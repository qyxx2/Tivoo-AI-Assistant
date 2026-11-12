#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

void tivoo_control_client_connected(int client_fd);
bool tivoo_control_client_data(int client_fd, const uint8_t *data, size_t size);
void tivoo_control_client_disconnected(int client_fd);
