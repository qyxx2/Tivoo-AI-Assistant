# Tivoo ESP32 firmware (P5b4)

This is the production ESP-IDF project for the ESP32-WROVER-E-N16R8 target. It is pinned to ESP-IDF v6.1 and `IDF_TARGET=esp32`. The dependency lock and partition layout are carried forward from P5b0 compatibility verification. The firmware is a Wi-Fi Station, two TCP listeners, and a Bluetooth Classic SPP initiator; it does not run the Tivoo display codec or any audio pipeline.

## Local build

From this directory on the ARM64 Ubuntu development machine:

```bash
. /home/Gold/.espressif/tools/activate_idf_v6.1.sh
export IDF_TARGET=esp32
idf.py build
```

For initial setup or to change the target, use `idf.py set-target esp32`. In menuconfig, open **Tivoo Wi-Fi** and set `TIVOO_WIFI_SSID` and `TIVOO_WIFI_PASSWORD` for the local 2.4 GHz network. IDF stores these values in the ignored local `sdkconfig`; keep that file out of commits and never paste credentials into source files, defaults, issue logs, or build reports.

The default controller mode is Classic-only (`BR_EDR_ONLY`) with Bluedroid and SPP enabled. The generated application image is `build/tivoo_firmware.bin`.

At CMake configure time, the firmware version is generated as `0.1.0+<git-short-sha>` from repository HEAD.

## Startup and NVS ownership

Startup order is diagnostics worker, `nvs_flash_init()`, Bluetooth Controller/Bluedroid/SPP, TCP listener manager, and then Wi-Fi Station. Bluetooth is never initialized when NVS initialization fails.

There is deliberately no automatic `nvs_flash_erase()` fallback. An NVS initialization error stops startup and is reported through the existing 7778 diagnostics path. This preserves previously stored Bluetooth bonds instead of silently deleting the entire NVS partition.

Bond keys are owned by ESP-IDF Bluedroid. In the pinned ESP-IDF v6.1 source, the Classic authentication-completion path in `btc_dm.c` calls `btc_storage_add_bonded_device()`; `btc_storage.c` persists the peer Link Key and associated metadata through `btc_config`; `btc_config.c` uses the OSI config store, whose `config.c` backend opens and saves the NVS namespace. The application reads only the Bluedroid bond-device address list to confirm the selected peer; it does not read, duplicate, or log key contents.

## Boot-time hardware memory diagnostics

At every boot, before Bluetooth and Wi-Fi initialization, the firmware reports the actual flash size, PSRAM initialization/size, linear PSRAM heap total/free, internal heap free, and himem physical/free/map-window values to UART and the 7778 diagnostic queue.

With the current WROVER-E-N16R8 configuration (`CONFIG_SPIRAM_BANKSWITCH_RESERVE=8`), the tested board reports:

- SPI Flash: 16,777,216 bytes (16 MiB).
- PSRAM: initialized, 8,388,608 bytes (8 MiB), Quad, 40 MHz; ESP-IDF's built-in SPI SRAM memory test passes.
- Linear `MALLOC_CAP_SPIRAM` heap: 3,932,160 bytes total (3.75 MiB); startup free value varies slightly with allocations.
- Himem physical pool: 4,456,448 bytes (4.25 MiB), 136 blocks of 32 KiB; reserved virtual mapping window: 262,144 bytes (256 KiB).
- The startup himem probe allocates the full physical pool, maps each 32 KiB bank, writes a deterministic pattern, unmaps, maps again and verifies every word; `himem_probe_ok=1` means all 4,456,448 bytes passed write/read verification and were released.

The linear heap and himem pool together account for the physical 8 MiB PSRAM. Do not interpret the module's 8 MiB total as 8 MiB of simultaneously linear `malloc()` space. The bank-switching reservation causes the actual split to be 3.75 MiB linear + 4.25 MiB himem with this IDF configuration. The full himem probe takes about four seconds on the tested board and runs before the Wi-Fi connection is started.

## TCP listeners and Wi-Fi lifecycle

