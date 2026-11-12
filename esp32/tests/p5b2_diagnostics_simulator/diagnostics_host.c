#include "diagnostics.h"
#include "network_listeners.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static bool decode_hex(
    const char *text, uint8_t *output, size_t capacity, size_t *size)
{
    const size_t length = strlen(text);
    if ((length % 2U) != 0U || length / 2U > capacity) {
        return false;
    }
    for (size_t i = 0; i < length / 2U; i++) {
        char byte[3] = {text[i * 2U], text[i * 2U + 1U], '\0'};
        char *end = NULL;
        unsigned long value = strtoul(byte, &end, 16);
        if (end != byte + 2 || value > UINT8_MAX) {
            return false;
        }
        output[i] = (uint8_t)value;
    }
    *size = length / 2U;
    return true;
}

static bool echo_message_handler(
    uint8_t type, const uint8_t *payload, size_t size)
{
    uint8_t response_type;
    switch (type) {
    case 0x03U:
        response_type = 0x04U;
        break;
    case 0x10U:
        response_type = 0x11U;
        break;
    case 0x23U:
    case 0x30U:
    case 0x31U:
        response_type = 0x32U;
        break;
    default:
        response_type = type;
        break;
    }
    return tivoo_diagnostics_send_message(response_type, payload, size);
}

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

static esp_log_level_t parse_level(const char *level)
{
    if (strcmp(level, "DEBUG") == 0) {
        return ESP_LOG_DEBUG;
    }
    if (strcmp(level, "WARNING") == 0 || strcmp(level, "WARN") == 0) {
        return ESP_LOG_WARN;
    }
    if (strcmp(level, "ERROR") == 0) {
        return ESP_LOG_ERROR;
    }
    return ESP_LOG_INFO;
}

int main(int argc, char **argv)
{
    uint16_t control_port;
    uint16_t diagnostic_port;
    if (argc != 3 || parse_port(argv[1], &control_port) != 0 ||
        parse_port(argv[2], &diagnostic_port) != 0) {
        return EXIT_FAILURE;
    }

    tivoo_diagnostics_set_message_handler(echo_message_handler);
    if (tivoo_diagnostics_start() != ESP_OK) {
        return EXIT_FAILURE;
    }
    if (network_listeners_start(control_port, diagnostic_port) != ESP_OK) {
        tivoo_diagnostics_stop();
        return EXIT_FAILURE;
    }

    char line[10240];
    while (fgets(line, sizeof(line), stdin) != NULL) {
        char *save = NULL;
        char *command = strtok_r(line, " \t\r\n", &save);
        if (command == NULL) {
            continue;
        }
        if (strcmp(command, "up") == 0) {
            network_listeners_set_ip_available(true);
        } else if (strcmp(command, "down") == 0) {
            network_listeners_set_ip_available(false);
        } else if (strcmp(command, "log") == 0) {
            char *level = strtok_r(NULL, " \t\r\n", &save);
            char *module = strtok_r(NULL, " \t\r\n", &save);
            char *message = save;
            if (level != NULL && module != NULL && message != NULL) {
                while (*message == ' ' || *message == '\t') {
                    message++;
                }
                message[strcspn(message, "\r\n")] = '\0';
                tivoo_log_write(parse_level(level), module, "%s", message);
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
        } else if (strcmp(command, "send") == 0) {
            char *type_value = strtok_r(NULL, " \t\r\n", &save);
            char *hex_payload = strtok_r(NULL, " \t\r\n", &save);
            if (type_value != NULL && hex_payload != NULL) {
                const unsigned long type = strtoul(type_value, NULL, 0);
                uint8_t payload[4096];
                size_t payload_size = 0U;
                if (type <= UINT8_MAX &&
                    decode_hex(hex_payload, payload, sizeof(payload), &payload_size)) {
                    (void)tivoo_diagnostics_send_message(
                        (uint8_t)type, payload, payload_size);
                }
            }
        } else if (strcmp(command, "burst") == 0) {
            char *count_value = strtok_r(NULL, " \t\r\n", &save);
            unsigned long count =
                count_value == NULL ? 0 : strtoul(count_value, NULL, 10);
            for (unsigned long i = 0; i < count; i++) {
                char message[32];
                (void)snprintf(message, sizeof(message), "burst-%03lu", i);
                tivoo_log_write(ESP_LOG_INFO, "host_test", "%s", message);
            }
        } else if (strcmp(command, "fail_after") == 0) {
            char *size_value = strtok_r(NULL, " \t\r\n", &save);
            if (size_value != NULL) {
                tivoo_diagnostics_host_fail_next_send_after(
                    (size_t)strtoul(size_value, NULL, 10));
            }
        } else if (strcmp(command, "exit") == 0) {
            break;
        }
    }

    network_listeners_stop();
    tivoo_diagnostics_stop();
    return EXIT_SUCCESS;
}
