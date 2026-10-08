#include <iostream>
#include <vector>
#include <complex>

using namespace std;

int main() {
    int n = 3;
    size_t count = size_t{1} << n;

    vector<complex<double>> state(count, complex<double>(0.0, 0.0));

    state[0] = 1.0;

    cout << "Qubits: " << n << '\n';
    cout << "Amplitudes: " << count << '\n';

    for (size_t i = 0; i < count; i++) {
        cout << i << ": " << state[i] << '\n';
    }

    return 0;
}