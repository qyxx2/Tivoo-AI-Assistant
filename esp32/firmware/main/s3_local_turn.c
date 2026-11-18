#include "s3_local_turn.h"
#include "p68_local_turn.h"
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
static bool test_gate_enabled;
static uint32_t epoch;
static char uuid[37];
static const char *phrase;
static portMUX_TYPE lock=portMUX_INITIALIZER_UNLOCKED;
static struct {
    uint32_t epoch;
    char uuid[37], playback[37];
    uint64_t ready_ms;
    bool ready, stop, reply_allowed;
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
    tivoo_turn_abort(turn,reason);
    tivoo_s3_afe_close_local_gate();
    portENTER_CRITICAL(&lock);
    shared.reply_allowed=false;
    portEXIT_CRITICAL(&lock);
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
        cJSON_AddStringToObject(root,"trigger_source","local_wake");
        cJSON_AddStringToObject(root,"wake_word_phrase",phrase);
        break;
    case TIVOO_TURN_GATE:
        wire=TVIO_TYPE_COMMAND_GATE;
        cJSON_AddStringToObject(root,"prompt_result","skipped"); /* b5 test gate only */
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

esp_err_t tivoo_s3_local_turn_init(bool test_gate)
{
    turn=heap_caps_calloc(1,sizeof(*turn),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!turn) return ESP_ERR_NO_MEM;
    test_gate_enabled=test_gate;
    return ESP_OK;
}
void tivoo_s3_local_turn_tick(void)
{
    if(!turn || !turn->active) return;
    uint32_t current=tivoo_diagnostics_local_wake_generation();
    if(current!=epoch) {
        turn->active=false;
        tivoo_s3_afe_close_local_gate();
        invalidate();
        return;
    }
    bool ready,stop;
    uint64_t ready_ms;
    portENTER_CRITICAL(&lock);
    ready=shared.ready; ready_ms=shared.ready_ms; stop=shared.stop;
    portEXIT_CRITICAL(&lock);
    if(stop) abort_turn("ha_stop");
    if(ready) tivoo_turn_ready(turn,ready_ms);
    tivoo_turn_tick(turn,now_ms(),send_event,NULL);
    if(turn->abort_reason) {
        tivoo_s3_afe_close_local_gate();
        portENTER_CRITICAL(&lock);
        shared.reply_allowed=false;
        portEXIT_CRITICAL(&lock);
    }
    if(!turn->active) invalidate();
}
void tivoo_s3_local_turn_event(void *ctx, const tivoo_afe_event_t *event)
{
    (void)ctx;
    if(!turn) return;
    const uint64_t now=now_ms();
    if(event->type==TIVOO_AFE_WAKE) {
        if(turn->active) {
            /* Full active-reply interruption and restart belong to b7. Do not
             * splice audio from this newly confirmed wake into the old turn. */
            if(!turn->complete) abort_turn("superseded_wake");
            return;
        }
        epoch=tivoo_diagnostics_local_wake_generation();
        phrase=tivoo_s3_afe_wake_word(event->word);
        if(!epoch || !phrase) return;
        new_uuid(uuid);
        tivoo_turn_begin(turn,now);
        portENTER_CRITICAL(&lock);
        memset(&shared,0,sizeof(shared));
        shared.epoch=epoch;
        memcpy(shared.uuid,uuid,sizeof(uuid));
        portEXIT_CRITICAL(&lock);
        /* A physical gate must be supplied by b6. The test-only gate is
         * deliberately available only before the first output since boot. */
        if(test_gate_enabled && tivoo_audio_resource_test_silent() && tivoo_s3_afe_open_test_gate())
            tivoo_turn_gate(turn,now);
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
    if(current && current==shared.epoch && shared.reply_allowed && !shared.stop &&
       strcmp(id,shared.uuid)==0 && (!shared.playback[0] || strcmp(playback,shared.playback)==0)) {
        memcpy(shared.playback,playback,37);
        ok=true;
    }
    portEXIT_CRITICAL(&lock);
    return ok;
}
