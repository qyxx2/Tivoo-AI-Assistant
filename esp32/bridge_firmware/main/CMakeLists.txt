# Share the existing SPP implementation; do not duplicate its security policy.
set(SHARED "${CMAKE_CURRENT_LIST_DIR}/../../firmware/main")
idf_component_register(
    SRCS "main.c" "bridge_scaffold.c"
        "${SHARED}/board_boot.c"
        "${SHARED}/uart_wire.c"
        "${SHARED}/uart_link.c"
        "${SHARED}/uart_router.c"
        "${SHARED}/uart_transport.c"
        "${SHARED}/tivoo_spp.c"
        "${SHARED}/tivoo_spp_session.c"
        "${SHARED}/tivoo_frame_stream.c"
        "${SHARED}/bt_security_policy.c"
    INCLUDE_DIRS "." "${SHARED}"
    REQUIRES bt nvs_flash esp_driver_uart esp_driver_gpio esp_driver_rmt
        esp_psram heap spi_flash esp_timer esp_hw_support
)

target_compile_definitions(${COMPONENT_LIB} PRIVATE TIVOO_P68_B2_BRIDGE=1)
