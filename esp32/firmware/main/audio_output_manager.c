#include "audio_output_manager.h"

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
    return true;
}

size_t tivoo_output_push(tivoo_output_queue_t *queue, uint32_t generation,
    const int16_t *pcm, size_t samples)
{
    if (queue->generation != generation || generation == 0 || queue->stopped) {
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
    const size_t count = queue->count < TIVOO_OUTPUT_BLOCK ? queue->count : TIVOO_OUTPUT_BLOCK;
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
    return generation != 0 && queue->generation == generation && queue->count == 0 &&
        (!queue->in_dma || (int32_t)(completed - queue->last_due) > 0);
}

void tivoo_output_end(tivoo_output_queue_t *queue, uint32_t generation)
{
    if (queue->generation == generation) {
        queue->count = 0;
        queue->generation = 0;
    }
}

#ifdef ESP_PLATFORM
#include "audio_capture.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#define REFERENCE_SAMPLES (TIVOO_OUTPUT_BLOCK / 2U)
#define REFERENCE_BLOCKS 32U

typedef struct {
    uint32_t block;
    int16_t pcm[REFERENCE_SAMPLES];
    bool valid;
    bool has_pcm;
} reference_block_t;

static uint32_t *s_dma[TIVOO_OUTPUT_DMA_BLOCKS];
static size_t s_dma_count;
static size_t s_dma_index;
static bool s_mute_pending;
static unsigned s_missed_eofs;
static unsigned s_reference_peak;

static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static tivoo_output_queue_t s_queue;
static reference_block_t s_reference[REFERENCE_BLOCKS];
static uint32_t s_completed;
static uint32_t s_last_pcm;
static bool s_has_pcm;
static bool s_draining;
static unsigned s_underruns;
static unsigned s_high_water;

bool tivoo_audio_output_begin(uint32_t generation)
{
    if (CONFIG_TIVOO_I2S_DOUT_GPIO < 0 || !tivoo_audio_capture_running()) {
        return false;
    }
    portENTER_CRITICAL(&s_lock);
    const bool started = tivoo_output_begin(&s_queue, generation);
    if (started) {
        s_draining = false;
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
    if (tivoo_output_stop(&s_queue, generation)) {
        s_mute_pending = s_queue.in_dma;
    }
    portEXIT_CRITICAL(&s_lock);
}

bool tivoo_audio_output_drained(uint32_t generation)
{
    portENTER_CRITICAL(&s_lock);
    s_draining = true;
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
    size_t index = 0;
    while (index < s_dma_count && s_dma[index] != slots) {
        ++index;
    }
    if (index == s_dma_count && s_dma_count < TIVOO_OUTPUT_DMA_BLOCKS) {
        s_dma[s_dma_count++] = slots;
    } else if (s_dma_count == TIVOO_OUTPUT_DMA_BLOCKS) {
        size_t distance = (index + TIVOO_OUTPUT_DMA_BLOCKS - s_dma_index) %
            TIVOO_OUTPUT_DMA_BLOCKS;
        if (distance == 0) {
            distance = TIVOO_OUTPUT_DMA_BLOCKS;
        }
        s_completed += distance - 1;
        s_missed_eofs += distance - 1;
    }
    s_dma_index = index;
    const uint32_t due = ++s_completed + TIVOO_OUTPUT_DMA_BLOCKS;
    if (s_mute_pending && s_dma_count == TIVOO_OUTPUT_DMA_BLOCKS) {
        // At EOF the next descriptor may already be in the FIFO. Zero the
        // remaining future descriptors, leaving the clocks and RX running.
        for (size_t ahead = 2; ahead < TIVOO_OUTPUT_DMA_BLOCKS; ++ahead) {
            const uint32_t block = s_completed + ahead - 1;
            volatile uint32_t *buffer = s_dma[(index + ahead) % TIVOO_OUTPUT_DMA_BLOCKS];
            for (size_t slot = 0; slot < 2 * TIVOO_OUTPUT_BLOCK; ++slot) {
                buffer[slot] = 0;
            }
            reference_block_t *entry = &s_reference[block % REFERENCE_BLOCKS];
            entry->has_pcm = false;
        }
        if ((int32_t)(s_queue.last_due - s_completed) > 1) {
            s_queue.last_due = s_completed + 1;
        }
        s_mute_pending = false;
    }
    const size_t count = tivoo_output_refill(&s_queue, slots, due);
    if (count == 0 && s_queue.in_dma && !s_draining && !s_queue.stopped) {
        ++s_underruns;
    }
    reference_block_t *reference = &s_reference[(due - 1) % REFERENCE_BLOCKS];
    reference->block = due - 1;
    reference->valid = true;
    reference->has_pcm = count != 0;
    if (count != 0) {
        s_last_pcm = due - 1;
        s_has_pcm = true;
        for (size_t i = 0; i < REFERENCE_SAMPLES; ++i) {
            const int32_t a = (int16_t)(slots[4 * i] >> 16);
            const int32_t b = (int16_t)(slots[4 * i + 2] >> 16);
            reference->pcm[i] = (a + b) / 2;
        }
    }
    portEXIT_CRITICAL_ISR(&s_lock);
}

tivoo_audio_reference_status_t tivoo_audio_output_reference(
    uint64_t first_sample, int16_t *reference, size_t samples)
{
    tivoo_audio_reference_status_t result = TIVOO_AUDIO_REFERENCE_SILENT;
    for (size_t i = 0; i < samples;) {
        const uint64_t rx_sample = first_sample + i;
        if (rx_sample < CONFIG_TIVOO_AEC_REFERENCE_DELAY_SAMPLES) {
            reference[2 * i++] = 0;
            continue;
        }
        const uint64_t sample = rx_sample - CONFIG_TIVOO_AEC_REFERENCE_DELAY_SAMPLES;
        const uint32_t block = sample / REFERENCE_SAMPLES;
        const size_t offset = sample % REFERENCE_SAMPLES;
        const size_t left = REFERENCE_SAMPLES - offset;
        const size_t count = left < samples - i ? left : samples - i;

        portENTER_CRITICAL(&s_lock);
        const reference_block_t *entry = &s_reference[block % REFERENCE_BLOCKS];
        const bool available = entry->valid && entry->block == block;
        if (available && entry->has_pcm) {
            for (size_t j = 0; j < count; ++j) {
                const int16_t pcm = entry->pcm[offset + j];
                reference[2 * (i + j)] = pcm;
                const unsigned amplitude = pcm < 0 ? -(int)pcm : pcm;
                if (amplitude > s_reference_peak) {
                    s_reference_peak = amplitude;
                }
            }
            if (result == TIVOO_AUDIO_REFERENCE_SILENT) {
                result = TIVOO_AUDIO_REFERENCE_READY;
            }
        } else {
            for (size_t j = 0; j < count; ++j) {
                reference[2 * (i + j)] = 0;
            }
            if (!available && s_has_pcm && block >= TIVOO_OUTPUT_DMA_BLOCKS) {
                if ((int32_t)(s_last_pcm - block) >= 0) {
                    result = TIVOO_AUDIO_REFERENCE_MISALIGNED;
                } else if (s_queue.count != 0 && result != TIVOO_AUDIO_REFERENCE_MISALIGNED) {
                    result = TIVOO_AUDIO_REFERENCE_UNDERRUN;
                }
            }
        }
        portEXIT_CRITICAL(&s_lock);
        i += count;
    }
    return result;
}
#endif
