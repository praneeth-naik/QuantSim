#!/usr/bin/env bash

# Locate the project root from this script's location.
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." || exit 1

quantsim_use_external() {
    local quantsim_mount="/media/praneeth/Crucial X6"
    local quantsim_storage="$quantsim_mount/QuantSim-storage"
    local quantsim_name

    if ! mountpoint -q "$quantsim_mount"; then
        echo "External SSD is not mounted at $quantsim_mount"
        return 1
    fi

    # Allow verification again if setup is already complete.
    if [ -L data ] && [ -L results ] && [ "$(readlink -f data)" = "$quantsim_storage/data" ] && [ "$(readlink -f results)" = "$quantsim_storage/results" ]; then
        echo "External storage is already configured"
        return 0
    fi

    for quantsim_name in data results; do
        if [ -L "$quantsim_name" ] || [ -e "$quantsim_storage/$quantsim_name" ] || [ -L "$quantsim_storage/$quantsim_name" ]; then
            echo "Existing link or destination: $quantsim_name"
            return 1
        fi

        if [ -e "$quantsim_name" ] && [ ! -d "$quantsim_name" ]; then
            echo "Expected a directory: $quantsim_name"
            return 1
        fi
    done

    mkdir -p "$quantsim_storage" || return 1

    for quantsim_name in data results; do
        if [ -d "$quantsim_name" ]; then
            mv "$quantsim_name" "$quantsim_storage/$quantsim_name" ||
                return 1
        else
            mkdir "$quantsim_storage/$quantsim_name" || return 1
        fi

        ln -s "$quantsim_storage/$quantsim_name" "$quantsim_name" ||
            return 1
    done
}

quantsim_use_external || exit 1

readlink -f data
readlink -f results
findmnt -T "$(readlink -f data)" -o SOURCE,FSTYPE,TARGET
df -h data

./build/direct_io_check