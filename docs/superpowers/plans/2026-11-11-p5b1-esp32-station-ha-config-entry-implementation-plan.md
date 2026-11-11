# P5b1 ESP32 Station and HA Config Entry — Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. The authoritative P5 matrix owns all batch boundaries; this file is only the execution plan for its existing P5b1 row.

**Goal:** Implement the P5b1 production ESP-IDF scaffold and the corresponding Home Assistant configuration/connection lifecycle without implementing later P5 protocol batches.

**Architecture:** The ESP32 firmware uses ESP-IDF v6.1 native Wi-Fi Station events to control two independent IPv4 TCP listeners. The HA Tivoo integration migrates its existing Config Entry without inventing an ESP32 address, requires explicit IPv4 reconfiguration, and maintains independent connection-state loops for ports 7777 and 7778. Both ends stop at connection lifecycle; P5b2/P5b3 own message framing and control forwarding.

**Tech Stack:** ESP-IDF v6.1 / ESP32 / Xtensa ARM64 toolchain; C and BSD sockets; Home Assistant Core 2026.11.0; pytest-homeassistant; a POSIX host simulator for the firmware listener source.

**Spec:** docs/superpowers/specs/2026-11-11-p5-esp32-minimal-firmware-contract-matrix.md — authoritative requirements in §2, §3, §5.1–§5.2, §8, §9, P5b1 row in §10, and P5-C07/C08/C16/C19/C20/C21 in §10.1. The matrix is the single source for batch definitions; this plan must not redefine P5b1–P5b4.

## Global Constraints

- Keep ESP-IDF exactly v6.1 and IDF_TARGET=esp32; reuse the P5b0 dependency lock and existing ARM64 toolchain.
- Hardware is Waveshare ESP32-DEV-KIT-WROVER-E-M / ESP32-WROVER-E-N16R8; do not substitute WROOM or ESP32-S3.
- Store Wi-Fi SSID/password only in local ignored sdkconfig through Kconfig; never put credentials in defaults, source, logs, or Git.
- Start listeners only after Station receives IPv4; stop listeners when the IPv4 connection is lost.
- TCP 7777 and 7778 are fixed IPv4 listeners, one HA client each, independent of one another.
- Preserve media_directory; migrate the old entry without guessing esp32_host; require user reconfiguration before transport starts.
- HA connects to the configured IPv4 host on ports 7777 and 7778 independently. No payload framing, HELLO, SPP transfer, or audio behavior in P5b1.
- Use the existing TivooCommand semantic seam. Command execution must remain explicitly unavailable until the later raw bridge is implemented; never report a device action as completed.
- Develop and test on the ARM64 Ubuntu host. Do not flash or require USB access to the development board.

## Review Focus

- Legacy entry with a missing ESP32 host must remain unavailable until the user supplies an IPv4 address; it must never inherit a guessed LAN address.
- Reconfiguration must preserve an existing media_directory and Bluetooth MAC unless the user changes them.
- Wi-Fi credentials must not appear in tracked files, build output, or logs; the local sdkconfig must stay ignored.
- IPv4 loss must close both listeners and their accepted sockets; a later IP event must recreate them.
- A second client on either port must be rejected without affecting the existing client or the other port.

---

### Task 1: Migrate Tivoo Config Entry and Add Reconfiguration

**Files:**
- Modify: homeassistant/custom_components/tivoo/const.py
- Modify: homeassistant/custom_components/tivoo/config_flow.py
- Modify: homeassistant/custom_components/tivoo/__init__.py
- Modify: homeassistant/custom_components/tivoo/translations/en.json
- Test: tests/homeassistant/custom_components/tivoo/test_tivoo_config_flow.py

**Interfaces:**
- Config Entry version becomes 2.
- Add CONF_ESP32_HOST = "esp32_host", CONF_TIVOO_BLUETOOTH_MAC = "tivoo_bluetooth_mac", and default MAC 11:75:58:97:49:98.
- async_migrate_entry(hass, entry) -> bool preserves all existing data, adds only the default MAC when absent, and upgrades v1 to v2. It must not invent esp32_host.
- User and reconfigure flows validate IPv4, MAC, and the existing relative media_directory. Reconfiguration updates the same entry and preserves media_directory.

