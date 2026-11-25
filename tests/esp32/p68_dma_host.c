/* Execute real capture/output ISR and task routing with a 12-slot driver ring.
 * The fake driver owns slots; only a fresh channel starts with calloc PCM. */
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include "driver/i2s_std.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "audio_capture.h"
#include "audio_output_manager.h"

struct channel {
    bool enabled, tx;
    unsigned index;
    uint32_t slots[TIVOO_OUTPUT_DMA_BLOCKS][2*TIVOO_OUTPUT_BLOCK];
    i2s_event_callbacks_t cb;
    void *ctx;
};
static struct channel *tx, *rx;
static unsigned creates, disables, ticks;
static bool fail_new, skip_rx, skip_tx, stall, stall_tx;
static unsigned notifications, notification_waits, isr_notifications, semaphore_gives;
static bool stop_on_wait, writer_woken;
_Thread_local unsigned p68_critical_depth;
static void step(void);
SemaphoreHandle_t xSemaphoreCreateMutex(void) {
    static StaticSemaphore_t mutex={.pending=1,.mutex=true};return &mutex;
}
SemaphoreHandle_t xSemaphoreCreateBinaryStatic(StaticSemaphore_t *s) {s->pending=0;return s;}
BaseType_t xSemaphoreGive(SemaphoreHandle_t s) {assert(!p68_critical_depth);++semaphore_gives;s->pending=1;return pdTRUE;}
BaseType_t xSemaphoreGiveFromISR(SemaphoreHandle_t s,BaseType_t *wake) {
    assert(!p68_critical_depth);++semaphore_gives;++isr_notifications;s->pending=1;*wake=pdTRUE;return pdTRUE;
}
BaseType_t xSemaphoreTake(SemaphoreHandle_t s,TickType_t wait) {
    assert(!p68_critical_depth);
    if(wait) ++notification_waits;
    if(!s->pending && wait) {
        if(stop_on_wait) tivoo_audio_output_stop(1);
        else step();
    }
    bool ready=s->pending;s->pending=0;
    if(!ready) ticks+=wait/5;
    return ready ? pdTRUE : pdFALSE;
}
static void step(void)
{
    if(stall || !tx || !rx || !tx->enabled || !rx->enabled) return;
    unsigned i=tx->index++%TIVOO_OUTPUT_DMA_BLOCKS;
    unsigned j=rx->index++%TIVOO_OUTPUT_DMA_BLOCKS;
    i2s_event_data_t out={tx->slots[i],sizeof(tx->slots[i])};
    i2s_event_data_t in={rx->slots[j],sizeof(rx->slots[j])};
    for(unsigned n=0;n<2*TIVOO_OUTPUT_BLOCK;n++) rx->slots[j][n]=0x12340000;
#ifdef P68_DMA_TX_OBSERVER
    P68_DMA_TX_OBSERVER(tx->slots[i]);
#endif
    if(!skip_tx && !stall_tx) writer_woken=tx->cb.on_sent(tx,&out,tx->ctx);
    if(!skip_rx) rx->cb.on_recv(rx,&in,rx->ctx);
    skip_tx=skip_rx=false;
    ++ticks;
}
esp_err_t i2s_new_channel(const i2s_chan_config_t *cfg,i2s_chan_handle_t *t,i2s_chan_handle_t *r)
{
    assert(cfg->dma_desc_num==12 && cfg->dma_frame_num==160);
    if(fail_new) return ESP_ERR_NO_MEM;
    assert(!tx && !rx);
    *t=tx=calloc(1,sizeof(*tx)); *r=rx=calloc(1,sizeof(*rx)); tx->tx=true;
    ++creates;
    return ESP_OK;
}
esp_err_t i2s_channel_init_std_mode(i2s_chan_handle_t h,const i2s_std_config_t *f)
{ (void)h; (void)f; return ESP_OK; }
esp_err_t i2s_channel_register_event_callback(i2s_chan_handle_t h,const i2s_event_callbacks_t *cb,void *ctx)
{ assert(!h->enabled); h->cb=*cb; h->ctx=ctx; return ESP_OK; }
esp_err_t i2s_channel_enable(i2s_chan_handle_t h)
{ assert(!h->enabled); h->enabled=true; return ESP_OK; }
esp_err_t i2s_channel_disable(i2s_chan_handle_t h)
{ assert(h->enabled); h->enabled=false; ++disables; return ESP_OK; }
esp_err_t i2s_del_channel(i2s_chan_handle_t h)
{ assert(!h->enabled); if(h==tx) tx=NULL; else rx=NULL; free(h); return ESP_OK; }
esp_err_t i2s_channel_read(i2s_chan_handle_t h,void *p,size_t n,size_t *r,unsigned t)
{ (void)h;(void)p;(void)n;(void)r;(void)t;return ESP_ERR_TIMEOUT; }
QueueHandle_t xQueueCreateStatic(size_t n,size_t s,uint8_t *buf,StaticQueue_t *q)
{ *q=(StaticQueue_t){.buf=buf,.n=n,.size=s}; return q; }
BaseType_t xQueueSendFromISR(QueueHandle_t q,const void *item,BaseType_t *wake)
{ (void)wake; if(q->count==q->n)return pdFALSE; memcpy(q->buf+((q->head+q->count)%q->n)*q->size,item,q->size); ++q->count;return pdTRUE; }
BaseType_t xQueueReceive(QueueHandle_t q,void *item,unsigned wait)
{ (void)wait; if(!q->count) step(); if(!q->count)return pdFALSE; memcpy(item,q->buf+q->head*q->size,q->size); q->head=(q->head+1)%q->n;--q->count;return pdTRUE; }
unsigned uxQueueMessagesWaiting(QueueHandle_t q) { return q->count; }
BaseType_t xQueueReset(QueueHandle_t q) {q->head=q->count=0;return pdTRUE;}
void vTaskDelay(unsigned t) { ticks+=t; }
TaskHandle_t xTaskGetCurrentTaskHandle(void) {return &notifications;}
void xTaskNotifyGive(TaskHandle_t t) {assert(!p68_critical_depth);if(t){assert(t==&notifications);++notifications;}}
void vTaskNotifyGiveFromISR(TaskHandle_t t,BaseType_t *wake) {
    assert(!p68_critical_depth);assert(t==&notifications);++notifications;++isr_notifications;*wake=pdTRUE;
}
unsigned ulTaskNotifyTake(BaseType_t clear,TickType_t wait) {
    assert(clear==pdTRUE);++notification_waits;
    if(!notifications && wait) {
        if(stop_on_wait) tivoo_audio_output_stop(1);
        else step();
    }
    unsigned n=notifications;notifications=0;
    if(!n) ticks+=wait/5;
    return n;
}
unsigned uxTaskGetStackHighWaterMark(void *unused) { (void)unused;return 4096; }
BaseType_t xTaskCreatePinnedToCore(void (*f)(void *),const char *name,unsigned stack,void *arg,unsigned prio,void *out,int core)
{ (void)stack;(void)prio;(void)out;(void)core; if(!strcmp(name,"dma_recover")) f(arg); return pdPASS; }
int xPortGetCoreID(void) {return 0;}
void vTaskDelete(void *arg) {(void)arg;}
int64_t esp_timer_get_time(void) { return (int64_t)ticks*5000; }
size_t heap_caps_get_minimum_free_size(unsigned c) {(void)c;return 0;}
size_t heap_caps_get_free_size(unsigned c) {(void)c;return 0;}

