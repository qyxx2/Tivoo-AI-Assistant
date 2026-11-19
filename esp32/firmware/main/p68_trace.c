#include "p68_trace.h"
#include <string.h>

_Static_assert(sizeof(tivoo_trace_header_t)==40, "trace v1 header size");

bool tivoo_trace_append(tivoo_trace_buffer_t *b, const tivoo_trace_header_t *h,
                        const void *first, const void *second)
{
    const size_t width=h->kind==TIVOO_TRACE_RAW ? 8 : 2;
    if (b->used>b->capacity || b->capacity-b->used<sizeof(*h)) goto drop;
    const size_t remaining=b->capacity-b->used-sizeof(*h);
    if (h->count>remaining/width) goto drop;
    const size_t n=h->count*width;
    if (h->extra>(remaining-n)/2 || (n && !first) || (h->extra && !second)) goto drop;
    const size_t m=h->extra*2;
    uint8_t *dst=b->data+b->used;
    memcpy(dst,h,sizeof(*h));
    if(n) memcpy(dst+sizeof(*h),first,n);
    if(m) memcpy(dst+sizeof(*h)+n,second,m);
    b->used+=sizeof(*h)+n+m;
    return true;
drop:
    ++b->dropped;
    return false;
}

#if defined(ESP_PLATFORM) && defined(CONFIG_TIVOO_P68_CALIBRATION_TRACE)
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>

/* Single explicitly enabled boot capture, never a recorder in normal builds.
 * A short mutex only protects memory copies; UART export happens afterwards. */
#define RAW_BYTES 1400000U
#define AFE_BYTES 600000U
#define DURATION_US 4000000
static tivoo_trace_buffer_t raw, enhanced;
static SemaphoreHandle_t mutex;
static atomic_bool active;
static int64_t deadline;

void tivoo_trace_record(const tivoo_trace_header_t *h, const void *a, const void *b)
{
    if(!atomic_load(&active)) return;
    xSemaphoreTake(mutex,portMAX_DELAY);
    if(atomic_load(&active) && esp_timer_get_time()<deadline) {
        tivoo_trace_buffer_t *stream=(h->kind==TIVOO_TRACE_RAW ||
            h->kind==TIVOO_TRACE_CAPTURE_ERROR) ? &raw : &enhanced;
        tivoo_trace_append(stream,h,a,b);
    }
    xSemaphoreGive(mutex);
}

static void dump(const char *name,const tivoo_trace_buffer_t *b)
{
    static const char hex[]="0123456789abcdef";
    char line[513];
    printf("P68TRACE BEGIN %s %u %zu\n",name,b->dropped,b->used);
    for(size_t i=0;i<b->used;) {
        size_t n=b->used-i;
        if(n>256) n=256;
        for(size_t j=0;j<n;++j) {
            uint8_t v=b->data[i+j];
            line[2*j]=hex[v>>4]; line[2*j+1]=hex[v&15];
        }
        line[2*n]=0;
        printf("P68TRACE DATA %s %zu %s\n",name,i,line);
        i+=n;
        vTaskDelay(1);
    }
    printf("P68TRACE END %s\n",name);
}

static void trace_task(void *arg)
{
    (void)arg;
    printf("P68TRACE armed: begins in %d seconds; 4s capture\n",CONFIG_TIVOO_P68_TRACE_DELAY_SECONDS);
    vTaskDelay(pdMS_TO_TICKS(CONFIG_TIVOO_P68_TRACE_DELAY_SECONDS*1000));
    printf("P68TRACE capture start\n");
    deadline=esp_timer_get_time()+DURATION_US;
    atomic_store(&active,true);
    vTaskDelay(pdMS_TO_TICKS(DURATION_US/1000));
    atomic_store(&active,false);
    xSemaphoreTake(mutex,portMAX_DELAY);
    xSemaphoreGive(mutex); /* no writer can touch the buffers after this */
    dump("raw",&raw);
    dump("afe",&enhanced);
    fflush(stdout);
    free(raw.data); free(enhanced.data);
    vTaskDelete(NULL);
}
void tivoo_trace_start(void)
{
    raw=(tivoo_trace_buffer_t){.capacity=RAW_BYTES,
        .data=heap_caps_malloc(RAW_BYTES,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT)};
    enhanced=(tivoo_trace_buffer_t){.capacity=AFE_BYTES,
        .data=heap_caps_malloc(AFE_BYTES,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT)};
    mutex=xSemaphoreCreateMutex();
    if(!raw.data || !enhanced.data || !mutex ||
       xTaskCreatePinnedToCore(trace_task,"p68_trace",3072,NULL,1,NULL,0)!=pdPASS) {
        printf("P68TRACE unavailable: allocation/task failed\n");
        free(raw.data); free(enhanced.data);
        if(mutex) vSemaphoreDelete(mutex);
    }
}
#endif
