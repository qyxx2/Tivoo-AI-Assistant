# P5b2 TCP 7778 Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking. The P5 contract matrix is authoritative for every batch boundary; this plan only decomposes the existing P5b2 row.

**Goal:** Complete the P5 TCP 7778 diagnostic channel with TVIO framing, HELLO/ACK negotiation, ERROR/DIAGNOSTIC_LOG delivery, HA standard logging, and bounded log buffering/replay after reconnect.

**Architecture:** Keep the existing P5b1 Wi-Fi/listener lifecycle and independent HA connections. Add a small Python stream codec and make only the HA diagnostic connection speak TVIO; keep the 7777 channel unchanged. Add a firmware-owned bounded non-blocking diagnostic queue and a low-priority sender that starts with HELLO, waits for an accepted HELLO_ACK, and flushes queued records in order. The existing listener manager remains responsible for socket lifecycle and forwards diagnostic-channel input to the protocol handler.

**Tech Stack:** ESP-IDF v6.1 / ESP32 / FreeRTOS / BSD sockets; Home Assistant Core 2026.11.0 / asyncio; Python standard-library `struct` and `json`; existing pytest and POSIX firmware simulator.

**Spec:** `docs/superpowers/specs/2026-11-11-p5-esp32-minimal-firmware-contract-matrix.md` — authoritative §5.1, §7.1–§7.3, §8, §9, P5b2 row in §10, and P5-C13–C19 plus P5-C21 in §10.1. This plan must not redefine P5b0/P5b1/P5b3/P5b4.

## Global Constraints

- Keep ESP-IDF exactly v6.1 and `IDF_TARGET=esp32`; reuse P5b0 dependency lock and existing ARM64 toolchain.
- Keep TCP 7777 and 7778 as independent IPv4 listeners; this batch implements only the 7778 application protocol.
- Use the fixed 16-byte little-endian TVIO header: magic `TVIO`, version `1`, flags `0`, payload length `uint32`, sequence `uint32`.
- P5 message types are HELLO `0x01`, HELLO_ACK `0x02`, ERROR `0x41`, DIAGNOSTIC_LOG `0x42`; ignore unknown message types.
- P5 JSON payload ceiling is 16 KiB; one diagnostic log JSON is at most 1 KiB; one log message is at most 384 UTF-8 bytes.
- Diagnostic queue depth is 16 records, non-blocking; queue-full drops the new record and increments `dropped_count`.
- Send no diagnostics before HELLO_ACK with `accepted=true`; on each reconnect send a new HELLO and reset that connection's sequence to zero.
- Retain queued records over TCP disconnects in RAM and replay in insertion order after a successful handshake; reboot loss is expected.
- HA maps ESP32 levels DEBUG/INFO/WARNING/ERROR to the matching standard Python logger levels and relies on the existing NAS `/config` volume; do not create another log persistence path.
- Never log Wi-Fi credentials, Authorization/API tokens, PCM, full STT transcripts, or full LLM answer text.
- Do not add heartbeat, DEVICE_STATUS, reverse control channel, HTTP, audio payloads, SPP control, or any P5b3/P5b4 behavior.
- Develop and test on ARM64 Ubuntu; do not flash the board or require USB access.

## Review Focus

- TCP fragmentation/coalescing must not change message boundaries or sequence validation.
- An unsupported protocol version or rejected HELLO_ACK must not unlock log delivery.
- A disconnect during a partially sent record must replay one complete record after reconnect, not resume at a byte offset.
- Queue saturation while disconnected must remain non-blocking, drop new records, and report the accumulated count on the next successfully delivered log.
- Loss of 7778 must not change the active 7777 connection; malformed diagnostic input must not crash either listener task.

---

### Task 1: HA TVIO Codec, Handshake, and Logger

**Files:**
- Create: `homeassistant/custom_components/tivoo/diagnostics.py`
- Modify: `homeassistant/custom_components/tivoo/transport.py`
- Test: `tests/homeassistant/custom_components/tivoo/test_diagnostics.py`
- Test: `tests/homeassistant/custom_components/tivoo/test_transport.py`

**Interfaces:**
- `DiagnosticMessage(message_type: int, flags: int, sequence: int, payload: bytes)`.
- `encode_message(message_type: int, payload: bytes, sequence: int) -> bytes`.
- `DiagnosticFrameStream.feed(data: bytes) -> list[DiagnosticMessage]`; it preserves incomplete bytes, enforces magic/version/flags/length and the expected receive sequence for one TCP connection.
- Only the diagnostic connection uses this codec. The control connection remains a plain TCP lifecycle connection during P5b2.
- A valid ESP32 HELLO requires `device_id`, `firmware_version`, `protocol_version`, `capabilities`, and `reset_reason`. HA accepts only protocol version 1 and sends HELLO_ACK sequence 0; unsupported protocol versions receive `{"accepted":false,"reason":"unsupported_protocol_version"}` and the connection closes.
- After an accepted HELLO, HA consumes ERROR/DIAGNOSTIC_LOG and writes them to the module's standard logger; it ignores unknown message types. ERROR codes follow the P5 closed enum. No custom file handler is added.

