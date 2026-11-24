"""P5b3 startup ordering and non-destructive NVS invariants."""

import os
from pathlib import Path

import pytest

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
    bridge = ROOT / "esp32/bridge_firmware"
    defaults = (bridge / "sdkconfig.defaults").read_text()
    assert "CONFIG_BT_SPP_ENABLED=y" in defaults
    assert "CONFIG_BTDM_CTRL_MODE_BR_EDR_ONLY=y" in defaults


def test_effective_target_configs_after_configure():
    # Source/host tests can run on a clean checkout. Explicit configure
    # evidence must exist when requested (missing config is a failure).
    configured_root = os.environ.get("TIVOO_P68_CONFIG_ROOT")
    paths = (
        (Path(configured_root) / "esp32s3/sdkconfig",
         Path(configured_root) / "esp32/sdkconfig")
        if configured_root else
        (FIRMWARE / "sdkconfig", ROOT / "esp32/bridge_firmware/sdkconfig")
    )
    if not configured_root and not all(path.is_file() for path in paths):
        pytest.skip("configure both targets first; set TIVOO_P68_CONFIG_ROOT for independent builds")
    s3, classic = (set(path.read_text().splitlines()) for path in paths)
    common = {
        "CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y", "CONFIG_ESPTOOLPY_FLASHMODE_DIO=y",
        "CONFIG_SPIRAM=y", "CONFIG_SPIRAM_USE_MALLOC=y",
        "CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ=240",
        "# CONFIG_FREERTOS_UNICORE is not set",
        "CONFIG_PARTITION_TABLE_CUSTOM=y", "CONFIG_PARTITION_TABLE_OFFSET=0x8000",
    }
    assert common <= s3
    assert common <= classic
    assert {
        'CONFIG_IDF_TARGET="esp32s3"', "CONFIG_ESPTOOLPY_FLASHFREQ_80M=y",
        "CONFIG_SPIRAM_MODE_OCT=y", "CONFIG_SPIRAM_SPEED_80M=y",
        "CONFIG_SPIRAM_TRY_ALLOCATE_WIFI_LWIP=y",
        "CONFIG_MODEL_IN_FLASH=y", "CONFIG_SR_VADN_VADNET1_MEDIUM=y",
        "CONFIG_SR_WN_WN9_HILEXIN=y",
        "CONFIG_ESP32S3_DATA_CACHE_SIZE=0x8000",
        "CONFIG_ESP32S3_DATA_CACHE_LINE_SIZE=64",
    } <= s3
    # A private sdkconfig must not silently override the checked-in memory
    # budget and measured AFE cache policy. A private config must not bring
    # back the buffer/window drift or the slower 32-byte cache lines.
    defaults = dict(
        line.split("=", 1)
        for line in (FIRMWARE / "sdkconfig.defaults").read_text().splitlines()
        if line.startswith("CONFIG_") and "=" in line
    )
    for key in ("CONFIG_ESP_WIFI_STATIC_RX_BUFFER_NUM",
                "CONFIG_ESP_WIFI_STATIC_TX_BUFFER_NUM", "CONFIG_ESP_WIFI_RX_BA_WIN",
                "CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL",
                "CONFIG_ESP32S3_DATA_CACHE_32KB", "CONFIG_ESP32S3_DATA_CACHE_LINE_64B"):
        assert key in defaults, f"{key} needs a persistent default"
        assert f"{key}={defaults[key]}" in s3, f"reconfigure stale {key}"
    assert "CONFIG_BT_ENABLED=y" not in s3
    assert {
        'CONFIG_IDF_TARGET="esp32"', "CONFIG_ESPTOOLPY_FLASHFREQ_40M=y",
        "CONFIG_SPIRAM_MODE_QUAD=y", "CONFIG_SPIRAM_SPEED_40M=y",
        "CONFIG_SPIRAM_TYPE_ESPPSRAM64=y", "CONFIG_BT_ALLOCATION_FROM_SPIRAM_FIRST=y",
        "CONFIG_SPIRAM_BANKSWITCH_ENABLE=y", "CONFIG_SPIRAM_BANKSWITCH_RESERVE=8",
        "CONFIG_BT_SMP_ENABLE=y", "CONFIG_BT_SPP_ENABLED=y",
        "CONFIG_BTDM_CTRL_MODE_BR_EDR_ONLY=y",
    } <= classic


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


def test_every_firmware_error_uses_the_p5_and_p6_error_code_sets():
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
        "protocol_invalid_header",
        "protocol_invalid_payload",
        "protocol_unsupported_message",
        "reverse_queue_full",
        "audio_busy",
        "audio_http_failed",
        "audio_http_status",
        "audio_content_type_mismatch",
        "operation_cancelled",
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
