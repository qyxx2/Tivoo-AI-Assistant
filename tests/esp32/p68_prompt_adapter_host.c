/* Existing real 12-slot driver boundary, not a hand-built prompt completion. */
#include <stdint.h>
static void observe_tx(const uint32_t *slots);
#define P68_DMA_TX_OBSERVER observe_tx
#define main dma_recovery_test_main
#include "p68_dma_host.c"
#undef main
#include "s3_afe.c"
#include "audio_resource.h"
#include "audio_playback.h"
#include "diagnostics.h"
#include "cJSON.h"

static unsigned transmitted, starts, gates, ends, random_choice, marker_length;
static bool verifying, marker_finished;
static uint32_t connection=1;
static uint64_t gate_index, observed_end;
static int prompt_offset;
static unsigned prompt_tail_samples;
static unsigned speech_frames, speech_end, speech_samples;
static char session[37], first_session[37];
static tivoo_afe_flow_t state;

static void observe_tx(const uint32_t *slots)
{
    for(unsigned i=0;i<160;i++) {
        assert(slots[2*i]==slots[2*i+1]);
        int16_t sample=(int16_t)(slots[2*i]>>16);
        if(!verifying) continue;
        if(!transmitted && !sample) continue;
        if(transmitted==marker_length) {
            assert(sample==0); marker_finished=true; continue;
        }
        int expected=(transmitted%2)?-(int)(transmitted+1):(int)(transmitted+1);
        assert(sample==expected);
        ++transmitted;
        if(transmitted==marker_length)
            observed_end=(tivoo_audio_output_clock_blocks()+2)*80; // EOF + FIFO safety block
    }
}
size_t heap_caps_get_largest_free_block(unsigned caps) {(void)caps;return 0;}
void esp_fill_random(void *ptr,size_t n) {static unsigned seq;memset(ptr,++seq,n);}
uint32_t esp_random(void) {return random_choice;}
esp_err_t tivoo_audio_playback_init(void) {return ESP_OK;}
uint32_t tivoo_diagnostics_local_wake_generation(void) {return connection;}
void tivoo_log_write(esp_log_level_t l,const char *m,const char *f,...) {(void)l;(void)m;(void)f;}
bool tivoo_diagnostics_send_mic(uint32_t epoch,uint8_t type,const void *ptr,size_t n)
{
    assert(epoch==connection);
    assert(type!=0x32); // short prompt never emits ordinary AUDIO_STATE
    if(type==TVIO_TYPE_MIC_PCM) {
        assert(n==640);
        const int16_t *pcm=ptr;
        for(unsigned i=0;i<320;i++) {
            unsigned k=speech_frames*320+i;
            assert(pcm[i]==(k<443?(int16_t)(k+1):0));
        }
        ++speech_frames;
        return true;
    }
    cJSON *o=cJSON_ParseWithLength(ptr,n);assert(o);
    const char *id=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o,"session_id"));
    assert(id && strlen(id)==36);
    if(type==TVIO_TYPE_MIC_SESSION_START) {
        ++starts;strcpy(session,id);
    } else if(type==TVIO_TYPE_COMMAND_GATE) {
        assert(strcmp(id,session)==0 && state.gate_open);
        assert(tivoo_audio_resource_test_silent());
        assert(strcmp(cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o,"prompt_result")),"completed")==0);
        ++gates;gate_index=state.gate;
        assert(gate_index==(uint64_t)((int64_t)observed_end+prompt_tail_samples+prompt_offset));
        assert(tivoo_audio_output_clock_blocks()*80>=observed_end+prompt_tail_samples);
    } else if(type==TVIO_TYPE_MIC_SESSION_END) ++ends;
    else if(type==TVIO_TYPE_MIC_ACTIVITY &&
            strcmp(cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o,"state")),"speech_end")==0) {
        ++speech_end;
        speech_samples=cJSON_GetObjectItemCaseSensitive(o,"pcm_samples")->valueint;
    }
    cJSON_Delete(o);
    return true;
}

static void pump(void)
{
    step();
    if(tivoo_audio_capture_next(&frame)==ESP_OK && !frame.gap) {
        // Fake one 160-sample fetch lag behind the real ADC time axis.
        state.next=frame.first_sample-160;
    }
    tivoo_s3_local_turn_tick();
}

static void wake(void)
{
    tivoo_s3_local_turn_event(NULL,&(tivoo_afe_event_t){.type=TIVOO_AFE_WAKE,.word=1});
}

static void msg(bool followup)
{
    char body[80];
    int n=snprintf(body,sizeof(body),"{\"session_id\":\"%s\"}",session);
    if(followup) tivoo_s3_local_turn_followup_message((const uint8_t*)body,n);
    else tivoo_s3_local_turn_ready_message((const uint8_t*)body,n);
}

