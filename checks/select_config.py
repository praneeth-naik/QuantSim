import argparse


def select_config(qubits, target, host_mib, device_mib):
    budget_bytes = min(host_mib, device_mib) * 1024**2
    candidates = []

    # For smaller states, cap the chunk at the state size.
    chunk_choices = sorted({min(qubits, 14), min(qubits, 16)})

    for chunk_qubits in chunk_choices:
        chunk_bytes = (1 << chunk_qubits) * 16

        # Gate type depends on the candidate chunk size.
        global_gate = target >= chunk_qubits
        buffers_per_slot = 2 if global_gate else 1

        bytes_per_slot = chunk_bytes * buffers_per_slot
        jobs = (1 << (qubits - chunk_qubits)) // buffers_per_slot

        slots = min(
            4,
            budget_bytes // bytes_per_slot,
            jobs,
        )

        if slots < 1:
            continue

        candidates.append({
            "chunk_qubits": chunk_qubits,
            "chunk_bytes": chunk_bytes,
            "slots": slots,
            "gate_type": "global" if global_gate else "local",
            "buffer_bytes_per_side": bytes_per_slot * slots,
        })

    if not candidates:
        raise ValueError("No candidate fits both buffer budgets")

    return max(
        candidates,
        key=lambda candidate: (
            candidate["slots"],
            candidate["chunk_bytes"],
        ),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Select a QuantSim configuration without running it."
    )
    parser.add_argument("qubits", type=int)
    parser.add_argument("target", type=int)
    parser.add_argument("host_budget_mib", type=int)
    parser.add_argument("device_budget_mib", type=int)
    args = parser.parse_args()

    if not 8 <= args.qubits <= 35:
        parser.error("qubits must be between 8 and 35 for this direct-I/O selector")
    if not 0 <= args.target < args.qubits:
        parser.error("target must be between 0 and qubits - 1")
    if not all(
        1 <= budget <= 512
        for budget in [args.host_budget_mib, args.device_budget_mib]
    ):
        parser.error("each buffer budget must be between 1 and 512 MiB")

    choice = select_config(
        args.qubits,
        args.target,
        args.host_budget_mib,
        args.device_budget_mib,
    )

    print("Selector: depth-first heuristic")
    print(f"Gate type: {choice['gate_type']}")
    print(f"Chunk qubits: {choice['chunk_qubits']}")
    print(f"Chunk size: {choice['chunk_bytes'] / 1024**2:g} MiB")
    print(f"Pipeline slots: {choice['slots']}")
    print(
        "Data buffers per memory side: "
        f"{choice['buffer_bytes_per_side'] / 1024**2:g} MiB"
    )
    print(f"State-file size: {(1 << args.qubits) * 16 / 1024**3:g} GiB")
    print("Selection only; no state file was opened or modified.")


if __name__ == "__main__":
    main()