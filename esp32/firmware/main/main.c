#include "driver/gpio.h"
#include "driver/rmt_encoder.h"
#include "driver/rmt_tx.h"
#include "esp_rom_sys.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_system.h"

#include "audio_frontend.h"
#include "audio_resource.h"
#include "audio_output_manager.h"
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

// Onboard WS2812 RGB LED is wired to GPIO27 on the Waveshare board.
// A latched WS2812 requires an all-zero color frame; a low GPIO alone cannot clear it.
static esp_err_t board_rgb_off(void)
{
    const gpio_num_t pin = GPIO_NUM_27;
    rmt_channel_handle_t channel = NULL;
    rmt_encoder_handle_t encoder = NULL;
    esp_err_t err;
    const rmt_tx_channel_config_t channel_config = {
        .gpio_num = pin,
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10000000,
        .mem_block_symbols = 64,
        .trans_queue_depth = 1,
    };
    const rmt_copy_encoder_config_t encoder_config = {};
    rmt_symbol_word_t off[25];
    // WS2812 zero: 0.3 us high + 0.9 us low. Last symbol latches the frame.
    for (int i = 0; i < 24; i++) {
        off[i] = (rmt_symbol_word_t){.level0 = 1, .duration0 = 3, .level1 = 0, .duration1 = 9};
    }
    off[24] = (rmt_symbol_word_t){.level0 = 0, .duration0 = 500, .level1 = 0, .duration1 = 500};

    gpio_reset_pin(pin);
    gpio_set_direction(pin, GPIO_MODE_OUTPUT);
    gpio_set_level(pin, 0);
    esp_rom_delay_us(100);
    err = rmt_new_tx_channel(&channel_config, &channel);
    if (err != ESP_OK) goto done;
    err = rmt_new_copy_encoder(&encoder_config, &encoder);
    if (err != ESP_OK) goto done;
    err = rmt_enable(channel);
    if (err != ESP_OK) goto done;
    err = rmt_transmit(channel, encoder, off, sizeof(off), &(rmt_transmit_config_t){.loop_count = 0});
    if (err == ESP_OK) err = rmt_tx_wait_all_done(channel, 1000);
    rmt_disable(channel);
done:
    if (encoder) rmt_del_encoder(encoder);
    if (channel) rmt_del_channel(channel);
    gpio_set_direction(pin, GPIO_MODE_OUTPUT);
    gpio_set_level(pin, 0);
    return err;
}

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
    esp_err_t led_err = board_rgb_off();
    ESP_LOGI(TAG, "Board RGB off GPIO27: %s", esp_err_to_name(led_err));

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

    err = tivoo_audio_frontend_start(tivoo_audio_output_reference);
    if (err != ESP_OK) {
        TIVOO_LOGE(TAG, "Audio frontend initialization failed: %s", esp_err_to_name(err));
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
