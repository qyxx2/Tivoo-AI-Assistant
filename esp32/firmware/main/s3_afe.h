#pragma once
#include "esp_err.h"
#include "p68_afe_flow.h"

/* Starts the sole consumer of b3's capture queue. AFE events are local only.
 * A sink runs synchronously in the fetch task; copy/enqueue, never block.
 * Gate control is single-owner and is integrated with the turn in b5/b6.
 * Sample indices here are logical enhanced-stream indices; the physical
 * RX/TX -> fetch latency must be calibrated before a physical gate is used. */
esp_err_t tivoo_s3_afe_start(tivoo_afe_sink_t sink, void *ctx);
const char *tivoo_s3_afe_wake_word(int index);

/* Queue a logical-index control for the fetch owner, without waiting.
 * true means enqueued, not applied. A stale/overlapping OPEN emits GAP.
 * b5 owns session identity/ordering and must handle false/overflow. */
typedef enum {
    TIVOO_AFE_GATE_OPEN, TIVOO_AFE_GATE_CLOSE,
    TIVOO_AFE_PROMPT_BEGIN, TIVOO_AFE_PROMPT_END
} tivoo_afe_control_t;
bool tivoo_s3_afe_control(tivoo_afe_control_t control, uint64_t index);

/* Software-only test gate; called exclusively from the fetch-task sink.
 * b6 replaces this logical boundary with the calibrated physical one. */
bool tivoo_s3_afe_open_test_gate(void);
void tivoo_s3_afe_close_local_gate(void);
