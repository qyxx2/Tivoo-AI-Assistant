#include "diagnostics.h"

#include <errno.h>
#include <stdarg.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

#include <arpa/inet.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include "cJSON.h"

#ifdef ESP_PLATFORM
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#else
#include <pthread.h>
#endif

#define TVIO_HEADER_SIZE 16U
#define TVIO_MAX_JSON_PAYLOAD (16U * 1024U)
#define TVIO_MAX_MIC_PCM_PAYLOAD (4U * 1024U)
#define TVIO_MAX_LOG_JSON 1024U
#define LOG_QUEUE_DEPTH 16U
#define MESSAGE_QUEUE_DEPTH 4U
#define LOG_MESSAGE_MAX 384U
#define LOG_MODULE_MAX 48U
#define ERROR_CODE_MAX 40U
#define RX_BUFFER_SIZE (TVIO_HEADER_SIZE + TVIO_MAX_JSON_PAYLOAD + 2048U)
#define SEND_TIMEOUT_MS 500U
#define WORKER_DELAY_MS 25U

#define TVIO_TYPE_HELLO 0x01U
#define TVIO_TYPE_HELLO_ACK 0x02U
#define TVIO_TYPE_PING 0x03U
#define TVIO_TYPE_PONG 0x04U
#define TVIO_TYPE_GET_STATUS 0x10U
#define TVIO_TYPE_DEVICE_STATUS 0x11U
#define TVIO_TYPE_MIC_SESSION_START 0x20U
#define TVIO_TYPE_MIC_PCM 0x21U
#define TVIO_TYPE_MIC_SESSION_END 0x22U
#define TVIO_TYPE_MIC_CAPTURE_STOP 0x23U
#define TVIO_TYPE_TTS_PLAY 0x30U
#define TVIO_TYPE_AUDIO_STOP 0x31U
#define TVIO_TYPE_AUDIO_STATE 0x32U
#define TVIO_TYPE_AUDIO_INTERRUPTED 0x33U
#define TVIO_TYPE_DEVICE_EVENT 0x40U
#define TVIO_TYPE_ERROR 0x41U
#define TVIO_TYPE_DIAGNOSTIC_LOG 0x42U

#ifndef TIVOO_FIRMWARE_VERSION
#define TIVOO_FIRMWARE_VERSION "0.1.0+unknown"
#endif

typedef struct {
    uint8_t type;
    esp_log_level_t level;
    char module[LOG_MODULE_MAX];
    char error_code[ERROR_CODE_MAX];
    char message[LOG_MESSAGE_MAX + 1U];
} diagnostic_record_t;

typedef struct {
    uint8_t type;
    size_t size;
    uint8_t *payload;
} realtime_message_t;

static diagnostic_record_t s_queue[LOG_QUEUE_DEPTH];
static size_t s_queue_head;
static size_t s_queue_count;
static realtime_message_t s_message_queue[MESSAGE_QUEUE_DEPTH];
static size_t s_message_head;
static size_t s_message_count;
static bool s_prefer_message = true;
static tivoo_diagnostics_message_handler_t s_message_handler;
static tivoo_diagnostics_mic_capture_stop_handler_t s_mic_capture_stop_handler;
static atomic_uint_fast32_t s_dropped_count = ATOMIC_VAR_INIT(0);
static atomic_bool s_running = ATOMIC_VAR_INIT(false);
static atomic_bool s_worker_alive = ATOMIC_VAR_INIT(false);
static bool s_started;

static int s_client_fd = -1;
static bool s_hello_sent;
static atomic_bool s_ack_accepted = ATOMIC_VAR_INIT(false);
static uint32_t s_tx_sequence;
static uint32_t s_rx_sequence;
static uint8_t s_rx_buffer[RX_BUFFER_SIZE];
static uint8_t s_tx_buffer[TVIO_HEADER_SIZE + TVIO_MAX_JSON_PAYLOAD];
static size_t s_rx_size;

#ifdef ESP_PLATFORM
static SemaphoreHandle_t s_mutex;
static SemaphoreHandle_t s_queue_mutex;
static TaskHandle_t s_worker_task;
#else
static pthread_mutex_t s_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t s_queue_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_t s_worker_thread;
#ifdef TIVOO_DIAGNOSTICS_HOST_TEST
static atomic_size_t s_test_fail_after = ATOMIC_VAR_INIT(SIZE_MAX);
#endif
#endif

static bool mutex_take(bool wait)
{
#ifdef ESP_PLATFORM
    return s_mutex != NULL &&
           xSemaphoreTake(s_mutex, wait ? portMAX_DELAY : 0) == pdTRUE;
#else
    if (wait) {
        return pthread_mutex_lock(&s_mutex) == 0;
    }
    return pthread_mutex_trylock(&s_mutex) == 0;
#endif
}

