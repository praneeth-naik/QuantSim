#include <iostream>
#include <fstream>
#include <vector>
#include <complex>
#include <algorithm>
#include "config.h"

using namespace std;

int main(int argc, char* argv[]) {
    Config config;

    if (!parseConfig(argc, argv, config)) {
        return 1;
    }

    size_t count = size_t{1} << config.qubits;
    size_t chunkSize = size_t{1} << config.chunkQubits;

    vector<complex<double>> buffer(chunkSize);

    ofstream file("data/state.bin", ios::binary | ios::trunc);

    if (!file) {
        cerr << "Could not open state file\n";
        return 1;
    }

    for (size_t start = 0; start < count; start += chunkSize) {
        fill(buffer.begin(), buffer.end(), complex<double>(0.0, 0.0));

        if (start == 0) {
            buffer[0] = 1.0;
        }

        size_t entries = min(chunkSize, count - start);

        file.write(
            reinterpret_cast<const char*>(buffer.data()),
            entries * sizeof(complex<double>)
        );

        if (!file) {
            cerr << "Could not write state file\n";
            return 1;
        }
    }

    file.close();

    if (!file) {
        cerr << "Could not finish writing state file\n";
        return 1;
    }

    cout << "State file created: data/state.bin\n";
    cout << "File size: " << count * sizeof(complex<double>) << " bytes\n";
    cout << "Buffer size: " << chunkSize * sizeof(complex<double>) << " bytes\n";

    return 0;
}