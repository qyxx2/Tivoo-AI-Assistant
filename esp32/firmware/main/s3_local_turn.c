#include "s3_local_turn.h"
#include "p68_local_turn.h"
#include "p68_prompt.h"
#include "audio_output_manager.h"
#include "s3_afe.h"
#include "diagnostics.h"
#include "audio_resource.h"
#include "cJSON.h"
#include "esp_heap_caps.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include <stdio.h>
#include <string.h>

static const char *TAG="local_turn";
/* All PCM/state transitions run on the AFE fetch task. RX shares only a
 * small mailbox/authorization snapshot, never the PCM storage. */
static tivoo_local_turn_t *turn;
static bool test_gate_enabled, prompt_calibrated;
static unsigned prompt_tail;
static int prompt_offset;
static uint32_t prompt_generation;
static tivoo_prompt_t prompt;
static int last_ready=-1;
static const char *gate_result;
static bool pending_prompt, is_followup;
static char parent_uuid[37];
extern const int16_t ready_01_start[], ready_01_end[], ready_02_start[], ready_02_end[];
extern const int16_t ready_03_start[], ready_03_end[], followup_01_start[], followup_01_end[];

static size_t prompt_push(void *ctx,const int16_t *pcm,size_t count)
{
    (void)ctx;
    return tivoo_audio_output_try_write(prompt_generation,pcm,count);
}
static void prompt_finish(void *ctx) { (void)ctx; tivoo_audio_output_finish_input(prompt_generation); }
static void prompt_stop(void *ctx) { (void)ctx; tivoo_audio_output_stop(prompt_generation); }
static bool prompt_drain(void *ctx,uint64_t *end,uint64_t *clock)
{
    (void)ctx;
    return tivoo_audio_output_prompt_drain(prompt_generation,end,clock);
}
static const tivoo_prompt_io_t prompt_io={prompt_push,prompt_finish,prompt_stop,prompt_drain};
static uint32_t epoch;
static char uuid[37];
static const char *phrase;
static portMUX_TYPE lock=portMUX_INITIALIZER_UNLOCKED;
static struct {
    uint32_t epoch;
    char uuid[37], playback[37];
    uint64_t ready_ms;
    bool ready, stop, reply_allowed, followup_requested, playback_completed;
} shared;