static void mutex_give(void)
{
#ifdef ESP_PLATFORM
    (void)xSemaphoreGive(s_mutex);
#else
    (void)pthread_mutex_unlock(&s_mutex);
#endif
}

static bool queue_mutex_take(bool wait)
{
#ifdef ESP_PLATFORM
    return s_queue_mutex != NULL &&
           xSemaphoreTake(
               s_queue_mutex, wait ? portMAX_DELAY : 0) == pdTRUE;
#else
    if (wait) {
        return pthread_mutex_lock(&s_queue_mutex) == 0;
    }
    return pthread_mutex_trylock(&s_queue_mutex) == 0;
#endif
}

static void queue_mutex_give(void)
{
#ifdef ESP_PLATFORM
    (void)xSemaphoreGive(s_queue_mutex);
#else
    (void)pthread_mutex_unlock(&s_queue_mutex);
#endif
}

static void worker_delay(void)
{
#ifdef ESP_PLATFORM
    vTaskDelay(pdMS_TO_TICKS(WORKER_DELAY_MS));
#else
    const struct timespec delay = {
        .tv_sec = WORKER_DELAY_MS / 1000U,
        .tv_nsec = (long)(WORKER_DELAY_MS % 1000U) * 1000000L,
    };
    nanosleep(&delay, NULL);
#endif
}

static uint64_t uptime_ms(void)
{
#ifdef ESP_PLATFORM
    return (uint64_t)(esp_timer_get_time() / 1000);
#else
    struct timespec now;
    (void)clock_gettime(CLOCK_MONOTONIC, &now);
    return (uint64_t)now.tv_sec * 1000U + (uint64_t)now.tv_nsec / 1000000U;
#endif
}

static const char *level_name(esp_log_level_t level)
{
    switch (level) {
    case ESP_LOG_ERROR:
        return "ERROR";
    case ESP_LOG_WARN:
        return "WARNING";
    case ESP_LOG_DEBUG:
    case ESP_LOG_VERBOSE:
        return "DEBUG";
    case ESP_LOG_INFO:
    default:
        return "INFO";
    }
}

static void console_log(
    esp_log_level_t level, const char *module, const char *message)
{
#ifdef ESP_PLATFORM
    switch (level) {
    case ESP_LOG_ERROR:
        ESP_LOGE(module, "%s", message);
        break;
    case ESP_LOG_WARN:
        ESP_LOGW(module, "%s", message);
        break;
    case ESP_LOG_DEBUG:
    case ESP_LOG_VERBOSE:
        ESP_LOGD(module, "%s", message);
        break;
    case ESP_LOG_INFO:
    default:
        ESP_LOGI(module, "%s", message);
        break;
    }
#else
    (void)fprintf(
        stderr, "%s %s: %s\n", level_name(level), module, message);
#endif
}

static void copy_text(char *destination, size_t capacity, const char *source)
{
    if (capacity == 0U) {
        return;
    }
    if (source == NULL) {
        destination[0] = '\0';
        return;
    }
    (void)snprintf(destination, capacity, "%s", source);
}

static void truncate_utf8(char *message, size_t length)
{
    if (length == 0U) {
        return;
    }

    size_t start = length - 1U;
    while (start > 0U &&
           (((unsigned char)message[start] & 0xC0U) == 0x80U)) {
        start--;
    }

    const unsigned char lead = (unsigned char)message[start];
    size_t expected = 1U;
    if ((lead & 0xE0U) == 0xC0U) {
        expected = 2U;
    } else if ((lead & 0xF0U) == 0xE0U) {
        expected = 3U;
    } else if ((lead & 0xF8U) == 0xF0U) {
        expected = 4U;
    }

    if (length - start < expected) {
        message[start] = '\0';
    } else {
        message[length] = '\0';
    }
}

static bool valid_error_code(const char *code)
{
    static const char *const allowed[] = {
        "wifi_init_failed",
        "wifi_connect_failed",
        "tcp_listen_failed",
        "spp_init_failed",
        "spp_connect_failed",
        "spp_disconnect_failed",
        "spp_not_connected",
        "spp_tx_queue_full",
        "spp_write_failed",
        "tcp_control_malformed",
        "tivoo_frame_malformed",
        "protocol_invalid_header",
        "protocol_invalid_payload",
        "protocol_unsupported_message",
        "reverse_queue_full",
        "audio_busy",
        "audio_http_failed",
        "audio_http_status",
        "audio_content_type_mismatch",
        "operation_cancelled",
    };
    if (code == NULL) {
        return false;
    }
    for (size_t i = 0; i < sizeof(allowed) / sizeof(allowed[0]); i++) {
        if (strcmp(code, allowed[i]) == 0) {
            return true;
        }
    }
    return false;
}

