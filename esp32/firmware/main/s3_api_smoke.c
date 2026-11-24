/* Adapted from P5b0. Never executes in b1; validates the S3 linker/API. */
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include "driver/i2s_common.h"
#include "driver/i2s_std.h"
#include "esp_afe_config.h"
#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#include "model_path.h"
#include "esp_audio_dec_default.h"
#include "esp_audio_simple_dec_default.h"
#include "esp_audio_simple_dec.h"
#include "esp_ae_rate_cvt.h"

volatile bool tivoo_s3_enable_api_probe = false;

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
    srmodel_list_t *models = esp_srmodel_init("model");
    if (models == NULL) {
        return;
    }
    int wake = esp_srmodel_exists(models, "wn9_hilexin");
    int vad = esp_srmodel_exists(models, "vadnet1_medium");
    if (wake < 0 || vad < 0) {
        esp_srmodel_deinit(models);
        return;
    }
    afe_config_t *config = afe_config_init(
        "MMNR", models, AFE_TYPE_SR, AFE_MODE_HIGH_PERF);
    if (config != NULL) {
        config->aec_init = true;
        config->aec_mode = AEC_MODE_SR_HIGH_PERF;
        config->vad_init = true;
        config->vad_model_name = models->model_name[vad];
        config->vad_mute_playback = false;
        config->ns_init = false;
        config->se_init = true;
        config->wakenet_init = true;
        config->wakenet_model_name = models->model_name[wake];
        (void)afe_config_check(config);
        const esp_afe_sr_iface_t *afe = esp_afe_handle_from_config(config);
        if (afe != NULL) {
            esp_afe_sr_data_t *afe_data = afe->create_from_config(config);
            if (afe_data != NULL) {
                (void)afe->get_feed_chunksize(afe_data);
                (void)afe->get_fetch_chunksize(afe_data);
                (void)afe->get_feed_channel_num(afe_data);
                (void)afe->get_fetch_channel_num(afe_data);
                (void)afe->get_samp_rate(afe_data);
                afe->destroy(afe_data);
            }
        }
        afe_config_free(config);
    }
    esp_srmodel_deinit(models);
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

void tivoo_s3_api_smoke(void)
{
    if (tivoo_s3_enable_api_probe) {
        probe_i2s_full_duplex();
        probe_esp_sr_afe();
        probe_simple_decoders();
        probe_sample_rate_conversion();
    }
}
