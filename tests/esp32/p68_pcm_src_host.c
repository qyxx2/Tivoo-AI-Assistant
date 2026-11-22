#include <assert.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include "audio_playback.h"
#include "audio_output_manager.h"
#include "esp_ae_rate_cvt.h"
#include "esp_audio_simple_dec.h"

/* Model vendor streaming history, capacity contract and 3:4 frame ratio.
 * This is not an implementation/quality test of the proprietary DSP. */
typedef struct {int16_t previous;} converter_t;
static unsigned opens, closes;
static bool src_error;
esp_ae_err_t esp_ae_rate_cvt_open(esp_ae_rate_cvt_cfg_t *c,void **h) {
    assert(c->src_rate==24000 && c->dest_rate==32000 && c->channel==1 && c->bits_per_sample==16);
    *h=calloc(1,sizeof(converter_t)); ++opens; return ESP_AE_ERR_OK;
}
esp_ae_err_t esp_ae_rate_cvt_get_max_out_sample_num(void *h,uint32_t n,uint32_t *out) {
    assert(h); *out=(n*4+2)/3+16; return ESP_AE_ERR_OK;
}
esp_ae_err_t esp_ae_rate_cvt_process(void *h,esp_ae_sample_t in,uint32_t n,esp_ae_sample_t out,uint32_t *count) {
    converter_t *c=h; int16_t *a=in,*b=out;
    if(src_error) return ESP_AE_ERR_FAIL;
    assert(n && n%3==0 && *count>=n*4/3);
    for(unsigned i=0,j=0;i<n;i+=3,j+=4) {
        b[j]=(c->previous+a[i])/2; b[j+1]=a[i]; b[j+2]=a[i+1]; b[j+3]=a[i+2]; c->previous=a[i+2];
    }
    *count=n*4/3; return ESP_AE_ERR_OK;
}
void esp_ae_rate_cvt_close(void *h) {assert(h);free(h);++closes;}
int esp_audio_simple_dec_open(void *c,void **h) {(void)c;*h=malloc(1);return 0;}
void esp_audio_simple_dec_close(void *h) {free(h);}
int esp_audio_simple_dec_get_info(void *h,esp_audio_simple_dec_info_t *i) {(void)h;(void)i;return -1;}
int esp_audio_simple_dec_process(void *h,esp_audio_simple_dec_raw_t *i,esp_audio_simple_dec_out_t *o) {(void)h;(void)i;(void)o;return -1;}

