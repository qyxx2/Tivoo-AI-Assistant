#include "board_boot.h"
#include <inttypes.h>
#include "driver/rmt_encoder.h"
#include "driver/rmt_tx.h"
#include "esp_rom_sys.h"
#include "esp_log.h"
#include "esp_flash.h"
#include "esp_heap_caps.h"
#include "esp_psram.h"
#if CONFIG_IDF_TARGET_ESP32
#include "esp32/himem.h"
#endif

esp_err_t tivoo_board_rgb_off(gpio_num_t pin)
{
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

void tivoo_board_memory_report(void)
{
    uint32_t flash = 0;
    esp_err_t err = esp_flash_get_size(NULL, &flash);
    ESP_LOGI("tivoo_boot", "flash result=%s bytes=%" PRIu32,
             esp_err_to_name(err), flash);
    ESP_LOGI("tivoo_boot", "psram physical=%zu", esp_psram_is_initialized() ?
             esp_psram_get_size() : 0);
    ESP_LOGI("tivoo_boot", "psram total=%zu free=%zu largest=%zu",
             heap_caps_get_total_size(MALLOC_CAP_SPIRAM),
             heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
             heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM));
    ESP_LOGI("tivoo_boot", "internal free=%zu largest=%zu dma free=%zu",
             heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
             heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
             heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA));
#if CONFIG_IDF_TARGET_ESP32
    ESP_LOGI("tivoo_boot", "himem physical=%zu free=%zu",
             esp_himem_get_phys_size(), esp_himem_get_free_size());
#endif
}