static bool queue_record(const diagnostic_record_t *record)
{
    if (!atomic_load(&s_running) || !queue_mutex_take(false)) {
        (void)atomic_fetch_add(&s_dropped_count, 1U);
        return false;
    }

    if (s_queue_count == LOG_QUEUE_DEPTH) {
        (void)atomic_fetch_add(&s_dropped_count, 1U);
        queue_mutex_give();
        return false;
    }

    const size_t tail = (s_queue_head + s_queue_count) % LOG_QUEUE_DEPTH;
    s_queue[tail] = *record;
    s_queue_count++;
    queue_mutex_give();
    return true;
}

static void write_le32(uint8_t *output, uint32_t value)
{
    output[0] = (uint8_t)(value & 0xFFU);
    output[1] = (uint8_t)((value >> 8U) & 0xFFU);
    output[2] = (uint8_t)((value >> 16U) & 0xFFU);
    output[3] = (uint8_t)((value >> 24U) & 0xFFU);
}

static uint32_t read_le32(const uint8_t *input)
{
    return (uint32_t)input[0] |
           ((uint32_t)input[1] << 8U) |
           ((uint32_t)input[2] << 16U) |
           ((uint32_t)input[3] << 24U);
}

static bool send_all(int fd, const uint8_t *data, size_t size)
{
    const uint64_t started = uptime_ms();
#ifdef TIVOO_DIAGNOSTICS_HOST_TEST
    const size_t fail_after =
        atomic_exchange(&s_test_fail_after, SIZE_MAX);
#else
    const size_t fail_after = SIZE_MAX;
#endif
    size_t sent = 0U;

    while (sent < size) {
        if (sent >= fail_after) {
            return false;
        }

        size_t chunk_size = size - sent;
        if (fail_after != SIZE_MAX && chunk_size > fail_after - sent) {
            chunk_size = fail_after - sent;
        }
        if (chunk_size == 0U) {
            return false;
        }

        int flags = 0;
#ifdef MSG_NOSIGNAL
        flags |= MSG_NOSIGNAL;
#endif
        const ssize_t result = send(fd, data + sent, chunk_size, flags);
        if (result > 0) {
            sent += (size_t)result;
            continue;
        }
        if (result == 0) {
            return false;
        }
        if (errno == EINTR) {
            continue;
        }
        if (errno != EAGAIN && errno != EWOULDBLOCK) {
            return false;
        }

        struct timeval timeout = {
            .tv_sec = 0,
            .tv_usec = 100000,
        };
        fd_set writable;
        FD_ZERO(&writable);
        FD_SET(fd, &writable);
        const int ready = select(fd + 1, NULL, &writable, NULL, &timeout);
        if (ready < 0 && errno == EINTR) {
            continue;
        }
        if (ready <= 0 || uptime_ms() - started >= SEND_TIMEOUT_MS) {
            return false;
        }
    }
    return true;
}

static bool send_message_locked(
    int fd,
    uint8_t message_type,
    const uint8_t *payload,
    size_t payload_size)
{
    if (payload_size > TVIO_MAX_JSON_PAYLOAD ||
        (payload_size > 0U && payload == NULL)) {
        return false;
    }

    s_tx_buffer[0] = 'T';
    s_tx_buffer[1] = 'V';
    s_tx_buffer[2] = 'I';
    s_tx_buffer[3] = 'O';
    s_tx_buffer[4] = 1U;
    s_tx_buffer[5] = message_type;
    s_tx_buffer[6] = 0U;
    s_tx_buffer[7] = 0U;
    write_le32(&s_tx_buffer[8], (uint32_t)payload_size);
    write_le32(&s_tx_buffer[12], s_tx_sequence);
    if (payload_size > 0U) {
        memcpy(&s_tx_buffer[TVIO_HEADER_SIZE], payload, payload_size);
    }
    return send_all(fd, s_tx_buffer, TVIO_HEADER_SIZE + payload_size);
}

