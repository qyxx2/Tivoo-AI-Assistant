#include "audio_output_manager.h"
#include <string.h>

#ifdef ESP_PLATFORM
#include "esp_attr.h"
#define TX_ISR_CODE IRAM_ATTR
#else
#define TX_ISR_CODE
#endif

bool tivoo_output_begin(tivoo_output_queue_t *queue, uint32_t generation)
{
    if (generation == 0 || queue->generation != 0) {
        return false;
    }
    queue->generation = generation;
    queue->stopped = false;
    queue->in_dma = false;
    queue->input_finished = false;
    return true;
}

size_t tivoo_output_push(tivoo_output_queue_t *queue, uint32_t generation,
    const int16_t *pcm, size_t samples)
{
    if (queue->generation != generation || generation == 0 || queue->stopped || queue->input_finished) {
        return 0;
    }
    const size_t space = TIVOO_OUTPUT_QUEUE_SAMPLES - queue->count;
    const size_t accepted = samples < space ? samples : space;
    size_t write = (queue->read + queue->count) % TIVOO_OUTPUT_QUEUE_SAMPLES;
    for (size_t i = 0; i < accepted; ++i) {
        queue->pcm[write] = pcm[i];
        if (++write == TIVOO_OUTPUT_QUEUE_SAMPLES) {
            write = 0;
        }
    }
    queue->count += accepted;
    return accepted;
}

size_t TX_ISR_CODE tivoo_output_refill(tivoo_output_queue_t *queue, uint32_t *slots, uint32_t due)
{
    volatile uint32_t *dma = slots;
    size_t count = 0;
    if (queue->in_dma || queue->input_finished || queue->count >= TIVOO_OUTPUT_PREFILL) {
        count = queue->count < TIVOO_OUTPUT_BLOCK ? queue->count : TIVOO_OUTPUT_BLOCK;
    }
    for (size_t i = 0; i < count; ++i) {
        const uint32_t sample = (uint32_t)(uint16_t)queue->pcm[queue->read] << 16;
        dma[2 * i] = sample;
        dma[2 * i + 1] = sample;
        if (++queue->read == TIVOO_OUTPUT_QUEUE_SAMPLES) {
            queue->read = 0;
        }
    }
    for (size_t i = 2 * count; i < 2 * TIVOO_OUTPUT_BLOCK; ++i) {
        dma[i] = 0;
    }
    queue->count -= count;
    if (count != 0) {
        queue->last_due = due;
        queue->in_dma = true;
    }
    return count;
}

bool tivoo_output_finish_input(tivoo_output_queue_t *queue, uint32_t generation)
{
    if (queue->generation != generation || generation == 0 || queue->stopped) {
        return false;
    }
    queue->input_finished = true;
    return true;
}

bool tivoo_output_stop(tivoo_output_queue_t *queue, uint32_t generation)
{
    if (queue->generation != generation || generation == 0) {
        return false;
    }
    queue->stopped = true;
    queue->count = 0;
    return true;
}

bool tivoo_output_drained(const tivoo_output_queue_t *queue, uint32_t generation,
    uint32_t completed)
{
    return generation != 0 && queue->generation == generation &&
        (queue->input_finished || queue->stopped) && queue->count == 0 &&
        (!queue->in_dma || (int32_t)(completed - queue->last_due) > 0);
}

void tivoo_output_end(tivoo_output_queue_t *queue, uint32_t generation)
{
    if (queue->generation == generation) {
        queue->count = 0;
        queue->generation = 0;
    }
}

/* Store only the descriptor that actually reached EOF, before refilling it.
 * Keep the original 32k mono samples: the capture task applies the same
 * 31-tap low-pass as both microphones, never inside the ISR. */
void TX_ISR_CODE tivoo_tx_reference_record(tivoo_tx_reference_t *reference,
    uint64_t block, const uint32_t *slots)
{
    tivoo_tx_reference_block_t *entry = &reference->blocks[block % TIVOO_REFERENCE_BLOCKS];
    entry->block = block;
    for (size_t i = 0; i < TIVOO_REFERENCE_SAMPLES; ++i) {
        entry->pcm[i] = (int16_t)(slots[2*i] >> 16);
    }
    entry->valid = true;
}

