#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define TIVOO_AFE_HISTORY_SAMPLES 8000U /* 500 ms @ 16 kHz */

typedef enum {
    TIVOO_AFE_WAKE, TIVOO_AFE_START, TIVOO_AFE_PCM, TIVOO_AFE_END, TIVOO_AFE_GAP
} tivoo_afe_event_type_t;

typedef struct {
    tivoo_afe_event_type_t type;
    uint64_t index; /* logical enhanced PCM sample index; END is exclusive */
    const int16_t *pcm; /* valid only during callback */
    size_t count;
    int word; /* one-based model metadata index, only for WAKE */
} tivoo_afe_event_t;
typedef void (*tivoo_afe_sink_t)(void *ctx, const tivoo_afe_event_t *event);

/* Single fetch-task owner. Sink must copy PCM before return and never block.
 * Network/session/physical prompt orchestration belongs to subsequent batches. */
typedef struct {
    tivoo_afe_sink_t sink;
    void *ctx;
    uint64_t next, gate, wake_after;
    bool have_next, gate_open, speaking, prompt, latched;
    int candidate, words;
    size_t write, history_count;
    uint64_t cache_ignored;
    int16_t history[TIVOO_AFE_HISTORY_SAMPLES];
} tivoo_afe_flow_t;

void tivoo_afe_interleave(int16_t *out, const int16_t *left,
    const int16_t *right, const int16_t *ref, size_t count);
void tivoo_afe_flow_init(tivoo_afe_flow_t *f, int words, tivoo_afe_sink_t sink, void *ctx);
bool tivoo_afe_flow_open(tivoo_afe_flow_t *f, uint64_t first);
void tivoo_afe_flow_close(tivoo_afe_flow_t *f);
void tivoo_afe_flow_prompt(tivoo_afe_flow_t *f, bool suppress, uint64_t wake_after);
void tivoo_afe_flow_gap(tivoo_afe_flow_t *f);
void tivoo_afe_flow_frame(tivoo_afe_flow_t *f, uint64_t first, const int16_t *pcm,
    size_t count, bool speech, int wake_state, int raw_channels,
    int model, int word, size_t cache_samples);
