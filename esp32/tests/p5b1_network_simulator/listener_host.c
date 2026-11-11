#include "diagnostics.h"
#include "network_listeners.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int parse_port(const char *value, uint16_t *port)
{
    char *end = NULL;
    unsigned long parsed = strtoul(value, &end, 10);
    if (value[0] == '\0' || end == value || *end != '\0' || parsed == 0 ||
        parsed > UINT16_MAX) {
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
        parse_port(argv[2], &diagnostic_port) != 0 ||
        tivoo_diagnostics_start() != ESP_OK) {
        return EXIT_FAILURE;
    }
    if (network_listeners_start(control_port, diagnostic_port) != ESP_OK) {
        tivoo_diagnostics_stop();
        return EXIT_FAILURE;
    }

    char command[16];
    while (fgets(command, sizeof(command), stdin) != NULL) {
        if (strcmp(command, "up\n") == 0) {
            network_listeners_set_ip_available(true);
        } else if (strcmp(command, "down\n") == 0) {
            network_listeners_set_ip_available(false);
        } else if (strcmp(command, "exit\n") == 0) {
            break;
        }
    }

    network_listeners_stop();
    tivoo_diagnostics_stop();
    return EXIT_SUCCESS;
}
