/* Exercise the actual feed/fetch owners with scripted capture and vendor APIs.
 * No simulated acoustic claims; fake scheduling only at blocking boundaries. */
#include <assert.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "s3_afe.c"

static jmp_buf exit_task;
static int64_t clock_us;
static unsigned budget, capture_count, feed_count, fetch_count;
static unsigned reset_buffer_count, reset_vad_count, gaps;
static bool initial_report, buffer_report, vad_report;
static bool capture_valid, capability, stop_monitor, gate_mode, gate_requested, gate_cross;
static unsigned starts, pcm_count;
static uint64_t start_index;
static int reset_buffer_result=1, reset_vad_result=1;
static int16_t enhanced[160], in[640];
static tivoo_afe_flow_t state;
static afe_fetch_result_t result={
    .data=enhanced,.data_size=sizeof(enhanced),.ret_value=ESP_OK,.vad_state=VAD_SILENCE
};
static int fake_feed(esp_afe_sr_data_t *d,const int16_t *pcm) {
    (void)d; (void)pcm; ++feed_count; return 160;
}
static afe_fetch_result_t *fake_fetch(esp_afe_sr_data_t *d,TickType_t t) {
    (void)d; (void)t;
    if (!budget--) longjmp(exit_task,1);
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
    if (!budget--) longjmp(exit_task,1);
    ++capture_count;
    memset(f,0,sizeof(*f));
    f->first_sample=(uint64_t)capture_count*80;
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
    if (!budget--) longjmp(exit_task,1);
}
void vTaskDelete(TaskHandle_t t) {(void)t;longjmp(exit_task,1);}
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
static void run(void (*task)(void *), unsigned calls) {
    budget=calls;
    if (!setjmp(exit_task)) task(NULL);
}
int main(int argc,char **argv) {
    assert(argc==2);
    afe=&vendor; data=(esp_afe_sr_data_t *)1; input=in; feed_size=fetch_size=160;
    flow=&state; tivoo_afe_flow_init(flow,1,sink,NULL);
    controls=xQueueCreate(4,sizeof(gate_control_t));
    if (!strncmp(argv[1],"gate",4)) {
        gate_mode=true; gate_cross=!strcmp(argv[1],"gate_cross");
        capture_valid=true;
        run(feed_task,2);
        run(fetch_task,2);
        assert(gate_requested && starts==1 && reset_vad_count==1);
        assert(start_index==epoch_first+(gate_cross?80:0) && pcm_count==(gate_cross?240:320));
        vQueueDelete(controls);
        return 0;
    }
    // Continuous capture failure before the first valid feed.
    run(feed_task,8);
    run(fetch_task,15);
    assert(!capability && !feed_count && !fetch_count && atomic_load(&rx_gaps)==8);
    assert(initial_report);
    capture_valid=true;
    run(feed_task,2);
    assert(feed_count==1 && !capability);
    run(fetch_task,1);
    assert(fetch_count==1 && capability);
    capture_valid=false;
    run(feed_task,1);
    assert(atomic_load(&reset_requested));
    atomic_store(&feed_paused,true); // feed owner has acknowledged the existing pause handshake
    if (!strcmp(argv[1],"buffer_fail")) reset_buffer_result=-1;
    if (!strcmp(argv[1],"vad_fail")) reset_vad_result=-1;
    run(fetch_task,1);
    assert(!capability && gaps==1 && reset_buffer_count==1);
    if (strcmp(argv[1],"recover")) {
        assert(atomic_load(&fatal) && !tivoo_s3_afe_control(TIVOO_AFE_GATE_OPEN,0));
        assert(buffer_report==!strcmp(argv[1],"buffer_fail"));
        assert(vad_report==!strcmp(argv[1],"vad_fail"));
        run(feed_task,1);
        assert(stop_monitor);
    } else {
        assert(!atomic_load(&fatal) && reset_vad_count==1 && !atomic_load(&reset_requested));
        capture_valid=true;
        run(feed_task,2);
        assert(!capability && feed_count==2);
        run(fetch_task,1);
        assert(capability && fetch_count==2);
    }
    vQueueDelete(controls);
    return 0;
}
