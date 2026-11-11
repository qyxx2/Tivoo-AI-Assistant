# P5b2 TCP 7778 Diagnostics Implementation Report

Date: 2026-11-11
Branch: feature/p5-esp32-minimal-firmware
Authoritative contract: docs/superpowers/specs/2026-11-11-p5-esp32-minimal-firmware-contract-matrix.md
Execution plan: docs/superpowers/plans/2026-11-11-p5b2-tcp-7778-diagnostics-implementation-plan.md

## 1. Result

P5b2 implementation is complete in the existing P5 branch. The ESP32 7778 diagnostic channel and HA receiver now implement the P5 TVIO v1 subset. The implementation does not add 7777 application framing, SPP pairing/forwarding, heartbeat/status/audio types, or physical-board behavior.

The implementation reuses the existing P5b1 listener lifecycle and the already-locked Espressif cJSON 1.7.19 component. It does not add a second JSON implementation or a new log-persistence service.

## 2. Implementation

### 2.1 ESP32 firmware

- Added diagnostics.c/.h: fixed 16-byte little-endian TVIO framing, HELLO/HELLO_ACK, ERROR and DIAGNOSTIC_LOG JSON, P5 error-code allowlist, reset-reason names, firmware version with Git short SHA, and per-connection sequence counters.
- Added a low-priority sender task and a 16-record RAM FIFO. Log producers retain console output and use non-blocking enqueue; TCP writes occur only in the diagnostics worker.
- Logs remain queued while 7778 is unavailable or before HA accepts HELLO. On reconnect, the worker sends a new HELLO and waits for an accepted ACK before replaying complete records in FIFO order. A failed partial write does not remove the current record.
- Queue saturation drops the new record. The accumulated count is included in the next successfully sent DIAGNOSTIC_LOG and is only then cleared.
- Added 7778 receive handling to the existing listener worker. The control endpoint remains its P5b1 placeholder; 7778 reconnect is independent of an active 7777 socket.
- Project-owned Wi-Fi/listener events now use the structured diagnostic logging path. No credentials or audio/conversation payloads are included.

Target-build static memory accounting from the ESP32 object symbols:

| Allocation | Bytes |
|---|---:|
| 16-record diagnostic queue | 7,744 |
| TCP receive buffer | 18,448 |
| TCP transmit buffer | 1,040 |
| **Total** | **27,232** |

The figure excludes transient cJSON heap allocations and task stacks. The ESP-IDF size report showed DRAM usage of 47,942 bytes (38.48% of 124,580 bytes), with 76,638 bytes remaining.

### 2.2 Home Assistant

- Added diagnostics.py with an incremental TVIO stream codec. It handles TCP fragmentation/coalescing and validates magic, version, flags, payload limits, and sequence.
- Extended the existing adapter with the 7778 HELLO/ACK session. HA accepts protocol version 1, explicitly rejects unsupported versions, and does not change the 7777 raw connection loop.
- ERROR and DIAGNOSTIC_LOG are validated and mapped to the standard custom_components.tivoo logger. ESP32 DEBUG/INFO/WARNING/ERROR map to the corresponding Python logger levels.
- Malformed individual log payloads are ignored with a warning; malformed protocol framing terminates only the diagnostic connection. Unknown message types remain ignored.
- No custom file handler is added. The integration relies on HA's existing main logger and /config persistence path.

The existing NAS HA deployment mount was previously verified as /volume1/docker/homeassistant/config → /config in docs/superpowers/reports/2026-11-10-p4-runtime-acceptance-report.md §2. This P5b2 development run verified logger delivery with HA test capture; it did not perform a new NAS-side log-file write test.

## 3. Contract traceability

| Contract | Result | Evidence |
|---|---|---|
| P5-C13 | PASS | Python header golden test; ESP32 host socket simulator exchanges TVIO v1 frames with the fixed 16-byte header. |
| P5-C14 | PASS (automated) | HELLO required fields and capabilities assertions; accepted/rejected HELLO_ACK tests; firmware rejects a false ACK and reconnects without draining the queue. |
| P5-C15 | PASS (automated) | ERROR and DIAGNOSTIC_LOG schemas; closed error-code validation; caplog confirms WARNING and ERROR level mapping. |
| P5-C16 | PASS (build + simulator) | HELLO includes fixed device ID, Git-version field, protocol/capabilities, and reset-reason name. Host test checks ESP_RST_POWERON; ESP-IDF v6.1 target compilation validates the actual reset-enum mapping. |
| P5-C17 | PASS (host simulation) | 16-entry queue saturation with dropped_count=4; disconnected buffering/reconnect replay; a forced partial TCP write is retried as a complete record. |
| P5-C18 | PASS (logger and existing deployment path) | HA caplog tests verify the standard Tivoo logger; the existing NAS /config mount is documented by the prior runtime acceptance report. NAS-side file persistence was not re-exercised in this batch. |
| P5-C19 | PASS (source review) | Reviewed all project-owned firmware log sites and structured diagnostic fields. No SSID/password, authorization token, PCM, full STT transcript, or full LLM answer is emitted. |
| P5-C21 | PASS (scope review) | No 7777 command framing/reverse channel, 7778 heartbeat/DEVICE_STATUS/audio message, HTTP audio, I²S/AEC/VAD implementation was added. |

## 4. Verification

All project test groups were run in their established Python environments because the repository separates the HA Core (Python 3.14) and Sherpa service (Python 3.11) dependencies.

| Test group | Command/environment | Result |
|---|---|---:|
| HA + ESP32 | .venv, pytest tests/homeassistant tests/esp32 -q | **234 passed**, 7 warnings |
| Sherpa Wyoming services | .venv-sherpa, pytest tests/services/sherpa_wyoming -q | **128 passed**, 3 warnings |
| **All repository test groups** | Split across the two project environments | **362 passed** |

A monolithic pytest -q is not supported by the repository's split environments: the HA environment lacks the Sherpa-only packages (wyoming, sherpa_onnx, numpy), while the Sherpa environment does not contain the matching HA Core test API. The complete groups passed when run in their matching environments.

Additional checks:

- Ruff format check: passed for all six changed Python implementation/test files.
- Ruff lint check: passed for all six changed Python implementation/test files.
- git diff --check: passed.
- ESP-IDF v6.1 idf.py build, IDF_TARGET=esp32: passed; tivoo_firmware.bin generated at 0x494D0 bytes. The smallest application partition is 0x800000 bytes, with 96% remaining.
- POSIX simulator compiles the same production listener and diagnostics C sources with the locked cJSON component; P5b1 listener regression plus P5b2 simulator tests: **8 passed**.

Warnings are from existing third-party/test dependencies and do not indicate P5b2 test failures.

## 5. Acceptance boundary and deferred work

This is host/target-build acceptance only. The ESP32 image was not flashed, and no physical Wi-Fi, HA-to-device TCP, Tivoo SPP, pairing, or power-cycle behavior was tested here. Those checks remain in P5b4, after P5b3 implements the 7777/SPP path.

P5b3 remains responsible for the 7777 raw bridge, 7-byte MAC commands, Tivoo frame-stream parser, Classic SPP initiation, authentication and native NVS bond persistence. P5b4 remains responsible for merged-image packaging, flashing, and real-device acceptance.
