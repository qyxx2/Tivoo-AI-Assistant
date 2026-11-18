#include "s3_afe.h"
#include "audio_capture.h"
#include "esp_afe_config.h"
#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#include "model_path.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/queue.h"
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>

static const char *TAG="s3_afe";
static srmodel_list_t *models;
static const esp_afe_sr_iface_t *afe;
static esp_afe_sr_data_t *data;
static int16_t *input;
static size_t feed_size, fetch_size;
static char *word_storage;
static const char *words[AFE_MAX_WAKEWORD_NUM];
static int word_count;
static tivoo_afe_flow_t *flow;
static TaskHandle_t feed_handle, fetch_handle;
typedef struct { tivoo_afe_control_t control; uint64_t index; } gate_control_t;
static QueueHandle_t controls;
static atomic_bool reset_requested, feed_paused, streaming, fatal;
static atomic_uint feed_errors, rx_gaps, feed_calls, feed_max_us, feed_stack;
static uint64_t epoch_first; /* publish before streaming release; reset handshake protects writes */

static void update_max(atomic_uint *value, unsigned sample)
{
    unsigned old=atomic_load(value);
    if (sample>old) atomic_store(value,sample); /* single writer */
}
const char *tivoo_s3_afe_wake_word(int index)
{
    return index>0 && index<=word_count ? words[index-1] : NULL;
}

bool tivoo_s3_afe_control(tivoo_afe_control_t control, uint64_t index)
{
    if (control<TIVOO_AFE_GATE_OPEN || control>TIVOO_AFE_PROMPT_END ||
        !controls || !atomic_load(&streaming) || atomic_load(&reset_requested) ||
        atomic_load(&fatal)) return false;
    const gate_control_t command={control,index};
    return xQueueSend(controls,&command,0)==pdTRUE;
}

static void apply_controls(void)
{
    gate_control_t command;
    // Bound work even if a future producer floods requests.
    for (unsigned i=0;i<4 && xQueueReceive(controls,&command,0)==pdTRUE;++i) {
        switch (command.control) {
        case TIVOO_AFE_GATE_OPEN:
            (void)tivoo_afe_flow_open(flow,command.index);
            break;
        case TIVOO_AFE_GATE_CLOSE: tivoo_afe_flow_close(flow); break;
        case TIVOO_AFE_PROMPT_BEGIN: tivoo_afe_flow_prompt(flow,true,0); break;
        case TIVOO_AFE_PROMPT_END: tivoo_afe_flow_prompt(flow,false,command.index); break;
        }
    }
}

static void request_reset(void)
{
    atomic_store(&reset_requested,true);
}

static void feed_task(void *arg)
{
    (void)arg;
    ulTaskNotifyTake(pdTRUE,portMAX_DELAY);
    tivoo_capture_frame_t frame;
    size_t filled=0;
    uint64_t chunk_first=0, expected=0;
    bool contiguous=false;
    while (!atomic_load(&fatal)) {
        if (atomic_load(&reset_requested)) {
            filled=0;
            contiguous=false;
            atomic_store(&feed_paused,true);
            while (atomic_load(&reset_requested) && !atomic_load(&fatal)) vTaskDelay(1);
            continue;
        }
        if (tivoo_audio_capture_next(&frame)!=ESP_OK) {
            ++rx_gaps;
            if (contiguous || atomic_load(&streaming)) request_reset();
            continue;
        }
        if (frame.gap || !frame.reference_valid ||
            (contiguous && expected!=frame.first_sample)) {
            ++rx_gaps;
            if (contiguous || atomic_load(&streaming)) request_reset();
            filled=0;
            contiguous=false;
            continue;
        }
        contiguous=true;
        expected=frame.first_sample+TIVOO_CAPTURE_SAMPLES;
        for (size_t offset=0;offset<TIVOO_CAPTURE_SAMPLES &&
             !atomic_load(&reset_requested);) {
            if (!filled) chunk_first=frame.first_sample+offset;
            size_t n=feed_size-filled;
            if (n>TIVOO_CAPTURE_SAMPLES-offset) n=TIVOO_CAPTURE_SAMPLES-offset;
            tivoo_afe_interleave(input+4*filled,frame.left+offset,
                frame.right+offset,frame.reference+offset,n);
            filled+=n;
            offset+=n;
            if (filled==feed_size) {
                int64_t before=esp_timer_get_time();
                int rc=afe->feed(data,input);
                update_max(&feed_max_us,(unsigned)(esp_timer_get_time()-before));
                ++feed_calls;
                filled=0;
                if (rc<=0) {
                    ++feed_errors;
                    request_reset();
                    break;
                }
                if (!atomic_load(&streaming)) {
                    epoch_first=chunk_first;
                    atomic_store(&streaming,true);
                }
            }
        }
        atomic_store(&feed_stack,uxTaskGetStackHighWaterMark(NULL));
    }
    vTaskDelete(NULL);
}

