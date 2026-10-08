#include <liburing.h>
#include <fcntl.h>
#include <unistd.h>
#include <iostream>
#include <complex>
#include <cstdint>
#include <cerrno>
#include <cstring>

using namespace std;

int main() {
    constexpr size_t chunkSize = 4;
    constexpr size_t bytes = chunkSize * sizeof(complex<double>);

    complex<double> buffers[2][chunkSize]{};
    uint64_t positions[2] = {0, 8 * sizeof(complex<double>)};
    bool seen[2] = {false, false};

    int fd = open("data/state.bin", O_RDONLY);

    if (fd < 0) {
        cerr << "Open error: " << strerror(errno) << '\n';
        return 1;
    }

    io_uring ring{};
    int result = io_uring_queue_init(8, &ring, 0);

    if (result < 0) {
        cerr << "Queue error: " << strerror(-result) << '\n';
        close(fd);
        return 1;
    }

    auto finish = [&](int status) {
        io_uring_queue_exit(&ring);
        close(fd);
        return status;
    };

    // Prepare both requests without waiting for either one.
    for (uint64_t id = 0; id < 2; id++) {
        io_uring_sqe* request = io_uring_get_sqe(&ring);

        if (!request) {
            cerr << "Could not obtain submission entry\n";
            return finish(1);
        }

        io_uring_prep_read(
            request, fd, buffers[id], bytes, positions[id]
        );

        request->user_data = id;
    }

    int submitted = 0;

    while (submitted < 2) {
        result = io_uring_submit(&ring);

        if (result == -EINTR) {
            continue;
        }

        if (result <= 0) {
            cerr << "Submission failed: " << result << '\n';
            return finish(1);
        }

        submitted += result;
    }

    cout << "Requests submitted: " << submitted << '\n';

    bool valid = true;

    // Match completions by ID, without assuming their order.
    for (int completed = 0; completed < 2; completed++) {
        io_uring_cqe* completion = nullptr;

        do {
            result = io_uring_wait_cqe(&ring, &completion);
        } while (result == -EINTR);

        if (result < 0) {
            cerr << "Wait error: " << strerror(-result) << '\n';
            return finish(1);
        }

        uint64_t id = completion->user_data;
        int completedBytes = completion->res;

        io_uring_cqe_seen(&ring, completion);

        cout << "Completed read " << id << ": " << completedBytes << " bytes\n";

        if (id >= 2 || completedBytes != static_cast<int>(bytes)) {
            valid = false;
        } else if (seen[id]) {
            valid = false;
        } else {
            seen[id] = true;
        }
    }

    // The initialized state has amplitude 1 only at index 0.
    for (size_t chunk = 0; chunk < 2; chunk++) {
        for (size_t index = 0; index < chunkSize; index++) {
            complex<double> expected =
                (chunk == 0 && index == 0)
                ? complex<double>(1.0, 0.0)
                : complex<double>(0.0, 0.0);

            if (buffers[chunk][index] != expected) {
                valid = false;
            }
        }
    }

    if (!valid || !seen[0] || !seen[1]) {
        cerr << "Batch read validation FAILED\n";
        return finish(1);
    }

    cout << "Batch read validation PASSED\n";
    return finish(0);
}