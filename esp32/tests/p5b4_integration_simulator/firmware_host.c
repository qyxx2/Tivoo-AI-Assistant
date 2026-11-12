#include "diagnostics.h"
#include "network_listeners.h"
#include "tivoo_spp_host_stub.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TIVOO_CONTROL_PORT 7777U
#define TIVOO_DIAGNOSTIC_PORT 7778U

int main(void)
{
    if (tivoo_diagnostics_start() != ESP_OK) {
        return EXIT_FAILURE;
    }
    if (network_listeners_start(
            TIVOO_CONTROL_PORT, TIVOO_DIAGNOSTIC_PORT) != ESP_OK) {
        tivoo_diagnostics_stop();
        return EXIT_FAILURE;
    }
    network_listeners_set_ip_available(true);

    char command[64];
    while (fgets(command, sizeof(command), stdin) != NULL) {
        if (strcmp(command, "up\n") == 0) {
            network_listeners_set_ip_available(true);
        } else if (strcmp(command, "down\n") == 0) {
            network_listeners_set_ip_available(false);
        } else if (strcmp(command, "fail_next_frame\n") == 0) {
            tivoo_spp_host_fail_next_frame();
            puts("COMMAND fail_next_frame");
            fflush(stdout);
        } else if (strcmp(command, "log\n") == 0) {
            TIVOO_LOGI("p5b4_host", "integration_log");
        } else if (strcmp(command, "exit\n") == 0) {
            break;
        }
    }

    network_listeners_stop();
    tivoo_diagnostics_stop();
    return EXIT_SUCCESS;
}
