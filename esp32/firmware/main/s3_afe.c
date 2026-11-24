#include "s3_afe.h"
#include "p68_trace.h"
#include "s3_local_turn.h"
#include "audio_capture.h"
#include "diagnostics.h"
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
static TaskHandle_t capture_handle, feed_handle, fetch_handle;
/* 160 ms of owned, already aligned PCM. This is task-to-task PSRAM
 * storage, separate from the short internal ISR queue and DMA ring. */
#define CAPTURE_QUEUE_FRAMES 32U
typedef struct { tivoo_capture_frame_t frame; bool valid; } captured_frame_t;
static QueueHandle_t captured;
static StaticQueue_t capture_queue_control;
static uint8_t *capture_queue_storage;
static atomic_uint capture_overruns, capture_stack;
typedef struct { tivoo_afe_control_t control; uint64_t index; } gate_control_t;
static QueueHandle_t controls;
static bool vad_gate_pending; /* fetch owner; new gate must have fresh vendor VAD */
static atomic_bool reset_requested, feed_paused, streaming, usable, fatal;
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
        !controls || !atomic_load(&usable) || atomic_load(&reset_requested) ||
        atomic_load(&fatal)) return false;
    const gate_control_t command={control,index};
    return xQueueSend(controls,&command,0)==pdTRUE;
}

static bool open_gate(uint64_t index)
{
    vad_gate_pending=tivoo_afe_flow_open(flow,index);
    tivoo_trace_record((&(tivoo_trace_header_t){.kind=TIVOO_TRACE_GATE,
        .index=flow->have_next?flow->next:UINT64_MAX,.epoch=flow->have_next?epoch_first:UINT64_MAX,.aux=index,
        .flags=TIVOO_TRACE_OPEN_REQUESTED|(vad_gate_pending?TIVOO_TRACE_GATE_OPEN:0)}),NULL,NULL);
    return vad_gate_pending;
}

static void apply_controls(void)
{
    gate_control_t command;
    // Bound work even if a future producer floods requests.
    for (unsigned i=0;i<4 && xQueueReceive(controls,&command,0)==pdTRUE;++i) {
        switch (command.control) {
        case TIVOO_AFE_GATE_OPEN:
            (void)open_gate(command.index);
            break;
        case TIVOO_AFE_GATE_CLOSE: tivoo_afe_flow_close(flow); break;
        case TIVOO_AFE_PROMPT_BEGIN: tivoo_afe_flow_prompt(flow,true,0); break;
        case TIVOO_AFE_PROMPT_END: tivoo_afe_flow_prompt(flow,false,command.index); break;
        }
    }
}

bool tivoo_s3_afe_open_test_gate(void)
{
    return flow && atomic_load(&usable) && !atomic_load(&reset_requested) &&
        !atomic_load(&fatal) && open_gate(flow->next);
}
void tivoo_s3_afe_close_local_gate(void)
{
    if(flow) {
        tivoo_afe_flow_close(flow);
        tivoo_trace_record((&(tivoo_trace_header_t){.kind=TIVOO_TRACE_GATE,
            .index=flow->have_next?flow->next:UINT64_MAX,.epoch=flow->have_next?epoch_first:UINT64_MAX,
            .aux=UINT64_MAX}),NULL,NULL);
    }
}

void tivoo_s3_afe_begin_prompt(void)
{
    if (flow) {
        tivoo_afe_flow_prompt(flow,true,0);
        tivoo_trace_record((&(tivoo_trace_header_t){.kind=TIVOO_TRACE_GATE,
            .index=flow->have_next?flow->next:UINT64_MAX,.epoch=flow->have_next?epoch_first:UINT64_MAX,
            .aux=UINT64_MAX,.flags=TIVOO_TRACE_PROMPT}),NULL,NULL);
    }
}
bool tivoo_s3_afe_finish_prompt(uint64_t boundary, bool open)
{
    if (!flow) return false;
    const bool valid=atomic_load(&usable) && !atomic_load(&reset_requested) &&
        !atomic_load(&fatal) && (!flow->have_next || boundary>=flow->next);
    const uint64_t wake_after=flow->have_next && boundary<flow->next ? flow->next : boundary;
    tivoo_afe_flow_prompt(flow,false,wake_after);
    if (open && valid) return open_gate(boundary);
    tivoo_trace_record((&(tivoo_trace_header_t){.kind=TIVOO_TRACE_GATE,
        .index=flow->have_next?flow->next:UINT64_MAX,.epoch=flow->have_next?epoch_first:UINT64_MAX,.aux=boundary,
        .flags=open?TIVOO_TRACE_OPEN_REQUESTED:0}),NULL,NULL);
    return false;
}

