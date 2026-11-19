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

typedef struct {
    void **buffers;
    size_t capacity;
    size_t count;
    size_t index;
    bool order_uncertain;
} tivoo_dma_eof_tracker_t;

void tivoo_dma_eof_tracker_reset(
    tivoo_dma_eof_tracker_t *tracker, void **buffers, size_t capacity);
size_t tivoo_dma_eof_tracker_observe(tivoo_dma_eof_tracker_t *tracker, void *buffer);

int32_t tivoo_inmp441_sample(uint32_t left_slot);
size_t tivoo_audio_decimate(
    tivoo_decimator_t *filter, const uint32_t *stereo, size_t frames, int16_t *mono);

size_t tivoo_audio_decimate_pcm16(tivoo_decimator_t *filter, const int16_t *pcm,
    size_t samples, int16_t *mono);

typedef struct {
    tivoo_decimator_t left, right;
} tivoo_stereo_decimator_t;

size_t tivoo_audio_decimate_stereo(tivoo_stereo_decimator_t *filter,
    const uint32_t *stereo, size_t frames, int16_t *left, int16_t *right);

#define TIVOO_RX_SETTLE_BLOCKS 26U /* 130ms, at least INMP441's 128ms */
typedef struct {
    uint64_t next_block;
    uint64_t lost_blocks;
} tivoo_rx_timeline_t;
bool tivoo_rx_timeline_accept(tivoo_rx_timeline_t *timeline, uint64_t block, bool *gap);

#ifdef ESP_PLATFORM
#include "esp_err.h"

#define TIVOO_CAPTURE_SAMPLES 80U
typedef struct {
    uint64_t first_sample;
    uint64_t epoch_first_raw; /* 32 kHz DMA epoch base */
    uint64_t tx_first_sample; /* raw 32 kHz index */
    bool gap;
    bool reference_valid;
    /* Raw trace pointers valid until the next call on the same task.
     * 160 raw stereo frames and 160 final TX mono samples, respectively.
     * Raw RX starts at first_sample*2; raw TX may include calibrated delay. */
    const uint32_t *raw_slots;
    const int16_t *raw_tx;
    int16_t left[TIVOO_CAPTURE_SAMPLES];
    int16_t right[TIVOO_CAPTURE_SAMPLES];
    int16_t reference[TIVOO_CAPTURE_SAMPLES];
} tivoo_capture_frame_t;
esp_err_t tivoo_audio_capture_start(void);
esp_err_t tivoo_audio_capture_next(tivoo_capture_frame_t *frame);
esp_err_t tivoo_audio_capture_monitor_start(void);
bool tivoo_audio_capture_running(void);
void tivoo_audio_capture_close(void);
esp_err_t tivoo_audio_capture_read(uint32_t *stereo, size_t bytes, size_t *read);
uint32_t tivoo_audio_capture_overruns(void);
uint32_t tivoo_audio_capture_missed_eofs(void);
#endif
