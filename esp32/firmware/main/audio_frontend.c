#include "audio_frontend.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "diagnostics.h"

static bool send_json(tivoo_mic_producer_t *mic, uint8_t type, const char *json)
{
    return mic->send(mic->generation, type, json, strlen(json));
}

static bool send_activity(tivoo_mic_producer_t *mic, bool speech, uint64_t uptime_ms)
{
    char json[144];
    snprintf(json, sizeof(json),
        "{\"session_id\":\"%s\",\"state\":\"%s\",\"uptime_ms\":%" PRIu64 "}",
        mic->session_id, speech ? "speech_start" : "speech_end", uptime_ms);
    return send_json(mic, TVIO_TYPE_MIC_ACTIVITY, json);
}

static void forget_session(tivoo_mic_producer_t *mic)
{
    mic->session_id[0] = '\0';
    mic->pending = 0;
    mic->preroll_pending = 0;
    mic->stopping = false;
    mic->sent_start = false;
}

bool tivoo_mic_stop(tivoo_mic_producer_t *mic, uint32_t generation, const char *session_id)
{
    if (!generation || mic->generation != generation || !mic->session_id[0] ||
        strcmp(mic->session_id, session_id) != 0) {
        return false;
    }
    if (!mic->sent_start || mic->stopping) {
        return false;
    }
    mic->pending = 0;
    mic->stopping = true;
    return true;
}

static void start_session(tivoo_mic_producer_t *mic, uint64_t uptime_ms)
{
    mic->new_id(mic->session_id);
    mic->start_ms = uptime_ms;
    mic->sent_start_activity = false;
    mic->reported_speech = true;
    mic->pending = mic->history_count;
    mic->preroll_pending = mic->pending;
}

static bool send_start(tivoo_mic_producer_t *mic)
{
    char json[224];
    snprintf(json, sizeof(json),
        "{\"session_id\":\"%s\",\"sample_rate\":16000,\"channels\":1,"
        "\"sample_format\":\"s16le\",\"frame_duration_ms\":20,"
        "\"preroll_ms\":%zu,\"trigger_source\":\"idle_vad\"}",
        mic->session_id, mic->preroll_pending * 20);
    return send_json(mic, TVIO_TYPE_MIC_SESSION_START, json);
}

static void upload(tivoo_mic_producer_t *mic)
{
    if (!mic->session_id[0]) {
        return;
    }
    if (mic->stopping) {
        char json[100];
        snprintf(json, sizeof(json), "{\"session_id\":\"%s\",\"reason\":\"capture_stopped\"}",
            mic->session_id);
        if (send_json(mic, TVIO_TYPE_MIC_SESSION_END, json)) {
            forget_session(mic);
            /* A server-side timeout can end the network session while VAD
             * still reports continuous speech (for example, TV dialogue).
             * Re-arm the local speech edge so the next speech frame can open
             * a fresh wake-word session without requiring intervening silence. */
            mic->speech = false;
        }
        return;
    }
    if (!mic->sent_start) {
        if (!send_start(mic)) {
            return;
        }
        mic->sent_start = true;
    }
    if (!mic->sent_start_activity) {
        if (!send_activity(mic, true, mic->start_ms)) {
            return;
        }
        mic->sent_start_activity = true;
    }
    while (mic->pending) {
        const size_t index = (mic->write + TIVOO_MIC_BUFFER_FRAMES - mic->pending)
            % TIVOO_MIC_BUFFER_FRAMES;
        const tivoo_mic_frame_t *frame = &mic->frames[index];
        if (!mic->preroll_pending && frame->speech != mic->reported_speech) {
            if (!send_activity(mic, frame->speech, frame->uptime_ms)) {
                return;
            }
            mic->reported_speech = frame->speech;
        }
        uint8_t payload[TIVOO_MIC_FRAME_SAMPLES * 2];
        for (size_t i = 0; i < TIVOO_MIC_FRAME_SAMPLES; ++i) {
            const uint16_t sample = (uint16_t)frame->samples[i];
            payload[2 * i] = (uint8_t)sample;
            payload[2 * i + 1] = (uint8_t)(sample >> 8);
        }
        if (!mic->send(mic->generation, TVIO_TYPE_MIC_PCM, payload, sizeof(payload))) {
            return;
        }
        mic->pending--;
        if (mic->preroll_pending) {
            mic->preroll_pending--;
        }
    }
}

