#include "tivoo_spp_session.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    char events[32][32];
    size_t event_count;
    size_t chunks[16];
    size_t chunk_count;
    size_t fail_chunk;
} capture_t;

static void record(capture_t *capture, const char *event)
{
    assert(capture->event_count < 32);
    snprintf(capture->events[capture->event_count++], 32, "%s", event);
}

static bool disconnect_peer(void *context, const uint8_t peer[6])
{
    capture_t *capture = context;
    (void)peer;
    record(capture, "disconnect");
    return true;
}

static bool connect_peer(void *context, const uint8_t peer[6])
{
    capture_t *capture = context;
    (void)peer;
    record(capture, "connect");
    return true;
}

static bool write_chunk(void *context, const uint8_t *data, size_t size)
{
    capture_t *capture = context;
    (void)data;
    assert(size > 0 && size <= TIVOO_SPP_WRITE_CHUNK_SIZE);
    capture->chunks[capture->chunk_count] = size;
    capture->chunk_count++;
    record(capture, "write");
    return capture->fail_chunk == 0 ||
        capture->chunk_count != capture->fail_chunk;
}

static void delay_ms(void *context, uint32_t delay)
{
    capture_t *capture = context;
    assert(delay == TIVOO_SPP_FRAME_DELAY_MS);
    record(capture, "delay");
}

int main(void)
{
    const uint8_t peer_a[6] = {0x11, 0x75, 0x58, 0x97, 0x49, 0x98};
    const uint8_t peer_b[6] = {0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF};
    uint8_t frame[700];
    memset(frame, 0x5A, sizeof(frame));

    assert(tivoo_spp_select_scn(true, 7) == 7);
    assert(tivoo_spp_select_scn(true, 0) == 1);
    assert(tivoo_spp_select_scn(false, 12) == 1);

    capture_t capture = {0};
    const tivoo_spp_session_backend_t backend = {
        .context = &capture,
        .disconnect = disconnect_peer,
        .connect = connect_peer,
        .write_chunk = write_chunk,
        .delay_ms = delay_ms,
    };
    tivoo_spp_session_t session = {0};
    tivoo_spp_request_t request = {.type = TIVOO_SPP_REQUEST_CONNECT};
    memcpy(request.peer, peer_a, sizeof(peer_a));
    assert(tivoo_spp_session_process(&session, &request, &backend) ==
           TIVOO_SPP_SESSION_OK);

    request = (tivoo_spp_request_t) {
        .type = TIVOO_SPP_REQUEST_FRAME,
        .frame = frame,
        .frame_size = sizeof(frame),
    };
    assert(tivoo_spp_session_process(&session, &request, &backend) ==
           TIVOO_SPP_SESSION_OK);
    assert(capture.chunk_count == 3);
    assert(capture.chunks[0] == 330);
    assert(capture.chunks[1] == 330);
    assert(capture.chunks[2] == 40);
    assert(strcmp(capture.events[0], "connect") == 0);
    assert(strcmp(capture.events[1], "write") == 0);
    assert(strcmp(capture.events[2], "write") == 0);
    assert(strcmp(capture.events[3], "write") == 0);
    assert(strcmp(capture.events[4], "delay") == 0);

    /* Every new 0x69, including the same MAC, switches an open session FIFO. */
    request = (tivoo_spp_request_t) {.type = TIVOO_SPP_REQUEST_CONNECT};
    memcpy(request.peer, peer_a, sizeof(peer_a));
    assert(tivoo_spp_session_process(&session, &request, &backend) ==
           TIVOO_SPP_SESSION_OK);
    assert(strcmp(capture.events[5], "disconnect") == 0);
    assert(strcmp(capture.events[6], "connect") == 0);

    request = (tivoo_spp_request_t) {.type = TIVOO_SPP_REQUEST_CONNECT};
    memcpy(request.peer, peer_b, sizeof(peer_b));
    assert(tivoo_spp_session_process(&session, &request, &backend) ==
           TIVOO_SPP_SESSION_OK);
    assert(strcmp(capture.events[7], "disconnect") == 0);
    assert(strcmp(capture.events[8], "connect") == 0);

    request = (tivoo_spp_request_t) {.type = TIVOO_SPP_REQUEST_DISCONNECT};
    memcpy(request.peer, peer_b, sizeof(peer_b));
    assert(tivoo_spp_session_process(&session, &request, &backend) ==
           TIVOO_SPP_SESSION_OK);
    assert(strcmp(capture.events[9], "disconnect") == 0);
    assert(!session.connected && !session.peer_valid);

    /* A write completion failure stops the frame and gates all later frames. */
    memset(&capture, 0, sizeof(capture));
    capture.fail_chunk = 2;
    session = (tivoo_spp_session_t) {0};
    request = (tivoo_spp_request_t) {.type = TIVOO_SPP_REQUEST_CONNECT};
    memcpy(request.peer, peer_a, sizeof(peer_a));
    assert(tivoo_spp_session_process(&session, &request, &backend) ==
           TIVOO_SPP_SESSION_OK);
    request = (tivoo_spp_request_t) {
        .type = TIVOO_SPP_REQUEST_FRAME,
        .frame = frame,
        .frame_size = sizeof(frame),
    };
    assert(tivoo_spp_session_process(&session, &request, &backend) ==
           TIVOO_SPP_SESSION_WRITE_FAILED);
    assert(capture.chunk_count == 2);
    assert(!session.connected && session.peer_valid);
    assert(tivoo_spp_session_process(&session, &request, &backend) ==
           TIVOO_SPP_SESSION_NOT_CONNECTED);
    assert(capture.chunk_count == 2);

    puts("P5b3 SPP session ordering checks passed");
    return 0;
}