After Station obtains an IPv4 address, the firmware starts two independent IPv4 TCP listener endpoints:

- TCP 7777 — raw Tivoo control bridge.
- TCP 7778 — TVIO v1 diagnostics.

Each port accepts one active client; a second client is closed. Station disconnect / IPv4 loss closes both accepted clients and listener sockets; a later IPv4 event enables them again. A 7778 client reconnect does not close or reset an otherwise-connected 7777 client. A 7777 TCP disconnect only clears its partial command/frame parser state; it does not implicitly disconnect an already-open SPP session.

## TCP 7777 raw control bridge

TCP 7777 is a byte stream, not JSON. The HA integration reads the current Config Entry `tivoo_bluetooth_mac` and sends a seven-byte `0x69 + six raw MAC bytes` connect command at the start of each TCP session. It then sends complete Tivoo protocol frames. A seven-byte `0x96 + MAC` command requests an orderly SPP disconnect.

The byte-stream parser accumulates the fixed-size control commands and delegates Tivoo frame boundaries, checksum validation, escaping, and fragmentation/coalescing to the upstream `esp32-divoom` frame parser adapted to C/ESP-IDF. Its 4608-byte frame buffer is retained. The bridge also verifies that each handler input is exactly one complete checksummed frame; malformed checksum candidates are rejected rather than forwarded as the upstream parser's generic unframed-data callback. The pending threshold accounts for the minimum 2-byte checksum frame size. The firmware does not assume one TCP recv equals one frame and never interprets 0x69/0x96 bytes inside a frame payload as control commands.

The SPP worker is a single FIFO consumer with a 32-request queue. It connects as Classic SPP master/initiator, performs SDP service-channel discovery for the explicit HA-selected MAC, and falls back to RFCOMM channel 1 when discovery fails, times out, or provides no SCN. A duplicate connect command for the same peer while its SPP session is already connected is idempotent and does not close/reopen the link. If the selected same peer has lost its link, the reconnect worker retries it; selecting a different MAC orderly closes the previous peer before connecting to the new one. The worker sends original Tivoo frames without decoding or re-encoding them.

Frames are written in chunks no larger than 330 bytes. Each chunk waits for congestion clearance and its SPP write-completion callback before the next chunk; successful frames retain the 15 ms upstream pacing. For a first pairing/new Link Key, the target-matched GAP AUTH_CMPL must report success and the target must appear in Bluedroid's bond list. Bluedroid does not guarantee a fresh successful AUTH_CMPL callback when reusing an existing BR/EDR Bond Key: in that path, the target must already be bonded before connect, RFCOMM SPP OPEN must succeed under `ESP_SPP_SEC_AUTHENTICATE | ESP_SPP_SEC_ENCRYPT`, and the target must still be present in the Bond List after OPEN. Any actual authentication failure remains fail-closed. Both paths end at `authenticated_spp_peer_ready` only after the post-connect Bond List check.

### Pairing behavior

The ESP32 explicitly declares `ESP_BT_IO_CAP_NONE`. Legacy PIN requests for the selected target use 16 ASCII zeroes when `min_16_digit` is set, otherwise ASCII `1234`. SSP numeric-comparison confirmation and passkey-input requests are rejected because the device has no user interface to compare or enter those values. Displayed passkeys are not logged.

The connection security baseline is `ESP_SPP_SEC_AUTHENTICATE | ESP_SPP_SEC_ENCRYPT`. It is retained for both first pairing and existing-Bond reuse; an authentication failure is never treated as a usable connection and the code does not silently downgrade to an unauthenticated link. Existing-Bond event behavior and the target Bond List checks are documented in P5-C24.

The HA Config Entry's `tivoo_bluetooth_mac` is the only target address source. The firmware contains no fixed Tivoo MAC, does not run Classic device Inquiry or BLE scanning, and does not select a device by advertised name. The address entered in HA must be the user-confirmed Classic `Tivoo-audio` address, not the `Tivoo-light` BLE address.

## TCP 7778 TVIO v1 protocol

Each TCP application message uses the fixed 16-byte little-endian header:

