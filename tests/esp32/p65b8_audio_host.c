#include "audio_capture.h"
#include "audio_frontend.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static void test_capture(void)
{
    assert(tivoo_inmp441_sample(0x7fffffff) == 8388607);
    assert(tivoo_inmp441_sample(0x800000ff) == -8388608);
    assert(tivoo_inmp441_sample(0xffffff00) == -1);

    tivoo_decimator_t filter = {0};
    uint32_t stereo[128];
    int16_t mono[64];
    for (size_t i = 0; i < 64; ++i) {
        stereo[2 * i] = 0xc00000ff;
        stereo[2 * i + 1] = 0x7fffffff;
    }
    assert(tivoo_audio_decimate(&filter, stereo, 23, mono) == 11);
    assert(tivoo_audio_decimate(&filter, stereo + 46, 41, mono + 11) == 21);
    assert(mono[31] == -16384);
    for (size_t i = 0; i < 64; ++i) {
        stereo[2 * i] = i % 2 ? 0xc0000000 : 0x40000000;
    }
    assert(tivoo_audio_decimate(&filter, stereo, 64, mono) == 32);
    assert(mono[31] >= -4 && mono[31] <= 4);
}

static const char session_id[] = "11111111-1111-4111-8111-111111111111";
static unsigned starts, activities, ends, packets;
static int next_pcm;
static bool block_start, block_pcm, block_activity;

static bool send_frame(uint32_t generation, uint8_t type, const void *data, size_t size)
{
    assert(generation == 7);
    char expected[180];
    switch (type) {
    case 0x20:
        if (block_start) {
            return false;
        }
        assert(starts == ends);
        snprintf(expected, sizeof(expected), "\"session_id\":\"%s\"", session_id);
        assert(strstr(data, expected));
        assert(strstr(data, "\"preroll_ms\":500"));
        starts++;
        break;
    case 0x24:
        if (block_activity) {
            return false;
        }
        assert(starts == ends + 1);
        assert(strstr(data, activities % 2 == 0 ? "speech_start" : "speech_end"));
        activities++;
        break;
    case 0x21: {
        if (block_pcm) {
            return false;
        }
        assert(activities > 0);
        assert(size == 640);
        const uint8_t *bytes = data;
        assert(bytes[0] == (uint8_t)next_pcm && bytes[1] == 0xff);
        next_pcm++;
        packets++;
        break;
    }
    case 0x22:
        assert(starts == ends + 1);
        assert(strstr(data, session_id));
        ends++;
        break;
    default:
        assert(false);
    }
    return true;
}

static void new_id(char out[37])
{
    memcpy(out, session_id, sizeof(session_id));
}

static void push(tivoo_mic_producer_t *mic, uint32_t generation, bool speech, int value)
{
    int16_t frame[320];
    for (size_t i = 0; i < 320; ++i) {
        frame[i] = -256 + value;
    }
    tivoo_mic_push(mic, generation, speech, 123, frame, 320);
}

static void test_session(void)
{
    tivoo_mic_producer_t mic = {.send = send_frame, .new_id = new_id};
    for (int i = 0; i < 30; ++i) {
        push(&mic, 7, false, i);
    }
    assert(starts == 0);
    next_pcm = 5;
    block_start = true;
    block_activity = true;
    push(&mic, 7, true, 30);
    assert(starts == 0 && packets == 0);
    block_start = false;
    tivoo_mic_push(&mic, 7, true, 124, NULL, 0);
    assert(starts == 1 && activities == 0 && packets == 0);
    block_activity = false;
    push(&mic, 7, true, 31);
    assert(starts == 1 && activities == 1 && packets == 27);
    push(&mic, 7, false, 32);
    assert(ends == 0 && activities == 2 && packets == 28);
    assert(!tivoo_mic_stop(&mic, 7, "other"));
    assert(!tivoo_mic_stop(&mic, 8, session_id));
    block_pcm = true;
    push(&mic, 7, true, 33);
    assert(mic.pending == 1 && mic.dropped_frames == 0 && activities == 3);
    assert(tivoo_mic_stop(&mic, 7, session_id));
    block_pcm = false;
    push(&mic, 7, true, 34);
    assert(ends == 1 && packets == 28);
    push(&mic, 7, false, 35);
    assert(starts == 1 && mic.history_count == 25);
    push(&mic, 0, true, 36);
    assert(starts == 1 && mic.speech);
}

static void test_backpressure_and_reconnect(void)
{
    starts = activities = ends = packets = 0;
    tivoo_mic_producer_t mic = {.send = send_frame, .new_id = new_id};
    for (int i = 0; i < 25; ++i) {
        push(&mic, 7, false, i);
    }
    block_pcm = true;
    for (int i = 25; i < 80; ++i) {
        push(&mic, 7, true, i);
    }
    assert(mic.pending == 50 && mic.dropped_frames == 30);
    assert(mic.preroll_pending == 0 && starts == 1 && activities == 1);
    next_pcm = 30;
    block_pcm = false;
    tivoo_mic_push(&mic, 7, true, 124, NULL, 0);
    assert(packets == 50 && mic.pending == 0);

    push(&mic, 8, true, 80);
    assert(!mic.session_id[0] && !tivoo_mic_stop(&mic, 7, session_id));
    assert(starts == 1 && packets == 50);
}

int main(void)
{
    test_capture();
    test_session();
    test_backpressure_and_reconnect();
    return 0;
}
