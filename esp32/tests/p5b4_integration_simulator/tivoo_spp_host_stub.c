#include "tivoo_spp_host_stub.h"

#include <stdbool.h>
#include <stdatomic.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include "tivoo_spp.h"

static atomic_bool s_fail_next_frame = ATOMIC_VAR_INIT(false);

void tivoo_spp_host_fail_next_frame(void)
{
    atomic_store(&s_fail_next_frame, true);
}

bool tivoo_spp_queue_connect(const uint8_t peer[6])
{
    printf("CONNECT %02X:%02X:%02X:%02X:%02X:%02X\n",
           peer[0], peer[1], peer[2], peer[3], peer[4], peer[5]);
    fflush(stdout);
    return true;
}

bool tivoo_spp_queue_disconnect(const uint8_t peer[6])
{
    printf("DISCONNECT %02X:%02X:%02X:%02X:%02X:%02X\n",
           peer[0], peer[1], peer[2], peer[3], peer[4], peer[5]);
    fflush(stdout);
    return true;
}

bool tivoo_spp_queue_frame(const uint8_t *frame, size_t size)
{
    if (atomic_exchange(&s_fail_next_frame, false)) {
        return false;
    }

    printf("FRAME ");
    for (size_t i = 0; i < size; i++) {
        printf("%02X", frame[i]);
    }
    putchar('\n');
    fflush(stdout);
    return true;
}