static char *build_hello_payload(size_t *payload_size)
{
#ifdef ESP_PLATFORM
    const esp_reset_reason_t reason = esp_reset_reason();
    const char *reset_reason = "ESP_RST_UNKNOWN";
    switch (reason) {
    case ESP_RST_POWERON:
        reset_reason = "ESP_RST_POWERON";
        break;
    case ESP_RST_EXT:
        reset_reason = "ESP_RST_EXT";
        break;
    case ESP_RST_SW:
        reset_reason = "ESP_RST_SW";
        break;
    case ESP_RST_PANIC:
        reset_reason = "ESP_RST_PANIC";
        break;
    case ESP_RST_INT_WDT:
        reset_reason = "ESP_RST_INT_WDT";
        break;
    case ESP_RST_TASK_WDT:
        reset_reason = "ESP_RST_TASK_WDT";
        break;
    case ESP_RST_WDT:
        reset_reason = "ESP_RST_WDT";
        break;
    case ESP_RST_DEEPSLEEP:
        reset_reason = "ESP_RST_DEEPSLEEP";
        break;
    case ESP_RST_BROWNOUT:
        reset_reason = "ESP_RST_BROWNOUT";
        break;
    case ESP_RST_SDIO:
        reset_reason = "ESP_RST_SDIO";
        break;
    case ESP_RST_USB:
        reset_reason = "ESP_RST_USB";
        break;
    case ESP_RST_JTAG:
        reset_reason = "ESP_RST_JTAG";
        break;
    case ESP_RST_EFUSE:
        reset_reason = "ESP_RST_EFUSE";
        break;
    case ESP_RST_PWR_GLITCH:
        reset_reason = "ESP_RST_PWR_GLITCH";
        break;
    case ESP_RST_CPU_LOCKUP:
        reset_reason = "ESP_RST_CPU_LOCKUP";
        break;
    case ESP_RST_UNKNOWN:
    default:
        reset_reason = "ESP_RST_UNKNOWN";
        break;
    }
#else
    const char *reset_reason = "ESP_RST_POWERON";
#endif

    cJSON *root = cJSON_CreateObject();
    cJSON *capabilities = cJSON_CreateArray();
    if (root == NULL || capabilities == NULL) {
        cJSON_Delete(root);
        cJSON_Delete(capabilities);
        return NULL;
    }
    cJSON_AddStringToObject(root, "device_id", "tivoo-esp32");
    cJSON_AddStringToObject(root, "firmware_version", TIVOO_FIRMWARE_VERSION);
    cJSON_AddNumberToObject(root, "protocol_version", 1);
    cJSON_AddItemToArray(capabilities, cJSON_CreateString("spp_control"));
    cJSON_AddItemToArray(capabilities, cJSON_CreateString("spp_reverse"));
    cJSON_AddItemToArray(
        capabilities, cJSON_CreateString("remote_diagnostics"));
    cJSON_AddItemToArray(capabilities, cJSON_CreateString("device_status"));
    cJSON_AddItemToArray(capabilities, cJSON_CreateString("device_events"));
    cJSON_AddItemToArray(
        capabilities, cJSON_CreateString("audio_resource_http"));
    cJSON_AddItemToArray(capabilities, cJSON_CreateString("audio_control"));
    cJSON_AddItemToObject(root, "capabilities", capabilities);
    cJSON_AddStringToObject(root, "reset_reason", reset_reason);

    char *payload = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (payload != NULL) {
        *payload_size = strlen(payload);
    }
    return payload;
}

static char *build_record_payload(
    const diagnostic_record_t *record,
    uint32_t dropped_count,
    size_t *payload_size)
{
    char message[LOG_MESSAGE_MAX + 1U];
    copy_text(message, sizeof(message), record->message);
    size_t message_length = strlen(message);

    for (;;) {
        cJSON *root = cJSON_CreateObject();
        if (root == NULL) {
            return NULL;
        }

        if (record->type == TVIO_TYPE_ERROR) {
            cJSON_AddStringToObject(root, "error_code", record->error_code);
            cJSON_AddStringToObject(root, "module", record->module);
            cJSON_AddStringToObject(root, "message", message);
            cJSON_AddNumberToObject(root, "uptime_ms", (double)uptime_ms());
        } else {
            cJSON_AddStringToObject(root, "level", level_name(record->level));
            cJSON_AddStringToObject(root, "module", record->module);
            cJSON_AddStringToObject(root, "message", message);
            cJSON_AddNumberToObject(root, "uptime_ms", (double)uptime_ms());
            if (dropped_count > 0U) {
                cJSON_AddNumberToObject(
                    root, "dropped_count", (double)dropped_count);
            }
        }

        char *payload = cJSON_PrintUnformatted(root);
        cJSON_Delete(root);
        if (payload == NULL) {
            return NULL;
        }

        const size_t size = strlen(payload);
        if (size <= TVIO_MAX_LOG_JSON) {
            *payload_size = size;
            return payload;
        }

        cJSON_free(payload);
        if (message_length == 0U) {
            return NULL;
        }
        message_length = message_length * 3U / 4U;
        truncate_utf8(message, message_length);
    }
}

static bool supported_message_type(uint8_t type)
{
    switch (type) {
    case TVIO_TYPE_HELLO:
    case TVIO_TYPE_HELLO_ACK:
    case TVIO_TYPE_PING:
    case TVIO_TYPE_PONG:
    case TVIO_TYPE_GET_STATUS:
    case TVIO_TYPE_DEVICE_STATUS:
    case TVIO_TYPE_MIC_SESSION_START:
    case TVIO_TYPE_MIC_PCM:
    case TVIO_TYPE_MIC_SESSION_END:
    case TVIO_TYPE_MIC_CAPTURE_STOP:
    case TVIO_TYPE_TTS_PLAY:
    case TVIO_TYPE_AUDIO_STOP:
    case TVIO_TYPE_AUDIO_STATE:
    case TVIO_TYPE_AUDIO_INTERRUPTED:
    case TVIO_TYPE_DEVICE_EVENT:
    case TVIO_TYPE_ERROR:
    case TVIO_TYPE_DIAGNOSTIC_LOG:
        return true;
    default:
        return false;
    }
}

