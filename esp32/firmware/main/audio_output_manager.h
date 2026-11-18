#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define TIVOO_OUTPUT_BLOCK 160U
#define TIVOO_OUTPUT_DMA_BLOCKS 12U
#define TIVOO_OUTPUT_QUEUE_SAMPLES (32U * TIVOO_OUTPUT_BLOCK)
#define TIVOO_OUTPUT_PREFILL (24U * TIVOO_OUTPUT_BLOCK)

typedef struct {
    int16_t pcm[TIVOO_OUTPUT_QUEUE_SAMPLES];
    size_t read;
    size_t count;
    uint32_t generation;
    uint32_t last_due;
    bool in_dma;
    bool stopped;
    bool input_finished;
} tivoo_output_queue_t;

bool tivoo_output_begin(tivoo_output_queue_t *queue, uint32_t generation);
size_t tivoo_output_push(tivoo_output_queue_t *queue, uint32_t generation,
    const int16_t *pcm, size_t samples);
size_t tivoo_output_refill(tivoo_output_queue_t *queue, uint32_t *slots, uint32_t due);
bool tivoo_output_finish_input(tivoo_output_queue_t *queue, uint32_t generation);
bool tivoo_output_stop(tivoo_output_queue_t *queue, uint32_t generation);
bool tivoo_output_drained(const tivoo_output_queue_t *queue, uint32_t generation,
    uint32_t completed);
void tivoo_output_end(tivoo_output_queue_t *queue, uint32_t generation);

#define TIVOO_REFERENCE_BLOCKS 32U
#define TIVOO_REFERENCE_SAMPLES TIVOO_OUTPUT_BLOCK
typedef struct {
    uint64_t block;
    int16_t pcm[TIVOO_REFERENCE_SAMPLES];
    bool valid;
} tivoo_tx_reference_block_t;
typedef struct {
    tivoo_tx_reference_block_t blocks[TIVOO_REFERENCE_BLOCKS];
} tivoo_tx_reference_t;
void tivoo_tx_reference_record(tivoo_tx_reference_t *reference, uint64_t block, const uint32_t *slots);
bool tivoo_tx_reference_read(const tivoo_tx_reference_t *reference, uint64_t first_sample,
    int16_t *pcm, size_t samples);

#ifdef ESP_PLATFORM
#include "audio_frontend.h"
void tivoo_audio_output_reset(void);
bool tivoo_audio_output_reference_raw(uint64_t first_sample, int16_t *pcm, size_t samples);

bool tivoo_audio_output_begin(uint32_t generation);
esp_err_t tivoo_audio_output_write(uint32_t generation, const int16_t *pcm, size_t samples);
void tivoo_audio_output_stop(uint32_t generation);
void tivoo_audio_output_finish_input(uint32_t generation);
bool tivoo_audio_output_drained(uint32_t generation);
void tivoo_audio_output_end(uint32_t generation);
void tivoo_audio_output_dma_sent(uint32_t *slots);
tivoo_audio_reference_status_t tivoo_audio_output_reference(
    uint64_t first_sample, int16_t *reference, size_t samples);
#endif