| Offset | Size | Field | P5 value |
|---:|---:|---|---|
| 0 | 4 | Magic | ASCII `TVIO` |
| 4 | 1 | Version | `1` |
| 5 | 1 | Message type | `0x01`, `0x02`, `0x41`, or `0x42` |
| 6 | 2 | Flags | `0` |
| 8 | 4 | Payload length | Unsigned JSON payload byte length |
| 12 | 4 | Sequence | Per sending direction, starts at `0` for each TCP connection |
| 16 | N | Payload | UTF-8 JSON object, without a NUL terminator |

TCP fragmentation/coalescing is handled as a byte stream; a receive call is not assumed to contain one complete message. P5 JSON payloads are capped at 16 KiB and diagnostic log JSON is capped at 1 KiB.

| Type | Name | Direction | Purpose |
|---:|---|---|---|
| `0x01` | HELLO | ESP32 → HA | Sent first after a 7778 connection |
| `0x02` | HELLO_ACK | HA → ESP32 | Accept or reject the device protocol session |
| `0x41` | ERROR | ESP32 → HA | Device error report |
| `0x42` | DIAGNOSTIC_LOG | ESP32 → HA | Device runtime log |

HELLO contains the fixed `device_id: "tivoo-esp32"`, firmware version with build SHA, `protocol_version: 1`, capabilities `["spp_control", "remote_diagnostics"]`, and the name returned by ESP-IDF `esp_reset_reason()`. HA replies with `{"accepted": true}`. An incompatible protocol version is rejected with `{"accepted": false, "reason": "unsupported_protocol_version"}`; firmware does not transmit logs until an accepted ACK is received.

DIAGNOSTIC_LOG contains `level`, `module`, `message`, and `uptime_ms`, plus optional `correlation_id` and `dropped_count`. Levels are `DEBUG`, `INFO`, `WARNING`, and `ERROR` (`ESP_LOG_WARN` maps to `WARNING`). ERROR contains `error_code`, `module`, `message`, and `uptime_ms`, plus optional `correlation_id`. P5 error codes are restricted to:

`wifi_init_failed`, `wifi_connect_failed`, `tcp_listen_failed`, `spp_init_failed`, `spp_connect_failed`, `spp_disconnect_failed`, `spp_not_connected`, `spp_tx_queue_full`, `spp_write_failed`, `tcp_control_malformed`, and `tivoo_frame_malformed`.

## Diagnostic queue and logging

Project-owned firmware code uses `TIVOO_LOGE/W/I/D` or `tivoo_report_error()`. These keep the corresponding ESP-IDF console output and enqueue a structured record for TCP 7778. Third-party component output remains on the local UART; P5b2 does not replace the global ESP-IDF log handler.

The diagnostic queue is a 16-record RAM FIFO. Log messages are limited to 384 UTF-8 bytes and serialized DIAGNOSTIC_LOG payloads to 1 KiB. Enqueue is non-blocking. A full queue drops the new record and increments a counter; the next successfully transmitted DIAGNOSTIC_LOG includes the accumulated `dropped_count`, which is cleared only after that message is sent successfully. The target build allocates 7,744 bytes for the queue, 18,448 bytes for the receive buffer, and 1,040 bytes for the transmit buffer (27,232 bytes total, excluding transient cJSON heap allocations).

The low-priority diagnostics worker is the only firmware path that writes to the 7778 socket. It sends HELLO, waits for an accepted HELLO_ACK, then drains the queue in FIFO order. A disconnect or failed partial socket write leaves the current record queued; a new connection starts a new HELLO/ACK exchange and replays complete records from the queue head. This queue is RAM-only: records are not preserved across an ESP32 reboot.

The HA integration writes received ERROR and DIAGNOSTIC_LOG records to the standard `custom_components.tivoo` Python logger, with ESP32 levels mapped to the corresponding Python levels. HA's normal main log and the existing NAS `/config` volume remain responsible for persistence; the integration does not create a second file handler or a new NAS logging service.

