#include "audio_resource.h"

#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "cJSON.h"

#ifdef ESP_PLATFORM
#include "esp_heap_caps.h"
#include "esp_http_client.h"
#endif

#define PLAYBACK_ID_MAX 64U
#define URL_MAX 2048U
#define MIME_MAX 96U
#define REASON_MAX 64U

typedef struct {
    char playback_id[PLAYBACK_ID_MAX + 1U];
    char session_id[37];
    char url[URL_MAX + 1U];
    char mime_type[MIME_MAX + 1U];
    bool suppress_vad;
    atomic_bool stop_requested;
    uint64_t bytes_received;
    char response_mime[MIME_MAX + 1U];
#ifdef ESP_PLATFORM
    int socket_fd;
    uint32_t generation;
    uint32_t peer_generation;
    bool terminal;
#endif
} audio_request_t;

typedef struct {
    char request_id[37];
    char session_id[37];
    char expected_audio_id[37];
    char reason[REASON_MAX + 1U];
} audio_stop_payload_t;

static bool is_ascii_hex(char value)
{
    return (value >= '0' && value <= '9') ||
           (value >= 'a' && value <= 'f') ||
           (value >= 'A' && value <= 'F');
}

static bool is_ascii_space(char value)
{
    return value == ' ' || value == '\t' || value == '\r' ||
           value == '\n' || value == '\v' || value == '\f';
}

static bool is_uuid(const char *value)
{
    if (value == NULL || strlen(value) != 36U) {
        return false;
    }
    for (size_t i = 0U; i < 36U; i++) {
        if (i == 8U || i == 13U || i == 18U || i == 23U) {
            if (value[i] != '-') {
                return false;
            }
        } else if (!is_ascii_hex(value[i])) {
            return false;
        }
    }
    return true;
}

static bool is_http_url(const char *url)
{
    if (url == NULL || url[0] == '\0' || strlen(url) > URL_MAX ||
        strchr(url, '\r') != NULL || strchr(url, '\n') != NULL ||
        strchr(url, ' ') != NULL) {
        return false;
    }

    size_t scheme_length = 0U;
    if (strncasecmp(url, "http://", 7U) == 0) {
        scheme_length = 7U;
    } else if (strncasecmp(url, "https://", 8U) == 0) {
        scheme_length = 8U;
    } else {
        return false;
    }

    const char *authority_end = strpbrk(url + scheme_length, "/?#");
    const size_t authority_length = authority_end == NULL
        ? strlen(url + scheme_length)
        : (size_t)(authority_end - (url + scheme_length));
    return authority_length > 0U;
}

static bool valid_mime(const char *mime)
{
    if (mime == NULL || strncasecmp(mime, "audio/", 6U) != 0 ||
        strlen(mime) > MIME_MAX || strchr(mime, '\r') != NULL ||
        strchr(mime, '\n') != NULL) {
        return false;
    }
    const size_t type_length = strcspn(mime, "; \t");
    return type_length > 6U && strchr(mime + 6U, '/') == NULL;
}

static bool media_type_equal(const char *actual, const char *expected)
{
    if (actual == NULL || expected == NULL) {
        return false;
    }

    while (is_ascii_space(*actual)) {
        actual++;
    }
    while (is_ascii_space(*expected)) {
        expected++;
    }

    const size_t actual_length = strcspn(actual, "; \t");
    const size_t expected_length = strcspn(expected, "; \t");
    return actual_length > 0U && actual_length == expected_length &&
           strncasecmp(actual, expected, actual_length) == 0;
}

static audio_request_t *create_request(
    const char *playback_id, const char *url, const char *mime_type)
{
    if (!is_uuid(playback_id) || !is_http_url(url) || !valid_mime(mime_type)) {
        return NULL;
    }

    audio_request_t *request = calloc(1U, sizeof(*request));
    if (request == NULL) {
        return NULL;
    }
    (void)snprintf(
        request->playback_id, sizeof(request->playback_id), "%s", playback_id);
    (void)snprintf(request->url, sizeof(request->url), "%s", url);
    (void)snprintf(request->mime_type, sizeof(request->mime_type), "%s", mime_type);
    atomic_init(&request->stop_requested, false);
#ifdef ESP_PLATFORM
    request->socket_fd = -1;
#endif
    return request;
}

