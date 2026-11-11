/*
 * P5b0 compile/link compatibility probe.
 *
 * This project is never used as a production firmware image. All API calls
 * live behind a volatile false guard so the linker must resolve them while
 * the probe does not start radios, sockets, I2S streams, AFE tasks or decoders.
 */

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>

#include "esp_err.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "nvs_flash.h"

#include "esp_bt.h"
#include "esp_bt_main.h"
#include "esp_gap_bt_api.h"
#include "esp_spp_api.h"

#include "driver/i2s_common.h"
#include "driver/i2s_std.h"

#include "lwip/sockets.h"
#include "lwip/inet.h"

#include "esp_afe_config.h"
#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#include "model_path.h"

#include "esp_audio_dec_default.h"
#include "esp_audio_simple_dec_default.h"
#include "esp_audio_simple_dec.h"
#include "esp_ae_rate_cvt.h"

volatile bool p5b0_enable_api_probe = false;

static void gap_callback(esp_bt_gap_cb_event_t event, esp_bt_gap_cb_param_t *param)
{
    (void)event;
    (void)param;
}

static void spp_callback(esp_spp_cb_event_t event, esp_spp_cb_param_t *param)
{
    (void)event;
    (void)param;
}

static void probe_classic_spp(void)
{
    esp_bt_controller_config_t bt_config = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
    esp_bd_addr_t peer_addr = {0x11, 0x75, 0x58, 0x97, 0x49, 0x98};
    esp_bt_pin_code_t pin = {'1', '2', '3', '4'};
    esp_bt_cod_t cod = {
        .service = ESP_BT_COD_SRVC_AUDIO | ESP_BT_COD_SRVC_RENDERING,
        .major = ESP_BT_COD_MAJOR_DEV_UNCATEGORIZED,
        .minor = 0,
    };
    esp_spp_cfg_t spp_config = {
        .mode = ESP_SPP_MODE_CB,
        .enable_l2cap_ertm = false,
        .tx_buffer_size = 0,
    };
    uint8_t payload[] = {0x01};

    (void)esp_bt_controller_get_status();
    (void)esp_bt_controller_init(&bt_config);
    (void)esp_bt_controller_enable(ESP_BT_MODE_CLASSIC_BT);
    (void)esp_bluedroid_get_status();
    (void)esp_bluedroid_init();
    (void)esp_bluedroid_enable();

    (void)esp_bt_gap_register_callback(gap_callback);
    (void)esp_spp_register_callback(spp_callback);
    (void)esp_spp_enhanced_init(&spp_config);

    (void)esp_bt_gap_set_scan_mode(ESP_BT_CONNECTABLE, ESP_BT_GENERAL_DISCOVERABLE);
    (void)esp_bt_gap_set_device_name("tivoo-esp32");
    (void)esp_bt_gap_set_cod(cod, ESP_BT_SET_COD_ALL);
    (void)esp_bt_gap_set_pin(ESP_BT_PIN_TYPE_FIXED, 4, pin);
    (void)esp_bt_gap_pin_reply(peer_addr, true, 4, pin);

    (void)esp_spp_start_discovery(peer_addr);
    (void)esp_spp_connect(ESP_SPP_SEC_AUTHENTICATE | ESP_SPP_SEC_ENCRYPT,
                          ESP_SPP_ROLE_MASTER, 1, peer_addr);
    (void)esp_spp_write(0, (int)sizeof(payload), payload);
    (void)esp_spp_disconnect(0);
}

static void probe_wifi_and_sockets(void)
{
    wifi_init_config_t wifi_init = WIFI_INIT_CONFIG_DEFAULT();
    wifi_config_t wifi_config = {0};
    esp_netif_t *sta_netif = NULL;
    struct sockaddr_in address = {
        .sin_family = AF_INET,
        .sin_port = htons(7777),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    struct sockaddr_in peer = {0};
    socklen_t peer_len = sizeof(peer);
    int reuse = 1;
    int server_fd = -1;
    int client_fd = -1;
    uint8_t buffer[16] = {0};

    (void)nvs_flash_init();
    (void)esp_netif_init();
    (void)esp_event_loop_create_default();
    sta_netif = esp_netif_create_default_wifi_sta();
    (void)sta_netif;
    (void)esp_wifi_init(&wifi_init);
    (void)esp_wifi_set_mode(WIFI_MODE_STA);
    (void)esp_wifi_set_config(WIFI_IF_STA, &wifi_config);
    (void)esp_wifi_start();
    (void)esp_wifi_connect();

    server_fd = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
    (void)setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
    (void)bind(server_fd, (struct sockaddr *)&address, sizeof(address));
    (void)listen(server_fd, 1);
    client_fd = accept(server_fd, (struct sockaddr *)&peer, &peer_len);
    (void)recv(client_fd, buffer, sizeof(buffer), 0);
    (void)send(client_fd, buffer, sizeof(buffer), 0);
    (void)shutdown(client_fd, SHUT_RDWR);
    (void)close(client_fd);
    (void)close(server_fd);
}

static void probe_i2s_full_duplex(void)
{
    i2s_chan_config_t channel_config =
        I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    i2s_chan_handle_t tx_handle = NULL;
    i2s_chan_handle_t rx_handle = NULL;
    i2s_std_config_t std_config = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(32000),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = I2S_GPIO_UNUSED,
            .ws = I2S_GPIO_UNUSED,
            .dout = I2S_GPIO_UNUSED,
            .din = I2S_GPIO_UNUSED,
        },
    };
    int32_t samples[16] = {0};
    size_t bytes = 0;

    (void)i2s_new_channel(&channel_config, &tx_handle, &rx_handle);
    (void)i2s_channel_init_std_mode(tx_handle, &std_config);
    (void)i2s_channel_init_std_mode(rx_handle, &std_config);
    (void)i2s_channel_enable(tx_handle);
    (void)i2s_channel_enable(rx_handle);
    (void)i2s_channel_read(rx_handle, samples, sizeof(samples), &bytes, 0);
    (void)i2s_channel_write(tx_handle, samples, sizeof(samples), &bytes, 0);
}

