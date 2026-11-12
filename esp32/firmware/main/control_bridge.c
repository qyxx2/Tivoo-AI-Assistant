#include "control_bridge.h"

#include <errno.h>
#include <stdatomic.h>
#include <string.h>

#include <sys/socket.h>

#ifdef ESP_PLATFORM
#include "freertos/FreeRTOS.h"
#else
#include <pthread.h>
#endif

#include "diagnostics.h"
#include "tivoo_frame_stream.h"
#include "tivoo_spp.h"

#define CONTROL_COMMAND_SIZE 7

typedef enum {
    CONTROL_MODE_IDLE,
    CONTROL_MODE_COMMAND,
    CONTROL_MODE_FRAME,
} control_mode_t;

static atomic_int s_client_fd = ATOMIC_VAR_INIT(-1);
static uint8_t s_reverse_queue[TIVOO_CONTROL_REVERSE_QUEUE_CAPACITY];
static size_t s_reverse_head;
static size_t s_reverse_count;
static atomic_bool s_reverse_queue_full_pending = ATOMIC_VAR_INIT(false);
#ifdef ESP_PLATFORM
static portMUX_TYPE s_reverse_mux = portMUX_INITIALIZER_UNLOCKED;
static void reverse_lock(void) { portENTER_CRITICAL(&s_reverse_mux); }
static void reverse_unlock(void) { portEXIT_CRITICAL(&s_reverse_mux); }
#else
static pthread_mutex_t s_reverse_mutex = PTHREAD_MUTEX_INITIALIZER;
static void reverse_lock(void) { (void)pthread_mutex_lock(&s_reverse_mutex); }
static void reverse_unlock(void) { (void)pthread_mutex_unlock(&s_reverse_mutex); }
#endif

static control_mode_t s_mode;
static uint8_t s_command[CONTROL_COMMAND_SIZE];
static size_t s_command_size;
static tivoo_frame_stream_t s_frame_stream;
static bool s_frame_invalid;
static bool s_frame_queue_full;

static void reverse_queue_clear_locked(void)
{
    s_reverse_head = 0U;
    s_reverse_count = 0U;
}

bool tivoo_control_spp_data(const uint8_t *data, size_t size)
{
    if (size == 0U) {
        return true;
    }
    if (data == NULL) {
        return false;
    }

    reverse_lock();
    if (atomic_load(&s_client_fd) < 0) {
        reverse_unlock();
        return true;
    }
    if (size > TIVOO_CONTROL_REVERSE_QUEUE_CAPACITY - s_reverse_count) {
        atomic_store(&s_reverse_queue_full_pending, true);
        reverse_unlock();
        return false;
    }

    const size_t tail =
        (s_reverse_head + s_reverse_count) % TIVOO_CONTROL_REVERSE_QUEUE_CAPACITY;
    const size_t first =
        size < TIVOO_CONTROL_REVERSE_QUEUE_CAPACITY - tail
            ? size : TIVOO_CONTROL_REVERSE_QUEUE_CAPACITY - tail;
    memcpy(&s_reverse_queue[tail], data, first);
    if (size > first) {
        memcpy(s_reverse_queue, data + first, size - first);
    }
    s_reverse_count += size;
    reverse_unlock();
    return true;
}

bool tivoo_control_client_has_pending(int client_fd)
{
    reverse_lock();
    const bool pending = atomic_load(&s_client_fd) == client_fd &&
        s_reverse_count > 0U;
    reverse_unlock();
    return pending;
}

