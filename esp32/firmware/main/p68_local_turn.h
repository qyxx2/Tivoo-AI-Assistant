#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define TIVOO_TURN_FRAME 320U
#define TIVOO_TURN_PENDING 16000U

typedef enum {
    TIVOO_TURN_START, TIVOO_TURN_GATE, TIVOO_TURN_SPEECH_START,
    TIVOO_TURN_PCM, TIVOO_TURN_SPEECH_END, TIVOO_TURN_ABORT
} tivoo_turn_event_t;
typedef bool (*tivoo_turn_send_t)(void *, tivoo_turn_event_t, const int16_t *, size_t, uint64_t, const char *);

typedef struct {
    bool active, start_sent, gated, gate_sent, ready, speaking, speech_sent, ended, complete;
    bool metrics_reported;
    uint32_t command_window_ms;
    uint32_t send_attempts, send_failures;
    uint64_t ready_ms;
    size_t peak_pending;
    uint64_t wake_ms, gate_ms, speech_ms, end_ms, next, last_progress_ms;
    size_t read, pending, valid_samples, pad_samples, sent;
    const char *abort_reason;
    int16_t ring[TIVOO_TURN_PENDING];
} tivoo_local_turn_t;

void tivoo_turn_begin(tivoo_local_turn_t *, uint64_t now);
bool tivoo_turn_followup_allowed(bool same_parent, bool reply_allowed, bool playback_complete, bool consumed);
void tivoo_turn_begin_followup(tivoo_local_turn_t *, uint64_t now);
void tivoo_turn_gate(tivoo_local_turn_t *, uint64_t now);
void tivoo_turn_ready(tivoo_local_turn_t *, uint64_t now);
void tivoo_turn_speech(tivoo_local_turn_t *, uint64_t now, uint64_t first);
void tivoo_turn_pcm(tivoo_local_turn_t *, uint64_t first, const int16_t *, size_t count);
void tivoo_turn_end(tivoo_local_turn_t *, uint64_t now, uint64_t end);
void tivoo_turn_abort(tivoo_local_turn_t *, const char *reason);
void tivoo_turn_tick(tivoo_local_turn_t *, uint64_t now, tivoo_turn_send_t send, void *ctx);
