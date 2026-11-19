#include "p68_prompt.h"
#include "audio_output_manager.h"
#include "p68_afe_flow.h"
#include "p68_local_turn.h"
#include <assert.h>
#include <string.h>

static int16_t pcm[321];
static tivoo_output_queue_t q;
static unsigned stops, finishes;
static uint64_t completed;
static size_t push(void *ctx, const int16_t *p, size_t n) {
    (void)ctx; return tivoo_output_push(&q, 1, p, n);
}
static void finish(void *ctx) { (void)ctx; ++finishes; assert(tivoo_output_finish_input(&q,1)); }
static void stop(void *ctx) { (void)ctx; ++stops; assert(tivoo_output_stop(&q,1)); }
static bool drain(void *ctx, uint64_t *end, uint64_t *clock) {
    (void)ctx;
    *clock=completed*80;
    if (!tivoo_output_drained(&q,1,(uint32_t)completed)) return false;
    *end=q.in_dma ? (q.last_due+1)*80 : *clock;
    return true;
}
static const tivoo_prompt_io_t io={push,finish,stop,drain};
static tivoo_afe_flow_t flow;
static tivoo_local_turn_t turn;
static uint64_t fake_ms;
static unsigned wake_count;
static void sink(void *ctx, const tivoo_afe_event_t *e) {
    (void)ctx;
    switch(e->type) {
    case TIVOO_AFE_WAKE: ++wake_count; break;
    case TIVOO_AFE_START: tivoo_turn_speech(&turn,fake_ms,e->index); break;
    case TIVOO_AFE_PCM: tivoo_turn_pcm(&turn,e->index,e->pcm,e->count); break;
    case TIVOO_AFE_END: tivoo_turn_end(&turn,fake_ms,e->index); break;
    case TIVOO_AFE_GAP: tivoo_turn_abort(&turn,"gap"); break;
    }
}
static void frame(uint64_t first, bool speech, int state) {
    int16_t p[160];
    for(size_t i=0;i<160;++i) p[i]=(int16_t)(first+i);
    tivoo_afe_flow_frame(&flow,first,p,160,speech,true,state,1,1,1,0);
}
int main(void) {
    const tivoo_prompt_asset_t pool[4]={{pcm,321},{pcm,321},{pcm,321},{pcm,321}};
    int last=-1;
    for(unsigned i=0;i<90;++i) {
        int pick=tivoo_prompt_select(pool,false,last,i);
        assert(pick>=0 && pick<3 && pick!=last);
        last=pick;
        assert(tivoo_prompt_select(pool,true,last,i)==3);
    }
    const tivoo_prompt_asset_t missing[4]={{0},{0},{0},{pcm,321}};
    assert(tivoo_prompt_select(missing,false,-1,0)==-1);
    const tivoo_prompt_asset_t one[4]={{pcm,321},{0},{0},{0}};
    assert(tivoo_prompt_select(one,false,-1,0)==0);
    assert(tivoo_prompt_select(one,false,0,0)==-1);
    assert(tivoo_prompt_select(one,true,-1,0)==-1);
    tivoo_prompt_t p;
    assert(tivoo_output_begin_prompt(&q,1));
    tivoo_prompt_begin(&p,pool[0],100,160,0);
    assert(tivoo_prompt_poll(&p,&io,0,100)==TIVOO_PROMPT_PENDING);
    uint32_t slots[320];
    assert(tivoo_output_refill(&q,slots,10)==160); // no network prefill
    assert(tivoo_output_refill(&q,slots,11)==160);
    assert(tivoo_output_refill(&q,slots,12)==1);
    completed=12;
    assert(tivoo_prompt_poll(&p,&io,0,150)==TIVOO_PROMPT_PENDING);
    completed=13; // confirmed digital drain only
    assert(tivoo_prompt_poll(&p,&io,0,155)==TIVOO_PROMPT_PENDING);
    completed=14;
    assert(tivoo_prompt_poll(&p,&io,0,160)==TIVOO_PROMPT_PENDING);
    completed=15; // exact measured tail boundary
    assert(tivoo_prompt_poll(&p,&io,0,165)==TIVOO_PROMPT_SAFE);
    assert(p.gate_sample==1200 && p.gate_ms==165 && !p.cancelled && finishes==1 && !stops);
    tivoo_afe_flow_init(&flow,1,sink,0);
    tivoo_turn_begin(&turn,100);
    tivoo_afe_flow_prompt(&flow,true,0);
    frame(880,true,1); frame(1040,true,1); assert(!wake_count && !turn.speaking);
    tivoo_afe_flow_prompt(&flow,false,p.gate_sample);
    assert(tivoo_afe_flow_open(&flow,p.gate_sample));
    tivoo_turn_gate(&turn,p.gate_ms);
    fake_ms=170; frame(1200,true,1); // immediate command, stale wake cannot reopen
    assert(!wake_count && turn.speaking && turn.valid_samples==160);
    frame(1360,true,0); frame(1520,false,0);
    assert(turn.ended && turn.valid_samples==480 && turn.pad_samples==160);
    for(size_t i=0;i<480;i++) assert(turn.ring[i]==(int16_t)(1200+i));
    for(size_t i=480;i<640;i++) assert(turn.ring[i]==0);
    tivoo_output_end(&q,1);
    // Missing asset: empty prompt, no alternate pool or playback.
    assert(tivoo_output_begin_prompt(&q,1));
    tivoo_prompt_begin(&p,(tivoo_prompt_asset_t){0},200,0,0);
    assert(tivoo_prompt_poll(&p,&io,0,200)==TIVOO_PROMPT_SAFE && p.skipped);
    tivoo_output_end(&q,1);
    // No drain at watchdog: never grant a gate, issue stop once, retain owner.
    assert(tivoo_output_begin_prompt(&q,1));
    tivoo_prompt_begin(&p,pool[0],1000,160,0);
    assert(tivoo_prompt_poll(&p,&io,0,1000)==TIVOO_PROMPT_PENDING);
    assert(tivoo_output_refill(&q,slots,100)==160);
    assert(tivoo_prompt_poll(&p,&io,0,6000)==TIVOO_PROMPT_UNSAFE);
    assert(stops==1 && p.cancelled);
    assert(tivoo_prompt_poll(&p,&io,0,6001)==TIVOO_PROMPT_UNSAFE && stops==1);
    completed=103;
    assert(tivoo_prompt_poll(&p,&io,0,6002)==TIVOO_PROMPT_SAFE && p.cancelled);
    return 0;
}
