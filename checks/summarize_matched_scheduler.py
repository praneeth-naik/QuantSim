import csv
import math
import statistics
import sys
from collections import defaultdict

from validate_budget_selector import RESULTS


def main():
    if len(sys.argv) != 2:
        raise RuntimeError("Usage: summarize_matched_scheduler.py CSV")

    groups = defaultdict(list)
    buffers = {}
    trials = defaultdict(set)

    with open(sys.argv[1], newline="") as source:
        for row in csv.DictReader(source):
            config = (
                row["gate_type"],
                int(row["chunk_qubits"]),
                int(row["slots"]),
            )
            key = (*config, row["variant"])
            value = float(row["processing_ms"])
            trial = int(row["trial"])

            if not math.isfinite(value) or value <= 0:
                raise RuntimeError(f"Invalid timing: {key}")
            if trial in trials[key]:
                raise RuntimeError(f"Duplicate trial: {key}, {trial}")

            trials[key].add(trial)
            groups[key].append(value)

            size = int(row["buffer_bytes_per_side"])
            if config in buffers and buffers[config] != size:
                raise RuntimeError(f"Inconsistent buffer size: {config}")
            buffers[config] = size

    expected = {
        (gate, chunk, slots, variant)
        for gate in ["local", "global"]
        for chunk in [14, 16, 20]
        for slots in [1, 2, 3, 4]
        for variant in ["control", "gpu"]
    }

    if set(groups) != expected:
        raise RuntimeError("Missing or unexpected configurations")
    if any(trials[key] != {0, 1, 2} for key in expected):
        raise RuntimeError("Expected trials 0, 1, and 2 for every group")

    medians = {
        key: statistics.median(values)
        for key, values in groups.items()
    }

    print("Matched processing-time summary:")
    for config in sorted(buffers):
        gate, chunk, slots = config
        control = medians[(*config, "control")]
        gpu = medians[(*config, "gpu")]
        chunk_mib = (1 << chunk) * 16 / 1024**2
        difference = 100 * (gpu / control - 1)

        control_ratio = control / medians[(gate, chunk, 1, "control")]
        gpu_ratio = gpu / medians[(gate, chunk, 1, "gpu")]

        print(
            f"{gate}, chunk={chunk_mib:g} MiB, slots={slots}: "
            f"control={control:.3f} ms, gpu={gpu:.3f} ms, "
            f"difference={difference:+.2f}%"
        )
        print(
            f"  Time relative to one slot: "
            f"control={control_ratio:.4f}, gpu={gpu_ratio:.4f}"
        )

    def describe(config):
        _, chunk, slots = config
        chunk_mib = (1 << chunk) * 16 / 1024**2
        return f"{chunk_mib:g} MiB/{slots} slots"

    print("\nCalibration-only configuration-selection check:")
    for gate in ["local", "global"]:
        for budget in [1, 2, 4, 8, 32, 128]:
            feasible = [
                config for config, size in buffers.items()
                if config[0] == gate and size <= budget * 1024**2
            ]

            # Select using storage-control measurements only.
            selected = min(
                feasible,
                key=lambda c: (
                    medians[(*c, "control")], buffers[c]
                ),
            )
            best_gpu = min(
                feasible,
                key=lambda c: medians[(*c, "gpu")],
            )

            # Previously defined heuristic: maximum depth,
            # then largest chunk, limited to chunks <= 1 MiB.
            depth_first = max(
                [c for c in feasible if c[1] <= 16],
                key=lambda c: (c[2], c[1]),
            )

            selected_ms = medians[(*selected, "gpu")]
            best_ms = medians[(*best_gpu, "gpu")]
            depth_ms = medians[(*depth_first, "gpu")]

            regret = 100 * (selected_ms / best_ms - 1)
            difference = 100 * (selected_ms / depth_ms - 1)

            print(f"\n{gate}, budget={budget} MiB/side:")
            print(
                f"  Control selects {describe(selected)}: "
                f"GPU time={selected_ms:.3f} ms"
            )
            print(
                f"  Measured GPU best={describe(best_gpu)}: "
                f"{best_ms:.3f} ms; selection regret={regret:.2f}%"
            )
            print(
                f"  Depth-first={describe(depth_first)}: "
                f"{depth_ms:.3f} ms; "
                f"control selection vs depth-first={difference:+.2f}%"
            )

    print("\nThese comparisons use calibration data, not a new holdout.")


if __name__ == "__main__":
    main()