static tivoo_output_queue_t queue;
static int16_t captured[100000];
static size_t captured_count;
esp_err_t tivoo_audio_output_write(uint32_t g,const int16_t *p,size_t n) {
    while(n) {
        size_t k=tivoo_output_push(&queue,g,p,n);
        if(!k) return ESP_ERR_INVALID_STATE;
        /* Drain the real queue at its external I2S boundary. */
        while(queue.count) {
            captured[captured_count++]=queue.pcm[queue.read];
            queue.read=(queue.read+1)%TIVOO_OUTPUT_QUEUE_SAMPLES; --queue.count;
        }
        p+=k;n-=k;
    }
    return ESP_OK;
}
static void begin(uint32_t g) {memset(&queue,0,sizeof(queue));assert(tivoo_output_begin(&queue,g));captured_count=0;}
static uint8_t data[48008];
static size_t run(uint32_t rate,size_t n,bool irregular,int16_t *out) {
    begin(7);
    const unsigned before=opens;
    tivoo_audio_playback_t *p=tivoo_audio_playback_open(7,rate); assert(p);
    const size_t chunks[]={1,7,2305,2,63,4093,5};
    for(size_t pos=0,i=0;pos<n;) {
        size_t k=irregular ? chunks[i++%7] : n;
        if(k>n-pos) k=n-pos;
        assert(tivoo_audio_playback_feed(p,data+pos,k,false)==ESP_OK);pos+=k;
    }
    assert(tivoo_audio_playback_feed(p,NULL,0,true)==ESP_OK);
    assert(tivoo_audio_playback_has_pcm(p));
    memcpy(out,captured,captured_count*2);
    size_t count=captured_count;
    /* EOF is terminal; repeated or late data cannot append. */
    assert(tivoo_audio_playback_feed(p,data,2,false)==ESP_ERR_INVALID_STATE);
    tivoo_audio_playback_close(p);
    assert(opens-before==(rate==24000?1U:0U));return count;
}
int main(int argc,char **argv) {
    assert(argc==2);const char *s=argv[1];
    static int16_t whole[40000],split[40000];
    if(!strcmp(s,"unsupported")) {
        assert(!tivoo_audio_playback_open(7,16000));assert(!tivoo_audio_playback_open(7,48000));return 0;
    }
    if(!strcmp(s,"unaligned")) {
        for(unsigned rate=24000;rate<=32000;rate+=8000) {
            begin(7);tivoo_audio_playback_t *p=tivoo_audio_playback_open(7,rate);assert(p);
            assert(tivoo_audio_playback_feed(p,data,3,true)==ESP_ERR_INVALID_SIZE);tivoo_audio_playback_close(p);
        }return 0;
    }
    if(!strcmp(s,"cancel")) {
        begin(7);tivoo_audio_playback_t *old=tivoo_audio_playback_open(7,24000);assert(old);
        memset(data,0x25,sizeof(data));assert(tivoo_audio_playback_feed(old,data,101,false)==ESP_OK);
        assert(tivoo_output_stop(&queue,7));tivoo_output_end(&queue,7);assert(tivoo_output_begin(&queue,8));
        captured_count=0;
        assert(tivoo_audio_playback_feed(old,data+101,4000,true)==ESP_ERR_INVALID_STATE);
        assert(!captured_count);tivoo_audio_playback_close(old);
        tivoo_audio_playback_t *next=tivoo_audio_playback_open(8,24000);memset(data,0,sizeof(data));
        assert(tivoo_audio_playback_feed(next,data,2400,true)==ESP_OK);assert(captured_count==1600);
        for(size_t i=0;i<captured_count;i++) assert(captured[i]==0);
        tivoo_audio_playback_close(next);assert(opens==closes);return 0;
    }
    if(!strcmp(s,"src_error")) {
        begin(7);tivoo_audio_playback_t *p=tivoo_audio_playback_open(7,24000);assert(p);src_error=true;
        assert(tivoo_audio_playback_feed(p,data,2400,true)!=ESP_OK);assert(!captured_count);
        tivoo_audio_playback_close(p);assert(opens==closes);return 0;
    }
    for(unsigned i=0;i<24004;i++) {
        int16_t v=0;
        if(!strcmp(s,"constant")) v=-10000;
        if(!strcmp(s,"impulse") && (i==1151 || i==1152)) v=30000;
        if(!strcmp(s,"sweep") || !strcmp(s,"passthrough") || !strcmp(s,"tail")) v=(int16_t)(12000*sin(i*i*0.000003));
        data[2*i]=(uint8_t)v;data[2*i+1]=(uint16_t)v>>8;
    }
    uint32_t rate=!strcmp(s,"passthrough")?32000:24000;
    unsigned first=!strcmp(s,"tail")?1:24000,last=!strcmp(s,"tail")?5:24000;
    for(unsigned n=first;n<=last;n++) {
        size_t a=run(rate,n*2,false,whole),b=run(rate,n*2,true,split);
        assert(a==(rate==32000?n:(n*4+2)/3) && a==b);assert(!memcmp(whole,split,a*2));
        if(!strcmp(s,"constant")) {
            assert(whole[0]==-5000);
            for(size_t i=1;i<a;i++) assert(whole[i]==-10000);
        }
        if(!strcmp(s,"silence")) for(size_t i=0;i<a;i++) assert(whole[i]==0);
        if(!strcmp(s,"impulse")) {
            assert(whole[1534]==0 && whole[1535]==30000);
            assert(whole[1536]==30000 && whole[1537]==30000 && whole[1538]==0);
        }
        if(rate==32000) assert(!memcmp(whole,data,n*2) && opens==0);
    }
    assert(opens==closes);return 0;
}
