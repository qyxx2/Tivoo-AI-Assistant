#include "uart_transport.h"
#include "uart_link.h"
#include "uart_router.h"
#include "control_bridge.h"
#include "device_status.h"
#include "diagnostics.h"
#include "tivoo_spp.h"
#include "driver/uart.h"
#include "esp_heap_caps.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include <stdatomic.h>
#include <string.h>

#define PORT UART_NUM_1
#define RING_BYTES 8192
#define CONTROL_DEPTH 16
#define TAG "uart_bridge"

typedef struct {
    uint64_t token;
    uint32_t seq, epoch;
    uint16_t size;
    uint8_t type, payload[8];
} small_packet_t;

typedef struct {
    uart_link_t link;
    uart_wire_stream_t stream;
    uart_wire_packet_t decoded, writing;
    uint8_t encoded[UART_WIRE_ENCODED];
    SemaphoreHandle_t lock;
    QueueHandle_t small_queue, data_queue, events;
    TaskHandle_t writer;
    atomic_bool writer_fault;
    unsigned crc_errors, rx_overflows;
#ifdef TIVOO_P68_B2_BRIDGE
    uart_router_t router;
    uart_reverse_ring_t reverse;
    uint8_t reverse_chunk[UART_WIRE_PAYLOAD];
    uint32_t reverse_epoch, generation;
    uint32_t request_errors[8];
    unsigned reverse_peak;
    bool reverse_failed, reverse_error_sent;
#else
    uint32_t epoch, next_epoch, closing_epoch;
    bool client_fault;
    uint8_t reported[8];
    bool reported_valid;
    uint64_t next_status_retry;
#endif
} transport_t;

static transport_t *s;
static portMUX_TYPE s_snapshot_mux = portMUX_INITIALIZER_UNLOCKED;
static const char *const errors[] = {
    "", "spp_init_failed", "spp_connect_failed", "spp_disconnect_failed",
    "spp_tx_queue_full", "spp_write_failed", "reverse_queue_full", "spp_not_connected"
};
#ifdef TIVOO_P68_B2_BRIDGE
static atomic_bool s_spp_available;
static atomic_bool s_status_dirty;
static atomic_uint s_error_bits;
#else
static uint8_t s_snapshot[8];
#endif

static uint64_t now_ms(void) {return (uint64_t)(esp_timer_get_time()/1000);}
static void lock(void) {xSemaphoreTake(s->lock,portMAX_DELAY);}
static void unlock(void) {xSemaphoreGive(s->lock);}

static bool emit(void *ctx,const uart_wire_packet_t *p)
{
    transport_t *t=ctx;
    BaseType_t ok;
    if(p->type==UW_COMMAND || p->type==UW_FRAME || p->type==UW_REVERSE ||
       p->type==UW_OPEN || p->type==UW_CLOSE) {
        ok=xQueueSend(t->data_queue,p,0);
    } else {
        if(p->size>8) return false;
        small_packet_t q={.token=p->token,.seq=p->seq,.epoch=p->epoch,
                          .size=p->size,.type=p->type};
        memcpy(q.payload,p->payload,p->size);
        ok=xQueueSend(t->small_queue,&q,0);
    }
    if(ok==pdTRUE) xTaskNotifyGive(t->writer);
    return ok==pdTRUE;
}

static uint64_t new_token(void *ctx)
{
    (void)ctx;
    uint64_t token;
    esp_fill_random(&token,sizeof(token));
    return token;
}

#ifdef TIVOO_P68_B2_BRIDGE
void tivoo_uart_bridge_set_available(bool available)
{
    atomic_store(&s_spp_available,available);
    if(!available) atomic_fetch_or(&s_error_bits,1u<<1);
}
void tivoo_uart_bridge_status_changed(void) {atomic_store(&s_status_dirty,true);}
void tivoo_uart_bridge_error(const char *code)
{
    for(unsigned i=1;i<sizeof(errors)/sizeof(errors[0]);i++) {
        if(!strcmp(code,errors[i])) {
            atomic_fetch_or(&s_error_bits,1u<<i);
            return;
        }
    }
}
/* Worker results are associated with the generation accepted into its FIFO.
 * Retired generations must never be relabelled as the new TCP owner's epoch. */