static bool parse_tts_play(
    const uint8_t *payload,
    size_t size,
    audio_request_t **request_out)
{
    if (request_out == NULL) {
        return false;
    }
    *request_out = NULL;

    cJSON *root = payload == NULL || size == 0U
        ? NULL
        : cJSON_ParseWithLength((const char *)payload, size);
    const cJSON *id_item = cJSON_IsObject(root)
        ? cJSON_GetObjectItemCaseSensitive(root, "playback_id")
        : NULL;
    const cJSON *url_item = cJSON_IsObject(root)
        ? cJSON_GetObjectItemCaseSensitive(root, "url")
        : NULL;
    const cJSON *mime_item = cJSON_IsObject(root)
        ? cJSON_GetObjectItemCaseSensitive(root, "mime_type")
        : NULL;
    const cJSON *suppress_vad_item = cJSON_IsObject(root)
        ? cJSON_GetObjectItemCaseSensitive(root, "suppress_vad")
        : NULL;
    const char *playback_id = cJSON_IsString(id_item)
        ? cJSON_GetStringValue(id_item)
        : NULL;
    const char *url = cJSON_IsString(url_item)
        ? cJSON_GetStringValue(url_item)
        : NULL;
    const char *mime_type = cJSON_IsString(mime_item)
        ? cJSON_GetStringValue(mime_item)
        : NULL;

    const cJSON *session_item = cJSON_GetObjectItemCaseSensitive(root,"session_id");
    const char *session_id = cJSON_GetStringValue(session_item);
#ifdef TIVOO_P68_B5_LOCAL
    if (!is_uuid(session_id) || cJSON_IsTrue(suppress_vad_item)) {
        cJSON_Delete(root);
        return false;
    }
#endif
    if (session_item && !is_uuid(session_id)) {
        cJSON_Delete(root);
        return false;
    }
    const bool suppress_vad_present = suppress_vad_item != NULL;
    if (suppress_vad_present && !cJSON_IsBool(suppress_vad_item)) {
        cJSON_Delete(root);
        return false;
    }

    *request_out = create_request(playback_id, url, mime_type);
    if (*request_out != NULL && suppress_vad_present) {
        (*request_out)->suppress_vad = cJSON_IsTrue(suppress_vad_item);
    }
    if (*request_out && session_id) memcpy((*request_out)->session_id,session_id,37);
    cJSON_Delete(root);
    return *request_out != NULL;
}

static bool parse_audio_stop(
    const uint8_t *payload, size_t size, audio_stop_payload_t *stop)
{
    if (stop == NULL) {
        return false;
    }
    memset(stop, 0, sizeof(*stop));

    cJSON *root = payload == NULL || size == 0U
        ? NULL
        : cJSON_ParseWithLength((const char *)payload, size);
    const cJSON *request_id_item = cJSON_IsObject(root)
        ? cJSON_GetObjectItemCaseSensitive(root, "request_id")
        : NULL;
    const cJSON *expected_item = cJSON_IsObject(root)
        ? cJSON_GetObjectItemCaseSensitive(root, "expected_audio_id")
        : NULL;
    const cJSON *reason_item = cJSON_IsObject(root)
        ? cJSON_GetObjectItemCaseSensitive(root, "reason")
        : NULL;
    const char *request_id = cJSON_IsString(request_id_item)
        ? cJSON_GetStringValue(request_id_item)
        : NULL;
    const char *expected_id = cJSON_IsString(expected_item)
        ? cJSON_GetStringValue(expected_item)
        : NULL;
    const char *reason = cJSON_IsString(reason_item)
        ? cJSON_GetStringValue(reason_item)
        : NULL;

    const cJSON *session_item=cJSON_GetObjectItemCaseSensitive(root,"session_id");
    const char *session_id=cJSON_GetStringValue(session_item);
    const bool valid = is_uuid(request_id) &&
#ifdef TIVOO_P68_B5_LOCAL
        is_uuid(session_id) && is_uuid(expected_id) &&
#endif
        (!session_item || is_uuid(session_id)) &&
        (expected_item == NULL || is_uuid(expected_id)) &&
        reason != NULL && reason[0] != '\0' && strlen(reason) <= REASON_MAX;
    if (valid) {
        if(session_id) memcpy(stop->session_id,session_id,37);
        (void)snprintf(stop->request_id, sizeof(stop->request_id), "%s", request_id);
        if (expected_id != NULL) {
            (void)snprintf(
                stop->expected_audio_id, sizeof(stop->expected_audio_id),
                "%s", expected_id);
        }
        (void)snprintf(stop->reason, sizeof(stop->reason), "%s", reason);
    }
    cJSON_Delete(root);
    return valid;
}

