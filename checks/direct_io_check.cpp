#include <liburing.h>
#include <fcntl.h>
#include <unistd.h>
#include <cstdlib>
#include <cstring>
#include <cerrno>
#include <iostream>

using namespace std;

int main() {
    constexpr size_t bytes = 4096;

    void* buffer = nullptr;
    int result = posix_memalign(&buffer, 4096, bytes);

    if (result != 0) {
        cerr << "Allocation error: " << strerror(result) << '\n';
        return 1;
    }

    int fd = open(
        "data/direct_io_test.bin",
        O_CREAT | O_TRUNC | O_RDWR | O_DIRECT,
        0644
    );

    if (fd < 0) {
        cerr << "Direct open error: " << strerror(errno) << '\n';
        free(buffer);
        return 1;
    }

    io_uring ring{};
    result = io_uring_queue_init(8, &ring, 0);

    if (result < 0) {
        cerr << "Queue error: " << strerror(-result) << '\n';
        close(fd);
        free(buffer);
        return 1;
    }

    auto finish = [&](int status) {
        io_uring_queue_exit(&ring);
        close(fd);
        free(buffer);
        return status;
    };

    auto transfer = [&](bool writing) {
        io_uring_sqe* request = io_uring_get_sqe(&ring);

        if (!request) {
            cerr << "Could not obtain submission entry\n";
            return false;
        }

        if (writing) {
            io_uring_prep_write(request, fd, buffer, bytes, 0);
        } else {
            io_uring_prep_read(request, fd, buffer, bytes, 0);
        }

        int submitted = io_uring_submit(&ring);

        if (submitted != 1) {
            cerr << "Submission failed: " << submitted << '\n';
            return false;
        }

        io_uring_cqe* completion = nullptr;
        int waited;

        do {
            waited = io_uring_wait_cqe(&ring, &completion);
        } while (waited == -EINTR);

        if (waited < 0) {
            cerr << "Wait error: " << strerror(-waited) << '\n';
            return false;
        }

        int completedBytes = completion->res;
        io_uring_cqe_seen(&ring, completion);

        if (completedBytes < 0) {
            cerr << "Direct I/O error: "
                 << strerror(-completedBytes) << '\n';
            return false;
        }

        if (completedBytes != static_cast<int>(bytes)) {
            cerr << "Incomplete transfer: "
                 << completedBytes << " bytes\n";
            return false;
        }

        cout << (writing ? "Direct write" : "Direct read")
             << ": " << completedBytes << " bytes\n";

        return true;
    };

    auto* data = static_cast<unsigned char*>(buffer);

    // Write a recognizable pattern.
    for (size_t index = 0; index < bytes; index++) {
        data[index] = static_cast<unsigned char>(index % 251);
    }

    if (!transfer(true)) {
        return finish(1);
    }

    // Clear the buffer so validation checks the read result.
    memset(buffer, 0, bytes);

    if (!transfer(false)) {
        return finish(1);
    }

    for (size_t index = 0; index < bytes; index++) {
        if (data[index] !=
            static_cast<unsigned char>(index % 251)) {
            cerr << "Data mismatch at byte " << index << '\n';
            return finish(1);
        }
    }

    cout << "Direct I/O validation PASSED\n";
    return finish(0);
}