static uint64_t now_ms(void) { return (uint64_t)esp_timer_get_time()/1000; }
static void new_uuid(char out[37])
{
    uint8_t id[16];
    esp_fill_random(id,sizeof(id));
    id[6]=(id[6]&15)|0x40;
    id[8]=(id[8]&63)|0x80;
    snprintf(out,37,"%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
        id[0],id[1],id[2],id[3],id[4],id[5],id[6],id[7],id[8],id[9],id[10],id[11],id[12],id[13],id[14],id[15]);
}
static void invalidate(void)
{
    portENTER_CRITICAL(&lock);
    memset(&shared,0,sizeof(shared));
    portEXIT_CRITICAL(&lock);
}
static void abort_turn(const char *reason)
{
    if (prompt_generation) tivoo_prompt_cancel(&prompt);
    tivoo_turn_abort(turn,reason);
    tivoo_s3_afe_close_local_gate();
    portENTER_CRITICAL(&lock);
    shared.reply_allowed=false;
    shared.stop=true;
    portEXIT_CRITICAL(&lock);
    pending_prompt=false;
    tivoo_audio_resource_retire_local(uuid,epoch);
}
static bool send_event(void *ctx, tivoo_turn_event_t type, const int16_t *pcm, size_t samples, uint64_t time, const char *reason)
{
    (void)ctx;
    if(epoch!=tivoo_diagnostics_local_wake_generation()) return false;
    if(type==TIVOO_TURN_PCM)
        return tivoo_diagnostics_send_mic(epoch,TVIO_TYPE_MIC_PCM,pcm,samples*sizeof(*pcm));
    cJSON *root=cJSON_CreateObject();
    if(!root) return false;
    cJSON_AddStringToObject(root,"session_id",uuid);
    uint8_t wire=0;
    switch(type) {
    case TIVOO_TURN_START:
        wire=TVIO_TYPE_MIC_SESSION_START;
        cJSON_AddNumberToObject(root,"sample_rate",16000);
        cJSON_AddNumberToObject(root,"channels",1);
        cJSON_AddStringToObject(root,"sample_format","s16le");
        cJSON_AddNumberToObject(root,"frame_duration_ms",20);
        cJSON_AddNumberToObject(root,"preroll_ms",0);
        cJSON_AddStringToObject(root,"trigger_source",is_followup?"local_followup":"local_wake");
        if (is_followup) cJSON_AddStringToObject(root,"parent_session_id",parent_uuid);
        else cJSON_AddStringToObject(root,"wake_word_phrase",phrase);
        break;
    case TIVOO_TURN_GATE:
        wire=TVIO_TYPE_COMMAND_GATE;
        cJSON_AddStringToObject(root,"prompt_result",gate_result);
        break;
    case TIVOO_TURN_SPEECH_START:
    case TIVOO_TURN_SPEECH_END:
        wire=TVIO_TYPE_MIC_ACTIVITY;
        cJSON_AddStringToObject(root,"state",type==TIVOO_TURN_SPEECH_START?"speech_start":"speech_end");
        if(type==TIVOO_TURN_SPEECH_END) cJSON_AddNumberToObject(root,"pcm_samples",(double)samples);
        break;
    case TIVOO_TURN_ABORT:
        wire=TVIO_TYPE_MIC_SESSION_END;
        cJSON_AddStringToObject(root,"reason",reason);
        break;
    case TIVOO_TURN_PCM: break;
    }
    cJSON_AddNumberToObject(root,"uptime_ms",(double)time);
    char *payload=cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    bool ok=payload && tivoo_diagnostics_send_mic(epoch,wire,payload,strlen(payload));
    cJSON_free(payload);
    if(ok && type==TIVOO_TURN_SPEECH_END) {
        portENTER_CRITICAL(&lock);
        shared.reply_allowed=!shared.stop;
        portEXIT_CRITICAL(&lock);
        ESP_LOGI(TAG,"end valid=%zu padded=%zu sent=%zu ready/gate tracked",turn->valid_samples,turn->pad_samples,samples);
    }
    return ok;
}

esp_err_t tivoo_s3_local_turn_init(bool test_gate, bool calibrated, unsigned tail, int offset)
{
    turn=heap_caps_calloc(1,sizeof(*turn),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!turn) return ESP_ERR_NO_MEM;
    test_gate_enabled=test_gate;
    prompt_calibrated=calibrated;
    prompt_tail=tail;
    prompt_offset=offset;
    return ESP_OK;
}
static void poll_prompt(void)
{
    if (!prompt_generation) return;
    const tivoo_prompt_status_t status=tivoo_prompt_poll(&prompt,&prompt_io,NULL,now_ms());
    if (status==TIVOO_PROMPT_UNSAFE) {
        if (turn->active && !turn->abort_reason) abort_turn("prompt_drain_timeout");
        return; /* keep the owner/mask until hardware confirms safe drain */
    }
    if (status!=TIVOO_PROMPT_SAFE ||
        !tivoo_audio_resource_prompt_end(prompt_generation)) return;
    prompt_generation=0;
    if (prompt.cancelled && turn->active && !turn->abort_reason) abort_turn("prompt_drain_timeout");
    const bool open=turn->active && !turn->abort_reason && !prompt.cancelled;
    const bool opened=tivoo_s3_afe_finish_prompt(prompt.gate_sample,open);
    if (opened) {
        gate_result=prompt.skipped ? "skipped" : "completed";
        tivoo_turn_gate(turn,prompt.gate_ms);
        ESP_LOGI(TAG,"prompt gate result=%s sample=%llu time=%llu",gate_result,
            (unsigned long long)prompt.gate_sample,(unsigned long long)prompt.gate_ms);
    } else if (open) {
        abort_turn("prompt_gate_stale");
    }
}