#ifdef ESP_PLATFORM

#include "audio_output_manager.h"
#include "audio_playback.h"
#include "audio_frontend.h"
#include "device_status.h"
#include "diagnostics.h"
#include "esp_crt_bundle.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "lwip/sockets.h"
#include "sdkconfig.h"
#ifdef TIVOO_P68_B5_LOCAL
#include "s3_local_turn.h"
#endif

#define TAG "audio_resource"
#define TYPE_TTS_PLAY 0x30U
#define TYPE_AUDIO_STOP 0x31U
#define TYPE_AUDIO_STATE 0x32U
#define HTTP_BUFFER_SIZE 1024
#define HTTP_CONNECT_TIMEOUT_MS 1500
#define HTTP_TIMEOUT_MS 8000
#define AUDIO_TASK_STACK 7168U
#define ID_HISTORY 16U
#define DMA_DRAIN_TIMEOUT_US 350000

static SemaphoreHandle_t s_mutex;
static atomic_bool s_output_claimed;

bool tivoo_audio_resource_test_silent(void)
{
    return s_mutex != NULL && !atomic_load(&s_output_claimed)
#ifdef TIVOO_P68_B5_LOCAL
        && tivoo_audio_output_available()
#endif
        ;
}

static esp_err_t stop_request(const char *request_id, const char *expected_audio_id, const char *reason, const char *session_id);
static audio_request_t *s_active_request;
static audio_request_t *s_pending_request;
static uint32_t s_generation;
#ifdef TIVOO_P68_B5_LOCAL
static uint32_t s_prompt_generation;
static uint64_t s_last_drain;

/* A successful restart has a new digital clock boundary, not a completed
 * old generation. Require the same calibrated tail for the next prompt. */
bool tivoo_audio_resource_prompt_ready(unsigned acoustic_tail)
{
    if (!s_mutex || xSemaphoreTake(s_mutex,0)!=pdTRUE) return false;
    uint64_t end=0, clock=0;
    (void)tivoo_audio_output_prompt_drain(0,&end,&clock);
    uint64_t boundary=tivoo_audio_output_recovery_boundary();
    if (s_last_drain>boundary) boundary=s_last_drain;
    const bool ready=tivoo_audio_output_available() &&
        !s_active_request && !s_pending_request && !s_prompt_generation &&
        clock>=boundary+acoustic_tail;
    xSemaphoreGive(s_mutex);
    return ready;
}

void tivoo_audio_resource_retire_local(const char *session_id, uint32_t epoch)
{
    if(!s_mutex || !session_id || !epoch) return;
    (void)xSemaphoreTake(s_mutex,portMAX_DELAY);
    audio_request_t *requests[]={s_active_request,s_pending_request};
    for (unsigned i=0;i<2;++i) {
        audio_request_t *request=requests[i];
        if(request && request->peer_generation==epoch && strcmp(request->session_id,session_id)==0 &&
           !request->terminal && !atomic_exchange(&request->stop_requested,true)) {
            tivoo_audio_output_stop(request->generation);
            if(request->socket_fd>=0) (void)shutdown(request->socket_fd,SHUT_RDWR);
        }
    }
    xSemaphoreGive(s_mutex);
}