bool tivoo_tx_reference_read(const tivoo_tx_reference_t *reference, uint64_t first_sample,
    int16_t *pcm, size_t samples)
{
    bool valid = true;
    for (size_t i = 0; i < samples;) {
        const uint64_t sample = first_sample+i;
        const uint64_t block = sample/TIVOO_REFERENCE_SAMPLES;
        const size_t offset = sample%TIVOO_REFERENCE_SAMPLES;
        const size_t left = TIVOO_REFERENCE_SAMPLES-offset;
        const size_t count = left < samples-i ? left : samples-i;
        const tivoo_tx_reference_block_t *entry = &reference->blocks[block%TIVOO_REFERENCE_BLOCKS];
        const bool found = entry->valid && entry->block == block;
        valid &= found;
        for (size_t j=0; j<count; ++j) pcm[i+j] = found ? entry->pcm[offset+j] : 0;
        i += count;
    }
    return valid;
}

#ifdef ESP_PLATFORM
#include "audio_capture.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

static void *s_dma[TIVOO_OUTPUT_DMA_BLOCKS];
static tivoo_dma_eof_tracker_t s_tracker;
static unsigned s_missed_eofs;
static unsigned s_reference_peak;
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static tivoo_output_queue_t s_queue;
static tivoo_tx_reference_t s_reference;
static uint64_t s_completed;
static unsigned s_underruns;
static unsigned s_high_water;

void tivoo_audio_output_reset(void)
{
    portENTER_CRITICAL(&s_lock);
    memset(&s_queue, 0, sizeof(s_queue));
    memset(&s_reference, 0, sizeof(s_reference));
    s_completed = 0;
    s_missed_eofs = 0;
    tivoo_dma_eof_tracker_reset(&s_tracker, s_dma, TIVOO_OUTPUT_DMA_BLOCKS);
    portEXIT_CRITICAL(&s_lock);
}

bool tivoo_audio_output_begin(uint32_t generation)
{
    if (CONFIG_TIVOO_I2S_DOUT_GPIO < 0 || !tivoo_audio_capture_running()) {
        return false;
    }
    portENTER_CRITICAL(&s_lock);
    const bool started = tivoo_output_begin(&s_queue, generation);
    if (started) {
        s_underruns = 0;
        s_high_water = 0;
        s_reference_peak = 0;
    }
    portEXIT_CRITICAL(&s_lock);
    return started;
}

esp_err_t tivoo_audio_output_write(uint32_t generation, const int16_t *pcm, size_t samples)
{
    int64_t deadline = esp_timer_get_time() + 250000;
    while (samples != 0) {
        portENTER_CRITICAL(&s_lock);
        if (s_queue.generation != generation || s_queue.stopped) {
            portEXIT_CRITICAL(&s_lock);
            return ESP_ERR_INVALID_STATE;
        }
        const size_t batch = samples < TIVOO_OUTPUT_BLOCK ? samples : TIVOO_OUTPUT_BLOCK;
        const size_t count = tivoo_output_push(&s_queue, generation, pcm, batch);
        if (s_queue.count > s_high_water) {
            s_high_water = s_queue.count;
        }
        portEXIT_CRITICAL(&s_lock);
        pcm += count;
        samples -= count;
        if (count != 0) {
            deadline = esp_timer_get_time() + 250000;
        } else {
            if (esp_timer_get_time() >= deadline) {
                return ESP_ERR_TIMEOUT;
            }
            vTaskDelay(1);
        }
    }
    return ESP_OK;
}

void tivoo_audio_output_stop(uint32_t generation)
{
    portENTER_CRITICAL(&s_lock);
    /* Never alter a descriptor that may already have been fetched by GDMA.
     * Drain the already submitted (<=60ms) tail; completed reference stays real. */
    tivoo_output_stop(&s_queue, generation);
    portEXIT_CRITICAL(&s_lock);
}

