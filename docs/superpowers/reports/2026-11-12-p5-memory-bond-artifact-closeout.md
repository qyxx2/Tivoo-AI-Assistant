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

The overnight power-cycle recovery observation passes for Wi-Fi and post-boot SPP command availability. However, no dedicated `spp_bond_reused_after_open` record or explicit no-PIN/no-repair observation was captured for this particular cold boot, so the strict “reuse the same Bond Key without manual pairing after full power loss” subcondition remains partially evidenced rather than fully PASS. The specifically required JTAG software-restart subtest is also NOT RUN. C25 as a whole is not marked fully PASS.

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
- IDF v6.1 reconfigure/build/size: passed for final source commit `22fcf1d63c67c3a871847138a8613bb45ca700cc`.
- Xtensa toolchain: `xtensa-esp-elf esp-15.2.0_20251204`, GCC 15.2.0.
- `git diff --check`: passed before commit; final worktree was clean after source commit.
- Final app binary: 1,262,688 bytes; final version string: `0.1.0+22fcf1d`; factory app partition: 8 MiB (85% available by IDF size report).

## 5. Remaining P5 observations and P6 continuation

The user explicitly considers the remaining second-Tivoo positive replacement test, post-fix long-scroll observation, and JTAG software-restart check non-blocking for P6 and later implementation. They remain open P5 validation records; they are not reclassified as PASS and do not change the P6 contract. The overnight boot and subsequent successful SPP tool command are recorded as positive recovery evidence, but the cold-boot no-repair Bond detail and JTAG restart remain explicitly incomplete. The real HA voice-assistant Tivoo command execution reported by the user is recorded as a successful end-to-end observation.


## 6. Final release package (source commit `22fcf1d`)

Package directory: `esp32/firmware/build/p5-final/`.

| Artifact | Size | SHA256 | Flash offset |
|---|---:|---|---|
| `tivoo-esp32-wrover-e-n16r8-p5-final-22fcf1d.bin` | 16,777,216 bytes | `302a6c27695c150fd66671f7c35f64155589d4c8ab5d36afc419cf5b50b6628e` | `0x000000` |
| `tivoo-esp32-app-p5-final-22fcf1d.bin` | 1,262,688 bytes | `32f1134d533daadeca0756640fcccab2d92892628584f4b1e63e2753f5e19e30` | `0x010000` |
| `flash_args.txt` | 173 bytes | `8e367aef27a99fa431f7d5009a48bb11193125a3097a5c487b8d57c53e1feb86` | IDF-derived segment map; paths resolve within package |
| `bootloader/bootloader.bin` | 26,176 bytes | `20688f24a9a694a3e07afd4dbcb5cfd297169896a30bb67143ca695fd9e1c098` | `0x1000` |
| `partition_table/partition-table.bin` | 3,072 bytes | `fc0cac519e0c7119f7ed0fa70326b9516f35a4c98ca3cd1ad50262b415f6dc90` | `0x8000` |
| `manifest.json` | 4,128 bytes | `41ce22bb26733a509e219a9cd2b1c349e93f42bc4d1d665d7de68311520ee1bb` | metadata |

The merged image was generated by ESP-IDF v6.1 `idf.py merge-bin --format raw --pad-to-size 16MB` and esptool updated the image SHA digest. The image length is exactly 16 MiB. The app-only image SHA matches the build's `tivoo_firmware.bin`. The `flash_args.txt` file is based on IDF-generated `build/flash_args`; its app filename is normalized to the package app binary, and all three referenced segment binaries are included under the same relative paths, so the argument file can be used from the package directory. The HELLO firmware version embedded in the app image is `0.1.0+22fcf1d`, matching the package source revision. `manifest.json` records the exact partition layout, flash geometry, toolchain, segment checksums and Wi-Fi credential-presence metadata without disclosing SSID/password values.

**NVS warning:** The full image spans the complete 16MiB flash and overwrites NVS. For an already paired board, routine update must flash only the app image at `0x10000`; do not erase NVS at `0x9000`.

The release package was copied to NAS `/volume1/docker/tivoo-esptool/artifacts/p5-final/` for persistent access through the esptool container. All six NAS files (full image, app-only image, flash arguments, manifest, bootloader and partition table) were re-hashed on the NAS and matched the development-machine values above. The NAS container remained running with restart policy `unless-stopped`. This package contains the local Wi-Fi-enabled firmware image and is private deployment material; do not publish it.
