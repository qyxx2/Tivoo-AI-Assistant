#include "p68_local_turn.h"
#include <string.h>

void tivoo_turn_begin(tivoo_local_turn_t *t, uint64_t now)
{
    memset(t,0,offsetof(tivoo_local_turn_t,ring));
    t->wake_ms=t->last_progress_ms=now;
    t->active=true;
}
void tivoo_turn_abort(tivoo_local_turn_t *t, const char *reason)
{
    if (t->active && !t->abort_reason) {
        t->abort_reason=reason;
        t->pending=0;
    }
}
void tivoo_turn_gate(tivoo_local_turn_t *t, uint64_t now)
{
    if (t->active && !t->gated && !t->abort_reason) {
        t->gated=true;
        t->gate_ms=now;
    }
}
void tivoo_turn_ready(tivoo_local_turn_t *t, uint64_t now)
{
    if (t->active && t->start_sent && !t->abort_reason && !t->ready) {
        if (t->gated && now > t->gate_ms + 1000) tivoo_turn_abort(t,"ready_timeout");
        else t->ready=true;
    }
}
void tivoo_turn_speech(tivoo_local_turn_t *t, uint64_t now, uint64_t first)
{
    if (!t->active || t->abort_reason) return;
    if (!t->gated || t->speaking || now-t->gate_ms>3000) {
        tivoo_turn_abort(t,"invalid_speech_start"); return;
    }
    t->speech_ms=t->last_progress_ms=now; t->speaking=true; t->next=first;
}
static void append(tivoo_local_turn_t *t, const int16_t *p, size_t count)
{
    if (count>TIVOO_TURN_PENDING-t->pending) {
        tivoo_turn_abort(t,"pcm_overflow"); return;
    }
    size_t pos=(t->read+t->pending)%TIVOO_TURN_PENDING;
    size_t first=TIVOO_TURN_PENDING-pos;
    if (first>count) first=count;
    if(p) { memcpy(t->ring+pos,p,first*sizeof(*p)); memcpy(t->ring,p+first,(count-first)*sizeof(*p)); }
    else { memset(t->ring+pos,0,first*sizeof(*p)); memset(t->ring,0,(count-first)*sizeof(*p)); }
    t->pending+=count;
}
void tivoo_turn_pcm(tivoo_local_turn_t *t, uint64_t first, const int16_t *pcm, size_t count)
{
    if (!t->active || t->abort_reason) return;
    if (!t->speaking || t->ended || first!=t->next || !pcm || !count) {
        tivoo_turn_abort(t,"afe_gap"); return;
    }
    append(t,pcm,count);
    if(!t->abort_reason) { t->valid_samples+=count; t->next+=count; }
}
void tivoo_turn_end(tivoo_local_turn_t *t, uint64_t now, uint64_t end)
{
    if (!t->active || t->abort_reason) return;
    if (!t->speaking || t->ended || end!=t->next || !t->valid_samples || now-t->speech_ms>15000) {
        tivoo_turn_abort(t,"invalid_speech_end"); return;
    }
    t->pad_samples=(TIVOO_TURN_FRAME-t->valid_samples%TIVOO_TURN_FRAME)%TIVOO_TURN_FRAME;
    append(t,NULL,t->pad_samples);
    t->ended=true; t->end_ms=now;
}
void tivoo_turn_tick(tivoo_local_turn_t *t, uint64_t now, tivoo_turn_send_t send, void *ctx)
{
    if (!t->active) return;
    if (!t->complete && !t->abort_reason) {
        if(!t->gated && now-t->wake_ms>5000) tivoo_turn_abort(t,"gate_timeout");
        else if(t->gated && !t->ready && now-t->gate_ms>1000) tivoo_turn_abort(t,"ready_timeout");
        else if(t->gated && !t->speaking && now-t->gate_ms>3000) tivoo_turn_abort(t,"command_timeout");
        else if(t->speaking && !t->ended && now-t->speech_ms>15000) tivoo_turn_abort(t,"speech_timeout");
        else if(t->ready && (t->pending || t->ended) && now-t->last_progress_ms>1000) tivoo_turn_abort(t,"tx_timeout");
    }
    if(!t->start_sent) {
        if(!send(ctx,TIVOO_TURN_START,NULL,0,t->wake_ms,NULL)) return;
        t->start_sent=true; t->last_progress_ms=now;
    }
    if(t->abort_reason) {
        if(send(ctx,TIVOO_TURN_ABORT,NULL,0,now,t->abort_reason)) t->active=false;
        return;
    }
    if(t->complete || !t->gated) return;
    if(!t->gate_sent) {
        if(!send(ctx,TIVOO_TURN_GATE,NULL,0,t->gate_ms,NULL)) return;
        t->gate_sent=true; t->last_progress_ms=now;
    }
    if(!t->ready || !t->speaking) return;
    if(!t->speech_sent) {
        if(!send(ctx,TIVOO_TURN_SPEECH_START,NULL,0,t->speech_ms,NULL)) return;
        t->speech_sent=true; t->last_progress_ms=now;
    }
    for(unsigned i=0;i<8 && t->pending>=TIVOO_TURN_FRAME;++i) {
        /* Ring size and read index are multiples of the wire frame size. */
        if(!send(ctx,TIVOO_TURN_PCM,t->ring+t->read,TIVOO_TURN_FRAME,now,NULL)) return;
        t->read=(t->read+TIVOO_TURN_FRAME)%TIVOO_TURN_PENDING;
        t->pending-=TIVOO_TURN_FRAME; t->sent+=TIVOO_TURN_FRAME;
        t->last_progress_ms=now;
    }
    if(t->ended && !t->pending && send(ctx,TIVOO_TURN_SPEECH_END,NULL,t->sent,t->end_ms,NULL)) t->complete=true;
}
