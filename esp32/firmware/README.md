# Tivoo ESP32 firmware (P5b2)

This is the production ESP-IDF project for the ESP32-WROVER-E-N16R8 target. It is pinned to ESP-IDF v6.1 and `IDF_TARGET=esp32`. The dependency lock and partition layout are carried forward from the P5b0 compatibility verification. P5b2 reuses the already-locked Espressif cJSON 1.7.19 component.

## Local build

From this directory on the ARM64 Ubuntu development machine:

```bash
. /home/Gold/.espressif/tools/activate_idf_v6.1.sh
idf.py build
```

For an initial setup or to change the target, use `idf.py set-target esp32`. In menuconfig, open **Tivoo Wi-Fi** and set `TIVOO_WIFI_SSID` and `TIVOO_WIFI_PASSWORD` for the local 2.4 GHz network. IDF stores these values in the ignored local `sdkconfig`; keep that file out of commits and never paste credentials into source files, defaults, issue logs, or build reports.

At CMake configure time, the firmware version is generated as `0.1.0+<git-short-sha>` from the repository HEAD. The generated application image is `build/tivoo_firmware.bin`.

## TCP listeners and Wi-Fi lifecycle

The firmware starts the Wi-Fi Station and two independent IPv4 TCP listener endpoints after Station obtains an IPv4 address:

- TCP 7777 — control channel. P5b2 deliberately leaves application framing and SPP forwarding for P5b3.
- TCP 7778 — diagnostic channel implemented in P5b2.

Each port accepts one active client; a second client is closed. Station disconnect / IPv4 loss closes both accepted clients and listener sockets; a later IPv4 event enables them again. A 7778 client reconnect does not close or reset an otherwise-connected 7777 client.

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

The POSIX simulator compiles the same production `diagnostics.c` and `network_listeners.c` sources with pthreads and the already-locked cJSON component. It exercises HELLO/ACK, ERROR/DIAGNOSTIC_LOG encoding, reconnect and FIFO replay, queue saturation and dropped-count reporting, rejected ACK behavior, partial-write retry, and independent 7777 availability.

From the repository root:

```bash
.venv/bin/python - <<'PY'
import homeassistant
import pytest
raise SystemExit(pytest.main([
    "tests/esp32/test_p5b1_network_listeners.py",
    "tests/esp32/test_p5b2_diagnostics.py",
    "-q",
]))
PY

PYTHONPATH=homeassistant .venv/bin/python - <<'PY'
import homeassistant
import pytest
raise SystemExit(pytest.main([
    "tests/homeassistant/custom_components/tivoo/test_diagnostics.py",
    "tests/homeassistant/custom_components/tivoo/test_transport.py",
    "tests/homeassistant/custom_components/tivoo/test_tivoo_config_flow.py",
    "tests/homeassistant/custom_components/tivoo/test_services.py",
    "-q",
]))
PY
```

No development-board flashing or physical Wi-Fi/SPP acceptance is part of P5b2. P5b3 owns 7777 framing, Classic SPP initiation/pairing and bond persistence. P5b4 owns final merged-image packaging, flashing and physical-device acceptance. P5b2 does not implement a 7777 reverse channel, 7778 heartbeat/DEVICE_STATUS/audio messages, HTTP audio, or I²S/AEC/VAD.
