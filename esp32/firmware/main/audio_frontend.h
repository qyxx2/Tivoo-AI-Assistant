#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define TIVOO_MIC_FRAME_SAMPLES 320U
#define TIVOO_MIC_PREROLL_FRAMES 25U
#define TIVOO_MIC_BUFFER_FRAMES 50U

typedef struct {
    int16_t samples[TIVOO_MIC_FRAME_SAMPLES];
    uint64_t uptime_ms;
    bool speech;
} tivoo_mic_frame_t;

/* One owner calls push/stop. The send callback only enqueues and never writes
 * to the socket. Generation zero means there is no accepted diagnostics peer. */
typedef struct {
    bool (*send)(uint32_t generation, uint8_t type, const void *data, size_t size);
    void (*new_id)(char out[37]);
    tivoo_mic_frame_t frames[TIVOO_MIC_BUFFER_FRAMES];
    tivoo_mic_frame_t partial;
    size_t partial_samples;
    size_t write;
    size_t history_count;
    size_t pending;
    uint32_t generation;
    uint32_t dropped_frames;
    uint32_t activity_transitions;
    uint64_t start_ms;
    char session_id[37];
    bool speech;
    bool sent_start;
    bool sent_start_activity;
    bool reported_speech;
    bool stopping;
    size_t preroll_pending;
} tivoo_mic_producer_t;

void tivoo_mic_push(tivoo_mic_producer_t *mic, uint32_t generation, bool speech,
    uint64_t uptime_ms, const int16_t *samples, size_t count);
bool tivoo_mic_stop(tivoo_mic_producer_t *mic, uint32_t generation, const char *session_id);

#ifdef ESP_PLATFORM
#include "esp_err.h"

typedef enum {
    TIVOO_AUDIO_REFERENCE_SILENT,
    TIVOO_AUDIO_REFERENCE_READY,
    TIVOO_AUDIO_REFERENCE_UNDERRUN,
    TIVOO_AUDIO_REFERENCE_MISALIGNED,
} tivoo_audio_reference_status_t;

/* Non-blocking. Read the aligned, final TX PCM at 16 kHz into R slots
 * reference[2 * i]. NULL selects silence while there is no PCM output owner. */
typedef tivoo_audio_reference_status_t (*tivoo_audio_reference_reader_t)(
    uint64_t first_sample, int16_t *reference, size_t samples);
esp_err_t tivoo_audio_frontend_start(tivoo_audio_reference_reader_t read_reference);
#endif
