#include <assert.h>
#include <string.h>
#include "audio_capture.h"
#include "audio_output_manager.h"

int main(void) {
    uint32_t raw[2*161];
    for (size_t i=0;i<161;i++) {
        raw[2*i]=0x400000ffU;
        raw[2*i+1]=0xc00000a5U;
    }
    tivoo_stereo_decimator_t whole={0}, split={0};
    int16_t l[81],r[81],ls[81],rs[81];
    assert(tivoo_audio_decimate_stereo(&whole,raw,161,l,r)==80);
    size_t n=tivoo_audio_decimate_stereo(&split,raw,17,ls,rs);
    n+=tivoo_audio_decimate_stereo(&split,raw+34,144,ls+n,rs+n);
    assert(n==80 && !memcmp(l,ls,n*2) && !memcmp(r,rs,n*2));
    assert(l[79]==16384 && r[79]==-16384);
    for(size_t i=0;i<80;i++) assert(l[i]==-r[i]);
    assert(tivoo_inmp441_sample(0x800000ffU)==-8388608);
    assert(tivoo_inmp441_sample(0x7fffffffu)==8388607);

    // The same 31-tap FIR must produce identical phase and amplitude on
    // reference PCM and each mic when presented with matching slot markers.
    int16_t tx[161], tx16[81];
    for (size_t i=0;i<161;i++) {
        tx[i]=(i==20 || i==51) ? 30000 : 0;
        raw[2*i]=(uint32_t)(uint16_t)tx[i]<<16;
        raw[2*i+1]=0;
    }
    whole=(tivoo_stereo_decimator_t){0};
    tivoo_decimator_t ref_filter={0};
    assert(tivoo_audio_decimate_stereo(&whole,raw,161,l,r)==80);
    assert(tivoo_audio_decimate_pcm16(&ref_filter,tx,161,tx16)==80);
    assert(!memcmp(l,tx16,80*2));
    for(size_t i=0;i<80;i++) assert(r[i]==0);

    // A skipped descriptor before the first complete ring cannot give an
    // exact sequence. Flag it rather than silently publish bogus alignment.
    int dma_ids[TIVOO_OUTPUT_DMA_BLOCKS];
    void *dma_order[TIVOO_OUTPUT_DMA_BLOCKS];
    tivoo_dma_eof_tracker_t tracker;
    tivoo_dma_eof_tracker_reset(&tracker,dma_order,TIVOO_OUTPUT_DMA_BLOCKS);
    assert(!tracker.order_uncertain);
    tivoo_dma_eof_tracker_observe(&tracker,&dma_ids[0]);
    tivoo_dma_eof_tracker_observe(&tracker,&dma_ids[2]);
    tivoo_dma_eof_tracker_observe(&tracker,&dma_ids[0]);
    assert(tracker.order_uncertain);

    tivoo_rx_timeline_t timeline={0};
    bool gap=false;
    assert(!tivoo_rx_timeline_accept(&timeline,0,&gap));
    assert(!tivoo_rx_timeline_accept(&timeline,25,&gap));
    assert(tivoo_rx_timeline_accept(&timeline,26,&gap) && !gap);
    assert(tivoo_rx_timeline_accept(&timeline,29,&gap) && gap);
    assert(timeline.lost_blocks==2);
    assert(tivoo_rx_timeline_accept(&timeline,30,&gap) && !gap);

    // Signed saturation on both channels and anti-alias on the right.
    for(size_t i=0;i<161;i++) {
        raw[2*i]=0x7fffffff;
        raw[2*i+1]=0x800000a5;
    }
    whole=(tivoo_stereo_decimator_t){0};
    assert(tivoo_audio_decimate_stereo(&whole,raw,161,l,r)==80);
    assert(l[79]==32767 && r[79]==-32768);
    for(size_t i=0;i<161;i++) raw[2*i+1]=i%2?0xc0000000:0x40000000;
    whole=(tivoo_stereo_decimator_t){0};
    assert(tivoo_audio_decimate_stereo(&whole,raw,161,l,r)==80);
    assert(r[79]>=-4 && r[79]<=4);

    tivoo_tx_reference_t ref={0};
    uint32_t dma[2*TIVOO_OUTPUT_BLOCK]={0};
    int16_t pcm[TIVOO_OUTPUT_BLOCK];
    assert(!tivoo_tx_reference_read(&ref,0,pcm,80));
    dma[0]=dma[1]=0x40000000;
    dma[2]=dma[3]=0x20000000;
    tivoo_tx_reference_record(&ref,0,dma);
    assert(tivoo_tx_reference_read(&ref,0,pcm,80));
    assert(pcm[0]==16384 && pcm[1]==8192 && pcm[2]==0);
    memset(dma,0,sizeof(dma));
    tivoo_tx_reference_record(&ref,2,dma);
    assert(!tivoo_tx_reference_read(&ref,160,pcm,80));
    assert(tivoo_tx_reference_read(&ref,320,pcm,80) && pcm[0]==0);
    tivoo_tx_reference_record(&ref,32,dma);
    assert(!tivoo_tx_reference_read(&ref,0,pcm,80));

    // Actual 160 raw samples at arbitrary calibrated 16k offset: cross
    // the 160-sample DMA reference boundary, including missing/overwritten halves.
    memset(&ref,0,sizeof(ref));
    for (unsigned block=0;block<2;block++) {
        for(unsigned i=0;i<160;i++) dma[2*i]=(uint32_t)(block*160+i+1)<<16;
        tivoo_tx_reference_record(&ref,block,dma);
    }
    assert(tivoo_tx_reference_read(&ref,78,pcm,160));
    for(unsigned i=0;i<160;i++) assert(pcm[i]==(int16_t)(79+i));
    assert(!tivoo_tx_reference_read(&ref,238,pcm,160));
    for(unsigned i=0;i<160;i++) assert(pcm[i]==(int16_t)(i<82?239+i:0));
    tivoo_tx_reference_record(&ref,TIVOO_REFERENCE_BLOCKS,dma);
    assert(!tivoo_tx_reference_read(&ref,78,pcm,160));
    for(unsigned i=0;i<160;i++) assert(pcm[i]==(int16_t)(i<82?0:79+i));

    tivoo_output_queue_t q={0};
    int16_t input[TIVOO_OUTPUT_PREFILL]={1};
    assert(tivoo_output_begin(&q,1));
    assert(tivoo_output_push(&q,1,input,TIVOO_OUTPUT_PREFILL)==TIVOO_OUTPUT_PREFILL);
    for(unsigned i=0;i<24;i++) assert(tivoo_output_refill(&q,dma,i)==160);
    for(unsigned i=24;i<224;i++) assert(tivoo_output_refill(&q,dma,i)==0);
    assert(!tivoo_output_drained(&q,1,224)); /* gap is not completion */
    assert(tivoo_output_push(&q,1,input,1)==1);
    /* A tiny arriving fragment stays queued until recovery prefill or EOF. */
    assert(tivoo_output_refill(&q,dma,225)==0 && dma[0]==0 && q.count==1);
    assert(q.rebuffer_count==1 && q.missing_samples==201U*160U && q.max_gap_samples==201U*160U);
    assert(tivoo_output_finish_input(&q,1));
    assert(tivoo_output_refill(&q,dma,226)==1 && dma[0]==65536 && dma[2]==0);
    assert(q.missing_samples==201U*160U); /* final padding is not an underrun */
    assert(!tivoo_output_drained(&q,1,226));
    assert(tivoo_output_drained(&q,1,227));
    tivoo_output_end(&q,1);
    assert(tivoo_output_begin(&q,2));
    for (size_t i=0;i<TIVOO_OUTPUT_PREFILL;i++) input[i]=(int16_t)(i+1);
    assert(tivoo_output_push(&q,2,input,TIVOO_OUTPUT_PREFILL)==TIVOO_OUTPUT_PREFILL);
    for (unsigned i=0;i<24;i++) assert(tivoo_output_refill(&q,dma,i)==160);
    assert(tivoo_output_refill(&q,dma,24)==0);
    assert(tivoo_output_push(&q,2,input,TIVOO_OUTPUT_PREFILL-1)==TIVOO_OUTPUT_PREFILL-1);
    assert(tivoo_output_refill(&q,dma,25)==0);
    assert(tivoo_output_push(&q,2,input+TIVOO_OUTPUT_PREFILL-1,1)==1);
    for (unsigned i=0;i<24;i++) {
        assert(tivoo_output_refill(&q,dma,26+i)==160);
        for (unsigned j=0;j<160;j++) assert(dma[2*j]==(uint32_t)(i*160+j+1)<<16);
    }
    /* STOP discards a pending recovery fragment and never restarts it. */
    assert(tivoo_output_refill(&q,dma,50)==0);
    assert(tivoo_output_push(&q,2,input,1)==1);
    assert(tivoo_output_stop(&q,2));
    assert(tivoo_output_refill(&q,dma,51)==0 && q.count==0);
    tivoo_output_end(&q,2);
    /* Eager prompts retain low latency; even partial missing blocks count. */
    assert(tivoo_output_begin_prompt(&q,3));
    assert(tivoo_output_push(&q,3,input,160)==160);
    assert(tivoo_output_refill(&q,dma,0)==160);
    assert(tivoo_output_push(&q,3,input,1)==1);
    assert(tivoo_output_refill(&q,dma,1)==1);
    assert(q.missing_samples==159 && q.rebuffer_count==0);
    tivoo_output_end(&q,3);
    assert(tivoo_output_begin_prompt(&q,4));
    for (unsigned i=0;i<3;i++) {
        assert(tivoo_output_push(&q,4,input,80)==80);
        assert(tivoo_output_refill(&q,dma,i)==80);
        assert(q.missing_samples==(i+1)*80 && q.max_gap_samples==80);
    }
    return 0;
}
