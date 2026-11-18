#pragma once
#include "uart_wire.h"

typedef struct {
    uint32_t epoch, last_epoch;
    void *ctx;
    int (*enqueue)(void *,const uart_wire_packet_t *);
    void (*client)(void *,uint32_t);
} uart_router_t;
int uart_router_accept(uart_router_t *,const uart_wire_packet_t *);
void uart_router_reset(uart_router_t *);

#define UART_REVERSE_CAPACITY 8192
typedef struct {
    size_t head, count;
    uint8_t bytes[UART_REVERSE_CAPACITY];
} uart_reverse_ring_t;
void uart_reverse_clear(uart_reverse_ring_t *);
bool uart_reverse_push(uart_reverse_ring_t *,const uint8_t *,size_t);
size_t uart_reverse_peek(const uart_reverse_ring_t *,uint8_t *,size_t);
void uart_reverse_consume(uart_reverse_ring_t *,size_t);
