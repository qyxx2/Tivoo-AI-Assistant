# P6b0 — TVIO v1 双向协议底座

**Date:** 2026-11-12  
**Branch:** feature/p6-esp32-ha-bidirectional-communication  
**Base:** cf96abf  
**Scope:** P6b0 only; P6b1–P6b6 remain unstarted.

## 1. Delivered

- Kept the P5 TVIO v1 16-byte little-endian header and existing Python codec API.
- Added all 17 P6/P5 message type constants and direction sets. JSON payloads remain capped at 16 KiB, MIC_PCM binary payloads at 4 KiB, and DIAGNOSTIC_LOG at 1 KiB.
- Preserved incremental TCP framing, fragmented/coalesced frames, per-direction uint32 Sequence state and wraparound. Unknown structurally valid message types are consumed without losing the next frame and reported as protocol_unsupported_message.
- Extended HELLO capabilities to the seven values defined by the P6 contract matrix. HELLO_ACK accepted/reason behavior remains unchanged.
- Added HA async_send_message() and register_message_handler() APIs. Sending is unavailable before the diagnostic handshake is accepted; outbound Sequence is independent of inbound Sequence and resets on reconnect.
- Added ESP32 tivoo_diagnostics_send_message() and tivoo_diagnostics_set_message_handler(). Outbound messages are copied into a bounded four-entry queue; callers do not perform socket writes. The realtime queue is independent from the existing 16-record P5 diagnostic queue, and the worker alternates the two queues so neither starves the other. Disconnect clears transient realtime messages but preserves queued P5 diagnostics.
- The ESP32 dispatcher owns HELLO_ACK handling and invokes registered handlers outside the protocol mutex.

## 2. Files

- homeassistant/custom_components/tivoo/diagnostics.py
- homeassistant/custom_components/tivoo/transport.py
- esp32/firmware/main/diagnostics.c
- esp32/firmware/main/diagnostics.h
- esp32/tests/p5b2_diagnostics_simulator/diagnostics_host.c
- tests/homeassistant/custom_components/tivoo/test_diagnostics.py
- tests/homeassistant/custom_components/tivoo/test_transport.py
- tests/esp32/test_p5b2_diagnostics.py

The P6 implementation and batch execution plans now mark P6b0 complete. No later batch was changed or started.

## 3. Verification

| Check | Result |
|---|---|
| HA Tivoo integration tests: ./scripts/test-ha.sh tests/homeassistant/custom_components/tivoo -q | **180 passed**, 16 warnings |
| ESP32 POSIX diagnostics simulator: ./scripts/test-ha.sh tests/esp32/test_p5b2_diagnostics.py -q | **19 passed**, 5 warnings |
| Ruff check | Passed |
| Ruff format check | Passed |
| Python compileall | Passed |
| git diff --check | Passed |
| ESP-IDF v6.1, IDF_TARGET=esp32, idf.py build | Passed |

The simulator covers the message directions, fragmented/coalesced frames, 16 KiB JSON and 4 KiB MIC_PCM boundaries, invalid headers and Sequence, unknown-type continuation, bounded realtime queue use, shared transmit Sequence, P5 log queue regression, and HELLO rejection/reconnect behavior.

Firmware output: esp32/firmware/build/tivoo_firmware.bin  
Image size: 0x134940 bytes. The 8 MiB application partition has 85% free after build.

Warnings are existing Home Assistant/aiohttp/backoff deprecations and the existing IDF component/Kconfig notices; none failed the checks.

## 4. Scope boundary

- No P6b1 SPP reverse data path was implemented.
- No heartbeat/status business behavior, MIC session manager, TTS Proxy, HTTP Client, or audio playback lifecycle was implemented.
- No firmware was flashed; no NAS deployment or real-device acceptance was performed. P6b0's simulator and build exit gates passed.
- No merge or push was performed. Source changes remain uncommitted on the P6 branch.