static bool inbound_message_type(uint8_t type)
{
    return type == TVIO_TYPE_HELLO_ACK || type == TVIO_TYPE_PING ||
           type == TVIO_TYPE_GET_STATUS ||
           type == TVIO_TYPE_MIC_CAPTURE_STOP || type == TVIO_TYPE_TTS_PLAY ||
           type == TVIO_TYPE_AUDIO_STOP || type == TVIO_TYPE_ERROR;
}

static void clear_message_queue_locked(void)
{
    if (!queue_mutex_take(true)) {
        return;
    }
    while (s_message_count > 0U) {
        realtime_message_t *message = &s_message_queue[s_message_head];
        free(message->payload);
        memset(message, 0, sizeof(*message));
        s_message_head = (s_message_head + 1U) % MESSAGE_QUEUE_DEPTH;
        s_message_count--;
    }
    s_message_head = 0U;
    s_prefer_message = true;
    queue_mutex_give();
}

bool tivoo_diagnostics_send_message(
    uint8_t type, const uint8_t *payload, size_t size)
{
    const bool outbound_type =
        type == TVIO_TYPE_PONG || type == TVIO_TYPE_DEVICE_STATUS ||
        type == TVIO_TYPE_MIC_SESSION_START || type == TVIO_TYPE_MIC_PCM ||
        type == TVIO_TYPE_MIC_SESSION_END || type == TVIO_TYPE_AUDIO_STATE ||
        type == TVIO_TYPE_AUDIO_INTERRUPTED || type == TVIO_TYPE_DEVICE_EVENT ||
        type == TVIO_TYPE_ERROR;
    if (!atomic_load(&s_running) || !atomic_load(&s_ack_accepted) ||
        !outbound_type ||
        size > TVIO_MAX_JSON_PAYLOAD ||
        (type == TVIO_TYPE_MIC_PCM && size > TVIO_MAX_MIC_PCM_PAYLOAD) ||
        (size > 0U && payload == NULL)) {
        return false;
    }

    uint8_t *copy = NULL;
    if (size > 0U) {
        copy = malloc(size);
        if (copy == NULL) {
            return false;
        }
        memcpy(copy, payload, size);
    }
    if (!queue_mutex_take(false)) {
        free(copy);
        return false;
    }
    if (!atomic_load(&s_running) || !atomic_load(&s_ack_accepted) ||
        s_message_count == MESSAGE_QUEUE_DEPTH) {
        queue_mutex_give();
        free(copy);
        return false;
    }

    const size_t tail = (s_message_head + s_message_count) % MESSAGE_QUEUE_DEPTH;
    s_message_queue[tail].type = type;
    s_message_queue[tail].size = size;
    s_message_queue[tail].payload = copy;
    s_message_count++;
    queue_mutex_give();
    return true;
}

void tivoo_diagnostics_set_message_handler(
    tivoo_diagnostics_message_handler_t handler)
{
    if (!s_started) {
        s_message_handler = handler;
        return;
    }
    if (mutex_take(true)) {
        s_message_handler = handler;
        mutex_give();
    }
}

void tivoo_diagnostics_set_mic_capture_stop_handler(
    tivoo_diagnostics_mic_capture_stop_handler_t handler)
{
    if (!s_started) {
        s_mic_capture_stop_handler = handler;
        return;
    }
    if (mutex_take(true)) {
        s_mic_capture_stop_handler = handler;
        mutex_give();
    }
}

static bool is_hex_char(char value)
{
    return (value >= '0' && value <= '9') ||
           (value >= 'a' && value <= 'f') ||
           (value >= 'A' && value <= 'F');
}

static bool valid_uuid(const char *value)
{
    if (value == NULL || strlen(value) != 36U) {
        return false;
    }
    for (size_t i = 0U; i < 36U; i++) {
        if (i == 8U || i == 13U || i == 18U || i == 23U) {
            if (value[i] != '-') {
                return false;
            }
        } else if (!is_hex_char(value[i])) {
            return false;
        }
    }
    return true;
}

static void dispatch_mic_capture_stop(
    tivoo_diagnostics_mic_capture_stop_handler_t handler,
    const uint8_t *payload,
    size_t size)
{
    cJSON *root = payload == NULL || size == 0U
        ? NULL
        : cJSON_ParseWithLength((const char *)payload, size);
    const cJSON *session_item = cJSON_IsObject(root)
        ? cJSON_GetObjectItemCaseSensitive(root, "session_id")
        : NULL;
    const cJSON *reason_item = cJSON_IsObject(root)
        ? cJSON_GetObjectItemCaseSensitive(root, "reason")
        : NULL;
    const char *session_id = cJSON_IsString(session_item)
        ? cJSON_GetStringValue(session_item)
        : NULL;
    const char *reason = cJSON_IsString(reason_item)
        ? cJSON_GetStringValue(reason_item)
        : NULL;
    if (!valid_uuid(session_id) || reason == NULL || reason[0] == '\0' ||
        strlen(reason) > 64U) {
        tivoo_report_error(
            "protocol_invalid_payload",
            "diagnostics",
            "invalid MIC_CAPTURE_STOP payload");
    } else if (handler != NULL) {
        handler(session_id, reason);
    }
    cJSON_Delete(root);
}