uint32_t tivoo_audio_resource_prompt_begin(void)
{
    if (!s_mutex || xSemaphoreTake(s_mutex,0)!=pdTRUE) return 0;
    uint32_t generation=0;
    if (!s_active_request && !s_pending_request && !s_prompt_generation) {
        if (++s_generation==0) ++s_generation;
        if (tivoo_audio_output_begin_prompt(s_generation)) {
            generation=s_prompt_generation=s_generation;
            atomic_store(&s_output_claimed,true);
        }
    }
    xSemaphoreGive(s_mutex);
    return generation;
}

bool tivoo_audio_resource_prompt_end(uint32_t generation)
{
    if (!s_mutex || xSemaphoreTake(s_mutex,0)!=pdTRUE) return false;
    uint64_t end=0;
    const bool valid=generation && generation==s_prompt_generation &&
        tivoo_audio_output_release_drained(generation,&end);
    if (valid) {
        s_prompt_generation=0;
        atomic_store(&s_output_claimed,false);
    }
    xSemaphoreGive(s_mutex);
    return valid;
}
/* Faulted owner releases only its logical claim. The manager remains
 * unavailable until both hardware channels have been rebuilt. */
bool tivoo_audio_resource_prompt_discard(uint32_t generation)
{
    if (!s_mutex || xSemaphoreTake(s_mutex,0)!=pdTRUE) return false;
    bool valid=generation && generation==s_prompt_generation &&
        tivoo_audio_output_failed(generation);
    if (valid) {
        tivoo_audio_output_end(generation);
        s_prompt_generation=0;
        atomic_store(&s_output_claimed,false);
    }
    xSemaphoreGive(s_mutex);
    return valid;
}
#endif
static char s_recent_playbacks[ID_HISTORY][37];
static size_t s_next_playback;
static char s_recent_stops[ID_HISTORY][37];
static size_t s_next_stop;

static bool seen_id(char history[ID_HISTORY][37], const char *id)
{
    for (size_t i = 0; i < ID_HISTORY; ++i) {
        if (strcmp(history[i], id) == 0) {
            return true;
        }
    }
    return false;
}

static void remember_id(char history[ID_HISTORY][37], size_t *next, const char *id)
{
    memcpy(history[*next], id, 37);
    *next = (*next + 1) % ID_HISTORY;
}

static void send_audio_state(
    const audio_request_t *request, const char *state, const char *error_code,
    bool retry)
{
    cJSON *root = cJSON_CreateObject();
    bool queued = false;
    char *payload = NULL;
    if (root && cJSON_AddStringToObject(root, "audio_id", request->playback_id) &&
        (!request->session_id[0] || cJSON_AddStringToObject(root, "session_id", request->session_id)) &&
        cJSON_AddStringToObject(root, "source", "tts_http") &&
        cJSON_AddStringToObject(root, "state", state) &&
        cJSON_AddNumberToObject(root, "bytes_received", (double)request->bytes_received) &&
        (!error_code || cJSON_AddStringToObject(root, "error_code", error_code))) {
        payload = cJSON_PrintUnformatted(root);
    }
    cJSON_Delete(root);
    if (payload != NULL) {
        const size_t size = strlen(payload);
        const int64_t deadline = esp_timer_get_time() + 250000;
        while (request->peer_generation != 0 &&
               request->peer_generation == tivoo_diagnostics_mic_generation()) {
            if (tivoo_diagnostics_send_mic(request->peer_generation, TYPE_AUDIO_STATE, payload, size)) {
                queued = true;
                break;
            }
            if (!retry || esp_timer_get_time() >= deadline) {
                break;
            }
            vTaskDelay(1);
        }
        cJSON_free(payload);
    }
    if (!queued) {
        ESP_LOGW(TAG, "Playback state %s could not be queued", state);
#ifdef TIVOO_P68_B5_LOCAL
        /* Losing a terminal leaves HA waiting indefinitely. Retire the
         * matching diagnostics epoch so both sides use existing teardown.
         * Intermediate states remain best effort. */
        if (strcmp(state, "buffering") && strcmp(state, "playing")) {
            tivoo_diagnostics_invalidate_mic(request->peer_generation);
        }
#endif
    }
    ESP_LOGI(TAG, "playback=%s state=%s error=%s", request->playback_id,
        state, error_code != NULL ? error_code : "-");
}

