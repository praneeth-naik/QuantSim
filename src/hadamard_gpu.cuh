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

__global__ void hadamardLocal(
    cuDoubleComplex* state,
    size_t count,
    size_t stride
) {
    size_t pair = size_t(blockIdx.x) * blockDim.x + threadIdx.x;

    if (pair >= count / 2) {
        return;
    }

    size_t i = (pair / stride) * (2 * stride) + pair % stride;
    size_t j = i + stride;

    cuDoubleComplex a = state[i];
    cuDoubleComplex b = state[j];

    double scale = 0.7071067811865475244;

    state[i] = make_cuDoubleComplex(
        (a.x + b.x) * scale,
        (a.y + b.y) * scale
    );

    state[j] = make_cuDoubleComplex(
        (a.x - b.x) * scale,
        (a.y - b.y) * scale
    );
}