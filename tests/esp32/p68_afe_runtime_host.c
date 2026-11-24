/* Exercise the actual feed/fetch owners with scripted capture and vendor APIs.
 * No simulated acoustic claims; fake scheduling only at blocking boundaries. */
#include <assert.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "s3_afe.c"

static jmp_buf *exit_task;
static void run(void (*task)(void *), unsigned calls);
static int64_t clock_us;
static unsigned budget, capture_count, feed_count, fetch_count;
static unsigned reset_buffer_count, reset_vad_count, gaps;
static bool initial_report, buffer_report, vad_report;
static bool capture_valid, capability, stop_monitor, gate_mode, gate_requested, gate_cross;
static unsigned starts, pcm_count;
static bool worker_mode;
static uint64_t expected_feed_first;
static uint64_t start_index;
static int reset_buffer_result=1, reset_vad_result=1;
static int16_t enhanced[160], in[640], raw_tx[160], cache[32];
static uint32_t raw_slots[320];
static unsigned trace_raw, trace_bad, trace_fetch, trace_gate, trace_gap;
static tivoo_afe_flow_t state;
static afe_fetch_result_t result={
    .data=enhanced,.data_size=sizeof(enhanced),.vad_cache=cache,.vad_cache_size=sizeof(cache),
    .ret_value=ESP_OK,.vad_state=VAD_SILENCE
};
static int fake_feed(esp_afe_sr_data_t *d,const int16_t *pcm) {
    (void)d;
    if(worker_mode) {
        for(unsigned i=0;i<160;i++) {
            int16_t marker=(int16_t)(expected_feed_first+i);
            assert(pcm[4*i]==marker && pcm[4*i+1]==-marker);
            assert(pcm[4*i+2]==0 && pcm[4*i+3]==(int16_t)(100+marker));
        }
        expected_feed_first+=160;
    }
    ++feed_count; return 160;
}
static afe_fetch_result_t *fake_fetch(esp_afe_sr_data_t *d,TickType_t t) {
    (void)d; (void)t;
    if (!budget--) longjmp(*exit_task,1);
    ++fetch_count;
    if (gate_mode) {
        if (fetch_count==2) assert(reset_vad_count==1);
        result.vad_state=VAD_SPEECH;
        for (size_t i=0;i<160;i++) enhanced[i]=(int16_t)(400+i);
    }
    return &result;
}
static int fake_buffer(esp_afe_sr_data_t *d) {(void)d; ++reset_buffer_count; return reset_buffer_result;}
static int fake_vad(esp_afe_sr_data_t *d) {(void)d; ++reset_vad_count; return reset_vad_result;}
static const esp_afe_sr_iface_t vendor={
    .feed=fake_feed,.fetch_with_delay=fake_fetch,.reset_buffer=fake_buffer,.reset_vad=fake_vad
};
esp_err_t tivoo_audio_capture_next(tivoo_capture_frame_t *f) {
    if (!budget--) longjmp(*exit_task,1);
    if(worker_mode && capture_count==16+CAPTURE_QUEUE_FRAMES+4)
        run(feed_task,CAPTURE_QUEUE_FRAMES);
    ++capture_count;
    memset(f,0,sizeof(*f));
    f->first_sample=(uint64_t)capture_count*80;
    f->epoch_first_raw=0;
    f->tx_first_sample=f->first_sample*2-6;
    f->raw_slots=raw_slots;
    f->raw_tx=raw_tx;
    for(unsigned i=0;i<80;i++) {
        f->left[i]=(int16_t)(f->first_sample+i);
        f->right[i]=-f->left[i];
        f->reference[i]=(int16_t)(100+f->left[i]);
    }
    raw_slots[0]=capture_count<<16; raw_slots[1]=(capture_count+1)<<16;
    raw_tx[0]=(int16_t)capture_count;
    f->reference_valid=capture_valid;
    return capture_valid ? ESP_OK : ESP_ERR_TIMEOUT;
}
uint32_t tivoo_audio_capture_overruns(void) {return 0;}
uint32_t tivoo_audio_capture_missed_eofs(void) {return 0;}
esp_err_t tivoo_audio_capture_monitor_start(void) {stop_monitor=true;return ESP_OK;}
void tivoo_s3_local_turn_tick(void) {
    if (gate_mode && !gate_requested && fetch_count==1 && capability) {
        gate_requested=true;
        tivoo_s3_afe_begin_prompt();
        assert(tivoo_s3_afe_finish_prompt(epoch_first+(gate_cross?80:0),true));
    }
}
void tivoo_trace_start(void) {}
void tivoo_trace_record(const tivoo_trace_header_t *h,const void *a,const void *b) {
    switch(h->kind) {
    case TIVOO_TRACE_RAW:
        ++trace_raw;
        assert(h->index==capture_count*160 && h->aux==h->index-6 && h->epoch==0);
        assert(h->flags==TIVOO_TRACE_REFERENCE_VALID && h->count==160 && h->extra==160);
        assert(a==raw_slots && b==raw_tx && raw_tx[0]==(int16_t)capture_count);
        break;
    case TIVOO_TRACE_CAPTURE_ERROR:
        ++trace_bad; assert(h->flags==TIVOO_TRACE_GAP && h->index==UINT64_MAX && !a && !b);break;
    case TIVOO_TRACE_FETCH:
        ++trace_fetch;
        assert(h->epoch==epoch_first && h->count==160 && h->extra==32);
        assert(a==enhanced && b==cache && cache[0]==-123);
        if(gate_mode) {
            assert(h->flags&TIVOO_TRACE_GATE_OPEN && h->flags&TIVOO_TRACE_SPEECH);
            assert((bool)(h->flags&TIVOO_TRACE_VAD_VALID)==(fetch_count!=1));
            assert(h->aux==epoch_first+(gate_cross?80:0));
        }
        break;
    case TIVOO_TRACE_GATE:
        ++trace_gate;assert(!a && !b);
        break;
    case TIVOO_TRACE_AFE_GAP:
        ++trace_gap;assert(h->flags==TIVOO_TRACE_GAP);break;
    default: assert(0);
    }
}
void tivoo_diagnostics_enable_local_wake(void) {capability=true;}
void tivoo_diagnostics_set_local_wake_available(bool available) {capability=available;}
void tivoo_log_write(esp_log_level_t level,const char *module,const char *format,...) {
    (void)level;(void)module;
    char buf[256]; va_list args; va_start(args,format); vsnprintf(buf,sizeof(buf),format,args); va_end(args);
    if (strstr(buf,"waiting for valid feed/fetch") && strstr(buf,"rx_gaps=8")) initial_report=true;
    if (strstr(buf,"reset_buffer failed") && strstr(buf,"resets=1")) buffer_report=true;
    if (strstr(buf,"reset_vad failed") && strstr(buf,"resets=1")) vad_report=true;
}
int64_t esp_timer_get_time(void) {return clock_us;}
void vTaskDelay(TickType_t t) {
    (void)t; clock_us+=1000000;
    if (!budget--) longjmp(*exit_task,1);
}
void vTaskDelete(TaskHandle_t t) {(void)t;longjmp(*exit_task,1);}
unsigned uxTaskGetStackHighWaterMark(void *t) {(void)t;return 4096;}
size_t heap_caps_get_minimum_free_size(unsigned c) {(void)c;return 0;}
size_t heap_caps_get_largest_free_block(unsigned c) {(void)c;return 0;}
size_t heap_caps_get_free_size(unsigned c) {(void)c;return 0;}
static void sink(void *ctx,const tivoo_afe_event_t *e) {
    (void)ctx;
    if(e->type==TIVOO_AFE_GAP)++gaps;
    if(e->type==TIVOO_AFE_START) {
        assert(fetch_count==2 && reset_vad_count==1);
        ++starts; start_index=e->index;
    }
    if(e->type==TIVOO_AFE_PCM) {
        assert(e->index==start_index+pcm_count);
        for(size_t i=0;i<e->count;i++)
            assert(e->pcm[i]==(int16_t)(400+(e->index+i-epoch_first)%160));
        pcm_count+=e->count;
    }
}
QueueHandle_t xQueueCreate(size_t n,size_t size) {
    TestQueue *q=calloc(1,sizeof(*q)); assert(q);
    q->data=calloc(n,size); assert(q->data); q->n=n; q->size=size; return q;
}
int xQueueSend(QueueHandle_t q,const void *p,TickType_t ticks) {
    (void)ticks;
    if(q->count==q->n) return 0;
    memcpy(q->data+((q->head+q->count)%q->n)*q->size,p,q->size);
    ++q->count; return pdTRUE;
}
int xQueueReceive(QueueHandle_t q,void *p,TickType_t ticks) {
    (void)ticks;
    if(q==captured && !budget--) longjmp(*exit_task,1);
    if(!q->count) return 0;
    memcpy(p,q->data+q->head*q->size,q->size);
    q->head=(q->head+1)%q->n; --q->count; return pdTRUE;
}
void xQueueReset(QueueHandle_t q) {q->head=q->count=0;}
void vQueueDelete(QueueHandle_t q) {free(q->data); free(q);}
static void run(void (*task)(void *), unsigned calls) {
    jmp_buf resume;
    jmp_buf *previous=exit_task;
    unsigned saved_budget=budget;
    exit_task=&resume; budget=calls;
    if (!setjmp(resume)) task(NULL);
    exit_task=previous; budget=saved_budget;
}
static void capture_feed(unsigned calls) {
    run(capture_task,calls);
    run(feed_task,calls);
}
int main(int argc,char **argv) {
    assert(argc==2);
    if (!strcmp(argv[1],"sr_config")) {
        uint8_t microphones[]={0,1}, reference[]={3};
        afe_config_t config={
            .aec_init=true,.aec_mode=AEC_MODE_SR_HIGH_PERF,
            .afe_type=AFE_TYPE_SR,.afe_mode=AFE_MODE_HIGH_PERF,
            .se_init=true,.ns_init=false,.vad_init=true,.vad_mute_playback=false,
            .vad_min_speech_ms=128,.vad_min_noise_ms=500,.vad_delay_ms=128,
            .vad_model_name="vadnet1_medium",.wakenet_init=true,
            .wakenet_model_name="wn9_hilexin",.wakenet_model_name_2=NULL,
            .pcm_config={.total_ch_num=4,.mic_num=2,.ref_num=1,.sample_rate=16000,
                         .mic_ids=microphones,.ref_ids=reference}
        };
        assert(config_valid(&config));
        config.aec_mode=AEC_MODE_FD_HIGH_PERF;
        assert(!config_valid(&config));
        config.aec_mode=AEC_MODE_SR_HIGH_PERF;config.afe_type=AFE_TYPE_FD;
        assert(!config_valid(&config));
        config.afe_type=AFE_TYPE_SR;config.vad_mute_playback=true;
        assert(!config_valid(&config));
        return 0;
    }
    cache[0]=-123;
    afe=&vendor; data=(esp_afe_sr_data_t *)1; input=in; feed_size=fetch_size=160;
    flow=&state; tivoo_afe_flow_init(flow,1,sink,NULL);
    controls=xQueueCreate(4,sizeof(gate_control_t));
    captured=xQueueCreate(CAPTURE_QUEUE_FRAMES,sizeof(captured_frame_t));
    if (!strcmp(argv[1],"capture_stall")) {
        worker_mode=capture_valid=true;
        expected_feed_first=80;
        /* The real capture owner keeps draining while feed is blocked for
         * 80 ms (16 DMA intervals, longer than the 12-slot ISR queue).
         * All PCM must be owned copies, despite reused raw source pointers. */
        run(capture_task,16);
        assert(capture_count==16 && !feed_count && captured->count==16);
        run(feed_task,16);
        assert(feed_count==8 && !captured->count && !atomic_load(&rx_gaps));
        assert(trace_raw==16 && !trace_bad && !atomic_load(&capture_overruns));
        // Even a longer overload must stay bounded and invalidate the next
        // accepted packet. It must never silently stitch across dropped PCM.
        run(capture_task,CAPTURE_QUEUE_FRAMES+5);
        assert(captured->count==1 && atomic_load(&capture_overruns)==4);
        unsigned before=feed_count;
        run(feed_task,1);
        assert(feed_count==before && atomic_load(&rx_gaps)==1 && atomic_load(&reset_requested));
        run(feed_task,0);
        assert(atomic_load(&feed_paused) && !captured->count);
        run(capture_task,8);
        assert(captured->count==8); // capture is independent of vendor reset
        vQueueDelete(captured); vQueueDelete(controls);
        return 0;
    }
    if (!strncmp(argv[1],"gate",4)) {
        gate_mode=true; gate_cross=!strcmp(argv[1],"gate_cross");
        capture_valid=true;
        capture_feed(2);
        run(fetch_task,2);
        assert(gate_requested && starts==1 && reset_vad_count==1);
        assert(start_index==epoch_first+(gate_cross?80:0) && pcm_count==(gate_cross?240:320));
        assert(trace_raw==2 && trace_fetch==2 && trace_gate>=2 && !trace_bad && !trace_gap);
        vQueueDelete(controls);
        return 0;
    }
    // Continuous capture failure before the first valid feed.
    capture_feed(8);
    run(fetch_task,15);
    assert(!capability && !feed_count && !fetch_count && atomic_load(&rx_gaps)==8);
    assert(initial_report && trace_bad==8 && !trace_raw && !trace_fetch);
    capture_valid=true;
    capture_feed(2);
    assert(feed_count==1 && !capability);
    run(fetch_task,1);
    assert(fetch_count==1 && capability);
    capture_valid=false;
    capture_feed(1);
    assert(atomic_load(&reset_requested));
    atomic_store(&feed_paused,true); // feed owner has acknowledged the existing pause handshake
    if (!strcmp(argv[1],"buffer_fail")) reset_buffer_result=-1;
    if (!strcmp(argv[1],"vad_fail")) reset_vad_result=-1;
    run(fetch_task,1);
    assert(!capability && gaps==1 && reset_buffer_count==1 && trace_gap==1 && trace_bad==9);
    if (strcmp(argv[1],"recover")) {
        assert(atomic_load(&fatal) && !tivoo_s3_afe_control(TIVOO_AFE_GATE_OPEN,0));
        assert(buffer_report==!strcmp(argv[1],"buffer_fail"));
        assert(vad_report==!strcmp(argv[1],"vad_fail"));
        run(feed_task,1);
        assert(!stop_monitor);
        run(capture_task,1);
        assert(stop_monitor);
    } else {
        assert(!atomic_load(&fatal) && reset_vad_count==1 && !atomic_load(&reset_requested));
        capture_valid=true;
        capture_feed(2);
        assert(!capability && feed_count==2);
        run(fetch_task,1);
        assert(capability && fetch_count==2);
    }
    vQueueDelete(controls);
    return 0;
}
