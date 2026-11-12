idf_component_register(
    SRCS "p5b0_smoke.c"
    INCLUDE_DIRS "."
    REQUIRES
        bt
        esp_netif
        esp_wifi
        nvs_flash
        esp_driver_i2s
        lwip
        esp-sr
        esp_audio_codec
        esp_audio_effects
)
