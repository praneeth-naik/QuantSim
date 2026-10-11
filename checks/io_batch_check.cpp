#include "../src/chunk_io.h"
#include <complex>
#include <iostream>

using namespace std;

int main() {
    constexpr size_t chunkSize = 4;
    constexpr size_t bytes = chunkSize * sizeof(complex<double>);

    // Keep buffers alive until their requests complete.
    complex<double> buffers[2][chunkSize]{};
    bool seen[2] = {false, false};

    ChunkIO file;

    if (!file.openFile("data/state.bin", 256)) {
        return 1;
    }

    if (!file.queueRead(0, buffers[0], bytes, 0) ||
        !file.queueRead(128, buffers[1], bytes, 1) ||
        !file.submit()) {
        return 1;
    }

    bool valid = true;

    for (int completed = 0; completed < 2; completed++) {
        uint64_t id;

        if (!file.wait(id, bytes)) {
            return 1;
        }

        cout << "Completed read " << id << '\n';

        if (id >= 2 || seen[id]) {
            valid = false;
        } else {
            seen[id] = true;
        }
    }

    for (size_t chunk = 0; chunk < 2; chunk++) {
        for (size_t index = 0; index < chunkSize; index++) {
            complex<double> expected =
                (chunk == 0 && index == 0)
                ? complex<double>(1.0, 0.0)
                : complex<double>(0.0, 0.0);

            if (buffers[chunk][index] != expected) {
                valid = false;
            }
        }
    }

    if (!valid || !seen[0] || !seen[1]) {
        cerr << "Async ChunkIO validation Failed\n";
        return 1;
    }

    cout << "Async ChunkIO validation Passed\n";
    return 0;
}