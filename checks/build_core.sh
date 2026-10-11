#!/usr/bin/env bash
set -euo pipefail

quantsim_root="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &&
    pwd
)"

cd "$quantsim_root"

for quantsim_tool in g++-11 nvcc; do
    if ! command -v "$quantsim_tool" >/dev/null 2>&1; then
        echo "Required compiler not found: $quantsim_tool" >&2
        exit 1
    fi
done

mkdir -p build

echo "Building state initializer..."
g++-11 -std=c++17 -O2 \
    src/init_state.cpp \
    -o build/init_state

echo "Building state validator..."
g++-11 -std=c++17 -O2 \
    src/validate_state.cpp \
    -o build/validate_state

echo "Building direct-I/O GPU pipeline..."
nvcc -ccbin g++-11 -std=c++17 -O3 \
    src/file_hadamard_direct.cu \
    -o build/file_hadamard_direct \
    -luring

echo "Core build completed successfully."