import csv
import os
import re
import shutil
import statistics
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOUNT = Path("/media/praneeth/Crucial X6")
STORAGE = MOUNT / "QuantSim-storage"
RESULTS = STORAGE / "results"

QUBITS = 24
TARGET = 0
CHUNK_QUBITS = 14
JOBS = 1 << (QUBITS - CHUNK_QUBITS)

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


def main():
    if not os.path.ismount(MOUNT):
        raise RuntimeError("External SSD is not mounted")

    if shutil.disk_usage(MOUNT).free < (512 << 20):
        raise RuntimeError("Need at least 512 MiB free on the external SSD")

    required = [
        *PROGRAMS.values(),
        ROOT / "build/init_state",
        ROOT / "build/validate_state",
    ]

    for executable in required:
        if not executable.is_file():
            raise RuntimeError(f"Missing executable: {executable}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = RESULTS / f"phase_timing_{stamp}.csv"

    fields = [
        "variant", "trial", "qubits", "target", "chunk_qubits", "slots",
        *METRICS,
    ]
    measurements = {"original": [], "diagnostic": []}

    # This directory is separate from the project's existing data directory.
    with tempfile.TemporaryDirectory(
        prefix="phase-check-", dir=STORAGE
    ) as temporary:
        directory = Path(temporary)
        (directory / "data").mkdir()

        with open(output_path, "x", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()

            # Trial 0 warms up both builds; trials 1–3 are recorded.
            for trial in range(4):
                order = (
                    ["original", "diagnostic"]
                    if trial % 2 == 0
                    else ["diagnostic", "original"]
                )

                for variant in order:
                    config = [QUBITS, TARGET, CHUNK_QUBITS]

                    run(
                        [ROOT / "build/init_state", *config],
                        directory,
                    )

                    with open(
                        directory / "data/state.bin", "r+b", buffering=0
                    ) as state:
                        os.fsync(state.fileno())

                    output = run(
                        [PROGRAMS[variant], *config, 1],
                        directory,
                    )

                    run(
                        [ROOT / "build/validate_state", *config],
                        directory,
                    )

                    row = {
                        "variant": variant,
                        "trial": trial,
                        "qubits": QUBITS,
                        "target": TARGET,
                        "chunk_qubits": CHUNK_QUBITS,
                        "slots": 1,
                        "processing_ms": extract(
                            output, METRICS["processing_ms"]
                        ),
                    }

                    if variant == "diagnostic":
                        for key, label in METRICS.items():
                            row[key] = extract(output, label)

                    if trial > 0:
                        writer.writerow(row)
                        file.flush()
                        measurements[variant].append(row)

                    print(
                        f"{variant}, trial={trial}: "
                        f"{row['processing_ms']:.3f} ms, validation passed"
                    )

    original = statistics.median(
        row["processing_ms"] for row in measurements["original"]
    )
    diagnostic = statistics.median(
        row["processing_ms"] for row in measurements["diagnostic"]
    )

    print(f"\nOriginal median: {original:.3f} ms")
    print(f"Diagnostic median: {diagnostic:.3f} ms")
    print(
        "Diagnostic vs original median: "
        f"{100 * (diagnostic / original - 1):+.2f}%"
    )

    for key in ("read_ms", "gpu_ms", "write_ms", "other_ms"):
        value = statistics.median(
            row[key] for row in measurements["diagnostic"]
        )
        print(
            f"{key}: median total={value:.3f} ms, "
            f"per job={value / JOBS:.6f} ms"
        )

    print(f"Results saved: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error))