void tivoo_mic_push(tivoo_mic_producer_t *mic, uint32_t generation, bool speech,
    uint64_t uptime_ms, const int16_t *samples, size_t count)
{
    if (mic->generation != generation) {
        forget_session(mic);
        mic->generation = generation;
    }
    if (speech != mic->speech) {
        mic->speech = speech;
        mic->activity_transitions++;
        if (speech && generation && !mic->session_id[0]) {
            start_session(mic, uptime_ms);
        }
    }

    while (count) {
        const size_t room = TIVOO_MIC_FRAME_SAMPLES - mic->partial_samples;
        const size_t copied = count < room ? count : room;
        memcpy(&mic->partial.samples[mic->partial_samples], samples, copied * sizeof(*samples));
        mic->partial_samples += copied;
        samples += copied;
        count -= copied;
        if (mic->partial_samples < TIVOO_MIC_FRAME_SAMPLES) {
            continue;
        }

        mic->partial_samples = 0;
        mic->partial.speech = speech;
        mic->partial.uptime_ms = uptime_ms;
        mic->frames[mic->write] = mic->partial;
        mic->write = (mic->write + 1) % TIVOO_MIC_BUFFER_FRAMES;
        if (mic->history_count < TIVOO_MIC_PREROLL_FRAMES) {
            mic->history_count++;
        }
        if (mic->session_id[0] && !mic->stopping) {
            if (mic->pending < TIVOO_MIC_BUFFER_FRAMES) {
                mic->pending++;
            } else {
                mic->dropped_frames++;
                if (mic->preroll_pending) {
                    mic->preroll_pending--;
                }
            }
        }
    }
    upload(mic);
}

void tivoo_mic_suppress(tivoo_mic_producer_t *mic, uint64_t uptime_ms)
{
    if (mic->speech) {
        mic->speech = false;
        mic->activity_transitions++;
    }
    if (mic->session_id[0] && mic->sent_start_activity && mic->reported_speech &&
        send_activity(mic, false, uptime_ms)) {
        mic->reported_speech = false;
    }
}

#ifdef ESP_PLATFORM
#include <stdatomic.h>

#include "audio_capture.h"
#include "esp_afe_sr_models.h"
#include "esp_attr.h"
#include "esp_heap_caps.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#define RX_READ_FRAMES 160U
#define TAG "audio_frontend"

static const esp_afe_sr_iface_t *s_afe;
static esp_afe_sr_data_t *s_afe_data;
static size_t s_feed_samples;
static int16_t *s_input;
static TaskHandle_t s_feed_task;
static TaskHandle_t s_fetch_task;
static tivoo_audio_reference_reader_t s_read_reference;
static EXT_RAM_BSS_ATTR tivoo_mic_producer_t s_mic;
static uint32_t s_raw[RX_READ_FRAMES * 2];
static atomic_uint s_read_errors;
static atomic_uint s_feed_errors;
static atomic_uint s_reference_underruns;
static atomic_uint s_reference_misalignments;
static atomic_uint s_mic_peak;
static atomic_uint s_right_peak;
static atomic_uint s_feed_max_us;
static atomic_bool s_vad_suppressed;
static portMUX_TYPE s_stop_lock = portMUX_INITIALIZER_UNLOCKED;
static char s_expected_id[37];
static bool s_stop_requested;

