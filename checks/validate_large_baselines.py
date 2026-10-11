import csv
import os
import random
import shutil
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from validate_budget_selector import (
    ROOT, MOUNT, STORAGE, RESULTS,
    run, processing_time, write_csv,
)

QUBITS = 28
TRIALS = 3
MiB = 1 << 20
SCENARIOS = (("local", 4), ("global", 8))


def key_for(row):
    return (
        row["gate_type"],
        int(row["chunk_qubits"]),
        int(row["slots"]),
    )


def main():
    if len(sys.argv) != 2:
        raise RuntimeError(
            "Usage: python3 checks/validate_large_baselines.py "
            "<pipeline-model.csv>"
        )

    if not os.path.ismount(MOUNT):
        raise RuntimeError("External SSD is not mounted")

    state_bytes = (1 << QUBITS) * 16

    if shutil.disk_usage(MOUNT).free < 2 * state_bytes:
        raise RuntimeError("Need at least 8 GiB free on the external SSD")

    model_path = Path(sys.argv[1]).resolve()

    if os.path.commonpath(
        [str(model_path), str(RESULTS.resolve())]
    ) != str(RESULTS.resolve()):
        raise RuntimeError("Expected a model CSV on the external SSD")

    with open(model_path, newline="") as file:
        model = list(csv.DictReader(file))

    if not model or {int(row["qubits"]) for row in model} != {24}:
        raise RuntimeError("Expected the frozen 24-qubit model")

    executables = {
        "initialize": ROOT / "build/init_state",
        "simulate": ROOT / "build/file_hadamard_direct",
        "validate": ROOT / "build/validate_state",
    }

    for executable in executables.values():
        if not executable.is_file():
            raise RuntimeError(f"Missing executable: {executable}")

    tests = {}
    choices = {}

    for gate, budget in SCENARIOS:
        feasible = [
            row for row in model
            if row["gate_type"] == gate
            and int(row["buffer_bytes_per_side"]) <= budget * MiB
        ]

        if not feasible:
            raise RuntimeError(f"No feasible choices for {gate}")

        policies = {
            "model": min(
                feasible,
                key=lambda row: (
                    float(row["predicted_ms"]),
                    int(row["buffer_bytes_per_side"]),
                ),
            ),
            "small_chunk": min(
                feasible,
                key=lambda row: (
                    int(row["chunk_qubits"]),
                    -int(row["slots"]),
                ),
            ),
            "depth_first": max(
                [row for row in feasible if int(row["chunk_qubits"]) <= 16],
                key=lambda row: (
                    int(row["slots"]),
                    int(row["chunk_qubits"]),
                ),
            ),
            "fixed": max(
                [row for row in feasible if int(row["chunk_qubits"]) == 16],
                key=lambda row: int(row["slots"]),
            ),
        }

        for policy, row in policies.items():
            key = key_for(row)
            choices[(gate, budget, policy)] = key

            if key not in tests:
                tests[key] = {
                    "budget": budget,
                    "roles": set(),
                    "prediction": float(row["predicted_ms"]) * 16,
                }

            tests[key]["roles"].add(policy)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = RESULTS / f"large_baseline_runs_{stamp}.csv"
    summary_path = RESULTS / f"large_baseline_summary_{stamp}.csv"

    fields = [
        "qubits", "target", "gate_type", "chunk_qubits", "slots",
        "budget_mib_per_side", "roles", "trial",
        "processing_ms", "gate_wall_ms", "predicted_ms",
    ]

    measurements = defaultdict(list)
    rng = random.Random(46)

    print(
        f"Testing {len(tests)} distinct configurations on a 4 GiB state",
        flush=True,
    )

    with open(raw_path, "x", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()

        with tempfile.TemporaryDirectory(
            prefix="large-baseline-", dir=STORAGE
        ) as temporary:
            directory = Path(temporary)
            (directory / "data").mkdir()

            for trial in range(TRIALS + 1):
                order = list(tests)
                rng.shuffle(order)

                for index, key in enumerate(order, 1):
                    gate, chunk_bits, slots = key
                    budget = tests[key]["budget"]
                    target = 0 if gate == "local" else QUBITS - 1
                    config = [QUBITS, target, chunk_bits]

                    run([executables["initialize"], *config], directory, budget)

                    state_path = directory / "data/state.bin"

                    if state_path.stat().st_size != state_bytes:
                        raise RuntimeError("Unexpected state size")

                    with open(state_path, "r+b", buffering=0) as state:
                        os.fsync(state.fileno())

                    start = time.perf_counter()

                    output = run(
                        [executables["simulate"], *config, slots],
                        directory,
                        budget,
                    )

                    wall_ms = (time.perf_counter() - start) * 1000

                    run([executables["validate"], *config], directory, budget)

                    row = {
                        "qubits": QUBITS,
                        "target": target,
                        "gate_type": gate,
                        "chunk_qubits": chunk_bits,
                        "slots": slots,
                        "budget_mib_per_side": budget,
                        "roles": "|".join(sorted(tests[key]["roles"])),
                        "trial": trial,
                        "processing_ms": processing_time(output),
                        "gate_wall_ms": wall_ms,
                        "predicted_ms": tests[key]["prediction"],
                    }

                    if trial == 0:
                        print(
                            f"Warm-up {index}/{len(order)} complete",
                            flush=True,
                        )
                        continue

                    measurements[key].append(row)
                    writer.writerow(row)
                    file.flush()

                if trial > 0:
                    print(
                        f"Trial {trial}/{TRIALS} complete; validations passed",
                        flush=True,
                    )

    summary = []
    print("\n28-qubit baseline comparison:")

    for gate, budget in SCENARIOS:
        model_key = choices[(gate, budget, "model")]
        model_time = statistics.median(
            row["processing_ms"] for row in measurements[model_key]
        )

        print(f"\n{gate}, budget={budget} MiB/side:")

        for policy in ("model", "small_chunk", "depth_first", "fixed"):
            key = choices[(gate, budget, policy)]
            samples = measurements[key]

            processing = statistics.median(
                row["processing_ms"] for row in samples
            )
            wall = statistics.median(
                row["gate_wall_ms"] for row in samples
            )

            chunk_mib = ((1 << key[1]) * 16) / MiB

            print(
                f"  {policy}: {chunk_mib:g} MiB/{key[2]} slots, "
                f"processing={processing:.3f} ms, "
                f"gate wall time={wall:.3f} ms"
            )

            summary.append({
                "qubits": QUBITS,
                "gate_type": gate,
                "budget_mib_per_side": budget,
                "policy": policy,
                "chunk_mib": chunk_mib,
                "slots": key[2],
                "median_processing_ms": processing,
                "median_gate_wall_ms": wall,
            })

        depth_key = choices[(gate, budget, "depth_first")]
        depth_time = statistics.median(
            row["processing_ms"] for row in measurements[depth_key]
        )

        print(
            "  Model vs depth-first processing time: "
            f"{100 * (model_time / depth_time - 1):+.2f}% "
            "(positive means model is slower)"
        )

    write_csv(summary_path, summary)

    print(f"\nRuns saved: {raw_path}")
    print(f"Summary saved: {summary_path}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        raise SystemExit(str(error))