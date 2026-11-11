#include <stddef.h>
#include <stdint.h>
#include "tivoo_spp.h"

bool tivoo_spp_queue_connect(const uint8_t peer[6])
{
    (void)peer;
    return true;
}

bool tivoo_spp_queue_disconnect(const uint8_t peer[6])
{
    (void)peer;
    return true;
}

bool tivoo_spp_queue_frame(const uint8_t *frame, size_t size)
{
    (void)frame;
    (void)size;
    return true;
}
