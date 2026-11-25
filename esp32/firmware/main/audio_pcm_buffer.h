#pragma once

#include <stdbool.h>
#include <stdatomic.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

/* Single producer/single consumer. Only task context touches PSRAM.
 * Unsigned monotonic cursors wrap naturally; capacity is a power of two. */
typedef struct {
    uint8_t *data;
    size_t capacity;
    atomic_uint read_pos, write_pos;
} tivoo_pcm_buffer_t;

static inline void tivoo_pcm_buffer_init(tivoo_pcm_buffer_t *b, uint8_t *data, size_t capacity)
{
    b->data=data;
    b->capacity=capacity;
    atomic_init(&b->read_pos,0);
    atomic_init(&b->write_pos,0);
}

static inline size_t tivoo_pcm_buffer_size(const tivoo_pcm_buffer_t *b)
{
    unsigned w=atomic_load(&b->write_pos), r=atomic_load(&b->read_pos);
    return (unsigned)(w-r);
}

static inline bool tivoo_pcm_buffer_ready(const tivoo_pcm_buffer_t *b, size_t prefill, bool eof)
{
    size_t n=tivoo_pcm_buffer_size(b);
    return n>=prefill || (eof && n!=0);
}

static inline size_t tivoo_pcm_buffer_push(tivoo_pcm_buffer_t *b, const uint8_t *data, size_t n)
{
    unsigned w=atomic_load(&b->write_pos), r=atomic_load(&b->read_pos);
    size_t space=b->capacity-(unsigned)(w-r);
    if (n>space) n=space;
    size_t i=w&(b->capacity-1), first=b->capacity-i;
    if (first>n) first=n;
    memcpy(b->data+i,data,first);
    memcpy(b->data,data+first,n-first);
    atomic_store(&b->write_pos,w+(unsigned)n);
    return n;
}

static inline size_t tivoo_pcm_buffer_pop(tivoo_pcm_buffer_t *b, uint8_t *data, size_t n)
{
    unsigned r=atomic_load(&b->read_pos), w=atomic_load(&b->write_pos);
    size_t available=(unsigned)(w-r);
    if (n>available) n=available;
    size_t i=r&(b->capacity-1), first=b->capacity-i;
    if (first>n) first=n;
    memcpy(data,b->data+i,first);
    memcpy(data+first,b->data,n-first);
    atomic_store(&b->read_pos,r+(unsigned)n);
    return n;
}
