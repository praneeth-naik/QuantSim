#!/usr/bin/env python3

import csv
import os
import random
import re
import statistics
import subprocess
from datetime import datetime
from pathlib import Path

QUBITS = 24
CHUNK_QUBITS = 16
REPEATS = 3

CONFIGURATIONS = [
    (target, slots)
    for target in (0, QUBITS - 1)
    for slots in (1, 2, 3, 4)
]

rng = random.Random(42)


def run(command):
    try:
        return subprocess.check_output(
            command,
            text=True,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as error:
        print(error.output, flush=True)
        raise


def metric(output, label):
    match = re.search(
        rf"^{re.escape(label)}:\s*([0-9]+(?:\.[0-9]+)?)\s*$",
        output,
        re.MULTILINE,
    )

    if match is None:
        raise RuntimeError(f"Missing metric: {label}\n{output}")

    return match.group(1)


def measure(target, slots, trial):
    arguments = [
        str(QUBITS),
        str(target),
        str(CHUNK_QUBITS),
    ]

    run(["./build/init_state", *arguments])

    state_path = Path("data/state.bin")

    if state_path.stat().st_size != (1 << QUBITS) * 16:
        raise RuntimeError("Unexpected initialized state size")

    # Flush initialization writes before launching the timed program.
    with state_path.open("r+b", buffering=0) as state:
        os.fsync(state.fileno())

    output = run([
        "./build/file_hadamard_direct",
        *arguments,
        str(slots),
    ])

    if "I/O mode: direct" not in output:
        raise RuntimeError("Expected the direct-I/O implementation")

    # Validation runs outside the processing interval.
    run(["./build/validate_state", *arguments])

    return {
        "qubits": QUBITS,
        "target": target,
        "gate_type": "local" if target == 0 else "global",
        "chunk_qubits": CHUNK_QUBITS,
        "slots": slots,
        "trial": trial,
        "io_mode": "direct",
        "host_optimization": "O3",
        "host_buffer_bytes": int(
            metric(output, "Pinned host buffer bytes")
        ),
        "device_buffer_bytes": int(
            metric(output, "Device buffer bytes")
        ),
        "setup_ms": float(metric(output, "Setup time (ms)")),
        "processing_ms": float(metric(output, "Processing time (ms)")), "storage": "Crucial X6 USB SSD",
        "filesystem": "exfat"
    }

external_mount = Path("/media/praneeth/Crucial X6")

if not os.path.ismount(external_mount):
    raise RuntimeError("External SSD is not mounted")

for folder in ("data", "results"):
    expected = (
        external_mount / "QuantSim-storage" / folder
    ).resolve()

    actual = Path(folder).resolve()

    if not Path(folder).is_dir() or actual != expected:
        raise RuntimeError(
            f"{folder} must point to external storage: {expected}"
        )

    print(f"{folder}: {actual}", flush=True)

print("Running warmups...", flush=True)

warmup_order = CONFIGURATIONS.copy()
rng.shuffle(warmup_order)

for target, slots in warmup_order:
    print(f"Warmup: target={target}, slots={slots}", flush=True)
    measure(target, slots, 0)

results_directory = Path("results")
results_directory.mkdir(exist_ok=True)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
result_path = results_directory / f"depth_pilot_{timestamp}.csv"

fields = [
    "qubits", "target", "gate_type", "chunk_qubits",
    "slots", "trial", "io_mode", "host_optimization",
    "host_buffer_bytes", "device_buffer_bytes",
    "setup_ms", "processing_ms", "storage", "filesystem",
]

rows = []

with result_path.open("w", newline="") as file:
    writer = csv.DictWriter(file, fieldnames=fields)
    writer.writeheader()

    for trial in range(1, REPEATS + 1):
        order = CONFIGURATIONS.copy()
        rng.shuffle(order)

        for target, slots in order:
            row = measure(target, slots, trial)

            rows.append(row)
            writer.writerow(row)
            file.flush()

            print(
                f"Trial {trial}: {row['gate_type']}, slots={slots}, "
                f"processing={row['processing_ms']:.3f} ms",
                flush=True,
            )

print("\nProcessing-time summary:")

for target in (0, QUBITS - 1):
    gate_type = "local" if target == 0 else "global"

    baseline = statistics.median(
        row["processing_ms"]
        for row in rows
        if row["target"] == target and row["slots"] == 1
    )

    for slots in (1, 2, 3, 4):
        times = [
            row["processing_ms"]
            for row in rows
            if row["target"] == target and row["slots"] == slots
        ]

        median = statistics.median(times)
        speedup = baseline / median if median > 0 else float("nan")

        print(
            f"{gate_type}, slots={slots}: "
            f"median={median:.3f} ms, "
            f"range={min(times):.3f}–{max(times):.3f} ms, "
            f"speedup={speedup:.2f}x"
        )

print(f"\nResults saved: {result_path}")