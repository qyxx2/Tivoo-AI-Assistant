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
    tivoo_afe_flow_frame(&flow,cursor,pcm,count,speech,true,state,raw,model,word,cache);
    cursor+=count;
}
static void gate_regression(void) {
    static int16_t silence[160], voice[160];
    for (size_t i=0;i<160;i++) voice[i]=(int16_t)(400+i);
    for (int fast=0;fast<2;fast++) {
        tivoo_afe_flow_init(&flow,1,sink,0);
        cursor=0; starts=ends=wakes=faults=0; n=0;
        tivoo_afe_flow_prompt(&flow,true,0);
        tivoo_afe_flow_frame(&flow,0,voice,160,true,true,1,2,1,1,0);
        tivoo_afe_flow_prompt(&flow,false,240);
        assert(tivoo_afe_flow_open(&flow,240));
        // Frame overlaps gate: only the second half belongs to the command.
        tivoo_afe_flow_frame(&flow,160,fast?voice:silence,160,true,true,-1,2,1,1,0);
        assert(starts==0 && wakes==0);
        if (fast) {
            tivoo_afe_flow_frame(&flow,320,voice,160,true,true,1,2,1,1,0);
            assert(starts==1 && first==240 && n==240 && wakes==0);
            assert(!memcmp(received,voice+80,80*sizeof(int16_t)));
            assert(!memcmp(received+80,voice,160*sizeof(int16_t)));
            tivoo_afe_flow_frame(&flow,480,silence,160,false,true,0,2,0,0,0);
            assert(ends==1 && n==400);
        } else {
            for (int i=0;i<50;i++)
                tivoo_afe_flow_frame(&flow,320+160*i,silence,160,true,true,0,2,0,0,0);
            tivoo_afe_flow_frame(&flow,8320,silence,160,false,true,0,2,0,0,0);
            assert(starts==0 && ends==0 && n==0);
            tivoo_afe_flow_frame(&flow,8480,voice,160,true,true,0,2,0,0,0);
            assert(starts==1 && first==480 && n==8160);
        }
    }
}
int main(void) {
    int16_t l[]={1,2,20000,-20000,8191,-8192}, r[]={3,-4,-20000,20000,8192,-8193}, ref[]={5,6,32767,-32768,123,-456}, mmnr[24];
    tivoo_afe_interleave(mmnr,l,r,ref,6);
    const int16_t expected[]={4,12,0,5,8,-16,0,6,32767,-32768,0,32767,-32768,32767,0,-32768,32764,32767,0,123,-32768,-32768,0,-456};
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
    frame(160,false,0,2,0,0,0);
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
    gate_regression();
    return 0;
}
