#include "audio_capture.h"

#include <limits.h>

#ifdef ESP_PLATFORM
#include "esp_attr.h"
#define TIVOO_CAPTURE_ISR_CODE IRAM_ATTR
#else
#define TIVOO_CAPTURE_ISR_CODE
#endif

void tivoo_dma_eof_tracker_reset(
    tivoo_dma_eof_tracker_t *tracker, void **buffers, size_t capacity)
{
    tracker->buffers = buffers;
    tracker->capacity = capacity;
    tracker->count = 0;
    tracker->index = 0;
    tracker->order_uncertain = false;
}

size_t TIVOO_CAPTURE_ISR_CODE tivoo_dma_eof_tracker_observe(
    tivoo_dma_eof_tracker_t *tracker, void *buffer)
{
    size_t index = 0;
    while (index < tracker->count && tracker->buffers[index] != buffer) {
        ++index;
    }

    if (index == tracker->count) {
        if (tracker->count < tracker->capacity) {
            tracker->buffers[tracker->count++] = buffer;
            tracker->index = index;
        }
        return 0;
    }
    if (tracker->count < tracker->capacity) {
        /* Repeated pointer before discovering the entire hardware ring.
         * Exact startup alignment is unrecoverable without restarting I2S. */
        tracker->order_uncertain = true;
        tracker->index = index;
        return 0;
    }

    size_t distance = index >= tracker->index
        ? index - tracker->index
        : tracker->capacity - tracker->index + index;
    if (distance == 0) {
        distance = tracker->capacity;
    }
    tracker->index = index;
    return distance - 1;
}

/* 32 kHz low-pass, 6.72 kHz cutoff, Blackman-windowed sinc in Q15.
 * Coefficients sum to 32768 so that DC gain is unity. */
static const int16_t lowpass[TIVOO_DECIMATOR_TAPS] = {
    0, -1, -13, -4, 68, 80, -148, -341, 110, 884, 406, -1643, -2152,
    2337, 9922, 13758, 9922, 2337, -2152, -1643, 406, 884, 110, -341,
    -148, 80, 68, -4, -13, -1, 0,
};

int32_t tivoo_inmp441_sample(uint32_t left_slot)
{
    const int32_t sample = (int32_t)(left_slot >> 8);
    return sample >= 0x800000 ? sample - 0x1000000 : sample;
}

/* Use exactly the same sample phase, coefficients and rounding on both mics
 * and final TX reference. Input is represented as signed 24-bit PCM. */
static bool decimate_sample(tivoo_decimator_t *filter, int32_t sample, int16_t *out)
{
    filter->history[filter->next] = sample;
    if (++filter->next == TIVOO_DECIMATOR_TAPS) filter->next = 0;
    filter->phase ^= 1U;
    if (filter->phase) return false;
    int64_t sum = 0;
    size_t slot = filter->next;
    for (size_t tap = 0; tap < TIVOO_DECIMATOR_TAPS; ++tap) {
        sum += (int64_t)filter->history[slot] * lowpass[tap];
        if (++slot == TIVOO_DECIMATOR_TAPS) slot = 0;
    }
    const int32_t pcm = (int32_t)((sum + (sum < 0 ? -4194304 : 4194304)) / 8388608);
    *out = pcm > INT16_MAX ? INT16_MAX : pcm < INT16_MIN ? INT16_MIN : pcm;
    return true;
}

static size_t decimate_slot(tivoo_decimator_t *filter, const uint32_t *stereo,
    size_t frames, int16_t *mono)
{
    size_t produced = 0;
    for (size_t i = 0; i < frames; ++i)
        if (decimate_sample(filter, tivoo_inmp441_sample(stereo[2*i]), &mono[produced]))
            ++produced;
    return produced;
}

size_t tivoo_audio_decimate_pcm16(tivoo_decimator_t *filter, const int16_t *pcm,
    size_t samples, int16_t *mono)
{
    size_t produced = 0;
    for (size_t i = 0; i < samples; ++i)
        if (decimate_sample(filter, (int32_t)pcm[i]*256, &mono[produced]))
            ++produced;
    return produced;
}

size_t tivoo_audio_decimate(tivoo_decimator_t *filter, const uint32_t *stereo,
    size_t frames, int16_t *mono)
{
    return decimate_slot(filter, stereo, frames, mono);
}

