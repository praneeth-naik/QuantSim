import argparse
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from select_config import select_config

ROOT = Path(__file__).resolve().parents[1]
MOUNT = Path("/media/praneeth/Crucial X6")
STORAGE = MOUNT / "QuantSim-storage"
RESULTS = STORAGE / "results"


def main():
    parser = argparse.ArgumentParser(
        description="Run and validate a selected single-Hadamard configuration."
    )
    parser.add_argument("qubits", type=int)
    parser.add_argument("target", type=int)
    parser.add_argument("host_budget_mib", type=int)
    parser.add_argument("device_budget_mib", type=int)
    args = parser.parse_args()

    if not 8 <= args.qubits <= 35:
        parser.error("qubits must be between 8 and 35")
    if not 0 <= args.target < args.qubits:
        parser.error("target must be between 0 and qubits - 1")
    if not all(
        1 <= budget <= 512
        for budget in [args.host_budget_mib, args.device_budget_mib]
    ):
        parser.error("each buffer budget must be between 1 and 512 MiB")

    if not os.path.ismount(MOUNT):
        raise RuntimeError("External SSD is not mounted")

    storage = STORAGE.resolve()
    results = RESULTS.resolve()
    storage.relative_to(MOUNT.resolve())
    results.relative_to(storage)

    if not storage.is_dir() or not results.is_dir():
        raise RuntimeError("External storage/results directories are missing")

    state_bytes = (1 << args.qubits) * 16
    reserve_bytes = 1024**3

    if shutil.disk_usage(storage).free < state_bytes + reserve_bytes:
        raise RuntimeError("Insufficient external SSD space for this state")

    programs = {
        "initialize": ROOT / "build/init_state",
        "apply": ROOT / "build/file_hadamard_direct",
        "validate": ROOT / "build/validate_state",
    }
    for executable in programs.values():
        if not os.access(executable, os.X_OK):
            raise RuntimeError(f"Missing executable: {executable}")

    choice = select_config(
        args.qubits,
        args.target,
        args.host_budget_mib,
        args.device_budget_mib,
    )

    environment = os.environ.copy()
    environment["QUANTSIM_HOST_BUFFER_BUDGET_MIB"] = str(
        args.host_budget_mib
    )
    environment["QUANTSIM_DEVICE_BUFFER_BUDGET_MIB"] = str(
        args.device_budget_mib
    )

    report = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "selector": "depth-first",
        "arguments": vars(args),
        "selection": choice,
        "state_bytes": state_bytes,
        "storage": str(storage),
        "status": "running",
        "steps": [],
    }

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    report_path = results / f"selected_run_{stamp}.json"

    print(
        f"Selected: {choice['gate_type']}, "
        f"{choice['chunk_bytes'] / 1024**2:g} MiB chunks, "
        f"{choice['slots']} slots",
        flush=True,
    )

    try:
        with tempfile.TemporaryDirectory(
            prefix="selected-run-", dir=storage
        ) as temporary:
            directory = Path(temporary)
            (directory / "data").mkdir()

            common = [
                str(args.qubits),
                str(args.target),
                str(choice["chunk_qubits"]),
            ]

            for stage in ["initialize", "apply", "validate"]:
                command = [str(programs[stage]), *common]
                if stage == "apply":
                    command.append(str(choice["slots"]))

                completed = subprocess.run(
                    command,
                    cwd=directory,
                    env=environment,
                    capture_output=True,
                    text=True,
                )

                report["steps"].append({
                    "stage": stage,
                    "command": command,
                    "returncode": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                })

                print(completed.stdout, end="", flush=True)
                if completed.stderr:
                    print(completed.stderr, end="", flush=True)

                if completed.returncode != 0:
                    raise RuntimeError(f"{stage} failed")

                if stage == "initialize":
                    state = directory / "data/state.bin"
                    if state.stat().st_size != state_bytes:
                        raise RuntimeError("Unexpected initialized state size")

                    with state.open("r+b") as state_file:
                        os.fsync(state_file.fileno())

                if stage == "apply":
                    expected = choice["buffer_bytes_per_side"]
                    for label in [
                        "Pinned host buffer bytes",
                        "Device buffer bytes",
                    ]:
                        if f"{label}: {expected}" not in completed.stdout.splitlines():
                            raise RuntimeError(
                                f"Reported {label} differs from selection"
                            )

        report["status"] = "passed"
        print("Selected configuration executed and validated successfully.")

    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise

    finally:
        with report_path.open("x") as output:
            json.dump(report, output, indent=2)
            output.write("\n")
        print(f"Report saved: {report_path}", flush=True)


if __name__ == "__main__":
    main()