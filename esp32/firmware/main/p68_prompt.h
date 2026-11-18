#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct { const int16_t *pcm; size_t samples; } tivoo_prompt_asset_t;
/* indices 0..2 are ready, 3 is followup; -1 means skip */
int tivoo_prompt_select(const tivoo_prompt_asset_t pool[4], bool followup, int last, unsigned random);

typedef struct {
    size_t (*push)(void *, const int16_t *, size_t);
    void (*finish)(void *);
    void (*stop)(void *);
    /* True only after the owner's digital drain. Both indices are 16k samples
     * on the physical TX clock, end is the exact conservative drain boundary. */
    bool (*drain)(void *, uint64_t *end, uint64_t *clock);
} tivoo_prompt_io_t;
typedef enum { TIVOO_PROMPT_PENDING, TIVOO_PROMPT_UNSAFE, TIVOO_PROMPT_SAFE } tivoo_prompt_status_t;
typedef struct {
    tivoo_prompt_asset_t asset;
    size_t written;
    uint64_t started_ms, physical_gate, gate_sample, gate_ms;
    unsigned tail;
    int offset; /* measured mapping from physical TX clock to logical AFE index */
    bool finished, stopping, drained, cancelled, skipped;
} tivoo_prompt_t;
void tivoo_prompt_begin(tivoo_prompt_t *, tivoo_prompt_asset_t, uint64_t now, unsigned tail, int offset);
void tivoo_prompt_cancel(tivoo_prompt_t *);
tivoo_prompt_status_t tivoo_prompt_poll(tivoo_prompt_t *, const tivoo_prompt_io_t *, void *, uint64_t now);
