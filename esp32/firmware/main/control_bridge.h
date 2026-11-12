#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define TIVOO_CONTROL_REVERSE_QUEUE_CAPACITY 8192U

void tivoo_control_client_connected(int client_fd);
bool tivoo_control_client_data(int client_fd, const uint8_t *data, size_t size);
void tivoo_control_client_disconnected(int client_fd);
bool tivoo_control_spp_data(const uint8_t *data, size_t size);
bool tivoo_control_client_has_pending(int client_fd);
bool tivoo_control_client_send_pending(int client_fd);
void tivoo_control_report_pending_errors(void);
