#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

typedef struct tivoo_audio_playback tivoo_audio_playback_t;

esp_err_t tivoo_audio_playback_init(void);
tivoo_audio_playback_t *tivoo_audio_playback_open(uint32_t generation);
esp_err_t tivoo_audio_playback_feed(tivoo_audio_playback_t *playback, uint8_t *data,
    size_t size, bool eof);
bool tivoo_audio_playback_has_pcm(const tivoo_audio_playback_t *playback);
void tivoo_audio_playback_close(tivoo_audio_playback_t *playback);
