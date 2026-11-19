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
#ifdef ESP_PLATFORM
/* Fetch-task short prompt owner: same generation allocator as HTTP TTS,
 * never emits ordinary AUDIO_STATE, and never blocks on the owner mutex. */
uint32_t tivoo_audio_resource_prompt_begin(void);
bool tivoo_audio_resource_prompt_end(uint32_t generation);
bool tivoo_audio_resource_prompt_discard(uint32_t generation);
bool tivoo_audio_resource_prompt_ready(unsigned acoustic_tail);
void tivoo_audio_resource_retire_local(const char *session_id, uint32_t epoch);
#endif
esp_err_t tivoo_audio_resource_start(
    const char *playback_id, const char *url, const char *mime_type);
esp_err_t tivoo_audio_resource_stop(
    const char *request_id, const char *expected_audio_id, const char *reason);
bool tivoo_audio_resource_handle_message(
    uint8_t type, const uint8_t *payload, size_t size);
