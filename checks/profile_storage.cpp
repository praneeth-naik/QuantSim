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

    csv << "gate_type,chunk_qubits,chunk_bytes,buffer_count,trial,jobs,"
            "read_ms,write_ms,read_ms_per_job,write_ms_per_job\n";
    csv << fixed << setprecision(6);
    cout << fixed << setprecision(6);

    for (int chunkBits : chunkOptions) {
        size_t bytes = (size_t{1} << chunkBits) * 16;

        for (int bufferCount : {1, 2}) {
            bool globalGate = bufferCount == 2;
            size_t jobs = fileBytes / bytes / bufferCount;
            void* buffers[2] = {nullptr, nullptr};

            for (int buffer = 0; buffer < bufferCount; ++buffer) {
                int result = posix_memalign(&buffers[buffer], 4096, bytes);

                if (result != 0) {
                    cerr << "Buffer allocation failed: " << strerror(result) << '\n';
                    return 1;
                }
            }

            ChunkIO file;

            if (!file.openFile(argv[1], fileBytes, true)) {
                return 1;
            }

            double totalRead = 0;
            double totalWrite = 0;

            // Trial 0 is a warm-up and is excluded from the results.
            for (int trial = 0; trial <= trials; ++trial) {
                if (!flushFile(argv[1])) {
                    cerr << "Could not flush before trial\n";
                    return 1;
                }

                double readMs = 0;
                double writeMs = 0;

                for (size_t job = 0; job < jobs; ++job) {
                    uint64_t positions[2] = {
                        static_cast<uint64_t>(job * bytes),
                        static_cast<uint64_t>(job * bytes + fileBytes / 2)
                    };

                    // Local: one chunk. Global: two paired chunks.
                    for (int writing = 0; writing <= 1; ++writing) {
                        auto start = Clock::now();

                        for (int buffer = 0; buffer < bufferCount; ++buffer) {
                            bool success = writing
                                ? file.queueWrite(
                                    positions[buffer], buffers[buffer],
                                    bytes, buffer
                                )
                                : file.queueRead(
                                    positions[buffer], buffers[buffer],
                                    bytes, buffer
                                );

                            if (!success) {
                                return 1;
                            }
                        }

                        if (!file.submit()) {
                            return 1;
                        }

                        unsigned completed = 0;

                        for (int request = 0; request < bufferCount; ++request) {
                            uint64_t id = 0;

                            if (!file.wait(id, bytes)) {
                                return 1;
                            }

                            if (id >= static_cast<uint64_t>(bufferCount) ||
                                (completed & (1u << id))) {
                                cerr << "Unexpected completion ID\n";
                                return 1;
                            }

                            completed |= 1u << id;
                        }

                        double elapsed = milliseconds(start, Clock::now());

                        if (writing) {
                            writeMs += elapsed;
                        } else {
                            readMs += elapsed;
                        }
                    }
                }

                if (trial == 0) {
                    continue;
                }

                totalRead += readMs;
                totalWrite += writeMs;

                csv << (globalGate ? "global" : "local") << ','
                    << chunkBits << ',' << bytes << ',' << bufferCount << ','
                    << trial << ',' << jobs << ','
                    << readMs << ',' << writeMs << ','
                    << readMs / jobs << ',' << writeMs / jobs << '\n';
                csv.flush();
            }

            cout << "chunk=" << double(bytes) / (size_t{1} << 20)
                << " MiB, " << (globalGate ? "global" : "local")
                << ": mean read/job=" << totalRead / trials / jobs
                << " ms, mean write/job=" << totalWrite / trials / jobs
                << " ms\n";

            for (int buffer = 0; buffer < bufferCount; ++buffer) {
                free(buffers[buffer]);
            }
        }
    }

    csv.close();

    if (!csv || !flushFile(argv[1]) ||
        !verifyTestFile(argv[1], fileBytes)) {
        cerr << "Results writing or test-file verification failed\n";
        return 1;
    }

    cout << "Storage test-file verification PASSED\n";

    if (unlink(argv[1]) != 0) {
        cerr << "Could not remove temporary test file\n";
        return 1;
    }

    cout << "Results saved: " << argv[2] << '\n';
    return 0;
}