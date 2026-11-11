#include "esp_err.h"
#include "esp_log.h"
#include "esp_system.h"

#include "diagnostics.h"
#include "network_listeners.h"
#include "wifi_station.h"

#define TIVOO_CONTROL_PORT 7777U
#define TIVOO_DIAGNOSTIC_PORT 7778U

static const char *TAG = "tivoo_main";

void app_main(void)
{
    esp_err_t err = tivoo_diagnostics_start();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Diagnostics worker did not start (error %d)", (int)err);
        return;
    }

    TIVOO_LOGI(TAG, "Reset reason: %d", (int)esp_reset_reason());

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