static esp_err_t http_event_handler(esp_http_client_event_t *event)
{
    audio_request_t *request = event->user_data;
    if (event->event_id == HTTP_EVENT_ON_HEADER && event->header_key != NULL &&
        event->header_value != NULL && strcasecmp(event->header_key, "Content-Type") == 0) {
        const size_t length = strlen(event->header_value);
        if (length <= MIME_MAX) {
            memcpy(request->response_mime, event->header_value, length + 1U);
        } else {
            request->response_mime[0] = '\0';
        }
    }
    return ESP_OK;
}

static const char *read_audio(
    audio_request_t *request, esp_http_client_handle_t client, bool *vad_suppressed)
{
    if (esp_http_client_open(client, 0) != ESP_OK) {
        return "audio_http_failed";
    }
    (void)xSemaphoreTake(s_mutex, portMAX_DELAY);
    request->socket_fd = esp_http_client_get_socket(client);
    const bool stopped = atomic_load(&request->stop_requested);
    (void)xSemaphoreGive(s_mutex);
    if (stopped) {
        return NULL;
    }
    (void)esp_http_client_set_timeout_ms(client, HTTP_TIMEOUT_MS);
    if (esp_http_client_fetch_headers(client) < 0 && !esp_http_client_is_chunked_response(client)) {
        return "audio_http_failed";
    }
    const int status = esp_http_client_get_status_code(client);
    if (status < 200 || status >= 300) {
        return "audio_http_status";
    }
    if (!media_type_equal(request->response_mime, request->mime_type)) {
        return "audio_content_type_mismatch";
    }

    const bool raw_pcm = media_type_equal(request->mime_type, TIVOO_PCM_MIME);
    const char *format_error = raw_pcm ? "audio_pcm_invalid" : "audio_decode_failed";
    tivoo_audio_playback_t *playback = tivoo_audio_playback_open(request->generation, raw_pcm);
    if (playback == NULL) {
        return format_error;
    }

    const char *error = NULL;
    bool started = false;
    uint8_t buffer[HTTP_BUFFER_SIZE];
    int64_t read_us = 0;
    int64_t max_read_us = 0;
    while (!atomic_load(&request->stop_requested)) {
        const int64_t read_start = esp_timer_get_time();
        const int bytes = esp_http_client_read(client, (char *)buffer, sizeof(buffer));
        const int64_t elapsed = esp_timer_get_time() - read_start;
        read_us += elapsed;
        if (elapsed > max_read_us) {
            max_read_us = elapsed;
        }
        if (bytes == -ESP_ERR_HTTP_EAGAIN) {
            // Keep the stream and decoder open while I2S fills the gap with silence.
            continue;
        }
        if (bytes < 0) {
            error = "audio_http_failed";
            break;
        }
        const bool eof = esp_http_client_is_complete_data_received(client);
        if (bytes == 0 && !eof) {
            error = "audio_http_failed";
            break;
        }
#ifndef TIVOO_P68_B3_AUDIO
        if (bytes > 0 && request->suppress_vad && !*vad_suppressed) {
            tivoo_audio_frontend_set_vad_suppressed(true);
            *vad_suppressed = true;
        }
#else
        (void)vad_suppressed; /* b6 adds local prompt gate, b3 has no VAD. */
#endif
        request->bytes_received += bytes;
        if (tivoo_audio_playback_feed(playback, buffer, (size_t)bytes, eof) != ESP_OK) {
            error = format_error;
            break;
        }
        if (!started && tivoo_audio_playback_has_pcm(playback)) {
            started = true;
            const uint32_t caps = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
            ESP_LOGI(TAG, "generation=%lu internal_free=%zu largest=%zu",
                (unsigned long)request->generation, heap_caps_get_free_size(caps),
                heap_caps_get_largest_free_block(caps));
            send_audio_state(request, "playing", NULL, true);
        }
        if (eof && bytes < sizeof(buffer)) {
            if (!started) {
                error = format_error;
            }
            break;
        }
    }
    if (error == NULL) {
        tivoo_audio_output_finish_input(request->generation);
    }
    ESP_LOGI(TAG, "generation=%lu HTTP read_ms=%ld max_read_ms=%ld",
        (unsigned long)request->generation, (long)(read_us / 1000), (long)(max_read_us / 1000));
    tivoo_audio_playback_close(playback);
    return error;
}

