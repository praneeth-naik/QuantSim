import csv
import os
import sys
from datetime import datetime
from pathlib import Path

MOUNT = Path("/media/praneeth/Crucial X6")
RESULTS = MOUNT / "QuantSim-storage/results"
MiB = 1 << 20

BUDGETS_MIB = (1, 2, 4, 8, 16, 32, 64, 128, 256, 512)


def chunk_mib(row):
    return ((1 << int(row["chunk_qubits"])) * 16) / MiB


def description(row):
    return f"{chunk_mib(row):g} MiB/{int(row['slots'])} slots"


def main():
    if len(sys.argv) != 2:
        raise RuntimeError(
            "Usage: python3 checks/check_budget_selection.py "
            "<pipeline-model.csv>"
        )

    if not os.path.ismount(MOUNT):
        raise RuntimeError("External SSD is not mounted")

    input_path = Path(sys.argv[1]).resolve()

    if os.path.commonpath(
        [str(input_path), str(RESULTS.resolve())]
    ) != str(RESULTS.resolve()):
        raise RuntimeError("Expected a model CSV on the external SSD")

    with open(input_path, newline="") as file:
        rows = list(csv.DictReader(file))

    if not rows or {int(row["qubits"]) for row in rows} != {24}:
        raise RuntimeError("Expected the frozen 24-qubit model results")

    output_rows = []

    for gate in ("local", "global"):
        print(f"\n{gate}:")
        candidates = [row for row in rows if row["gate_type"] == gate]

        if not candidates:
            raise RuntimeError(f"No configurations for {gate}")

        for budget_mib in BUDGETS_MIB:
            budget_bytes = budget_mib * MiB

            feasible = [
                row for row in candidates
                if int(row["buffer_bytes_per_side"]) <= budget_bytes
            ]

            if not feasible:
                raise RuntimeError(
                    f"No tested configuration fits {gate}, {budget_mib} MiB"
                )

            # The selector uses predicted times only.
            selected = min(
                feasible,
                key=lambda row: (
                    float(row["predicted_ms"]),
                    int(row["buffer_bytes_per_side"]),
                ),
            )

            oracle = min(
                feasible,
                key=lambda row: float(row["observed_median_ms"]),
            )

            # Fixed 1 MiB chunks, using the largest feasible tested depth.
            fixed_candidates = [
                row for row in feasible
                if int(row["chunk_qubits"]) == 16
            ]

            fixed = (
                max(fixed_candidates, key=lambda row: int(row["slots"]))
                if fixed_candidates
                else None
            )

            selected_time = float(selected["observed_median_ms"])
            oracle_time = float(oracle["observed_median_ms"])

            regret = 100 * (selected_time / oracle_time - 1)

            fixed_time = (
                float(fixed["observed_median_ms"])
                if fixed is not None
                else None
            )

            difference = (
                100 * (selected_time / fixed_time - 1)
                if fixed_time is not None
                else None
            )

            output_rows.append({
                "qubits": 24,
                "gate_type": gate,
                "budget_mib_per_side": budget_mib,
                "model_chunk_mib": chunk_mib(selected),
                "model_slots": int(selected["slots"]),
                "model_buffer_mib_per_side":
                    int(selected["buffer_bytes_per_side"]) / MiB,
                "model_observed_ms": selected_time,
                "oracle_chunk_mib": chunk_mib(oracle),
                "oracle_slots": int(oracle["slots"]),
                "oracle_observed_ms": oracle_time,
                "selection_regret_percent": regret,
                "fixed_slots":
                    int(fixed["slots"]) if fixed is not None else None,
                "fixed_observed_ms": fixed_time,
                "model_vs_fixed_percent": difference,
            })

            print(
                f"budget={budget_mib} MiB/side: "
                f"model={description(selected)}, "
                f"measured={selected_time:.3f} ms, "
                f"regret={regret:.2f}%"
            )

            if fixed is not None:
                print(
                    f"  Fixed baseline={description(fixed)}, "
                    f"{fixed_time:.3f} ms; "
                    f"model vs fixed={difference:+.2f}%"
                )
            else:
                print("  Fixed 1 MiB chunks do not fit this budget")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = RESULTS / f"budget_selection_{stamp}.csv"

    with open(output_path, "x", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(output_rows[0]))
        writer.writeheader()
        writer.writerows(output_rows)

    print("\nPositive model-vs-fixed percentages mean the model is slower.")
    print(f"Results saved: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        raise SystemExit(str(error))