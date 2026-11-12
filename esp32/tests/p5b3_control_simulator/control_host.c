#include "control_bridge.h"
#include "network_listeners.h"
#include "tivoo_spp.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static tivoo_spp_queue_result_t s_frame_result = TIVOO_SPP_QUEUE_QUEUED;

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

tivoo_spp_queue_result_t tivoo_spp_queue_frame(
    const uint8_t *frame, size_t size)
{
    if (s_frame_result == TIVOO_SPP_QUEUE_QUEUED) {
        printf("FRAME ");
        for (size_t i = 0; i < size; i++) {
            printf("%02X", frame[i]);
        }
        putchar('\n');
        fflush(stdout);
    }
    return s_frame_result;
}

static bool parse_hex(const char *value, uint8_t *output, size_t capacity,
                      size_t *output_size)
{
    const size_t length = strlen(value);
    if ((length % 2U) != 0U || length / 2U > capacity) {
        return false;
    }
    for (size_t i = 0; i < length / 2U; i++) {
        char octet[3] = {value[i * 2U], value[i * 2U + 1U], '\0'};
        char *end = NULL;
        const unsigned long parsed = strtoul(octet, &end, 16);
        if (end == octet || *end != '\0' || parsed > 0xFFUL) {
            return false;
        }
        output[i] = (uint8_t)parsed;
    }
    *output_size = length / 2U;
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
    char input[512];
    uint8_t data[240];
    while (fgets(input, sizeof(input), stdin) != NULL) {
        if (strncmp(input, "exit", 4) == 0) {
            break;
        }
        if (strncmp(input, "data ", 5) == 0) {
            size_t size = 0U;
            input[strcspn(input, "\r\n")] = '\0';
            const bool valid = parse_hex(input + 5, data, sizeof(data), &size);
            const bool accepted = valid && tivoo_control_spp_data(data, size);
            puts(accepted ? "DATA_ACCEPTED" : "DATA_REJECTED");
            fflush(stdout);
        } else if (strncmp(input, "frame-result ", 13) == 0) {
            char *value = input + 13;
            value[strcspn(value, "\r\n")] = '\0';
            if (strcmp(value, "connecting") == 0) {
                s_frame_result = TIVOO_SPP_QUEUE_CONNECTING;
            } else if (strcmp(value, "disconnected") == 0) {
                s_frame_result = TIVOO_SPP_QUEUE_DISCONNECTED;
            } else if (strcmp(value, "full") == 0) {
                s_frame_result = TIVOO_SPP_QUEUE_FULL;
            } else {
                s_frame_result = TIVOO_SPP_QUEUE_QUEUED;
            }
            puts("FRAME_RESULT_SET");
            fflush(stdout);
        }
    }
    network_listeners_stop();
    return 0;
}
