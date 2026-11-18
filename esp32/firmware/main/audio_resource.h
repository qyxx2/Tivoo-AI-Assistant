#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef ESP_PLATFORM
#include "esp_err.h"
#else
#include "diagnostics.h"
#endif

esp_err_t tivoo_audio_resource_init(void);
bool tivoo_audio_resource_test_silent(void);
esp_err_t tivoo_audio_resource_start(
    const char *playback_id, const char *url, const char *mime_type);
esp_err_t tivoo_audio_resource_stop(
    const char *request_id, const char *expected_audio_id, const char *reason);
bool tivoo_audio_resource_handle_message(
    uint8_t type, const uint8_t *payload, size_t size);
