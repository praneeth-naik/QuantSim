#include "../src/hadamard_gpu.cuh"

#include <array>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <vector>

using namespace std;

void check(cudaError_t result) {
    if (result != cudaSuccess) {
        cerr << "CUDA error: " << cudaGetErrorString(result) << '\n';
        exit(1);
    }
}

double median(vector<float> values) {
    for (size_t i = 1; i < values.size(); ++i) {
        float value = values[i];
        size_t j = i;

        while (j > 0 && values[j - 1] > value) {
            values[j] = values[j - 1];
            --j;
        }

        values[j] = value;
    }

    size_t middle = values.size() / 2;

    if (values.size() % 2 != 0) {
        return values[middle];
    }

    return (double(values[middle - 1]) + values[middle]) / 2.0;
}

int main(int argc, char* argv[]) {
    if (argc != 2) {
        cerr << "Usage: " << argv[0] << " <output.csv>\n";
        return 1;
    }

    ofstream csv(argv[1]);

    if (!csv) {
        cerr << "Could not create calibration file\n";
        return 1;
    }

    csv << "gate_type,chunk_qubits,target,trial,"
        << "chunk_bytes,buffer_count,"
        << "h2d_ms,kernel_ms,d2h_ms\n";
    csv << fixed << setprecision(6);

    cout << fixed << setprecision(6);

    constexpr int repeats = 10;
    const int chunkOptions[] = {14, 16, 20};

    for (int chunkBits : chunkOptions) {
        size_t chunkSize = size_t{1} << chunkBits;
        size_t bytes = chunkSize * sizeof(cuDoubleComplex);

        // Test every local target, followed by the paired-chunk kernel.
        for (int target = 0; target <= chunkBits; target++) {
            bool globalGate = target == chunkBits;
            int bufferCount = globalGate ? 2 : 1;
            size_t stride = size_t{1} << target;

            cuDoubleComplex* host[2] = {nullptr, nullptr};
            cuDoubleComplex* device[2] = {nullptr, nullptr};

            double amplitude =
                1.0 / sqrt(double(chunkSize) * bufferCount);

            for (int buffer = 0; buffer < bufferCount; buffer++) {
                check(cudaMallocHost(&host[buffer], bytes));
                check(cudaMalloc(&device[buffer], bytes));

                for (size_t index = 0; index < chunkSize; index++) {
                    host[buffer][index] =
                        make_cuDoubleComplex(amplitude, 0.0);
                }
            }

            cudaStream_t stream;
            check(cudaStreamCreateWithFlags(
                &stream, cudaStreamNonBlocking
            ));

            cudaEvent_t events[4]{};

            for (auto& event : events) {
                // Timing must be enabled for these events.
                check(cudaEventCreate(&event));
            }

            int threads = 128;
            size_t workItems =
                globalGate ? chunkSize : chunkSize / 2;

            int blocks = static_cast<int>(
                (workItems + threads - 1) / threads
            );

            auto runGPU = [&]() {
                check(cudaEventRecord(events[0], stream));

                for (int buffer = 0; buffer < bufferCount; buffer++) {
                    check(cudaMemcpyAsync(
                        device[buffer], host[buffer], bytes,
                        cudaMemcpyHostToDevice, stream
                    ));
                }

                check(cudaEventRecord(events[1], stream));

                if (globalGate) {
                    hadamardPair<<<blocks, threads, 0, stream>>>(
                        device[0], device[1], chunkSize
                    );
                } else {
                    hadamardLocal<<<blocks, threads, 0, stream>>>(
                        device[0], chunkSize, stride
                    );
                }

                check(cudaGetLastError());
                check(cudaEventRecord(events[2], stream));

                for (int buffer = 0; buffer < bufferCount; buffer++) {
                    check(cudaMemcpyAsync(
                        host[buffer], device[buffer], bytes,
                        cudaMemcpyDeviceToHost, stream
                    ));
                }

                check(cudaEventRecord(events[3], stream));
                check(cudaEventSynchronize(events[3]));

                array<float, 3> elapsed{};

                for (int phase = 0; phase < 3; phase++) {
                    check(cudaEventElapsedTime(
                        &elapsed[phase],
                        events[phase],
                        events[phase + 1]
                    ));
                }

                return elapsed;
            };

            // Warm this workload before collecting samples.
            auto warmUntil =
                chrono::steady_clock::now() +
                chrono::milliseconds(100);

            do {
                runGPU();
            } while (chrono::steady_clock::now() < warmUntil);

            array<vector<float>, 3> timings;

            for (int trial = 0; trial < repeats; trial++) {
                auto elapsed = runGPU();

                for (int phase = 0; phase < 3; phase++) {
                    timings[phase].push_back(elapsed[phase]);
                }

                csv << (globalGate ? "global" : "local") << ','
                    << chunkBits << ','
                    << target << ','
                    << trial + 1 << ','
                    << bytes << ','
                    << bufferCount << ','
                    << elapsed[0] << ','
                    << elapsed[1] << ','
                    << elapsed[2] << '\n';
            }

            csv.flush();

            // Show representative targets; save every target in CSV.
            if (target == 0 ||
                target == chunkBits - 1 ||
                globalGate) {
                double chunkMiB = double(bytes) / (1 << 20);

                cout << "chunk=" << chunkMiB
                    << " MiB, target=" << target
                    << ", " << (globalGate ? "global" : "local")
                    << ": H2D=" << median(timings[0])
                    << " ms, kernel=" << median(timings[1])
                    << " ms, D2H=" << median(timings[2])
                    << " ms\n";
            }

            for (auto& event : events) {
                check(cudaEventDestroy(event));
            }

            check(cudaStreamDestroy(stream));

            for (int buffer = 0; buffer < bufferCount; buffer++) {
                check(cudaFree(device[buffer]));
                check(cudaFreeHost(host[buffer]));
            }
        }
    }

    csv.close();

    if (!csv) {
        cerr << "Could not finish writing calibration file\n";
        return 1;
    }

    cout << "Results saved: " << argv[1] << '\n';
    return 0;
}