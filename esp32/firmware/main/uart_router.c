#include "uart_router.h"
#include "tivoo_frame_stream.h"
#include <string.h>

void uart_router_reset(uart_router_t *r)
{
    r->epoch=r->last_epoch=0; r->client(r->ctx,0);
}
int uart_router_accept(uart_router_t *r,const uart_wire_packet_t *p)
{
    if(!p->epoch) return 1;
    if(p->type==UW_OPEN) {
        if(r->epoch || p->size || p->epoch<=r->last_epoch) return 1;
        r->epoch=r->last_epoch=p->epoch; r->client(r->ctx,p->epoch); return 0;
    }
    if(r->epoch!=p->epoch) return 1;
    if(p->type==UW_CLOSE) {
        if(p->size) return 1;
        r->epoch=0; r->client(r->ctx,0); return 0;
    }
    if(p->type==UW_COMMAND) {
        if(p->size!=7 || (p->payload[0]!=0x69 && p->payload[0]!=0x96)) return 1;
    } else if(p->type==UW_FRAME) {
        if(p->size<6 || p->size>UART_WIRE_PAYLOAD ||
           tivoo_frame_get_size(p->payload,p->size)!=p->size) return 1;
    } else return 1;
    return r->enqueue(r->ctx,p);
}
void uart_reverse_clear(uart_reverse_ring_t *r) {r->head=r->count=0;}
bool uart_reverse_push(uart_reverse_ring_t *r,const uint8_t *p,size_t n)
{
    if(!n) return true;
    if(!p || n>UART_REVERSE_CAPACITY-r->count) return false;
    size_t tail=(r->head+r->count)%UART_REVERSE_CAPACITY;
    size_t first=UART_REVERSE_CAPACITY-tail;
    if(first>n) first=n;
    memcpy(r->bytes+tail,p,first);
    memcpy(r->bytes,p+first,n-first);
    r->count+=n;
    return true;
}
size_t uart_reverse_peek(const uart_reverse_ring_t *r,uint8_t *out,size_t n)
{
    if(n>r->count) n=r->count;
    if(!n) return 0;
    size_t first=UART_REVERSE_CAPACITY-r->head;
    if(first>n) first=n;
    memcpy(out,r->bytes+r->head,first);
    memcpy(out+first,r->bytes,n-first);
    return n;
}
void uart_reverse_consume(uart_reverse_ring_t *r,size_t n)
{
    if(n>r->count) n=r->count;
    r->head=(r->head+n)%UART_REVERSE_CAPACITY; r->count-=n;
}
