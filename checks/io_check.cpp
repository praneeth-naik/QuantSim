#include <liburing.h>
#include <cstdio>
#include <cstring>

int main() {
    io_uring ring;

    int result = io_uring_queue_init(8, &ring, 0);

    if (result < 0) {
        printf("io_uring error: %s\n", strerror(-result));
        return 1;
    }

    printf("io_uring queue created successfully\n");

    io_uring_queue_exit(&ring);
    return 0;
}