static void new_uuid(char out[37])
{
    uint8_t id[16];
    esp_fill_random(id, sizeof(id));
    id[6] = (id[6] & 0x0f) | 0x40;
    id[8] = (id[8] & 0x3f) | 0x80;
    snprintf(out, 37,
        "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
        id[0], id[1], id[2], id[3], id[4], id[5], id[6], id[7],
        id[8], id[9], id[10], id[11], id[12], id[13], id[14], id[15]);
    portENTER_CRITICAL(&s_stop_lock);
    memcpy(s_expected_id, out, sizeof(s_expected_id));
    s_stop_requested = false;
    portEXIT_CRITICAL(&s_stop_lock);
}

static void request_stop(const char *session_id, const char *reason)
{
    (void)reason;
    portENTER_CRITICAL(&s_stop_lock);
    if (strcmp(s_expected_id, session_id) == 0) {
        s_stop_requested = true;
    }
    portEXIT_CRITICAL(&s_stop_lock);
}

static void apply_stop(uint32_t generation)
{
    char session_id[37];
    portENTER_CRITICAL(&s_stop_lock);
    const bool requested = s_stop_requested;
    if (requested) {
        memcpy(session_id, s_expected_id, sizeof(session_id));
        s_stop_requested = false;
    }
    portEXIT_CRITICAL(&s_stop_lock);
    if (requested && tivoo_mic_stop(&s_mic, generation, session_id)) {
        TIVOO_LOGI(TAG, "MIC_CAPTURE_STOP accepted; RX/AFE stay active");
    }
}

static void feed_afe(uint64_t first_sample)
{
    /* The reader writes only the R slots and receives the processed RX index.
     * Its owner compensates for TX DMA latency before returning samples. */
    if (s_read_reference != NULL) {
        const tivoo_audio_reference_status_t status =
            s_read_reference(first_sample, s_input + 1, s_feed_samples);
        if (status == TIVOO_AUDIO_REFERENCE_UNDERRUN) {
            atomic_fetch_add(&s_reference_underruns, 1);
        } else if (status == TIVOO_AUDIO_REFERENCE_MISALIGNED) {
            atomic_fetch_add(&s_reference_misalignments, 1);
        }
        goto feed;
    }
    for (size_t i = 0; i < s_feed_samples; ++i) {
        s_input[2 * i + 1] = 0;
    }

feed:
    const int64_t started = esp_timer_get_time();
    if (s_afe->feed(s_afe_data, s_input) <= 0) {
        atomic_fetch_add(&s_feed_errors, 1);
    }
    const unsigned elapsed = esp_timer_get_time() - started;
    if (elapsed > atomic_load_explicit(&s_feed_max_us, memory_order_relaxed)) {
        atomic_store_explicit(&s_feed_max_us, elapsed, memory_order_relaxed);
    }
}

#ifdef CONFIG_TIVOO_AUDIO_PROBE
typedef struct {
    int64_t sum;
    uint64_t squares;
    uint32_t clipped;
} probe_level_t;

static void probe_add(probe_level_t *level, int32_t sample)
{
    level->sum += sample;
    level->squares += (uint32_t)(sample * sample);
    level->clipped += sample <= -32760 || sample >= 32760;
}

static void probe_report(const char *stage, const probe_level_t *level, unsigned n)
{
    const int32_t dc = (int32_t)(level->sum / n);
    const uint64_t mean_square = level->squares / n;
    const uint32_t ac_square = (uint32_t)(mean_square - (uint64_t)(dc * dc));
    ESP_LOGI(TAG, "PROBE %s n=%u dc=%" PRId32 " ac_ms=%" PRIu32 " clipped=%" PRIu32,
        stage, n, dc, ac_square, level->clipped);
}
#endif

