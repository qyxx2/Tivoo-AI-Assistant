#include "p68_local_turn.h"
#include <assert.h>
#include <string.h>

typedef struct { unsigned n, samples, ends, aborts; bool blocked; tivoo_turn_event_t events[100]; } wire_t;
static bool send(void *ctx, tivoo_turn_event_t type, const int16_t *pcm, size_t samples, uint64_t time, const char *reason)
{
    wire_t *w=ctx;
    (void)time; (void)reason;
    if (w->blocked) return false;
    w->events[w->n++]=type;
    if (type==TIVOO_TURN_PCM) {
        assert(samples>=320 && samples<=1920 && samples%320==0);
        for (size_t i=0;i<samples;++i) assert(pcm[i]==(w->samples+i<321 ? 7 : 0));
        w->samples+=samples;
    }
    if(type==TIVOO_TURN_SPEECH_END) { ++w->ends; assert(samples==w->samples); }
    if(type==TIVOO_TURN_ABORT) ++w->aborts;
    return true;
}
int main(void)
{
    tivoo_local_turn_t t={0};
    wire_t w={0};
    int16_t pcm[321]; for(unsigned i=0;i<321;++i) pcm[i]=7;
    for(unsigned first=0;first<2;++first) {
        memset(&w,0,sizeof(w)); tivoo_turn_begin(&t,100);
        tivoo_turn_tick(&t,100,send,&w); assert(w.n==1 && w.events[0]==TIVOO_TURN_START);
        if(first) tivoo_turn_ready(&t,100);
        tivoo_turn_gate(&t,200);
        tivoo_turn_speech(&t,250,1000);
        tivoo_turn_pcm(&t,1000,pcm,321);
        tivoo_turn_end(&t,300,1321);
        tivoo_turn_tick(&t,300,send,&w);
        if(!first) { assert(w.n==2); tivoo_turn_ready(&t,300); }
        tivoo_turn_tick(&t,301,send,&w);
        assert(w.n==5 && w.events[1]==TIVOO_TURN_GATE && w.events[2]==TIVOO_TURN_SPEECH_START);
        assert(w.events[3]==TIVOO_TURN_PCM && w.events[4]==TIVOO_TURN_SPEECH_END);
        assert(t.complete && t.active && w.samples==640 && w.ends==1 && !w.aborts);
        assert(t.valid_samples==321 && t.pad_samples==319);
    }
    memset(&w,0,sizeof(w)); tivoo_turn_begin(&t,0); tivoo_turn_gate(&t,1); tivoo_turn_tick(&t,1,send,&w);
    tivoo_turn_tick(&t,1002,send,&w); assert(w.aborts==1 && !w.ends && !t.active);
    memset(&w,0,sizeof(w)); tivoo_turn_begin(&t,0); tivoo_turn_gate(&t,1); tivoo_turn_tick(&t,1,send,&w); tivoo_turn_ready(&t,1);
    tivoo_turn_tick(&t,3002,send,&w); assert(w.aborts==1 && !w.ends);
    memset(&w,0,sizeof(w)); tivoo_turn_begin(&t,0); tivoo_turn_gate(&t,1); tivoo_turn_tick(&t,1,send,&w); tivoo_turn_ready(&t,1);
    tivoo_turn_speech(&t,2,0); tivoo_turn_tick(&t,15003,send,&w);
    assert(w.aborts==1 && !w.ends);
    memset(&w,0,sizeof(w)); tivoo_turn_begin(&t,0); tivoo_turn_gate(&t,1); tivoo_turn_tick(&t,1,send,&w);
    tivoo_turn_speech(&t,2,0);
    for (unsigned i=0;i<50;++i) tivoo_turn_pcm(&t,i*320,pcm,320);
    tivoo_turn_pcm(&t,16000,pcm,1);
    tivoo_turn_tick(&t,10,send,&w); assert(w.aborts==1 && !w.ends);
    memset(&w,0,sizeof(w)); tivoo_turn_begin(&t,0); tivoo_turn_gate(&t,1); tivoo_turn_tick(&t,1,send,&w);
    tivoo_turn_ready(&t,1002); tivoo_turn_tick(&t,1002,send,&w);
    assert(w.aborts==1 && !w.ends && !t.active);
    memset(&w,0,sizeof(w)); tivoo_turn_begin_followup(&t,0); tivoo_turn_gate(&t,1);
    tivoo_turn_tick(&t,1,send,&w); tivoo_turn_ready(&t,1);
    tivoo_turn_tick(&t,3002,send,&w); assert(!w.aborts);
    tivoo_turn_speech(&t,4001,0); assert(t.speaking && !t.abort_reason);
    memset(&w,0,sizeof(w)); tivoo_turn_begin_followup(&t,0); tivoo_turn_gate(&t,1);
    tivoo_turn_tick(&t,1,send,&w); tivoo_turn_ready(&t,1);
    tivoo_turn_tick(&t,4002,send,&w); assert(w.aborts==1 && !t.active);
    /* Blocked unsent START expires without opening a stale HA turn. */
    memset(&w,0,sizeof(w)); w.blocked=true;
    tivoo_turn_begin(&t,100); tivoo_turn_gate(&t,200);
    tivoo_turn_tick(&t,200,send,&w);
    assert(t.active && !t.start_sent && !w.n);
    tivoo_turn_tick(&t,1201,send,&w);
    assert(!t.active && !t.start_sent && !w.n);
    w.blocked=false; tivoo_turn_tick(&t,1202,send,&w);
    assert(!w.n);
    /* Short backpressure keeps FIFO and real PCM; after START, timeout is targeted. */
    memset(&w,0,sizeof(w)); w.blocked=true;
    tivoo_turn_begin(&t,100); tivoo_turn_gate(&t,200);
    tivoo_turn_tick(&t,200,send,&w); w.blocked=false;
    tivoo_turn_tick(&t,201,send,&w); tivoo_turn_ready(&t,220);
    tivoo_turn_speech(&t,250,1000); tivoo_turn_pcm(&t,1000,pcm,321);
    tivoo_turn_end(&t,300,1321); w.blocked=true;
    tivoo_turn_tick(&t,300,send,&w); assert(w.n==2 && t.pending==640);
    w.blocked=false; tivoo_turn_tick(&t,301,send,&w);
    assert(w.n==5 && w.events[2]==TIVOO_TURN_SPEECH_START && w.events[3]==TIVOO_TURN_PCM && w.events[4]==TIVOO_TURN_SPEECH_END && t.complete);
    memset(&w,0,sizeof(w)); tivoo_turn_begin(&t,100); tivoo_turn_gate(&t,200);
    tivoo_turn_tick(&t,200,send,&w); w.blocked=true;
    tivoo_turn_tick(&t,1201,send,&w); assert(t.active && w.n==2);
    w.blocked=false; tivoo_turn_tick(&t,1202,send,&w);
    assert(!t.active && w.n==3 && w.events[2]==TIVOO_TURN_ABORT);
    /* A ready turn with a blocked PCM send expires at the transmit deadline. */
    memset(&w,0,sizeof(w)); tivoo_turn_begin(&t,100); tivoo_turn_gate(&t,200);
    tivoo_turn_tick(&t,200,send,&w); tivoo_turn_ready(&t,220);
    tivoo_turn_speech(&t,250,1000); tivoo_turn_tick(&t,250,send,&w);
    assert(w.n==3 && w.events[2]==TIVOO_TURN_SPEECH_START);
    tivoo_turn_pcm(&t,1000,pcm,321);
    tivoo_turn_end(&t,300,1321); w.blocked=true;
    tivoo_turn_tick(&t,300,send,&w); assert(t.pending==640 && t.peak_pending==640);
    tivoo_turn_tick(&t,1251,send,&w);
    assert(t.abort_reason && strcmp(t.abort_reason,"tx_timeout")==0 && !t.pending && t.send_failures==2);
    w.blocked=false; tivoo_turn_tick(&t,1252,send,&w);
    assert(w.n==4 && w.events[3]==TIVOO_TURN_ABORT && !w.ends && !t.active);
    assert(t.send_attempts==6 && t.send_failures==2 && t.ready_ms==220 && t.peak_pending==640);
    /* A grant binds the completed parent once; playback in progress or a
     * stale epoch/UUID never authorizes a second microphone session. */
    assert(!tivoo_turn_followup_allowed(false,true,true,false));
    assert(!tivoo_turn_followup_allowed(true,false,true,false));
    assert(!tivoo_turn_followup_allowed(true,true,false,false));
    assert(!tivoo_turn_followup_allowed(true,true,true,true));
    assert(tivoo_turn_followup_allowed(true,true,true,false));
    return 0;
}
