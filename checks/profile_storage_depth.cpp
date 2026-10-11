#include "../src/chunk_io.h"
#include <chrono>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <vector>
#include <unistd.h>
#include <algorithm>

using namespace std;
using Clock = chrono::steady_clock;

double milliseconds(Clock::time_point start, Clock::time_point end) {
    return chrono::duration<double, milli>(end - start).count();
}

bool createTestFile(const char* path, size_t fileBytes) {
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0644);

    if (fd < 0) {
        cerr << "Could not create test file: " << strerror(errno) << '\n';
        return false;
    }

    vector<unsigned char> block(size_t{1} << 20);

    for (size_t i = 0; i < block.size(); ++i) {
        block[i] = static_cast<unsigned char>((i * 131 + i / 4096) % 251);
    }

    for (size_t start = 0; start < fileBytes; start += block.size()) {
        size_t completed = 0;

        while (completed < block.size()) {
            ssize_t result = write(
                fd, block.data() + completed, block.size() - completed
            );

            if (result < 0 && errno == EINTR) {
                continue;
            }

            if (result <= 0) {
                cerr << "Could not initialize test file\n";
                close(fd);
                return false;
            }

            completed += static_cast<size_t>(result);
        }
    }

    if (fsync(fd) != 0) {
        cerr << "Could not flush test file\n";
        close(fd);
        return false;
    }

    return close(fd) == 0;
}

bool flushFile(const char* path) {
    int fd = open(path, O_RDWR);

    if (fd < 0) {
        return false;
    }

    bool success = fsync(fd) == 0;

    if (close(fd) != 0) {
        success = false;
    }

    return success;
}

bool verifyTestFile(const char* path, size_t fileBytes) {
    ifstream file(path, ios::binary);
    vector<unsigned char> block(size_t{1} << 20);

    for (size_t start = 0; start < fileBytes; start += block.size()) {
        file.read(
            reinterpret_cast<char*>(block.data()),
            static_cast<streamsize>(block.size())
        );

        if (!file) {
            return false;
        }

        for (size_t i = 0; i < block.size(); ++i) {
            unsigned char expected =
                static_cast<unsigned char>((i * 131 + i / 4096) % 251);

            if (block[i] != expected) {
                return false;
            }
        }
    }

    return true;
}

