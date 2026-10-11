import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOUNT = Path("/media/praneeth/Crucial X6")
STORAGE = MOUNT / "QuantSim-storage"
RESULTS = STORAGE / "results"

SIMULATOR = ROOT / "build/file_hadamard_direct"
INITIALIZER = ROOT / "build/init_state"
VALIDATOR = ROOT / "build/validate_state"


def execute(command, directory, host_budget, device_budget):
    environment = os.environ.copy()
    environment["QUANTSIM_HOST_BUFFER_BUDGET_MIB"] = str(host_budget)
    environment["QUANTSIM_DEVICE_BUFFER_BUDGET_MIB"] = str(device_budget)

    return subprocess.run(
        [str(value) for value in command],
        cwd=directory,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def main():
    if not os.path.ismount(MOUNT):
        raise RuntimeError("External SSD is not mounted")

    for executable in (SIMULATOR, INITIALIZER, VALIDATOR):
        if not executable.is_file():
            raise RuntimeError(f"Missing executable: {executable}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = RESULTS / f"budget_enforcement_{stamp}.txt"

    with open(output_path, "x") as log:
        with tempfile.TemporaryDirectory(
            prefix="budget-check-", dir=STORAGE
        ) as temporary:
            directory = Path(temporary)
            (directory / "data").mkdir()

            rejected_cases = [
                (
                    "Host budget exceeded",
                    [17, 0, 16, 2],
                    1,
                    512,
                    "Configuration exceeds buffer memory budget",
                ),
                (
                    "Device budget exceeded",
                    [17, 16, 16, 1],
                    512,
                    1,
                    "Configuration exceeds buffer memory budget",
                ),
                (
                    "Invalid budget value",
                    [16, 0, 14, 4],
                    "abc",
                    1,
                    "QUANTSIM_HOST_BUFFER_BUDGET_MIB must be",
                ),
            ]

            for label, arguments, host, device, expected in rejected_cases:
                result = execute(
                    [SIMULATOR, *arguments], directory, host, device
                )

                log.write(f"{label}\n{result.stdout}\n")
                log.flush()

                if result.returncode == 0 or expected not in result.stdout:
                    raise RuntimeError(
                        f"Rejection check failed: {label}\n{result.stdout}"
                    )

                print(f"{label}: correctly rejected", flush=True)

            accepted_cases = [
                ("Local gate at the 1 MiB boundary", [16, 0, 14], 4),
                ("Global gate at the 1 MiB boundary", [17, 16, 14], 2),
            ]

            for label, config, slots in accepted_cases:
                initialization = execute(
                    [INITIALIZER, *config], directory, 1, 1
                )

                if initialization.returncode != 0:
                    raise RuntimeError(initialization.stdout)

                state_path = directory / "data/state.bin"

                if state_path.stat().st_size != (1 << config[0]) * 16:
                    raise RuntimeError("Unexpected initialized state size")

                with open(state_path, "r+b", buffering=0) as state:
                    os.fsync(state.fileno())

                simulation = execute(
                    [SIMULATOR, *config, slots], directory, 1, 1
                )

                log.write(f"{label}\n{simulation.stdout}\n")
                log.flush()

                if simulation.returncode != 0:
                    raise RuntimeError(simulation.stdout)

                lines = simulation.stdout.splitlines()

                for expected in (
                    "Pinned host buffer bytes: 1048576",
                    "Device buffer bytes: 1048576",
                ):
                    if expected not in lines:
                        raise RuntimeError(
                            f"Boundary allocation mismatch:\n{simulation.stdout}"
                        )

                validation = execute(
                    [VALIDATOR, *config], directory, 1, 1
                )

                log.write(validation.stdout + "\n")
                log.flush()

                if validation.returncode != 0:
                    raise RuntimeError(validation.stdout)

                print(f"{label}: accepted and validated", flush=True)

    print("All buffer-budget checks PASSED")
    print(f"Results saved: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error))