#include <iostream>
#include <fstream>
#include <vector>
#include <complex>
#include <algorithm>

using namespace std;

int main() {
    int n = 3;
    size_t count = size_t{1} << n;
    size_t chunkSize = 4;

    vector<complex<double>> buffer(chunkSize);

    ifstream file("data/state.bin", ios::binary | ios::ate);

    if (!file) {
        cerr << "Could not open state file\n";
        return 1;
    }

    streamoff expectedSize = count * sizeof(complex<double>);

    if (file.tellg() != expectedSize) {
        cerr << "Unexpected state file size\n";
        return 1;
    }

    file.seekg(0, ios::beg);

    double totalProbability = 0.0;

    for (size_t start = 0; start < count; start += chunkSize) {
        size_t entries = min(chunkSize, count - start);

        file.read(
            reinterpret_cast<char*>(buffer.data()),
            entries * sizeof(complex<double>)
        );

        if (!file) {
            cerr << "Could not read chunk\n";
            return 1;
        }

        cout << "Chunk " << start / chunkSize << '\n';

        for (size_t i = 0; i < entries; i++) {
            cout << start + i << ": " << buffer[i] << '\n';
            totalProbability += norm(buffer[i]);
        }
    }

    cout << "Total probability: " << totalProbability << '\n';

    return 0;
}