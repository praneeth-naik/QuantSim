import csv
import os
import random
import shutil
import tempfile
import time
from datetime import datetime

from check_storage_control import verify_identity
from validate_budget_selector import (
    ROOT, MOUNT, STORAGE, RESULTS, run, processing_time
)

QUBITS = 24
TRIALS = 3
BUDGET_MIB = 128

PROGRAMS = {
    "control": ROOT / "build/file_hadamard_storage_control",
    "gpu": ROOT / "build/file_hadamard_direct",
}


def main():
    if not os.path.ismount(MOUNT):
        raise RuntimeError("External SSD is not mounted")

    storage = STORAGE.resolve()
    results = RESULTS.resolve()

    storage.relative_to(MOUNT.resolve())
    results.relative_to(storage)

    if shutil.disk_usage(storage).free < 2 * 1024**3:
        raise RuntimeError("Need at least 2 GiB free on the external SSD")

    for executable in [
        ROOT / "build/init_state",
        ROOT / "build/validate_state",
        *PROGRAMS.values(),
    ]:
        if not executable.is_file():
            raise RuntimeError(f"Missing executable: {executable}")

    cases = [
        (gate, target, chunk, slots)
        for gate, target in [("local", 0), ("global", QUBITS - 1)]
        for chunk in [14, 16, 20]
        for slots in [1, 2, 3, 4]
    ]

    fields = [
        "qubits", "target", "gate_type", "chunk_qubits",
        "slots", "variant", "trial", "buffer_bytes_per_side",
        "processing_ms", "gate_wall_ms",
    ]

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = results / f"matched_calibration_{stamp}.csv"
    rng = random.Random(48)

    with tempfile.TemporaryDirectory(
        prefix="matched-calibration-", dir=storage
    ) as temporary:
        from pathlib import Path
        directory = Path(temporary)
        (directory / "data").mkdir()
        state = directory / "data/state.bin"

        with output_path.open("x", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()

            # Round -1 is warm-up and is excluded from the CSV.
            for trial in range(-1, TRIALS):
                ordered = cases.copy()
                rng.shuffle(ordered)

                for index, (gate, target, chunk, slots) in enumerate(
                    ordered, start=1
                ):
                    variants = list(PROGRAMS)
                    rng.shuffle(variants)

                    for variant in variants:
                        run([
                            str(ROOT / "build/init_state"),
                            str(QUBITS), str(target), str(chunk),
                        ], directory, BUDGET_MIB)

                        with state.open("r+b") as initialized:
                            os.fsync(initialized.fileno())

                        start = time.perf_counter()
                        text = run([
                            str(PROGRAMS[variant]),
                            str(QUBITS), str(target),
                            str(chunk), str(slots),
                        ], directory, BUDGET_MIB)
                        wall_ms = (time.perf_counter() - start) * 1000

                        if variant == "control":
                            verify_identity(state)
                        else:
                            run([
                                str(ROOT / "build/validate_state"),
                                str(QUBITS), str(target), str(chunk),
                            ], directory, BUDGET_MIB)

                        if trial >= 0:
                            buffers = 2 if gate == "global" else 1
                            writer.writerow({
                                "qubits": QUBITS,
                                "target": target,
                                "gate_type": gate,
                                "chunk_qubits": chunk,
                                "slots": slots,
                                "variant": variant,
                                "trial": trial,
                                "buffer_bytes_per_side":
                                    (1 << chunk) * 16 * slots * buffers,
                                "processing_ms": processing_time(text),
                                "gate_wall_ms": wall_ms,
                            })
                            output.flush()

                    label = (
                        "Warm-up" if trial == -1
                        else f"Trial {trial + 1}/{TRIALS}"
                    )
                    print(
                        f"{label}: configuration {index}/{len(cases)} "
                        "complete; validations passed",
                        flush=True,
                    )

    print(f"Results saved: {output_path}")


if __name__ == "__main__":
    main()