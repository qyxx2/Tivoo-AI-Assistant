#include <stddef.h>
#include <stdint.h>
#include "tivoo_spp.h"

static tivoo_spp_queue_result_t s_frame_result = TIVOO_SPP_QUEUE_QUEUED;

void tivoo_spp_host_set_frame_result(tivoo_spp_queue_result_t result)
{
    s_frame_result = result;
}

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

tivoo_spp_queue_result_t tivoo_spp_queue_frame(
    const uint8_t *frame, size_t size)
{
    (void)frame;
    (void)size;
    return s_frame_result;
}
