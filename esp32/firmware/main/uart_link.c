#include "uart_link.h"
#include <string.h>
void uart_link_init(uart_link_t *l,bool master,void *ctx,
    bool (*emit)(void *,const uart_wire_packet_t *),
    int (*receive)(void *,const uart_wire_packet_t *),void (*reset)(void *),
    uint64_t (*token)(void *),void (*status)(void *,uint8_t *))
{
    memset(l,0,sizeof(*l)); l->master=master; l->ctx=ctx; l->emit=emit;
    l->receive=receive; l->reset=reset; l->new_token=token; l->status=status;
    l->tx_seq=l->rx_seq=1;
}
void uart_link_invalidate(uart_link_t *l)
{
    if(l->token) l->retired=l->token;
    l->ready=l->acknowledged=l->outstanding=l->pending=false;
    l->token=l->last_rx=l->next_ping=l->deadline=0;
    l->tx_seq=l->rx_seq=1; l->tx_epoch=0;
    l->reset(l->ctx);
}
bool uart_link_control(uart_link_t *l,uint8_t t,uint32_t seq,uint32_t epoch,
                       const void *p,uint16_t n)
{
    if (!l->token || n>UART_WIRE_PAYLOAD || (n&&!p)) return false;
    uart_wire_packet_t *o=&l->outgoing;
    o->type=t; o->token=l->token; o->seq=seq; o->epoch=epoch; o->size=n;
    if(n) memcpy(o->payload,p,n);
    return l->emit(l->ctx,o);
}
void uart_link_status(uart_link_t *l)
{
    if(!l->master && l->ready) {
        uint8_t p[8]; l->status(l->ctx,p);
        (void)uart_link_control(l,UW_STATUS,0,0,p,8);
    }
}
bool uart_link_send(uart_link_t *l,uint8_t t,uint32_t epoch,const void *p,uint16_t n,uint64_t now)
{
    if(!l->ready || l->outstanding || !epoch) return false;
    if(l->tx_seq==UINT32_MAX) {uart_link_invalidate(l); return false;}
    if(l->master ? (t<UW_OPEN || t>UW_FRAME) : t!=UW_REVERSE) return false;
    if(!uart_link_control(l,t,l->tx_seq,epoch,p,n)) return false;
    l->outstanding=true; l->tx_epoch=epoch; l->deadline=now+20000;
    return true;
}
static void accept_pending(uart_link_t *l)
{
    if(!l->pending) return;
    const uart_wire_packet_t *p=&l->incoming;
    int result=l->receive(l->ctx,p);
    if(result<0) return;
    uint8_t value=result ? 1 : 0;
    l->pending=false;
    if(!uart_link_control(l,UW_ACK,p->seq,p->epoch,&value,1) || result || l->rx_seq==UINT32_MAX) {
        uart_link_invalidate(l); return;
    }
    l->rx_seq++;
}
void uart_link_tick(uart_link_t *l,uint64_t now)
{
    if(l->ready && (now-l->last_rx>=3000 ||
        (l->outstanding && now>=l->deadline))) {
        if(l->outstanding && now>=l->deadline) l->ack_timeouts++;
        else l->heartbeat_timeouts++;
        uart_link_invalidate(l); return;
    }
    accept_pending(l);
    if(!l->master) return;
    if(!l->token) {
        l->token=l->new_token(l->ctx);
        if(!l->token || l->token==l->retired) {l->token=0;return;}
    }
    if(now>=l->next_ping) {
        (void)uart_link_control(l,l->ready?UW_PING:UW_HELLO,0,0,NULL,0);
        l->next_ping=now+1000;
    }
}
void uart_link_receive(uart_link_t *l,const uart_wire_packet_t *p,uint64_t now)
{
    if(!l->master && p->type==UW_HELLO) {
        if(p->token==l->retired) return;
        if(p->token!=l->token) {
            uart_link_invalidate(l);
            l->token=p->token;
        }
        l->ready=true; l->last_rx=now;
        (void)uart_link_control(l,UW_HELLO_ACK,0,0,NULL,0);
        uart_link_status(l);
        return;
    }
    if(!l->token || p->token!=l->token) return;
    if(l->master && p->type==UW_HELLO_ACK) {l->acknowledged=true; return;}
    if(l->master && p->type==UW_STATUS && l->acknowledged) {
        l->ready=true; l->last_rx=now; (void)l->receive(l->ctx,p); return;
    }
    if(!l->ready) return;
    if(!l->master && p->type==UW_PING) {
        l->last_rx=now; uart_link_status(l); return;
    }
    if(p->type==UW_ACK) {
        if(!l->outstanding || p->seq!=l->tx_seq || p->epoch!=l->tx_epoch || p->payload[0]) {
            l->sequence_errors++;
            uart_link_invalidate(l); return;
        }
        unsigned wait=(unsigned)(now-(l->deadline-20000));
        if(wait>l->max_ack_wait_ms) l->max_ack_wait_ms=wait;
        l->outstanding=false; l->tx_seq++; return;
    }
    if(l->master && p->type==UW_ERROR) {(void)l->receive(l->ctx,p); return;}
    if(l->master ? p->type!=UW_REVERSE : (p->type<UW_OPEN || p->type>UW_FRAME)) return;
    if(l->pending || p->seq!=l->rx_seq) {l->sequence_errors++;uart_link_invalidate(l);return;}
    l->incoming=*p; l->pending=true; accept_pending(l);
}
