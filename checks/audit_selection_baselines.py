import csv
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

MOUNT = Path("/media/praneeth/Crucial X6")
RESULTS = MOUNT / "QuantSim-storage/results"
MiB = 1 << 20
BUDGETS_MIB = (1, 2, 4, 8)


def read_csv(path):
    resolved = Path(path).resolve()

    if os.path.commonpath(
        [str(resolved), str(RESULTS.resolve())]
    ) != str(RESULTS.resolve()):
        raise RuntimeError("Expected a results CSV on the external SSD")

    with open(resolved, newline="") as file:
        return list(csv.DictReader(file))


def configuration(row):
    return (
        row["gate_type"],
        int(row["chunk_qubits"]),
        int(row["slots"]),
    )


def main():
    if len(sys.argv) != 3:
        raise RuntimeError(
            "Usage: python3 checks/audit_selection_baselines.py "
            "<pipeline-model.csv> <budget-holdout-runs.csv>"
        )

    if not os.path.ismount(MOUNT):
        raise RuntimeError("External SSD is not mounted")

    model = read_csv(sys.argv[1])
    runs = read_csv(sys.argv[2])

    if not model or {int(row["qubits"]) for row in model} != {24}:
        raise RuntimeError("Expected the frozen 24-qubit model")

    if not runs or {int(row["qubits"]) for row in runs} != {26}:
        raise RuntimeError("Expected the 26-qubit budget measurements")

    timings = defaultdict(list)

    for row in runs:
        timings[configuration(row)].append(float(row["processing_ms"]))

    output_rows = []
    small_chunk_matches = 0
    scenario_count = 0

    for gate in ("local", "global"):
        for budget in BUDGETS_MIB:
            feasible = [
                row for row in model
                if row["gate_type"] == gate
                and int(row["buffer_bytes_per_side"]) <= budget * MiB
            ]

            if not feasible:
                raise RuntimeError(f"No feasible candidates: {gate}, {budget}")

            model_choice = min(
                feasible,
                key=lambda row: (
                    float(row["predicted_ms"]),
                    int(row["buffer_bytes_per_side"]),
                ),
            )

            small_choice = min(
                feasible,
                key=lambda row: (
                    int(row["chunk_qubits"]),
                    -int(row["slots"]),
                ),
            )

            depth_candidates = [
                row for row in feasible
                if int(row["chunk_qubits"]) <= 16
            ]

            depth_choice = (
                max(
                    depth_candidates,
                    key=lambda row: (
                        int(row["slots"]),
                        int(row["chunk_qubits"]),
                    ),
                )
                if depth_candidates else None
            )

            fixed_candidates = [
                row for row in feasible
                if int(row["chunk_qubits"]) == 16
            ]

            fixed_choice = (
                max(fixed_candidates, key=lambda row: int(row["slots"]))
                if fixed_candidates else None
            )

            choices = {
                "model": model_choice,
                "small_chunk": small_choice,
                "depth_first": depth_choice,
                "fixed": fixed_choice,
            }

            model_key = configuration(model_choice)
            scenario_count += 1

            if configuration(small_choice) == model_key:
                small_chunk_matches += 1

            print(f"\n{gate}, budget={budget} MiB/side:")

            for policy, choice in choices.items():
                record = {
                    "qubits": 26,
                    "gate_type": gate,
                    "budget_mib_per_side": budget,
                    "policy": policy,
                    "chunk_mib": None,
                    "slots": None,
                    "buffer_mib_per_side": None,
                    "median_processing_ms": None,
                    "measured_trials": 0,
                    "same_configuration_as_model": None,
                }

                if choice is None:
                    print(f"  {policy}: no feasible configuration")
                    output_rows.append(record)
                    continue

                key = configuration(choice)
                chunk_mib = ((1 << key[1]) * 16) / MiB
                samples = timings.get(key, [])

                record.update({
                    "chunk_mib": chunk_mib,
                    "slots": key[2],
                    "buffer_mib_per_side":
                        int(choice["buffer_bytes_per_side"]) / MiB,
                    "measured_trials": len(samples),
                    "same_configuration_as_model": key == model_key,
                })

                if samples:
                    observed = statistics.median(samples)
                    record["median_processing_ms"] = observed
                    result = f"{observed:.3f} ms"
                else:
                    result = "not measured in this holdout"

                print(
                    f"  {policy}: {chunk_mib:g} MiB/{key[2]} slots, {result}"
                )
                output_rows.append(record)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = RESULTS / f"selection_baseline_audit_{stamp}.csv"

    with open(output_path, "x", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(output_rows[0]))
        writer.writeheader()
        writer.writerows(output_rows)

    print(
        "\nSmall-chunk rule matches the model in "
        f"{small_chunk_matches}/{scenario_count} budget scenarios."
    )
    print("Repeated configurations reuse the same timing samples.")
    print(f"Results saved: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        raise SystemExit(str(error))