- [x] Write codec tests for the exact 16-byte header, partial header/payload, coalesced messages, bad magic/version/flags, invalid lengths, oversized payload, and out-of-order sequence.
- [x] Run the new codec tests and observe the intended failures.
- [x] Implement the Python codec with standard-library `struct`/JSON only.
- [x] Run codec tests and observe them pass.
- [x] Write transport tests proving HELLO/ACK acceptance, unsupported-version rejection, ERROR/DIAGNOSTIC_LOG level mapping via `caplog`, malformed payload handling, and independent control-channel operation during diagnostic reconnect.
- [x] Run the new transport tests and observe the intended failures.
- [x] Implement the HA diagnostic receive loop and logger mapping without changing 7777 behavior.
- [x] Run the focused Tivoo transport/config/service tests.

### Task 2: ESP32 7778 Protocol and Bounded Diagnostic Queue

**Files:**
- Create: `esp32/firmware/main/diagnostics.c`
- Create: `esp32/firmware/main/diagnostics.h`
- Modify: `esp32/firmware/main/main.c`
- Modify: `esp32/firmware/main/network_listeners.c`
- Modify: `esp32/firmware/main/wifi_station.c`
- Modify: `esp32/firmware/main/CMakeLists.txt`
- Modify: `esp32/tests/p5b1_network_simulator/listener_host.c`
- Modify: `tests/esp32/test_p5b1_network_listeners.py`
- Create: `esp32/tests/p5b2_diagnostics_simulator/diagnostics_host.c`
- Test: `tests/esp32/test_p5b2_diagnostics.py`

**Interfaces:**
- `esp_err_t tivoo_diagnostics_start(void)`; starts one low-priority sender task and initializes the bounded queue.
- `void tivoo_diagnostics_client_connected(int fd)`, `bool tivoo_diagnostics_client_data(int fd, const uint8_t *data, size_t size)`, and `void tivoo_diagnostics_client_disconnected(int fd)`; called by the existing listener worker for port 7778 only. The data callback returns false for invalid/rejected protocol input so the listener closes that connection.
- `void tivoo_log_write(esp_log_level_t level, const char *module, const char *format, ...)`; keeps local ESP-IDF console logging and enqueues a bounded network record. `TIVOO_LOGD/I/W/E` macros wrap it.
- `void tivoo_report_error(const char *error_code, const char *module, const char *message)`; accepts only the P5 error-code enum.
- Device sends HELLO as type `0x01`, sequence 0, with `device_id=tivoo-esp32`, app version plus Git short SHA, protocol version 1, capabilities `spp_control` and `remote_diagnostics`, and the ESP-IDF reset-reason enum name. HELLO_ACK type `0x02`, sequence 0, must contain a boolean `accepted`; rejected/invalid ACK never enables log delivery.
- Device log queue holds 16 records with a 384-byte message ceiling. A successful DIAGNOSTIC_LOG send carries the accumulated dropped count and clears only the count included in that successful send. ERROR and DIAGNOSTIC_LOG use the exact P5 JSON fields and 16-byte header.
- Network sends run only in the diagnostics worker; Wi-Fi/listener callbacks and logging macros never perform blocking socket writes.

- [x] Write POSIX simulator tests for HELLO bytes/schema, accepted/rejected ACK, ordered log delivery, disconnect/reconnect HELLO, replay after a mid-record disconnect, queue depth 16, dropped-count reporting, and independent 7777 availability.
- [x] Run the simulator tests and observe the intended failures.
- [x] Implement the diagnostics module and connect it to the existing 7778 receive lifecycle.
- [x] Convert project-owned Wi-Fi/listener startup and failure messages to `TIVOO_LOG*`; report the applicable P5 network error codes without logging credentials.
- [x] Run the POSIX simulator tests and observe them pass.
- [x] Build the production firmware with ESP-IDF v6.1 / `esp32`; confirm the new firmware links successfully.
- [x] Re-run P5b1 listener lifecycle tests to prove no regression.

### Task 3: Documentation, Contract Traceability, and Final Verification

**Files:**
- Modify: `esp32/firmware/README.md`
- Create: `docs/superpowers/reports/2026-11-11-p5b2-diagnostics-implementation-report.md`
- Create: `.superpowers/sdd/2026-11-11-p5b2-tcp-7778-diagnostics-implementation-plan/progress.md`

- [x] Document the 7778 handshake, message types, reconnect replay behavior, queue limits, local build/test commands, and explicit P5 scope exclusions.
- [x] Record evidence against P5-C13–C19 and P5-C21; clearly separate automated host evidence from not-yet-performed board acceptance.
- [x] Run the complete project test suite, Ruff check/format, firmware build, and `git diff --check`; read every final output.
- [x] Inspect the final diff for credentials, logs containing sensitive payloads, and any 7777/P5b3/P5b4 scope creep.
- [x] Commit only the P5b2 implementation, tests, execution plan, and report on `feature/p5-esp32-minimal-firmware`.

**Out of scope:** P5b3 7777 command framing, SPP initiator/pairing/bond persistence; P5b4 final merge image, flashing, physical Wi-Fi/SPP/peer replacement tests; all P6/P7/P8 behavior.