static void start_prompt(uint64_t now)
{
    if (test_gate_enabled) {
        if (!tivoo_audio_resource_prompt_ready(0)) return;
        if (tivoo_s3_afe_open_test_gate()) {
            pending_prompt=false;
            gate_result="skipped";
            tivoo_turn_gate(turn,now);
        } else {
            abort_turn("test_gate_failed");
        }
        return;
    }
    if (!prompt_calibrated) {
        abort_turn("prompt_calibration_required");
        return;
    }
    const tivoo_prompt_asset_t pool[]={
        {ready_01_start,((uintptr_t)ready_01_end-(uintptr_t)ready_01_start)/sizeof(int16_t)},
        {ready_02_start,((uintptr_t)ready_02_end-(uintptr_t)ready_02_start)/sizeof(int16_t)},
        {ready_03_start,((uintptr_t)ready_03_end-(uintptr_t)ready_03_start)/sizeof(int16_t)},
        {followup_01_start,((uintptr_t)followup_01_end-(uintptr_t)followup_01_start)/sizeof(int16_t)}
    };
    if (!tivoo_audio_resource_prompt_ready(prompt_tail)) return;
    const int pick=tivoo_prompt_select(pool,is_followup,last_ready,esp_random());
    prompt_generation=tivoo_audio_resource_prompt_begin();
    if (!prompt_generation) return;
    pending_prompt=false;
    tivoo_s3_afe_begin_prompt();
    tivoo_prompt_begin(&prompt,pick<0 ? (tivoo_prompt_asset_t){0} : pool[pick],
        now,prompt_tail,prompt_offset);
    if (pick>=0 && !is_followup) last_ready=pick;
}

static void begin_turn(uint32_t current, const char *wake_phrase, bool followup, uint64_t now)
{
    /* Invalidate old network authorization before retiring its captured owner.
     * RX may hold the resource mutex while consulting the shared snapshot. */
    invalidate();
    if (epoch && uuid[0]) tivoo_audio_resource_retire_local(uuid,epoch);
    tivoo_s3_afe_close_local_gate();
    if (followup) memcpy(parent_uuid,uuid,sizeof(parent_uuid));
    is_followup=followup;
    epoch=current;
    phrase=wake_phrase;
    new_uuid(uuid);
    if (followup) tivoo_turn_begin_followup(turn,now);
    else tivoo_turn_begin(turn,now);
    pending_prompt=true;
    portENTER_CRITICAL(&lock);
    shared.epoch=epoch;
    memcpy(shared.uuid,uuid,sizeof(uuid));
    portEXIT_CRITICAL(&lock);
}

