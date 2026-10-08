#include <iostream>
#include <fstream>
#include <vector>
#include <complex>
#include <cmath>

using namespace std;

int main() {
    int n = 3;
    int target = 0;

    size_t count = size_t{1} << n;
    size_t chunkSize = 4;
    size_t stride = size_t{1} << target;

    if (stride >= chunkSize) {
        cerr << "This gate requires cross-chunk processing\n";
        return 1;
    }

    vector<complex<double>> buffer(chunkSize);
    double scale = 1.0 / sqrt(2.0);

    fstream file("data/state.bin", ios::binary | ios::in | ios::out | ios::ate);

    if (!file) {
        cerr << "Could not open state file\n";
        return 1;
    }

    streamoff expectedSize = count * sizeof(complex<double>);

    if (file.tellg() != expectedSize) {
        cerr << "Unexpected state file size\n";
        return 1;
    }

    for (size_t start = 0; start < count; start += chunkSize) {
        streamoff position = start * sizeof(complex<double>);

        file.seekg(position, ios::beg);
        file.read(
            reinterpret_cast<char*>(buffer.data()),
            chunkSize * sizeof(complex<double>)
        );

        if (!file) {
            cerr << "Could not read chunk\n";
            return 1;
        }

        for (size_t base = 0; base < chunkSize; base += 2 * stride) {
            for (size_t offset = 0; offset < stride; offset++) {
                size_t i = base + offset;
                size_t j = i + stride;

                complex<double> a = buffer[i];
                complex<double> b = buffer[j];

                buffer[i] = (a + b) * scale;
                buffer[j] = (a - b) * scale;
            }
        }

        file.seekp(position, ios::beg);
        file.write(
            reinterpret_cast<const char*>(buffer.data()),
            chunkSize * sizeof(complex<double>)
        );

        if (!file) {
            cerr << "Could not write chunk\n";
            return 1;
        }
    }

    file.close();

    if (!file) {
        cerr << "Could not finish writing state file\n";
        return 1;
    }

    cout << "Applied Hadamard to qubit " << target << '\n';
    return 0;
}