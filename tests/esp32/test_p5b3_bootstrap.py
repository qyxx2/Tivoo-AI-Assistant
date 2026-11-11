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
    assert "uint8_t data[TCP_RECV_BUFFER_SIZE]" in source
