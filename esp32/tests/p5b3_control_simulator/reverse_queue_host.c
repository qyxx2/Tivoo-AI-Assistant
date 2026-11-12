#include "control_bridge.h"
#include "tivoo_spp.h"

#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static size_t s_partial_send_calls;

ssize_t __real_send(int fd, const void *buffer, size_t size, int flags);

ssize_t __wrap_send(int fd, const void *buffer, size_t size, int flags)
{
    if (size > 73U) {
        size = 73U;
        s_partial_send_calls++;
    }
    return __real_send(fd, buffer, size, flags);
}

bool tivoo_spp_queue_connect(const uint8_t peer[6])
{
    (void)peer;
    return true;
}

bool tivoo_spp_queue_disconnect(const uint8_t peer[6])
{
    (void)peer;
    return true;
}

tivoo_spp_queue_result_t tivoo_spp_queue_frame(
    const uint8_t *frame, size_t size)
{
    (void)frame;
    (void)size;
    return TIVOO_SPP_QUEUE_QUEUED;
}

static int make_socket_pair(int pair[2])
{
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, pair) != 0) {
        return -1;
    }
    const int send_buffer = 1024;
    (void)setsockopt(pair[0], SOL_SOCKET, SO_SNDBUF,
                     &send_buffer, sizeof(send_buffer));
    const int flags = fcntl(pair[0], F_GETFL, 0);
    if (flags < 0 || fcntl(pair[0], F_SETFL, flags | O_NONBLOCK) != 0) {
        close(pair[0]);
        close(pair[1]);
        return -1;
    }
    return 0;
}

static int drain_peer(int fd, uint8_t *output, size_t capacity, size_t *size)
{
    for (;;) {
        const ssize_t received = recv(
            fd, output + *size, capacity - *size, MSG_DONTWAIT);
        if (received > 0) {
            *size += (size_t)received;
            continue;
        }
        if (received < 0 && errno != EAGAIN && errno != EWOULDBLOCK &&
            errno != EINTR) {
            return -1;
        }
        return 0;
    }
}

int main(void)
{
    int pair[2];
    if (make_socket_pair(pair) != 0) {
        return 1;
    }

    uint8_t expected[TIVOO_CONTROL_REVERSE_QUEUE_CAPACITY];
    uint8_t actual[TIVOO_CONTROL_REVERSE_QUEUE_CAPACITY];
    for (size_t i = 0; i < sizeof(expected); i++) {
        expected[i] = (uint8_t)(i * 37U + 11U);
    }
    memset(actual, 0, sizeof(actual));

    tivoo_control_client_connected(pair[0]);
    static const uint8_t overflow_probe = 0x7A;
    if (!tivoo_control_spp_data(expected, sizeof(expected)) ||
        tivoo_control_spp_data(&overflow_probe, sizeof(overflow_probe)) ||
        !tivoo_control_client_has_pending(pair[0])) {
        return 2;
    }

    /* Fill the nonblocking socket without reading: EAGAIN must retain bytes. */
    for (int i = 0; i < 100; i++) {
        if (!tivoo_control_client_send_pending(pair[0])) {
            return 3;
        }
    }
    if (!tivoo_control_client_has_pending(pair[0])) {
        return 4;
    }

    size_t actual_size = 0;
    for (int i = 0; i < 200 && tivoo_control_client_has_pending(pair[0]); i++) {
        if (!tivoo_control_client_send_pending(pair[0]) ||
            drain_peer(pair[1], actual, sizeof(actual), &actual_size) != 0) {
            return 5;
        }
    }
    if (s_partial_send_calls == 0U ||
        drain_peer(pair[1], actual, sizeof(actual), &actual_size) != 0 ||
        actual_size != sizeof(expected) ||
        memcmp(actual, expected, sizeof(expected)) != 0 ||
        tivoo_control_client_has_pending(pair[0])) {
        return 6;
    }

    /* Closing this client discards its pending bytes, not SPP state. */
    static const uint8_t stale[] = {0x31, 0x32, 0x33, 0x34};
    if (!tivoo_control_spp_data(stale, sizeof(stale)) ||
        !tivoo_control_client_has_pending(pair[0])) {
        return 7;
    }
    tivoo_control_client_disconnected(pair[0]);
    close(pair[0]);
    close(pair[1]);

    /* With no 7777 client, data is dropped rather than carried to the next. */
    if (!tivoo_control_spp_data(stale, sizeof(stale)) ||
        make_socket_pair(pair) != 0) {
        return 8;
    }
    tivoo_control_client_connected(pair[0]);
    if (tivoo_control_client_has_pending(pair[0]) ||
        tivoo_control_client_send_pending(pair[0]) != true) {
        return 9;
    }
    uint8_t byte;
    if (recv(pair[1], &byte, 1, MSG_DONTWAIT) >= 0 ||
        (errno != EAGAIN && errno != EWOULDBLOCK)) {
        return 10;
    }

    /* Oversized SPP callback payload is rejected atomically. */
    uint8_t *oversized = malloc(TIVOO_CONTROL_REVERSE_QUEUE_CAPACITY + 1U);
    if (oversized == NULL) {
        return 11;
    }
    memset(oversized, 0xA5, TIVOO_CONTROL_REVERSE_QUEUE_CAPACITY + 1U);
    const bool accepted = tivoo_control_spp_data(
        oversized, TIVOO_CONTROL_REVERSE_QUEUE_CAPACITY + 1U);
    free(oversized);
    if (accepted || tivoo_control_client_has_pending(pair[0])) {
        return 12;
    }

    tivoo_control_client_disconnected(pair[0]);
    close(pair[0]);
    close(pair[1]);
    puts("reverse queue, EAGAIN, offset, overflow, and disconnect checks passed");
    return 0;
}
