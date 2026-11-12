#include "device_status.h"
#include "device_status_host_stub.h"
#include "diagnostics.h"
#include "network_listeners.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static bool decode_mac(const char *text, uint8_t peer[6])
{
    unsigned int values[6];
    if (text == NULL ||
        sscanf(text, "%2x:%2x:%2x:%2x:%2x:%2x",
               &values[0], &values[1], &values[2],
               &values[3], &values[4], &values[5]) != 6) {
        return false;
    }
    for (size_t i = 0; i < 6; i++) {
        if (values[i] > UINT8_MAX) {
            return false;
        }
        peer[i] = (uint8_t)values[i];
    }
    return true;
}

static int parse_port(const char *value, uint16_t *port)
{
    char *end = NULL;
    unsigned long parsed = strtoul(value, &end, 10);
    if (value[0] == '\0' || end == value || *end != '\0' ||
        parsed == 0 || parsed > UINT16_MAX) {
        return -1;
    }
    *port = (uint16_t)parsed;
    return 0;
}

int main(int argc, char **argv)
{
    uint16_t control_port;
    uint16_t diagnostic_port;
    if (argc != 3 || parse_port(argv[1], &control_port) != 0 ||
        parse_port(argv[2], &diagnostic_port) != 0) {
        return EXIT_FAILURE;
    }

    static bool wifi_connected;
    p6_host_set_wifi(false, NULL, 0);
    p6_host_set_spp(TIVOO_SPP_LINK_DISCONNECTED, NULL);
    tivoo_diagnostics_set_message_handler(tivoo_device_status_handle_message);
    if (tivoo_diagnostics_start() != ESP_OK) {
        return EXIT_FAILURE;
    }
    if (network_listeners_start(control_port, diagnostic_port) != ESP_OK) {
        tivoo_diagnostics_stop();
        return EXIT_FAILURE;
    }

    char line[512];
    while (fgets(line, sizeof(line), stdin) != NULL) {
        char *save = NULL;
        char *command = strtok_r(line, " \t\r\n", &save);
        if (command == NULL) {
            continue;
        }
        if (strcmp(command, "ready") == 0) {
            /* Keep host TCP listeners available independently of the fake Wi-Fi state. */
            (void)network_listeners_set_ip_available(true);
        } else if (strcmp(command, "wifi") == 0) {
            char *state_text = strtok_r(NULL, " \t\r\n", &save);
            const bool next = state_text != NULL && strcmp(state_text, "connected") == 0;
            if (next != wifi_connected) {
                wifi_connected = next;
                p6_host_set_wifi(next, next ? "192.168.3.28" : NULL, -55);
                (void)tivoo_device_status_report_event(
                    next ? "wifi_connected" : "wifi_disconnected", NULL);
            }
        } else if (strcmp(command, "audio") == 0) {
            char *state_text = strtok_r(NULL, " \t\r\n", &save);
            char *playback_id = strtok_r(NULL, " \t\r\n", &save);
            if (state_text != NULL) {
                const bool fetching = strcmp(state_text, "fetching") == 0;
                (void)tivoo_device_status_set_audio_resource(
                    fetching, fetching ? playback_id : NULL);
            }
        } else if (strcmp(command, "spp") == 0) {
            char *state_text = strtok_r(NULL, " \t\r\n", &save);
            char *mac_text = strtok_r(NULL, " \t\r\n", &save);
            if (state_text != NULL) {
                tivoo_spp_link_state_t next = TIVOO_SPP_LINK_DISCONNECTED;
                if (strcmp(state_text, "connecting") == 0) {
                    next = TIVOO_SPP_LINK_CONNECTING;
                } else if (strcmp(state_text, "connected") == 0) {
                    next = TIVOO_SPP_LINK_CONNECTED;
                }
                uint8_t peer[6];
                const bool peer_valid = decode_mac(mac_text, peer);
                static tivoo_spp_link_state_t previous =
                    TIVOO_SPP_LINK_DISCONNECTED;
                p6_host_set_spp(next, peer_valid ? peer : NULL);
                (void)tivoo_device_status_report_transition(
                    next == TIVOO_SPP_LINK_CONNECTING ? "spp_connecting" :
                    (next == TIVOO_SPP_LINK_CONNECTED ? "spp_connected" :
                     "spp_disconnected"),
                    previous, next, peer_valid ? peer : NULL);
                previous = next;
            }
        } else if (strcmp(command, "error") == 0) {
            char *code = strtok_r(NULL, " \t\r\n", &save);
            char *module = strtok_r(NULL, " \t\r\n", &save);
            char *message = save;
            if (code != NULL && module != NULL && message != NULL) {
                while (*message == ' ' || *message == '\t') {
                    message++;
                }
                message[strcspn(message, "\r\n")] = '\0';
                tivoo_report_error(code, module, message);
            }
        } else if (strcmp(command, "exit") == 0) {
            break;
        }
    }

    network_listeners_stop();
    tivoo_diagnostics_stop();
    return EXIT_SUCCESS;
}