static void fetch_task(void *arg)
{
    (void)arg;
    ulTaskNotifyTake(pdTRUE,portMAX_DELAY);
    bool have_epoch=false;
    bool wait_neutral=true;
    uint64_t cursor=0, fetch_calls=0, fetch_errors=0, resets=0;
    unsigned fetch_max_us=0;
    int last_state=0;
    int64_t report=esp_timer_get_time();
    for (;;) {
        if (atomic_load(&reset_requested)) {
            /* Both API users are quiescent before reset_buffer/reset_vad. */
            if (!atomic_load(&feed_paused)) {
                // If feed is waiting for room, drain without publishing until it pauses.
                (void)afe->fetch_with_delay(data,1);
                continue;
            }
            tivoo_afe_flow_gap(flow);
            xQueueReset(controls);
            have_epoch=false;
            wait_neutral=true;
            last_state=0;
            atomic_store(&streaming,false);
            ++resets;
            if (resets==1 || resets%10==0)
                ESP_LOGW(TAG,"AFE discontinuity: resets=%llu rx_gaps=%u feed_errors=%u fetch_errors=%llu",
                    (unsigned long long)resets,atomic_load(&rx_gaps),
                    atomic_load(&feed_errors),(unsigned long long)fetch_errors);
            if (afe->reset_buffer(data)!=1 || afe->reset_vad(data)!=1) {
                ESP_LOGE(TAG,"AFE reset failed; local wake disabled");
                atomic_store(&fatal,true);
                break;
            }
            atomic_store(&feed_paused,false);
            atomic_store(&reset_requested,false);
            continue;
        }
        if (!atomic_load(&streaming)) { vTaskDelay(1); continue; }
        if (!have_epoch) {
            cursor=epoch_first;
            have_epoch=true;
        }
        int64_t before=esp_timer_get_time();
        afe_fetch_result_t *r=afe->fetch_with_delay(data,pdMS_TO_TICKS(250));
        unsigned elapsed=(unsigned)(esp_timer_get_time()-before);
        if (elapsed>fetch_max_us) fetch_max_us=elapsed;
        if (atomic_load(&reset_requested)) continue;
        if (!r || r->ret_value!=ESP_OK || !r->data || r->data_size<=0 ||
            r->data_size%sizeof(int16_t) ||
            (size_t)r->data_size/sizeof(int16_t)>fetch_size ||
            r->vad_cache_size<0 || r->vad_cache_size%sizeof(int16_t) ||
            (r->vad_cache_size && !r->vad_cache)) {
            ++fetch_errors;
            request_reset();
            continue;
        }
        ++fetch_calls;
        apply_controls();
        size_t count=(size_t)r->data_size/sizeof(int16_t);
        if (r->wakeup_state!=last_state || r->wakeup_state!=WAKENET_NO_DETECT) {
            ESP_LOGI(TAG,"wake trace sample=%llu state=%d raw_ch=%d model=%d word=%d channel=%d",
                (unsigned long long)cursor,r->wakeup_state,r->raw_data_channels,
                r->wakenet_model_index,r->wake_word_index,r->trigger_channel_id);
            last_state=r->wakeup_state;
        }
        /* After boot/reset, require a neutral detector result before arming. */
        if (r->wakeup_state==WAKENET_NO_DETECT) wait_neutral=false;
        tivoo_afe_flow_frame(flow,cursor,r->data,count,r->vad_state==VAD_SPEECH,
            wait_neutral ? WAKENET_NO_DETECT : r->wakeup_state,r->raw_data_channels,
            r->wakenet_model_index,r->wake_word_index,r->vad_cache_size/sizeof(int16_t));
        cursor+=count;
        if (esp_timer_get_time()-report>=10000000) {
            report=esp_timer_get_time();
            ESP_LOGI(TAG,"feed=%u fetch=%llu feed_errors=%u fetch_errors=%llu rx_gaps=%u resets=%llu overruns=%u missed_eof=%u cache_samples_ignored=%llu ring_free_pct=%.3f feed_max_us=%u fetch_wait_max_us=%u stack=%u/%u internal_min=%zu internal_largest=%zu dma_largest=%zu psram_free=%zu",
                atomic_load(&feed_calls),(unsigned long long)fetch_calls,
                atomic_load(&feed_errors),(unsigned long long)fetch_errors,
                atomic_load(&rx_gaps),(unsigned long long)resets,
                tivoo_audio_capture_overruns(),tivoo_audio_capture_missed_eofs(),
                (unsigned long long)flow->cache_ignored,(double)r->ringbuff_free_pct,
                atomic_load(&feed_max_us),fetch_max_us,atomic_load(&feed_stack),
                (unsigned)uxTaskGetStackHighWaterMark(NULL),
                heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL),
                heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
                heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_DMA),
                heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
        }
    }
    vTaskDelete(NULL);
}