static void capture_task(void *arg)
{
    (void)arg;
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    tivoo_decimator_t filter = {0};
    int16_t mic[RX_READ_FRAMES / 2];
    size_t filled = 0;
    uint64_t next_sample = 0;
    uint64_t first_sample = 0;
    uint32_t previous_overruns = 0;
    uint32_t previous_missed_eofs = 0;
#ifdef CONFIG_TIVOO_AUDIO_PROBE
    probe_level_t raw_left = {0}, raw_right = {0}, filtered = {0};
    unsigned raw_count = 0, filtered_count = 0;
#endif

    for (;;) {
        size_t bytes = 0;
        const esp_err_t err = tivoo_audio_capture_read(s_raw, sizeof(s_raw), &bytes);
        if (err != ESP_OK || bytes % (2 * sizeof(*s_raw)) != 0) {
            atomic_fetch_add(&s_read_errors, 1);
            if (!bytes || bytes % (2 * sizeof(*s_raw)) != 0) {
                vTaskDelay(1);
                continue;
            }
        }
        const uint32_t overruns = tivoo_audio_capture_overruns();
        const uint32_t missed_eofs = tivoo_audio_capture_missed_eofs();
        const uint32_t lost_blocks =
            (overruns - previous_overruns) + (missed_eofs - previous_missed_eofs);
        if (lost_blocks != 0) {
            next_sample += (uint64_t)lost_blocks * (RX_READ_FRAMES / 2U);
            previous_overruns = overruns;
            previous_missed_eofs = missed_eofs;
            filled = 0;
            filter = (tivoo_decimator_t){0};
            atomic_fetch_add(&s_reference_misalignments, 1);
        }
#ifdef CONFIG_TIVOO_AUDIO_PROBE
        for (size_t slot = 0; slot < bytes / sizeof(*s_raw); slot += 2) {
            probe_add(&raw_left, tivoo_inmp441_sample(s_raw[slot]) / 256);
            probe_add(&raw_right, tivoo_inmp441_sample(s_raw[slot + 1]) / 256);
            if (++raw_count == 32000) {
                probe_report("raw_left", &raw_left, raw_count);
                probe_report("raw_right", &raw_right, raw_count);
                raw_left = (probe_level_t){0};
                raw_right = (probe_level_t){0};
                raw_count = 0;
            }
        }
#endif
        unsigned right_peak = atomic_load_explicit(&s_right_peak, memory_order_relaxed);
        for (size_t slot = 1; slot < bytes / sizeof(*s_raw); slot += 2) {
            const int32_t pcm = tivoo_inmp441_sample(s_raw[slot]) / 256;
            const unsigned amplitude = pcm < 0 ? -pcm : pcm;
            if (amplitude > right_peak) {
                right_peak = amplitude;
            }
        }
        atomic_store_explicit(&s_right_peak, right_peak, memory_order_relaxed);
        const size_t samples = tivoo_audio_decimate(&filter, s_raw,
            bytes / (2 * sizeof(*s_raw)), mic);
        unsigned peak = atomic_load_explicit(&s_mic_peak, memory_order_relaxed);
        for (size_t i = 0; i < samples; ++i) {
#ifdef CONFIG_TIVOO_AUDIO_PROBE
            probe_add(&filtered, mic[i]);
            if (++filtered_count == 16000) {
                probe_report("filtered_left", &filtered, filtered_count);
                filtered = (probe_level_t){0};
                filtered_count = 0;
            }
#endif
            const unsigned amplitude = mic[i] < 0 ? -(int)mic[i] : mic[i];
            if (amplitude > peak) {
                peak = amplitude;
            }
            if (filled == 0) {
                first_sample = next_sample;
            }
            ++next_sample;
            s_input[2 * filled++] = mic[i];
            if (filled == s_feed_samples) {
                feed_afe(first_sample);
                filled = 0;
            }
        }
        atomic_store_explicit(&s_mic_peak, peak, memory_order_relaxed);
    }
}

