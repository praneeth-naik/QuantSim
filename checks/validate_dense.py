#!/usr/bin/env python3

import math
import random
import struct
import subprocess
from pathlib import Path
import sys

QUBITS = 6
CHUNK_QUBITS = 2
COUNT = 1 << QUBITS
TOLERANCE = 1e-12
EXECUTABLE = (
    sys.argv[1]
    if len(sys.argv) > 1
    else "./build/file_hadamard_uring"
)

state_path = Path("data/state.bin")
state_path.parent.mkdir(exist_ok=True)

# Generate a repeatable, normalized complex state.
rng = random.Random(42)
initial = [
    complex(rng.uniform(-1, 1), rng.uniform(-1, 1))
    for _ in range(COUNT)
]

length = math.sqrt(sum(abs(value) ** 2 for value in initial))
initial = [value / length for value in initial]


def write_state(values):
    with state_path.open("wb") as file:
        for value in values:
            file.write(struct.pack("=dd", value.real, value.imag))


def read_state():
    raw = state_path.read_bytes()

    if len(raw) != COUNT * 16:
        raise SystemExit("Failed: unexpected state file size")

    return [
        complex(real, imag)
        for real, imag in struct.iter_unpack("=dd", raw)
    ]


for target in range(QUBITS):
    # Each test starts from the same input.
    write_state(initial)

    subprocess.run(
        [
            EXECUTABLE,
            str(QUBITS),
            str(target),
            str(CHUNK_QUBITS),
        ],
        check=True,
    )

    actual = read_state()
    mask = 1 << target
    scale = 1.0 / math.sqrt(2.0)

    # Independent reference: compute each output directly from
    # its original amplitude and its bit-flipped partner.
    expected = [
        (
            initial[index ^ mask]
            + (-initial[index] if index & mask else initial[index])
        ) * scale
        for index in range(COUNT)
    ]

    if any(
        not math.isfinite(value.real)
        or not math.isfinite(value.imag)
        for value in actual
    ):
        raise SystemExit(f"Failed: non-finite amplitude for target {target}")

    max_error = max(
        abs(result - reference)
        for result, reference in zip(actual, expected)
    )
    probability = sum(abs(value) ** 2 for value in actual)

    print(
        f"Target {target}: maximum error = {max_error:.3e}, "
        f"total probability = {probability:.15f}"
    )

    if max_error > TOLERANCE or abs(probability - 1.0) > TOLERANCE:
        raise SystemExit(f"Failed: target {target}")

print("All dense-state tests Passed")