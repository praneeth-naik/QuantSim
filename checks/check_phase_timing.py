import csv
import os
import random
import re
import shutil
import statistics
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOUNT = Path("/media/praneeth/Crucial X6")
STORAGE = MOUNT / "QuantSim-storage"
RESULTS = STORAGE / "results"

QUBITS = 24
TRIALS = 3

CONFIGURATIONS = [
    (gate, target, chunk_bits)
    for chunk_bits in (14, 16, 20)
    for gate, target in (("local", 0), ("global", QUBITS - 1))
]

PROGRAMS = {
    "original": ROOT / "build/file_hadamard_direct",
    "diagnostic": ROOT / "build/file_hadamard_diagnostic",
}

METRICS = {
    "processing_ms": "Processing time (ms)",
    "read_ms": "Read phase wall time (ms)",
    "gpu_ms": "GPU phase wall time (ms)",
    "write_ms": "Write phase wall time (ms)",
    "other_ms": "Other processing time (ms)",
}


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


def extract(output, label):
    pattern = (
        rf"^{re.escape(label)}:\s*"
        r"([-+]?[0-9]+(?:\.[0-9]+)?)\s*$"
    )
    match = re.search(pattern, output, re.MULTILINE)

    if not match:
        raise RuntimeError(f"Missing metric {label}:\n{output}")

    return float(match.group(1))


def measure(variant, configuration, trial, directory):
    gate, target, chunk_bits = configuration
    config = [QUBITS, target, chunk_bits]

    run([ROOT / "build/init_state", *config], directory)

    state_path = directory / "data/state.bin"

    if state_path.stat().st_size != (1 << QUBITS) * 16:
        raise RuntimeError("Unexpected initialized state size")

    with open(state_path, "r+b", buffering=0) as state:
        os.fsync(state.fileno())

    output = run([PROGRAMS[variant], *config, 1], directory)

    run([ROOT / "build/validate_state", *config], directory)

    buffer_count = 2 if gate == "global" else 1
    jobs = (1 << QUBITS) // (1 << chunk_bits) // buffer_count

    row = {
        "variant": variant,
        "trial": trial,
        "qubits": QUBITS,
        "target": target,
        "gate_type": gate,
        "chunk_qubits": chunk_bits,
        "slots": 1,
        "jobs": jobs,
        "processing_ms": extract(output, METRICS["processing_ms"]),
    }

    if variant == "diagnostic":
        for key, label in METRICS.items():
            row[key] = extract(output, label)

        # Calculate within each run before taking medians.
        row["stage_sum_ms"] = (
            row["read_ms"] + row["gpu_ms"] + row["write_ms"]
        )

    return row


def main():
    if not os.path.ismount(MOUNT):
        raise RuntimeError("External SSD is not mounted")

    if shutil.disk_usage(MOUNT).free < (512 << 20):
        raise RuntimeError("Need at least 512 MiB free on the external SSD")

    for executable in (
        *PROGRAMS.values(),
        ROOT / "build/init_state",
        ROOT / "build/validate_state",
    ):
        if not executable.is_file():
            raise RuntimeError(f"Missing executable: {executable}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = RESULTS / f"phase_calibration_{stamp}.csv"

    fields = [
        "variant", "trial", "qubits", "target", "gate_type",
        "chunk_qubits", "slots", "jobs",
        *METRICS, "stage_sum_ms",
    ]

    groups = defaultdict(list)
    rng = random.Random(42)

    with tempfile.TemporaryDirectory(
        prefix="phase-calibration-", dir=STORAGE
    ) as temporary:
        directory = Path(temporary)
        (directory / "data").mkdir()

        with open(output_path, "x", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()

            for trial in range(TRIALS + 1):
                configurations = list(CONFIGURATIONS)
                rng.shuffle(configurations)

                for configuration in configurations:
                    variants = list(PROGRAMS)
                    rng.shuffle(variants)

                    for variant in variants:
                        row = measure(
                            variant, configuration, trial, directory
                        )

                        if trial > 0:
                            writer.writerow(row)
                            file.flush()

                            key = (
                                row["gate_type"],
                                row["chunk_qubits"],
                                variant,
                            )
                            groups[key].append(row)

                if trial == 0:
                    print("Warm-up complete", flush=True)
                else:
                    print(
                        f"Trial {trial}/{TRIALS} complete; "
                        "all validations passed",
                        flush=True,
                    )

    print("\nPhase-calibration summary:")

    for gate, target, chunk_bits in CONFIGURATIONS:
        original_rows = groups[(gate, chunk_bits, "original")]
        diagnostic_rows = groups[(gate, chunk_bits, "diagnostic")]

        original = statistics.median(
            row["processing_ms"] for row in original_rows
        )
        diagnostic = statistics.median(
            row["processing_ms"] for row in diagnostic_rows
        )

        chunk_mib = ((1 << chunk_bits) * 16) / (1 << 20)

        print(
            f"\n{gate}, chunk={chunk_mib:g} MiB: "
            f"original={original:.3f} ms, "
            f"diagnostic={diagnostic:.3f} ms, "
            f"difference={100 * (diagnostic / original - 1):+.2f}%"
        )

        for key in ("read_ms", "gpu_ms", "write_ms", "other_ms"):
            per_job = statistics.median(
                row[key] / row["jobs"] for row in diagnostic_rows
            )
            print(f"  {key}/job={per_job:.6f} ms")

    print(f"\nResults saved: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error))