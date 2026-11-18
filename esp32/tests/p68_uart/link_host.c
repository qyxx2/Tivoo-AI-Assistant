#include "uart_link.h"
#include <assert.h>
#include <string.h>

typedef struct {
    uart_link_t l;
    uart_wire_packet_t sent[16];
    unsigned count, accepted, resets;
    bool full;
} endpoint;
static bool emit(void *ctx,const uart_wire_packet_t *p) {
    endpoint *e=ctx; assert(e->count<16);
    e->sent[e->count++]=*p; return true;
}
static int receive(void *ctx,const uart_wire_packet_t *p) {
    endpoint *e=ctx;
    if (p->type==UW_STATUS) return 0;
    if (e->full) return -1;
    e->accepted++;
    return 0;
}
static void reset(void *ctx) { ((endpoint *)ctx)->resets++; }
static uint64_t token(void *ctx) {return 47+((endpoint *)ctx)->resets;}
static void status(void *ctx,uint8_t *p){(void)ctx; memset(p,0,8);}
static void deliver(endpoint *a,endpoint *b,uint64_t now) {
    for(unsigned i=0;i<a->count;i++) uart_link_receive(&b->l,&a->sent[i],now);
    a->count=0;
}
static unsigned packets;
static void decoded(void *ctx,const uart_wire_packet_t *p) {
    (void)ctx; assert(p->type==UW_REVERSE && p->size==4608); packets++;
}
int main(void) {
    static endpoint a,b;
    uart_link_init(&a.l,true,&a,emit,receive,reset,token,status);
    uart_link_init(&b.l,false,&b,emit,receive,reset,token,status);
    uart_link_tick(&a.l,1); deliver(&a,&b,1); deliver(&b,&a,1);
    assert(a.l.ready && b.l.ready);
    assert(uart_link_send(&a.l,UW_OPEN,1,NULL,0,2));
    deliver(&a,&b,2); deliver(&b,&a,2);
    assert(!a.l.outstanding && b.accepted==1);
    const uint8_t cmd[]={0x69,1,2,3,4,5,6};
    const uint8_t rev[]={0,0x69,0x96};
    a.full=b.full=true;
    assert(uart_link_send(&a.l,UW_COMMAND,1,cmd,7,3));
    assert(uart_link_send(&b.l,UW_REVERSE,1,rev,3,3));
    assert(!uart_link_send(&a.l,UW_COMMAND,1,cmd,7,3));
    deliver(&a,&b,3); deliver(&b,&a,3);
    assert(a.l.pending && b.l.pending && a.l.outstanding && b.l.outstanding);
    uart_link_tick(&a.l,1002); deliver(&a,&b,1002); deliver(&b,&a,1002);
    assert(a.l.ready && b.l.ready); /* heartbeat despite both directions full */
    a.full=b.full=false;
    uart_link_tick(&a.l,1003); uart_link_tick(&b.l,1003);
    deliver(&a,&b,1003); deliver(&b,&a,1003);
    assert(!a.l.outstanding && !b.l.outstanding && a.accepted==1 && b.accepted==2);
    uart_wire_packet_t stale={.type=UW_REVERSE,.token=a.l.token-1,.seq=2,.epoch=1,.size=1};
    uart_link_receive(&a.l,&stale,1004);
    assert(a.l.ready && a.accepted==1);
    assert(uart_link_send(&a.l,UW_COMMAND,1,cmd,7,1005));
    /* Keep valid heartbeat but suppress ACK: never retransmit. */
    deliver(&a,&b,1005);
    assert(b.accepted==3 && b.count==1 && b.sent[0].type==UW_ACK);
    b.count=0; /* Peer did accept it: lose only the ACK. */
    uint64_t old_token=a.l.token;
    for(uint64_t t=2000;t<=22000 && a.l.ready;t+=1000) {
        uart_link_tick(&a.l,t); deliver(&a,&b,t); deliver(&b,&a,t);
    }
    assert(!a.l.ready && !a.l.outstanding && b.accepted==3);
    uart_link_tick(&a.l,22001);deliver(&a,&b,22001);deliver(&b,&a,22001);
    assert(a.l.ready && b.l.ready && a.l.token!=old_token);
    assert(uart_link_send(&a.l,UW_OPEN,2,NULL,0,22002));
    uart_wire_packet_t duplicate=a.sent[0];
    deliver(&a,&b,22002);deliver(&b,&a,22002);
    assert(b.accepted==4);
    uart_link_receive(&b.l,&duplicate,22003);
    assert(!b.l.ready && b.accepted==4); /* no duplicate enqueue */
    uart_link_tick(&a.l,26001);
    assert(!a.l.ready);
    static uint8_t payload[4608],wire[4652],garbage[4700];
    memset(payload,0xa5,sizeof(payload)); memset(garbage,1,sizeof(garbage));
    size_t n=uart_wire_encode(UW_REVERSE,1,1,1,payload,sizeof(payload),wire);
    uart_wire_stream_t stream={0}; uart_wire_packet_t scratch;
    for(size_t i=0;i<n;i++) assert(!uart_wire_feed(&stream,wire+i,1,&scratch,decoded,NULL));
    assert(packets==1);
    assert(!uart_wire_feed(&stream,garbage,sizeof(garbage),&scratch,decoded,NULL));
    assert(uart_wire_feed(&stream,(uint8_t[]){0},1,&scratch,decoded,NULL)==1);
    assert(!uart_wire_feed(&stream,wire,n,&scratch,decoded,NULL));
    assert(packets==2);
    return 0;
}
