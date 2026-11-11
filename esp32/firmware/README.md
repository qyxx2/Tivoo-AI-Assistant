# Tivoo ESP32 firmware (P5b3)

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

## TCP listeners and Wi-Fi lifecycle

After Station obtains an IPv4 address, the firmware starts two independent IPv4 TCP listener endpoints:

- TCP 7777 — raw Tivoo control bridge.
- TCP 7778 — TVIO v1 diagnostics.

Each port accepts one active client; a second client is closed. Station disconnect / IPv4 loss closes both accepted clients and listener sockets; a later IPv4 event enables them again. A 7778 client reconnect does not close or reset an otherwise-connected 7777 client. A 7777 TCP disconnect only clears its partial command/frame parser state; it does not implicitly disconnect an already-open SPP session.

## TCP 7777 raw control bridge

TCP 7777 is a byte stream, not JSON. The HA integration reads the current Config Entry `tivoo_bluetooth_mac` and sends a seven-byte `0x69 + six raw MAC bytes` connect command at the start of each TCP session. It then sends complete Tivoo protocol frames. A seven-byte `0x96 + MAC` command requests an orderly SPP disconnect.

The byte-stream parser accumulates the fixed-size control commands and delegates Tivoo frame boundaries, checksum validation, escaping, and fragmentation/coalescing to the upstream `esp32-divoom` frame parser adapted to C/ESP-IDF. Its 4608-byte frame buffer is retained. The bridge also verifies that each handler input is exactly one complete checksummed frame; malformed checksum candidates are rejected rather than forwarded as the upstream parser's generic unframed-data callback. The pending threshold accounts for the minimum 2-byte checksum frame size. The firmware does not assume one TCP recv equals one frame and never interprets 0x69/0x96 bytes inside a frame payload as control commands.

The SPP worker is a single FIFO consumer with a 32-request queue. It connects as Classic SPP master/initiator, performs SDP service-channel discovery for the explicit HA-selected MAC, and falls back to RFCOMM channel 1 when discovery fails, times out, or provides no SCN. Every new connect command—including the same MAC—first closes the previous session before connecting. The worker sends original Tivoo frames without decoding or re-encoding them.

Frames are written in chunks no larger than 330 bytes. Each chunk waits for congestion clearance and its SPP write-completion callback before the next chunk; successful frames retain the 15 ms upstream pacing. The SPP_OPEN and GAP AUTH_CMPL results must both succeed for the same configured peer, and the peer must appear in Bluedroid's bond list before frame writes are accepted.

### Pairing behavior

The ESP32 explicitly declares `ESP_BT_IO_CAP_NONE`. Legacy PIN requests for the selected target use 16 ASCII zeroes when `min_16_digit` is set, otherwise ASCII `1234`. SSP numeric-comparison confirmation and passkey-input requests are rejected because the device has no user interface to compare or enter those values. Displayed passkeys are not logged.

The connection security baseline is `ESP_SPP_SEC_AUTHENTICATE | ESP_SPP_SEC_ENCRYPT`. Its actual interoperability with the user's Tivoo revision must be confirmed during P5b4 physical-device acceptance; an authentication failure is never treated as a usable connection and the code does not silently downgrade to an unauthenticated link.

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
    "tests/homeassistant/custom_components/tivoo",
    "-q",
]))
PY
```

No development-board flashing or physical pairing acceptance is part of P5b3. P5b4 owns final merged-image packaging, Windows flashing, first pairing with the actual Tivoo, and verification that the native Bluedroid bond list survives both software restart and complete power loss. P5b3 does not implement a 7777 reverse channel, 7778 heartbeat/DEVICE_STATUS/audio messages, HTTP audio, or I²S/AEC/VAD.