static void publish_available(bool available)
{
    if (atomic_exchange(&usable,available)!=available)
        tivoo_diagnostics_set_local_wake_available(available);
}

static void request_reset(void)
{
    /* Feed only requests; fetch owns availability publication so a racing
     * feed error cannot reorder two independent capability updates. */
    atomic_store(&reset_requested,true);
}

static void capture_task(void *arg)
{
    (void)arg;
    ulTaskNotifyTake(pdTRUE,portMAX_DELAY);
    captured_frame_t packet;
    bool pending_gap=false;
    while (!atomic_load(&fatal)) {
        packet.valid=tivoo_audio_capture_next(&packet.frame)==ESP_OK;
        tivoo_capture_frame_t *frame=&packet.frame;
        if (packet.valid) {
            /* These raw pointers are transient. Trace on the capture owner,
             * before the next read, never forward pointers to the feed task. */
            tivoo_trace_record((&(tivoo_trace_header_t){.kind=TIVOO_TRACE_RAW,
                .index=frame->first_sample*2,.epoch=frame->epoch_first_raw,
                .aux=frame->tx_first_sample,.count=2*TIVOO_CAPTURE_SAMPLES,
                .extra=2*TIVOO_CAPTURE_SAMPLES,
                .flags=(frame->gap?TIVOO_TRACE_GAP:0)|
                       (frame->reference_valid?TIVOO_TRACE_REFERENCE_VALID:0)}),
                frame->raw_slots,frame->raw_tx);
        } else {
            *frame=(tivoo_capture_frame_t){.gap=true};
            tivoo_trace_record((&(tivoo_trace_header_t){.kind=TIVOO_TRACE_CAPTURE_ERROR,
                .index=UINT64_MAX,.epoch=UINT64_MAX,.aux=UINT64_MAX,
                .flags=TIVOO_TRACE_GAP}),NULL,NULL);
        }
        frame->raw_slots=NULL;
        frame->raw_tx=NULL;
        frame->gap|=pending_gap;
        if (xQueueSend(captured,&packet,0)!=pdTRUE) {
            ++capture_overruns;
            pending_gap=true;
        } else pending_gap=false;
        atomic_store(&capture_stack,uxTaskGetStackHighWaterMark(NULL));
    }
    /* Only this task owns capture, including transfer after fatal AFE. */
    if (tivoo_audio_capture_monitor_start()!=ESP_OK)
        TIVOO_LOGE(TAG,"AFE fatal; capture monitor unavailable");
    vTaskDelete(NULL);
}

