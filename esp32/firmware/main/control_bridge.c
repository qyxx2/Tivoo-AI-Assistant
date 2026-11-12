#include "control_bridge.h"

#include <string.h>

#include "diagnostics.h"
#include "tivoo_frame_stream.h"
#include "tivoo_spp.h"

#define CONTROL_COMMAND_SIZE 7

typedef enum {
    CONTROL_MODE_IDLE,
    CONTROL_MODE_COMMAND,
    CONTROL_MODE_FRAME,
} control_mode_t;

static int s_client_fd = -1;
static control_mode_t s_mode;
static uint8_t s_command[CONTROL_COMMAND_SIZE];
static size_t s_command_size;
static tivoo_frame_stream_t s_frame_stream;
static bool s_frame_invalid;
static bool s_frame_queue_full;

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
    s_client_fd = client_fd;
    reset_parser();
}

void tivoo_control_client_disconnected(int client_fd)
{
    if (s_client_fd != client_fd) {
        return;
    }
    s_client_fd = -1;
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
    if (!tivoo_spp_queue_frame(frame, size)) {
        s_frame_queue_full = true;
        return;
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