void tivoo_s3_local_turn_tick(void)
{
    if(!turn) return;
    if(!turn->active) { poll_prompt(); return; }
    uint32_t current=tivoo_diagnostics_local_wake_generation();
    if(current!=epoch) {
        turn->active=false;
        pending_prompt=false;
        if (prompt_generation) tivoo_prompt_cancel(&prompt);
        invalidate();
        tivoo_audio_resource_retire_local(uuid,epoch);
        tivoo_s3_afe_close_local_gate();
        poll_prompt();
        return;
    }
    bool ready,stop,followup;
    uint64_t ready_ms;
    portENTER_CRITICAL(&lock);
    ready=shared.ready; ready_ms=shared.ready_ms; stop=shared.stop;
    followup=shared.followup_requested;
    portEXIT_CRITICAL(&lock);
    if(stop) abort_turn("ha_stop");
    else if(followup && turn->complete && !prompt_generation) {
        begin_turn(current,NULL,true,now_ms());
        ready=false;
    }
    if(ready) tivoo_turn_ready(turn,ready_ms);
    if(pending_prompt && !turn->abort_reason) {
        if(now_ms()-turn->wake_ms>=5000) abort_turn("prompt_owner_timeout");
        else start_prompt(now_ms());
    }
    poll_prompt();
    tivoo_turn_tick(turn,now_ms(),send_event,NULL);
    if(turn->abort_reason) abort_turn(turn->abort_reason);
    if(!turn->active) invalidate();
}
void tivoo_s3_local_turn_event(void *ctx, const tivoo_afe_event_t *event)
{
    (void)ctx;
    if(!turn) return;
    const uint64_t now=now_ms();
    if(event->type==TIVOO_AFE_WAKE) {
        if(prompt_generation) return;
        const uint32_t current=tivoo_diagnostics_local_wake_generation();
        const char *wake_phrase=tivoo_s3_afe_wake_word(event->word);
        if(!current || !wake_phrase) return;
        begin_turn(current,wake_phrase,false,now);
        tivoo_s3_local_turn_tick();
        return;
    }
    if(!turn->active || turn->complete || turn->abort_reason) return;
    switch(event->type) {
    case TIVOO_AFE_START: tivoo_turn_speech(turn,now,event->index); break;
    case TIVOO_AFE_PCM: tivoo_turn_pcm(turn,event->index,event->pcm,event->count); break;
    case TIVOO_AFE_END: tivoo_turn_end(turn,now,event->index); break;
    case TIVOO_AFE_GAP: abort_turn("afe_gap"); break;
    case TIVOO_AFE_WAKE: break;
    }
    tivoo_s3_local_turn_tick();
}
bool tivoo_s3_local_turn_ready_message(const uint8_t *payload, size_t size)
{
    cJSON *root=cJSON_ParseWithLength((const char *)payload,size);
    const char *id=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(root,"session_id"));
    const uint32_t current=tivoo_diagnostics_local_wake_generation();
    portENTER_CRITICAL(&lock);
    if(id && current && current==shared.epoch && strcmp(id,shared.uuid)==0 && !shared.stop && !shared.ready) {
        shared.ready_ms=now_ms();
        shared.ready=true;
    }
    portEXIT_CRITICAL(&lock);
    cJSON_Delete(root);
    return true;
}
void tivoo_s3_local_turn_stop(const char *id, const char *reason)
{
    (void)reason;
    const uint32_t current=tivoo_diagnostics_local_wake_generation();
    portENTER_CRITICAL(&lock);
    if(id && current && current==shared.epoch && strcmp(id,shared.uuid)==0) {
        shared.stop=true;
        shared.reply_allowed=false;
    }
    portEXIT_CRITICAL(&lock);
}
bool tivoo_s3_local_turn_bind_playback(const char *id, const char *playback)
{
    const uint32_t current=tivoo_diagnostics_local_wake_generation();
    bool ok=false;
    if(!id || !playback || strlen(playback)!=36) return false;
    portENTER_CRITICAL(&lock);
    if(current && current==shared.epoch && shared.reply_allowed && !shared.stop && !shared.followup_requested &&
       strcmp(id,shared.uuid)==0 && (!shared.playback[0] || strcmp(playback,shared.playback)==0)) {
        memcpy(shared.playback,playback,37);
        ok=true;
    }
    portEXIT_CRITICAL(&lock);
    return ok;
}

bool tivoo_s3_local_turn_followup_message(const uint8_t *payload, size_t size)
{
    cJSON *root=cJSON_ParseWithLength((const char *)payload,size);
    const char *id=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(root,"session_id"));
    const uint32_t current=tivoo_diagnostics_local_wake_generation();
    portENTER_CRITICAL(&lock);
    if(tivoo_turn_followup_allowed(id && current && current==shared.epoch && strcmp(id,shared.uuid)==0,
        shared.reply_allowed && !shared.stop, !shared.playback[0] || shared.playback_completed,
        shared.followup_requested)) shared.followup_requested=true;
    portEXIT_CRITICAL(&lock);
    cJSON_Delete(root);
    return true;
}

void tivoo_s3_local_turn_playback_finished(const char *id, const char *playback, uint32_t peer, bool completed)
{
    portENTER_CRITICAL(&lock);
    if(peer==shared.epoch && strcmp(id,shared.uuid)==0 && strcmp(playback,shared.playback)==0) {
        shared.playback_completed=completed;
        if(!completed) shared.reply_allowed=false;
    }
    portEXIT_CRITICAL(&lock);
}
