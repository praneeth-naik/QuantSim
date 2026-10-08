#pragma once

#include <cuda_runtime.h>
#include <cuComplex.h>

__global__ void hadamardPair(
    cuDoubleComplex* first,
    cuDoubleComplex* second,
    size_t count
) {
    size_t i = size_t(blockIdx.x) * blockDim.x + threadIdx.x;

    if (i >= count) {
        return;
    }

    cuDoubleComplex a = first[i];
    cuDoubleComplex b = second[i];

    double scale = 0.7071067811865475244;

    first[i] = make_cuDoubleComplex(
        (a.x + b.x) * scale,
        (a.y + b.y) * scale
    );

    second[i] = make_cuDoubleComplex(
        (a.x - b.x) * scale,
        (a.y - b.y) * scale
    );
}