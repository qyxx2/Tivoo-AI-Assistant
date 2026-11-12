#pragma once

#include <stdbool.h>
#include <stddef.h>

#ifdef ESP_PLATFORM
#include "esp_err.h"
#else
typedef int esp_err_t;
#define ESP_OK 0
#endif

typedef struct {
    bool connected;
    bool ip_available;
    char ip[16];
    bool rssi_available;
    int rssi_dbm;
} tivoo_wifi_status_t;

esp_err_t tivoo_wifi_station_init_nvs(void);
esp_err_t tivoo_wifi_station_start(void);
bool tivoo_wifi_station_get_status(tivoo_wifi_status_t *status);
