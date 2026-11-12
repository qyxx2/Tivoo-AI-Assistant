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
