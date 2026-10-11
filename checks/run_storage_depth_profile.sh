#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

quantsim_mount="/media/praneeth/Crucial X6"
quantsim_storage="$quantsim_mount/QuantSim-storage"

if ! mountpoint -q "$quantsim_mount"; then
    echo "External SSD is not mounted"
    exit 1
fi

mkdir -p "$quantsim_storage/data" "$quantsim_storage/results"

quantsim_stamp="$(date +%Y%m%d_%H%M%S)"

g++-11 -std=c++17 -O2 checks/profile_storage_depth.cpp \
    -o build/profile_storage_depth -luring

./build/profile_storage_depth \
    "$quantsim_storage/data/storage_depth_$quantsim_stamp.bin" \
    "$quantsim_storage/results/storage_depth_$quantsim_stamp.csv"