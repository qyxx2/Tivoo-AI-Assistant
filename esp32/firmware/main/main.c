#include "esp_err.h"
#include "esp_log.h"
#include "esp_system.h"

#include "audio_resource.h"
#include "diagnostics.h"
#include "device_status.h"
#include "hardware_memory.h"
#include "network_listeners.h"
#include "tivoo_spp.h"
#include "wifi_station.h"

#define TIVOO_CONTROL_PORT 7777U
#define TIVOO_DIAGNOSTIC_PORT 7778U
#define TVIO_TYPE_TTS_PLAY 0x30U
#define TVIO_TYPE_AUDIO_STOP 0x31U

static const char *TAG = "tivoo_main";

static bool app_message_handler(
    uint8_t type, const uint8_t *payload, size_t size)
{
    if (type == TVIO_TYPE_TTS_PLAY || type == TVIO_TYPE_AUDIO_STOP) {
        return tivoo_audio_resource_handle_message(type, payload, size);
    }
    return tivoo_device_status_handle_message(type, payload, size);
}

void app_main(void)
{
    esp_err_t err = tivoo_audio_resource_init();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Audio resource manager initialization failed (%d)", (int)err);
        return;
    }

    tivoo_diagnostics_set_message_handler(app_message_handler);
    err = tivoo_diagnostics_start();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Diagnostics worker did not start (error %d)", (int)err);
        return;
    }

    TIVOO_LOGI(TAG, "Reset reason: %d", (int)esp_reset_reason());
    tivoo_hardware_memory_report();

    err = tivoo_wifi_station_init_nvs();
    if (err != ESP_OK) {
        tivoo_report_error("spp_init_failed", TAG, "nvs_init_prerequisite_failed");
        return;
    }

    err = tivoo_spp_start();
    if (err != ESP_OK) {
        tivoo_report_error("spp_init_failed", TAG, "classic_spp_start_failed");
        return;
    }

    err = network_listeners_start(
        TIVOO_CONTROL_PORT, TIVOO_DIAGNOSTIC_PORT);
    if (err != ESP_OK) {
        tivoo_report_error(
            "tcp_listen_failed", TAG, "network_listeners_start_failed");
        return;
    }

    err = tivoo_wifi_station_start();
    if (err != ESP_OK) {
        tivoo_report_error(
            "wifi_init_failed", TAG, "wifi_station_start_failed");
    }
}
