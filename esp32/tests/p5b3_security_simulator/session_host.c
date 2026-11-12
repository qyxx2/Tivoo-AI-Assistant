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
    bool fail_connect;
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
    return !capture->fail_connect;
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

    /* Wait only for events that have not arrived, plus the failure event. */
    const uint32_t EVENT_OPEN = 1U << 0;
    const uint32_t EVENT_AUTH_DONE = 1U << 1;
    const uint32_t EVENT_FAILED = 1U << 2;
    assert(tivoo_spp_connection_wait_mask(
        0, EVENT_OPEN, EVENT_AUTH_DONE, EVENT_FAILED) ==
        (EVENT_OPEN | EVENT_AUTH_DONE | EVENT_FAILED));
    assert(tivoo_spp_connection_wait_mask(
        EVENT_OPEN, EVENT_OPEN, EVENT_AUTH_DONE, EVENT_FAILED) ==
        (EVENT_AUTH_DONE | EVENT_FAILED));
    assert(tivoo_spp_connection_wait_mask(
        EVENT_AUTH_DONE, EVENT_OPEN, EVENT_AUTH_DONE, EVENT_FAILED) ==
        (EVENT_OPEN | EVENT_FAILED));
    assert(tivoo_spp_connection_wait_mask(
        EVENT_OPEN | EVENT_AUTH_DONE, EVENT_OPEN, EVENT_AUTH_DONE,
        EVENT_FAILED) == EVENT_FAILED);

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

    /* A first connection failure must retain the HA-selected peer for retry. */
    capture_t first_failure_capture = {.fail_connect = true};
    const tivoo_spp_session_backend_t first_failure_backend = {
        .context = &first_failure_capture,
        .disconnect = disconnect_peer,
        .connect = connect_peer,
        .write_chunk = write_chunk,
        .delay_ms = delay_ms,
    };
    tivoo_spp_session_t first_failure_session = {0};
    request = (tivoo_spp_request_t) {.type = TIVOO_SPP_REQUEST_CONNECT};
    memcpy(request.peer, peer_a, sizeof(peer_a));
    assert(tivoo_spp_session_process(
        &first_failure_session, &request, &first_failure_backend) ==
        TIVOO_SPP_SESSION_CONNECT_FAILED);
    assert(first_failure_session.peer_valid);
    assert(!first_failure_session.connected);
    assert(memcmp(first_failure_session.peer, peer_a, sizeof(peer_a)) == 0);
    first_failure_capture.fail_connect = false;
    request = (tivoo_spp_request_t) {.type = TIVOO_SPP_REQUEST_RECONNECT};
    assert(tivoo_spp_session_process(
        &first_failure_session, &request, &first_failure_backend) ==
        TIVOO_SPP_SESSION_OK);
    assert(first_failure_session.peer_valid && first_failure_session.connected);

    /* An unexpected link loss retains the requested peer for automatic retry. */
    capture_t reconnect_capture = {0};
    const tivoo_spp_session_backend_t reconnect_backend = {
        .context = &reconnect_capture,
        .disconnect = disconnect_peer,
        .connect = connect_peer,
        .write_chunk = write_chunk,
        .delay_ms = delay_ms,
    };
    tivoo_spp_session_t reconnect_session = {0};
    request = (tivoo_spp_request_t) {.type = TIVOO_SPP_REQUEST_CONNECT};
    memcpy(request.peer, peer_a, sizeof(peer_a));
    assert(tivoo_spp_session_process(
        &reconnect_session, &request, &reconnect_backend) ==
        TIVOO_SPP_SESSION_OK);
    tivoo_spp_session_mark_disconnected(&reconnect_session);
    assert(reconnect_session.peer_valid && !reconnect_session.connected);
    request = (tivoo_spp_request_t) {.type = TIVOO_SPP_REQUEST_RECONNECT};
    assert(tivoo_spp_session_process(
        &reconnect_session, &request, &reconnect_backend) ==
        TIVOO_SPP_SESSION_OK);
    assert(reconnect_session.peer_valid && reconnect_session.connected);

    tivoo_spp_session_mark_disconnected(&reconnect_session);
    reconnect_capture.fail_connect = true;
    assert(tivoo_spp_session_process(
        &reconnect_session, &request, &reconnect_backend) ==
        TIVOO_SPP_SESSION_CONNECT_FAILED);
    assert(reconnect_session.peer_valid && !reconnect_session.connected);
    reconnect_capture.fail_connect = false;
    assert(tivoo_spp_session_process(
        &reconnect_session, &request, &reconnect_backend) ==
        TIVOO_SPP_SESSION_OK);
    assert(reconnect_session.peer_valid && reconnect_session.connected);

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

    /* Repeated 0x69 for the already connected MAC is idempotent. */
    request = (tivoo_spp_request_t) {.type = TIVOO_SPP_REQUEST_CONNECT};
    memcpy(request.peer, peer_a, sizeof(peer_a));
    assert(tivoo_spp_session_process(&session, &request, &backend) ==
           TIVOO_SPP_SESSION_OK);
    assert(session.connected && session.peer_valid);
    assert(capture.event_count == 5);

    /* A same-MAC 0x69 after a drop reconnects without a disconnect cycle. */
    tivoo_spp_session_mark_disconnected(&session);
    assert(tivoo_spp_session_process(&session, &request, &backend) ==
           TIVOO_SPP_SESSION_OK);
    assert(session.connected && session.peer_valid);
    assert(strcmp(capture.events[5], "connect") == 0);
    assert(capture.event_count == 6);

    /* A different MAC switches peers in FIFO order. */
    request = (tivoo_spp_request_t) {.type = TIVOO_SPP_REQUEST_CONNECT};
    memcpy(request.peer, peer_b, sizeof(peer_b));
    assert(tivoo_spp_session_process(&session, &request, &backend) ==
           TIVOO_SPP_SESSION_OK);
    assert(strcmp(capture.events[6], "disconnect") == 0);
    assert(strcmp(capture.events[7], "connect") == 0);

    request = (tivoo_spp_request_t) {.type = TIVOO_SPP_REQUEST_DISCONNECT};
    memcpy(request.peer, peer_b, sizeof(peer_b));
    assert(tivoo_spp_session_process(&session, &request, &backend) ==
           TIVOO_SPP_SESSION_OK);
    assert(strcmp(capture.events[8], "disconnect") == 0);
    assert(!session.connected && !session.peer_valid);
    request = (tivoo_spp_request_t) {.type = TIVOO_SPP_REQUEST_RECONNECT};
    assert(tivoo_spp_session_process(&session, &request, &backend) ==
           TIVOO_SPP_SESSION_NOT_CONNECTED);

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
