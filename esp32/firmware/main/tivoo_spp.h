#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef ESP_PLATFORM
#include "esp_err.h"
esp_err_t tivoo_spp_start(void);
#endif

bool tivoo_spp_queue_connect(const uint8_t peer[6]);
bool tivoo_spp_queue_disconnect(const uint8_t peer[6]);
bool tivoo_spp_queue_frame(const uint8_t *frame, size_t size);
