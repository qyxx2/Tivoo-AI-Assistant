#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum { TIVOO_TRACE_RAW=1, TIVOO_TRACE_FETCH, TIVOO_TRACE_CAPTURE_ERROR,
       TIVOO_TRACE_GATE, TIVOO_TRACE_AFE_GAP };
enum { TIVOO_TRACE_GAP=1, TIVOO_TRACE_REFERENCE_VALID=2,
       TIVOO_TRACE_SPEECH=4, TIVOO_TRACE_VAD_VALID=8,
       TIVOO_TRACE_GATE_OPEN=16, TIVOO_TRACE_PROMPT=32,
       TIVOO_TRACE_OPEN_REQUESTED=64 };
/* Version 1, little endian. Index/epoch/aux in samples, with rates per kind.
 * RAW: 32k RX index/DMA base/TX index; count stereo u32 slots, extra mono s16.
 * FETCH: 16k cursor/AFE first feed/gate index; count enhanced + extra cache s16.
 * GATE: 16k next/AFE first feed/requested boundary, no payload.
 * ERROR/GAP: no payload, unknown indices UINT64_MAX. Cache has NO known index. */
typedef struct {
    uint64_t index, epoch, aux;
    uint32_t kind, flags, count, extra;
} tivoo_trace_header_t;
typedef struct {
    uint8_t *data;
    size_t capacity, used;
    unsigned dropped;
} tivoo_trace_buffer_t;
bool tivoo_trace_append(tivoo_trace_buffer_t *buffer, const tivoo_trace_header_t *header,
                        const void *first, const void *second);

#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#ifdef CONFIG_TIVOO_P68_CALIBRATION_TRACE
void tivoo_trace_start(void);
void tivoo_trace_record(const tivoo_trace_header_t *header, const void *first, const void *second);
#else
#define tivoo_trace_start() ((void)0)
#define tivoo_trace_record(...) ((void)0)
#endif
#endif
