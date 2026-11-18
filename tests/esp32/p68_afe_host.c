#include "p68_afe_flow.h"
#include <assert.h>
#include <string.h>

static tivoo_afe_flow_t flow;
static int16_t received[24000];
static size_t n;
static unsigned wakes, starts, ends, faults;
static uint64_t first, next;
static int last_word;
static void sink(void *ctx, const tivoo_afe_event_t *e) {
    (void)ctx;
    switch (e->type) {
    case TIVOO_AFE_WAKE: ++wakes; last_word=e->word; break;
    case TIVOO_AFE_START: ++starts; first=next=e->index; n=0; break;
    case TIVOO_AFE_PCM:
        assert(e->index==next && n+e->count<=24000);
        memcpy(received+n,e->pcm,e->count*sizeof(int16_t));
        n+=e->count; next+=e->count; break;
    case TIVOO_AFE_END: ++ends; assert(e->index==next); break;
    case TIVOO_AFE_GAP: ++faults; break;
    }
}
static uint64_t cursor;
static void frame(size_t count, bool speech, int state, int raw, int model, int word, size_t cache) {
    int16_t pcm[1000];
    assert(count<=1000);
    for(size_t i=0;i<count;i++) pcm[i]=(int16_t)(cursor+i);
    tivoo_afe_flow_frame(&flow,cursor,pcm,count,speech,state,raw,model,word,cache);
    cursor+=count;
}
int main(void) {
    int16_t l[]={1,2}, r[]={3,4}, ref[]={5,6}, mmnr[8];
    tivoo_afe_interleave(mmnr,l,r,ref,2);
    const int16_t expected[]={1,3,0,5,2,4,0,6};
    assert(memcmp(mmnr,expected,sizeof(expected))==0);
    tivoo_afe_flow_init(&flow,1,sink,0);
    frame(160,false,-1,2,1,1,0); assert(wakes==0);
    frame(160,false,1,2,1,1,0);
    frame(160,false,1,2,1,1,0); assert(wakes==0);
    frame(160,false,-1,2,0,0,0);
    frame(160,false,-1,2,1,1,0); assert(wakes==1 && last_word==1);
    frame(160,false,0,2,0,0,0);
    frame(160,false,-1,2,1,1,0); assert(wakes==1);
    frame(160,false,1,2,1,1,0);
    frame(160,false,-1,2,1,1,0); assert(wakes==2);
    frame(160,false,1,2,1,2,0);
    frame(160,false,-1,2,1,2,0); assert(wakes==2);
    frame(160,false,1,2,1,1,0);
    tivoo_afe_flow_prompt(&flow,true,0);
    frame(160,true,-1,2,1,1,0);
    tivoo_afe_flow_prompt(&flow,false,cursor+80);
    frame(160,false,1,2,1,1,0);
    frame(160,false,-1,2,1,1,0); assert(wakes==2);
    frame(160,false,1,2,1,1,0);
    frame(160,false,-1,2,1,1,0); assert(wakes==3);
    assert(starts==0 && n==0);
    // Gate clips a frame; cache is a duplicate of already retained enhanced history.
    tivoo_afe_flow_open(&flow,cursor+80);
    uint64_t gate=cursor+80;
    frame(160,false,0,2,0,0,0);
    frame(320,false,0,2,0,0,0);
    frame(480,true,0,2,0,0,400);
    assert(starts==1 && first==gate && n==880);
    for(size_t i=0;i<n;i++) assert(received[i]==(int16_t)(gate+i));
    frame(512,true,0,2,0,0,128);
    frame(160,false,0,2,0,0,0); // vendor VAD has already applied 500ms hysteresis
    assert(ends==1 && n==1552);
    frame(160,true,0,2,0,0,0); assert(starts==1);
    // Rolling history is bounded to exactly 500ms, arbitrary chunk sizes.
    tivoo_afe_flow_open(&flow,cursor);
    for(int i=0;i<17;i++) frame(500,false,0,2,0,0,0);
    uint64_t onset=cursor;
    frame(333,true,0,2,0,0,1000);
    assert(starts==2 && first==onset-8000 && n==8333);
    for(size_t i=0;i<n;i++) assert(received[i]==(int16_t)(first+i));
    // Gap must cancel, not concatenate or emit a false normal end.
    cursor+=80;
    frame(160,true,0,2,0,0,0); assert(faults==1 && ends==1 && n==8333);
    frame(160,false,1,2,1,1,0);
    tivoo_afe_flow_gap(&flow);
    frame(160,false,-1,2,1,1,0); assert(wakes==3);
    frame(160,false,1,1,1,1,0);
    frame(160,false,1,1,1,1,0); assert(wakes==4);
    frame(160,false,0,1,0,0,0);
    frame(160,false,1,1,1,1,0); assert(wakes==5);
    // Late gate cannot pretend already discarded samples still exist.
    assert(!tivoo_afe_flow_open(&flow,cursor-1));
    assert(!flow.gate_open);
    assert(tivoo_afe_flow_open(&flow,cursor));
    frame(160,true,0,2,0,0,0);
    unsigned prior_faults=faults;
    // A second gate while speech is active must not silently discard PCM.
    assert(!tivoo_afe_flow_open(&flow,cursor));
    assert(faults==prior_faults+1 && !flow.gate_open);
    return 0;
}
