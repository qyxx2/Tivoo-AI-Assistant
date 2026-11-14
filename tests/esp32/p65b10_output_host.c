#include <assert.h>

#include "audio_output_manager.h"

int main(void)
{
    tivoo_output_queue_t queue = {0};
    uint32_t dma[TIVOO_OUTPUT_BLOCK * 2];
    int16_t input[] = {INT16_MIN, 1234, INT16_MAX};

    assert(tivoo_output_begin(&queue, 1));
    assert(!tivoo_output_begin(&queue, 2));
    assert(tivoo_output_push(&queue, 1, input, 3) == 3);
    assert(tivoo_output_stop(&queue, 2) == false);
    assert(tivoo_output_refill(&queue, dma, 11) == 0);
    assert(!tivoo_output_drained(&queue, 1, 11));
    assert(tivoo_output_finish_input(&queue, 1));
    assert(tivoo_output_refill(&queue, dma, 12) == 3);
    assert(dma[0] == 0x80000000 && dma[1] == dma[0]);
    assert(dma[2] == 1234U * 65536 && dma[3] == dma[2]);
    assert(dma[6] == 0 && dma[7] == 0);
    assert(!tivoo_output_drained(&queue, 1, 12));
    assert(tivoo_output_drained(&queue, 1, 13));

    assert(tivoo_output_push(&queue, 1, input, 3) == 0);
    assert(tivoo_output_stop(&queue, 1));
    assert(tivoo_output_push(&queue, 1, input, 3) == 0);
    assert(tivoo_output_refill(&queue, dma, 13) == 0);
    assert(dma[0] == 0 && dma[1] == 0);
    assert(tivoo_output_drained(&queue, 1, 13));
    tivoo_output_end(&queue, 1);

    assert(tivoo_output_begin(&queue, 2));
    assert(!tivoo_output_stop(&queue, 1));
    tivoo_output_end(&queue, 1);
    assert(tivoo_output_push(&queue, 2, input, 3) == 3);
    assert(!tivoo_output_drained(&queue, 2, 200));
    assert(!tivoo_output_finish_input(&queue, 1));
    int16_t prefill[TIVOO_OUTPUT_PREFILL] = {0};
    assert(tivoo_output_push(&queue, 2, prefill, TIVOO_OUTPUT_PREFILL - 4)
        == TIVOO_OUTPUT_PREFILL - 4);
    assert(tivoo_output_refill(&queue, dma, 201) == 0);
    assert(tivoo_output_push(&queue, 2, input, 1) == 1);
    assert(tivoo_output_refill(&queue, dma, 202) == TIVOO_OUTPUT_BLOCK);
    assert(tivoo_output_stop(&queue, 2));
    assert(tivoo_output_refill(&queue, dma, 203) == 0);
    return 0;
}
