idf_component_register(
    SRCS
        "s3_main.c"
        "audio_capture.c"
        "p68_afe_flow.c"
        "p68_local_turn.c"
        "p68_prompt.c"
        "p68_trace.c"
        "s3_local_turn.c"
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
target_compile_definitions(${COMPONENT_LIB} PRIVATE TIVOO_P68_B1_SCAFFOLD=1 TIVOO_P68_B2_UART=1 TIVOO_P68_B3_AUDIO=1 TIVOO_P68_B5_LOCAL=1)

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

# Frozen source MP3 -> aligned, read-only PCM in app flash. The build host
# needs FFmpeg; neither firmware nor HA fetches a prompt at runtime.
idf_build_get_property(_prompt_python PYTHON)
set(_prompt_src "${CMAKE_CURRENT_LIST_DIR}/../../../homeassistant/prompt_assets")
set(_prompt_out "${CMAKE_CURRENT_BINARY_DIR}/local_prompts")
file(GLOB _prompt_inputs CONFIGURE_DEPENDS "${_prompt_src}/*.mp3")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    ${_prompt_inputs} "${CMAKE_CURRENT_LIST_DIR}/generate_prompts.py")
execute_process(COMMAND "${_prompt_python}" "${CMAKE_CURRENT_LIST_DIR}/generate_prompts.py"
    "${_prompt_src}" "${_prompt_out}" COMMAND_ERROR_IS_FATAL ANY)
set(_prompt_asm "${_prompt_out}/p68_prompt_assets.S")
set_property(SOURCE "${_prompt_asm}" PROPERTY OBJECT_DEPENDS
    "${_prompt_out}/ready_01.pcm;${_prompt_out}/ready_02.pcm;${_prompt_out}/ready_03.pcm;${_prompt_out}/followup_01.pcm;${_prompt_out}/local_success_01.pcm;${_prompt_out}/local_failure_01.pcm")
target_sources(${COMPONENT_LIB} PRIVATE "${_prompt_asm}")
