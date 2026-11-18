# Tivoo Classic ESP32 bridge (P6.8 b1)

Target: ESP32-WROVER-E-N16R8, ESP-IDF v6.1. This project contains the existing Classic authenticated SPP initiator and local boot diagnostics; the UART transport is intentionally absent until b2. It does not start Wi-Fi or audio.

Build independently on the development host:

```bash
. ~/.espressif/tools/activate_idf_v6.1.sh
export CMAKE_BUILD_PARALLEL_LEVEL=2
idf.py set-target esp32   # first initialization only
ninja -C build -j2
idf.py size
idf.py merge-bin --format raw --flash-offset 0x0 --pad-to-size 16MB
```

The original NVS/PHY/factory/storage layout is retained. NVS initialization errors stop startup; no erase fallback is used. IDF's Bluetooth component transitively depends on esp_wifi; no Wi-Fi station is started by this project.

**Do not flash the current production board during b1.** The new bridge cannot operate as the legacy voice assistant. A padded 16 MiB full image covers NVS and must never be used for an in-place update preserving Bond keys. For an authorized future update use only the compatible generated segments, excluding NVS, and retain the old production app/manifest for rollback. Confirm target, USB mapping and flash geometry physically first.

See the [hardware contract](../../docs/superpowers/specs/2026-11-18-p6-8-b0-2-hardware-uart-spp-design.md) for pin assignments and hardware gates.
