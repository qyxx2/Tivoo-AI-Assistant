/* Run the actual debug export task with a fake scheduler and time source.
 * No board or microphones are needed to exercise the one-shot lifetime. */
#include "p68_trace.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void (*task)(void *);
static unsigned delays;
static int64_t clock_us;
static uint32_t rx[320];
static int16_t tx[160], enhanced[160], cache[32];
static tivoo_trace_header_t h={.kind=TIVOO_TRACE_RAW,.index=3200,.epoch=0,
    .aux=3122,.flags=TIVOO_TRACE_REFERENCE_VALID,.count=160,.extra=160};

int64_t esp_timer_get_time(void) {return clock_us;}
int xTaskCreatePinnedToCore(void (*f)(void *),const char *name,unsigned size,void *arg,
        unsigned priority,void *out,int core)
{
    (void)name;(void)size;(void)arg;(void)priority;(void)out;(void)core;
    task=f;return 1;
}
void vTaskDelay(unsigned ms)
{
    ++delays;
    if(delays==1) {
        assert(ms==15000);
        tivoo_trace_record(&h,rx,tx); // before active, ignored
    } else if(delays==2) {
        assert(ms==4000);
        for(unsigned i=0;i<160;++i) {
            rx[2*i]=(i+1U)<<16;rx[2*i+1]=(i+2U)<<16;tx[i]=(int16_t)(i+1);
            enhanced[i]=(int16_t)(500+i);
        }
        cache[0]=-321;
        tivoo_trace_record(&h,rx,tx);
        tivoo_trace_header_t f={.kind=TIVOO_TRACE_FETCH,.index=1600,.epoch=1600,
            .aux=1637,.flags=TIVOO_TRACE_GATE_OPEN|TIVOO_TRACE_VAD_VALID,
            .count=160,.extra=32};
        tivoo_trace_record(&f,enhanced,cache);
        memset(rx,0,sizeof(rx));memset(tx,0,sizeof(tx));
        memset(enhanced,0,sizeof(enhanced));memset(cache,0,sizeof(cache));
        // Fill beyond one stream's capacity; no partial record.
        for(unsigned i=0;i<900;++i) {
            h.index+=160;h.aux+=160;
            tivoo_trace_record(&h,rx,tx);
        }
        clock_us+=4000000;
        tivoo_trace_record(&f,enhanced,cache); // after deadline, ignored
        return;
    } else {
        tivoo_trace_record(&h,rx,tx); // exporting, ignored
    }
    clock_us+=(int64_t)ms*1000;
}
void vTaskDelete(void *arg) {(void)arg;}
int main(void)
{
    tivoo_trace_start();
    assert(task);
    task(NULL);
    tivoo_trace_record(&h,rx,tx); // after buffers released: must be inert
    return 0;
}