void tivoo_uart_bridge_request_error(uint32_t generation,const char *code)
{
    if(!s) return;
    for(unsigned i=1;i<sizeof(errors)/sizeof(errors[0]);i++) {
        if(strcmp(code,errors[i])) continue;
        portENTER_CRITICAL(&s_snapshot_mux);
        if(generation==s->generation && s->reverse_epoch)
            s->request_errors[i]=s->reverse_epoch;
        portEXIT_CRITICAL(&s_snapshot_mux);
        return;
    }
}
static void bridge_client(void *ctx,uint32_t epoch)
{
    transport_t *t=ctx;
    portENTER_CRITICAL(&s_snapshot_mux);
    t->reverse_epoch=epoch;
    if(++t->generation==0) ++t->generation;
    uart_reverse_clear(&t->reverse);
    memset(t->request_errors,0,sizeof(t->request_errors));
    t->reverse_failed=t->reverse_error_sent=false;
    portEXIT_CRITICAL(&s_snapshot_mux);
    tivoo_spp_set_control_generation(t->generation);
}
static bool bridge_reverse(const uint8_t *p,size_t n,uint32_t generation,bool tagged)
{
    if(!s) return true;
    portENTER_CRITICAL(&s_snapshot_mux);
    bool ok=true;
    if(s->reverse_epoch && (!tagged || generation==s->generation)) {
        ok=!s->reverse_failed && uart_reverse_push(&s->reverse,p,n);
        if(s->reverse.count>s->reverse_peak) s->reverse_peak=s->reverse.count;
        if(!ok) {
            s->reverse_failed=true;
            uart_reverse_clear(&s->reverse);
        }
    }
    portEXIT_CRITICAL(&s_snapshot_mux);
    return ok;
}
bool tivoo_control_spp_data(const uint8_t *p,size_t n)
{
    return bridge_reverse(p,n,0,false);
}
void tivoo_uart_bridge_hint(uint32_t generation,uint8_t hint)
{
    (void)bridge_reverse(&hint,1,generation,true);
}
static int bridge_enqueue(void *ctx,const uart_wire_packet_t *p)
{
    (void)ctx;
    if(!atomic_load(&s_spp_available)) return 1;
    if(p->type==UW_COMMAND) {
        bool ok=p->payload[0]==0x69 ? tivoo_spp_queue_connect(p->payload+1)
                                  : tivoo_spp_queue_disconnect(p->payload+1);
        return ok?0:-1;
    }
    return tivoo_spp_queue_frame(p->payload,p->size)==TIVOO_SPP_QUEUE_QUEUED?0:-1;
}
static int receive(void *ctx,const uart_wire_packet_t *p)
{
    transport_t *t=ctx;
    return uart_router_accept(&t->router,p);
}
static void status(void *ctx,uint8_t *p)
{
    (void)ctx;
    tivoo_spp_link_state_t state=TIVOO_SPP_LINK_DISCONNECTED;
    bool valid=false;
    memset(p,0,8);
    if(atomic_load(&s_spp_available)) tivoo_spp_get_status(&state,p+2,&valid);
    if(valid && !memcmp(p+2,(uint8_t[6]){0},6)) valid=false;
    if(state==TIVOO_SPP_LINK_CONNECTED && !valid) state=TIVOO_SPP_LINK_DISCONNECTED;
    p[0]=state; p[1]=valid;
    if(!valid) memset(p+2,0,6);
}
static void reset(void *ctx)
{
    transport_t *t=ctx;
    xQueueReset(t->data_queue);
    uart_router_reset(&t->router);
}
static void service_role(transport_t *t,uint64_t now)
{
    if(!t->link.ready) return;
    if(atomic_exchange(&s_status_dirty,false)) uart_link_status(&t->link);
    unsigned bits=atomic_exchange(&s_error_bits,0);
    for(unsigned i=1;i<sizeof(errors)/sizeof(errors[0]);i++) {
        uint8_t code=i;
        if(bits&(1u<<i)) {
            if(!uart_link_control(&t->link,UW_ERROR,0,0,&code,1))
                atomic_fetch_or(&s_error_bits,1u<<i);
        }
        portENTER_CRITICAL(&s_snapshot_mux);
        uint32_t request_epoch=t->request_errors[i];
        portEXIT_CRITICAL(&s_snapshot_mux);
        if(request_epoch && uart_link_control(&t->link,UW_ERROR,0,request_epoch,&code,1)) {
            portENTER_CRITICAL(&s_snapshot_mux);
            t->request_errors[i]=0;
            portEXIT_CRITICAL(&s_snapshot_mux);
        }
    }
    portENTER_CRITICAL(&s_snapshot_mux);
    uint32_t epoch=t->reverse_epoch;
    bool overflow=t->reverse_failed && !t->reverse_error_sent;
    size_t n=t->reverse_failed?0:uart_reverse_peek(&t->reverse,t->reverse_chunk,
                                                    sizeof(t->reverse_chunk));
    portEXIT_CRITICAL(&s_snapshot_mux);
    if(overflow) {
        uint8_t code=6;
        if(uart_link_control(&t->link,UW_ERROR,0,epoch,&code,1)) {
            portENTER_CRITICAL(&s_snapshot_mux);
            t->reverse_error_sent=true;
            portEXIT_CRITICAL(&s_snapshot_mux);
        }
    }
    if(epoch && n && !t->link.outstanding &&
        uart_link_send(&t->link,UW_REVERSE,epoch,t->reverse_chunk,n,now)) {
        portENTER_CRITICAL(&s_snapshot_mux);
        if(!t->reverse_failed) uart_reverse_consume(&t->reverse,n);
        portEXIT_CRITICAL(&s_snapshot_mux);
    }
}
#else
static void publish_status(transport_t *t,const uint8_t p[8])
{
    static const char *const events[]={
        "spp_disconnected","spp_connecting","spp_connected"};
    portENTER_CRITICAL(&s_snapshot_mux);
    memcpy(s_snapshot,p,8);
    portEXIT_CRITICAL(&s_snapshot_mux);
    if(!t->reported_valid || memcmp(t->reported,p,8)) {
        if(tivoo_device_status_report_event(events[p[0]],p[1]?p+2:NULL)) {
            memcpy(t->reported,p,8);
            t->reported_valid=true;
        }
    }
}
static void status(void *ctx,uint8_t *p) {(void)ctx;(void)p;}
static void reset(void *ctx)
{
    transport_t *t=ctx;
    xQueueReset(t->data_queue);
    t->epoch=t->closing_epoch=0;
    t->client_fault=true;
    if(t->reported_valid || t->link.ready || s_snapshot[0] || s_snapshot[1])
        tivoo_report_error("spp_not_connected",TAG,"UART session unavailable");
    static const uint8_t offline[8]={0};
    publish_status(t,offline);
    /* Even if diagnostics could not enqueue offline, re-handshake must
     * publish a fresh connected snapshot (including the same physical peer). */
    if(memcmp(t->reported,offline,8)) t->reported_valid=false;
    t->next_status_retry=now_ms()+1000;
}
static int receive(void *ctx,const uart_wire_packet_t *p)
{
    transport_t *t=ctx;
    if(p->type==UW_STATUS) {
        publish_status(t,p->payload);
        return 0;
    }
    if(p->type==UW_ERROR) {
        tivoo_report_error(errors[p->payload[0]],TAG,"Classic SPP bridge error");
        /* A failed peer switch cannot forward frames to the old peer.
         * Retire this 7777 owner so HA resends its latest target on reconnect.
         * The same epoch isolation already applies to reverse overflow. */
        if((p->payload[0]==3 || p->payload[0]==6) && p->epoch && p->epoch==t->epoch)
            t->client_fault=true;
        return 0;
    }
    if(p->epoch==t->closing_epoch && p->epoch!=t->epoch) return 0;
    if(p->epoch!=t->epoch || !t->epoch) return 1;
    if(t->client_fault) return 0;
    return tivoo_control_try_reverse(p->payload,p->size)?0:-1;
}
static void service_role(transport_t *t,uint64_t now)
{
    if(now>=t->next_status_retry && !t->link.ready && (!t->reported_valid || memcmp(t->reported,(uint8_t[8]){0},8))) {
        static const uint8_t offline[8]={0};
        publish_status(t,offline);
        t->next_status_retry=now+1000;
    }
}

