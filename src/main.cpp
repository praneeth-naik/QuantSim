#include <iostream>
#include <vector>
#include <complex>
#include <cmath>
#include <utility>

using namespace std;

void applyHadamard(vector<complex<double>>& state, int target) {
    size_t stride = size_t{1} << target;
    double scale = 1.0 / sqrt(2.0);

    for (size_t base = 0; base < state.size(); base += 2 * stride) {
        for (size_t offset = 0; offset < stride; offset++) {
            size_t i = base + offset;
            size_t j = i + stride;

            complex<double> a = state[i];
            complex<double> b = state[j];

            state[i] = (a + b) * scale;
            state[j] = (a - b) * scale;
        }
    }
}

void applyCNOT(vector<complex<double>>& state, int control, int target) {
    size_t controlMask = size_t{1} << control;
    size_t targetMask = size_t{1} << target;

    for (size_t i = 0; i < state.size(); i++) {
        if ((i & controlMask) != 0 && (i & targetMask) == 0) {
            size_t j = i | targetMask;
            swap(state[i], state[j]);
        }
    }
}

int main() {
    int n = 3;
    size_t count = size_t{1} << n;

    vector<complex<double>> state(count, complex<double>(0.0, 0.0));
    state[0] = 1.0;

    applyHadamard(state, 0);
    applyCNOT(state, 0, 1);

    cout << "Qubits: " << n << '\n';
    cout << "Amplitudes: " << count << '\n';

    for (size_t i = 0; i < count; i++) {
        cout << i << ": " << state[i] << '\n';
    }

    return 0;
}