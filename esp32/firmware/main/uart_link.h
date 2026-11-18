#pragma once
#include "uart_wire.h"
typedef struct {
    bool master, ready, acknowledged, outstanding, pending;
    uint64_t token, retired, last_rx, next_ping, deadline;
    uint32_t tx_seq, rx_seq, tx_epoch;
    unsigned ack_timeouts, heartbeat_timeouts, sequence_errors, max_ack_wait_ms;
    void *ctx;
    bool (*emit)(void *, const uart_wire_packet_t *);
    int (*receive)(void *, const uart_wire_packet_t *); /* -1 wait, 0 accepted, 1 reject */
    void (*reset)(void *);
    uint64_t (*new_token)(void *);
    void (*status)(void *, uint8_t *);
    uart_wire_packet_t incoming, outgoing;
} uart_link_t;
void uart_link_init(uart_link_t *,bool,void *,bool (*)(void *,const uart_wire_packet_t *),
    int (*)(void *,const uart_wire_packet_t *),void (*)(void *),uint64_t (*)(void *),
    void (*)(void *,uint8_t *));
void uart_link_invalidate(uart_link_t *);
void uart_link_tick(uart_link_t *,uint64_t);
void uart_link_receive(uart_link_t *,const uart_wire_packet_t *,uint64_t);
bool uart_link_send(uart_link_t *,uint8_t,uint32_t,const void *,uint16_t,uint64_t);
bool uart_link_control(uart_link_t *,uint8_t,uint32_t,uint32_t,const void *,uint16_t);
void uart_link_status(uart_link_t *);