static tivoo_capture_frame_t frame;
static void valid_frame(void)
{
    for(unsigned i=0;i<50;i++) {
        if(tivoo_audio_capture_next(&frame)==ESP_OK && frame.reference_valid && !frame.gap) return;
    }
    assert(!"no valid frame after bounded recovery");
}
int main(int argc,char **argv)
{
    assert(argc==2);
    assert(tivoo_audio_capture_start()==ESP_OK);
    if(!strcmp(argv[1],"startup")) {
        step(); // learn descriptor 0
        skip_rx=true;step(); // miss descriptor 1 during discovery
        valid_frame();
        assert(creates==2 && disables==2);
        assert(frame.left[79]==0x1234 && frame.reference[79]==0);
    } else {
        valid_frame();
        uint64_t before=frame.first_sample;
        uint64_t initial_epoch=frame.epoch_first_raw;
        assert(initial_epoch==0 && frame.tx_first_sample==2*before);
        valid_frame();
        assert(frame.epoch_first_raw==initial_epoch && frame.first_sample==before+80);
        assert(frame.tx_first_sample==2*frame.first_sample);
        assert(frame.raw_slots[0]==0x12340000 && frame.raw_tx[0]==0);
        int16_t pcm[TIVOO_OUTPUT_QUEUE_SAMPLES];
        for(unsigned i=0;i<TIVOO_OUTPUT_QUEUE_SAMPLES;i++) pcm[i]=1234;
        if(!strcmp(argv[1],"normal")) {
            assert(tivoo_audio_output_begin(1));
        } else assert(tivoo_audio_output_begin_prompt(1));
        assert(tivoo_audio_output_try_write(1,pcm,TIVOO_OUTPUT_QUEUE_SAMPLES)==TIVOO_OUTPUT_QUEUE_SAMPLES);
        if(!strcmp(argv[1],"writer") || !strcmp(argv[1],"writer_stop")) {
            stop_on_wait=!strcmp(argv[1],"writer_stop");
            esp_err_t result=tivoo_audio_output_write(1,pcm,TIVOO_OUTPUT_BLOCK);
            assert(notification_waits>0);
            assert(result==(stop_on_wait ? ESP_ERR_INVALID_STATE : ESP_OK));
            if(!stop_on_wait) assert(isr_notifications && writer_woken);
            unsigned before_notifications=semaphore_gives;
            tivoo_audio_output_stop(1);step();
            assert(semaphore_gives==before_notifications); /* waiter unregistered */
            return 0;
        }
        for(unsigned i=0;i<12;i++) {step();(void)tivoo_audio_capture_next(&frame);}
        if(!strcmp(argv[1],"normal")) {
            // Long ordinary streaming gap is not EOF and does not reset RX.
            for(unsigned i=0;i<60;i++) {step();(void)tivoo_audio_capture_next(&frame);}
            assert(!tivoo_audio_output_drained(1));
            assert(tivoo_audio_output_try_write(1,pcm,1)==1);
            step(); (void)tivoo_audio_capture_next(&frame);
            unsigned last=(tx->index-1)%12;
            assert(tx->slots[last][0]==0); /* recovery waits for its watermark */
            tivoo_audio_output_stop(1);
            for(unsigned i=0;i<14;i++) {step();(void)tivoo_audio_capture_next(&frame);}
            uint64_t boundary=0;
            assert(tivoo_audio_output_release_drained(1,&boundary) && boundary>0);
            assert(creates==1 && disables==0 && frame.first_sample>before);
            assert(tivoo_audio_output_begin_prompt(2));
            return 0;
        }
        assert(tx->slots[tx->index%12][0]==(1234U<<16));
        skip_tx=true;step();step();
        uint64_t end=0,clock=0;
        int16_t ref[160];
        assert(!tivoo_audio_output_reference_raw(before*2,ref,160));
        assert(!tivoo_audio_output_prompt_drain(1,&end,&clock));
        assert(tivoo_audio_output_failed(1));
        tivoo_audio_output_stop(1);
        assert(!tivoo_audio_output_drained(1));
        if(!strcmp(argv[1],"failure")) fail_new=true;
        if(!strcmp(argv[1],"failure")) {
            for(unsigned i=0;i<5;i++) (void)tivoo_audio_capture_next(&frame);
            assert(!tivoo_audio_capture_running());
            assert(!tivoo_audio_output_begin_prompt(2));
            assert(creates==1 && disables==2);
            return 0;
        }
        assert(tivoo_audio_capture_next(&frame)!=ESP_OK); // explicit gap to AFE
        assert(creates==2 && disables==2);
        if(!strcmp(argv[1],"early_release")) {
            tivoo_audio_output_end(1);
            assert(!tivoo_audio_output_begin_prompt(2)); // not yet proven new epoch
        }
        if(!strcmp(argv[1],"repeat") || !strcmp(argv[1],"stalled_tx")) {
            if(!strcmp(argv[1],"repeat")) { step();skip_rx=true;step(); }
            else stall_tx=true;
            for(unsigned i=0;i<80;i++) (void)tivoo_audio_capture_next(&frame);
            assert(!tivoo_audio_capture_running() && !tivoo_audio_output_available());
            assert(creates==2 && disables==4); // one attempt, then stop both
            return 0;
        }
        valid_frame();
        assert(creates==2 && disables==2 && frame.first_sample>before);
        assert(frame.epoch_first_raw>initial_epoch && frame.epoch_first_raw<2*frame.first_sample);
        assert(!tivoo_audio_output_prompt_drain(1,&end,&clock));
        assert(!tivoo_audio_output_drained(1));
        assert(!tivoo_audio_output_release_drained(1,&end));
        tivoo_audio_output_end(1);
        assert(tivoo_audio_output_begin_prompt(2));
        for(unsigned i=0;i<12;i++) for(unsigned n=0;n<2*TIVOO_OUTPUT_BLOCK;n++) assert(tx->slots[i][n]==0);
    }
    return 0;
}
