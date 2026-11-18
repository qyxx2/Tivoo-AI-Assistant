#include "board_boot.h"
#include "audio_capture.h"
#include "s3_afe.h"
#include "audio_resource.h"
#include "device_status.h"
#include "diagnostics.h"
#include "network_listeners.h"
#include "wifi_station.h"
#include "uart_transport.h"
#include "esp_log.h"

void tivoo_s3_api_smoke(void);

static void local_afe_event(void *ctx, const tivoo_afe_event_t *event)
{
    (void)ctx;
    if (event->type==TIVOO_AFE_WAKE)
        ESP_LOGI("tivoo_boot", "local confirmed wake sample=%llu word=%s",
            (unsigned long long)event->index,tivoo_s3_afe_wake_word(event->word));
    /* b5 owns HA session and b6 owns physical prompt/gate. No MIC_PCM or
     * remote KWS in b4. The default command gate remains closed. */
}

static bool app_message_handler(uint8_t type, const uint8_t *payload, size_t size)
{
    if (type == 0x30U || type == 0x31U)
        return tivoo_audio_resource_handle_message(type, payload, size);
    return tivoo_device_status_handle_message(type, payload, size);
}

void app_main(void)
{
    tivoo_s3_api_smoke(); /* volatile-disabled compile/link probe */
    tivoo_board_memory_report();
    /* GPIO38 RGB is enabled only after actual carrier revision is confirmed. */
    ESP_LOGI("tivoo_boot", "P6.8 b4 S3 control and local AFE; RGB GPIO38 pending board check");
    esp_err_t err = tivoo_wifi_station_init_nvs();
    if (err != ESP_OK) {
        ESP_LOGE("tivoo_boot", "NVS initialization failed: %s", esp_err_to_name(err));
        return;
    }
    err = tivoo_audio_resource_init();
    if (err == ESP_OK) err = tivoo_audio_capture_start();
    if (err != ESP_OK) {
        tivoo_audio_capture_close();
        ESP_LOGE("tivoo_boot", "Physical audio unavailable: %s", esp_err_to_name(err));
    } else {
        err = tivoo_s3_afe_start(local_afe_event,NULL);
        if (err != ESP_OK) {
            ESP_LOGE("tivoo_boot", "Local wake unavailable: %s",esp_err_to_name(err));
            /* Keep the b3 DAC/downlink available and drain capture for diagnostics. */
            if (tivoo_audio_capture_monitor_start()!=ESP_OK)
                ESP_LOGE("tivoo_boot", "Capture monitor unavailable");
        }
        tivoo_board_memory_report();
    }
    tivoo_diagnostics_set_message_handler(app_message_handler);
    ESP_ERROR_CHECK(tivoo_diagnostics_start());
    err = tivoo_uart_transport_start();
    if (err != ESP_OK) {
        ESP_LOGE("tivoo_boot", "UART bridge unavailable: %s", esp_err_to_name(err));
    }
    ESP_ERROR_CHECK(network_listeners_start(7777, 7778));
    err = tivoo_wifi_station_start();
    if (err != ESP_OK) {
        ESP_LOGE("tivoo_boot", "Wi-Fi not started: %s", esp_err_to_name(err));
    }
}
