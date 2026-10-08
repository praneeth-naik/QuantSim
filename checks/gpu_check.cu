#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>

void check(cudaError_t result) {
    if (result != cudaSuccess) {
        printf("CUDA error: %s\n", cudaGetErrorString(result));
        exit(1);
    }
}

__global__ void setValue(int* value) {
    *value = 42;
}

int main() {
    cudaDeviceProp properties;
    check(cudaGetDeviceProperties(&properties, 0));
    printf("GPU: %s\n", properties.name);

    int* deviceValue;
    int hostValue = 0;

    check(cudaMalloc(&deviceValue, sizeof(int)));

    setValue<<<1, 1>>>(deviceValue);
    check(cudaGetLastError());

    check(cudaMemcpy(&hostValue, deviceValue, sizeof(int), cudaMemcpyDeviceToHost));

    check(cudaFree(deviceValue));

    printf("Result: %d\n", hostValue);
    return hostValue == 42 ? 0 : 1;
}