void tivoo_spp_get_status(tivoo_spp_link_state_t *state,uint8_t peer[6],bool *valid)
{
    portENTER_CRITICAL(&s_snapshot_mux);
    if(state) *state=s_snapshot[0];
    if(valid) *valid=s_snapshot[1];
    if(peer) memcpy(peer,s_snapshot+2,6);
    portEXIT_CRITICAL(&s_snapshot_mux);
}
bool tivoo_uart_client_open(void)
{
    if(!s) return false;
    lock();
    bool ok=false;
    if(s->link.ready && !s->link.outstanding && !s->epoch) {
        if(++s->next_epoch==0) {
            uart_link_invalidate(&s->link);
        } else if(uart_link_send(&s->link,UW_OPEN,s->next_epoch,NULL,0,now_ms())) {
            s->epoch=s->next_epoch; s->client_fault=false; ok=true;
        }
    }
    unlock();
    return ok;
}
void tivoo_uart_client_close(void)
{
    if(!s) return;
    lock();
    if(s->epoch) {
        if(s->link.outstanding ||
           !uart_link_send(&s->link,UW_CLOSE,s->epoch,NULL,0,now_ms())) {
            uart_link_invalidate(&s->link);
        } else {
            s->closing_epoch=s->epoch; s->epoch=0;
        }
    }
    unlock();
}
bool tivoo_uart_client_valid(void)
{
    if(!s) return false;
    lock();
    bool ok=s->link.ready && s->epoch && !s->client_fault;
    unlock(); return ok;
}
bool tivoo_uart_client_can_read(void)
{
    if(!s) return false;
    lock();
    bool ok=s->link.ready && s->epoch && !s->client_fault && !s->link.outstanding;
    unlock(); return ok;
}
static bool send_data(uint8_t type,const void *p,size_t n)
{
    if(!s || n>UART_WIRE_PAYLOAD) return false;
    lock();
    bool ok=!s->client_fault && uart_link_send(&s->link,type,s->epoch,p,n,now_ms());
    unlock(); return ok;
}
bool tivoo_spp_queue_connect(const uint8_t peer[6])
{
    uint8_t cmd[7]={0x69}; memcpy(cmd+1,peer,6);return send_data(UW_COMMAND,cmd,7);
}
bool tivoo_spp_queue_disconnect(const uint8_t peer[6])
{
    uint8_t cmd[7]={0x96}; memcpy(cmd+1,peer,6);return send_data(UW_COMMAND,cmd,7);
}
tivoo_spp_queue_result_t tivoo_spp_queue_frame(const uint8_t *p,size_t n)
{
    return send_data(UW_FRAME,p,n)?TIVOO_SPP_QUEUE_QUEUED:TIVOO_SPP_QUEUE_FULL;
}
#endif

