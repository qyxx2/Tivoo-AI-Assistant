#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include "s3_local_turn.h"
#include "diagnostics.h"
#include "audio_output_manager.h"
#include "audio_resource.h"
#include "cJSON.h"

static uint32_t connection=1;
static uint64_t ms=100;
static bool drained=true, gate_open, wire_blocked;
static bool prompt_mode, prompt_failed, prompt_owned, output_available=true;
static unsigned recoveries, discards;
static uint32_t prompt_owner;
void tivoo_test_log(const char *tag,const char *fmt,...) {
    (void)tag;
    if(strncmp(fmt,"turn_metrics ",13)) return;
    va_list args; va_start(args,fmt); vprintf(fmt,args); va_end(args); puts("");
}
static unsigned starts, gates, retired, pcm_frames, ends;
static char sid[37], parent[37], retired_id[37];
static const char playback[]="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const int16_t ready_01_start[1]={0}, ready_01_end[1]={0}, ready_02_start[1]={0}, ready_02_end[1]={0};
const int16_t ready_03_start[1]={0}, ready_03_end[1]={0}, followup_01_start[1]={0}, followup_01_end[1]={0};
void *heap_caps_calloc(size_t n,size_t s,unsigned caps) { (void)caps; return calloc(n,s); }
void esp_fill_random(void *p,size_t n) { static unsigned v; memset(p,++v,n); }
uint32_t esp_random(void) { return 0; }
int64_t esp_timer_get_time(void) { return (int64_t)ms*1000; }
uint32_t tivoo_diagnostics_local_wake_generation(void) { return connection; }
bool tivoo_diagnostics_send_mic(uint32_t e,uint8_t type,const void *data,size_t n)
{
    assert(e==connection);
    if(wire_blocked) return false;
    if(type==TVIO_TYPE_MIC_PCM) { assert(n==640); ++pcm_frames; return true; }
    cJSON *o=cJSON_ParseWithLength(data,n);
    assert(o);
    const char *id=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o,"session_id"));
    assert(id && strlen(id)==36);
    if(type==TVIO_TYPE_MIC_SESSION_START) {
        ++starts; strcpy(sid,id);
        const char *p=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o,"parent_session_id"));
        if(p) strcpy(parent,p); else parent[0]=0;
        const char *source=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o,"trigger_source"));
        assert(strcmp(source,p?"local_followup":"local_wake")==0);
        assert((cJSON_GetObjectItemCaseSensitive(o,"wake_word_phrase")!=NULL)==(p==NULL));
    } else if(type==TVIO_TYPE_COMMAND_GATE) { assert(drained && gate_open); ++gates; }
    else if(type==TVIO_TYPE_MIC_SESSION_END) { ++ends; }
    cJSON_Delete(o);
    return true;
}
const char *tivoo_s3_afe_wake_word(int n) { return n==1?"wake":NULL; }
bool tivoo_s3_afe_open_test_gate(void) { assert(drained); gate_open=true; return true; }
void tivoo_s3_afe_close_local_gate(void) { gate_open=false; }
void tivoo_s3_afe_begin_prompt(void) { assert(prompt_mode); }
bool tivoo_s3_afe_finish_prompt(uint64_t b,bool o) { (void)b; assert(prompt_mode); gate_open=o; return o; }
bool tivoo_audio_resource_prompt_ready(unsigned tail) { (void)tail; return prompt_mode ? output_available && !prompt_owned : drained; }
void tivoo_audio_resource_retire_local(const char *id,uint32_t e)
{ assert(e); strcpy(retired_id,id); ++retired; }
uint32_t tivoo_audio_resource_prompt_begin(void) { assert(prompt_mode && !prompt_owned); prompt_owned=true; prompt_failed=false; return ++prompt_owner; }
bool tivoo_audio_resource_prompt_end(uint32_t g) { assert(prompt_mode && g==prompt_owner && !prompt_failed && drained); prompt_owned=false; return true; }
bool tivoo_audio_resource_prompt_discard(uint32_t g) { assert(prompt_mode && g==prompt_owner && prompt_failed); prompt_owned=false; ++discards; return true; }
bool tivoo_audio_output_failed(uint32_t g) { return prompt_failed && g==prompt_owner; }
bool tivoo_audio_output_available(void) {return output_available;}
uint32_t tivoo_audio_output_fault_serial(void) {return recoveries;}
uint64_t tivoo_audio_output_recovery_boundary(void) {return ms*16;}
void tivoo_audio_output_request_recovery(void) { ++recoveries; prompt_failed=true; output_available=false; }
size_t tivoo_audio_output_try_write(uint32_t g,const int16_t *p,size_t n)
{ (void)p; assert(prompt_mode && g==prompt_owner); return n; }
void tivoo_audio_output_finish_input(uint32_t g) { assert(prompt_mode && g==prompt_owner); }
void tivoo_audio_output_stop(uint32_t g) { assert(prompt_mode && g==prompt_owner); }
bool tivoo_audio_output_prompt_drain(uint32_t g,uint64_t *e,uint64_t *c)
{ assert(prompt_mode && g==prompt_owner); *e=*c=ms*16; return drained && !prompt_failed; }

