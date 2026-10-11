#include "hadamard_gpu.cuh"
#include "config.h"
#include "chunk_io.h"

#include <iostream>
#include <cstdlib>
#include <climits>
#include <vector>
#include <chrono>
#include <iomanip>

using namespace std;

void check(cudaError_t result) {
    if (result != cudaSuccess) {
        cerr << "CUDA error: " << cudaGetErrorString(result) << '\n';
        exit(1);
    }
}

enum class Phase {
    Empty,
    Reading,
    Computing,
    Writing
};

struct Slot {
    cuDoubleComplex* host[2] = {nullptr, nullptr};
    cuDoubleComplex* device[2] = {nullptr, nullptr};

    uint64_t position[2] = {0, 0};

    cudaStream_t stream{};
    cudaEvent_t done{};

    Phase phase = Phase::Empty;
    int pending = 0;
    unsigned completedBuffers = 0;
};

bool queueTransfers(
    ChunkIO& file,
    Slot& slot,
    int slotIndex,
    int bufferCount,
    size_t bytes,
    bool writing
) {
    slot.phase = writing ? Phase::Writing : Phase::Reading;
    slot.pending = bufferCount;
    slot.completedBuffers = 0;

    for (int buffer = 0; buffer < bufferCount; buffer++) {
        uint64_t id = uint64_t(slotIndex) * 2 + buffer;

        bool success;

        if (writing) {
            success = file.queueWrite(
                slot.position[buffer],
                slot.host[buffer],
                bytes,
                id
            );
        } else {
            success = file.queueRead(
                slot.position[buffer],
                slot.host[buffer],
                bytes,
                id
            );
        }

        if (!success) {
            return false;
        }
    }

    return true;
}

void launchGPU(
    Slot& slot,
    size_t chunkSize,
    size_t stride,
    size_t bytes,
    bool globalGate
) {
    int bufferCount = globalGate ? 2 : 1;

    for (int buffer = 0; buffer < bufferCount; buffer++) {
        check(cudaMemcpyAsync(
            slot.device[buffer],
            slot.host[buffer],
            bytes,
            cudaMemcpyHostToDevice,
            slot.stream
        ));
    }

    int threads = 128;
    size_t workItems = globalGate ? chunkSize : chunkSize / 2;
    int blocks = static_cast<int>(
        (workItems + threads - 1) / threads
    );

    if (globalGate) {
        hadamardPair<<<blocks, threads, 0, slot.stream>>>(
            slot.device[0], slot.device[1], chunkSize
        );
    } else {
        hadamardLocal<<<blocks, threads, 0, slot.stream>>>(
            slot.device[0], chunkSize, stride
        );
    }

    check(cudaGetLastError());

    for (int buffer = 0; buffer < bufferCount; buffer++) {
        check(cudaMemcpyAsync(
            slot.host[buffer],
            slot.device[buffer],
            bytes,
            cudaMemcpyDeviceToHost,
            slot.stream
        ));
    }

    check(cudaEventRecord(slot.done, slot.stream));
    slot.phase = Phase::Computing;
}

