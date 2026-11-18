idf_component_register(
    SRCS
        "s3_main.c"
        "audio_capture.c"
        "p68_afe_flow.c"
        "s3_afe.c"
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
# Derive the exact single WakeNet model ID from the effective Kconfig.
get_cmake_property(_cfg_vars VARIABLES)
set(_wake_models "")
foreach(_var IN LISTS _cfg_vars)
    if(_var MATCHES "^CONFIG_SR_WN_WN[0-9].*" AND ${_var})
        string(REGEX REPLACE "^CONFIG_SR_WN_" "" _model "${_var}")
        string(TOLOWER "${_model}" _model)
        list(APPEND _wake_models "${_model}")
    endif()
endforeach()
list(LENGTH _wake_models _wake_count)
if(NOT _wake_count EQUAL 1)
    message(FATAL_ERROR "P6.8 requires exactly one WakeNet model, got: ${_wake_models}")
endif()
target_compile_definitions(${COMPONENT_LIB} PRIVATE TIVOO_AFE_MODEL_ID="${_wake_models}")
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
