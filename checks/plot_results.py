import argparse
import csv
import math
import os
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

MOUNT = Path("/media/praneeth/Crucial X6")
RESULTS = MOUNT / "QuantSim-storage/results"


def read_rows(filename):
    path = Path(filename).resolve()
    path.relative_to(RESULTS.resolve())
    with path.open(newline="") as source:
        return list(csv.DictReader(source))


def summarize(rows, qubits):
    groups = defaultdict(list)
    trials = defaultdict(set)

    for row in rows:
        if int(row["qubits"]) != qubits:
            raise RuntimeError("Unexpected state size in input")

        key = (
            row["gate_type"],
            int(row["chunk_qubits"]),
            int(row["slots"]),
        )
        trial = int(row["trial"])
        value = float(row["processing_ms"]) / 1000

        if not math.isfinite(value) or value <= 0:
            raise RuntimeError(f"Invalid timing: {key}")
        if trial in trials[key]:
            raise RuntimeError(f"Duplicate trial: {key}, {trial}")

        trials[key].add(trial)
        groups[key].append(value)

    if any(len(values) != 3 for values in groups.values()):
        raise RuntimeError("Expected three measured trials per configuration")

    return {
        key: (
            statistics.median(values),
            min(values),
            max(values),
        )
        for key, values in groups.items()
    }


def save_figure(figure, directory, name):
    for extension in ["png", "pdf"]:
        path = directory / f"{name}.{extension}"
        figure.savefig(path, dpi=300, bbox_inches="tight")
        print(f"Saved: {path}")
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("matched_calibration")
    parser.add_argument("large_baseline_runs")
    args = parser.parse_args()

    if not os.path.ismount(MOUNT):
        raise RuntimeError("External SSD is not mounted")
    RESULTS.resolve().relative_to(MOUNT.resolve())

    matched = read_rows(args.matched_calibration)
    gpu = summarize(
        [row for row in matched if row["variant"] == "gpu"],
        qubits=24,
    )
    large = summarize(read_rows(args.large_baseline_runs), qubits=28)

    expected_gpu = {
        (gate, chunk, slots)
        for gate in ["local", "global"]
        for chunk in [14, 16, 20]
        for slots in [1, 2, 3, 4]
    }
    expected_large = {
        (gate, chunk, 4)
        for gate in ["local", "global"]
        for chunk in [14, 16]
    }

    if set(gpu) != expected_gpu or set(large) != expected_large:
        raise RuntimeError("Input configuration grid differs from expectations")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destination = RESULTS / f"figures_{stamp}"
    destination.mkdir()

    plt.rcParams.update({
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "pdf.fonttype": 42,
    })

    # Figure 1: actual GPU measurements from matched calibration.
    figure, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    colors = ["#0072B2", "#D55E00", "#009E73"]

    for axis, gate in zip(axes, ["local", "global"]):
        for chunk, color in zip([14, 16, 20], colors):
            values = [gpu[(gate, chunk, slots)] for slots in range(1, 5)]
            medians = [value[0] for value in values]
            lower = [median - low for median, low, high in values]
            upper = [high - median for median, low, high in values]

            axis.errorbar(
                [1, 2, 3, 4],
                medians,
                yerr=[lower, upper],
                marker="o",
                capsize=3,
                color=color,
                label=f"{(1 << chunk) * 16 / 1024**2:g} MiB",
            )

        axis.set_title(f"{gate.capitalize()} gate")
        axis.set_xlabel("Pipeline slots")
        axis.set_xticks([1, 2, 3, 4])
        axis.grid(axis="y", alpha=0.25)
        axis.legend(title="Chunk size")

    axes[0].set_ylabel("Processing time (seconds)")
    figure.suptitle("24-qubit state: pipeline-depth calibration")
    figure.text(
        0.5, 0.01,
        "Points: medians of 3 trials. Whiskers: observed minimum–maximum.",
        ha="center", fontsize=9,
    )
    figure.tight_layout(rect=[0, 0.06, 1, 0.94])
    save_figure(figure, destination, "pipeline_depth")

    # Figure 2: independent 28-qubit comparison.
    figure, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    maximum = max(high for median, low, high in large.values())

    for axis, gate, budget in zip(
        axes, ["local", "global"], [4, 8]
    ):
        values = [large[(gate, chunk, 4)] for chunk in [14, 16]]
        medians = [value[0] for value in values]
        lower = [median - low for median, low, high in values]
        upper = [high - median for median, low, high in values]

        bars = axis.bar(
            [0, 1],
            medians,
            yerr=[lower, upper],
            capsize=4,
            color=["#D55E00", "#0072B2"],
            width=0.6,
        )
        axis.set_xticks([0, 1])
        axis.set_xticklabels([
            "Model\n0.25 MiB × 4",
            "Depth-first\n1 MiB × 4",
        ])
        axis.set_title(
            f"{gate.capitalize()} gate; budget {budget} MiB/side"
        )
        axis.set_ylim(0, maximum * 1.18)
        axis.grid(axis="y", alpha=0.25)
        axis.set_axisbelow(True)

        for bar, median in zip(bars, medians):
            axis.annotate(
                f"{median:.3f} s",
                (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                xytext=(0, 8),
                textcoords="offset points",
                ha="center",
            )

    axes[0].set_ylabel("Processing time (seconds)")
    figure.suptitle("28-qubit state: independent selector comparison")
    figure.text(
        0.5, 0.01,
        "Bars: medians of 3 trials. Whiskers: observed minimum–maximum.",
        ha="center", fontsize=9,
    )
    figure.tight_layout(rect=[0, 0.06, 1, 0.94])
    save_figure(figure, destination, "selector_comparison")

    print("Both figures use processing time, excluding setup.")
    print(f"Figure directory: {destination}")


if __name__ == "__main__":
    main()