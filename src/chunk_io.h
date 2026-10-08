#pragma once

#include <liburing.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <cerrno>
#include <climits>
#include <cstring>
#include <cstdint>
#include <iostream>

class ChunkIO {
    int fd = -1;
    io_uring ring{};
    bool ready = false;

    bool transfer(uint64_t position, void* buffer, size_t bytes, bool writing) {
        if (bytes > static_cast<size_t>(INT_MAX)) {
            std::cerr << "Chunk exceeds supported request size\n";
            return false;
        }

        io_uring_sqe* request = io_uring_get_sqe(&ring);

        if (!request) {
            std::cerr << "Could not obtain submission entry\n";
            return false;
        }

        if (writing) {
            io_uring_prep_write(request, fd, buffer, bytes, position);
        } else {
            io_uring_prep_read(request, fd, buffer, bytes, position);
        }

        int result = io_uring_submit(&ring);

        if (result != 1) {
            std::cerr << "Unexpected submission result: " << result << '\n';
            return false;
        }

        io_uring_cqe* completion;

        do {
            result = io_uring_wait_cqe(&ring, &completion);
        } while (result == -EINTR);

        if (result < 0) {
            std::cerr << "Completion error: " << strerror(-result) << '\n';
            return false;
        }

        int completedBytes = completion->res;
        io_uring_cqe_seen(&ring, completion);

        if (completedBytes < 0) {
            std::cerr << "I/O error: " << strerror(-completedBytes) << '\n';
            return false;
        }

        if (completedBytes != static_cast<int>(bytes)) {
            std::cerr << "Incomplete chunk transfer\n";
            return false;
        }

        return true;
    }

public:
    ChunkIO() = default;
    ChunkIO(const ChunkIO&) = delete;
    ChunkIO& operator=(const ChunkIO&) = delete;

    ~ChunkIO() {
        if (ready) {
            io_uring_queue_exit(&ring);
        }

        if (fd >= 0) {
            close(fd);
        }
    }

    bool openFile(const char* path, uint64_t expectedBytes) {
        fd = open(path, O_RDWR);

        if (fd < 0) {
            std::cerr << "Open error: " << strerror(errno) << '\n';
            return false;
        }

        struct stat info;

        if (fstat(fd, &info) != 0) {
            std::cerr << "File size check failed: " << strerror(errno) << '\n';
            return false;
        }

        if (info.st_size != static_cast<off_t>(expectedBytes)) {
            std::cerr << "Unexpected state file size\n";
            return false;
        }

        int result = io_uring_queue_init(8, &ring, 0);

        if (result < 0) {
            std::cerr << "Queue error: " << strerror(-result) << '\n';
            return false;
        }

        ready = true;
        return true;
    }

    bool read(uint64_t position, void* buffer, size_t bytes) {
        return transfer(position, buffer, bytes, false);
    }

    bool write(uint64_t position, void* buffer, size_t bytes) {
        return transfer(position, buffer, bytes, true);
    }
};