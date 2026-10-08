#include "../src/hadamard_gpu.cuh"
#include <cstdio>
#include <cstdlib>

void check(cudaError_t result) {
    if (result != cudaSuccess) {
        printf("CUDA error: %s\n", cudaGetErrorString(result));
        exit(1);
    }
}

int main() {
    const int count = 4;
    size_t bytes = count * sizeof(cuDoubleComplex);

    cuDoubleComplex first[count] = {};
    cuDoubleComplex second[count] = {};

    first[0] = make_cuDoubleComplex(1.0, 0.0);

    cuDoubleComplex* deviceFirst;
    cuDoubleComplex* deviceSecond;

    check(cudaMalloc(&deviceFirst, bytes));
    check(cudaMalloc(&deviceSecond, bytes));

    check(cudaMemcpy(deviceFirst, first, bytes, cudaMemcpyHostToDevice));
    check(cudaMemcpy(deviceSecond, second, bytes, cudaMemcpyHostToDevice));

    hadamardPair<<<1, 128>>>(deviceFirst, deviceSecond, count);
    check(cudaGetLastError());

    check(cudaMemcpy(first, deviceFirst, bytes, cudaMemcpyDeviceToHost));
    check(cudaMemcpy(second, deviceSecond, bytes, cudaMemcpyDeviceToHost));

    check(cudaFree(deviceFirst));
    check(cudaFree(deviceSecond));

    for (int i = 0; i < count; i++) {
        printf("%d: (%f,%f)\n", i, first[i].x, first[i].y);
    }

    for (int i = 0; i < count; i++) {
        printf("%d: (%f,%f)\n", i + count, second[i].x, second[i].y);
    }

    return 0;
}