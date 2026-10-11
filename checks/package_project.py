import hashlib
import json
import os
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOUNT = Path("/media/praneeth/Crucial X6")
STORAGE = MOUNT / "QuantSim-storage"
RESULTS = STORAGE / "results"

FIGURES = "figures_20261011_174209_996224"


def git_output(*arguments):
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip())
    return completed.stdout.strip()


def main():
    if not os.path.ismount(MOUNT):
        raise RuntimeError("External SSD is not mounted")

    storage = STORAGE.resolve()
    results = RESULTS.resolve()
    storage.relative_to(MOUNT.resolve())
    results.relative_to(storage)

    files = {}

    def add(path, archive_name):
        if path.is_symlink():
            raise RuntimeError(f"Unexpected file symlink: {path}")
        if not path.is_file():
            raise RuntimeError(f"Missing file: {path}")
        if path.stat().st_size > 16 * 1024**2:
            raise RuntimeError(f"Unexpectedly large package file: {path}")
        files[archive_name] = path

    source_extensions = {
        ".cpp", ".cc", ".c", ".cu", ".h", ".hpp", ".cuh",
        ".py", ".sh", ".md", ".txt", ".json", ".yaml", ".yml",
    }

    for folder in ["src", "checks", "docs"]:
        directory = ROOT / folder
        if not directory.is_dir() or directory.is_symlink():
            raise RuntimeError(f"Expected project directory: {directory}")

        for path in sorted(directory.rglob("*")):
            if "__pycache__" in path.parts:
                continue
            if path.is_file() and path.suffix in source_extensions:
                add(path, path.relative_to(ROOT).as_posix())

    for name in ["README.md", "CMakeLists.txt", "Makefile", ".gitignore"]:
        path = ROOT / name
        if path.exists():
            add(path, name)

    # Include small result records, including calibration inputs.
    for path in sorted(results.iterdir()):
        if path.is_file() and path.suffix in {".csv", ".json", ".txt"}:
            add(path, f"results/{path.name}")

    for name in [
        "pipeline_depth.png",
        "pipeline_depth.pdf",
        "selector_comparison.png",
        "selector_comparison.pdf",
    ]:
        add(
            results / FIGURES / name,
            f"results/{FIGURES}/{name}",
        )

    required = [
        "src/file_hadamard_direct.cu",
        "checks/build_core.sh",
        "checks/run_selected.py",
        "checks/run_plots.sh",
        "docs/project_summary.md",
    ]
    for name in required:
        if name not in files:
            raise RuntimeError(f"Required package entry missing: {name}")

    manifest = {
        "created_at": datetime.now().astimezone().isoformat(),
        "git_head_at_packaging": git_output("rev-parse", "HEAD"),
        "git_status_at_packaging": git_output(
            "status", "--short", "--untracked-files=all"
        ),
        "note": (
            "Source files represent the current working tree, including "
            "uncommitted changes. The recorded Git commit does not establish "
            "which source version produced earlier experiments."
        ),
        "files": [],
    }

    releases = storage / "releases"
    releases.mkdir(exist_ok=True)
    releases.resolve().relative_to(storage)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    archive = releases / f"QuantSim_{stamp}.zip"

    with zipfile.ZipFile(
        archive, "x", compression=zipfile.ZIP_DEFLATED
    ) as output:
        for name, path in sorted(files.items()):
            content = path.read_bytes()
            output.writestr(f"QuantSim/{name}", content)
            manifest["files"].append({
                "file": name,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            })

        output.writestr(
            "QuantSim/package_manifest.json",
            json.dumps(manifest, indent=2) + "\n",
        )

    with zipfile.ZipFile(archive) as completed:
        damaged = completed.testzip()
        if damaged is not None:
            raise RuntimeError(f"Archive verification failed: {damaged}")

    print(f"Project files packaged: {len(files)}")
    print("Package manifest: included")
    print("Archive integrity check: PASSED")
    print(f"Archive size: {archive.stat().st_size / 1024**2:.2f} MiB")
    print(f"Archive saved: {archive}")


if __name__ == "__main__":
    main()