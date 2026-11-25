/* Real audio_resource.c worker; fake only external task, HTTP, output and
 * diagnostic boundaries. Execute scheduled worker synchronously with a
 * deterministic interleaving during its HTTP read. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <unistd.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <time.h>
#include <stdarg.h>
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_http_client.h"
#include "audio_resource.h"
#include "audio_output_manager.h"
#include "audio_playback.h"
#include "diagnostics.h"
#include "cJSON.h"

static const char sid1[]="11111111-1111-4111-8111-111111111111";
static const char sid2[]="22222222-2222-4222-8222-222222222222";
static const char pid1[]="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
static const char pid2[]="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
static const char req1[]="cccccccc-cccc-4ccc-8ccc-cccccccccccc";
static const char *scenario, *current_sid=sid1;
static uint32_t epoch=1, owner;
static unsigned terminals, terminal_attempts, invalidations, opened, closed, stops, recoveries, replies, reads, status_fetches;
static atomic_llong clock_us;
static pthread_t feeder;
static bool feeder_created;
static _Thread_local bool is_feeder;
static atomic_bool feeder_waiting;
static atomic_bool producer_space_waiting, full_gate_passed;
static atomic_uint space_wakes;
_Thread_local unsigned p68_critical_depth;
static unsigned event_roles, diagnostic_warnings;
static unsigned http_read_timeout_ms;
SemaphoreHandle_t xSemaphoreCreateBinaryStatic(StaticSemaphore_t *s) {
    assert(!pthread_mutex_init(&s->mutex,NULL));assert(!pthread_cond_init(&s->ready,NULL));
    s->pending=0;s->role=++event_roles;return s;
}
SemaphoreHandle_t xSemaphoreCreateMutex(void) {
    static StaticSemaphore_t lock={PTHREAD_MUTEX_INITIALIZER,PTHREAD_COND_INITIALIZER,1,0};return &lock;
}
BaseType_t xSemaphoreGive(SemaphoreHandle_t s) {
    assert(!p68_critical_depth);pthread_mutex_lock(&s->mutex);s->pending=1;
    pthread_cond_signal(&s->ready);pthread_mutex_unlock(&s->mutex);return pdTRUE;
}
BaseType_t xSemaphoreTake(SemaphoreHandle_t t,TickType_t wait) {
    assert(!p68_critical_depth);
    struct timespec end;timespec_get(&end,TIME_UTC);
    end.tv_nsec+=(long)wait*1000000;
    end.tv_sec+=end.tv_nsec/1000000000;end.tv_nsec%=1000000000;
    pthread_mutex_lock(&t->mutex);
    if(is_feeder && !t->pending) atomic_store(&feeder_waiting,true);
    bool full_wait=!is_feeder && t->role==2 && !t->pending && wait;
    if(full_wait) atomic_store(&producer_space_waiting,true);
    while(!t->pending && wait) if(pthread_cond_timedwait(&t->ready,&t->mutex,&end)) break;
    if(is_feeder) atomic_store(&feeder_waiting,false);
    if(full_wait) {
        atomic_store(&producer_space_waiting,false);
        if(t->pending) atomic_fetch_add(&space_wakes,1);
    }
    unsigned n=t->pending;t->pending=0;pthread_mutex_unlock(&t->mutex);
    return n ? pdTRUE : pdFALSE;
}
static atomic_size_t pcm_received;
static bool pending_case(void) {return !strncmp(scenario,"pending",7);}
static bool quarantine, input_finished, completed, http_eof;
static int sockets[2];
static void (*task)(void *);
static void *task_arg;
static esp_http_client_config_t config;
static char terminal_state[16];
static bool format_failure(void) {return !strcmp(scenario,"pcm_mismatch") || !strcmp(scenario,"pcm_unsupported");}
static const char *request_mime(void) {
    if(!strcmp(scenario,"pcm_unsupported")) return "audio/x-tivoo-pcm-s16le-16000-mono";
    if(!strncmp(scenario,"pcm32",5)) return TIVOO_PCM_MIME;
    if(!strncmp(scenario,"pcm",3)) return TIVOO_PCM_24K_MIME;
    return "audio/mpeg";
}
static void play(const char *sid,const char *pid) {
    char json[512];
    int n=snprintf(json,sizeof(json),"{\"session_id\":\"%s\",\"playback_id\":\"%s\",\"url\":\"http://test/audio\",\"mime_type\":\"%s\"}",sid,pid,request_mime());
    assert(tivoo_audio_resource_handle_message(0x30,(uint8_t *)json,n));
}
static void stop(const char *sid,const char *pid) {
    char json[256];
    int n=snprintf(json,sizeof(json),"{\"session_id\":\"%s\",\"expected_audio_id\":\"%s\",\"request_id\":\"%s\",\"reason\":\"test\"}",sid,pid,req1);
    assert(tivoo_audio_resource_handle_message(0x31,(uint8_t *)json,n));
}
int64_t esp_timer_get_time(void) {return clock_us;}
void vTaskDelay(unsigned n) {assert(n);if(!is_feeder)clock_us+=5000;sched_yield();}
void vTaskDelete(void *p) {(void)p;}
static void (*feeder_fn)(void *);
static void *feeder_start(void *arg) {is_feeder=true;feeder_fn(arg);return NULL;}
BaseType_t xTaskCreatePinnedToCore(void (*f)(void *),const char *name,unsigned stack,void *arg,unsigned prio,void *out,int core) {
    (void)stack;(void)prio;(void)out;(void)core;
    if(!strcmp(name,"pcm_feed")) {assert(!feeder_created);feeder_created=true;feeder_fn=f;assert(!pthread_create(&feeder,NULL,feeder_start,arg));return pdPASS;}
    assert(!task);task=f;task_arg=arg;return pdPASS;
}
size_t heap_caps_get_free_size(unsigned c) {(void)c;return 0;}
size_t heap_caps_get_largest_free_block(unsigned c) {(void)c;return 0;}
void tivoo_log_write(esp_log_level_t level,const char *module,const char *format,...) {
    assert(level==ESP_LOG_WARN && !strcmp(module,"audio_resource"));
    char message[385];va_list args;va_start(args,format);vsnprintf(message,sizeof(message),format,args);va_end(args);
    assert(strstr(message,"PCM supply") && strstr(message,"missing_samples=160"));++diagnostic_warnings;
}
void tivoo_report_error(const char *c,const char *m,const char *s) {(void)c;(void)m;(void)s;assert(0);}
uint32_t tivoo_diagnostics_mic_generation(void) {return epoch;}
void tivoo_diagnostics_invalidate_mic(uint32_t e) {if(e && e==epoch){++invalidations;epoch=0;}}
bool tivoo_diagnostics_send_mic(uint32_t e,uint8_t type,const void *p,size_t n) {
    assert(e==epoch && type==0x32);
    cJSON *o=cJSON_ParseWithLength(p,n);assert(o);
    const char *state=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o,"state"));
    const char *id=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o,"audio_id"));
    const char *sid=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o,"session_id"));
    assert(!strcmp(sid,!strcmp(id,pid1)?sid1:sid2));
    bool terminal=strcmp(state,"buffering")&&strcmp(state,"playing");
    if(terminal) {
        ++terminal_attempts;
        assert(!owner);
        if(!strcmp(scenario,"permanent") || !strcmp(scenario,"pending_lost") ||
            (!strcmp(scenario,"temporary") && terminal_attempts<4)) {cJSON_Delete(o);return false;}
        if(!strcmp(scenario,"old_epoch")) {++epoch;cJSON_Delete(o);return false;}
        if(!strcmp(scenario,"pending") && !strcmp(id,pid1)) {
            assert(!strcmp(state,"stopped") && !tivoo_audio_resource_test_silent());
        } else if(!strcmp(scenario,"matching_stop") || !strcmp(scenario,"pcm32_stop") || !strcmp(scenario,"pcm32_wait_stop") || !strcmp(scenario,"pcm32_full_stop")) {
            assert(!strcmp(state,"stopped") && tivoo_audio_resource_test_silent());
        } else if(!strcmp(scenario,"pcm32_error")) {
            const char *err=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o,"error_code"));
            assert(!strcmp(state,"failed") && err && !strcmp(err,"audio_http_failed"));
        } else if(format_failure()) {
            const char *err=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o,"error_code"));
            assert(!strcmp(state,"failed") && err);
            assert(!strcmp(err,!strcmp(scenario,"pcm_mismatch") ? "audio_content_type_mismatch" : "audio_format_unsupported"));
            assert(!reads && tivoo_audio_resource_test_silent());
        } else if(!strcmp(scenario,"timeout")) {
            assert(!strcmp(state,"failed") && quarantine);
        } else {
            assert(!strcmp(state,"completed") && tivoo_audio_resource_test_silent());
        }
        strcpy(terminal_state,state);++terminals;
    }
    cJSON_Delete(o);return true;
}
bool tivoo_s3_local_turn_bind_playback(const char *sid,const char *pid) {(void)pid;return !strcmp(sid,current_sid);}
void tivoo_s3_local_turn_playback_finished(const char *sid,const char *pid,uint32_t e,bool ok) {
    (void)pid;assert(!owner);
    if(e==epoch && !strcmp(sid,current_sid)){++replies;completed=ok;}
}
bool tivoo_device_status_set_audio_resource(bool f,const char *p) {assert(f==(p!=NULL));if(f)++status_fetches;return true;}
bool tivoo_audio_output_available(void) {return !quarantine;}
bool tivoo_audio_output_begin(uint32_t g) {assert(!owner);if(quarantine)return false;owner=g;input_finished=false;return true;}
bool tivoo_audio_output_begin_prompt(uint32_t g) {return tivoo_audio_output_begin(g);}
void tivoo_audio_output_stop(uint32_t g) {if(owner==g){++stops;input_finished=true;}}
void tivoo_audio_output_finish_input(uint32_t g) {assert(g==owner);input_finished=true;}
bool tivoo_audio_output_drained(uint32_t g) {assert(g==owner);return input_finished && strcmp(scenario,"timeout");}
bool tivoo_audio_output_failed(uint32_t g) {(void)g;return quarantine;}
bool tivoo_audio_output_progress(uint32_t g,tivoo_output_progress_t *p) {
    assert(g==owner);*p=(tivoo_output_progress_t){0};
    if(!strcmp(scenario,"pcm32_paced") && atomic_load(&pcm_received)>=26624) {
        p->missing_samples=160;p->rebuffer_count=1;
    }
    return true;
}
void tivoo_audio_output_request_recovery(void) {++recoveries;quarantine=true;}
void tivoo_audio_output_end(uint32_t g) {assert(g==owner && quarantine);owner=0;}
bool tivoo_audio_output_release_drained(uint32_t g,uint64_t *end) {
    if(!tivoo_audio_output_drained(g))return false;
    *end=100;owner=0;return true;
}
uint64_t tivoo_audio_output_recovery_boundary(void) {return 0;}
bool tivoo_audio_output_prompt_drain(uint32_t g,uint64_t *end,uint64_t *c) {(void)g;*end=100;*c=1000;return !quarantine;}
esp_err_t tivoo_audio_playback_init(void) {return ESP_OK;}
struct tivoo_audio_playback {bool pcm,ended;};
static struct tivoo_audio_playback decoder;
tivoo_audio_playback_t *tivoo_audio_playback_open(uint32_t g,uint32_t pcm_rate) {assert(g==owner);assert(pcm_rate==(!strncmp(scenario,"pcm24",5) ? 24000U : !strncmp(scenario,"pcm32",5) ? 32000U : 0U));decoder.pcm=decoder.ended=false;return &decoder;}
esp_err_t tivoo_audio_playback_feed(tivoo_audio_playback_t *p,uint8_t *d,size_t n,bool eof) {
    if(p->ended)return ESP_ERR_INVALID_STATE;
    if((!strcmp(scenario,"pcm32_full") || !strcmp(scenario,"pcm32_full_stop")) &&
       !atomic_exchange(&full_gate_passed,true)) {
        struct timespec start,now;timespec_get(&start,TIME_UTC);
        while(!atomic_load(&producer_space_waiting)) {
            sched_yield();timespec_get(&now,TIME_UTC);
            double elapsed=now.tv_sec-start.tv_sec+(now.tv_nsec-start.tv_nsec)/1e9;
            assert(elapsed<1 && "producer must block when receive ring is full");
        }
        if(!strcmp(scenario,"pcm32_full_stop")) {
            stop(sid1,pid1);return ESP_ERR_INVALID_STATE;
        }
    }
    if(!strncmp(scenario,"pcm32",5)) {
        size_t pos=atomic_load(&pcm_received);
        for(size_t i=0;i<n;i++) assert(d[i]==(uint8_t)(pos+i));
        atomic_fetch_add(&pcm_received,n);
    }
    p->ended=eof;if(n)p->pcm=true;return ESP_OK;
}
bool tivoo_audio_playback_has_pcm(const tivoo_audio_playback_t *p) {return p->pcm;}
void tivoo_audio_playback_close(tivoo_audio_playback_t *p) {(void)p;}
int esp_crt_bundle_attach(void *p) {(void)p;return 0;}
esp_http_client_handle_t esp_http_client_init(const esp_http_client_config_t *c) {
    assert(owner);config=*c;http_eof=false;++opened;assert(socketpair(AF_UNIX,SOCK_STREAM,0,sockets)==0);return &config;
}
int esp_http_client_open(esp_http_client_handle_t c,int n) {(void)c;(void)n;return ESP_OK;}
int esp_http_client_get_socket(esp_http_client_handle_t c) {(void)c;return sockets[0];}
int esp_http_client_set_timeout_ms(esp_http_client_handle_t c,int n) {(void)c;http_read_timeout_ms=n;return ESP_OK;}
int64_t esp_http_client_fetch_headers(esp_http_client_handle_t c) {
    (void)c;esp_http_client_event_t e={config.user_data,HTTP_EVENT_ON_HEADER,"Content-Type",(char *)(!strcmp(scenario,"pcm_mismatch") ? TIVOO_PCM_MIME : request_mime())};
    config.event_handler(&e);return 8;
}
bool esp_http_client_is_chunked_response(esp_http_client_handle_t c) {(void)c;return false;}
int esp_http_client_get_status_code(esp_http_client_handle_t c) {(void)c;return 200;}
int esp_http_client_read(esp_http_client_handle_t c,char *p,int n) {
    (void)c;assert(n>=8);memset(p,1,8);
    ++reads;
    if(!strncmp(scenario,"pcm32",5)) {
        if(!strcmp(scenario,"pcm32_fragments")) {
            /* Model IDF read(): a short delta waits until the socket read
             * deadline, even though these bytes have already arrived. */
            assert(http_read_timeout_ms<=100 && "partial PCM must reach the 160ms output queue before it drains");
            clock_us+=(int64_t)http_read_timeout_ms*1000;
            size_t pos=(reads-1U)*320;
            size_t count=pos<64000 ? 320 : 0;
            for(size_t i=0;i<count;i++) p[i]=(uint8_t)(pos+i);
            http_eof=pos+count>=64000;
            return (int)count;
        }
        if((!strcmp(scenario,"pcm32_paced") || !strcmp(scenario,"pcm32_wait_stop")) && reads==27) {
            struct timespec start,now;timespec_get(&start,TIME_UTC);
            while(atomic_load(&pcm_received)!=26624 || !atomic_load(&feeder_waiting)) {
                sched_yield();timespec_get(&now,TIME_UTC);
                double elapsed=now.tv_sec-start.tv_sec+(now.tv_nsec-start.tv_nsec)/1e9;
                assert(elapsed<1 && "feeder must block awaiting the next PCM delta");
            }
            if(!strcmp(scenario,"pcm32_wait_stop")) {stop(sid1,pid1);return -1;}
        }
        if(!strcmp(scenario,"pcm32_stop") && reads==2) {
            stop(sid1,pid1);
            return -1;
        }
        if(!strcmp(scenario,"pcm32_error") && reads==2) return -1;
        size_t size=(!strcmp(scenario,"pcm32_long") || !strcmp(scenario,"pcm32_stop") ||
            !strcmp(scenario,"pcm32_error") || !strcmp(scenario,"pcm32_full") ||
            !strcmp(scenario,"pcm32_full_stop")) ? 700000 :
            (!strcmp(scenario,"pcm32_paced") || !strcmp(scenario,"pcm32_wait_stop")) ? 70000 : 8;
        size_t pos=(reads-1U)*(size_t)n;
        size_t count=size>pos ? size-pos : 0;
        if(count>(size_t)n) count=n;
        for(size_t i=0;i<count;i++) p[i]=(uint8_t)(pos+i);
        http_eof=pos+count>=size;
        return (int)count;
    }
    if(!strcmp(scenario,"pcm24_full") || !strcmp(scenario,"pcm24_buffered")) {
        http_eof=true;
        if(reads==1) {memset(p,1,n);return n;}
        return !strcmp(scenario,"pcm24_full") ? 0 : 8;
    }
    if(!strcmp(scenario,"long_stream") && reads>1 && reads<=9) {
        clock_us+=1000000;
        return -ESP_ERR_HTTP_EAGAIN;
    }
    if(!strcmp(scenario,"matching_stop")) {
        stop(sid1,pid1);
        stop(sid1,pid1); /* duplicate stop */
        char byte;assert(recv(sockets[1],&byte,1,MSG_DONTWAIT)==0);
    } else if(pending_case() && opened==1) {
        tivoo_audio_resource_retire_local(sid1,epoch+1);
        char byte;assert(recv(sockets[1],&byte,1,MSG_DONTWAIT)<0);
        tivoo_audio_resource_retire_local(sid1,epoch);
        assert(recv(sockets[1],&byte,1,MSG_DONTWAIT)==0);
        current_sid=sid2;play(sid2,pid2);
        assert(opened==1 && !tivoo_audio_resource_test_silent());
        stop(sid1,pid2); /* wrong old UUID must not stop pending new play */
    } else if(pending_case()) {
        tivoo_audio_resource_retire_local(sid1,epoch);
        char byte;assert(recv(sockets[1],&byte,1,MSG_DONTWAIT)<0);
    }
    http_eof=strcmp(scenario,"long_stream") || reads>9;
    return 8;
}
bool esp_http_client_is_complete_data_received(esp_http_client_handle_t c) {(void)c;return http_eof;}
int esp_http_client_cleanup(esp_http_client_handle_t c) {(void)c;close(sockets[0]);close(sockets[1]);++closed;return ESP_OK;}
int main(int argc,char **argv) {
    assert(argc==2);scenario=argv[1];assert(tivoo_audio_resource_init()==ESP_OK);
    play(sid2,pid2);assert(!task); /* stale UUID */
    play(sid1,pid1);assert(task && !tivoo_audio_resource_test_silent());
    task(task_arg);
    if(feeder_created) {
        assert(!pthread_join(feeder,NULL));
        bool early=!strcmp(scenario,"pcm32_stop") || !strcmp(scenario,"pcm32_error") ||
            !strcmp(scenario,"pcm32_wait_stop") || !strcmp(scenario,"pcm32_full_stop");
        assert(decoder.ended!=early);
        assert(atomic_load(&pcm_received)==(!strcmp(scenario,"pcm32_wait_stop")?26624U:early?0U:
            !strcmp(scenario,"pcm32_paced")?70000U:!strcmp(scenario,"pcm32_fragments")?64000U:
            (!strcmp(scenario,"pcm32_long") || !strcmp(scenario,"pcm32_full"))?700000U:8U));
        if(!strcmp(scenario,"pcm32_full") || !strcmp(scenario,"pcm32_full_stop"))
            assert(atomic_load(&full_gate_passed) && atomic_load(&space_wakes));
    }
    if(!strcmp(scenario,"pcm32_paced")) assert(diagnostic_warnings==1 && "starvation warnings must reach persistent TVIO diagnostics");
    assert(!owner && opened==closed);
    if(!strcmp(scenario,"permanent")) {
        assert(!terminals && terminal_attempts>1 && invalidations==1 && epoch==0);
    } else if(!strcmp(scenario,"pending_lost")) {
        assert(!terminals && invalidations==1 && epoch==0 && opened==1 && status_fetches==1);
    } else if(!strcmp(scenario,"old_epoch")) {
        assert(!terminals && terminal_attempts==1 && !invalidations && epoch==2);
    } else if(!strcmp(scenario,"pending")) {
        assert(terminals==2 && opened==2 && stops==1 && completed && replies==1);
    } else if(!strcmp(scenario,"matching_stop") || !strcmp(scenario,"pcm32_stop") || !strcmp(scenario,"pcm32_wait_stop") || !strcmp(scenario,"pcm32_full_stop")) {
        assert(terminals==1 && stops==1 && !completed && replies==1);
    } else if(!strcmp(scenario,"pcm32_error")) {
        assert(terminals==1 && !completed && replies==1 && stops==1);
    } else if(format_failure()) {
        assert(terminals==1 && !completed && replies==1);
        assert(stops==(!strcmp(scenario,"pcm_mismatch") ? 1U : 0U));
        assert(opened==(!strcmp(scenario,"pcm_mismatch") ? 1U : 0U));
    } else if(!strcmp(scenario,"timeout")) {
        assert(terminals==1 && recoveries==1 && !completed && !tivoo_audio_resource_test_silent());
    } else {
        assert(terminals==1 && completed && replies==1 && !invalidations);
        assert(terminal_attempts==(!strcmp(scenario,"temporary")?4:1));
        if(!strncmp(scenario,"pcm24_",6)) assert(reads==2);
        if(!strcmp(scenario,"long_stream")) assert(clock_us>=8000000 && reads==10 && !stops);
    }
    play(current_sid,!strcmp(current_sid,sid1)?pid1:pid2);
    assert(terminals<=2 && opened<=2); /* duplicate cannot schedule new work */
    return 0;
}
