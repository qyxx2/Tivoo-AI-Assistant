#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "tivoo_spp.h"
#include "wifi_station.h"

void p6_host_set_wifi(bool connected, const char *ip, int rssi);
void p6_host_set_spp(tivoo_spp_link_state_t state, const uint8_t peer[6]);