int main(int argc, char* argv[]) {
    if (argc != 4 && argc != 5) {
        cerr << "Usage: " << argv[0] << " <qubits> <target> <chunk_qubits> [slots]\n";
        return 1;
    }

    Config config;

    // The common parser handles the first three arguments.
    if (!parseConfig(4, argv, config)) {
        return 1;
    }

    int slotCount = 2;

    if (argc == 5 &&
        !parseInteger(argv[4], 1, 4, slotCount)) {
        cerr << "Pipeline slots must be between 1 and 4\n";
        return 1;
    }

    size_t count = size_t{1} << config.qubits;
    size_t chunkSize = size_t{1} << config.chunkQubits;
    size_t stride = size_t{1} << config.target;
    size_t bytes = chunkSize * sizeof(cuDoubleComplex);

    bool globalGate = stride >= chunkSize;
    int bufferCount = globalGate ? 2 : 1;

    if (bytes > static_cast<size_t>(INT_MAX)) {
        cerr << "Chunk exceeds supported request size\n";
        return 1;
    }

        constexpr size_t MiB = size_t{1} << 20;
    constexpr size_t hostBudget = 512 * MiB;
    constexpr size_t deviceBudget = 512 * MiB;

    size_t buffersPerSide =
        static_cast<size_t>(slotCount) * bufferCount;

    // Check before multiplying or allocating buffers.
    if (bytes > hostBudget / buffersPerSide ||
        bytes > deviceBudget / buffersPerSide) {
        cerr << "Configuration exceeds buffer memory budget\n";
        cerr << "Chunk bytes: " << bytes << '\n';
        cerr << "Buffers per memory side: " << buffersPerSide << '\n';
        cerr << "Host budget: " << hostBudget << " bytes\n";
        cerr << "Device budget: " << deviceBudget << " bytes\n";
        return 1;
    }

    size_t bufferBytes = bytes * buffersPerSide;

    cout << "Pinned host buffer bytes: " << bufferBytes << '\n';
    cout << "Device buffer bytes: " << bufferBytes << '\n';

    auto setupStart = chrono::steady_clock::now();

    vector<Slot> slots(slotCount);
    ChunkIO file;

    if (!file.openFile(
        "data/state.bin",
        count * sizeof(cuDoubleComplex)
    )) {
        return 1;
    }

    for (Slot& slot : slots) {
        for (int buffer = 0; buffer < bufferCount; buffer++) {
            check(cudaMallocHost(&slot.host[buffer], bytes));
            check(cudaMalloc(&slot.device[buffer], bytes));
        }

        check(cudaStreamCreateWithFlags(
            &slot.stream, cudaStreamNonBlocking
        ));

        check(cudaEventCreateWithFlags(
            &slot.done,
            cudaEventDisableTiming | cudaEventBlockingSync
        ));
    }

    size_t nextStart = 0;
    size_t completedJobs = 0;
    size_t totalJobs = count / chunkSize / bufferCount;
    int ioPending = 0;

    auto processingStart = chrono::steady_clock::now();

    while (completedJobs < totalJobs) {
        for (int index = 0; index < slotCount; index++) {
            Slot& slot = slots[index];

            // Completed GPU output can now be written.
            if (slot.phase == Phase::Computing) {
                cudaError_t result = cudaEventQuery(slot.done);

                if (result != cudaErrorNotReady) {
                    check(result);

                    if (!queueTransfers(
                        file, slot, index, bufferCount, bytes, true
                    )) {
                        return 1;
                    }

                    ioPending += bufferCount;
                }
            }

            // Assign another job only after all previous writes finish.
            if (slot.phase == Phase::Empty) {
                while (
                    nextStart < count &&
                    globalGate &&
                    (nextStart & stride) != 0
                ) {
                    nextStart += chunkSize;
                }

                if (nextStart < count) {
                    slot.position[0] =
                        nextStart * sizeof(cuDoubleComplex);

                    if (globalGate) {
                        slot.position[1] =
                            (nextStart + stride) *
                            sizeof(cuDoubleComplex);
                    }

                    nextStart += chunkSize;

                    if (!queueTransfers(
                        file, slot, index, bufferCount, bytes, false
                    )) {
                        return 1;
                    }

                    ioPending += bufferCount;
                }
            }
        }

        if (!file.submit()) {
            return 1;
        }

        if (ioPending > 0) {
            uint64_t id;

            if (!file.wait(id, bytes)) {
                return 1;
            }

            if (id >= uint64_t(slotCount) * 2) {
                cerr << "Invalid completion ID\n";
                return 1;
            }

            int slotIndex = static_cast<int>(id / 2);
            int buffer = static_cast<int>(id % 2);
            Slot& slot = slots[slotIndex];

            unsigned mask = 1u << buffer;

            if (
                buffer >= bufferCount ||
                slot.pending <= 0 ||
                (slot.completedBuffers & mask) != 0 ||
                (slot.phase != Phase::Reading && slot.phase != Phase::Writing)
            ) {
                cerr << "Unexpected completion\n";
                return 1;
            }

            slot.completedBuffers |= mask;
            slot.pending--;
            ioPending--;

            if (slot.pending == 0) {
                if (slot.phase == Phase::Reading) {
                    launchGPU(
                        slot, chunkSize, stride, bytes, globalGate
                    );
                } else {
                    slot.phase = Phase::Empty;
                    completedJobs++;
                }
            }
        } else {
            // With no disk requests outstanding, wait for one GPU
            // job so its writes can be queued on the next iteration.
            bool waited = false;

            for (Slot& slot : slots) {
                if (slot.phase == Phase::Computing) {
                    check(cudaEventSynchronize(slot.done));
                    waited = true;
                    break;
                }
            }

            if (!waited) {
                cerr << "Pipeline stalled\n";
                return 1;
            }
        }
    }

    auto processingEnd = chrono::steady_clock::now();

    for (Slot& slot : slots) {
        check(cudaStreamDestroy(slot.stream));
        check(cudaEventDestroy(slot.done));

        for (int buffer = 0; buffer < bufferCount; buffer++) {
            check(cudaFree(slot.device[buffer]));
            check(cudaFreeHost(slot.host[buffer]));
        }
    }

    double setupMs =
        chrono::duration<double, milli>(
            processingStart - setupStart
        ).count();

    double processingMs =
        chrono::duration<double, milli>(
            processingEnd - processingStart
        ).count();

    cout << fixed << setprecision(3);
    cout << "Setup time (ms): " << setupMs << '\n';
    cout << "Processing time (ms): " << processingMs << '\n';

    cout << "Applied pipelined GPU Hadamard to qubit " << config.target << '\n';
    cout << "Gate type: " << (globalGate ? "global" : "local") << '\n';
    cout << "Pipeline slots: " << slotCount << '\n';
    cout << "Completed jobs: " << completedJobs << '\n';

    return 0;
}