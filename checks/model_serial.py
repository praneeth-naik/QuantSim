import csv
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime

MOUNT = "/media/praneeth/Crucial X6"
RESULTS = os.path.join(MOUNT, "QuantSim-storage", "results")


def read_csv(path):
    resolved = os.path.realpath(path)
    results_directory = os.path.realpath(RESULTS)

    if os.path.commonpath([resolved, results_directory]) != results_directory:
        raise RuntimeError(f"Expected a results file on the external SSD: {path}")

    with open(resolved, newline="") as file:
        return list(csv.DictReader(file))


def main():
    if len(sys.argv) != 4:
        raise RuntimeError(
            "Usage: python3 checks/model_serial.py "
            "<gpu.csv> <storage.csv> <benchmark.csv>"
        )

    if not os.path.ismount(MOUNT):
        raise RuntimeError("External SSD is not mounted")

    gpu_rows = read_csv(sys.argv[1])
    storage_rows = read_csv(sys.argv[2])
    benchmark_rows = read_csv(sys.argv[3])

    gpu_groups = defaultdict(list)
    storage_groups = defaultdict(list)
    benchmark_groups = defaultdict(list)

    for row in gpu_rows:
        gate = row["gate_type"]
        chunk_bits = int(row["chunk_qubits"])
        target = int(row["target"])

        # The benchmark used target 0 for local gates.
        # The paired GPU kernel is the same for all global targets.
        if gate == "local" and target != 0:
            continue

        gpu_groups[(gate, chunk_bits)].append(row)

    for row in storage_rows:
        key = (row["gate_type"], int(row["chunk_qubits"]))
        storage_groups[key].append(row)

    for row in benchmark_rows:
        if int(row["slots"]) != 1:
            continue

        qubits = int(row["qubits"])
        target = int(row["target"])
        gate = row["gate_type"]
        chunk_bits = int(row["chunk_qubits"])

        expected_target = 0 if gate == "local" else qubits - 1

        if target != expected_target:
            raise RuntimeError(
                "This calibration expects local target 0 "
                "and global target qubits-1"
            )

        key = (qubits, target, gate, chunk_bits)
        benchmark_groups[key].append(float(row["processing_ms"]))

    if not benchmark_groups:
        raise RuntimeError("No one-slot benchmark measurements found")

    output_rows = []

    for key, observed_times in sorted(benchmark_groups.items()):
        qubits, target, gate, chunk_bits = key
        stage_key = (gate, chunk_bits)

        if stage_key not in gpu_groups or stage_key not in storage_groups:
            raise RuntimeError(f"Missing calibration for {stage_key}")

        gpu = gpu_groups[stage_key]
        storage = storage_groups[stage_key]

        h2d = statistics.median(float(row["h2d_ms"]) for row in gpu)
        kernel = statistics.median(float(row["kernel_ms"]) for row in gpu)
        d2h = statistics.median(float(row["d2h_ms"]) for row in gpu)

        read = statistics.median(
            float(row["read_ms_per_job"]) for row in storage
        )
        write = statistics.median(
            float(row["write_ms_per_job"]) for row in storage
        )

        buffer_count = 2 if gate == "global" else 1
        jobs = (1 << qubits) // (1 << chunk_bits) // buffer_count

        predicted = jobs * (read + h2d + kernel + d2h + write)
        observed = statistics.median(observed_times)
        error_percent = 100 * (predicted - observed) / observed

        output_rows.append({
            "qubits": qubits,
            "target": target,
            "gate_type": gate,
            "chunk_qubits": chunk_bits,
            "slots": 1,
            "jobs": jobs,
            "read_ms_per_job": read,
            "h2d_ms_per_job": h2d,
            "kernel_ms_per_job": kernel,
            "d2h_ms_per_job": d2h,
            "write_ms_per_job": write,
            "predicted_ms": predicted,
            "observed_median_ms": observed,
            "signed_error_percent": error_percent,
            "absolute_error_percent": abs(error_percent),
        })

        chunk_mib = ((1 << chunk_bits) * 16) / (1 << 20)

        print(
            f"{gate}, chunk={chunk_mib:g} MiB: "
            f"predicted={predicted:.3f} ms, "
            f"observed={observed:.3f} ms, "
            f"error={error_percent:+.2f}%"
        )

    errors = [row["absolute_error_percent"] for row in output_rows]

    print(f"\nMean absolute percentage error: {statistics.mean(errors):.2f}%")
    print(f"Maximum absolute percentage error: {max(errors):.2f}%")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(RESULTS, f"serial_model_{stamp}.csv")

    with open(output_path, "x", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(output_rows[0]))
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Results saved: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)