static void disconnect_client_locked(int fd)
{
    if (s_client_fd != fd) {
        return;
    }
    (void)shutdown(fd, SHUT_RDWR);
    s_client_fd = -1;
    s_hello_sent = false;
    atomic_store(&s_ack_accepted, false);
    s_tx_sequence = 0U;
    s_rx_sequence = 0U;
    s_rx_size = 0U;
    clear_message_queue_locked();
}

static void diagnostics_worker(void)
{
    while (atomic_load(&s_running)) {
        if (!mutex_take(true)) {
            worker_delay();
            continue;
        }

        if (!atomic_load(&s_running)) {
            mutex_give();
            break;
        }

        const int fd = s_client_fd;
        if (fd < 0) {
            mutex_give();
            worker_delay();
            continue;
        }

        if (!s_hello_sent) {
            size_t payload_size = 0U;
            char *payload = build_hello_payload(&payload_size);
            const bool sent =
                payload != NULL &&
                send_message_locked(
                    fd, TVIO_TYPE_HELLO, (const uint8_t *)payload, payload_size);
            cJSON_free(payload);
            if (sent) {
                s_hello_sent = true;
                s_tx_sequence++;
            } else {
                disconnect_client_locked(fd);
            }
            mutex_give();
            worker_delay();
            continue;
        }

        if (!atomic_load(&s_ack_accepted) || !queue_mutex_take(true)) {
            mutex_give();
            worker_delay();
            continue;
        }

        const bool has_record = s_queue_count > 0U;
        const bool has_message = s_message_count > 0U;
        const bool send_realtime =
            has_message && (!has_record || s_prefer_message);
        diagnostic_record_t record = {0};
        realtime_message_t message = {0};

        if (send_realtime) {
            message = s_message_queue[s_message_head];
            memset(&s_message_queue[s_message_head], 0, sizeof(realtime_message_t));
            s_message_head = (s_message_head + 1U) % MESSAGE_QUEUE_DEPTH;
            s_message_count--;
            s_prefer_message = false;
        } else if (has_record) {
            record = s_queue[s_queue_head];
            s_prefer_message = true;
        }
        queue_mutex_give();

        if (!has_record && !has_message) {
            mutex_give();
            worker_delay();
            continue;
        }

        bool sent = false;
        if (send_realtime) {
            sent = send_message_locked(fd, message.type, message.payload, message.size);
            free(message.payload);
        } else {
            const uint32_t dropped_count = (uint32_t)atomic_load(&s_dropped_count);
            size_t payload_size = 0U;
            char *payload =
                build_record_payload(&record, dropped_count, &payload_size);
            sent = payload != NULL &&
                   send_message_locked(
                       fd, record.type, (const uint8_t *)payload, payload_size);
            cJSON_free(payload);

            if (sent && queue_mutex_take(true)) {
                s_queue_head = (s_queue_head + 1U) % LOG_QUEUE_DEPTH;
                s_queue_count--;
                queue_mutex_give();
            }
            if (sent && record.type == TVIO_TYPE_DIAGNOSTIC_LOG &&
                dropped_count > 0U) {
                (void)atomic_fetch_sub(&s_dropped_count, dropped_count);
            }
        }

        if (sent) {
            s_tx_sequence++;
        } else {
            disconnect_client_locked(fd);
        }
        mutex_give();
        if (!sent) {
            worker_delay();
        }
    }

    atomic_store(&s_worker_alive, false);
}

#ifdef ESP_PLATFORM
static void diagnostics_task(void *context)
{
    (void)context;
    diagnostics_worker();
    s_worker_task = NULL;
    vTaskDelete(NULL);
}
#else
static void *diagnostics_thread(void *context)
{
    (void)context;
    diagnostics_worker();
    return NULL;
}
#endif

