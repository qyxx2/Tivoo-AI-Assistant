#include "control_bridge.h"
#include "network_listeners.h"
#include "tivoo_spp.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void print_mac_event(const char *event, const uint8_t peer[6])
{
    printf("%s %02X:%02X:%02X:%02X:%02X:%02X\n", event,
           peer[0], peer[1], peer[2], peer[3], peer[4], peer[5]);
    fflush(stdout);
}

bool tivoo_spp_queue_connect(const uint8_t peer[6])
{
    print_mac_event("CONNECT", peer);
    return true;
}

bool tivoo_spp_queue_disconnect(const uint8_t peer[6])
{
    print_mac_event("DISCONNECT", peer);
    return true;
}

bool tivoo_spp_queue_frame(const uint8_t *frame, size_t size)
{
    printf("FRAME ");
    for (size_t i = 0; i < size; i++) {
        printf("%02X", frame[i]);
    }
    putchar('\n');
    fflush(stdout);
    return true;
}

int main(int argc, char **argv)
{
    if (argc != 3) {
        return 2;
    }
    if (network_listeners_start((uint16_t)strtoul(argv[1], NULL, 10),
                                (uint16_t)strtoul(argv[2], NULL, 10)) != ESP_OK) {
        return 3;
    }
    network_listeners_set_ip_available(true);
    char input[32];
    while (fgets(input, sizeof(input), stdin) != NULL) {
        if (strncmp(input, "exit", 4) == 0) {
            break;
        }
    }
    network_listeners_stop();
    return 0;
}
