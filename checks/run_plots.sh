#!/usr/bin/env bash
set -euo pipefail

quantsim_root="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &&
    pwd
)"
quantsim_mount="/media/praneeth/Crucial X6"
quantsim_storage="$quantsim_mount/QuantSim-storage"
quantsim_packages="$quantsim_storage/plot-packages"

if ! mountpoint -q "$quantsim_mount"; then
    echo "External SSD is not mounted" >&2
    exit 1
fi

cd "$quantsim_root"

export TMPDIR="$quantsim_storage/python-tmp"
export MPLCONFIGDIR="$quantsim_storage/matplotlib-cache"
mkdir -p "$TMPDIR" "$MPLCONFIGDIR" "$quantsim_packages"

# Check only the dedicated package folder and Python's standard library.
if ! /usr/bin/python3 -I -S - "$quantsim_packages" \
    >/dev/null 2>&1 <<'PY'
import sys
sys.path.insert(0, sys.argv[1])

import numpy
import matplotlib

assert numpy.__version__ == "1.26.4"
assert matplotlib.__version__ == "3.8.4"
PY
then
    /usr/bin/python3 -I -m pip --isolated install \
        --target "$quantsim_packages" \
        --upgrade \
        --only-binary=:all: \
        --no-cache-dir \
        "numpy==1.26.4" \
        "matplotlib==3.8.4"
fi

/usr/bin/python3 -I -S - \
    "$quantsim_packages" "$quantsim_root" <<'PY'
import runpy
import sys
from pathlib import Path

packages = Path(sys.argv[1])
root = Path(sys.argv[2])
sys.path.insert(0, str(packages))

import numpy
import matplotlib

print("NumPy:", numpy.__version__, numpy.__file__, flush=True)
print("Matplotlib:", matplotlib.__version__, matplotlib.__file__, flush=True)

script = root / "checks/plot_results.py"
sys.argv = [
    str(script),
    str(root / "results/matched_calibration_20261011_170250.csv"),
    str(root / "results/large_baseline_runs_20261011_164145.csv"),
]
runpy.run_path(str(script), run_name="__main__")
PY