static void fetch_task(void *arg)
{
    (void)arg;
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    uint32_t frames = 0;
    uint32_t fetch_errors = 0;
#ifdef CONFIG_TIVOO_AUDIO_PROBE
    probe_level_t enhanced = {0};
    unsigned enhanced_count = 0, speech_count = 0;
#endif
    uint64_t report_ms = esp_timer_get_time() / 1000;
    for (;;) {
        afe_fetch_result_t *result =
            s_afe->fetch_with_delay(s_afe_data, pdMS_TO_TICKS(250));
        const uint64_t now = esp_timer_get_time() / 1000;
        const uint32_t generation = tivoo_diagnostics_mic_generation();
        apply_stop(generation);
        if (result != NULL && result->ret_value == ESP_OK && result->data != NULL &&
            result->data_size > 0 && result->data_size % sizeof(int16_t) == 0) {
            if (atomic_load_explicit(&s_vad_suppressed, memory_order_acquire)) {
                const bool transition = s_mic.speech;
                tivoo_mic_suppress(&s_mic, now);
                ++frames;
                if (transition) {
                    TIVOO_LOGI(TAG, "VAD speech_end transitions=%" PRIu32
                        " upload=%u (prompt suppressed)",
                        s_mic.activity_transitions,
                        s_mic.session_id[0] && !s_mic.stopping);
                }
                continue;
            }
            const bool speech = result->vad_state == VAD_SPEECH;
#ifdef CONFIG_TIVOO_AUDIO_PROBE
            for (size_t i = 0; i < result->data_size / sizeof(int16_t); ++i) {
                probe_add(&enhanced, result->data[i]);
                speech_count += speech;
                if (++enhanced_count == 16000) {
                    probe_report("enhanced", &enhanced, enhanced_count);
                    ESP_LOGI(TAG, "PROBE vad speech_samples=%u/16000", speech_count);
                    enhanced = (probe_level_t){0};
                    enhanced_count = 0;
                    speech_count = 0;
                }
            }
#endif
            const bool transition = speech != s_mic.speech;
            /* Every successful fetch enters the history, including silence.
             * vad_cache overlaps that history and would duplicate samples. */
            tivoo_mic_push(&s_mic, generation, speech, now,
                result->data, result->data_size / sizeof(int16_t));
            ++frames;
            if (transition) {
                TIVOO_LOGI(TAG, "VAD %s transitions=%" PRIu32 " upload=%u",
                    speech ? "speech_start" : "speech_end", s_mic.activity_transitions,
                    s_mic.session_id[0] && !s_mic.stopping);
            }
        } else {
            fetch_errors++;
            tivoo_mic_push(&s_mic, generation, s_mic.speech, now, NULL, 0);
            vTaskDelay(1);
        }

        if (now - report_ms >= 10000) {
            report_ms = now;
            TIVOO_LOGI(TAG,
                "AFE frames=%" PRIu32 " fetch_errors=%" PRIu32 " feed_errors=%u "
                "RX errors=%u overruns=%" PRIu32 " missed_eofs=%" PRIu32
                " mic_peak=%u right_peak=%u feed_max_us=%u "
                "ref_underruns=%u ref_misaligned=%u PCM drops=%" PRIu32
                " pending=%zu stack_min=%u/%u vad=%s",
                frames, fetch_errors, atomic_load(&s_feed_errors),
                atomic_load(&s_read_errors), tivoo_audio_capture_overruns(),
                tivoo_audio_capture_missed_eofs(),
                atomic_exchange(&s_mic_peak, 0), atomic_exchange(&s_right_peak, 0),
                atomic_exchange(&s_feed_max_us, 0),
                atomic_load(&s_reference_underruns), atomic_load(&s_reference_misalignments),
                s_mic.dropped_frames, s_mic.pending,
                (unsigned)uxTaskGetStackHighWaterMark(s_feed_task),
                (unsigned)uxTaskGetStackHighWaterMark(NULL),
                s_mic.speech ? "speech" : "silence");
        }
    }
}

