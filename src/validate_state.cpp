#include <iostream>
#include <fstream>
#include <complex>
#include <cmath>
#include <cstdlib>

using namespace std;

int main(int argc, char* argv[]) {
    int n = 3;

    if (argc != 2) {
        cerr << "Usage: " << argv[0] << " <target>\n";
        return 1;
    }

    char* end;
    long targetArgument = strtol(argv[1], &end, 10);

    if (end == argv[1] || *end != '\0' ||
        targetArgument < 0 || targetArgument >= n) {
        cerr << "Target must be an integer from 0 to " << n - 1 << '\n';
        return 1;
    }

    int target = static_cast<int>(targetArgument);

    size_t count = size_t{1} << n;
    size_t partner = size_t{1} << target;
    double scale = 1.0 / sqrt(2.0);
    double tolerance = 1e-12;
    double maxError = 0.0;

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

    for (size_t i = 0; i < count; i++) {
        complex<double> actual;

        file.read(
            reinterpret_cast<char*>(&actual),
            sizeof(actual)
        );

        if (!file) {
            cerr << "Could not read amplitude\n";
            return 1;
        }

        complex<double> expected(0.0, 0.0);

        if (i == 0 || i == partner) {
            expected = scale;
        }

        double error = abs(actual - expected);

        if (!isfinite(error)) {
            cerr << "Invalid amplitude at index " << i << '\n';
            return 1;
        }

        if (error > maxError) {
            maxError = error;
        }
    }

    cout << "Maximum amplitude error: " << maxError << '\n';

    if (maxError > tolerance) {
        cerr << "Validation Failed\n";
        return 1;
    }

    cout << "Validation Passed\n";
    return 0;
}