static bool config_valid(const afe_config_t *c)
{
    return c && c->aec_init && c->aec_mode==AEC_MODE_FD_HIGH_PERF &&
        c->afe_type==AFE_TYPE_FD && c->afe_mode==AFE_MODE_HIGH_PERF &&
        c->se_init && !c->ns_init && c->vad_init && !c->vad_mute_playback &&
        c->vad_min_speech_ms==128 && c->vad_min_noise_ms==500 && c->vad_delay_ms==128 &&
        c->vad_model_name && !strcmp(c->vad_model_name,"vadnet1_medium") &&
        c->wakenet_init && c->wakenet_model_name &&
        !strcmp(c->wakenet_model_name,TIVOO_AFE_MODEL_ID) &&
        !c->wakenet_model_name_2 && c->pcm_config.total_ch_num==4 &&
        c->pcm_config.mic_num==2 && c->pcm_config.ref_num==1 &&
        c->pcm_config.sample_rate==16000 && c->pcm_config.mic_ids &&
        c->pcm_config.ref_ids && c->pcm_config.mic_ids[0]==0 &&
        c->pcm_config.mic_ids[1]==1 && c->pcm_config.ref_ids[0]==3;
}

esp_err_t tivoo_s3_afe_start(tivoo_afe_sink_t sink, void *ctx)
{
    if (data) return ESP_ERR_INVALID_STATE;
    esp_err_t err=ESP_ERR_INVALID_STATE;
    afe_config_t *config=NULL;
    models=esp_srmodel_init("model");
    if (!models) goto fail;
    int wake=esp_srmodel_exists(models,TIVOO_AFE_MODEL_ID);
    int vad=esp_srmodel_exists(models,"vadnet1_medium");
    for (int i=0;i<models->num;i++) ESP_LOGI(TAG,"model[%d]=%s",i,models->model_name[i]);
    if (wake<0 || vad<0 || models->num!=2) goto fail;
    word_storage=esp_srmodel_get_wake_words(models,TIVOO_AFE_MODEL_ID);
    if (!word_storage || !*word_storage) goto fail;
    char *p=word_storage;
    while (p) {
        if (!*p || word_count>=AFE_MAX_WAKEWORD_NUM) goto fail;
        words[word_count++]=p;
        char *semi=strchr(p,';');
        if (semi) *semi++='\0';
        p=semi;
    }
    for (int i=0;i<word_count;i++) ESP_LOGI(TAG,"wake word[%d]=%s",i+1,words[i]);
    config=afe_config_init("MMNR", models, AFE_TYPE_FD, AFE_MODE_HIGH_PERF);
    if (!config) goto fail;
    config->aec_init=true;
    config->aec_mode=AEC_MODE_FD_HIGH_PERF;
    config->se_init=true;
    config->ns_init=false;
    config->vad_init=true;
    config->vad_model_name=models->model_name[vad];
    config->vad_mute_playback=false;
    config->vad_min_speech_ms=128;
    config->vad_min_noise_ms=500;
    config->vad_delay_ms=128;
    config->wakenet_init=true;
    config->wakenet_model_name=models->model_name[wake];
    config->memory_alloc_mode=AFE_MEMORY_ALLOC_MORE_PSRAM;
    if (!afe_config_check(config) || !config_valid(config)) goto fail;
    ESP_LOGI(TAG,"effective AFE FD HIGH_PERF MMNR BSS=%d NS=%d VAD mode=%d speech/noise/delay=%d/%d/%d energy=%.1f wake_mode=%d AGC=%d/%d AEC filter=%d mem=%d",
        config->se_init,config->ns_init,config->vad_mode,config->vad_min_speech_ms,
        config->vad_min_noise_ms,config->vad_delay_ms,(double)config->vad_energy_threshold,
        config->wakenet_mode,config->agc_init,config->agc_mode,config->aec_filter_length,
        config->memory_alloc_mode);
    afe=esp_afe_handle_from_config(config);
    if (!afe) goto fail;
    data=afe->create_from_config(config);
    afe_config_free(config);
    config=NULL;
    if (!data) goto fail;
    int feed=afe->get_feed_chunksize(data), fetch=afe->get_fetch_chunksize(data);
    if (feed<=0 || fetch<=0 || afe->get_feed_channel_num(data)!=4 ||
        afe->get_fetch_channel_num(data)!=1 || afe->get_samp_rate(data)!=16000) goto fail;
    feed_size=(size_t)feed;
    fetch_size=(size_t)fetch;
    afe->print_pipeline(data);
    ESP_LOGI(TAG,"feed=%d x4 fetch=%d x1 rate=16000 VAD threshold=%.3f (smoke until hardware acceptance)",
        feed,fetch,(double)afe->get_vadnet_threshold(data));
    err=ESP_ERR_NO_MEM;
    input=heap_caps_malloc(feed_size*4*sizeof(int16_t),MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
    flow=heap_caps_malloc(sizeof(*flow),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    controls=xQueueCreate(4,sizeof(gate_control_t));
    if (!input || !flow || !controls) goto fail;
    tivoo_afe_flow_init(flow,word_count,sink,ctx);
    if (xTaskCreatePinnedToCore(feed_task,"afe_feed",4096,NULL,7,&feed_handle,1)!=pdPASS ||
        xTaskCreatePinnedToCore(fetch_task,"afe_fetch",4096,NULL,5,&fetch_handle,1)!=pdPASS) goto fail;
    xTaskNotifyGive(fetch_handle);
    xTaskNotifyGive(feed_handle);
    return ESP_OK;
fail:
    ESP_LOGE(TAG,"local AFE initialization failed (%s), model=%s; no remote KWS fallback",
        esp_err_to_name(err),TIVOO_AFE_MODEL_ID);
    if (feed_handle) { vTaskDelete(feed_handle); feed_handle=NULL; }
    if (fetch_handle) { vTaskDelete(fetch_handle); fetch_handle=NULL; }
    if (controls) { vQueueDelete(controls); controls=NULL; }
    free(input); input=NULL;
    free(flow); flow=NULL;
    if (data) { afe->destroy(data); data=NULL; }
    if (config) afe_config_free(config);
    if (models) { esp_srmodel_deinit(models); models=NULL; }
    free(word_storage); word_storage=NULL;
    word_count=0;
    return err;
}