- [x] Write tests for v1 migration, missing-host behavior, required IPv4 input, MAC validation, and reconfigure preservation.
- [x] Run the focused HA tests and observe failures against the current v1 integration.
- [x] Implement the migration and flows with Home Assistant 2026.11 ConfigFlow APIs.
- [x] Run the focused HA tests and the existing service/config tests.

### Task 2: Add Independent HA TCP Connection Adapter Skeleton

**Files:**
- Create: homeassistant/custom_components/tivoo/transport.py
- Modify: homeassistant/custom_components/tivoo/__init__.py
- Test: tests/homeassistant/custom_components/tivoo/test_transport.py
- Test: tests/homeassistant/custom_components/tivoo/test_tivoo_config_flow.py

**Interfaces:**
- Esp32ConnectionAdapter(host: str, retry_interval: float = 1.0) exposes states for control (7777) and diagnostic (7778), async_start(), async_stop(), and async_execute(command: TivooCommand).
- async_execute raises a clear HomeAssistantError stating that command forwarding is not available in P5b1; no bytes are sent.
- Each connection loop connects/reconnects independently and updates its own state. A missing host starts no tasks and remains unavailable.
- async_setup_entry stores the adapter and preserves the current media path/services; async_unload_entry stops both loops.

- [x] Use local asyncio TCP servers as the network simulator and write tests for both-port connect, independent disconnect/reconnect, no-host behavior, and unload cleanup.
- [x] Run the new tests and observe the expected failures.
- [x] Implement the adapter and wire its lifecycle into the config entry.
- [x] Run all Tivoo tests.

### Task 3: Build ESP-IDF Station Firmware and IP-Gated TCP Listeners

**Files:**
- Create: esp32/firmware/CMakeLists.txt
- Create: esp32/firmware/main/Kconfig.projbuild
- Create: esp32/firmware/sdkconfig.defaults
- Create: esp32/firmware/dependencies.lock (copied from the already verified P5b0 lock)
- Create: esp32/firmware/partitions.csv (same verified WROVER-E layout)
- Create: esp32/firmware/main/CMakeLists.txt
- Create: esp32/firmware/main/main.c
- Create: esp32/firmware/main/wifi_station.c and wifi_station.h
- Create: esp32/firmware/main/network_listeners.c and network_listeners.h
- Create: esp32/tests/p5b1_network_simulator/listener_host.c
- Test: tests/esp32/test_p5b1_network_listeners.py

**Interfaces:**
- Kconfig exposes only local TIVOO_WIFI_SSID and TIVOO_WIFI_PASSWORD; neither has a credential value in sdkconfig.defaults.
- tivoo_wifi_station_start(void) -> esp_err_t initializes NVS/netif/event loop/Wi-Fi STA and handles START, DISCONNECTED, GOT_IP, and LOST_IP events. It calls network_listeners_set_ip_available(bool) on IP state changes and logs esp_reset_reason() at startup without logging credentials.
- network_listeners_start(uint16_t control_port, uint16_t diagnostic_port) -> esp_err_t starts one manager task; network_listeners_set_ip_available(bool) enables/disables both listeners. Each listener binds IPv4 INADDR_ANY, listens on its supplied fixed port, accepts one client and closes extra clients.
- The host test compiles the same listener implementation with a small pthread-backed simulator; test-only port overrides avoid fixed-port conflicts.
- No 7777 command parsing, 7778 framing, SPP, protocol payload handling, or board flashing.

- [x] Add a host-simulator test for offline/online listener lifecycle, independent ports, one-client limit, and closing clients on IP loss; observe it fail before the implementation exists.
- [x] Implement the portable listener core and minimal host simulator.
- [x] Build the production firmware using the installed ESP-IDF v6.1 / esp32 environment.
- [x] Run host simulator tests and verify no credential values are tracked or logged.
- [x] Run the final P5b1 verification and inspect the full diff.

---

## Acceptance and Commit

P5b1 is complete only when Tasks 1–3 pass, the production firmware builds for ESP32 under ESP-IDF v6.1, the host simulator proves the listener lifecycle/client limit, HA tests pass, and no board flashing or P5b2–P5b4 behavior is performed. Commit only P5b1 sources, tests, plan, and report on the existing P5 branch.