Do not log Wi-Fi credentials, Authorization/API tokens, PCM/audio content, full speech transcripts, or full LLM response text. Keep device diagnostics to module names, short events, closed error codes, uptime, firmware/reset metadata, and optional correlation IDs.

## Host simulation and tests

The POSIX simulators compile the same production parser, listener, diagnostics, GAP policy, and SPP session-policy code with host mocks. They exercise segmented control commands, segmented/coalesced Tivoo frames, FIFO connect/frame/disconnect operations, 330-byte writes, write-completion failure gating, MAC replacement, Legacy PIN/SSP callbacks, authentication result matching, bond-address matching, listener behavior, and 7778 reconnect/log replay.

From the repository root:

```bash
PYTHONPATH=homeassistant .venv/bin/python - <<'PY'
import homeassistant
import pytest
raise SystemExit(pytest.main([
    "tests/esp32/test_p5b1_network_listeners.py",
    "tests/esp32/test_p5b2_diagnostics.py",
    "tests/esp32/test_p5b3_bootstrap.py",
    "tests/esp32/test_p5b3_control_bridge.py",
    "tests/esp32/test_p5b3_security.py",
    "tests/esp32/test_p5b3_session.py",
    "tests/esp32/test_p5b4_integration.py",
    "tests/homeassistant/custom_components/tivoo",
    "-q",
]))
PY
```

No development-board flashing or physical pairing acceptance is part of P5b3. P5b4 owns final merged-image packaging, Windows flashing, first pairing with the actual Tivoo, and verification that the native Bluedroid bond list survives both software restart and complete power loss. P5b3 does not implement a 7777 reverse channel, 7778 heartbeat/DEVICE_STATUS/audio messages, HTTP audio, or I²S/AEC/VAD.

## P5 final release package and flashing

The release package is generated on the ARM64 Ubuntu development machine after a clean ESP-IDF v6.1 build from the final closeout commit:

`build/p5-final/`

- `tivoo-esp32-wrover-e-n16r8-p5-final-<commit>.bin` — complete raw 16MB flash image, including bootloader, partition table and application; flash once at offset `0x000000`.
- `tivoo-esp32-app-p5-final-<commit>.bin` — application-only image; flash at `0x010000` for a compatible firmware update after initial installation. It does not overwrite NVS, the partition table or bootloader.
- `bootloader/bootloader.bin` and `partition_table/partition-table.bin` — standalone IDF segments for use with the package `flash_args.txt`.
- `manifest.json` — exact source commit, IDF/toolchain version, flash geometry, partition layout, image sizes and SHA256 values.
- `flash_args.txt` — IDF-generated flash segment map with paths resolved against the package directory; it can be used with `esptool write_flash @flash_args.txt` when run from that directory.

The complete image is exactly 16,777,216 bytes and is padded to the full 16MB address range. Flash it using ESP32 target, 16MB flash size, DIO mode and 40MHz frequency. It is a single image at address `0x000000`; do not also program the individual bootloader/partition/application files. Check its SHA256 against `manifest.json` on Windows before flashing.

**NVS preservation:** The full 16MB image covers the NVS partition and is intended for first installation or a deliberate full reinitialization. Flashing it again after pairing will replace the existing NVS contents, including Bluetooth Bond Keys. For an ordinary firmware update after the device has been paired, use the application-only image at `0x010000` and do not erase flash/NVS. Keep the partition layout unchanged.

All firmware builds, tests, merge-bin generation and hash verification are performed on ARM Ubuntu. The NAS-attached `tivoo-esptool` container is used only for physical-board flashing and UART inspection; Windows may also be used as a manual flashing station, but is not a build or test host.

## NAS-attached persistent esptool utility

The development workspace remains the source/build/test machine. The NAS only hosts a persistent utility container for the ESP32 board physically attached to its CH343P USB-UART adapter:

- Container configuration directory: `/volume1/docker/tivoo-esptool/`
- Container: `tivoo-esptool` (restart policy `unless-stopped`)
- Image: `tivoo-esptool:4.8.1` (esptool 4.8.1 + pyserial 3.5)
- Serial device: `/dev/ttyACM0`
- Artifact bind mount: host `/volume1/docker/tivoo-esptool/artifacts` → container `/work`