static void finish_command(void)
{
    msg(false);tivoo_s3_local_turn_tick();
    // First speech crosses the actual gate; recover its legal tail without
    // transmitting pre-gate samples. Then two full fetches and padded END.
    int16_t audio[160];
    uint64_t first=gate_index-37;
    state.next=first;
    for(unsigned j=0;j<3;j++) {
        for(unsigned i=0;i<160;i++) audio[i]=(int16_t)((int64_t)(first+j*160+i)-(int64_t)gate_index+1);
        tivoo_afe_flow_frame(&state,first+j*160,audio,160,j<2,j!=0,0,1,1,1,0);
    }
    assert(speech_frames==2 && speech_end==1 && speech_samples==640);
}
static void expect_prompt(unsigned samples)
{
    marker_length=samples;transmitted=0;marker_finished=false;verifying=true;
}
static void run_until_gate(unsigned target)
{
    for(unsigned i=0;i<300 && gates<target;i++) pump();
    assert(gates==target && transmitted==marker_length && marker_finished);
    verifying=false;
}
int main(int argc,char **argv)
{
    assert(argc==2);
    int offset=!strcmp(argv[1],"negative")?-37:37;
    unsigned tail=121;
    prompt_tail_samples=tail;prompt_offset=offset;
    assert(tivoo_audio_capture_start()==ESP_OK);
    valid_frame();
    assert(tivoo_audio_resource_init()==ESP_OK);
    assert(tivoo_s3_local_turn_init(false,true,tail,offset)==ESP_OK);
    flow=&state;word_count=1;words[0]="wake";
    tivoo_afe_flow_init(flow,1,tivoo_s3_local_turn_event,NULL);
    atomic_store(&usable,true);atomic_store(&streaming,true);
    epoch_first=frame.first_sample;
    state.have_next=true;state.next=frame.first_sample;
    random_choice=!strcmp(argv[1],"ready2")?1:!strcmp(argv[1],"ready3")?2:0;
    const unsigned lengths[]={23701,23892,26627};
    expect_prompt(lengths[random_choice]);
    wake();assert(starts==1 && !gates && !state.gate_open && state.prompt);
    assert(!tivoo_audio_resource_test_silent());
    assert(!tivoo_audio_resource_prompt_begin());
    if(!strcmp(argv[1],"late")) {
        // Fill the queue through the full asset, then withhold adapter poll
        // while DMA and the enhanced cursor advance past the mapped boundary.
        for(unsigned i=0;i<130;i++) pump();
        for(unsigned i=0;i<100;i++) {
            step(); assert(tivoo_audio_capture_next(&frame)==ESP_OK);
            state.next=frame.first_sample-160;
        }
        tivoo_s3_local_turn_tick();
        assert(!gates && ends==1 && !state.gate_open && tivoo_audio_resource_test_silent());
        assert(transmitted==marker_length);
        return 0;
    }
    if(!strcmp(argv[1],"fault") || !strcmp(argv[1],"timeout")) {
        verifying=false;
        for(unsigned i=0;i<20;i++) pump();
        if(!strcmp(argv[1],"fault")) {skip_tx=true;step();step();}
        else {
            // No trusted progress for the entire watchdog; keep the real
            // capture from independently initiating recovery until after tick.
            ticks+=1001;tivoo_s3_local_turn_tick();
        }
        for(unsigned i=0;i<80;i++) pump();
        assert(!gates && ends==1 && !state.gate_open);
        assert(creates==2 && tivoo_audio_resource_test_silent());
        state.next=frame.first_sample;
        expect_prompt(23892);wake();run_until_gate(1);
        assert(starts==2);
        return 0;
    }
    if(!strcmp(argv[1],"stop") || !strcmp(argv[1],"epoch")) {
        verifying=false;
        for(unsigned i=0;i<20;i++) pump();
        if(!strcmp(argv[1],"stop")) tivoo_s3_local_turn_stop(session,"test");
        else ++connection;
        for(unsigned i=0;i<100;i++) pump();
        assert(!gates && !state.gate_open && tivoo_audio_resource_test_silent());
        state.next=frame.first_sample;
        expect_prompt(23892);wake();run_until_gate(1);
        assert(starts==2);
        return 0;
    }
    run_until_gate(1);
    assert((gate_index-offset-tail)%80==0);
    assert(gate_index%80!=0);
    if(!strcmp(argv[1],"followup")) {
        strcpy(first_session,session);
        finish_command();msg(true);
        expect_prompt(15360);tivoo_s3_local_turn_tick();
        assert(starts==2 && strcmp(first_session,session)!=0);
        run_until_gate(2);
    }
    return 0;
}
