#include "p68_local_turn.h"
#include <assert.h>
#include <stdint.h>
#include <string.h>

typedef struct { size_t sent, packets, ends; } tx_t;
static bool send(void *ctx, tivoo_turn_event_t event, const int16_t *pcm,
                 size_t samples, uint64_t now, const char *reason)
{
    tx_t *tx = ctx;
    (void)now; (void)reason;
    if (event == TIVOO_TURN_PCM) {
        assert(samples >= 320 && samples <= 1920 && samples % 320 == 0);
        for (size_t i = 0; i < samples; i++)
            assert(pcm[i] == (int16_t)((tx->sent+i)/320));
        tx->sent += samples;
        tx->packets++;
    }
    if (event == TIVOO_TURN_SPEECH_END) {
        assert(samples == tx->sent);
        tx->ends++;
    }
    return true;
}
int main(void)
{
    tivoo_local_turn_t t = {0};
    tx_t tx = {0};
    int16_t pcm[320];
    tivoo_turn_begin(&t, 0);
    tivoo_turn_tick(&t, 0, send, &tx);
    tivoo_turn_gate(&t, 1);
    tivoo_turn_ready(&t, 1);
    tivoo_turn_speech(&t, 2, 0);
    for (unsigned frame=0; frame<13; frame++) {
        for (size_t i=0; i<320; i++) pcm[i]=(int16_t)frame;
        tivoo_turn_pcm(&t, frame*320, pcm, 320);
        tivoo_turn_tick(&t, 3+frame*20, send, &tx);
        if (frame == 4) assert(tx.packets == 0);
        if (frame == 5) assert(tx.packets == 1 && tx.sent == 1920);
        if (frame == 11) assert(tx.packets == 2 && tx.sent == 3840);
    }
    assert(tx.sent == 3840);
    tivoo_turn_end(&t, 264, 4160);
    tivoo_turn_tick(&t, 265, send, &tx);
    assert(tx.packets == 3 && tx.sent == 4160 && tx.ends == 1 && t.complete);

    /* 50-frame ring wraps after eight six-frame batches. */
    memset(&tx, 0, sizeof(tx));
    tivoo_turn_begin(&t, 0);
    tivoo_turn_tick(&t, 0, send, &tx);
    tivoo_turn_gate(&t, 1); tivoo_turn_ready(&t, 1);
    tivoo_turn_speech(&t, 2, 0);
    for (unsigned frame=0; frame<57; frame++) {
        for (size_t i=0; i<320; i++) pcm[i]=(int16_t)frame;
        tivoo_turn_pcm(&t, frame*320, pcm, 320);
        tivoo_turn_tick(&t, 3+frame*20, send, &tx);
    }
    tivoo_turn_end(&t, 1144, 57*320);
    tivoo_turn_tick(&t, 1145, send, &tx);
    assert(tx.sent == 57*320 && tx.ends == 1 && t.complete && !t.abort_reason);
    return 0;
}
