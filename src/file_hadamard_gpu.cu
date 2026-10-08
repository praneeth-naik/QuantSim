#include "hadamard_gpu.cuh"
#include <iostream>
#include <fstream>
#include <vector>
#include <cstdlib>
#include "config.h"

using namespace std;

void check(cudaError_t result) {
    if (result != cudaSuccess) {
        cerr << "CUDA error: " << cudaGetErrorString(result) << '\n';
        exit(1);
    }
}

bool readChunk(fstream& file, streamoff position, vector<cuDoubleComplex>& chunk) {
    file.seekg(position, ios::beg);
    file.read(
        reinterpret_cast<char*>(chunk.data()),
        chunk.size() * sizeof(cuDoubleComplex)
    );
    return bool(file);
}

bool writeChunk(fstream& file, streamoff position,
                const vector<cuDoubleComplex>& chunk) {
    file.seekp(position, ios::beg);
    file.write(
        reinterpret_cast<const char*>(chunk.data()),
        chunk.size() * sizeof(cuDoubleComplex)
    );
    return bool(file);
}

int main(int argc, char* argv[]) {
    Config config;

    if (!parseConfig(argc, argv, config)) {
        return 1;
    }

    int target = config.target;

    size_t count = size_t{1} << config.qubits;
    size_t chunkSize = size_t{1} << config.chunkQubits;
    size_t stride = size_t{1} << target;
    size_t bytes = chunkSize * sizeof(cuDoubleComplex);

    bool globalGate = stride >= chunkSize;

    vector<cuDoubleComplex> first(chunkSize);
    vector<cuDoubleComplex> second(globalGate ? chunkSize : 0);

    fstream file("data/state.bin", ios::binary | ios::in | ios::out | ios::ate);

    if (!file) {
        cerr << "Could not open state file\n";
        return 1;
    }

    streamoff expectedSize = count * sizeof(cuDoubleComplex);

    if (file.tellg() != expectedSize) {
        cerr << "Unexpected state file size\n";
        return 1;
    }

    cuDoubleComplex* deviceFirst;
    cuDoubleComplex* deviceSecond = nullptr;

    check(cudaMalloc(&deviceFirst, bytes));

    if (globalGate) {
        check(cudaMalloc(&deviceSecond, bytes));
    }

    int threads = 128;
    int blocks = (chunkSize + threads - 1) / threads;

    for (size_t start = 0; start < count; start += chunkSize) {
        if (globalGate && (start & stride) != 0) {
            continue;
        }

        streamoff position = start * sizeof(cuDoubleComplex);
        streamoff partnerPosition = (start + stride) * sizeof(cuDoubleComplex);

        if (!readChunk(file, position, first) ||
            (globalGate && !readChunk(file, partnerPosition, second))) {
            cerr << "Could not read chunks\n";
            return 1;
        }

        check(cudaMemcpy(deviceFirst, first.data(), bytes, cudaMemcpyHostToDevice));

        if (globalGate) {
            check(cudaMemcpy(deviceSecond, second.data(), bytes, cudaMemcpyHostToDevice));

            hadamardPair<<<blocks, threads>>>(
                deviceFirst, deviceSecond, chunkSize
            );
        } else {
            hadamardLocal<<<blocks, threads>>>(
                deviceFirst, chunkSize, stride
            );
        }

        check(cudaGetLastError());

        check(cudaMemcpy(first.data(), deviceFirst, bytes, cudaMemcpyDeviceToHost));

        if (globalGate) {
            check(cudaMemcpy(second.data(), deviceSecond, bytes, cudaMemcpyDeviceToHost));
        }

        if (!writeChunk(file, position, first) ||
            (globalGate && !writeChunk(file, partnerPosition, second))) {
            cerr << "Could not write chunks\n";
            return 1;
        }
    }

    file.close();

    if (!file) {
        cerr << "Could not finish writing state file\n";
        return 1;
    }

    check(cudaFree(deviceFirst));

    if (globalGate) {
        check(cudaFree(deviceSecond));
    }

    cout << "Applied GPU Hadamard to qubit " << target << '\n';
    cout << "Gate type: " << (globalGate ? "global" : "local") << '\n';
    return 0;
}