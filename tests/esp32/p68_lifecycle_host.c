#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
#include <time.h>
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
static unsigned starts, gates, retired, pcm_frames, ends, ack_states;
static char ack_state[16], ack_source[16], ack_audio[37];
static char sid[37], parent[37], retired_id[37];
static const char playback[]="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const int16_t ready_01_start[1]={0}, ready_01_end[1]={0}, ready_02_start[1]={0}, ready_02_end[1]={0};
const int16_t ready_03_start[1]={0}, ready_03_end[1]={0}, followup_01_start[1]={0}, followup_01_end[1]={0};
const int16_t local_success_01_start[2]={1,0}, local_success_01_end[1]={0};
const int16_t local_failure_01_start[2]={2,0}, local_failure_01_end[1]={0};
void *heap_caps_calloc(size_t n,size_t s,unsigned caps) { (void)caps; return calloc(n,s); }
void esp_fill_random(void *p,size_t n) { static unsigned v; memset(p,++v,n); }
uint32_t esp_random(void) { return 0; }
int64_t esp_timer_get_time(void) { return (int64_t)ms*1000; }
/* In the normal-end case, use the actual host diagnostic parser and
 * sender on a socket pair; other cases retain the deterministic wire seam. */
static int diag_socket[2] = {-1,-1};
static uint32_t tx_seq;
uint32_t host_diag_local_wake_generation(void);
bool host_diag_send_mic(uint32_t,uint8_t,const void *,size_t);
static void read_exact(void *data,size_t n) {
    uint8_t *p=data;
    while(n) {
        ssize_t got=read(diag_socket[1],p,n); assert(got>0);
        p+=got;n-=(size_t)got;
    }
}
static uint32_t le32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1]<<8) |
        ((uint32_t)p[2]<<16) | ((uint32_t)p[3]<<24);
}
static void put32(uint8_t *p,uint32_t v) {
    for(unsigned i=0;i<4;i++) p[i]=(uint8_t)(v>>(8*i));
}
static void read_wire(uint8_t type,const void *payload,size_t size) {
    uint8_t header[16], body[4096];read_exact(header,sizeof(header));
    assert(!memcmp(header,"TVIO",4) && header[4]==1 && header[5]==type);
    size_t n=le32(header+8);assert(n<=sizeof(body) && le32(header+12)==tx_seq++);
    read_exact(body,n);
    if(payload) assert(n==size && !memcmp(body,payload,n));
}
static void receive_wire(uint8_t type,uint32_t seq,const char *payload) {
    uint8_t frame[256]={'T','V','I','O',1,type,0,0};
    size_t n=strlen(payload);assert(n<=sizeof(frame)-16);
    put32(frame+8,n);put32(frame+12,seq);memcpy(frame+16,payload,n);
    assert(tivoo_diagnostics_client_data(diag_socket[0],frame,16+n));
}
static void start_wire(void) {
    assert(socketpair(AF_UNIX,SOCK_STREAM,0,diag_socket)==0);
    struct timeval timeout={2,0};
    assert(setsockopt(diag_socket[1],SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout))==0);
    tivoo_diagnostics_set_mic_capture_stop_handler(tivoo_s3_local_turn_stop);
    assert(tivoo_diagnostics_start()==ESP_OK);
    tivoo_diagnostics_enable_local_wake();
    tivoo_diagnostics_client_connected(diag_socket[0]);
    read_wire(1,NULL,0);
    receive_wire(2,0,"{\"accepted\":true,\"capabilities\":[\"local_wake_stt_v1\"]}");
    assert(host_diag_local_wake_generation()==connection);
}
static void stop_wire(const char *id,uint32_t seq) {
    char body[128];snprintf(body,sizeof(body),"{\"session_id\":\"%s\",\"reason\":\"conversation_complete\"}",id);
    receive_wire(0x23,seq,body);
}
static void close_wire(void) {
    tivoo_diagnostics_stop();close(diag_socket[0]);close(diag_socket[1]);
}
uint32_t tivoo_diagnostics_local_wake_generation(void) { return connection; }
bool tivoo_diagnostics_send_mic(uint32_t e,uint8_t type,const void *data,size_t n)
{
    assert(e==connection);
    if(wire_blocked) return false;
    if(diag_socket[0]>=0) {
        /* Synchronous test consumer drains each message so this check is
         * independent of host thread scheduling and queue backpressure. */
        const struct timespec pause={0,1000000};
        bool sent=false;
        for(unsigned i=0;i<100 && !sent;i++) {
            sent=host_diag_send_mic(e,type,data,n);
            if(!sent) nanosleep(&pause,NULL);
        }
        assert(sent);read_wire(type,data,n);
    }
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
    else if(type==TVIO_TYPE_AUDIO_STATE) {
        const char *state=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o,"state"));
        const char *source=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o,"source"));
        const char *audio=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o,"audio_id"));
        assert(state && source && audio);
        strcpy(ack_state,state); strcpy(ack_source,source); strcpy(ack_audio,audio); ++ack_states;
    } else if(type==TVIO_TYPE_MIC_SESSION_END) {
        assert(strcmp(id,sid)==0);
        const char *reason=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o,"reason"));
        assert(reason);
        ++ends;
    }
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
static bool ack(const char *id,const char *pid,const char *result) {
    char json[192]; int n=snprintf(json,sizeof(json),
        "{\"session_id\":\"%s\",\"playback_id\":\"%s\",\"result\":\"%s\"}",id,pid,result);
    return tivoo_s3_local_turn_ack_message((const uint8_t *)json,(size_t)n);
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
    if(argc==2 && strcmp(argv[1],"ack")==0) {
        assert(tivoo_s3_local_turn_init(true,false,0,0)==ESP_OK);
        wake(); command();
        assert(!ack("00000000-0000-4000-8000-000000000000",playback,"success"));
        assert(!ack(sid,"bad","success"));
        assert(!ack(sid,playback,"other"));
        prompt_mode=true;
        assert(ack(sid,playback,"success"));
        assert(!ack(sid,playback,"success"));
        tivoo_s3_local_turn_tick();
        assert(ack_states>=2 && !strcmp(ack_source,"local_ack") && !strcmp(ack_audio,playback));
        assert(!strcmp(ack_state,"completed"));
        assert(!ack(sid,"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","failure"));
        return 0;
    }
    if(argc==2 && strcmp(argv[1],"normal_end")==0) {
        start_wire();
        assert(tivoo_s3_local_turn_init(true,false,0,0)==ESP_OK);
        wake(); command();
        char first[37]; strcpy(first,sid);
        assert(tivoo_s3_local_turn_bind_playback(first,playback));
        tivoo_s3_local_turn_playback_finished(first,playback,connection,true);
        stop_wire(first,1);
        tivoo_s3_local_turn_tick(); tivoo_s3_local_turn_tick();
        assert(ends==1 && !gate_open && !strcmp(retired_id,first));
        wake(); assert(starts==2 && gates==2 && strcmp(sid,first));
        stop_wire(first,2);
        tivoo_s3_local_turn_tick();
        assert(ends==1 && gate_open);
        close_wire();
        return 0;
    }
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