void tivoo_audio_frontend_set_vad_suppressed(bool suppressed)
{
    if (s_afe == NULL || s_afe_data == NULL) {
        return;
    }

    if (suppressed) {
        atomic_store_explicit(&s_vad_suppressed, true, memory_order_release);
        const int disable_result = s_afe->disable_vad(s_afe_data);
        const int reset_result = s_afe->reset_vad(s_afe_data);
        TIVOO_LOGI(TAG, "Prompt VAD suppression on disable=%d reset=%d",
            disable_result, reset_result);
        return;
    }

    const int enable_result = s_afe->enable_vad(s_afe_data);
    const int reset_result = s_afe->reset_vad(s_afe_data);
    atomic_store_explicit(&s_vad_suppressed, false, memory_order_release);
    TIVOO_LOGI(TAG, "Prompt VAD suppression off enable=%d reset=%d",
        enable_result, reset_result);
}

esp_err_t tivoo_audio_frontend_start(tivoo_audio_reference_reader_t read_reference)
{
    afe_config_t *config = afe_config_init("MR", NULL, AFE_TYPE_SR, AFE_MODE_HIGH_PERF);
    if (config == NULL) {
        return ESP_ERR_NO_MEM;
    }
    config->aec_init = true;
    config->aec_mode = AEC_MODE_SR_HIGH_PERF;
    /* Two 32 ms AEC blocks keep classic ESP32 within the DMA budget. */
    config->aec_filter_length = 2;
    config->vad_init = true;
    config->vad_mute_playback = false;
    config->wakenet_init = false;
    config->memory_alloc_mode = AFE_MEMORY_ALLOC_INTERNAL_PSRAM_BALANCE;
    config->afe_perferred_core = 1;
    config->afe_perferred_priority = 6;
    s_afe = esp_afe_handle_from_config(config);
    s_afe_data = s_afe == NULL ? NULL : s_afe->create_from_config(config);
    afe_config_free(config);
    if (s_afe_data == NULL) {
        return ESP_FAIL;
    }

    const int feed_samples = s_afe->get_feed_chunksize(s_afe_data);
    esp_err_t err = ESP_ERR_INVALID_STATE;
    if (feed_samples <= 0 || s_afe->get_feed_channel_num(s_afe_data) != 2 ||
        s_afe->get_fetch_channel_num(s_afe_data) != 1 ||
        s_afe->get_samp_rate(s_afe_data) != 16000) {
        goto fail;
    }
    s_feed_samples = (size_t)feed_samples;
    s_input = heap_caps_calloc(s_feed_samples * 2, sizeof(*s_input),
        MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (s_input == NULL) {
        err = ESP_ERR_NO_MEM;
        goto fail;
    }

    err = tivoo_audio_capture_start();
    if (err != ESP_OK) {
        goto fail;
    }
    if (xTaskCreatePinnedToCore(capture_task, "mic_feed", 4096, NULL, 7, &s_feed_task, 1)
            != pdPASS ||
        xTaskCreatePinnedToCore(fetch_task, "mic_fetch", 4096, NULL, 5, &s_fetch_task, 1)
            != pdPASS) {
        err = ESP_ERR_NO_MEM;
        goto fail;
    }

    s_read_reference = read_reference;
    s_mic.send = tivoo_diagnostics_send_mic;
    s_mic.new_id = new_uuid;
    tivoo_diagnostics_set_mic_capture_stop_handler(request_stop);
    tivoo_diagnostics_enable_mic_activity();
    TIVOO_LOGI(TAG, "I2S 32k stereo / AFE MR 16k feed=%d fetch=%d, continuous RX",
        feed_samples, s_afe->get_fetch_chunksize(s_afe_data));
    xTaskNotifyGive(s_feed_task);
    xTaskNotifyGive(s_fetch_task);
    return ESP_OK;

fail:
    if (s_feed_task != NULL) {
        vTaskDelete(s_feed_task);
    }
    tivoo_audio_capture_close();
    heap_caps_free(s_input);
    s_afe->destroy(s_afe_data);
    return err;
}
#endif
