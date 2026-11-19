#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef ESP_PLATFORM
#include "esp_err.h"
#include "esp_log.h"
#else
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_INVALID_STATE -2
typedef enum {
    ESP_LOG_NONE = 0,
    ESP_LOG_ERROR = 1,
    ESP_LOG_WARN = 2,
    ESP_LOG_INFO = 3,
    ESP_LOG_DEBUG = 4,
    ESP_LOG_VERBOSE = 5,
} esp_log_level_t;
#endif

typedef bool (*tivoo_diagnostics_message_handler_t)(
    uint8_t type, const uint8_t *payload, size_t size);
/* Called on the diagnostics receive worker; keep this callback non-blocking. */
typedef void (*tivoo_diagnostics_mic_capture_stop_handler_t)(
    const char *session_id, const char *reason);

#define TVIO_TYPE_MIC_SESSION_START 0x20U
#define TVIO_TYPE_MIC_PCM 0x21U
#define TVIO_TYPE_MIC_SESSION_END 0x22U
#define TVIO_TYPE_MIC_ACTIVITY 0x24U
#define TVIO_TYPE_STT_READY 0x25U
#define TVIO_TYPE_COMMAND_GATE 0x26U
#define TVIO_TYPE_FOLLOWUP_OPEN 0x27U
#define TVIO_LOCAL_WAKE_CAPABILITY "local_wake_stt_v1"

esp_err_t tivoo_diagnostics_start(void);
void tivoo_diagnostics_enable_mic_activity(void);
uint32_t tivoo_diagnostics_mic_generation(void);
void tivoo_diagnostics_enable_local_wake(void);
/* Nonblocking availability publication; a changed HELLO requires a fresh ACK. */
void tivoo_diagnostics_set_local_wake_available(bool available);
uint32_t tivoo_diagnostics_local_wake_generation(void);
bool tivoo_diagnostics_send_mic(
    uint32_t generation, uint8_t type, const void *payload, size_t size);
void tivoo_diagnostics_stop(void);

bool tivoo_diagnostics_send_message(
    uint8_t type, const uint8_t *payload, size_t size);
void tivoo_diagnostics_set_message_handler(
    tivoo_diagnostics_message_handler_t handler);
void tivoo_diagnostics_set_mic_capture_stop_handler(
    tivoo_diagnostics_mic_capture_stop_handler_t handler);

void tivoo_diagnostics_client_connected(int fd);
bool tivoo_diagnostics_client_data(int fd, const uint8_t *data, size_t size);
void tivoo_diagnostics_client_disconnected(int fd);

void tivoo_log_write(
    esp_log_level_t level,
    const char *module,
    const char *format,
    ...);
void tivoo_report_error(
    const char *error_code,
    const char *module,
    const char *message);

#define TIVOO_LOGD(module, format, ...) \
    tivoo_log_write(ESP_LOG_DEBUG, module, format, ##__VA_ARGS__)
#define TIVOO_LOGI(module, format, ...) \
    tivoo_log_write(ESP_LOG_INFO, module, format, ##__VA_ARGS__)
#define TIVOO_LOGW(module, format, ...) \
    tivoo_log_write(ESP_LOG_WARN, module, format, ##__VA_ARGS__)
#define TIVOO_LOGE(module, format, ...) \
    tivoo_log_write(ESP_LOG_ERROR, module, format, ##__VA_ARGS__)

#ifdef TIVOO_DIAGNOSTICS_HOST_TEST
void tivoo_diagnostics_host_fail_next_send_after(size_t bytes);
#endif