static const char *stream_audio(audio_request_t *request, bool *vad_suppressed)
{
    const esp_http_client_config_t config = {
        .url = request->url,
        .method = HTTP_METHOD_GET,
        .timeout_ms = HTTP_CONNECT_TIMEOUT_MS,
        .buffer_size = HTTP_BUFFER_SIZE,
        .buffer_size_tx = HTTP_BUFFER_SIZE,
        .event_handler = http_event_handler,
        .user_data = request,
        .disable_auto_redirect = true,
        .crt_bundle_attach = esp_crt_bundle_attach,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == NULL) {
        return "audio_http_failed";
    }
    const char *error = read_audio(request, client, vad_suppressed);
    (void)xSemaphoreTake(s_mutex, portMAX_DELAY);
    request->socket_fd = -1;
    (void)xSemaphoreGive(s_mutex);
    (void)esp_http_client_cleanup(client);
    return error;
}

static audio_request_t *run_request(audio_request_t *request)
{
    /* A pending request from a retired peer must not claim output or
     * publish a fetching snapshot on a replacement diagnostic connection. */
#ifdef TIVOO_P68_B5_LOCAL
    const bool announce = request->peer_generation != 0 &&
        request->peer_generation == tivoo_diagnostics_mic_generation();
#else
    const bool announce = true;
#endif
    if (announce) {
        (void)tivoo_device_status_set_audio_resource(true, request->playback_id);
        send_audio_state(request, "buffering", NULL, true);
    }

    const char *error = NULL;
    bool output = false;
    bool vad_suppressed = false;
    (void)xSemaphoreTake(s_mutex, portMAX_DELAY);
#ifdef TIVOO_P68_B5_LOCAL
    if (!request->peer_generation ||
        request->peer_generation != tivoo_diagnostics_mic_generation()) {
        atomic_store(&request->stop_requested, true);
    }
#endif
    if (!atomic_load(&request->stop_requested)) {
        if (!media_type_equal(request->mime_type, "audio/mpeg") &&
            !media_type_equal(request->mime_type, TIVOO_PCM_MIME)) {
            error = "audio_format_unsupported";
        } else if (!tivoo_audio_output_begin(request->generation)) {
            error = "audio_output_unavailable";
        } else {
            output = true;
        }
    }
    (void)xSemaphoreGive(s_mutex);
    if (output) {
        if (!atomic_load(&request->stop_requested)) {
            error = stream_audio(request, &vad_suppressed);
        }
        if (error != NULL) {
            tivoo_audio_output_stop(request->generation);
        }
        const int64_t deadline = esp_timer_get_time() + DMA_DRAIN_TIMEOUT_US;
        while (!tivoo_audio_output_drained(request->generation)) {
#ifdef TIVOO_P68_B5_LOCAL
            if (tivoo_audio_output_failed(request->generation)) {
                error="audio_dma_fault";
                break;
            }
#endif
            if (esp_timer_get_time() >= deadline) {
                tivoo_audio_output_stop(request->generation);
                error = "audio_output_timeout";
                break;
            }
            vTaskDelay(1);
        }
#ifdef TIVOO_P68_B5_LOCAL
        uint64_t end;
        (void)xSemaphoreTake(s_mutex,portMAX_DELAY);
        if (tivoo_audio_output_release_drained(request->generation,&end)) {
            s_last_drain=end;
        } else {
            /* The ordinary TTS and prompt timeout use the same recovery.
             * Never turn this discard into an ordinary completed terminal. */
            if (!tivoo_audio_output_failed(request->generation))
                tivoo_audio_output_request_recovery();
            tivoo_audio_output_end(request->generation);
            error="audio_dma_fault";
        }
        xSemaphoreGive(s_mutex);
#else
        tivoo_audio_output_end(request->generation);
#endif
    }
#ifndef TIVOO_P68_B3_AUDIO
    if (vad_suppressed) {
        /* output_end() is digital completion. Keep the prompt-only gate until
         * the final acoustic copy reaches INMP441, using the measured TX->mic
         * reference delay (760 samples = 47.5 ms in production). */
        const TickType_t acoustic_tail_ticks = pdMS_TO_TICKS(
            (CONFIG_TIVOO_AEC_REFERENCE_DELAY_SAMPLES + 15) / 16);
        if (acoustic_tail_ticks > 0) {
            vTaskDelay(acoustic_tail_ticks);
        }
        tivoo_audio_frontend_set_vad_suppressed(false);
    }
#endif
    if (announce) {
        (void)tivoo_device_status_set_audio_resource(false, NULL);
    }
    (void)xSemaphoreTake(s_mutex, portMAX_DELAY);
    const bool stopped = atomic_load(&request->stop_requested);
    request->terminal = true;
#ifndef TIVOO_P68_B5_LOCAL
    (void)xSemaphoreGive(s_mutex);
    send_audio_state(request, stopped ? "stopped" : error != NULL ? "failed" : "completed",
        stopped ? NULL : error, true);
    (void)xSemaphoreTake(s_mutex, portMAX_DELAY);
#endif
    remember_id(s_recent_playbacks, &s_next_playback, request->playback_id);
    audio_request_t *next = s_pending_request;
    s_active_request = next;
    s_pending_request = NULL;
#ifdef TIVOO_P68_B5_LOCAL
    atomic_store(&s_output_claimed,next!=NULL);
    tivoo_s3_local_turn_playback_finished(request->session_id,request->playback_id,
        request->peer_generation,!stopped && !error);
#else
    atomic_store(&s_output_claimed,next!=NULL);
#endif
    (void)xSemaphoreGive(s_mutex);
#ifdef TIVOO_P68_B5_LOCAL
    /* completed must mean the ordinary output owner is already released. */
    send_audio_state(request, stopped ? "stopped" : error != NULL ? "failed" : "completed",
        stopped ? NULL : error, true);
#endif
    return next;
}