size_t tivoo_audio_decimate_stereo(tivoo_stereo_decimator_t *filter,
    const uint32_t *stereo, size_t frames, int16_t *left, int16_t *right)
{
    const size_t n = decimate_slot(&filter->left, stereo, frames, left);
    decimate_slot(&filter->right, stereo + 1, frames, right);
    return n;
}

bool tivoo_rx_timeline_accept(tivoo_rx_timeline_t *timeline, uint64_t block, bool *gap)
{
    *gap = false;
    if (block < timeline->next_block) return false;
    if (block >= TIVOO_RX_SETTLE_BLOCKS) {
        const uint64_t expected = timeline->next_block < TIVOO_RX_SETTLE_BLOCKS
            ? TIVOO_RX_SETTLE_BLOCKS : timeline->next_block;
        timeline->lost_blocks += block - expected;
        *gap = block != expected;
    }
    timeline->next_block = block + 1;
    return block >= TIVOO_RX_SETTLE_BLOCKS;
}

#ifdef ESP_PLATFORM
#include <stdatomic.h>

#include "audio_output_manager.h"
#include "driver/i2s_std.h"
#include "sdkconfig.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

static i2s_chan_handle_t s_rx;
static i2s_chan_handle_t s_tx;
static bool s_tx_enabled;
static bool s_rx_enabled;
static atomic_bool s_running, s_accept_callbacks, s_recovering, s_unavailable;
static bool s_recovery_attempted;
static int s_driver_core;
static uint64_t s_epoch_base;
static void *s_rx_dma[TIVOO_OUTPUT_DMA_BLOCKS];
static tivoo_dma_eof_tracker_t s_rx_dma_tracker;
static atomic_uint s_rx_overruns;
static atomic_uint s_rx_missed_eofs;
static atomic_bool s_rx_order_uncertain;

/* Own the payload at EOF, not a delayed driver DMA pointer. One queue and
 * one serial block counter mean an EOF skip and queue drop cannot count
 * the same block twice. The unused IDF pointer queue has no overflow callback. */
typedef struct {
    uint64_t block;
    uint32_t slots[2 * TIVOO_OUTPUT_BLOCK];
} rx_block_t;
static QueueHandle_t s_blocks;
static StaticQueue_t s_block_queue;
static uint8_t s_block_storage[TIVOO_OUTPUT_DMA_BLOCKS * sizeof(rx_block_t)];
static rx_block_t s_isr_block, s_task_block;
static uint64_t s_next_block;
static tivoo_rx_timeline_t s_timeline;
static tivoo_stereo_decimator_t s_filter;
static tivoo_decimator_t s_tx_filter;
static int16_t s_tx_raw[TIVOO_OUTPUT_BLOCK];
static bool s_pending_gap;
static size_t s_queue_peak;

static bool IRAM_ATTR rx_received(i2s_chan_handle_t handle, i2s_event_data_t *event, void *context)
{
    (void)handle;
    (void)context;
    if (!atomic_load_explicit(&s_accept_callbacks,memory_order_relaxed)) return false;
    const size_t missed = tivoo_dma_eof_tracker_observe(&s_rx_dma_tracker, event->dma_buf);
    if (s_rx_dma_tracker.order_uncertain)
        atomic_store_explicit(&s_rx_order_uncertain, true, memory_order_relaxed);
    if (missed) atomic_fetch_add_explicit(&s_rx_missed_eofs, missed, memory_order_relaxed);
    if (missed || s_rx_dma_tracker.order_uncertain || event->size != sizeof(s_isr_block.slots)) {
        tivoo_audio_output_fault_from_isr();
        return false;
    }
    s_next_block += missed;
    s_isr_block.block = s_next_block++;
    const volatile uint32_t *source = event->dma_buf;
    for (size_t i = 0; i < 2 * TIVOO_OUTPUT_BLOCK; ++i) s_isr_block.slots[i] = source[i];
    BaseType_t wake = pdFALSE;
    if (xQueueSendFromISR(s_blocks, &s_isr_block, &wake) != pdTRUE) {
        atomic_fetch_add_explicit(&s_rx_overruns, 1, memory_order_relaxed);
    }
    return wake == pdTRUE;
}

static bool IRAM_ATTR tx_sent(i2s_chan_handle_t handle, i2s_event_data_t *event, void *context)
{
    (void)handle;
    (void)context;
    if (atomic_load_explicit(&s_accept_callbacks,memory_order_relaxed)) {
        if (event->size != 2*TIVOO_OUTPUT_BLOCK*sizeof(uint32_t))
            tivoo_audio_output_fault_from_isr();
        else
            tivoo_audio_output_dma_sent(event->dma_buf);
    }
    return false;
}

