#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define TIVOO_SPP_WRITE_CHUNK_SIZE 330U
#define TIVOO_SPP_FRAME_DELAY_MS 15U

typedef enum {
    TIVOO_SPP_REQUEST_CONNECT,
    TIVOO_SPP_REQUEST_DISCONNECT,
    TIVOO_SPP_REQUEST_FRAME,
} tivoo_spp_request_type_t;

typedef struct {
    tivoo_spp_request_type_t type;
    uint8_t peer[6];
    const uint8_t *frame;
    size_t frame_size;
} tivoo_spp_request_t;

typedef struct {
    bool peer_valid;
    bool connected;
    uint8_t peer[6];
} tivoo_spp_session_t;

typedef struct {
    void *context;
    bool (*disconnect)(void *context, const uint8_t peer[6]);
    bool (*connect)(void *context, const uint8_t peer[6]);
    bool (*write_chunk)(void *context, const uint8_t *data, size_t size);
    void (*delay_ms)(void *context, uint32_t delay_ms);
} tivoo_spp_session_backend_t;

typedef enum {
    TIVOO_SPP_SESSION_OK,
    TIVOO_SPP_SESSION_CONNECT_FAILED,
    TIVOO_SPP_SESSION_DISCONNECT_FAILED,
    TIVOO_SPP_SESSION_NOT_CONNECTED,
    TIVOO_SPP_SESSION_WRITE_FAILED,
    TIVOO_SPP_SESSION_INVALID_REQUEST,
} tivoo_spp_session_result_t;

uint8_t tivoo_spp_select_scn(bool discovery_completed, uint8_t discovered_scn);

tivoo_spp_session_result_t tivoo_spp_session_process(
    tivoo_spp_session_t *session,
    const tivoo_spp_request_t *request,
    const tivoo_spp_session_backend_t *backend);
