# P5b1 implementation report — ESP32 Station and HA connection lifecycle

**Date:** 2026-11-11
**Branch:** `feature/p5-esp32-minimal-firmware`
**Base:** `137fedb` (P5b0 environment compatibility)
**Contract:** `docs/superpowers/specs/2026-11-11-p5-esp32-minimal-firmware-contract-matrix.md` (authoritative; P5b1 only)

## Delivered

### ESP32 production firmware
- Added `esp32/firmware` as the production ESP-IDF project, retaining ESP-IDF v6.1, `IDF_TARGET=esp32`, the P5b0 managed-component dependency lock, and the WROVER-E N16R8 flash/PSRAM and partition configuration.
- Added local Kconfig values for Wi-Fi SSID/password. The defaults contain no credentials; values are stored in the ignored local `sdkconfig`.
- Added Station initialization (NVS, netif, default event loop, STA interface, Wi-Fi init/config/start) and START, DISCONNECTED, GOT_IP, LOST_IP event handling. Disconnects request reconnect; listener availability follows IPv4 acquisition/loss.
- Startup logs the reset reason and does not log Wi-Fi credentials.
- Added the shared BSD-socket listener manager for IPv4 TCP 7777 and 7778. Both endpoints are independent, allow one active client each, close accepted clients/listeners on IP loss, and reopen after a subsequent IP-up event.

### Home Assistant
- Upgraded the Tivoo Config Entry to version 2.
- Added ESP32 IPv4 and Tivoo Bluetooth MAC config fields, validation, and reconfigure flow.
- Migration from v1 preserves existing entry data and adds only the default Bluetooth MAC. It never guesses or inserts `esp32_host`; migrated entries without a host keep both connection channels unavailable until user reconfiguration.
- Preserved the existing media directory and service registration behavior.
- Added independent HA TCP connection loops for ports 7777 and 7778, with connect/disconnect/reconnect states and unload cleanup.
- Command execution deliberately remains unavailable in P5b1 and raises a clear error; no command payload is sent.

### Network simulator and guidance
- Added a POSIX/pthread simulator that compiles the same listener source used by the ESP-IDF target.
- Added `esp32/firmware/README.md` with local build, secret handling, listener lifecycle, and simulator instructions.
- Added this report and an execution-plan checklist. The P5 contract matrix and its existing batch definitions were not modified.

## Verification

| Verification | Result |
|---|---|
| Tivoo HA tests + ESP32 listener simulator | **122 passed**, 7 warnings |
| POSIX listener simulator | Included in the 122-test run; passed |
| Ruff check | Passed |
| Ruff format check | Passed |
| Firmware translation JSON parse | Passed |
| `git diff --check` | Passed |
| ESP-IDF build | **Passed** with ESP-IDF v6.1, target `esp32` |
| Firmware binary | `0x44470` bytes |
| Smallest application partition | `0x800000` bytes; approximately 97% free |
| Wi-Fi credentials in tracked firmware inputs | None found |
| Local sdkconfig / build / managed components | Ignored by Git |

The IDF build emits several non-fatal Kconfig compatibility/deprecation notices from ESP-IDF v6.1 dependencies. The project sources compile and the final ELF/image and partition-size checks complete successfully.

## Explicitly not done

- No board was flashed; there was no USB or real-hardware Wi-Fi test in this batch.
- No 7778 framing/HELLO protocol, 7777 command framing, SPP forwarding, or audio path was implemented.
- No P5b2, P5b3, or P5b4 work was performed.
- No Wi-Fi credentials were committed.
