"""P5b3 startup ordering and non-destructive NVS invariants."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "esp32/firmware"


def test_nvs_initialization_never_erases_bluetooth_bond_database():
    source = (FIRMWARE / "main/wifi_station.c").read_text()
    assert "nvs_flash_init()" in source
    assert "nvs_flash_erase" not in source
    assert "tivoo_wifi_station_init_nvs" in source


def test_main_initializes_nvs_and_bluetooth_before_accepting_network_clients():
    source = (FIRMWARE / "main/main.c").read_text()
    nvs = source.index("tivoo_wifi_station_init_nvs()")
    spp = source.index("tivoo_spp_start()")
    listeners = source.index("network_listeners_start(")
    wifi = source.index("tivoo_wifi_station_start()")
    assert nvs < spp < listeners < wifi


def test_firmware_default_controller_mode_includes_classic_bluetooth():
    defaults = (FIRMWARE / "sdkconfig.defaults").read_text()
    assert "CONFIG_BT_SPP_ENABLED=y" in defaults
    assert "CONFIG_BTDM_CTRL_MODE_BR_EDR_ONLY=y" in defaults

    sdkconfig = (FIRMWARE / "sdkconfig").read_text()
    assert "CONFIG_BT_SMP_ENABLE=y" in sdkconfig
    assert "CONFIG_BTDM_CTRL_MODE_BR_EDR_ONLY=y" in sdkconfig


def test_classic_spp_uses_explicit_mac_sdp_and_never_scans_for_devices():
    source = (FIRMWARE / "main/tivoo_spp.c").read_text()
    assert "esp_spp_start_discovery" in source
    assert "esp_spp_connect(" in source
    assert "ESP_SPP_ROLE_MASTER" in source
    assert "ESP_SPP_SEC_AUTHENTICATE | ESP_SPP_SEC_ENCRYPT" in source
    assert "ESP_BT_GAP_KEY_NOTIF_EVT" in source
    assert "esp_bt_gap_get_bond_device_num" in source
    assert "esp_bt_gap_get_bond_device_list" in source
    for forbidden in (
        "esp_bt_gap_start_discovery",
        "esp_bt_gap_start_inquiry",
        "esp_ble_gap_start_scanning",
        "esp_ble_gap_start_scan",
    ):
        assert forbidden not in source


def test_firmware_has_no_fixed_tivoo_target_mac():
    sources = list((FIRMWARE / "main").glob("*.c")) + list(
        (FIRMWARE / "main").glob("*.h")
    )
    combined = "\n".join(path.read_text() for path in sources)
    assert "11:75:58:97:49:98" not in combined
    assert "0x11, 0x75, 0x58, 0x97, 0x49, 0x98" not in combined


def test_every_firmware_error_uses_the_closed_p5_error_code_set():
    import re

    allowed = {
        "wifi_init_failed",
        "wifi_connect_failed",
        "tcp_listen_failed",
        "spp_init_failed",
        "spp_connect_failed",
        "spp_disconnect_failed",
        "spp_not_connected",
        "spp_tx_queue_full",
        "spp_write_failed",
        "tcp_control_malformed",
        "tivoo_frame_malformed",
    }
    codes = set()
    for path in (FIRMWARE / "main").glob("*.c"):
        text = path.read_text()
        codes.update(
            re.findall(
                r'(?:tivoo_report_error|report_spp_error)\(\s*"([^"]+)"',
                text,
            )
        )
    assert codes
    assert codes <= allowed


def test_firmware_receive_block_uses_the_idf_tcp_mss():
    source = (FIRMWARE / "main/network_listeners.c").read_text()
    assert "TCP_RECV_BUFFER_SIZE CONFIG_LWIP_TCP_MSS" in source
    assert "static uint8_t s_receive_buffer[TCP_RECV_BUFFER_SIZE];" in source
    assert "uint8_t data[TCP_RECV_BUFFER_SIZE]" not in source


def test_spp_tx_queue_applies_the_contract_bounded_backpressure_wait():
    source = (FIRMWARE / "main/tivoo_spp.c").read_text()
    assert "SPP_QUEUE_WRITE_TIMEOUT_MS 1000" in source
    assert "pdMS_TO_TICKS(SPP_QUEUE_WRITE_TIMEOUT_MS)" in source
    assert "xQueueSend(s_request_queue, &request, 0)" not in source


def test_spp_connection_callbacks_report_each_lifecycle_stage():
    source = (FIRMWARE / "main/tivoo_spp.c").read_text()
    assert "case ESP_SPP_CL_INIT_EVT:" in source
    assert "case ESP_SPP_DISCOVERY_COMP_EVT:" in source
    assert "case ESP_SPP_OPEN_EVT:" in source
    assert "case ESP_SPP_CLOSE_EVT:" in source
    assert "cl_init.status" in source
    assert "open.status" in source
    assert "close.async" in source
    assert "disc_comp.status" in source
    assert "spp_connect_wait_timeout" in source
    assert "spp_bond_missing" in source


def test_spp_disconnect_reaches_worker_auto_reconnect_path():
    source = (FIRMWARE / "main/tivoo_spp.c").read_text()
    close_handler = source.split("case ESP_SPP_CLOSE_EVT:", 1)[1].split(
        "case ESP_SPP_CONG_EVT:", 1
    )[0]
    request_handler = source.split("static void process_request(", 1)[1].split(
        "static void spp_worker(", 1
    )[0]
    assert "EVENT_AUTO_RECONNECT" in close_handler
    assert "EVENT_FAILED | EVENT_LINK_LOST" in close_handler
    assert "REQUEST_CONNECT" in request_handler
    assert "xEventGroupSetBits(s_events, EVENT_AUTO_RECONNECT)" in request_handler
    assert "REQUEST_DISCONNECT" in request_handler
    assert "spp_connect_duplicate_ignored" in request_handler
    assert "same_address(queued->peer, s_session.peer)" in request_handler
    assert "xEventGroupClearBits(s_events, EVENT_AUTO_RECONNECT)" in request_handler
    assert "volatile bool s_auto_reconnect_enabled" not in source
    assert "s_target_valid" not in source
    assert "service_spp_reconnect" in source
    assert "TIVOO_SPP_REQUEST_RECONNECT" in source
    assert "pdMS_TO_TICKS(SPP_WORKER_POLL_MS)" in source
    failed_connect = source.split("case TIVOO_SPP_SESSION_CONNECT_FAILED:", 1)[1].split(
        "case TIVOO_SPP_SESSION_DISCONNECT_FAILED:", 1
    )[0]
    assert "EVENT_AUTO_RECONNECT" in failed_connect
    assert "s_reconnect_not_before" in failed_connect
    assert "SPP_RECONNECT_RETRY_MS" in failed_connect


def test_spp_reuses_a_preexisting_bond_without_waiting_for_auth_complete():
    source = (FIRMWARE / "main/tivoo_spp.c").read_text()
    connect_peer = source.split("static bool connect_peer(", 1)[1].split(
        "static bool write_chunk(", 1
    )[0]
    assert (
        "const bool target_bonded_before_connect = bond_list_contains_target();"
        in connect_peer
    )
    assert "wait_for_open_and_auth(target_bonded_before_connect)" in connect_peer
    assert "spp_bond_reused_after_open" in source
