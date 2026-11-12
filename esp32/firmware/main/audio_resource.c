#include "audio_resource.h"

#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "cJSON.h"

#ifdef ESP_PLATFORM
#include "esp_http_client.h"
#endif

#define PLAYBACK_ID_MAX 64U
#define URL_MAX 2048U
#define MIME_MAX 96U
#define REASON_MAX 64U

typedef struct {
    char playback_id[PLAYBACK_ID_MAX + 1U];
    char url[URL_MAX + 1U];
    char mime_type[MIME_MAX + 1U];
    atomic_bool stop_requested;
    atomic_bool finished;
    uint64_t bytes_received;
    bool headers_checked;
    bool headers_valid;
    bool reader_failed;
    int status_code;
    char response_mime[MIME_MAX + 1U];
#ifdef ESP_PLATFORM
    esp_http_client_handle_t client;
#endif
} audio_request_t;

typedef struct {
    char request_id[37];
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
    atomic_init(&request->finished, false);
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
    const char *playback_id = cJSON_IsString(id_item)
        ? cJSON_GetStringValue(id_item)
        : NULL;
    const char *url = cJSON_IsString(url_item)
        ? cJSON_GetStringValue(url_item)
        : NULL;
    const char *mime_type = cJSON_IsString(mime_item)
        ? cJSON_GetStringValue(mime_item)
        : NULL;

    *request_out = create_request(playback_id, url, mime_type);
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

    const bool valid = is_uuid(request_id) &&
        (expected_item == NULL || is_uuid(expected_id)) &&
        reason != NULL && reason[0] != '\0' && strlen(reason) <= REASON_MAX;
    if (valid) {
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

#include "device_status.h"
#include "diagnostics.h"
#include "esp_crt_bundle.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#define TAG "audio_resource"
#define TYPE_TTS_PLAY 0x30U
#define TYPE_AUDIO_STOP 0x31U
#define TYPE_AUDIO_STATE 0x32U
#define HTTP_BUFFER_SIZE 1024
#define HTTP_TIMEOUT_MS 8000
#define AUDIO_TASK_STACK 7168U

static SemaphoreHandle_t s_mutex;
static audio_request_t *s_active_request;
static tivoo_audio_resource_reader_t s_reader;
static void *s_reader_context;

static esp_err_t drain_reader(
    const uint8_t *data, size_t size, void *context)
{
    (void)data;
    (void)size;
    (void)context;
    return ESP_OK;
}

static void send_audio_state(
    const audio_request_t *request,
    const char *state,
    const char *error_code)
{
    cJSON *root = cJSON_CreateObject();
    if (root == NULL) {
        return;
    }
    cJSON_AddStringToObject(root, "audio_id", request->playback_id);
    cJSON_AddStringToObject(root, "source", "tts_http");
    cJSON_AddStringToObject(root, "state", state);
    cJSON_AddNumberToObject(root, "bytes_received", (double)request->bytes_received);
    if (error_code != NULL) {
        cJSON_AddStringToObject(root, "error_code", error_code);
    }

    char *payload = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (payload == NULL) {
        return;
    }
    (void)tivoo_diagnostics_send_message(
        TYPE_AUDIO_STATE, (const uint8_t *)payload, strlen(payload));
    cJSON_free(payload);
}

static void finish_request(
    audio_request_t *request,
    esp_http_client_handle_t client,
    const char *state,
    const char *error_code)
{
    if (error_code != NULL) {
        tivoo_report_error(error_code, TAG, "TTS HTTP resource request failed");
    }
    send_audio_state(request, state, error_code);
    (void)tivoo_device_status_set_audio_resource(false, NULL);

    (void)xSemaphoreTake(s_mutex, portMAX_DELAY);
    if (s_active_request == request) {
        s_active_request = NULL;
    }
    request->client = NULL;
    (void)xSemaphoreGive(s_mutex);

    if (client != NULL) {
        (void)esp_http_client_close(client);
        (void)esp_http_client_cleanup(client);
    }
    free(request);
    vTaskDelete(NULL);
}

static esp_err_t http_event_handler(esp_http_client_event_t *event)
{
    audio_request_t *request = event->user_data;
    if (request == NULL) {
        return ESP_FAIL;
    }

    switch (event->event_id) {
    case HTTP_EVENT_ON_HEADER:
        if (event->header_key != NULL && event->header_value != NULL &&
            strcasecmp(event->header_key, "Content-Type") == 0) {
            const size_t length = strlen(event->header_value);
            if (length <= MIME_MAX) {
                memcpy(request->response_mime, event->header_value, length + 1U);
            } else {
                request->response_mime[0] = '\0';
            }
        }
        break;
    case HTTP_EVENT_ON_HEADERS_COMPLETE:
        request->status_code = esp_http_client_get_status_code(event->client);
        request->headers_checked = true;
        request->headers_valid =
            request->status_code >= 200 && request->status_code < 300 &&
            media_type_equal(request->response_mime, request->mime_type);
        break;
    case HTTP_EVENT_ON_DATA:
        if (!request->headers_checked || !request->headers_valid ||
            atomic_load(&request->stop_requested) || request->reader_failed ||
            event->data == NULL || event->data_len <= 0) {
            break;
        }

        (void)xSemaphoreTake(s_mutex, portMAX_DELAY);
        tivoo_audio_resource_reader_t reader = s_reader;
        void *reader_context = s_reader_context;
        (void)xSemaphoreGive(s_mutex);

        if (reader != NULL &&
            reader((const uint8_t *)event->data, (size_t)event->data_len,
                   reader_context) != ESP_OK) {
            request->reader_failed = true;
            break;
        }
        request->bytes_received += (uint64_t)event->data_len;
        break;
    default:
        break;
    }
    return ESP_OK;
}

static void audio_resource_task(void *context)
{
    audio_request_t *request = context;
    const esp_http_client_config_t config = {
        .url = request->url,
        .method = HTTP_METHOD_GET,
        .timeout_ms = HTTP_TIMEOUT_MS,
        .buffer_size = HTTP_BUFFER_SIZE,
        .buffer_size_tx = HTTP_BUFFER_SIZE,
        .event_handler = http_event_handler,
        .user_data = request,
        .disable_auto_redirect = true,
        .crt_bundle_attach = esp_crt_bundle_attach,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == NULL) {
        atomic_store(&request->finished, true);
        finish_request(request, NULL, "failed", "audio_http_failed");
        return;
    }

    (void)xSemaphoreTake(s_mutex, portMAX_DELAY);
    request->client = client;
    (void)xSemaphoreGive(s_mutex);

    esp_err_t result = ESP_FAIL;
    if (!atomic_load(&request->stop_requested)) {
        result = esp_http_client_perform(client);
    }

    atomic_store(&request->finished, true);
    if (atomic_load(&request->stop_requested)) {
        finish_request(request, client, "stopped", NULL);
        return;
    }
    if (!request->headers_checked) {
        finish_request(request, client, "failed", "audio_http_failed");
        return;
    }
    if (request->status_code < 200 || request->status_code >= 300) {
        finish_request(request, client, "failed", "audio_http_status");
        return;
    }
    if (!request->headers_valid) {
        finish_request(
            request, client, "failed", "audio_content_type_mismatch");
        return;
    }
    if (request->reader_failed || result != ESP_OK ||
        !esp_http_client_is_complete_data_received(client)) {
        finish_request(request, client, "failed", "audio_http_failed");
        return;
    }

    finish_request(request, client, "resource_ready", NULL);
}

static esp_err_t start_request(audio_request_t *request)
{
    (void)xSemaphoreTake(s_mutex, portMAX_DELAY);
    audio_request_t *active = s_active_request;
    if (active != NULL) {
        const bool duplicate =
            strcmp(active->playback_id, request->playback_id) == 0;
        (void)xSemaphoreGive(s_mutex);
        if (!duplicate) {
            tivoo_report_error("audio_busy", TAG, "Another audio resource is active");
        }
        free(request);
        return duplicate ? ESP_OK : ESP_ERR_INVALID_STATE;
    }
    s_active_request = request;
    (void)xSemaphoreGive(s_mutex);

    (void)tivoo_device_status_set_audio_resource(true, request->playback_id);
    send_audio_state(request, "buffering", NULL);
    if (xTaskCreate(
            audio_resource_task, "tivoo_audio", AUDIO_TASK_STACK, request,
            tskIDLE_PRIORITY + 2, NULL) != pdPASS) {
        tivoo_report_error("audio_http_failed", TAG, "Unable to start HTTP task");
        send_audio_state(request, "failed", "audio_http_failed");
        (void)tivoo_device_status_set_audio_resource(false, NULL);
        (void)xSemaphoreTake(s_mutex, portMAX_DELAY);
        if (s_active_request == request) {
            s_active_request = NULL;
        }
        (void)xSemaphoreGive(s_mutex);
        free(request);
        return ESP_ERR_NO_MEM;
    }
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
    (void)tivoo_audio_resource_stop(
        stop.request_id,
        stop.expected_audio_id[0] == '\0' ? NULL : stop.expected_audio_id,
        stop.reason);
}

esp_err_t tivoo_audio_resource_init(void)
{
    if (s_mutex != NULL) {
        return ESP_OK;
    }
    s_mutex = xSemaphoreCreateMutex();
    if (s_mutex == NULL) {
        return ESP_ERR_NO_MEM;
    }
    s_reader = drain_reader;
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
    audio_request_t *active = s_active_request;
    if (active == NULL ||
        (expected_audio_id != NULL && expected_audio_id[0] != '\0' &&
         strcmp(expected_audio_id, active->playback_id) != 0) ||
        atomic_load(&active->finished)) {
        (void)xSemaphoreGive(s_mutex);
        return ESP_OK;
    }

    const bool already_stopping = atomic_exchange(&active->stop_requested, true);
    esp_err_t result = ESP_OK;
    if (!already_stopping && active->client != NULL) {
        result = esp_http_client_cancel_request(active->client);
    }
    (void)xSemaphoreGive(s_mutex);
    return result;
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

void tivoo_audio_resource_set_reader(
    tivoo_audio_resource_reader_t reader, void *context)
{
    if (s_mutex == NULL) {
        return;
    }
    (void)xSemaphoreTake(s_mutex, portMAX_DELAY);
    s_reader = reader == NULL ? drain_reader : reader;
    s_reader_context = context;
    (void)xSemaphoreGive(s_mutex);
}

#endif