esp_err_t tivoo_diagnostics_start(void)
{
    if (s_started) {
        return ESP_ERR_INVALID_STATE;
    }

    memset(s_queue, 0, sizeof(s_queue));
    s_queue_head = 0U;
    s_queue_count = 0U;
    s_message_head = 0U;
    s_message_count = 0U;
    s_prefer_message = true;
    s_client_fd = -1;
    s_hello_sent = false;
    atomic_store(&s_ack_accepted, false);
    s_tx_sequence = 0U;
    s_rx_sequence = 0U;
    s_rx_size = 0U;
    atomic_store(&s_dropped_count, 0U);

#ifdef ESP_PLATFORM
    s_mutex = xSemaphoreCreateMutex();
    s_queue_mutex = xSemaphoreCreateMutex();
    if (s_mutex == NULL || s_queue_mutex == NULL) {
        if (s_mutex != NULL) {
            vSemaphoreDelete(s_mutex);
            s_mutex = NULL;
        }
        if (s_queue_mutex != NULL) {
            vSemaphoreDelete(s_queue_mutex);
            s_queue_mutex = NULL;
        }
        return ESP_FAIL;
    }
#endif

    atomic_store(&s_running, true);
    atomic_store(&s_worker_alive, true);
#ifdef ESP_PLATFORM
    if (xTaskCreate(
            diagnostics_task,
            "tivoo_diag",
            4096,
            NULL,
            tskIDLE_PRIORITY + 1,
            &s_worker_task) != pdPASS) {
        atomic_store(&s_running, false);
        atomic_store(&s_worker_alive, false);
        vSemaphoreDelete(s_mutex);
        vSemaphoreDelete(s_queue_mutex);
        s_mutex = NULL;
        s_queue_mutex = NULL;
        return ESP_FAIL;
    }
#else
    if (pthread_create(&s_worker_thread, NULL, diagnostics_thread, NULL) != 0) {
        atomic_store(&s_running, false);
        atomic_store(&s_worker_alive, false);
        return ESP_FAIL;
    }
#endif

    s_started = true;
    return ESP_OK;
}

