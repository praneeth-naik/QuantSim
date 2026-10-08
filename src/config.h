#pragma once

#include <cstdlib>
#include <iostream>

struct Config {
    int qubits;
    int target;
    int chunkQubits;
};

inline bool parseInteger(const char* text, int minimum, int maximum, int& value) {
    char* end;
    long parsed = std::strtol(text, &end, 10);

    if (end == text || *end != '\0' ||
        parsed < minimum || parsed > maximum) {
        return false;
    }

    value = static_cast<int>(parsed);
    return true;
}

inline bool parseConfig(int argc, char* argv[], Config& config) {
    if (argc != 4) {
        std::cerr << "Usage: " << argv[0] << " <qubits> <target> <chunk_qubits>\n";
        return false;
    }

    if (!parseInteger(argv[1], 1, 35, config.qubits) ||
        !parseInteger(argv[2], 0, config.qubits - 1, config.target) ||
        !parseInteger(argv[3], 0, config.qubits, config.chunkQubits)) {
        std::cerr << "Invalid configuration: qubits must be 1–35, " << "target 0–qubits-1, and chunk_qubits 0–qubits\n";
        return false;
    }

    return true;
}