#include "uart_router.h"
#include <assert.h>
#include <string.h>
static unsigned queued, last_epoch, commands;
static int enqueue(void *ctx,const uart_wire_packet_t *p) {
    (void)ctx;
    if (queued==32) return -1;
    queued++;
    if (p->type==UW_COMMAND) commands++;
    return 0;
}
static void client(void *ctx,uint32_t epoch) {(void)ctx;last_epoch=epoch;}
int main(void) {
    uart_router_t r={.enqueue=enqueue,.client=client};
    static uart_wire_packet_t p={.type=UW_COMMAND,.epoch=1,.size=7,.payload={0x69,1,2,3,4,5,6}};
    assert(uart_router_accept(&r,&p)==1);
    p.type=UW_OPEN;p.size=0;
    assert(uart_router_accept(&r,&p)==0 && last_epoch==1);
    p.type=UW_COMMAND;p.size=7;
    assert(uart_router_accept(&r,&p)==0 && commands==1);
    p.type=UW_FRAME;p.size=4608;
    /* Original raw frame: length=4604, checksum of length bytes and payload. */
    memset(p.payload,0x69,p.size);
    p.payload[0]=1;p.payload[1]=0xfc;p.payload[2]=0x11;
    uint32_t sum=0;for(unsigned i=1;i<4605;i++) sum+=p.payload[i];
    /* Use 4-byte checksum if needed: maximum 4608 frame with 2-byte sum only,
       keep payload small except for an embedded command marker. */
    memset(p.payload+3,0,4602);p.payload[10]=0x69;
    sum=0;for(unsigned i=1;i<4605;i++) sum+=p.payload[i];
    p.payload[4605]=sum;p.payload[4606]=sum>>8;p.payload[4607]=2;
    for(unsigned i=1;i<32;i++) assert(uart_router_accept(&r,&p)==0);
    assert(uart_router_accept(&r,&p)==-1);
    queued--; assert(uart_router_accept(&r,&p)==0);
    p.payload[4606]^=1;assert(uart_router_accept(&r,&p)==1);
    p.type=UW_CLOSE;p.size=0;
    assert(uart_router_accept(&r,&p)==0 && last_epoch==0);
    p.type=UW_OPEN;
    assert(uart_router_accept(&r,&p)==1); /* old client cannot reopen */
    p.epoch=2;
    assert(uart_router_accept(&r,&p)==0 && last_epoch==2);
    p.type=UW_COMMAND;p.epoch=1;p.size=7;
    assert(uart_router_accept(&r,&p)==1);
    uart_router_reset(&r);assert(last_epoch==0);
    uart_reverse_ring_t q={0}; static uint8_t data[8192],out[8192];
    for(unsigned i=0;i<sizeof(data);i++) data[i]=(uint8_t)i;
    assert(uart_reverse_push(&q,data,8192));
    assert(!uart_reverse_push(&q,data,1));
    assert(uart_reverse_peek(&q,out,4608)==4608 && !memcmp(data,out,4608));
    uart_reverse_consume(&q,4608);
    assert(uart_reverse_push(&q,data,4608));
    assert(uart_reverse_peek(&q,out,8192)==8192);
    assert(!memcmp(data+4608,out,3584) && !memcmp(data,out+3584,4608));
    uart_reverse_clear(&q);assert(!uart_reverse_peek(&q,out,8192));
    return 0;
}
