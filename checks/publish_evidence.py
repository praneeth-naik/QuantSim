import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOUNT = Path("/media/praneeth/Crucial X6")
RESULTS = MOUNT / "QuantSim-storage/results"

MANIFEST = "evidence_manifest_20261011_173448_880008.json"
FIGURES = "figures_20261011_174209_996224"


def main():
    if not os.path.ismount(MOUNT):
        raise RuntimeError("External SSD is not mounted")

    results = RESULTS.resolve()
    results.relative_to(MOUNT.resolve())

    manifest = json.loads((results / MANIFEST).read_text())
    pending = []

    def prepare(source, destination, expected_hash=None):
        source = source.resolve()
        source.relative_to(results)

        if source.stat().st_size > 16 * 1024**2:
            raise RuntimeError(f"Unexpectedly large evidence file: {source}")

        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()

        if expected_hash is not None and digest != expected_hash:
            raise RuntimeError(f"Evidence checksum mismatch: {source.name}")

        if destination.is_symlink():
            raise RuntimeError(f"Expected a regular destination: {destination}")
        if destination.exists() and destination.read_bytes() != content:
            raise RuntimeError(f"Different file already exists: {destination}")

        pending.append((destination, content))

    for folder in [ROOT / "docs/evidence", ROOT / "docs/figures"]:
        folder.resolve().relative_to(ROOT.resolve())

    for record in manifest["files"]:
        name = record["file"]
        if Path(name).name != name:
            raise RuntimeError(f"Expected a plain filename: {name}")

        prepare(
            results / name,
            ROOT / "docs/evidence" / name,
            record["sha256"],
        )

    for name in [
        "pipeline_depth.png",
        "pipeline_depth.pdf",
        "selector_comparison.png",
        "selector_comparison.pdf",
    ]:
        prepare(
            results / FIGURES / name,
            ROOT / "docs/figures" / name,
        )

    prepare(
        results / MANIFEST,
        ROOT / "docs/evidence" / MANIFEST,
    )

    summary_path = ROOT / "docs/project_summary.md"
    summary = summary_path.read_text()
    old_prefix = f"../results/{FIGURES}/"

    if old_prefix in summary:
        summary = summary.replace(old_prefix, "figures/")
    elif not all(
        f"figures/{name}.png" in summary
        for name in ["pipeline_depth", "selector_comparison"]
    ):
        raise RuntimeError("Could not identify the summary's figure links")

    index = [
        "# Published experiment evidence",
        "",
        "These files are snapshots of the recorded experiments.",
        "The manifest retains the original external-SSD location and hashes.",
        "Repeated budget scenarios may reuse the same timing samples.",
        "",
    ]
    groups = {}
    for record in manifest["files"]:
        groups.setdefault(record["finding"], []).append(record["file"])

    for finding, names in groups.items():
        index.extend([f"## {finding}", ""])
        index.extend(f"- [{name}]({name})" for name in names)
        index.append("")

    index.extend([
        f"[Original evidence manifest]({MANIFEST})",
        "",
    ])

    for destination, content in pending:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)

    summary_path.write_text(summary)
    (ROOT / "docs/evidence/README.md").write_text("\n".join(index))

    print(f"Evidence files published: {len(manifest['files'])}")
    print("Figures published: 4")
    print("Evidence manifest and index: included")
    print("Project-summary figure links: updated")
    print(f"Copied asset size: {sum(len(b) for _, b in pending):,} bytes")


if __name__ == "__main__":
    main()