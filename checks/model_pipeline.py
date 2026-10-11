import csv
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

MOUNT = Path("/media/praneeth/Crucial X6")
RESULTS = MOUNT / "QuantSim-storage/results"
BUFFER_BUDGET = 512 << 20


def read_csv(path):
    resolved = Path(path).resolve()
    results_directory = RESULTS.resolve()

    if os.path.commonpath(
        [str(resolved), str(results_directory)]
    ) != str(results_directory):
        raise RuntimeError("Expected a results file on the external SSD")

    with open(resolved, newline="") as file:
        return list(csv.DictReader(file))


def main():
    if len(sys.argv) != 4:
        raise RuntimeError(
            "Usage: python3 checks/model_pipeline.py "
            "<phase-calibration.csv> <storage-depth.csv> <gpu-benchmark.csv>"
        )

    if not os.path.ismount(MOUNT):
        raise RuntimeError("External SSD is not mounted")

    calibration = read_csv(sys.argv[1])
    storage = read_csv(sys.argv[2])
    benchmark = read_csv(sys.argv[3])

    phase_groups = defaultdict(list)
    io_groups = defaultdict(list)
    benchmark_groups = defaultdict(list)

    for row in calibration:
        if row["variant"] != "diagnostic":
            continue

        if int(row["slots"]) != 1:
            raise RuntimeError("Expected one-slot phase calibration")

        key = (row["gate_type"], int(row["chunk_qubits"]))
        phase_groups[key].append(row)

    for row in storage:
        key = (
            row["gate_type"],
            int(row["chunk_qubits"]),
            int(row["slots"]),
        )
        io_groups[key].append(float(row["processing_ms"]))

    for row in benchmark:
        qubits = int(row["qubits"])
        target = int(row["target"])
        gate = row["gate_type"]

        expected_target = 0 if gate == "local" else qubits - 1

        if target != expected_target:
            raise RuntimeError("Benchmark target differs from calibration")

        key = (
            qubits,
            target,
            gate,
            int(row["chunk_qubits"]),
            int(row["slots"]),
        )
        benchmark_groups[key].append(float(row["processing_ms"]))

    output_rows = []

    for key, times in sorted(benchmark_groups.items()):
        qubits, target, gate, chunk_bits, slots = key

        buffer_count = 2 if gate == "global" else 1
        chunk_bytes = (1 << chunk_bits) * 16
        buffer_bytes = chunk_bytes * buffer_count * slots

        if buffer_bytes > BUFFER_BUDGET:
            continue

        jobs = (1 << qubits) // (1 << chunk_bits) // buffer_count

        phase_key = (gate, chunk_bits)
        io_key = (gate, chunk_bits, slots)
        serial_io_key = (gate, chunk_bits, 1)

        if (
            phase_key not in phase_groups
            or io_key not in io_groups
            or serial_io_key not in io_groups
        ):
            raise RuntimeError(f"Missing calibration for {key}")

        io_ratio = (
            statistics.median(io_groups[io_key])
            / statistics.median(io_groups[serial_io_key])
        )

        predictions = []

        for sample in phase_groups[phase_key]:
            calibration_jobs = int(sample["jobs"])

            read_write = (
                float(sample["read_ms"]) + float(sample["write_ms"])
            ) / calibration_jobs

            gpu = float(sample["gpu_ms"]) / calibration_jobs
            other = float(sample["other_ms"]) / calibration_jobs

            predictions.append(
                jobs * (read_write * io_ratio + gpu / slots + other)
            )

        predicted = statistics.median(predictions)
        observed = statistics.median(times)
        error = 100 * (predicted / observed - 1)

        output_rows.append({
            "qubits": qubits,
            "target": target,
            "gate_type": gate,
            "chunk_qubits": chunk_bits,
            "slots": slots,
            "jobs": jobs,
            "buffer_bytes_per_side": buffer_bytes,
            "io_depth_ratio": io_ratio,
            "predicted_ms": predicted,
            "observed_median_ms": observed,
            "signed_error_percent": error,
            "absolute_error_percent": abs(error),
        })

        print(
            f"{gate}, chunk={chunk_bytes / (1 << 20):g} MiB, "
            f"slots={slots}: predicted={predicted:.3f} ms, "
            f"observed={observed:.3f} ms, error={error:+.2f}%"
        )

    if not output_rows:
        raise RuntimeError("No configurations available for evaluation")

    errors = [row["absolute_error_percent"] for row in output_rows]

    print(
        "\nMean absolute percentage error: "
        f"{statistics.mean(errors):.2f}%"
    )
    print(f"Maximum absolute percentage error: {max(errors):.2f}%")

    selections = defaultdict(list)

    for row in output_rows:
        selections[(row["qubits"], row["gate_type"])].append(row)

    print("\nConfiguration-selection check:")

    for (qubits, gate), candidates in sorted(selections.items()):
        selected = min(
            candidates,
            key=lambda row: (
                row["predicted_ms"],
                row["buffer_bytes_per_side"],
            ),
        )

        oracle = min(
            candidates, key=lambda row: row["observed_median_ms"]
        )

        regret = 100 * (
            selected["observed_median_ms"]
            / oracle["observed_median_ms"] - 1
        )

        selected_chunk = (
            (1 << selected["chunk_qubits"]) * 16 / (1 << 20)
        )
        oracle_chunk = (
            (1 << oracle["chunk_qubits"]) * 16 / (1 << 20)
        )

        print(
            f"{qubits} qubits, {gate}: "
            f"model selects {selected_chunk:g} MiB/"
            f"{selected['slots']} slots; "
            f"measured time={selected['observed_median_ms']:.3f} ms"
        )

        print(
            f"  Measured best: {oracle_chunk:g} MiB/"
            f"{oracle['slots']} slots, "
            f"{oracle['observed_median_ms']:.3f} ms; "
            f"selection regret={regret:.2f}%"
        )

        fixed = [
            row for row in candidates
            if row["chunk_qubits"] == 16 and row["slots"] == 4
        ]

        if fixed:
            print(
                "  Fixed 1 MiB/4-slot configuration: "
                f"{fixed[0]['observed_median_ms']:.3f} ms"
            )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = RESULTS / f"pipeline_model_{stamp}.csv"

    with open(output_path, "x", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(output_rows[0]))
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"\nResults saved: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        raise SystemExit(str(error))