bool tivoo_audio_capture_running(void)
{
    return atomic_load(&s_running);
}

/* Stop BOTH sides before deleting either side. The recovery worker is pinned
 * to the original IDF allocation core; no concurrent old ISR can traverse
 * a descriptor we free. GDMA deletion disables/clears pending interrupts. */
static esp_err_t close_channels(void)
{
    atomic_store(&s_running,false);
    atomic_store(&s_accept_callbacks,false);
    esp_err_t rx_err=ESP_OK, tx_err=ESP_OK;
    if (s_rx_enabled) {
        rx_err=i2s_channel_disable(s_rx);
        if (rx_err==ESP_OK) s_rx_enabled=false;
    }
    if (s_tx_enabled) {
        tx_err=i2s_channel_disable(s_tx);
        if (tx_err==ESP_OK) s_tx_enabled=false;
    }
    if (rx_err!=ESP_OK || tx_err!=ESP_OK) return rx_err!=ESP_OK ? rx_err : tx_err;
    /* Let any already pending IRQ finish on this same core before freeing
     * its driver descriptors. User callbacks are disabled above. */
    if (s_rx || s_tx) vTaskDelay(1);
    if (s_rx) {
        rx_err=i2s_del_channel(s_rx);
        if (rx_err==ESP_OK) s_rx=NULL;
    }
    if (s_tx) {
        tx_err=i2s_del_channel(s_tx);
        if (tx_err==ESP_OK) s_tx=NULL;
    }
    return rx_err!=ESP_OK ? rx_err : tx_err;
}

void tivoo_audio_capture_close(void)
{
    (void)close_channels();
}

static esp_err_t start_channels(uint64_t base, bool initial)
{
    i2s_chan_config_t channels = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    channels.dma_desc_num = TIVOO_OUTPUT_DMA_BLOCKS;
    channels.dma_frame_num = TIVOO_OUTPUT_BLOCK;
    const i2s_std_config_t format = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(32000),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = CONFIG_TIVOO_I2S_BCLK_GPIO,
            .ws = CONFIG_TIVOO_I2S_WS_GPIO,
            .dout = CONFIG_TIVOO_I2S_DOUT_GPIO,
            .din = CONFIG_TIVOO_I2S_DIN_GPIO,
        },
    };
    const i2s_event_callbacks_t callbacks = {
        .on_recv = rx_received,
    };

    if (initial) {
        atomic_store_explicit(&s_rx_overruns, 0, memory_order_relaxed);
        atomic_store_explicit(&s_rx_missed_eofs, 0, memory_order_relaxed);
    }
    atomic_store_explicit(&s_rx_order_uncertain, false, memory_order_relaxed);
    tivoo_dma_eof_tracker_reset(&s_rx_dma_tracker, s_rx_dma, TIVOO_OUTPUT_DMA_BLOCKS);

    if (!s_blocks) s_blocks = xQueueCreateStatic(TIVOO_OUTPUT_DMA_BLOCKS, sizeof(rx_block_t),
        s_block_storage, &s_block_queue);
    if (!s_blocks) return ESP_ERR_NO_MEM;
    xQueueReset(s_blocks);
    s_epoch_base = s_next_block = base;
    s_timeline.next_block = base + TIVOO_RX_SETTLE_BLOCKS;
    if (initial) s_timeline.lost_blocks = 0;
    s_filter = (tivoo_stereo_decimator_t){0};
    s_tx_filter = (tivoo_decimator_t){0};
    s_pending_gap = !initial;
    if (initial) {
        s_queue_peak = 0;
        tivoo_audio_output_reset();
    } else {
        tivoo_audio_output_restart_clock(base);
    }
    channels.auto_clear_before_cb = false;
    channels.auto_clear_after_cb = false;

    esp_err_t err = i2s_new_channel(&channels, &s_tx, &s_rx);
    if (err == ESP_OK) {
        err = i2s_channel_init_std_mode(s_tx, &format);
    }
    if (err == ESP_OK) {
        err = i2s_channel_init_std_mode(s_rx, &format);
    }
    if (err == ESP_OK) {
        err = i2s_channel_register_event_callback(s_rx, &callbacks, NULL);
    }
    if (err == ESP_OK) {
        const i2s_event_callbacks_t tx_callbacks = {.on_sent = tx_sent};
        err = i2s_channel_register_event_callback(s_tx, &tx_callbacks, NULL);
    }
    if (err == ESP_OK) {
        atomic_store(&s_accept_callbacks,true);
        err = i2s_channel_enable(s_rx);
        s_rx_enabled = err == ESP_OK;
    }
    if (err == ESP_OK) {
        err = i2s_channel_enable(s_tx);
        s_tx_enabled = err == ESP_OK;
    }
    if (err != ESP_OK) {
        (void)close_channels();
        tivoo_audio_output_request_recovery();
    } else if (initial) {
        atomic_store(&s_running,true);
    }
    return err;
}

