#include <liburing.h>
#include <fcntl.h>
#include <unistd.h>
#include <cerrno>
#include <cstring>
#include <iostream>
#include <vector>
#include <complex>

using namespace std;

int main() {
    int fd = open("data/state.bin", O_RDONLY);

    if (fd < 0) {
        cerr << "Could not open file: " << strerror(errno) << '\n';
        return 1;
    }

    io_uring ring;
    int result = io_uring_queue_init(8, &ring, 0);

    if (result < 0) {
        cerr << "Queue error: " << strerror(-result) << '\n';
        close(fd);
        return 1;
    }

    vector<complex<double>> buffer(4);
    unsigned bytes = buffer.size() * sizeof(complex<double>);

    io_uring_sqe* request = io_uring_get_sqe(&ring);

    if (!request) {
        cerr << "Could not obtain submission entry\n";
        io_uring_queue_exit(&ring);
        close(fd);
        return 1;
    }

    io_uring_prep_read(request, fd, buffer.data(), bytes, 0);

    result = io_uring_submit(&ring);

    if (result != 1) {
        cerr << "Unexpected submission result: " << result << '\n';
        io_uring_queue_exit(&ring);
        close(fd);
        return 1;
    }

    io_uring_cqe* completion;
    result = io_uring_wait_cqe(&ring, &completion);

    if (result < 0) {
        cerr << "Completion wait error: " << strerror(-result) << '\n';
        io_uring_queue_exit(&ring);
        close(fd);
        return 1;
    }

    int completedBytes = completion->res;
    io_uring_cqe_seen(&ring, completion);

    io_uring_queue_exit(&ring);
    close(fd);

    if (completedBytes < 0) {
        cerr << "Read error: " << strerror(-completedBytes) << '\n';
        return 1;
    }

    if (completedBytes != static_cast<int>(bytes)) {
        cerr << "Incomplete chunk read\n";
        return 1;
    }

    cout << "Bytes read: " << completedBytes << '\n';

    for (size_t i = 0; i < buffer.size(); i++) {
        cout << i << ": " << buffer[i] << '\n';
    }

    return 0;
}