static void decoded(void *ctx,const uart_wire_packet_t *p)
{
    transport_t *t=ctx;
    uart_link_receive(&t->link,p,now_ms());
}
static void writer_task(void *arg)
{
    transport_t *t=arg;
    for(;;) {
        small_packet_t small;
        uart_wire_packet_t *p=&t->writing;
        if(xQueueReceive(t->small_queue,&small,0)==pdTRUE) {
            p->type=small.type;p->token=small.token;p->seq=small.seq;
            p->epoch=small.epoch;p->size=small.size;
            memcpy(p->payload,small.payload,p->size);
        } else if(xQueueReceive(t->data_queue,p,0)==pdTRUE) {
            lock(); bool current=t->link.token==p->token; unlock();
            if(!current) continue;
        } else {
            ulTaskNotifyTake(pdTRUE,portMAX_DELAY);continue;
        }
        size_t n=uart_wire_encode(p->type,p->token,p->seq,p->epoch,p->payload,p->size,t->encoded);
        if(!n || uart_write_bytes(PORT,t->encoded,n)!=(int)n)
            atomic_store(&t->writer_fault,true);
    }
}
static void reader_task(void *arg)
{
    transport_t *t=arg;
    uint8_t bytes[512];
    uint64_t next_log=0;
    for(;;) {
        uart_event_t event;
        bool overflow=false;
        while(xQueueReceive(t->events,&event,0)==pdTRUE) {
            if(event.type==UART_FIFO_OVF || event.type==UART_BUFFER_FULL) overflow=true;
        }
        if(overflow) {
            uart_flush_input(PORT);
            xQueueReset(t->events);
        }
        int n=uart_read_bytes(PORT,bytes,sizeof(bytes),pdMS_TO_TICKS(10));
        lock();
        if(overflow || atomic_exchange(&t->writer_fault,false)) {
            t->rx_overflows+=overflow;
            memset(&t->stream,0,sizeof(t->stream));
            uart_link_invalidate(&t->link);
        }
        if(n>0) t->crc_errors+=uart_wire_feed(&t->stream,bytes,n,&t->decoded,decoded,t);
        uint64_t now=now_ms();
        uart_link_tick(&t->link,now);
        service_role(t,now);
        if(now>=next_log && (t->link.ready || t->crc_errors || t->rx_overflows ||
                            t->link.ack_timeouts || t->link.heartbeat_timeouts)) {
            next_log=now+10000;
            unsigned reverse_peak, spp_peak=0;
#ifdef TIVOO_P68_B2_BRIDGE
            portENTER_CRITICAL(&s_snapshot_mux);
            reverse_peak=t->reverse_peak;
            portEXIT_CRITICAL(&s_snapshot_mux);
            spp_peak=tivoo_spp_queue_peak();
#else
            reverse_peak=tivoo_control_reverse_peak();
#endif
            TIVOO_LOGI(TAG,"decode_errors=%u uart_overflows=%u ack_timeouts=%u heartbeat_timeouts=%u seq_errors=%u ack_max_ms=%u reverse_peak=%u spp_peak=%u",
                t->crc_errors,t->rx_overflows,t->link.ack_timeouts,t->link.heartbeat_timeouts,
                t->link.sequence_errors,t->link.max_ack_wait_ms,reverse_peak,spp_peak);
        }
        unlock();
    }
}