esp_err_t tivoo_audio_capture_start(void)
{
    if (s_rx || s_tx || atomic_load(&s_recovering)) return ESP_ERR_INVALID_STATE;
    s_driver_core=xPortGetCoreID();
    s_recovery_attempted=false;
    atomic_store(&s_unavailable,false);
    return start_channels(0,true);
}

static void recover_capture(void *arg)
{
    const bool stop_only = arg != NULL;
    esp_err_t err=close_channels();
    /* The old callbacks are gone. Rebase both clocks monotonically; the
     * discontinuity is explicit, not a fabricated run of silent samples. */
    uint64_t base=tivoo_audio_output_clock_blocks();
    if (s_next_block>base) base=s_next_block;
    if (err==ESP_OK && !stop_only) err=start_channels(base+1,false);
    if (err!=ESP_OK || stop_only) {
        tivoo_audio_output_request_recovery();
        atomic_store(&s_unavailable,true);
        ESP_LOGE("audio_capture","DMA recovery unavailable (err=%d, repeated=%d)",err,stop_only);
    } else {
        ESP_LOGW("audio_capture","DMA restarted at block=%llu; old owner invalidated",
            (unsigned long long)(base+1));
    }
    atomic_store(&s_recovering,false);
    vTaskDelete(NULL);
}

static esp_err_t schedule_recovery(void)
{
    atomic_store(&s_running,false);
    atomic_store(&s_recovering,true);
    bool stop_only=s_recovery_attempted;
    s_recovery_attempted=true;
    if (xTaskCreatePinnedToCore(recover_capture,"dma_recover",4096,
            stop_only ? (void *)1 : NULL, 6,NULL,s_driver_core)!=pdPASS) {
        atomic_store(&s_unavailable,true);
        atomic_store(&s_recovering,false);
        ESP_LOGE("audio_capture","DMA recovery task unavailable");
    }
    return ESP_ERR_INVALID_STATE;
}

