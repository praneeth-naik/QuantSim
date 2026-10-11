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

    bool directIO = false;
    static constexpr size_t directAlignment = 4096;

    int queued = 0;
    int outstanding = 0;

    bool queue(uint64_t position, void* buffer, size_t bytes, uint64_t id, bool writing) {
        if (!ready || bytes > static_cast<size_t>(INT_MAX)) {
            std::cerr << "Invalid I/O request\n";
            return false;
        }

        if (directIO &&
            (position % directAlignment != 0 || bytes % directAlignment != 0 || reinterpret_cast<uintptr_t>(buffer)%directAlignment != 0)) {
            std::cerr << "Unaligned direct I/O request\n";
            return false;
        }

        io_uring_sqe* request = io_uring_get_sqe(&ring);

        if (!request) {
            std::cerr << "Submission queue is full\n";
            return false;
        }

        if (writing) {
            io_uring_prep_write(request, fd, buffer, bytes, position);
        } else {
            io_uring_prep_read(request, fd, buffer, bytes, position);
        }

        request->user_data = id;
        queued++;
        return true;
    }

    bool transfer(uint64_t position, void* buffer, size_t bytes, bool writing) {
        if (queued != 0 || outstanding != 0) {
            std::cerr << "Blocking transfer requires an idle queue\n";
            return false;
        }

        uint64_t completedId = 0;

        return queue(position, buffer, bytes, 0, writing)
            && submit()
            && wait(completedId, bytes);
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

        bool openFile(const char* path, uint64_t expectedBytes, bool useDirect = false) {
        if (fd >= 0) {
            std::cerr << "File is already open\n";
            return false;
        }

        directIO = useDirect;
        fd = open(path, O_RDWR | (directIO ? O_DIRECT : 0));

        if (fd < 0) {
            std::cerr << "Open error: " << strerror(errno) << '\n';
            return false;
        }

        struct stat info{};

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

    bool queueRead(uint64_t position, void* buffer, size_t bytes, uint64_t id) {
        return queue(position, buffer, bytes, id, false);
    }

    bool queueWrite(uint64_t position, const void* buffer,
                    size_t bytes, uint64_t id) {
        return queue(
            position, const_cast<void*>(buffer), bytes, id, true
        );
    }

    bool submit() {
        if (!ready) {
            return false;
        }

        while (queued > 0) {
            int result = io_uring_submit(&ring);

            if (result == -EINTR) {
                continue;
            }

            if (result <= 0 || result > queued) {
                std::cerr << "Submission failed: " << result << '\n';
                return false;
            }

            queued -= result;
            outstanding += result;
        }

        return true;
    }

    bool wait(uint64_t& id, size_t expectedBytes) {
        if (outstanding == 0) {
            std::cerr << "No submitted requests to wait for\n";
            return false;
        }

        io_uring_cqe* completion = nullptr;
        int result;

        do {
            result = io_uring_wait_cqe(&ring, &completion);
        } while (result == -EINTR);

        if (result < 0) {
            std::cerr << "Completion error: " << strerror(-result) << '\n';
            return false;
        }

        id = completion->user_data;
        int completedBytes = completion->res;

        io_uring_cqe_seen(&ring, completion);
        outstanding--;

        if (completedBytes < 0) {
            std::cerr << "I/O error: " << strerror(-completedBytes) << '\n';
            return false;
        }

        if (static_cast<size_t>(completedBytes) != expectedBytes) {
            std::cerr << "Incomplete chunk transfer\n";
            return false;
        }

        return true;
    }

    bool read(uint64_t position, void* buffer, size_t bytes) {
        return transfer(position, buffer, bytes, false);
    }

    bool write(uint64_t position, const void* buffer, size_t bytes) {
        return transfer(
            position, const_cast<void*>(buffer), bytes, true
        );
    }
};