#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef ESP_PLATFORM
#include "esp_err.h"
#else
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_INVALID_STATE -2
#endif

esp_err_t network_listeners_start(uint16_t control_port, uint16_t diagnostic_port);
void network_listeners_set_ip_available(bool available);
void network_listeners_stop(void);