esp_err_t tivoo_uart_transport_start(void)
{
    if(s) return ESP_ERR_INVALID_STATE;
    transport_t *t=heap_caps_calloc(1,sizeof(*t),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!t) return ESP_ERR_NO_MEM;
    t->lock=xSemaphoreCreateMutex();
    t->small_queue=xQueueCreate(CONTROL_DEPTH,sizeof(small_packet_t));
    t->data_queue=xQueueCreate(1,sizeof(uart_wire_packet_t));
    esp_err_t err=ESP_ERR_NO_MEM;
    bool driver_installed=false;
    if(!t->lock || !t->small_queue || !t->data_queue) goto fail;
    uart_config_t cfg={
        .baud_rate=921600,.data_bits=UART_DATA_8_BITS,.parity=UART_PARITY_DISABLE,
        .stop_bits=UART_STOP_BITS_1,.flow_ctrl=UART_HW_FLOWCTRL_DISABLE,
        .source_clk=UART_SCLK_DEFAULT};
#ifdef TIVOO_P68_B2_BRIDGE
    const int tx=18,rx=19;
    t->router=(uart_router_t){.ctx=t,.enqueue=bridge_enqueue,.client=bridge_client};
    const bool master=false;
#else
    const int tx=17,rx=18;
    const bool master=true;
#endif
    err=uart_param_config(PORT,&cfg);
    if(err!=ESP_OK) goto fail;
    err=uart_set_pin(PORT,tx,rx,UART_PIN_NO_CHANGE,UART_PIN_NO_CHANGE);
    if(err!=ESP_OK) goto fail;
    err=uart_driver_install(PORT,RING_BYTES,RING_BYTES,32,&t->events,0);
    if(err!=ESP_OK) goto fail;
    driver_installed=true;
    uart_link_init(&t->link,master,t,emit,receive,reset,new_token,status);
    s=t;
    if(xTaskCreate(writer_task,"tivoo_uart_tx",8192,t,6,&t->writer)!=pdPASS ||
       xTaskCreate(reader_task,"tivoo_uart_rx",8192,t,6,NULL)!=pdPASS)
    {
        err=ESP_ERR_NO_MEM;
        goto fail;
    }
    return ESP_OK;
fail:
    s=NULL;
    if(t->writer) vTaskDelete(t->writer);
    if(driver_installed) uart_driver_delete(PORT);
    if(t->data_queue) vQueueDelete(t->data_queue);
    if(t->small_queue) vQueueDelete(t->small_queue);
    if(t->lock) vSemaphoreDelete(t->lock);
    heap_caps_free(t);
    return err;
}
