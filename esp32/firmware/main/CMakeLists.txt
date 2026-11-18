idf_component_register(
    SRCS
        "s3_main.c"
        "audio_capture.c"
        "audio_output_manager.c"
        "audio_playback.c"
        "audio_resource.c"
        "uart_wire.c"
        "uart_link.c"
        "uart_transport.c"
        "control_bridge.c"
        "tivoo_frame_stream.c"
        "s3_api_smoke.c"
        "board_boot.c"
        "device_status.c"
        "wifi_station.c"
        "network_listeners.c"
        "diagnostics.c"
    INCLUDE_DIRS "."
    REQUIRES
        esp_driver_uart esp_driver_i2s esp_driver_gpio esp_driver_rmt
        esp_event esp_http_client mbedtls esp_netif esp_timer esp_wifi
        espressif__cjson esp_psram heap spi_flash lwip nvs_flash
        esp-sr esp_audio_codec esp_audio_effects
)
target_compile_definitions(${COMPONENT_LIB} PRIVATE TIVOO_P68_B1_SCAFFOLD=1 TIVOO_P68_B2_UART=1 TIVOO_P68_B3_AUDIO=1)

execute_process(
    COMMAND git rev-parse --short=7 HEAD
    WORKING_DIRECTORY "${CMAKE_CURRENT_LIST_DIR}/../../.."
    OUTPUT_VARIABLE TIVOO_GIT_SHORT_SHA
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
)
if(NOT TIVOO_GIT_SHORT_SHA)
    set(TIVOO_GIT_SHORT_SHA "unknown")
endif()
target_compile_definitions(
    ${COMPONENT_LIB}
    PRIVATE TIVOO_FIRMWARE_VERSION="0.1.0+${TIVOO_GIT_SHORT_SHA}"
)
