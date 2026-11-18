#include "board_boot.h"
#include "device_status.h"
#include "diagnostics.h"
#include "network_listeners.h"
#include "wifi_station.h"
#include "esp_log.h"

void tivoo_s3_api_smoke(void);

void app_main(void)
{
    tivoo_s3_api_smoke(); /* volatile-disabled compile/link probe */
    tivoo_board_memory_report();
    /* GPIO38 RGB is enabled only after actual carrier revision is confirmed. */
    ESP_LOGI("tivoo_boot", "P6.8 b1 S3 scaffold; RGB GPIO38 pending board check");
    esp_err_t err = tivoo_wifi_station_init_nvs();
    if (err != ESP_OK) {
        ESP_LOGE("tivoo_boot", "NVS initialization failed: %s", esp_err_to_name(err));
        return;
    }
    tivoo_diagnostics_set_message_handler(tivoo_device_status_handle_message);
    ESP_ERROR_CHECK(tivoo_diagnostics_start());
    ESP_ERROR_CHECK(network_listeners_start(7777, 7778));
    err = tivoo_wifi_station_start();
    if (err != ESP_OK) {
        ESP_LOGE("tivoo_boot", "Wi-Fi not started: %s", esp_err_to_name(err));
    }
}
