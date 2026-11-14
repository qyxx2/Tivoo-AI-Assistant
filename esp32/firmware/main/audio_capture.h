#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define TIVOO_DECIMATOR_TAPS 31U

typedef struct {
    int32_t history[TIVOO_DECIMATOR_TAPS];
    size_t next;
    unsigned phase;
} tivoo_decimator_t;

int32_t tivoo_inmp441_sample(uint32_t left_slot);
size_t tivoo_audio_decimate(
    tivoo_decimator_t *filter, const uint32_t *stereo, size_t frames, int16_t *mono);

#ifdef ESP_PLATFORM
#include "esp_err.h"

esp_err_t tivoo_audio_capture_start(void);
bool tivoo_audio_capture_running(void);
void tivoo_audio_capture_close(void);
esp_err_t tivoo_audio_capture_read(uint32_t *stereo, size_t bytes, size_t *read);
uint32_t tivoo_audio_capture_overruns(void);
#endif
