#include <assert.h>
#include <stddef.h>

#include "audio_capture.h"
#include "audio_output_manager.h"

int main(void)
{
    void *buffers[TIVOO_OUTPUT_DMA_BLOCKS] = {0};
    tivoo_dma_eof_tracker_t tracker;
    tivoo_dma_eof_tracker_reset(&tracker, buffers, TIVOO_OUTPUT_DMA_BLOCKS);

    int dma[TIVOO_OUTPUT_DMA_BLOCKS];
    for (size_t i = 0; i < TIVOO_OUTPUT_DMA_BLOCKS; ++i) {
        assert(tivoo_dma_eof_tracker_observe(&tracker, &dma[i]) == 0);
    }

    assert(tivoo_dma_eof_tracker_observe(&tracker, &dma[0]) == 0);
    const size_t one_missed = tivoo_dma_eof_tracker_observe(&tracker, &dma[2]);
    assert(one_missed == 1);
    assert(one_missed * (TIVOO_OUTPUT_BLOCK / 2U) == 80U);

    assert(tivoo_dma_eof_tracker_observe(&tracker, &dma[3]) == 0);
    assert(tivoo_dma_eof_tracker_observe(&tracker, &dma[5]) == 1);
    assert(tivoo_dma_eof_tracker_observe(&tracker, &dma[5]) == TIVOO_OUTPUT_DMA_BLOCKS - 1U);

    return 0;
}