static void audio_resource_task(void *context)
{
    audio_request_t *request = context;
    while (request != NULL) {
        audio_request_t *next = run_request(request);
        free(request);
        request = next;
    }
    vTaskDelete(NULL);
}

static esp_err_t start_request(audio_request_t *request)
{
    (void)xSemaphoreTake(s_mutex, portMAX_DELAY);
    request->peer_generation = tivoo_diagnostics_mic_generation();
#ifdef TIVOO_P68_B5_LOCAL
    if (s_prompt_generation || !tivoo_audio_output_available() || !tivoo_s3_local_turn_bind_playback(request->session_id,request->playback_id)) {
        (void)xSemaphoreGive(s_mutex);
        free(request);
        return ESP_ERR_INVALID_STATE;
    }
#endif
    audio_request_t *active = s_active_request;
    audio_request_t *pending = s_pending_request;
    if (seen_id(s_recent_playbacks, request->playback_id) ||
        (active != NULL && strcmp(active->playback_id, request->playback_id) == 0) ||
        (pending != NULL && strcmp(pending->playback_id, request->playback_id) == 0)) {
        (void)xSemaphoreGive(s_mutex);
        free(request);
        return ESP_OK;
    }
    if (pending != NULL || (active != NULL && !active->terminal && !atomic_load(&active->stop_requested))) {
        send_audio_state(request, "failed", "audio_busy", false);
        remember_id(s_recent_playbacks, &s_next_playback, request->playback_id);
        (void)xSemaphoreGive(s_mutex);
        free(request);
        return ESP_ERR_INVALID_STATE;
    }

    if (++s_generation == 0) {
        ++s_generation;
    }
    request->generation = s_generation;
    atomic_store(&s_output_claimed,true);
    if (active != NULL) {
        s_pending_request = request;
        (void)xSemaphoreGive(s_mutex);
        return ESP_OK;
    }

    s_active_request = request;
    // Keep MP3/SRC off the core that owns the time-sensitive microphone AFE.
    if (xTaskCreatePinnedToCore(audio_resource_task, "tivoo_audio", AUDIO_TASK_STACK,
            request, tskIDLE_PRIORITY + 3, NULL, 0) != pdPASS) {
        s_active_request = NULL;
        atomic_store(&s_output_claimed,false);
        send_audio_state(request, "failed", "audio_task_failed", false);
        remember_id(s_recent_playbacks, &s_next_playback, request->playback_id);
        (void)xSemaphoreGive(s_mutex);
        free(request);
        return ESP_ERR_NO_MEM;
    }
    (void)xSemaphoreGive(s_mutex);
    return ESP_OK;
}

