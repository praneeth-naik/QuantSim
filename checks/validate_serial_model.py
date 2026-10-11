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

CONFIGURATIONS = [
    (gate, target, chunk_bits)
    for chunk_bits in (14, 16, 20)
    for gate, target in (
        ("local", 0),
        ("global", TEST_QUBITS - 1),
    )
]


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


def load_costs(path):
    resolved = Path(path).resolve()
    results_directory = RESULTS.resolve()

    if os.path.commonpath(
        [str(resolved), str(results_directory)]
    ) != str(results_directory):
        raise RuntimeError("Calibration must be in external SSD results")

    groups = defaultdict(list)

    with open(resolved, newline="") as file:
        for row in csv.DictReader(file):
            if int(row["slots"]) != 1 or int(row["qubits"]) != 24:
                raise RuntimeError("Expected the 24-qubit, one-slot calibration")

            key = (
                row["gate_type"],
                int(row["chunk_qubits"]),
                row["variant"],
            )
            groups[key].append(row)

    costs = {}

    for gate, target, chunk_bits in CONFIGURATIONS:
        diagnostic = groups[(gate, chunk_bits, "diagnostic")]
        original = groups[(gate, chunk_bits, "original")]

        if len(diagnostic) < 3 or len(original) < 3:
            raise RuntimeError(f"Incomplete calibration: {gate}, {chunk_bits}")

        # Sum phases within each trial before taking the median.
        phase_cost = statistics.median(
            (
                float(row["read_ms"])
                + float(row["gpu_ms"])
                + float(row["write_ms"])
                + float(row["other_ms"])
            ) / int(row["jobs"])
            for row in diagnostic
        )

        baseline_cost = statistics.median(
            float(row["processing_ms"]) / int(row["jobs"])
            for row in original
        )

        costs[(gate, chunk_bits)] = (phase_cost, baseline_cost)

    return costs


def main():
    if len(sys.argv) != 2:
        raise RuntimeError(
            "Usage: python3 checks/validate_serial_model.py <calibration.csv>"
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

    costs = load_costs(sys.argv[1])
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = RESULTS / f"serial_holdout_{stamp}.csv"

    fields = [
        "qubits", "target", "gate_type", "chunk_qubits",
        "slots", "jobs", "trial", "processing_ms",
        "phase_prediction_ms", "baseline_prediction_ms",
        "phase_error_percent", "baseline_error_percent",
    ]

    measurements = defaultdict(list)
    rng = random.Random(43)

    with tempfile.TemporaryDirectory(
        prefix="serial-holdout-", dir=STORAGE
    ) as temporary:
        directory = Path(temporary)
        (directory / "data").mkdir()

        with open(output_path, "x", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()

            # Trial 0 warms up each configuration.
            for trial in range(TRIALS + 1):
                configurations = list(CONFIGURATIONS)
                rng.shuffle(configurations)

                for gate, target, chunk_bits in configurations:
                    config = [TEST_QUBITS, target, chunk_bits]

                    run([executables["initialize"], *config], directory)

                    state_path = directory / "data/state.bin"

                    if state_path.stat().st_size != (1 << TEST_QUBITS) * 16:
                        raise RuntimeError("Unexpected initialized state size")

                    with open(state_path, "r+b", buffering=0) as state:
                        os.fsync(state.fileno())

                    output = run(
                        [executables["simulate"], *config, 1],
                        directory,
                    )

                    run([executables["validate"], *config], directory)

                    observed = processing_time(output)

                    if trial == 0:
                        continue

                    buffer_count = 2 if gate == "global" else 1
                    jobs = (
                        (1 << TEST_QUBITS)
                        // (1 << chunk_bits)
                        // buffer_count
                    )

                    phase_cost, baseline_cost = costs[(gate, chunk_bits)]
                    phase_prediction = jobs * phase_cost
                    baseline_prediction = jobs * baseline_cost

                    writer.writerow({
                        "qubits": TEST_QUBITS,
                        "target": target,
                        "gate_type": gate,
                        "chunk_qubits": chunk_bits,
                        "slots": 1,
                        "jobs": jobs,
                        "trial": trial,
                        "processing_ms": observed,
                        "phase_prediction_ms": phase_prediction,
                        "baseline_prediction_ms": baseline_prediction,
                        "phase_error_percent":
                            100 * (phase_prediction / observed - 1),
                        "baseline_error_percent":
                            100 * (baseline_prediction / observed - 1),
                    })
                    file.flush()

                    measurements[(gate, chunk_bits)].append(observed)

                print(
                    "Warm-up complete"
                    if trial == 0
                    else f"Trial {trial}/{TRIALS} complete; validations passed",
                    flush=True,
                )

    phase_errors = []
    baseline_errors = []

    print("\nUnseen 26-qubit state summary:")

    for gate, target, chunk_bits in CONFIGURATIONS:
        times = measurements[(gate, chunk_bits)]
        observed = statistics.median(times)

        buffer_count = 2 if gate == "global" else 1
        jobs = (1 << TEST_QUBITS) // (1 << chunk_bits) // buffer_count
        phase_cost, baseline_cost = costs[(gate, chunk_bits)]

        phase_prediction = jobs * phase_cost
        baseline_prediction = jobs * baseline_cost

        phase_error = 100 * (phase_prediction / observed - 1)
        baseline_error = 100 * (baseline_prediction / observed - 1)

        phase_errors.append(abs(phase_error))
        baseline_errors.append(abs(baseline_error))

        chunk_mib = ((1 << chunk_bits) * 16) / (1 << 20)

        print(
            f"{gate}, chunk={chunk_mib:g} MiB: "
            f"observed={observed:.3f} ms "
            f"[{min(times):.3f}–{max(times):.3f}], "
            f"phase prediction={phase_prediction:.3f} ms "
            f"({phase_error:+.2f}%), "
            f"baseline={baseline_prediction:.3f} ms "
            f"({baseline_error:+.2f}%)"
        )

    print(
        "\nPhase-model mean absolute percentage error: "
        f"{statistics.mean(phase_errors):.2f}%"
    )
    print(
        "Scaling-baseline mean absolute percentage error: "
        f"{statistics.mean(baseline_errors):.2f}%"
    )
    print(f"Results saved: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        raise SystemExit(str(error))