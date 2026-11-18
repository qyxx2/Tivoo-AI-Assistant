#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define UART_WIRE_PAYLOAD 4608
#define UART_WIRE_DECODED 4632
#define UART_WIRE_ENCODED 4652
enum {
    UW_HELLO=1, UW_HELLO_ACK, UW_PING, UW_STATUS,
    UW_OPEN=0x10, UW_CLOSE, UW_COMMAND, UW_FRAME, UW_REVERSE, UW_ACK, UW_ERROR
};
typedef struct {
    uint64_t token;
    uint32_t seq, epoch;
    uint16_t size;
    uint8_t type;
    uint8_t payload[UART_WIRE_PAYLOAD];
} uart_wire_packet_t;
typedef struct {
    size_t size;
    bool dropping;
    uint8_t encoded[UART_WIRE_ENCODED-1];
} uart_wire_stream_t;
typedef void (*uart_wire_handler_t)(void *, const uart_wire_packet_t *);
size_t uart_wire_encode(uint8_t type, uint64_t token, uint32_t seq, uint32_t epoch,
                        const void *data, uint16_t size, uint8_t *out);
bool uart_wire_decode(const uint8_t *encoded, size_t size, uart_wire_packet_t *out);
unsigned uart_wire_feed(uart_wire_stream_t *stream, const uint8_t *data, size_t size,
                        uart_wire_packet_t *scratch, uart_wire_handler_t handler, void *ctx);