static void wake(void) {
    ++ms;
    tivoo_s3_local_turn_event(NULL,&(tivoo_afe_event_t){.type=TIVOO_AFE_WAKE,.word=1});
}
static void message(bool followup,const char *id) {
    char json[80]; int n=snprintf(json,sizeof(json),"{\"session_id\":\"%s\"}",id);
    if(followup) tivoo_s3_local_turn_followup_message((const uint8_t *)json,n);
    else tivoo_s3_local_turn_ready_message((const uint8_t *)json,n);
}
static void command(void) {
    int16_t pcm[320]={0};
    message(false,sid); tivoo_s3_local_turn_tick();
    ++ms;
    tivoo_s3_local_turn_event(NULL,&(tivoo_afe_event_t){.type=TIVOO_AFE_START,.index=0});
    tivoo_s3_local_turn_event(NULL,&(tivoo_afe_event_t){.type=TIVOO_AFE_PCM,.index=0,.pcm=pcm,.count=320});
    tivoo_s3_local_turn_event(NULL,&(tivoo_afe_event_t){.type=TIVOO_AFE_END,.index=320});
}
int main(int argc, char **argv) {
    if(argc==2 && strcmp(argv[1],"metrics")==0) {
        assert(tivoo_s3_local_turn_init(true,false,0,0)==ESP_OK);
        wake(); ms+=100; message(false,sid); tivoo_s3_local_turn_tick();
        command(); tivoo_s3_local_turn_tick(); message(false,sid); tivoo_s3_local_turn_tick();
        wire_blocked=true; wake(); ms+=1001; tivoo_s3_local_turn_tick();
        wire_blocked=false; tivoo_s3_local_turn_tick();
        wake(); ms+=1001; tivoo_s3_local_turn_tick(); tivoo_s3_local_turn_tick();
        ++connection; tivoo_s3_local_turn_tick();
        return 0;
    }
    if(argc==2 && strcmp(argv[1],"stale_fault")==0) {
        assert(tivoo_s3_local_turn_init(true,false,0,0)==ESP_OK);
        wake(); command();
        assert(tivoo_s3_local_turn_bind_playback(sid,playback));
        ++recoveries; /* Already recovered, but fetch has not ticked yet. */
        assert(!tivoo_s3_local_turn_bind_playback(sid,playback));
        return 0;
    }
    if(argc==2) {
        prompt_mode=true; drained=false;
        assert(tivoo_s3_local_turn_init(false,true,0,0)==ESP_OK);
        wake(); assert(starts==1 && gates==0 && prompt_owned);
        ms+=5001; tivoo_s3_local_turn_tick(); tivoo_s3_local_turn_tick();
        assert(recoveries==1 && discards==1 && !prompt_owned && !gate_open && !gates);
        wake(); assert(starts==1 && !gates);
        output_available=true; drained=true;
        wake(); tivoo_s3_local_turn_tick();
        assert(starts==2 && gates==1 && !prompt_owned && prompt_owner==2);
        return 0;
    }
    assert(tivoo_s3_local_turn_init(true,false,0,0)==ESP_OK);
    wake(); assert(starts==1 && gates==1);
    char first[37]; strcpy(first,sid);
    command(); assert(pcm_frames==1);
    assert(tivoo_s3_local_turn_bind_playback(first,playback));
    message(true,first); tivoo_s3_local_turn_tick(); assert(starts==1);
    /* New true wake preempts active reply but must await output drain. */
    drained=false; wake();
    assert(starts==2 && gates==1 && !gate_open && retired && strcmp(retired_id,first)==0);
    assert(!tivoo_s3_local_turn_bind_playback(first,playback));
    message(true,first); message(false,first);
    tivoo_s3_local_turn_playback_finished(first,playback,connection,true);
    wake(); assert(starts==3 && gates==1);
    drained=true; tivoo_s3_local_turn_tick(); assert(gates==2);
    command(); assert(pcm_frames==2);
    char third[37]; strcpy(third,sid);
    assert(tivoo_s3_local_turn_bind_playback(third,playback));
    tivoo_s3_local_turn_playback_finished(third,playback,connection+1,true);
    message(true,third); tivoo_s3_local_turn_tick(); assert(starts==3);
    tivoo_s3_local_turn_playback_finished(third,playback,connection,true);
    message(true,third); message(true,third);
    ++ms; tivoo_s3_local_turn_tick();
    assert(starts==4 && gates==3 && strcmp(parent,third)==0 && strcmp(sid,third)!=0);
    message(true,third); tivoo_s3_local_turn_tick(); assert(starts==4);
    message(false,sid); tivoo_s3_local_turn_tick();
    ms+=3999; tivoo_s3_local_turn_tick(); assert(ends==0);
    ms+=2; tivoo_s3_local_turn_tick(); assert(ends==1 && !gate_open);
    wake(); assert(starts==5);
    ++connection; tivoo_s3_local_turn_tick(); assert(!gate_open);
    assert(!tivoo_s3_local_turn_bind_playback(sid,playback));
    return 0;
}
