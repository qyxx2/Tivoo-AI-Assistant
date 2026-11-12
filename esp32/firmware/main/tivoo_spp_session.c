#include "tivoo_spp_session.h"

#include <string.h>

uint8_t tivoo_spp_select_scn(bool discovery_completed, uint8_t discovered_scn)
{
    return discovery_completed && discovered_scn > 0 ? discovered_scn : 1;
}

uint32_t tivoo_spp_connection_wait_mask(
    uint32_t current,
    uint32_t event_open,
    uint32_t event_auth_done,
    uint32_t event_failed)
{
    uint32_t missing = event_failed;
    if ((current & event_open) == 0) {
        missing |= event_open;
    }
    if ((current & event_auth_done) == 0) {
        missing |= event_auth_done;
    }
    return missing;
}

void tivoo_spp_session_mark_disconnected(tivoo_spp_session_t *session)
{
    if (session != NULL) {
        session->connected = false;
    }
}

static bool same_address(const uint8_t left[6], const uint8_t right[6])
{
    return memcmp(left, right, 6) == 0;
}

static void clear_peer(tivoo_spp_session_t *session)
{
    session->peer_valid = false;
    session->connected = false;
    memset(session->peer, 0, sizeof(session->peer));
}

static bool backend_valid(const tivoo_spp_session_backend_t *backend)
{
    return backend != NULL && backend->disconnect != NULL &&
        backend->connect != NULL && backend->write_chunk != NULL &&
        backend->delay_ms != NULL;
}

tivoo_spp_session_result_t tivoo_spp_session_process(
    tivoo_spp_session_t *session,
    const tivoo_spp_request_t *request,
    const tivoo_spp_session_backend_t *backend)
{
    if (session == NULL || request == NULL || !backend_valid(backend)) {
        return TIVOO_SPP_SESSION_INVALID_REQUEST;
    }

    switch (request->type) {
    case TIVOO_SPP_REQUEST_CONNECT:
        if (session->peer_valid && same_address(session->peer, request->peer)) {
            if (session->connected) {
                return TIVOO_SPP_SESSION_OK;
            }
            if (!backend->connect(backend->context, session->peer)) {
                return TIVOO_SPP_SESSION_CONNECT_FAILED;
            }
            session->connected = true;
            return TIVOO_SPP_SESSION_OK;
        }

        if (session->peer_valid) {
            session->connected = false;
            if (!backend->disconnect(backend->context, session->peer)) {
                return TIVOO_SPP_SESSION_DISCONNECT_FAILED;
            }
            clear_peer(session);
        }

        /* Keep the explicitly selected peer even when its first connect fails. */
        memcpy(session->peer, request->peer, sizeof(session->peer));
        session->peer_valid = true;
        session->connected = false;
        if (!backend->connect(backend->context, request->peer)) {
            return TIVOO_SPP_SESSION_CONNECT_FAILED;
        }
        session->connected = true;
        return TIVOO_SPP_SESSION_OK;

    case TIVOO_SPP_REQUEST_DISCONNECT:
        if (!session->peer_valid ||
            !same_address(session->peer, request->peer)) {
            return TIVOO_SPP_SESSION_OK;
        }
        session->connected = false;
        if (!backend->disconnect(backend->context, session->peer)) {
            return TIVOO_SPP_SESSION_DISCONNECT_FAILED;
        }
        clear_peer(session);
        return TIVOO_SPP_SESSION_OK;

    case TIVOO_SPP_REQUEST_RECONNECT:
        if (!session->peer_valid) {
            return TIVOO_SPP_SESSION_NOT_CONNECTED;
        }
        if (session->connected) {
            return TIVOO_SPP_SESSION_OK;
        }
        if (!backend->connect(backend->context, session->peer)) {
            return TIVOO_SPP_SESSION_CONNECT_FAILED;
        }
        session->connected = true;
        return TIVOO_SPP_SESSION_OK;

    case TIVOO_SPP_REQUEST_FRAME:
        if (!session->connected) {
            return TIVOO_SPP_SESSION_NOT_CONNECTED;
        }
        if (request->frame == NULL || request->frame_size == 0) {
            return TIVOO_SPP_SESSION_INVALID_REQUEST;
        }

        for (size_t offset = 0; offset < request->frame_size;) {
            const size_t remaining = request->frame_size - offset;
            const size_t chunk_size = remaining > TIVOO_SPP_WRITE_CHUNK_SIZE
                ? TIVOO_SPP_WRITE_CHUNK_SIZE : remaining;
            if (!backend->write_chunk(
                    backend->context, request->frame + offset, chunk_size)) {
                session->connected = false;
                return TIVOO_SPP_SESSION_WRITE_FAILED;
            }
            offset += chunk_size;
        }

        backend->delay_ms(backend->context, TIVOO_SPP_FRAME_DELAY_MS);
        return TIVOO_SPP_SESSION_OK;

    default:
        return TIVOO_SPP_SESSION_INVALID_REQUEST;
    }
}
