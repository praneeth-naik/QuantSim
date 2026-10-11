import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

MOUNT = Path("/media/praneeth/Crucial X6")
RESULTS = MOUNT / "QuantSim-storage/results"

EVIDENCE = {
    "Initial pipeline speedups": [
        "depth_pilot_20261011_122803.csv",
    ],
    "Chunk-size and pipeline-depth exploration": [
        "chunk_depth_20261011_130011.csv",
    ],
    "Validated 16 GiB state": [
        "large_state_20261011_131641.txt",
    ],
    "Serial-model holdout comparison": [
        "serial_holdout_20261011_150803.csv",
    ],
    "Original pipeline-model evaluation": [
        "pipeline_model_20261011_152322.csv",
        "selector_holdout_20261011_152648.csv",
    ],
    "Buffer-budget enforcement": [
        "budget_enforcement_20261011_153733.txt",
    ],
    "Budget-constrained holdout": [
        "budget_holdout_runs_20261011_154129.csv",
        "budget_holdout_summary_20261011_154129.csv",
    ],
    "Simple-selection-rule audit": [
        "selection_baseline_audit_20261011_163816.csv",
    ],
    "Independent 28-qubit baseline comparison": [
        "large_baseline_runs_20261011_164145.csv",
        "large_baseline_summary_20261011_164145.csv",
    ],
    "Matched scheduler calibration": [
        "matched_calibration_20261011_170250.csv",
    ],
    "Integration checks after the reproducible build": [
        "selected_run_20261011_173039_803484.json",
        "selected_run_20261011_173042_057716.json",
    ],
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    if not os.path.ismount(MOUNT):
        raise RuntimeError("External SSD is not mounted")

    results = RESULTS.resolve()
    results.relative_to(MOUNT.resolve())

    missing = [
        name
        for names in EVIDENCE.values()
        for name in names
        if not (results / name).is_file()
    ]

    if missing:
        print("Missing evidence files:")
        for name in missing:
            print(f"  {name}")
        raise SystemExit(1)

    records = []

    for finding, names in EVIDENCE.items():
        for name in names:
            path = (results / name).resolve()
            path.relative_to(results)

            records.append({
                "finding": finding,
                "file": name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            })

    manifest = {
        "created_at": datetime.now().astimezone().isoformat(),
        "results_directory": str(results),
        "purpose": "Index of evidence referenced by the project summary",
        "note": (
            "Checksums identify the current file contents. "
            "This index does not independently validate the experiments."
        ),
        "files": records,
    }

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destination = results / f"evidence_manifest_{stamp}.json"

    with destination.open("x") as output:
        json.dump(manifest, output, indent=2)
        output.write("\n")

    print(f"Evidence groups: {len(EVIDENCE)}")
    print(f"Result files indexed: {len(records)}")
    print(f"Total evidence size: {sum(r['bytes'] for r in records):,} bytes")
    print("All listed evidence files were found and checksummed.")
    print(f"Manifest saved: {destination}")


if __name__ == "__main__":
    main()