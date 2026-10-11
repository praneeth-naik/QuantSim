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
CHUNK_BITS = (14, 16, 20)
REPEATS = 5

CONFIGURATIONS = [
    (chunk_bits, target, slots)
    for chunk_bits in CHUNK_BITS
    for target in (0, QUBITS - 1)
    for slots in (1, 2, 3, 4)
]

rng = random.Random(42)

external_mount = Path("/media/praneeth/Crucial X6")

if not os.path.ismount(external_mount):
    raise RuntimeError("External SSD is not mounted")

for folder in ("data", "results"):
    expected = (
        external_mount / "QuantSim-storage" / folder
    ).resolve()

    if not Path(folder).is_dir() or Path(folder).resolve() != expected:
        raise RuntimeError(f"{folder} must point to {expected}")


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


def measure(chunk_bits, target, slots, trial):
    arguments = [str(QUBITS), str(target), str(chunk_bits)]

    run(["./build/init_state", *arguments])

    state_path = Path("data/state.bin")

    if state_path.stat().st_size != (1 << QUBITS) * 16:
        raise RuntimeError("Unexpected initialized state size")

    with state_path.open("r+b", buffering=0) as state:
        os.fsync(state.fileno())

    output = run([
        "./build/file_hadamard_direct",
        *arguments,
        str(slots),
    ])

    if "I/O mode: direct" not in output:
        raise RuntimeError("Expected the direct-I/O implementation")

    run(["./build/validate_state", *arguments])

    return {
        "qubits": QUBITS,
        "target": target,
        "gate_type": "local" if target == 0 else "global",
        "chunk_qubits": chunk_bits,
        "chunk_bytes": (1 << chunk_bits) * 16,
        "slots": slots,
        "trial": trial,
        "io_mode": "direct",
        "host_optimization": "O3",
        "storage": "Crucial X6 USB SSD",
        "filesystem": "exfat",
        "host_buffer_bytes": int(
            metric(output, "Pinned host buffer bytes")
        ),
        "device_buffer_bytes": int(
            metric(output, "Device buffer bytes")
        ),
        "setup_ms": float(metric(output, "Setup time (ms)")),
        "processing_ms": float(metric(output, "Processing time (ms)")),
    }


print("Running warmups...", flush=True)

order = CONFIGURATIONS.copy()
rng.shuffle(order)

for chunk_bits, target, slots in order:
    print(
        f"Warmup: chunk_bits={chunk_bits}, "
        f"target={target}, slots={slots}",
        flush=True,
    )
    measure(chunk_bits, target, slots, 0)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
result_path = Path("results") / f"chunk_depth_{timestamp}.csv"

rows = []

with result_path.open("x", newline="") as file:
    writer = None

    for trial in range(1, REPEATS + 1):
        order = CONFIGURATIONS.copy()
        rng.shuffle(order)

        for chunk_bits, target, slots in order:
            row = measure(chunk_bits, target, slots, trial)

            if writer is None:
                writer = csv.DictWriter(
                    file, fieldnames=list(row.keys())
                )
                writer.writeheader()

            writer.writerow(row)
            file.flush()
            rows.append(row)

            print(
                f"Trial {trial}: {row['gate_type']}, "
                f"chunk_bits={chunk_bits}, slots={slots}, "
                f"processing={row['processing_ms']:.3f} ms",
                flush=True,
            )

medians = {}

print("\nProcessing-time summary:")

for chunk_bits, target, slots in CONFIGURATIONS:
    times = [
        row["processing_ms"]
        for row in rows
        if row["chunk_qubits"] == chunk_bits
        and row["target"] == target
        and row["slots"] == slots
    ]

    median = statistics.median(times)
    medians[(chunk_bits, target, slots)] = median

    gate_type = "local" if target == 0 else "global"
    chunk_mib = ((1 << chunk_bits) * 16) / (1 << 20)

    print(
        f"{gate_type}, chunk={chunk_mib:g} MiB, slots={slots}: "
        f"median={median:.3f} ms, "
        f"range={min(times):.3f}–{max(times):.3f} ms"
    )

print("\nFastest measured configuration per gate type:")

for target in (0, QUBITS - 1):
    candidates = [
        configuration
        for configuration in CONFIGURATIONS
        if configuration[1] == target
    ]

    best = min(candidates, key=lambda configuration: medians[configuration])
    chunk_bits, _, slots = best

    gate_type = "local" if target == 0 else "global"
    chunk_mib = ((1 << chunk_bits) * 16) / (1 << 20)

    print(
        f"{gate_type}: chunk={chunk_mib:g} MiB, slots={slots}, "
        f"median={medians[best]:.3f} ms"
    )

print(f"\nResults saved: {result_path}")