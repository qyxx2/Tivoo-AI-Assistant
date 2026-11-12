# P6b3 — MIC Session Bounded Dispatch Implementation Report

- Date: 2026-11-12
- Branch: feature/p6-esp32-ha-bidirectional-communication
- Base: b6dbbfa (P6b2 hardware acceptance report commit)
- Scope: P6b3 only; P6b4–P6b6 untouched.
- Contract: P6-C11 and P6-C18.

## Delivered

- Added homeassistant/custom_components/tivoo/audio_session.py with one active MIC session, a fixed 16-element PCM queue, a single async iterator, strict session/audio-format validation, queue-overflow stop behavior, and interruption callback registration.
- Wired MIC_SESSION_START, MIC_PCM, MIC_SESSION_END and AUDIO_INTERRUPTED through the existing TVIO message-handler API. MIC_PCM remains opaque binary S16LE; no Base64 or duplicate unbounded buffer is used.
- Added config-entry runtime ownership and unload cleanup. An active session is closed, queued PCM is dropped, and MIC_CAPTURE_STOP is sent before the transport is stopped.
- Added ESP32 diagnostics MIC_CAPTURE_STOP JSON/session UUID/reason validation and a non-blocking callback registration seam. Without a registered P7 producer callback, valid STOP is validated and treated as an idempotent no-op.
- Added HA manager tests, cross-transport fragmented/coalesced-message coverage, stale END isolation, queue-saturation checks, config-entry unload/STOP verification, and ESP32 POSIX simulator coverage for malformed, registered-callback, and no-callback STOP behavior.
- Extended the HA accepted firmware error-code set for protocol_invalid_header and protocol_invalid_payload. Updated the old P5-only firmware error-code regression assertion to the explicit P5+P6 set.

## Verification

- ./scripts/test-ha.sh tests/homeassistant/custom_components/tivoo -q — 210 passed, 16 warnings.
- PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32 -q — 49 passed, 27 warnings.
- Ruff check and Ruff format check — passed.
- Python compileall for Tivoo integration/tests — passed.
- git diff --check — passed.
- ESP-IDF v6.1, target esp32, idf.py build — passed; build/tivoo_firmware.bin size 0x1360a0, app partition 85% free.

## Device / Scope Status

- No NAS deployment or firmware flash was performed. P6 has no physical microphone producer, so there is no real device source to emit valid MIC_SESSION_START/MIC_PCM traffic. That physical path is deferred until P7 implements the producer; it is not reported as a P6b3 hardware PASS.
- The ESP32 STOP dispatch seam was exercised through the existing POSIX diagnostics simulator.
- No Assist Satellite, Pipeline lifecycle, I²S RX, INMP441, AEC/VAD, STT, Pipeline cancellation or AstrBot Stop behavior was added.
- No merge or push was performed.

## Protocol Ordering Note

TVIO v1 defines MIC_PCM as an unwrapped binary payload without a per-frame session_id. HA associates PCM with the most recent valid MIC_SESSION_START on the same ordered TCP stream, until that session's MIC_SESSION_END. Explicit END/STOP messages are matched by session_id. The ESP32 producer must serialize all PCM for a session before its END and must not enqueue old-session PCM after a newer START. This preserves the existing fixed wire format.
