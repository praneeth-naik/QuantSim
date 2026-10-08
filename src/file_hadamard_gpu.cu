#include "hadamard_gpu.cuh"
#include <iostream>
#include <fstream>
#include <vector>
#include <cstdlib>

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

int main() {
    int n = 3;
    int target = 2;

    size_t count = size_t{1} << n;
    size_t chunkSize = 4;
    size_t stride = size_t{1} << target;
    size_t bytes = chunkSize * sizeof(cuDoubleComplex);

    if (stride < chunkSize) {
        cerr << "This version handles cross-chunk gates only\n";
        return 1;
    }

    vector<cuDoubleComplex> first(chunkSize);
    vector<cuDoubleComplex> second(chunkSize);

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
    cuDoubleComplex* deviceSecond;

    check(cudaMalloc(&deviceFirst, bytes));
    check(cudaMalloc(&deviceSecond, bytes));

    int threads = 128;
    int blocks = (chunkSize + threads - 1) / threads;

    for (size_t start = 0; start < count; start += chunkSize) {
        if ((start & stride) != 0) {
            continue;
        }

        streamoff position = start * sizeof(cuDoubleComplex);
        streamoff partnerPosition = (start + stride) * sizeof(cuDoubleComplex);

        if (!readChunk(file, position, first) ||
            !readChunk(file, partnerPosition, second)) {
            cerr << "Could not read chunk pair\n";
            return 1;
        }

        check(cudaMemcpy(deviceFirst, first.data(), bytes, cudaMemcpyHostToDevice));
        check(cudaMemcpy(deviceSecond, second.data(), bytes, cudaMemcpyHostToDevice));

        hadamardPair<<<blocks, threads>>>(deviceFirst, deviceSecond, chunkSize);
        check(cudaGetLastError());

        check(cudaMemcpy(first.data(), deviceFirst, bytes, cudaMemcpyDeviceToHost));
        check(cudaMemcpy(second.data(), deviceSecond, bytes, cudaMemcpyDeviceToHost));

        if (!writeChunk(file, position, first) ||
            !writeChunk(file, partnerPosition, second)) {
            cerr << "Could not write chunk pair\n";
            return 1;
        }
    }

    file.close();

    if (!file) {
        cerr << "Could not finish writing state file\n";
        return 1;
    }

    check(cudaFree(deviceFirst));
    check(cudaFree(deviceSecond));

    cout << "Applied GPU Hadamard to qubit " << target << '\n';
    return 0;
}