int main(int argc, char* argv[]) {
    if (argc != 3) {
        cerr << "Usage: " << argv[0] << " <test-file> <output.csv>\n";
        return 1;
    }

    constexpr size_t fileBytes = size_t{1} << 28;
    constexpr size_t MiB = size_t{1} << 20;
    constexpr int trials = 3;

    const int chunkOptions[] = {14, 16, 20};

    if (!createTestFile(argv[1], fileBytes)) {
        return 1;
    }

    ofstream csv(argv[2]);

    if (!csv) {
        cerr << "Could not open results file\n";
        return 1;
    }

    csv << "gate_type,chunk_qubits,chunk_bytes,slots,buffer_count,"
        "trial,jobs,processing_ms,logical_io_mib_per_second\n";

    csv << fixed << setprecision(6);
    cout << fixed << setprecision(3);

    struct IOSlot {
        void* buffers[2] = {nullptr, nullptr};
        uint64_t positions[2] = {0, 0};

        bool writing = false;
        int pending = 0;
        unsigned completedBuffers = 0;
    };

    for (int chunkBits : chunkOptions) {
        size_t bytes = (size_t{1} << chunkBits) * 16;

        for (int bufferCount : {1, 2}) {
            bool globalGate = bufferCount == 2;
            size_t jobs = fileBytes / bytes / bufferCount;

            for (int slotCount = 1; slotCount <= 4; ++slotCount) {
                vector<IOSlot> slots(slotCount);

                for (IOSlot& slot : slots) {
                    for (int buffer = 0; buffer < bufferCount; ++buffer) {
                        int result = posix_memalign(
                            &slot.buffers[buffer], 4096, bytes
                        );

                        if (result != 0) {
                            cerr << "Buffer allocation failed: "
                                << strerror(result) << '\n';
                            return 1;
                        }
                    }
                }

                ChunkIO file;

                if (!file.openFile(argv[1], fileBytes, true)) {
                    return 1;
                }

                auto beginIO = [&](int index, bool writing) {
                    IOSlot& slot = slots[index];

                    slot.writing = writing;
                    slot.pending = bufferCount;
                    slot.completedBuffers = 0;

                    for (int buffer = 0; buffer < bufferCount; ++buffer) {
                        uint64_t id = uint64_t(index) * 2 + buffer;

                        bool success = writing
                            ? file.queueWrite(
                                slot.positions[buffer],
                                slot.buffers[buffer],
                                bytes,
                                id
                            )
                            : file.queueRead(
                                slot.positions[buffer],
                                slot.buffers[buffer],
                                bytes,
                                id
                            );

                        if (!success) {
                            return false;
                        }
                    }

                    return file.submit();
                };

                vector<double> times;

                // Trial 0 is a warm-up.
                for (int trial = 0; trial <= trials; ++trial) {
                    if (!flushFile(argv[1])) {
                        cerr << "Could not flush before trial\n";
                        return 1;
                    }

                    size_t nextJob = 0;
                    size_t completedJobs = 0;

                    auto startRead = [&](int index) {
                        IOSlot& slot = slots[index];

                        slot.positions[0] = nextJob * bytes;
                        slot.positions[1] =
                            nextJob * bytes + fileBytes / 2;

                        ++nextJob;
                        return beginIO(index, false);
                    };

                    auto start = Clock::now();

                    for (int index = 0; index < slotCount; ++index) {
                        if (nextJob < jobs && !startRead(index)) {
                            return 1;
                        }
                    }

                    while (completedJobs < jobs) {
                        uint64_t id = 0;

                        if (!file.wait(id, bytes)) {
                            return 1;
                        }

                        if (id >= uint64_t(slotCount) * 2) {
                            cerr << "Invalid completion ID\n";
                            return 1;
                        }

                        int index = static_cast<int>(id / 2);
                        int buffer = static_cast<int>(id % 2);
                        IOSlot& slot = slots[index];

                        unsigned mask = 1u << buffer;

                        if (
                            buffer >= bufferCount ||
                            slot.pending <= 0 ||
                            (slot.completedBuffers & mask) != 0
                        ) {
                            cerr << "Unexpected completion\n";
                            return 1;
                        }

                        slot.completedBuffers |= mask;
                        --slot.pending;

                        if (slot.pending != 0) {
                            continue;
                        }

                        if (!slot.writing) {
                            // Write back the same bytes after reads finish.
                            if (!beginIO(index, true)) {
                                return 1;
                            }
                        } else {
                            ++completedJobs;

                            if (nextJob < jobs && !startRead(index)) {
                                return 1;
                            }
                        }
                    }

                    double elapsed = milliseconds(start, Clock::now());

                    if (trial == 0) {
                        continue;
                    }

                    times.push_back(elapsed);

                    // Each pass reads and writes the entire test file.
                    double logicalRate =
                        (2.0 * fileBytes / MiB) / (elapsed / 1000.0);

                    csv << (globalGate ? "global" : "local") << ','
                        << chunkBits << ',' << bytes << ','
                        << slotCount << ',' << bufferCount << ','
                        << trial << ',' << jobs << ','
                        << elapsed << ',' << logicalRate << '\n';

                    csv.flush();
                }

                sort(times.begin(), times.end());
                double medianMs = times[times.size() / 2];

                cout << (globalGate ? "global" : "local")
                    << ", chunk=" << double(bytes) / MiB << " MiB"
                    << ", slots=" << slotCount
                    << ": median=" << medianMs << " ms"
                    << ", range=" << times.front()
                    << "–" << times.back() << " ms\n";

                for (IOSlot& slot : slots) {
                    for (int buffer = 0; buffer < bufferCount; ++buffer) {
                        free(slot.buffers[buffer]);
                    }
                }
            }
        }
    }

    csv.close();

    if (!csv || !flushFile(argv[1]) ||
        !verifyTestFile(argv[1], fileBytes)) {
        cerr << "Results writing or test-file verification failed\n";
        return 1;
    }

    cout << "Storage depth test-file verification PASSED\n";

    if (unlink(argv[1]) != 0) {
        cerr << "Could not remove temporary test file\n";
        return 1;
    }

    cout << "Results saved: " << argv[2] << '\n';
    return 0;
}