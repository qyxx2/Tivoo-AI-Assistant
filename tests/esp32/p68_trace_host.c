#include "p68_trace.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    uint8_t buf[4096];
    tivoo_trace_buffer_t b={.data=buf,.capacity=sizeof(buf)};
    uint32_t rx[320];
    int16_t tx[160], pcm[160], cache[32];
    for (unsigned i=0;i<160;i++) {
        rx[2*i]=(i+1U)<<16; rx[2*i+1]=(uint32_t)(uint16_t)(-1-(int)i)<<16;
        tx[i]=(int16_t)(1000+i); pcm[i]=(int16_t)(2000+i);
    }
    for(unsigned i=0;i<32;i++) cache[i]=(int16_t)(-1000-(int)i);
    tivoo_trace_header_t h={.kind=TIVOO_TRACE_RAW,.index=4160,.epoch=0,
        .aux=4082,.flags=TIVOO_TRACE_REFERENCE_VALID,.count=160,.extra=160};
    assert(tivoo_trace_append(&b,&h,rx,tx));
    memset(rx,0,sizeof(rx)); memset(tx,0,sizeof(tx)); // source pointer lifetime
    h=(tivoo_trace_header_t){.kind=TIVOO_TRACE_FETCH,.index=2080,.epoch=2080,
        .aux=2117,.flags=TIVOO_TRACE_GATE_OPEN|TIVOO_TRACE_SPEECH,.count=160,.extra=32};
    assert(tivoo_trace_append(&b,&h,pcm,cache));
    memset(pcm,0,sizeof(pcm)); memset(cache,0,sizeof(cache));
    h=(tivoo_trace_header_t){.kind=TIVOO_TRACE_RAW,.index=4320,.epoch=0,
        .aux=4242,.flags=TIVOO_TRACE_GAP,.count=160,.extra=160};
    assert(tivoo_trace_append(&b,&h,rx,tx)); // invalid reference is explicit
    size_t saved=b.used;
    assert(!tivoo_trace_append(&b,&h,rx,tx)); // no partial record
    assert(b.used==saved && b.dropped==1);
    assert(fwrite(buf,1,b.used,stdout)==b.used);
    return 0;
}
