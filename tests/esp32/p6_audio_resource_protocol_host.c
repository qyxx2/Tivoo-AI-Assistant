#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../../esp32/firmware/main/audio_resource.c"

int main(void)
{
    static const char playback_id[] = "123e4567-e89b-12d3-a456-426614174000";
    static const char request_id[] = "123e4567-e89b-12d3-a456-426614174001";
    static const char url[] = "http://192.168.3.94:8123/api/tts_proxy/opaque-token";
    char payload[512];
    audio_request_t *request = NULL;

    (void)snprintf(payload, sizeof(payload),
        "{\"playback_id\":\"%s\",\"url\":\"%s\",\"mime_type\":\"audio/mpeg\"}",
        playback_id, url);
    assert(parse_tts_play((const uint8_t *)payload, strlen(payload), &request));
    assert(strcmp(request->playback_id, playback_id) == 0);
    assert(strcmp(request->url, url) == 0);
    assert(strcmp(request->mime_type, "audio/mpeg") == 0);
    free(request);

    const char *bad_urls[] = {
        "ftp://192.168.3.94/audio.mp3",
        "/api/tts_proxy/token",
        "file:///etc/passwd",
    };
    for (size_t i = 0; i < sizeof(bad_urls) / sizeof(bad_urls[0]); i++) {
        (void)snprintf(payload, sizeof(payload),
            "{\"playback_id\":\"%s\",\"url\":\"%s\",\"mime_type\":\"audio/mpeg\"}",
            playback_id, bad_urls[i]);
        request = NULL;
        assert(!parse_tts_play((const uint8_t *)payload, strlen(payload), &request));
        assert(request == NULL);
    }

    audio_stop_payload_t stop = {0};
    (void)snprintf(payload, sizeof(payload),
        "{\"request_id\":\"%s\",\"expected_audio_id\":\"%s\",\"reason\":\"user_stop\"}",
        request_id, playback_id);
    assert(parse_audio_stop((const uint8_t *)payload, strlen(payload), &stop));
    assert(strcmp(stop.request_id, request_id) == 0);
    assert(strcmp(stop.expected_audio_id, playback_id) == 0);
    assert(strcmp(stop.reason, "user_stop") == 0);

    (void)snprintf(payload, sizeof(payload),
        "{\"request_id\":\"%s\",\"reason\":\"user_stop\"}", request_id);
    assert(parse_audio_stop((const uint8_t *)payload, strlen(payload), &stop));
    assert(stop.expected_audio_id[0] == '\0');

    assert(media_type_equal("Audio/MPEG; charset=binary", "audio/mpeg"));
    assert(!media_type_equal("audio/wav", "audio/mpeg"));
    assert(!media_type_equal(NULL, "audio/mpeg"));

    puts("P6 audio resource protocol tests passed");
    return 0;
}
