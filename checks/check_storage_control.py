import csv
import os
import random
import statistics
import struct
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from validate_budget_selector import (
    ROOT, MOUNT, STORAGE, RESULTS,
    run, processing_time,
)

QUBITS = 24
CHUNK_QUBITS = 16
TRIALS = 3

PROGRAMS = {
    "gpu": ROOT / "build/file_hadamard_direct",
    "control": ROOT / "build/file_hadamard_storage_control",
}


def verify_identity(path):
    block_bytes = 1 << 20
    zeros = bytes(block_bytes)
    expected_first = struct.pack("=dd", 1.0, 0.0) + zeros[16:]

    if path.stat().st_size != (1 << QUBITS) * 16:
        raise RuntimeError("Unexpected control state size")

    with open(path, "rb") as file:
        if file.read(block_bytes) != expected_first:
            raise RuntimeError("Control changed the initial state")

        while True:
            block = file.read(block_bytes)

            if not block:
                break

            if block != zeros[:len(block)]:
                raise RuntimeError("Control changed state data")


def main():
    if len(sys.argv) != 2:
        raise RuntimeError(
            "Usage: python3 checks/check_storage_control.py "
            "<storage-depth.csv>"
        )

    if not os.path.ismount(MOUNT):
        raise RuntimeError("External SSD is not mounted")

    for executable in (
        *PROGRAMS.values(),
        ROOT / "build/init_state",
        ROOT / "build/validate_state",
    ):
        if not executable.is_file():
            raise RuntimeError(f"Missing executable: {executable}")

    input_path = Path(sys.argv[1]).resolve()

    if os.path.commonpath(
        [str(input_path), str(RESULTS.resolve())]
    ) != str(RESULTS.resolve()):
        raise RuntimeError("Expected storage results on the external SSD")

    standalone = defaultdict(list)

    with open(input_path, newline="") as file:
        for row in csv.DictReader(file):
            if int(row["chunk_qubits"]) == CHUNK_QUBITS:
                standalone[
                    (row["gate_type"], int(row["slots"]))
                ].append(float(row["processing_ms"]))

    cases = [
        (gate, target, slots, variant)
        for gate, target in (("local", 0), ("global", QUBITS - 1))
        for slots in (1, 4)
        for variant in PROGRAMS
    ]

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = RESULTS / f"storage_control_{stamp}.csv"

    fields = [
        "qubits", "target", "gate_type", "chunk_qubits",
        "slots", "variant", "trial", "processing_ms",
    ]

    measurements = defaultdict(list)
    rng = random.Random(47)

    with open(output_path, "x", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()

        with tempfile.TemporaryDirectory(
            prefix="storage-control-", dir=STORAGE
        ) as temporary:
            directory = Path(temporary)
            (directory / "data").mkdir()

            for trial in range(TRIALS + 1):
                order = list(cases)
                rng.shuffle(order)

                for gate, target, slots, variant in order:
                    config = [QUBITS, target, CHUNK_QUBITS]

                    run(
                        [ROOT / "build/init_state", *config],
                        directory,
                        8,
                    )

                    state_path = directory / "data/state.bin"

                    with open(state_path, "r+b", buffering=0) as state:
                        os.fsync(state.fileno())

                    output = run(
                        [PROGRAMS[variant], *config, slots],
                        directory,
                        8,
                    )

                    if variant == "control":
                        verify_identity(state_path)
                    else:
                        run(
                            [ROOT / "build/validate_state", *config],
                            directory,
                            8,
                        )

                    elapsed = processing_time(output)

                    if trial == 0:
                        continue

                    measurements[(gate, slots, variant)].append(elapsed)

                    writer.writerow({
                        "qubits": QUBITS,
                        "target": target,
                        "gate_type": gate,
                        "chunk_qubits": CHUNK_QUBITS,
                        "slots": slots,
                        "variant": variant,
                        "trial": trial,
                        "processing_ms": elapsed,
                    })
                    file.flush()

                print(
                    "Warm-up complete"
                    if trial == 0
                    else f"Trial {trial}/{TRIALS} complete; validations passed",
                    flush=True,
                )

    print("\nMatched storage-control summary:")

    for gate in ("local", "global"):
        for slots in (1, 4):
            for variant in ("control", "gpu"):
                values = measurements[(gate, slots, variant)]

                print(
                    f"{gate}, slots={slots}, {variant}: "
                    f"median={statistics.median(values):.3f} ms, "
                    f"range={min(values):.3f}–{max(values):.3f} ms"
                )

        print("  Four-slot/one-slot time ratios:")

        for label, groups in (
            (
                "standalone storage",
                {
                    slots: standalone[(gate, slots)]
                    for slots in (1, 4)
                },
            ),
            (
                "matched control",
                {
                    slots: measurements[(gate, slots, "control")]
                    for slots in (1, 4)
                },
            ),
            (
                "full GPU pipeline",
                {
                    slots: measurements[(gate, slots, "gpu")]
                    for slots in (1, 4)
                },
            ),
        ):
            if not groups[1] or not groups[4]:
                raise RuntimeError(f"Missing measurements for {label}")

            ratio = (
                statistics.median(groups[4])
                / statistics.median(groups[1])
            )
            print(f"    {label}: {ratio:.4f}")

    print(f"Results saved: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        raise SystemExit(str(error))