bool tivoo_control_client_send_pending(int client_fd)
{
    uint8_t buffer[512];
    size_t size = 0U;

    reverse_lock();
    if (atomic_load(&s_client_fd) == client_fd && s_reverse_count > 0U) {
        size = s_reverse_count;
        if (size > sizeof(buffer)) {
            size = sizeof(buffer);
        }
        const size_t contiguous =
            TIVOO_CONTROL_REVERSE_QUEUE_CAPACITY - s_reverse_head;
        if (size > contiguous) {
            size = contiguous;
        }
        memcpy(buffer, &s_reverse_queue[s_reverse_head], size);
    }
    reverse_unlock();

    if (size == 0U) {
        return true;
    }

    int flags = 0;
#ifdef MSG_NOSIGNAL
    flags |= MSG_NOSIGNAL;
#endif
    const ssize_t sent = send(client_fd, buffer, size, flags);
    if (sent > 0) {
        reverse_lock();
        if (atomic_load(&s_client_fd) == client_fd) {
            const size_t consumed =
                (size_t)sent < s_reverse_count ? (size_t)sent : s_reverse_count;
            s_reverse_head =
                (s_reverse_head + consumed) % TIVOO_CONTROL_REVERSE_QUEUE_CAPACITY;
            s_reverse_count -= consumed;
        }
        reverse_unlock();
        return true;
    }
    if (sent < 0 &&
        (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) {
        return true;
    }
    return false;
}

void tivoo_control_report_pending_errors(void)
{
    if (atomic_exchange(&s_reverse_queue_full_pending, false)) {
        tivoo_report_error(
            "reverse_queue_full", "control_bridge", "SPP reverse queue full");
    }
}

static void reset_parser(void)
{
    s_mode = CONTROL_MODE_IDLE;
    s_command_size = 0;
    s_frame_stream.size = 0;
    s_frame_invalid = false;
    s_frame_queue_full = false;
}

void tivoo_control_client_connected(int client_fd)
{
    reverse_lock();
    reverse_queue_clear_locked();
    atomic_store(&s_client_fd, client_fd);
    reverse_unlock();
    reset_parser();
}

void tivoo_control_client_disconnected(int client_fd)
{
    reverse_lock();
    if (atomic_load(&s_client_fd) != client_fd) {
        reverse_unlock();
        return;
    }
    atomic_store(&s_client_fd, -1);
    reverse_queue_clear_locked();
    reverse_unlock();
    reset_parser();
}

static void handle_frame(const uint8_t *frame, size_t size)
{
    if (size < 6 || size > TIVOO_FRAME_BUFFER_SIZE ||
        frame[0] != 0x01 || frame[size - 1] != 0x02 ||
        tivoo_frame_get_size(frame, size) != size) {
        s_frame_invalid = true;
        return;
    }
    const tivoo_spp_queue_result_t result = tivoo_spp_queue_frame(frame, size);
    if (result == TIVOO_SPP_QUEUE_FULL) {
        s_frame_queue_full = true;
        return;
    }
    if (result == TIVOO_SPP_QUEUE_CONNECTING ||
        result == TIVOO_SPP_QUEUE_DISCONNECTED) {
        const uint8_t hint = result == TIVOO_SPP_QUEUE_CONNECTING ? 0x69 : 0x96;
        (void)tivoo_control_spp_data(&hint, sizeof(hint));
    }
    s_mode = CONTROL_MODE_IDLE;
}

static bool dispatch_command(void)
{
    const uint8_t opcode = s_command[0];
    if (opcode == 0x69) {
        if (!tivoo_spp_queue_connect(&s_command[1])) {
            tivoo_report_error(
                "spp_tx_queue_full", "control_bridge", "spp_connect_queue_full");
            return false;
        }
    } else if (opcode == 0x96) {
        if (!tivoo_spp_queue_disconnect(&s_command[1])) {
            tivoo_report_error(
                "spp_tx_queue_full", "control_bridge", "spp_disconnect_queue_full");
            return false;
        }
    } else {
        tivoo_report_error(
            "tcp_control_malformed", "control_bridge", "unknown_control_opcode");
        return false;
    }
    return true;
}

bool tivoo_control_client_data(int client_fd, const uint8_t *data, size_t size)
{
    if (client_fd != s_client_fd || (data == NULL && size > 0)) {
        return false;
    }

    for (size_t i = 0; i < size; i++) {
        const uint8_t byte = data[i];
        if (s_mode == CONTROL_MODE_IDLE) {
            if (byte == 0x69 || byte == 0x96) {
                s_command[0] = byte;
                s_command_size = 1;
                s_mode = CONTROL_MODE_COMMAND;
            } else if (byte == 0x01) {
                s_mode = CONTROL_MODE_FRAME;
                s_frame_invalid = false;
                s_frame_queue_full = false;
                static const uint8_t frame_start = 0x01;
                tivoo_frame_append(
                    &s_frame_stream, &frame_start, 1, handle_frame);
            } else {
                tivoo_report_error(
                    "tcp_control_malformed", "control_bridge",
                    "unknown_control_stream_start");
                return false;
            }
        } else if (s_mode == CONTROL_MODE_COMMAND) {
            s_command[s_command_size++] = byte;
            if (s_command_size == CONTROL_COMMAND_SIZE) {
                if (!dispatch_command()) {
                    return false;
                }
                s_command_size = 0;
                s_mode = CONTROL_MODE_IDLE;
            }
        } else {
            tivoo_frame_append(&s_frame_stream, &byte, 1, handle_frame);
            if (s_frame_invalid) {
                tivoo_report_error(
                    "tivoo_frame_malformed", "control_bridge",
                    "invalid_or_unframed_tivoo_data");
                return false;
            }
            if (s_frame_queue_full) {
                tivoo_report_error(
                    "spp_tx_queue_full", "control_bridge", "spp_frame_queue_full");
                return false;
            }
        }
    }
    return true;
}
