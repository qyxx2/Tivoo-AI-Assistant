#include "uart_wire.h"
#include <string.h>

/* COBS standard block coding (Cheshire/Baker); CRC-32/ISO-HDLC. */
static uint32_t crc32(const uint8_t *p, size_t n)
{
    uint32_t c=UINT32_MAX;
    while (n--) {
        c ^= *p++;
        for (unsigned i=0;i<8;i++) c=(c>>1)^((0u-(c&1u))&0xedb88320u);
    }
    return ~c;
}
static uint64_t get(const uint8_t *p, unsigned n)
{
    uint64_t v=0;
    for (unsigned i=0;i<n;i++) v|=(uint64_t)p[i]<<(8*i);
    return v;
}
static void put(uint8_t *p, uint64_t v, unsigned n)
{
    for (unsigned i=0;i<n;i++) p[i]=(uint8_t)(v>>(8*i));
}
static bool valid(uint8_t t,uint64_t token,uint32_t seq,uint32_t epoch,
                  const uint8_t *p,uint16_t n)
{
    if (!token || n>UART_WIRE_PAYLOAD || (n && !p)) return false;
    switch(t) {
    case UW_HELLO: case UW_HELLO_ACK: case UW_PING:
        return !seq && !epoch && !n;
    case UW_STATUS: {
        static const uint8_t zero[6]={0};
        return !seq && !epoch && n==8 && p[0]<=2 && p[1]<=1 &&
            (p[1] ? memcmp(p+2,zero,6)!=0 : !memcmp(p+2,zero,6)) &&
            (p[0]!=2 || p[1]);
    }
    case UW_OPEN: case UW_CLOSE: return seq && epoch && !n;
    case UW_COMMAND: return seq && epoch && n==7 && (p[0]==0x69 || p[0]==0x96);
    case UW_FRAME: return seq && epoch && n>=6;
    case UW_REVERSE: return seq && epoch && n>0;
    case UW_ACK: return seq && epoch && n==1 && p[0]<=1;
    case UW_ERROR: return !seq && n==1 && p[0]>=1 && p[0]<=7;
    default: return false;
    }
}
size_t uart_wire_encode(uint8_t t,uint64_t token,uint32_t seq,uint32_t epoch,
                        const void *data,uint16_t n,uint8_t *out)
{
    if (!out || !valid(t,token,seq,epoch,data,n)) return 0;
    uint8_t raw[UART_WIRE_DECODED];
    raw[0]=1; raw[1]=t; put(raw+2,n,2); put(raw+4,token,8);
    put(raw+12,seq,4); put(raw+16,epoch,4);
    if(n) memcpy(raw+20,data,n);
    put(raw+20+n,crc32(raw,20+n),4);
    size_t w=1, code_at=0;
    uint8_t code=1;
    for (size_t i=0;i<(size_t)n+24;i++) {
        if (raw[i]==0) {out[code_at]=code; code_at=w++; code=1;}
        else {
            out[w++]=raw[i];
            if (++code==255) {out[code_at]=code; code_at=w++; code=1;}
        }
    }
    out[code_at]=code; out[w++]=0;
    return w;
}
bool uart_wire_decode(const uint8_t *encoded,size_t n,uart_wire_packet_t *out)
{
    if(!encoded || !out || !n || n>=UART_WIRE_ENCODED) return false;
    uint8_t raw[UART_WIRE_DECODED];
    size_t r=0,w=0;
    while(r<n) {
        unsigned code=encoded[r++];
        if (!code || code-1>n-r || code-1>sizeof(raw)-w) return false;
        for (unsigned i=1;i<code;i++) {
            if(!encoded[r]) return false;
            raw[w++]=encoded[r++];
        }
        if(code!=255 && r<n) {
            if(w==sizeof(raw)) return false;
            raw[w++]=0;
        }
    }
    if(w<24 || raw[0]!=1) return false;
    uint16_t size=(uint16_t)get(raw+2,2);
    if(w!=(size_t)size+24 || get(raw+w-4,4)!=crc32(raw,w-4)) return false;
    uint64_t token=get(raw+4,8);
    uint32_t seq=(uint32_t)get(raw+12,4),epoch=(uint32_t)get(raw+16,4);
    if (!valid(raw[1],token,seq,epoch,raw+20,size)) return false;
    out->type=raw[1]; out->token=token; out->seq=seq; out->epoch=epoch; out->size=size;
    memcpy(out->payload,raw+20,size);
    return true;
}
unsigned uart_wire_feed(uart_wire_stream_t *s,const uint8_t *data,size_t n,
                        uart_wire_packet_t *scratch,uart_wire_handler_t handler,void *ctx)
{
    unsigned errors=0;
    while(n--) {
        uint8_t b=*data++;
        if(!b) {
            if(s->dropping) errors++;
            else if(s->size) {
                if(uart_wire_decode(s->encoded,s->size,scratch)) handler(ctx,scratch);
                else errors++;
            }
            s->dropping=false; s->size=0;
        } else if(!s->dropping) {
            if(s->size==sizeof(s->encoded)) s->dropping=true;
            else s->encoded[s->size++]=b;
        }
    }
    return errors;
}
