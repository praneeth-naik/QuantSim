import csv
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from validate_selector import (
    ROOT, MOUNT, STORAGE, RESULTS, processing_time
)

TEST_QUBITS = 26
TRIALS = 3
BUDGETS_MIB = (1, 2, 4, 8)
MiB = 1 << 20


def run(command, directory, budget):
    environment = os.environ.copy()
    environment["QUANTSIM_HOST_BUFFER_BUDGET_MIB"] = str(budget)
    environment["QUANTSIM_DEVICE_BUFFER_BUDGET_MIB"] = str(budget)

    result = subprocess.run(
        [str(value) for value in command],
        cwd=directory,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stdout)

    return result.stdout


def write_csv(path, rows):
    with open(path, "x", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    if len(sys.argv) != 2:
        raise RuntimeError(
            "Usage: python3 checks/validate_budget_selector.py "
            "<pipeline-model.csv>"
        )

    if not os.path.ismount(MOUNT):
        raise RuntimeError("External SSD is not mounted")

    if shutil.disk_usage(MOUNT).free < (2 << 30):
        raise RuntimeError("Need at least 2 GiB free on the external SSD")

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
    comparisons = {}

    for gate in ("local", "global"):
        for budget in BUDGETS_MIB:
            feasible = [
                row for row in model
                if row["gate_type"] == gate
                and int(row["buffer_bytes_per_side"]) <= budget * MiB
            ]

            if not feasible:
                raise RuntimeError(f"No feasible model choice: {gate}, {budget}")

            selected = min(
                feasible,
                key=lambda row: (
                    float(row["predicted_ms"]),
                    int(row["buffer_bytes_per_side"]),
                ),
            )

            fixed_candidates = [
                row for row in feasible
                if int(row["chunk_qubits"]) == 16
            ]

            fixed = (
                max(fixed_candidates, key=lambda row: int(row["slots"]))
                if fixed_candidates else None
            )

            role_keys = {}

            for role, row in (("model", selected), ("fixed", fixed)):
                if row is None:
                    role_keys[role] = None
                    continue

                key = (
                    gate,
                    int(row["chunk_qubits"]),
                    int(row["slots"]),
                )
                role_keys[role] = key

                if key not in tests:
                    tests[key] = {
                        "budget": budget,
                        "buffer_bytes": int(row["buffer_bytes_per_side"]),
                        "prediction": float(row["predicted_ms"]) * 4,
                    }

            comparisons[(gate, budget)] = role_keys

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = RESULTS / f"budget_holdout_runs_{stamp}.csv"
    summary_path = RESULTS / f"budget_holdout_summary_{stamp}.csv"

    fields = [
        "qubits", "target", "gate_type", "chunk_qubits", "slots",
        "enforced_budget_mib_per_side", "buffer_bytes_per_side",
        "trial", "processing_ms", "predicted_ms",
    ]

    measurements = defaultdict(list)
    rng = random.Random(45)

    print(f"Testing {len(tests)} distinct configurations", flush=True)

    with open(raw_path, "x", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()

        with tempfile.TemporaryDirectory(
            prefix="budget-holdout-", dir=STORAGE
        ) as temporary:
            directory = Path(temporary)
            (directory / "data").mkdir()

            for trial in range(TRIALS + 1):
                order = list(tests)
                rng.shuffle(order)

                for index, key in enumerate(order, 1):
                    gate, chunk_bits, slots = key
                    budget = tests[key]["budget"]
                    target = 0 if gate == "local" else TEST_QUBITS - 1
                    config = [TEST_QUBITS, target, chunk_bits]

                    run([executables["initialize"], *config], directory, budget)

                    state_path = directory / "data/state.bin"

                    if state_path.stat().st_size != (1 << TEST_QUBITS) * 16:
                        raise RuntimeError("Unexpected initialized state size")

                    with open(state_path, "r+b", buffering=0) as state:
                        os.fsync(state.fileno())

                    output = run(
                        [executables["simulate"], *config, slots],
                        directory,
                        budget,
                    )

                    lines = output.splitlines()
                    expected_bytes = tests[key]["buffer_bytes"]

                    for label in (
                        "Pinned host buffer bytes",
                        "Device buffer bytes",
                    ):
                        if f"{label}: {expected_bytes}" not in lines:
                            raise RuntimeError(f"Allocation mismatch:\n{output}")

                    run([executables["validate"], *config], directory, budget)
                    observed = processing_time(output)

                    if trial == 0:
                        print(
                            f"Warm-up {index}/{len(order)} complete",
                            flush=True,
                        )
                        continue

                    measurements[key].append(observed)

                    writer.writerow({
                        "qubits": TEST_QUBITS,
                        "target": target,
                        "gate_type": gate,
                        "chunk_qubits": chunk_bits,
                        "slots": slots,
                        "enforced_budget_mib_per_side": budget,
                        "buffer_bytes_per_side": expected_bytes,
                        "trial": trial,
                        "processing_ms": observed,
                        "predicted_ms": tests[key]["prediction"],
                    })
                    file.flush()

                if trial > 0:
                    print(
                        f"Trial {trial}/{TRIALS} complete; validations passed",
                        flush=True,
                    )

    summary = []
    print("\n26-qubit budget comparison:")

    for (gate, budget), roles in comparisons.items():
        selected_key = roles["model"]
        fixed_key = roles["fixed"]

        selected_time = statistics.median(measurements[selected_key])
        fixed_time = (
            statistics.median(measurements[fixed_key])
            if fixed_key is not None else None
        )

        difference = (
            100 * (selected_time / fixed_time - 1)
            if fixed_time is not None else None
        )

        chunk_mib = ((1 << selected_key[1]) * 16) / MiB

        print(
            f"{gate}, budget={budget} MiB/side: "
            f"model={chunk_mib:g} MiB/{selected_key[2]} slots, "
            f"{selected_time:.3f} ms"
        )

        if fixed_key is not None:
            print(
                f"  Fixed=1 MiB/{fixed_key[2]} slots, "
                f"{fixed_time:.3f} ms; "
                f"model vs fixed={difference:+.2f}%"
            )
        else:
            print("  Fixed 1 MiB chunks cannot fit this budget")

        summary.append({
            "qubits": TEST_QUBITS,
            "gate_type": gate,
            "budget_mib_per_side": budget,
            "model_chunk_mib": chunk_mib,
            "model_slots": selected_key[2],
            "model_median_ms": selected_time,
            "fixed_slots": fixed_key[2] if fixed_key is not None else None,
            "fixed_median_ms": fixed_time,
            "model_vs_fixed_percent": difference,
        })

    write_csv(summary_path, summary)

    print("\nPositive model-vs-fixed percentages mean the model is slower.")
    print(f"Runs saved: {raw_path}")
    print(f"Summary saved: {summary_path}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        raise SystemExit(str(error))