void tivoo_audio_output_finish_input(uint32_t generation)
{
    portENTER_CRITICAL(&s_lock);
    tivoo_output_finish_input(&s_queue, generation);
    portEXIT_CRITICAL(&s_lock);
}

bool tivoo_audio_output_drained(uint32_t generation)
{
    portENTER_CRITICAL(&s_lock);
    const bool drained = tivoo_output_drained(&s_queue, generation, s_completed);
    portEXIT_CRITICAL(&s_lock);
    return drained;
}

void tivoo_audio_output_end(uint32_t generation)
{
    portENTER_CRITICAL(&s_lock);
    const unsigned underruns = s_underruns;
    const unsigned high_water = s_high_water;
    const unsigned missed_eofs = s_missed_eofs;
    const unsigned reference_peak = s_reference_peak;
    tivoo_output_end(&s_queue, generation);
    portEXIT_CRITICAL(&s_lock);
    ESP_LOGI("audio_output", "generation=%lu TX underruns=%u queue_high_water=%u "
        "missed_eofs=%u reference_peak=%u", (unsigned long)generation, underruns,
        high_water, missed_eofs, reference_peak);
}

void IRAM_ATTR tivoo_audio_output_dma_sent(uint32_t *slots)
{
    portENTER_CRITICAL_ISR(&s_lock);
    const size_t missed = tivoo_dma_eof_tracker_observe(&s_tracker, slots);
    s_completed += missed;
    s_missed_eofs += missed;
    tivoo_tx_reference_record(&s_reference, s_completed, slots);
    /* GDMA EOF can precede actual FIFO output. Preserve one more descriptor
     * interval for drain, as in the previous output manager. */
    const uint32_t due = (uint32_t)(++s_completed + TIVOO_OUTPUT_DMA_BLOCKS);
    const size_t count = tivoo_output_refill(&s_queue, slots, due);
    if (!count && s_queue.in_dma && !s_queue.input_finished && !s_queue.stopped)
        ++s_underruns;
    portEXIT_CRITICAL_ISR(&s_lock);
}

bool tivoo_audio_output_reference_raw(uint64_t first_sample, int16_t *pcm, size_t samples)
{
    portENTER_CRITICAL(&s_lock);
    bool valid = tivoo_tx_reference_read(&s_reference, first_sample, pcm, samples) &&
        !s_tracker.order_uncertain;
    for (size_t i=0;i<samples;i++) {
        const unsigned amplitude = pcm[i] < 0 ? -(int)pcm[i] : pcm[i];
        if (amplitude > s_reference_peak) s_reference_peak = amplitude;
    }
    portEXIT_CRITICAL(&s_lock);
    return valid;
}

/* Preserve the old source-only MR reader; not part of the S3 target. */
tivoo_audio_reference_status_t tivoo_audio_output_reference(
    uint64_t first_sample, int16_t *reference, size_t samples)
{
    bool valid = true, signal = false;
    for (size_t i=0;i<samples;i++) {
        int16_t pair[2];
#if CONFIG_TIVOO_AEC_REFERENCE_DELAY_SAMPLES > 0
        if (first_sample+i < CONFIG_TIVOO_AEC_REFERENCE_DELAY_SAMPLES) {
            reference[2*i] = 0;
            continue;
        }
#endif
        valid &= tivoo_audio_output_reference_raw(
            2*(first_sample+i-CONFIG_TIVOO_AEC_REFERENCE_DELAY_SAMPLES),pair,2);
        reference[2*i] = ((int32_t)pair[0]+pair[1])/2;
        signal |= reference[2*i] != 0;
    }
    return !valid ? TIVOO_AUDIO_REFERENCE_MISALIGNED :
        signal ? TIVOO_AUDIO_REFERENCE_READY : TIVOO_AUDIO_REFERENCE_SILENT;
}
#endif
