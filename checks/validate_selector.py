import csv
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOUNT = Path("/media/praneeth/Crucial X6")
STORAGE = MOUNT / "QuantSim-storage"
RESULTS = STORAGE / "results"

TEST_QUBITS = 26
TRIALS = 3


def run(command, directory):
    result = subprocess.run(
        [str(value) for value in command],
        cwd=directory,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stdout)

    return result.stdout


def processing_time(output):
    match = re.search(
        r"^Processing time \(ms\):\s*([0-9.]+)\s*$",
        output,
        re.MULTILINE,
    )

    if not match:
        raise RuntimeError(f"Processing time missing:\n{output}")

    return float(match.group(1))


def load_model(path):
    resolved = Path(path).resolve()

    if os.path.commonpath(
        [str(resolved), str(RESULTS.resolve())]
    ) != str(RESULTS.resolve()):
        raise RuntimeError("Expected a model CSV on the external SSD")

    with open(resolved, newline="") as file:
        rows = list(csv.DictReader(file))

    if not rows:
        raise RuntimeError("Model CSV is empty")

    if {int(row["qubits"]) for row in rows} != {24}:
        raise RuntimeError("Expected the frozen 24-qubit development model")

    lookup = {}
    selections = {}
    cases = {}

    for row in rows:
        key = (
            row["gate_type"],
            int(row["chunk_qubits"]),
            int(row["slots"]),
        )
        lookup[key] = row

    for gate in ("local", "global"):
        candidates = [row for row in rows if row["gate_type"] == gate]

        if not candidates:
            raise RuntimeError(f"No model candidates for {gate}")

        # Selection uses predictions only.
        selected = min(
            candidates,
            key=lambda row: (
                float(row["predicted_ms"]),
                int(row["buffer_bytes_per_side"]),
            ),
        )

        selected_key = (
            gate,
            int(selected["chunk_qubits"]),
            int(selected["slots"]),
        )
        selections[gate] = selected_key

        role_cases = [
            ("model", selected_key),
            ("fixed", (gate, 16, 4)),
            ("serial", (gate, 16, 1)),
        ]

        for role, key in role_cases:
            if key not in lookup:
                raise RuntimeError(f"Missing model configuration: {key}")

            if key not in cases:
                cases[key] = {
                    "roles": set(),
                    "prediction": float(lookup[key]["predicted_ms"]) * 4,
                }

            cases[key]["roles"].add(role)

    return selections, cases


def main():
    if len(sys.argv) != 2:
        raise RuntimeError(
            "Usage: python3 checks/validate_selector.py <pipeline-model.csv>"
        )

    if not os.path.ismount(MOUNT):
        raise RuntimeError("External SSD is not mounted")

    if shutil.disk_usage(MOUNT).free < (2 << 30):
        raise RuntimeError("Need at least 2 GiB free on the external SSD")

    executables = {
        "initialize": ROOT / "build/init_state",
        "simulate": ROOT / "build/file_hadamard_direct",
        "validate": ROOT / "build/validate_state",
    }

    for executable in executables.values():
        if not executable.is_file():
            raise RuntimeError(f"Missing executable: {executable}")

    selections, cases = load_model(sys.argv[1])

    print("Frozen model choices:", flush=True)

    for gate, key in selections.items():
        _, chunk_bits, slots = key
        chunk_mib = ((1 << chunk_bits) * 16) / (1 << 20)
        print(
            f"  {gate}: {chunk_mib:g} MiB, {slots} slots",
            flush=True,
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = RESULTS / f"selector_holdout_{stamp}.csv"

    fields = [
        "qubits", "target", "gate_type", "chunk_qubits",
        "slots", "roles", "trial", "processing_ms",
        "predicted_ms", "signed_error_percent",
    ]

    measurements = defaultdict(list)
    rng = random.Random(44)

    with tempfile.TemporaryDirectory(
        prefix="selector-holdout-", dir=STORAGE
    ) as temporary:
        directory = Path(temporary)
        (directory / "data").mkdir()

        with open(output_path, "x", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()

            for trial in range(TRIALS + 1):
                order = list(cases)
                rng.shuffle(order)

                for key in order:
                    gate, chunk_bits, slots = key
                    target = 0 if gate == "local" else TEST_QUBITS - 1
                    config = [TEST_QUBITS, target, chunk_bits]

                    run([executables["initialize"], *config], directory)

                    state_path = directory / "data/state.bin"

                    if state_path.stat().st_size != (1 << TEST_QUBITS) * 16:
                        raise RuntimeError("Unexpected state file size")

                    with open(state_path, "r+b", buffering=0) as state:
                        os.fsync(state.fileno())

                    output = run(
                        [executables["simulate"], *config, slots],
                        directory,
                    )

                    run([executables["validate"], *config], directory)

                    observed = processing_time(output)

                    if trial == 0:
                        continue

                    predicted = cases[key]["prediction"]

                    writer.writerow({
                        "qubits": TEST_QUBITS,
                        "target": target,
                        "gate_type": gate,
                        "chunk_qubits": chunk_bits,
                        "slots": slots,
                        "roles": "|".join(sorted(cases[key]["roles"])),
                        "trial": trial,
                        "processing_ms": observed,
                        "predicted_ms": predicted,
                        "signed_error_percent":
                            100 * (predicted / observed - 1),
                    })
                    file.flush()
                    measurements[key].append(observed)

                print(
                    "Warm-up complete"
                    if trial == 0
                    else f"Trial {trial}/{TRIALS} complete; validations passed",
                    flush=True,
                )

    print("\n26-qubit processing-time comparison:")

    for gate in ("local", "global"):
        role_keys = {
            "model": selections[gate],
            "fixed": (gate, 16, 4),
            "serial": (gate, 16, 1),
        }

        medians = {}

        for role, key in role_keys.items():
            times = measurements[key]
            observed = statistics.median(times)
            predicted = cases[key]["prediction"]
            medians[role] = observed

            print(
                f"{gate}, {role}: median={observed:.3f} ms, "
                f"range={min(times):.3f}–{max(times):.3f} ms, "
                f"prediction error={100 * (predicted / observed - 1):+.2f}%"
            )

        difference = 100 * (
            medians["model"] / medians["fixed"] - 1
        )

        print(
            f"  Model vs fixed setting: {difference:+.2f}% "
            "(positive means slower)"
        )
        print(
            "  Speedup over the 1 MiB/one-slot reference: "
            f"model={medians['serial'] / medians['model']:.2f}x, "
            f"fixed={medians['serial'] / medians['fixed']:.2f}x"
        )

    print(f"\nResults saved: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        raise SystemExit(str(error))