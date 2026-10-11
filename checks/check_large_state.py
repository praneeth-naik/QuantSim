#!/usr/bin/env python3

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

QUBITS = 30
TARGET = 29
CHUNK_QUBITS = 16
SLOTS = 4
STATE_BYTES = (1 << QUBITS) * 16

external_mount = Path("/media/praneeth/Crucial X6")

if not os.path.ismount(external_mount):
    raise RuntimeError("External SSD is not mounted")

for folder in ("data", "results"):
    expected = (
        external_mount / "QuantSim-storage" / folder
    ).resolve()

    if not Path(folder).is_dir() or Path(folder).resolve() != expected:
        raise RuntimeError(f"{folder} must point to {expected}")

if shutil.disk_usage("data").free < STATE_BYTES:
    raise RuntimeError("External SSD needs at least 16 GiB free")

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_path = Path("results") / f"large_state_{timestamp}.txt"

arguments = [
    str(QUBITS),
    str(TARGET),
    str(CHUNK_QUBITS),
]

with log_path.open("x") as log:
    def run(command):
        message = "Running: " + " ".join(command)
        print(message, flush=True)
        log.write(message + "\n")
        log.flush()

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        print(result.stdout, end="", flush=True)
        log.write(result.stdout)
        log.flush()
        result.check_returncode()

    run(["./build/init_state", *arguments])

    state_path = Path("data/state.bin")

    if state_path.stat().st_size != STATE_BYTES:
        raise RuntimeError("Unexpected state file size")

    print("Flushing the initialized 16 GiB state...", flush=True)

    with state_path.open("r+b", buffering=0) as state:
        os.fsync(state.fileno())

    run([
        "./build/file_hadamard_direct",
        *arguments,
        str(SLOTS),
    ])

    run(["./build/validate_state", *arguments])

print(f"Results saved: {log_path}")