#include "board_boot.h"
#include "tivoo_spp.h"
#include "uart_transport.h"
#include "esp_log.h"
#include "nvs_flash.h"

void app_main(void)
{
    esp_err_t err = tivoo_board_rgb_off(GPIO_NUM_27);
    ESP_LOGI("tivoo_boot", "Board RGB off GPIO27: %s", esp_err_to_name(err));
    tivoo_board_memory_report();
    err = nvs_flash_init();
    if (err != ESP_OK) {
        ESP_LOGE("tivoo_boot", "NVS init failed (preserved): %s", esp_err_to_name(err));
        return;
    }
    err = tivoo_spp_start();
    ESP_LOGI("tivoo_boot", "Classic SPP startup: %s", esp_err_to_name(err));
    tivoo_uart_bridge_set_available(err == ESP_OK);
    err = tivoo_uart_transport_start();
    ESP_LOGI("tivoo_boot", "UART bridge startup: %s", esp_err_to_name(err));
}
