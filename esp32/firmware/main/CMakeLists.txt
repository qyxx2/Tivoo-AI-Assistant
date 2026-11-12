idf_component_register(
    SRCS
        "main.c"
        "audio_resource.c"
        "device_status.c"
        "hardware_memory.c"
        "wifi_station.c"
        "network_listeners.c"
        "diagnostics.c"
        "control_bridge.c"
        "tivoo_frame_stream.c"
        "bt_security_policy.c"
        "tivoo_spp.c"
        "tivoo_spp_session.c"
    INCLUDE_DIRS "."
    REQUIRES
        esp_event
        esp_http_client
        mbedtls
        esp_netif
        esp_timer
        esp_wifi
        bt
        espressif__cjson
        esp_psram
        heap
        spi_flash
        lwip
        nvs_flash
)

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