static void probe_esp_sr_afe(void)
{
    srmodel_list_t empty_models = {0};
    afe_config_t *config = afe_config_init(
        "MR", &empty_models, AFE_TYPE_SR, AFE_MODE_HIGH_PERF);

    if (config == NULL) {
        return;
    }

    config->aec_init = true;
    config->aec_mode = AEC_MODE_SR_HIGH_PERF;
    config->vad_init = true;
    config->vad_model_name = NULL;
    config->vad_mute_playback = false;
    config->ns_init = false;
    config->se_init = false;
    config->wakenet_init = false;
    config->agc_init = false;

    const esp_afe_sr_iface_t *afe = esp_afe_handle_from_config(config);
    if (afe == NULL) {
        return;
    }

    esp_afe_sr_data_t *afe_data = afe->create_from_config(config);
    if (afe_data == NULL) {
        return;
    }

    int feed_chunk_samples = afe->get_feed_chunksize(afe_data);
    int16_t input[16] = {0};
    if (feed_chunk_samples > 0) {
        (void)afe->feed(afe_data, input);
    }
    (void)afe->fetch(afe_data);
}

static void probe_simple_decoders(void)
{
    (void)esp_audio_dec_register_default();
    (void)esp_audio_simple_dec_register_default();

    const esp_audio_simple_dec_type_t types[] = {
        ESP_AUDIO_SIMPLE_DEC_TYPE_WAV,
        ESP_AUDIO_SIMPLE_DEC_TYPE_MP3,
    };

    uint8_t input_data[32] = {0};
    uint8_t output_data[128] = {0};

    for (size_t i = 0; i < sizeof(types) / sizeof(types[0]); ++i) {
        (void)esp_audio_simple_check_audio_type(types[i]);

        esp_audio_simple_dec_cfg_t config = {
            .dec_type = types[i],
            .dec_cfg = NULL,
            .cfg_size = 0,
            .use_frame_dec = false,
        };
        esp_audio_simple_dec_handle_t decoder = NULL;
        if (esp_audio_simple_dec_open(&config, &decoder) != ESP_AUDIO_ERR_OK ||
            decoder == NULL) {
            continue;
        }

        esp_audio_simple_dec_raw_t raw = {
            .buffer = input_data,
            .len = sizeof(input_data),
            .eos = false,
            .consumed = 0,
        };
        esp_audio_simple_dec_out_t frame = {
            .buffer = output_data,
            .len = sizeof(output_data),
            .needed_size = 0,
            .decoded_size = 0,
        };
        esp_audio_simple_dec_info_t info = {0};

        (void)esp_audio_simple_dec_process(decoder, &raw, &frame);
        (void)esp_audio_simple_dec_get_info(decoder, &info);
        (void)esp_audio_simple_dec_reset(decoder);
        esp_audio_simple_dec_close(decoder);
    }
}

static void probe_sample_rate_conversion(void)
{
    const esp_ae_rate_cvt_perf_type_t modes[] = {
        ESP_AE_RATE_CVT_PERF_TYPE_MEMORY,
        ESP_AE_RATE_CVT_PERF_TYPE_SPEED,
    };
    int16_t input[256] = {0};
    int16_t output[512] = {0};

    for (size_t i = 0; i < sizeof(modes) / sizeof(modes[0]); ++i) {
        esp_ae_rate_cvt_cfg_t config = {
            .src_rate = 22050,
            .dest_rate = 32000,
            .channel = 1,
            .bits_per_sample = 16,
            .complexity = 3,
            .perf_type = modes[i],
        };
        esp_ae_rate_cvt_handle_t converter = NULL;
        if (esp_ae_rate_cvt_open(&config, &converter) != ESP_AE_ERR_OK ||
            converter == NULL) {
            continue;
        }

        uint32_t output_samples = 0;
        (void)esp_ae_rate_cvt_get_max_out_sample_num(
            converter, 256, &output_samples);
        output_samples = sizeof(output) / sizeof(output[0]);
        (void)esp_ae_rate_cvt_process(
            converter, input, 256, output, &output_samples);
        esp_ae_rate_cvt_close(converter);
    }
}

void app_main(void)
{
    if (p5b0_enable_api_probe) {
        probe_classic_spp();
        probe_wifi_and_sockets();
        probe_i2s_full_duplex();
        probe_esp_sr_afe();
        probe_simple_decoders();
        probe_sample_rate_conversion();
    }
}