esp_err_t tivoo_audio_capture_next(tivoo_capture_frame_t *frame)
{
    if (!frame || !s_blocks) return ESP_ERR_INVALID_ARG;
    for (;;) {
        if (atomic_load(&s_recovering) || atomic_load(&s_unavailable)) {
            vTaskDelay(1);
            return ESP_ERR_INVALID_STATE;
        }
        if (tivoo_audio_output_faulted()) return schedule_recovery();
        if (xQueueReceive(s_blocks, &s_task_block, pdMS_TO_TICKS(100)) != pdTRUE) {
            s_pending_gap = true;
            tivoo_audio_output_request_recovery();
            return schedule_recovery();
        }
        if (tivoo_audio_output_faulted()) return schedule_recovery();
        if (s_task_block.block < s_epoch_base + TIVOO_RX_SETTLE_BLOCKS) continue;
        const size_t depth = uxQueueMessagesWaiting(s_blocks) + 1;
        if (depth > s_queue_peak) s_queue_peak = depth;
        bool gap;
        if (!tivoo_rx_timeline_accept(&s_timeline, s_task_block.block, &gap)) continue;
        frame->first_sample = s_task_block.block * TIVOO_CAPTURE_SAMPLES;
        frame->raw_slots = s_task_block.slots;
        frame->raw_tx = s_tx_raw;
        const uint64_t tx_sample = 2 * (frame->first_sample - CONFIG_TIVOO_AEC_REFERENCE_DELAY_SAMPLES);
        frame->tx_first_sample = tx_sample;
        /* RX and TX EOF callbacks may be delivered in either order.
         * Allow a bounded scheduling turn for the same block's TX EOF. */
        frame->reference_valid = tivoo_audio_output_reference_raw(
            tx_sample, s_tx_raw, TIVOO_OUTPUT_BLOCK);
        if (!frame->reference_valid) {
            vTaskDelay(1);
            frame->reference_valid = tivoo_audio_output_reference_raw(
                tx_sample, s_tx_raw, TIVOO_OUTPUT_BLOCK);
        }
        if (tivoo_audio_output_faulted()) return schedule_recovery();
        frame->reference_valid &= !atomic_load_explicit(&s_rx_order_uncertain, memory_order_relaxed);
        frame->gap = gap || s_pending_gap || !frame->reference_valid;
        /* A recreated driver is not yet a usable epoch. Once settle has
         * elapsed allow one DMA ring to obtain a continuous, aligned frame;
         * then stop rather than repeatedly restart an unproven stream. */
        if (s_recovery_attempted && frame->gap &&
            s_task_block.block >= s_epoch_base+TIVOO_RX_SETTLE_BLOCKS+TIVOO_OUTPUT_DMA_BLOCKS) {
            ESP_LOGE("audio_capture","DMA recovery did not produce aligned reference");
            tivoo_audio_output_request_recovery();
            return schedule_recovery();
        }
        if (frame->gap) {
            s_filter = (tivoo_stereo_decimator_t){0};
            s_tx_filter = (tivoo_decimator_t){0};
        }
        tivoo_audio_decimate_stereo(&s_filter, s_task_block.slots,
            TIVOO_OUTPUT_BLOCK, frame->left, frame->right);
        tivoo_audio_decimate_pcm16(&s_tx_filter, s_tx_raw,
            TIVOO_OUTPUT_BLOCK, frame->reference);
        s_pending_gap = !frame->reference_valid;
        if (frame->reference_valid && !frame->gap && s_recovery_attempted) {
            s_recovery_attempted=false;
            atomic_store(&s_running,true);
            ESP_LOGI("audio_capture","DMA recovery valid sample=%llu",
                (unsigned long long)frame->first_sample);
        }
        return ESP_OK;
    }
}

static void capture_monitor(void *arg)
{
    (void)arg;
    tivoo_capture_frame_t frame;
    unsigned frames = 0, gaps = 0, ref_missing = 0, lp = 0, rp = 0, tp = 0, timeouts = 0;
    for (;;) {
        if (tivoo_audio_capture_next(&frame) != ESP_OK) {
            if (++timeouts % 10 == 0) ESP_LOGW("audio_capture", "RX timeouts=%u", timeouts);
            continue;
        }
        gaps += frame.gap;
        ref_missing += !frame.reference_valid;
        for (size_t i = 0; i < TIVOO_CAPTURE_SAMPLES; ++i) {
            unsigned l = frame.left[i] < 0 ? -(int)frame.left[i] : frame.left[i];
            unsigned r = frame.right[i] < 0 ? -(int)frame.right[i] : frame.right[i];
            unsigned t = frame.reference[i] < 0 ? -(int)frame.reference[i] : frame.reference[i];
            if (l > lp) lp = l;
            if (r > rp) rp = r;
            if (t > tp) tp = t;
        }
        if (++frames == 200) {
            ESP_LOGI("audio_capture", "sample=%llu L/R/TX peak=%u/%u/%u gaps=%u ref_missing=%u lost_blocks=%llu rx_queue_peak=%zu internal_min=%zu dma_free=%zu stack_water=%u",
                (unsigned long long)frame.first_sample, lp, rp, tp, gaps, ref_missing,
                (unsigned long long)s_timeline.lost_blocks, s_queue_peak,
                heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL),
                heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA),
                (unsigned)uxTaskGetStackHighWaterMark(NULL));
            frames = gaps = ref_missing = lp = rp = tp = 0;
        }
    }
}

esp_err_t tivoo_audio_capture_monitor_start(void)
{
    return xTaskCreatePinnedToCore(capture_monitor, "tivoo_capture", 4096, NULL, 5, NULL, 1)
        == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}

/* Legacy frontend remains source-only until b9. */
esp_err_t tivoo_audio_capture_read(uint32_t *stereo, size_t bytes, size_t *read)
{
    return i2s_channel_read(s_rx, stereo, bytes, read, 100);
}

uint32_t tivoo_audio_capture_overruns(void)
{
    return atomic_load_explicit(&s_rx_overruns, memory_order_relaxed);
}

uint32_t tivoo_audio_capture_missed_eofs(void)
{
    return atomic_load_explicit(&s_rx_missed_eofs, memory_order_relaxed);
}
#endif