static void feed_task(void *arg)
{
    (void)arg;
    ulTaskNotifyTake(pdTRUE,portMAX_DELAY);
    captured_frame_t packet;
    size_t filled=0;
    uint64_t chunk_first=0, expected=0;
    bool contiguous=false;
    while (!atomic_load(&fatal)) {
        if (atomic_load(&reset_requested)) {
            filled=0;
            contiguous=false;
            xQueueReset(captured);
            atomic_store(&feed_paused,true);
            while (atomic_load(&reset_requested) && !atomic_load(&fatal)) vTaskDelay(1);
            continue;
        }
        bool received=xQueueReceive(captured,&packet,pdMS_TO_TICKS(100))==pdTRUE;
        if (!received || !packet.valid) {
            ++rx_gaps;
            if (contiguous || atomic_load(&streaming)) request_reset();
            continue;
        }
        const tivoo_capture_frame_t frame=packet.frame;
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
    const char *failure=NULL;
    for (;;) {
        if (atomic_load(&reset_requested)) publish_available(false);
        tivoo_s3_local_turn_tick();
        if (!atomic_load(&usable) && esp_timer_get_time()-report>=10000000) {
            report=esp_timer_get_time();
            TIVOO_LOGW(TAG,"AFE unavailable: %s rx_gaps=%u feed_errors=%u fetch_errors=%llu resets=%llu",
                failure ? failure : (atomic_load(&reset_requested) ? "recovering" : "waiting for valid feed/fetch"),
                atomic_load(&rx_gaps),atomic_load(&feed_errors),
                (unsigned long long)fetch_errors,(unsigned long long)resets);
        }
        if (atomic_load(&fatal)) {
            /* Retire a canceled prompt on the existing turn tick even if
             * there will never be another vendor fetch. No AFE retry loop. */
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }
        if (atomic_load(&reset_requested)) {
            /* Both API users are quiescent before reset_buffer/reset_vad. */
            if (!atomic_load(&feed_paused)) {
                // If feed is waiting for room, drain without publishing until it pauses.
                (void)afe->fetch_with_delay(data,1);
                continue;
            }
            tivoo_trace_record((&(tivoo_trace_header_t){.kind=TIVOO_TRACE_AFE_GAP,
                .index=have_epoch?cursor:UINT64_MAX,.epoch=have_epoch?epoch_first:UINT64_MAX,
                .aux=UINT64_MAX,.flags=TIVOO_TRACE_GAP}),NULL,NULL);
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
            if (afe->reset_buffer(data)!=1) failure="reset_buffer failed";
            else if (afe->reset_vad(data)!=1) failure="reset_vad failed";
            if (failure) {
                TIVOO_LOGE(TAG,"AFE reset failed: %s rx_gaps=%u feed_errors=%u fetch_errors=%llu resets=%llu",
                    failure,atomic_load(&rx_gaps),atomic_load(&feed_errors),
                    (unsigned long long)fetch_errors,(unsigned long long)resets);
                atomic_store(&fatal,true);
                continue;
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
        /* The locked 2mic vendor library computes VAD in fetch_with_delay,
         * after reading enhanced PCM. Reset only VAD, on its sole owner,
         * before the first entirely post-gate fetch. Do not reset the ring
         * or WakeNet, and keep the tail of a crossing frame in history. */
        if (flow->gate_open && vad_gate_pending && cursor>=flow->gate) {
            if (afe->reset_vad(data)!=1) {
                TIVOO_LOGE(TAG,"AFE gate reset_vad failed; recovering");
                request_reset();
                continue;
            }
            vad_gate_pending=false;
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
        if (!atomic_load(&usable) && !atomic_load(&reset_requested)) {
            publish_available(true);
            // A feed-side fault racing publication still wins.
            if (atomic_load(&reset_requested)) publish_available(false);
            else TIVOO_LOGI(TAG,"AFE available: valid feed/fetch sample=%llu rx_gaps=%u",
                (unsigned long long)cursor,atomic_load(&rx_gaps));
        }
        if (atomic_load(&reset_requested)) continue;
        tivoo_s3_local_turn_tick();
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
        /* A gate may have been opened by the tick/controls after this
         * vendor result was evaluated. Keep its legal PCM, not its VAD. */
        const bool vad_valid=!(flow->gate_open && vad_gate_pending);
        if (atomic_load(&reset_requested)) continue;
        /* The vendor owns both pointers; copy before the next fetch. Cache
         * is recorded separately, never prepended or assigned a sample index. */
        tivoo_trace_record((&(tivoo_trace_header_t){.kind=TIVOO_TRACE_FETCH,
            .index=cursor,.epoch=epoch_first,.aux=flow->gate_open?flow->gate:UINT64_MAX,
            .count=count,.extra=r->vad_cache_size/sizeof(int16_t),
            .flags=(r->vad_state==VAD_SPEECH?TIVOO_TRACE_SPEECH:0)|
                   (vad_valid?TIVOO_TRACE_VAD_VALID:0)|
                   (flow->gate_open?TIVOO_TRACE_GATE_OPEN:0)|
                   (flow->prompt?TIVOO_TRACE_PROMPT:0)}),r->data,r->vad_cache);
        tivoo_afe_flow_frame(flow,cursor,r->data,count,r->vad_state==VAD_SPEECH,vad_valid,
            wait_neutral ? WAKENET_NO_DETECT : r->wakeup_state,r->raw_data_channels,
            r->wakenet_model_index,r->wake_word_index,r->vad_cache_size/sizeof(int16_t));
        cursor+=count;
        if (esp_timer_get_time()-report>=10000000) {
            report=esp_timer_get_time();
            ESP_LOGI(TAG,"feed=%u fetch=%llu feed_errors=%u fetch_errors=%llu rx_gaps=%u resets=%llu overruns=%u missed_eof=%u capture_overruns=%u capture_stack=%u cache_samples_ignored=%llu ring_free_pct=%.3f feed_max_us=%u fetch_wait_max_us=%u stack=%u/%u internal_min=%zu internal_largest=%zu dma_largest=%zu psram_free=%zu",
                atomic_load(&feed_calls),(unsigned long long)fetch_calls,
                atomic_load(&feed_errors),(unsigned long long)fetch_errors,
                atomic_load(&rx_gaps),(unsigned long long)resets,
                tivoo_audio_capture_overruns(),tivoo_audio_capture_missed_eofs(),
                atomic_load(&capture_overruns),atomic_load(&capture_stack),
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
    return c && c->aec_init && c->aec_mode==AEC_MODE_SR_HIGH_PERF &&
        c->afe_type==AFE_TYPE_SR && c->afe_mode==AFE_MODE_HIGH_PERF &&
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
    config=afe_config_init("MMNR", models, AFE_TYPE_SR, AFE_MODE_HIGH_PERF);
    if (!config) goto fail;
    config->aec_init=true;
    config->aec_mode=AEC_MODE_SR_HIGH_PERF;
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
    ESP_LOGI(TAG,"effective AFE SR HIGH_PERF MMNR BSS=%d NS=%d VAD mode=%d speech/noise/delay=%d/%d/%d energy=%.1f wake_mode=%d AGC=%d/%d AEC filter=%d mem=%d",
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
    input=heap_caps_malloc(feed_size*4*sizeof(int16_t),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    flow=heap_caps_malloc(sizeof(*flow),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    controls=xQueueCreate(4,sizeof(gate_control_t));
    capture_queue_storage=heap_caps_malloc(CAPTURE_QUEUE_FRAMES*sizeof(captured_frame_t),
        MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if (capture_queue_storage)
        captured=xQueueCreateStatic(CAPTURE_QUEUE_FRAMES,sizeof(captured_frame_t),
            capture_queue_storage,&capture_queue_control);
    if (!input || !flow || !controls || !captured) goto fail;
    tivoo_afe_flow_init(flow,word_count,sink,ctx);
    /* Hardware profiling: 2mic SR feed needs its own core. Keep capture
     * above fetch on core0 so vendor processing cannot stall the DMA drain. */
    if (xTaskCreatePinnedToCore(capture_task,"afe_capture",4096,NULL,8,&capture_handle,0)!=pdPASS ||
        xTaskCreatePinnedToCore(feed_task,"afe_feed",4096,NULL,7,&feed_handle,1)!=pdPASS ||
        xTaskCreatePinnedToCore(fetch_task,"afe_fetch",4096,NULL,5,&fetch_handle,0)!=pdPASS) goto fail;
    tivoo_trace_start();
    xTaskNotifyGive(fetch_handle);
    xTaskNotifyGive(feed_handle);
    xTaskNotifyGive(capture_handle);
    return ESP_OK;
fail:
    ESP_LOGE(TAG,"local AFE initialization failed (%s), model=%s; no remote KWS fallback",
        esp_err_to_name(err),TIVOO_AFE_MODEL_ID);
    if (feed_handle) { vTaskDelete(feed_handle); feed_handle=NULL; }
    if (capture_handle) { vTaskDelete(capture_handle); capture_handle=NULL; }
    if (fetch_handle) { vTaskDelete(fetch_handle); fetch_handle=NULL; }
    if (controls) { vQueueDelete(controls); controls=NULL; }
    if (captured) { vQueueDelete(captured); captured=NULL; }
    free(capture_queue_storage); capture_queue_storage=NULL;
    free(input); input=NULL;
    free(flow); flow=NULL;
    if (data) { afe->destroy(data); data=NULL; }
    if (config) afe_config_free(config);
    if (models) { esp_srmodel_deinit(models); models=NULL; }
    free(word_storage); word_storage=NULL;
    word_count=0;
    return err;
}
