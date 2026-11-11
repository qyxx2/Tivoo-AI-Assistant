idf_component_register(
    SRCS
        "main.c"
        "wifi_station.c"
        "network_listeners.c"
    INCLUDE_DIRS "."
    REQUIRES
        esp_event
        esp_netif
        esp_wifi
        lwip
        nvs_flash
)