static void handle_tts_play(const uint8_t *payload, size_t size)
{
    audio_request_t *request = NULL;
    if (!parse_tts_play(payload, size, &request)) {
        tivoo_report_error(
            "protocol_invalid_payload", TAG, "Invalid TTS_PLAY payload");
        return;
    }
    (void)start_request(request);
}

static void handle_audio_stop(const uint8_t *payload, size_t size)
{
    audio_stop_payload_t stop = {0};
    if (!parse_audio_stop(payload, size, &stop)) {
        tivoo_report_error(
            "protocol_invalid_payload", TAG, "Invalid AUDIO_STOP payload");
        return;
    }
    (void)stop_request(
        stop.request_id,
        stop.expected_audio_id[0] == '\0' ? NULL : stop.expected_audio_id,
        stop.reason,stop.session_id[0] ? stop.session_id : NULL);
}

esp_err_t tivoo_audio_resource_init(void)
{
    if (s_mutex != NULL) {
        return ESP_OK;
    }
    const esp_err_t err = tivoo_audio_playback_init();
    if (err != ESP_OK) {
        return err;
    }
    s_mutex = xSemaphoreCreateMutex();
    if (s_mutex == NULL) {
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

esp_err_t tivoo_audio_resource_start(
    const char *playback_id, const char *url, const char *mime_type)
{
    if (s_mutex == NULL) {
        const esp_err_t err = tivoo_audio_resource_init();
        if (err != ESP_OK) {
            return err;
        }
    }

    audio_request_t *request = create_request(playback_id, url, mime_type);
    if (request == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    return start_request(request);
}

esp_err_t tivoo_audio_resource_stop(
    const char *request_id, const char *expected_audio_id, const char *reason)
{
    return stop_request(request_id,expected_audio_id,reason,NULL);
}

static esp_err_t stop_request(
    const char *request_id, const char *expected_audio_id, const char *reason, const char *session_id)
{
    if (!is_uuid(request_id) ||
        (expected_audio_id != NULL && expected_audio_id[0] != '\0' &&
         !is_uuid(expected_audio_id)) ||
        reason == NULL || reason[0] == '\0' || strlen(reason) > REASON_MAX) {
        return ESP_ERR_INVALID_ARG;
    }
    if (s_mutex == NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    (void)xSemaphoreTake(s_mutex, portMAX_DELAY);
    if (!seen_id(s_recent_stops, request_id)) {
        remember_id(s_recent_stops, &s_next_stop, request_id);
        audio_request_t *request = s_active_request;
        if (expected_audio_id != NULL && expected_audio_id[0] != '\0' &&
            (request == NULL || strcmp(expected_audio_id, request->playback_id) != 0)) {
            request = s_pending_request;
            if (request != NULL && strcmp(expected_audio_id, request->playback_id) != 0) {
                request = NULL;
            }
        }
        if(session_id && request &&
            (strcmp(session_id,request->session_id)!=0 ||
             request->peer_generation!=tivoo_diagnostics_mic_generation())) request=NULL;
        if (request != NULL && !request->terminal && !atomic_exchange(&request->stop_requested, true)) {
            tivoo_audio_output_stop(request->generation);
            if (request->socket_fd >= 0) {
                // Wake the HTTP worker without modifying ESP-IDF client state from this task.
                (void)shutdown(request->socket_fd, SHUT_RDWR);
            }
        }
    }
    (void)xSemaphoreGive(s_mutex);
    return ESP_OK;
}

bool tivoo_audio_resource_handle_message(
    uint8_t type, const uint8_t *payload, size_t size)
{
    if (type == TYPE_TTS_PLAY) {
        handle_tts_play(payload, size);
    } else if (type == TYPE_AUDIO_STOP) {
        handle_audio_stop(payload, size);
    }
    return true;
}

#endif
