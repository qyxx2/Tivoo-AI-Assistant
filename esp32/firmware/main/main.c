#include "esp_err.h"
#include "esp_log.h"
#include "esp_system.h"

#include "network_listeners.h"
#include "wifi_station.h"

#define TIVOO_CONTROL_PORT 7777U
#define TIVOO_DIAGNOSTIC_PORT 7778U

static const char *TAG = "tivoo_main";

void app_main(void)
{
    ESP_LOGI(TAG, "Reset reason: %d", (int)esp_reset_reason());

    ESP_ERROR_CHECK(network_listeners_start(
        TIVOO_CONTROL_PORT, TIVOO_DIAGNOSTIC_PORT));

    esp_err_t err = tivoo_wifi_station_start();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Wi-Fi Station did not start (error %d)", (int)err);
    }
}
