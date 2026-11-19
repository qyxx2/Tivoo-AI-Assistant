#pragma once
#include <stdbool.h>
#include <stdint.h>

#ifdef ESP_PLATFORM
#include "esp_err.h"
esp_err_t tivoo_uart_transport_start(void);
#endif
#ifdef TIVOO_P68_B2_BRIDGE
void tivoo_uart_bridge_set_available(bool available);
void tivoo_uart_bridge_status_changed(void);
void tivoo_uart_bridge_error(const char *code);
void tivoo_uart_bridge_request_error(uint32_t generation, const char *code);
void tivoo_uart_bridge_hint(uint32_t generation, uint8_t hint);
#else
bool tivoo_uart_client_open(void);
void tivoo_uart_client_close(void);
bool tivoo_uart_client_valid(void);
bool tivoo_uart_client_can_read(void);
#endif