Examples from the NAS shell:

```bash
docker exec tivoo-esptool esptool.py version
docker exec tivoo-esptool python -m esptool --chip esp32 -p /dev/ttyACM0 chip_id
docker exec tivoo-esptool python -m esptool --chip esp32 -p /dev/ttyACM0 -b 460800 write_flash --flash_mode dio --flash_freq 40m --flash_size 16MB 0x10000 /work/tivoo_firmware.bin
```

Use the app-only image at `0x10000` for normal updates to an already paired board. Do not erase flash or write the NVS partition at `0x9000`; it stores Wi-Fi settings and Bluedroid Bond Keys. The full merged image at offset `0x000000` covers the full 16 MiB address range and overwrites NVS. Build, tests, merge-bin and checksum generation remain on ARM Ubuntu; do not build firmware on the NAS.

## P5b4 physical-device acceptance

Use the Classic Bluetooth address of the actual Tivoo audio endpoint (`Tivoo-audio`), not the BLE address of `Tivoo-light`. Enter that address in the HA Config Entry `tivoo_bluetooth_mac`; it remains the single source of the peer address. Do not hardcode it in firmware.

After boot, verify Wi-Fi obtains an address and HA establishes both TCP channels. On the 7778 log stream, a new Link Key path includes `auth_complete peer=<configured-MAC> status=0 ... target_match=1 authenticated=1` followed by `spp_bond_created_after_auth`; an existing-Bond path may not emit a new successful AUTH_CMPL and instead includes `spp_bond_reused_after_open ... security=authenticate+encrypt`. Both paths must end with `authenticated_spp_peer_ready peer=<configured-MAC> bond_list=confirmed`.

A wrong peer or failed authentication must log `authenticated=0` and must never reach the ready state or accept frame writes.

For software-restart acceptance, invoke ESP-IDF `esp_restart()` through a JTAG/OpenOCD GDB session while the board is running. Pressing EN, disconnecting USB or cycling the power supply is a hardware reset/power cycle, not a software-restart test. If a JTAG debugger is unavailable, leave the software-restart result NOT RUN; do not mark an EN-button reset as its substitute.

After pairing, verify native Bluedroid Bond Key reuse through both a software restart and a complete power-off/on cycle. Do not forget the Tivoo in the phone or erase NVS between these steps. A successful reconnect must use the same configured Classic MAC, return to the authenticated SPP-ready state without a new pairing/PIN interaction, and accept a real HA control command.

To verify HA-side MAC replacement, change only `tivoo_bluetooth_mac` in the HA Config Entry and reload the existing integration. The ESP32 must disconnect the old peer and attempt the new configured address without firmware rebuild or reflash. Use a second real Tivoo for a positive replacement-pairing test; an intentionally wrong address is useful only to verify fail-closed rejection, not to claim successful replacement pairing.

A complete overnight power-off/on cycle was user-tested on 2026-11-12: the device automatically rejoined Wi-Fi on the next power-on. HA diagnostics subsequently observed the same configured peer in the already-connected SPP session (`spp_connect_duplicate_ignored`), and the user confirmed an HA voice-assistant Tivoo tool command executed successfully. No NVS erase or re-pairing was performed.

A JTAG/OpenOCD GDB software restart invoking `esp_restart()` remains NOT RUN because the current NAS connection exposes only the CH343P USB-UART interface and no JTAG adapter is connected. The EN/RTS reset used for serial boot-log capture is a hardware reset and is not substituted for this test. The user has explicitly accepted this remaining software-restart check, the second-Tivoo replacement check and the post-fix long-scroll observation as non-blocking for P6 and later implementation; they remain visible as P5 residual validation items.

Finally, disable the Wi-Fi AP or remove the ESP32 from the network. Both TCP sessions should close; after network recovery, HA must reconnect, complete the 7778 HELLO/ACK exchange, restore the 7777 control session and deliver a fresh command.

The P5b4 report records each physical item separately from host-test results.