void tivoo_diagnostics_stop(void)
{
    if (!s_started) {
        return;
    }

    atomic_store(&s_running, false);
    if (mutex_take(true)) {
        if (s_client_fd >= 0) {
            (void)shutdown(s_client_fd, SHUT_RDWR);
            s_client_fd = -1;
        }
        atomic_store(&s_ack_accepted, false);
        clear_message_queue_locked();
        mutex_give();
    }

#ifdef ESP_PLATFORM
    while (atomic_load(&s_worker_alive)) {
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    if (s_mutex != NULL) {
        vSemaphoreDelete(s_mutex);
        s_mutex = NULL;
    }
    if (s_queue_mutex != NULL) {
        vSemaphoreDelete(s_queue_mutex);
        s_queue_mutex = NULL;
    }
    s_worker_task = NULL;
#else
    (void)pthread_join(s_worker_thread, NULL);
#endif
    s_started = false;
}

void tivoo_diagnostics_client_connected(int fd)
{
    if (!s_started || !mutex_take(true)) {
        return;
    }
    if (s_client_fd >= 0 && s_client_fd != fd) {
        (void)shutdown(s_client_fd, SHUT_RDWR);
    }
    clear_message_queue_locked();
    s_client_fd = fd;
    s_hello_sent = false;
    atomic_store(&s_ack_accepted, false);
    s_tx_sequence = 0U;
    s_rx_sequence = 0U;
    s_rx_size = 0U;
    mutex_give();
}

bool tivoo_diagnostics_client_data(int fd, const uint8_t *data, size_t size)
{
    if (data == NULL || size == 0U || !mutex_take(true)) {
        return false;
    }
    if (s_client_fd != fd || size > sizeof(s_rx_buffer) - s_rx_size) {
        mutex_give();
        return false;
    }

    memcpy(&s_rx_buffer[s_rx_size], data, size);
    s_rx_size += size;

    while (s_rx_size >= TVIO_HEADER_SIZE) {
        const uint8_t *header = s_rx_buffer;
        if (memcmp(header, "TVIO", 4U) != 0 || header[4] != 1U ||
            header[6] != 0U || header[7] != 0U) {
            mutex_give();
            return false;
        }

        const uint32_t payload_size = read_le32(&header[8]);
        const uint32_t sequence = read_le32(&header[12]);
        const uint8_t message_type = header[5];
        if (payload_size > TVIO_MAX_JSON_PAYLOAD ||
            (message_type == TVIO_TYPE_MIC_PCM &&
             payload_size > TVIO_MAX_MIC_PCM_PAYLOAD) ||
            (message_type == TVIO_TYPE_DIAGNOSTIC_LOG &&
             payload_size > TVIO_MAX_LOG_JSON) ||
            sequence != s_rx_sequence) {
            mutex_give();
            return false;
        }

        const size_t frame_size = TVIO_HEADER_SIZE + payload_size;
        if (s_rx_size < frame_size) {
            break;
        }

        if (message_type == TVIO_TYPE_HELLO_ACK) {
            if (!s_hello_sent || atomic_load(&s_ack_accepted)) {
                mutex_give();
                return false;
            }
            cJSON *payload = cJSON_ParseWithLength(
                (const char *)&s_rx_buffer[TVIO_HEADER_SIZE], payload_size);
            const cJSON *accepted = cJSON_IsObject(payload)
                                        ? cJSON_GetObjectItemCaseSensitive(
                                              payload, "accepted")
                                        : NULL;
            const bool valid = cJSON_IsBool(accepted) && cJSON_IsTrue(accepted);
            cJSON_Delete(payload);
            if (!valid) {
                mutex_give();
                return false;
            }
            atomic_store(&s_ack_accepted, true);
        } else if (!atomic_load(&s_ack_accepted) ||
                   (supported_message_type(message_type) &&
                    !inbound_message_type(message_type))) {
            mutex_give();
            return false;
        }

        tivoo_diagnostics_message_handler_t handler = NULL;
        tivoo_diagnostics_mic_capture_stop_handler_t mic_stop_handler = NULL;
        uint8_t *payload_copy = NULL;
        bool unsupported = false;
        if (message_type != TVIO_TYPE_HELLO_ACK &&
            message_type != TVIO_TYPE_HELLO) {
            if (!supported_message_type(message_type)) {
                unsupported = true;
            } else if (message_type == TVIO_TYPE_MIC_CAPTURE_STOP) {
                mic_stop_handler = s_mic_capture_stop_handler;
            }
            if (supported_message_type(message_type) &&
                (message_type == TVIO_TYPE_MIC_CAPTURE_STOP ||
                 s_message_handler != NULL || mic_stop_handler != NULL) &&
                payload_size > 0U) {
                payload_copy = malloc(payload_size);
                if (payload_copy == NULL) {
                    mutex_give();
                    return false;
                }
                memcpy(payload_copy, &s_rx_buffer[TVIO_HEADER_SIZE], payload_size);
            }
            if (supported_message_type(message_type)) {
                handler = s_message_handler;
            }
        }

        s_rx_sequence++;
        s_rx_size -= frame_size;
        if (s_rx_size > 0U) {
            memmove(s_rx_buffer, &s_rx_buffer[frame_size], s_rx_size);
        }

        mutex_give();
        if (unsupported) {
            tivoo_report_error(
                "protocol_unsupported_message",
                "diagnostics",
                "Unsupported TVIO message type");
        }
        if (message_type == TVIO_TYPE_MIC_CAPTURE_STOP) {
            dispatch_mic_capture_stop(mic_stop_handler, payload_copy, payload_size);
        }
        bool handled = true;
        if (handler != NULL) {
            handled = handler(message_type, payload_copy, payload_size);
        }
        free(payload_copy);
        if (!handled) {
            return false;
        }

        if (!mutex_take(true)) {
            return false;
        }
        if (s_client_fd != fd) {
            mutex_give();
            return false;
        }
    }

    mutex_give();
    return true;
}

void tivoo_diagnostics_client_disconnected(int fd)
{
    if (!s_started || !mutex_take(true)) {
        return;
    }
    if (s_client_fd == fd) {
        s_client_fd = -1;
        s_hello_sent = false;
        atomic_store(&s_ack_accepted, false);
        s_tx_sequence = 0U;
        s_rx_sequence = 0U;
        s_rx_size = 0U;
        clear_message_queue_locked();
    }
    mutex_give();
}

void tivoo_log_write(
    esp_log_level_t level,
    const char *module,
    const char *format,
    ...)
{
    const char *tag = module == NULL ? "tivoo" : module;
    char message[LOG_MESSAGE_MAX + 1U];

    va_list arguments;
    va_start(arguments, format);
    const int written = vsnprintf(message, sizeof(message), format, arguments);
    va_end(arguments);

    if (written < 0) {
        message[0] = '\0';
    } else if ((size_t)written > LOG_MESSAGE_MAX) {
        truncate_utf8(message, LOG_MESSAGE_MAX);
    }

    console_log(level, tag, message);

    diagnostic_record_t record = {
        .type = TVIO_TYPE_DIAGNOSTIC_LOG,
        .level = level,
    };
    copy_text(record.module, sizeof(record.module), tag);
    copy_text(record.message, sizeof(record.message), message);
    (void)queue_record(&record);
}

void tivoo_report_error(
    const char *error_code,
    const char *module,
    const char *message)
{
    if (!valid_error_code(error_code)) {
        return;
    }

    diagnostic_record_t record = {
        .type = TVIO_TYPE_ERROR,
        .level = ESP_LOG_ERROR,
    };
    copy_text(record.error_code, sizeof(record.error_code), error_code);
    copy_text(record.module, sizeof(record.module), module);
    copy_text(record.message, sizeof(record.message), message);
    truncate_utf8(record.message, strlen(record.message));
    console_log(ESP_LOG_ERROR, record.module, record.message);
    (void)queue_record(&record);
}

#ifdef TIVOO_DIAGNOSTICS_HOST_TEST
void tivoo_diagnostics_host_fail_next_send_after(size_t bytes)
{
    atomic_store(&s_test_fail_after, bytes);
}
#endif
