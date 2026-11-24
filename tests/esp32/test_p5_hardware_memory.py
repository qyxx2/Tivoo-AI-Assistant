"""P5 runtime memory diagnostics must verify real flash, PSRAM heap and himem."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_MAIN = ROOT / "esp32/firmware/main"


def test_boot_reports_memory_and_probes_himem_banks():
    source = (FIRMWARE_MAIN / "hardware_memory.c").read_text()
    main = (FIRMWARE_MAIN / "main.c").read_text()

    assert "esp_flash_get_size(NULL, &flash_bytes)" in source
    assert "esp_psram_is_initialized()" in source
    assert "esp_psram_get_size()" in source
    assert "heap_caps_get_total_size(MALLOC_CAP_SPIRAM)" in source
    assert "heap_caps_get_free_size(MALLOC_CAP_SPIRAM)" in source
    assert "esp_himem_get_phys_size()" in source
    assert "esp_himem_get_free_size()" in source
    assert "esp_himem_alloc(" in source
    assert "esp_himem_alloc_map_range(" in source
    assert "esp_himem_map(" in source
    assert "esp_himem_unmap(" in source
    assert "himem_probe_ok=" in source
    assert "tivoo_hardware_memory_report();" in main


def _partitions(project):
    import csv
    rows = []
    for row in csv.reader((project / "partitions.csv").read_text().splitlines()):
        if not row or row[0].strip().startswith("#"):
            continue
        name, kind, subtype, offset, size = [v.strip() for v in row[:5]]
        rows.append((name, kind, subtype, int(offset, 0), int(size, 0)))
    return rows


def test_p68_s3_partition_layout():
    rows = _partitions(ROOT / "esp32/firmware")
    assert rows == [
        ("nvs", "data", "nvs", 0x9000, 0x6000),
        ("phy_init", "data", "phy", 0xf000, 0x1000),
        ("factory", "app", "factory", 0x10000, 0x800000),
        ("model", "data", "spiffs", 0x810000, 0x400000),
        ("storage", "data", "spiffs", 0xc10000, 0x3f0000),
    ]


def test_p68_bridge_preserves_legacy_nvs_and_partition_layout():
    rows = _partitions(ROOT / "esp32/bridge_firmware")
    assert rows == [
        ("nvs", "data", "nvs", 0x9000, 0x6000),
        ("phy_init", "data", "phy", 0xf000, 0x1000),
        ("factory", "app", "factory", 0x10000, 0x800000),
        ("storage", "data", "spiffs", 0x810000, 0x7f0000),
    ]


def test_p68_independent_target_defaults_and_model_selection():
    s3 = ROOT / "esp32/firmware"
    bridge = ROOT / "esp32/bridge_firmware"
    for project, target in [(s3, "esp32s3"), (bridge, "esp32")]:
        defaults = (project / "sdkconfig.defaults").read_text()
        assert f'CONFIG_IDF_TARGET="{target}"' in defaults
        assert "CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y" in defaults
        assert "CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_240=y" in defaults
    s3_defaults = (s3 / "sdkconfig.defaults").read_text()
    assert "CONFIG_SPIRAM_MODE_OCT=y" in s3_defaults
    assert "CONFIG_SPIRAM_SPEED_80M=y" in s3_defaults
    assert "CONFIG_BT_ENABLED=y" not in s3_defaults
    assert "CONFIG_MODEL_IN_FLASH=y" in s3_defaults
    assert "CONFIG_SR_VADN_VADNET1_MEDIUM=y" in s3_defaults
    assert [line for line in s3_defaults.splitlines()
            if line.startswith("CONFIG_SR_WN_") and line.endswith("=y")] == [
                "CONFIG_SR_WN_WN9_HIWALLE_TTS2=y"]
    bridge_defaults = (bridge / "sdkconfig.defaults").read_text()
    assert "CONFIG_SPIRAM_MODE_QUAD=y" in bridge_defaults
    assert "CONFIG_SPIRAM_BANKSWITCH_ENABLE=y" in bridge_defaults
    assert "CONFIG_BTDM_CTRL_MODE_BR_EDR_ONLY=y" in bridge_defaults
    assert "CONFIG_BT_SPP_ENABLED=y" in bridge_defaults


def test_p68_independent_project_source_graph():
    s3 = (ROOT / "esp32/firmware/main/CMakeLists.txt").read_text()
    bridge = (ROOT / "esp32/bridge_firmware/main/CMakeLists.txt").read_text()
    assert '"s3_main.c"' in s3
    assert '"tivoo_spp.c"' not in s3
    assert '"bt_security_policy.c"' not in s3
    assert '"audio_frontend.c"' not in s3  # legacy single-mic runtime not yet migrated
    assert "esp_driver_uart" in s3 and "esp_driver_uart" in bridge
    assert "tivoo_spp.c" in bridge
    assert "esp_wifi" not in bridge and "esp_driver_i2s" not in bridge
    assert "esp-sr" not in bridge and "esp_audio" not in bridge
    entry = (ROOT / "esp32/bridge_firmware/main/main.c").read_text()
    assert entry.index("nvs_flash_init()") < entry.index("tivoo_spp_start()")
    assert "nvs_flash_erase" not in entry


def test_p68_s3_compile_probe_matches_frozen_afe_graph():
    source = (FIRMWARE_MAIN / "s3_api_smoke.c").read_text()
    assert 'esp_srmodel_init("model")' in source
    assert '"MMNR", models, AFE_TYPE_SR, AFE_MODE_HIGH_PERF' in source
    assert 'AEC_MODE_SR_HIGH_PERF' in source
    assert 'config->se_init = true;' in source
    assert 'config->ns_init = false;' in source
    assert 'config->wakenet_init = true;' in source
    assert 'config->vad_mute_playback = false;' in source
    assert 'volatile bool tivoo_s3_enable_api_probe = false;' in source


def test_active_targets_boot_and_memory():
    s3 = ROOT / "esp32/firmware"
    classic = ROOT / "esp32/bridge_firmware"
    for project, target, entry in (
        (s3, "esp32s3", "s3_main.c"),
        (classic, "esp32", "main.c"),
    ):
        project_cmake = (project / "CMakeLists.txt").read_text()
        graph = (project / "main/CMakeLists.txt").read_text()
        assert f'set(IDF_TARGET "{target}" CACHE STRING' in project_cmake
        assert f'if(NOT IDF_TARGET STREQUAL "{target}")' in project_cmake
        assert f'"{entry}"' in graph
        assert "board_boot.c" in graph
        assert "hardware_memory.c" not in graph
        boot = (project / "main" / entry).read_text().split("void app_main(void)", 1)[1]
        assert "tivoo_board_memory_report();" in boot
        assert "nvs_flash_erase" not in boot

    s3_graph = (s3 / "main/CMakeLists.txt").read_text()
    assert '"main.c"' not in s3_graph
    assert '"wifi_station.c"' in s3_graph
    assert '"diagnostics.c"' in s3_graph
    assert '"network_listeners.c"' in s3_graph
    assert "esp_wifi" in s3_graph and "esp-sr" in s3_graph
    s3_boot = (FIRMWARE_MAIN / "s3_main.c").read_text().split("void app_main(void)", 1)[1]
    assert (s3_boot.index("tivoo_wifi_station_init_nvs()")
            < s3_boot.index("tivoo_diagnostics_start()")
            < s3_boot.index("network_listeners_start(7777, 7778)")
            < s3_boot.index("tivoo_wifi_station_start()"))
    assert (s3_boot.index("tivoo_wifi_station_start()")
            < s3_boot.index("tivoo_audio_resource_init()"))
    nvs_guard = s3_boot.split("tivoo_wifi_station_init_nvs()", 1)[1].split(
        "tivoo_audio_resource_init()", 1
    )[0]
    assert "if (err != ESP_OK)" in nvs_guard and "return;" in nvs_guard
    nvs = (FIRMWARE_MAIN / "wifi_station.c").read_text()
    assert "nvs_flash_init()" in nvs and "nvs_flash_erase" not in nvs
    s3_defaults = (s3 / "sdkconfig.defaults").read_text()
    # Effective Wi-Fi/PSRAM budget versus defaults is checked after configure
    # in test_p5b3_bootstrap, rather than pinning a second conflicting value.
    assert "CONFIG_SPIRAM_USE_MALLOC=y" in s3_defaults
    assert "tivoo_board_rgb_off(GPIO_NUM_38)" in s3_boot

    classic_boot = (classic / "main/main.c").read_text().split("void app_main(void)", 1)[1]
    assert (classic_boot.index("tivoo_board_rgb_off(GPIO_NUM_27)")
            < classic_boot.index("nvs_flash_init()")
            < classic_boot.index("tivoo_spp_start()"))
    nvs_guard = classic_boot.split("nvs_flash_init()", 1)[1].split(
        "tivoo_spp_start()", 1
    )[0]
    assert "if (err != ESP_OK)" in nvs_guard and "return;" in nvs_guard

    board = (FIRMWARE_MAIN / "board_boot.c").read_text()
    memory = board.split("void tivoo_board_memory_report(void)", 1)[1]
    for call in (
        "esp_flash_get_size(NULL, &flash)", "esp_psram_is_initialized()",
        "esp_psram_get_size()", "heap_caps_get_total_size(MALLOC_CAP_SPIRAM)",
        "heap_caps_get_free_size(MALLOC_CAP_SPIRAM)",
        "heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM)",
        "heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA)",
        "esp_himem_get_phys_size()", "esp_himem_get_free_size()",
    ):
        assert call in memory
    assert "#if CONFIG_IDF_TARGET_ESP32" in memory
    rgb = board.split("esp_err_t tivoo_board_rgb_off", 1)[1].split(
        "void tivoo_board_memory_report", 1
    )[0]
    assert "rmt_transmit(" in rgb and "rmt_tx_wait_all_done(" in rgb
    assert "gpio_set_level(pin, 0)" in rgb
