# P5 Hardware / Bond / Release Closeout

**Date:** 2026-11-12
**Branch:** `feature/p5-esp32-minimal-firmware`
**Base:** `b2f1af7` (`fix(esp32): reuse bonded SPP connections`)
**Target:** ESP32-DEV-KIT-WROVER-E-M / ESP32-WROVER-E-N16R8 / ESP-IDF v6.1

## Scope

This closeout executes the selected P5 items: (1) actual Flash/PSRAM/linear heap/himem verification, (3) native Bluedroid Bond persistence across a full power cycle, and (5) a new merged release image and manifest from the final source commit. It does not attempt the second-Tivoo replacement or long-scroll acceptance items.

## 1. Actual Flash / PSRAM / heap / himem verification

Added `hardware_memory.c/.h` and invokes `tivoo_hardware_memory_report()` immediately after diagnostics startup. The report is sent to UART and the existing 7778 diagnostic FIFO. It reads actual capacities from ESP-IDF and runs a full physical himem integrity probe before Bluetooth/Wi-Fi startup.

**Board evidence from UART after flashing the memory-report build:**

| Measurement | Actual result |
|---|---:|
| SoC | ESP32-D0WD-V3, revision 3.1 |
| SPI Flash | 16,777,216 bytes (16 MiB), `esp_flash_get_size()` returned `ESP_OK` |
| PSRAM | 8,388,608 bytes (8 MiB), initialized, Quad, 40 MHz |
| ESP-IDF PSRAM startup self-test | `SPI SRAM memory test OK` |
| Linear PSRAM heap total | 3,932,160 bytes (3.75 MiB) |
| Linear PSRAM heap free at report time | 3,929,880 bytes |
| Himem physical pool | 4,456,448 bytes (4.25 MiB) |
| Himem map window | 262,144 bytes (256 KiB) |
| Himem bank size / count | 32,768 bytes / 136 banks |
| Full-pool write/read probe | `himem_probe_ok=1`, `ESP_OK`, 4,456,448 bytes tested |
| Himem free after releasing test allocation | 4,456,448 bytes |

The observed split is not an even 4 MiB + 4 MiB. `CONFIG_SPIRAM_BANKSWITCH_RESERVE=8` reserves eight 32 KiB virtual map blocks for bank switching, yielding a 3.75 MiB linear heap and 4.25 MiB physical himem pool. Together they account for the module's 8 MiB PSRAM. The contract and firmware README now record this measured configuration.

UART capture: NAS `/volume1/docker/tivoo-esptool/artifacts/uart-boot.log`. SHA256: `b52625a987e319e1cda17586ddf29a76209ac1cab842232b7793091a990a9726`.

## 2. Bond persistence across full power-off/on

The user confirmed that the ESP32 had been completely without power overnight and, after the next power-on, automatically rejoined Wi-Fi. The post-power-on device boot used `ESP_RST_POWERON`; HA diagnostics recorded the same configured peer `11:75:58:97:49:98` as `spp_connect_duplicate_ignored`. Firmware emits that event only when the SPP worker already has the same peer in its connected session state. The user also confirmed a real HA voice-assistant invocation of a Tivoo tool successfully executed the command.

The existing-Bond connection path had separately been validated on the physical ESP32 in the preceding closeout report: SPP OPEN success under `AUTHENTICATE | ENCRYPT`, pre/post-connect Bond List presence, `spp_bond_reused_after_open`, and `authenticated_spp_peer_ready ... bond_list=confirmed`. No NVS erase, key copy, or repeated pairing was used for these checks.

**Software restart subtest: NOT RUN.** The contract requires a JTAG/OpenOCD GDB call to `esp_restart()`. The connected NAS exposes only the board's CH343P USB-UART interface; no JTAG adapter is attached. An RTS/EN reset used to capture UART boot output is a hardware reset and is not counted as the software-restart test.

Thus C25's full power-cycle evidence is PASS; its specifically required JTAG software-restart subtest remains NOT RUN. This report does not silently mark the complete C25 row as PASS.

## 3. Persistent NAS esptool utility

Created and started a persistent container on the NAS:

- Directory: `/volume1/docker/tivoo-esptool/`
- Container: `tivoo-esptool`
- Image: `tivoo-esptool:4.8.1`
- Tools: esptool 4.8.1, pyserial 3.5
- Device: `/dev/ttyACM0` (CH343P)
- Restart policy: `unless-stopped`
- Persistent artifacts: `/volume1/docker/tivoo-esptool/artifacts` mounted at `/work`

The container was used to flash the memory diagnostic app at `0x10000`; esptool verified the written image hash. The NVS partition at `0x9000` was not touched. Recreate instructions and a simple `recreate.sh` are stored beside the Dockerfile on the NAS.

## 4. Automated / build verification

- Focused P5 ESP32 + HA Tivoo suite, including the new hardware-memory diagnostic source test: **188 passed, 7 warnings**.
- IDF v6.1 reconfigure/build/size: passed for the memory diagnostic build.
- `git diff --check`: recorded in final closeout after documentation edits.
- Final source commit, merged image and manifest values are recorded below after packaging.

## 5. Remaining P5 observations and P6 continuation

The user explicitly considers the remaining second-Tivoo positive replacement test, post-fix long-scroll observation, and JTAG software-restart check non-blocking for P6 and later implementation. They remain open P5 validation records; they are not reclassified as PASS and do not change the P6 contract. The real HA voice-assistant Tivoo command execution reported by the user is recorded as a successful end-to-end observation.
