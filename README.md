# QuantSim

An SSD-backed GPU research prototype for applying Hadamard gates to
quantum state vectors using bounded host and device data buffers.

QuantSim explores how chunk size, asynchronous file I/O, and CUDA
pipeline depth affect processing time when the full state cannot fit
in GPU memory.

**Current scope:** one Hadamard gate per invocation. This is not yet
a general quantum-circuit simulator.

## How it works

The state vector stays on an SSD. QuantSim reads chunks into pinned
host memory, transfers them to the GPU, applies a Hadamard kernel,
and writes the results back.

Multiple pipeline slots allow operations on different chunks to
overlap.

- **Local gates:** both paired amplitudes are inside one chunk.
- **Global gates:** paired amplitudes lie in two different chunks.
- **Storage:** asynchronous `io_uring` operations with direct I/O.
- **Computation:** CUDA kernels and streams.
- **Memory control:** separately enforced host and device data-buffer
  budgets.

Each amplitude uses a double-precision complex value: 16 bytes.
An n-qubit state occupies `16 × 2^n` bytes.

## Main findings

On the tested RTX 2050 laptop and Crucial X6 external USB SSD:

| Experiment | Result |
|---|---|
| Initial 24-qubit local-gate depth pilot | Four slots achieved 1.45× speedup over one slot |
| Initial 24-qubit global-gate depth pilot | Four slots achieved 1.41× speedup over one slot |
| 30-qubit state | Validated processing of a 16 GiB state |
| Buffers for the 16 GiB experiment | 8 MiB on the host and 8 MiB on the GPU |
| 16 GiB experiment processing time | 33.879 seconds, excluding setup |

A calibrated performance model was evaluated against simpler selection
rules. It did **not** demonstrate an advantage over the depth-first
heuristic. On the independent 28-qubit comparison, its selected
configuration was 4.73% slower locally and 3.39% slower globally.

The default selector therefore uses a depth-first rule: maximize
feasible pipeline depth, then choose the larger chunk from the
0.25 MiB and 1 MiB candidates.

These are measurements from one hardware and storage configuration,
not general performance guarantees.

## Tested environment

- Ubuntu 22.04.5 LTS; Linux kernel 6.8.0-138-generic.
- NVIDIA GeForce RTX 2050 with 4 GiB VRAM.
- Approximately 11 GiB system RAM reported by the operating system.
- CUDA 11.5 and GCC 11.4.
- liburing 2.0, including its development headers.
- Python 3.10.
- Crucial X6 external USB SSD formatted as exFAT.

The build script expects `g++-11`, `nvcc`, and the liburing development
files to be installed.

## Storage setup

The current experiment scripts use this machine-specific mount:

```text
/media/praneeth/Crucial X6
```

Their storage directory is:

```text
/media/praneeth/Crucial X6/QuantSim-storage
```

On another machine, the storage paths in the relevant scripts must be
adapted before running them. Storage configuration is not yet portable
through a shared command-line option or environment variable.

For the tested setup, verify the mount and create the results directory:

```bash
mountpoint -q "/media/praneeth/Crucial X6" &&
mkdir -p "/media/praneeth/Crucial X6/QuantSim-storage/results"
```

Generated state files, local storage symlinks, compiled executables,
and Python caches are excluded from Git.

## Build

From the repository root:

```bash
bash checks/build_core.sh
```

This builds the initializer, analytic validator, and direct-I/O GPU
pipeline.

## Select a configuration

```bash
python3 checks/select_config.py 28 27 8 8
```

Arguments:

```text
qubits target host_budget_MiB device_budget_MiB
```

This command prints a configuration without modifying a state file.

Budgets cover pipeline data buffers. CUDA context memory, other
process allocations, and operating-system caches are additional.

## Run a validated demonstration

```bash
python3 checks/run_selected.py 20 0 2 2
python3 checks/run_selected.py 20 19 1 1
```

Each command:

1. Selects a configuration within both buffer budgets.
2. Creates a temporary state on the configured external SSD.
3. Initializes the state to the zero basis state.
4. Applies one Hadamard gate.
5. Checks the amplitudes against the expected result.
6. Saves a JSON report and removes the temporary state.

Each example uses a 16 MiB state.

## Dense-state correctness check

```bash
QUANTSIM_TEST_QUBITS=12 QUANTSIM_TEST_CHUNK_QUBITS=8 \
python3 checks/validate_dense.py ./build/file_hadamard_direct 4
```

This compares all target qubits against an independent reference
calculation using a deterministic normalized complex input state.
It uses temporary external-SSD storage.

## Repository structure

| Directory | Contents |
|---|---|
| `src/` | CUDA kernels, file I/O, pipeline implementations, initialization, and validation |
| `checks/` | Build scripts, correctness checks, experiments, models, and plotting tools |
| `docs/` | Project summary, findings, and limitations |

Several implementations in `src/` preserve earlier development stages.
The current core GPU executable is built from
`src/file_hadamard_direct.cu`.

## Interpretation and limitations

- Processing time excludes setup, initialization, and validation.
- Write completion does not imply an explicit durable-storage flush.
- Large-state validation used a single Hadamard on the zero basis
  state; dense-state validation was performed separately at smaller sizes.
- Timing repetitions are limited; small differences do not establish
  statistical significance.
- The selector searches a restricted set of configurations.
- The model-based selection advantage remains unproven.
- Historical scripts `benchmark_depth.py`, `benchmark_chunks.py`, and
  `check_large_state.py` regenerate the project's `data/state.bin`.

See [the project summary](docs/project_summary.md) for the experimental
findings and their interpretation.