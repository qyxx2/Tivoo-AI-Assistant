#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef ESP_PLATFORM
#include "esp_err.h"
esp_err_t tivoo_spp_start(void);
#endif

typedef enum {
    TIVOO_SPP_LINK_DISCONNECTED,
    TIVOO_SPP_LINK_CONNECTING,
    TIVOO_SPP_LINK_CONNECTED,
} tivoo_spp_link_state_t;

typedef enum {
    TIVOO_SPP_QUEUE_QUEUED,
    TIVOO_SPP_QUEUE_CONNECTING,
    TIVOO_SPP_QUEUE_DISCONNECTED,
    TIVOO_SPP_QUEUE_FULL,
} tivoo_spp_queue_result_t;

void tivoo_spp_get_status(
    tivoo_spp_link_state_t *state, uint8_t peer[6], bool *peer_valid);
bool tivoo_spp_queue_connect(const uint8_t peer[6]);
bool tivoo_spp_queue_disconnect(const uint8_t peer[6]);
tivoo_spp_queue_result_t tivoo_spp_queue_frame(
    const uint8_t *frame, size_t size);
