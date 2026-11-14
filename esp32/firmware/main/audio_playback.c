#include "audio_playback.h"

#include <stdlib.h>

#include "audio_output_manager.h"
#include "esp_ae_rate_cvt.h"
#include "esp_audio_simple_dec.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_mp3_dec.h"

#define MP3_FRAME_SAMPLES 1152U

struct tivoo_audio_playback {
    uint32_t generation;
    esp_audio_simple_dec_handle_t decoder;
    esp_ae_rate_cvt_handle_t src;
    uint32_t rate;
    uint32_t converted_capacity;
    int16_t *converted;
    bool has_pcm;
    unsigned frames;
    int64_t decode_us;
    int64_t src_us;
    int64_t queue_us;
    int16_t decoded[2 * MP3_FRAME_SAMPLES];
};

esp_err_t tivoo_audio_playback_init(void)
{
    return esp_mp3_dec_register() == ESP_AUDIO_ERR_OK ? ESP_OK : ESP_FAIL;
}

tivoo_audio_playback_t *tivoo_audio_playback_open(uint32_t generation)
{
    tivoo_audio_playback_t *playback = calloc(1, sizeof(*playback));
    if (playback == NULL) {
        return NULL;
    }

    esp_audio_simple_dec_cfg_t config = {.dec_type = ESP_AUDIO_SIMPLE_DEC_TYPE_MP3};
    if (esp_audio_simple_dec_open(&config, &playback->decoder) != ESP_AUDIO_ERR_OK) {
        free(playback);
        return NULL;
    }
    playback->generation = generation;
    return playback;
}

static esp_err_t configure_src(tivoo_audio_playback_t *playback, uint32_t rate)
{
    if (playback->src != NULL) {
        esp_ae_rate_cvt_close(playback->src);
        playback->src = NULL;
    }
    free(playback->converted);
    playback->converted = NULL;
    playback->rate = rate;
    if (rate == 32000) {
        return ESP_OK;
    }

    esp_ae_rate_cvt_cfg_t config = {
        .src_rate = rate,
        .dest_rate = 32000,
        .channel = 1,
        .bits_per_sample = 16,
        .complexity = 1,
        .perf_type = ESP_AE_RATE_CVT_PERF_TYPE_SPEED,
    };
    if (esp_ae_rate_cvt_open(&config, &playback->src) != ESP_AE_ERR_OK ||
        esp_ae_rate_cvt_get_max_out_sample_num(playback->src, MP3_FRAME_SAMPLES,
            &playback->converted_capacity) != ESP_AE_ERR_OK) {
        return ESP_FAIL;
    }
    playback->converted = malloc(playback->converted_capacity * sizeof(int16_t));
    return playback->converted == NULL ? ESP_ERR_NO_MEM : ESP_OK;
}

static esp_err_t output_frame(tivoo_audio_playback_t *playback, size_t bytes)
{
    esp_audio_simple_dec_info_t info;
    if (esp_audio_simple_dec_get_info(playback->decoder, &info) != ESP_AUDIO_ERR_OK ||
        info.bits_per_sample != 16 || (info.channel != 1 && info.channel != 2) ||
        info.sample_rate < 8000 || info.sample_rate > 48000 ||
        bytes % (info.channel * sizeof(int16_t)) != 0) {
        return ESP_FAIL;
    }
    uint32_t samples = bytes / (info.channel * sizeof(int16_t));
    if (samples > MP3_FRAME_SAMPLES) {
        return ESP_FAIL;
    }
    if (info.channel == 2) {
        for (size_t i = 0; i < samples; ++i) {
            const int32_t left = playback->decoded[2 * i];
            playback->decoded[i] = (left + playback->decoded[2 * i + 1]) / 2;
        }
    }

    if (playback->rate != info.sample_rate) {
        ESP_LOGI("audio_playback", "MP3 PCM %lu Hz, %u channels",
            (unsigned long)info.sample_rate, info.channel);
        const esp_err_t err = configure_src(playback, info.sample_rate);
        if (err != ESP_OK) {
            return err;
        }
    }
    const int64_t src_start = esp_timer_get_time();
    const int16_t *pcm = playback->decoded;
    if (playback->src != NULL) {
        uint32_t converted = playback->converted_capacity;
        if (esp_ae_rate_cvt_process(playback->src, playback->decoded, samples,
                playback->converted, &converted) != ESP_AE_ERR_OK) {
            return ESP_FAIL;
        }
        pcm = playback->converted;
        samples = converted;
    }
    const int64_t queue_start = esp_timer_get_time();
    playback->src_us += queue_start - src_start;
    const esp_err_t err = tivoo_audio_output_write(playback->generation, pcm, samples);
    playback->queue_us += esp_timer_get_time() - queue_start;
    if (err == ESP_OK && samples != 0) {
        playback->has_pcm = true;
    }
    return err;
}

esp_err_t tivoo_audio_playback_feed(tivoo_audio_playback_t *playback, uint8_t *data,
    size_t size, bool eof)
{
    esp_audio_simple_dec_raw_t input = {.buffer = data, .len = size, .eos = eof};
    while (input.len != 0) {
        esp_audio_simple_dec_out_t output = {
            .buffer = (uint8_t *)playback->decoded, .len = sizeof(playback->decoded),
        };
        input.consumed = 0;
        const int64_t decode_start = esp_timer_get_time();
        const esp_audio_err_t decoded = esp_audio_simple_dec_process(
            playback->decoder, &input, &output);
        playback->decode_us += esp_timer_get_time() - decode_start;
        if (decoded != ESP_AUDIO_ERR_OK || input.consumed > input.len ||
            (input.consumed == 0 && output.decoded_size == 0) ||
            output.decoded_size > sizeof(playback->decoded)) {
            ESP_LOGW("audio_playback", "MP3 decode failed (%d)", decoded);
            return ESP_FAIL;
        }
        if (output.decoded_size != 0) {
            ++playback->frames;
            const esp_err_t err = output_frame(playback, output.decoded_size);
            if (err != ESP_OK) {
                return err;
            }
        }
        input.len -= input.consumed;
        input.buffer += input.consumed;
    }
    return ESP_OK;
}

bool tivoo_audio_playback_has_pcm(const tivoo_audio_playback_t *playback)
{
    return playback->has_pcm;
}

void tivoo_audio_playback_close(tivoo_audio_playback_t *playback)
{
    if (playback == NULL) {
        return;
    }
    ESP_LOGI("audio_playback", "generation=%lu frames=%u decode_ms=%ld src_ms=%ld queue_ms=%ld",
        (unsigned long)playback->generation, playback->frames, (long)(playback->decode_us / 1000),
        (long)(playback->src_us / 1000), (long)(playback->queue_us / 1000));
    esp_audio_simple_dec_close(playback->decoder);
    if (playback->src != NULL) {
        esp_ae_rate_cvt_close(playback->src);
    }
    free(playback->converted);
    free(playback);
}
