#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

#define TIVOO_PCM_MIME "audio/x-tivoo-pcm-s16le-32000-mono"
#define TIVOO_PCM_24K_MIME "audio/x-tivoo-pcm-s16le-24000-mono"

typedef struct tivoo_audio_playback tivoo_audio_playback_t;

esp_err_t tivoo_audio_playback_init(void);
/* pcm_rate: 0 for MP3, 24000/32000 for raw S16LE mono. */
tivoo_audio_playback_t *tivoo_audio_playback_open(uint32_t generation, uint32_t pcm_rate);
esp_err_t tivoo_audio_playback_feed(tivoo_audio_playback_t *playback, uint8_t *data,
    size_t size, bool eof);
bool tivoo_audio_playback_has_pcm(const tivoo_audio_playback_t *playback);
void tivoo_audio_playback_close(tivoo_audio_playback_t *playback);
