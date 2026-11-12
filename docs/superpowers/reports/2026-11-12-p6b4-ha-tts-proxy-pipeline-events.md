# P6b4 — HA TTS Proxy URL 与 Pipeline 事件触发执行报告

- Date: 2026-11-12
- Branch: `feature/p6-esp32-ha-bidirectional-communication`
- Base: `c456f1548581` (P6b3)
- Contract: P6-C12 and P6-C01 TTS_PLAY outbound integration
- Scope: P6b4 only. P6b5/P6b6 and P6.5 are untouched.

## Delivered

- Added `audio_resource.py`:
  - `build_internal_tts_url()` calls HA Core 2026.11.0 `get_url()` with `allow_internal=True`, `allow_external=False`, `allow_cloud=False`, `allow_ip=True`.
  - HA configured `internal_url` takes priority; if absent, HA Core's detected LAN IP fallback is used. With no internal address, a HomeAssistantError is raised and no message is sent.
  - Only relative `/api/tts_proxy/{token}` resource paths are accepted. The complete relative path/query is appended unchanged; the token remains in the URL path and is not split into another field.
  - `TtsResourceManager` stores one Pipeline run's playback_id, URL, MIME type and streaming flag. Streamed TTS sends on `intent-progress` with `tts_start_streaming=True`; non-streamed/short TTS sends on `tts-end`. A run sends once, and run-start/run-end reset run-local state.
  - A synchronous `PipelineEventCallback` factory schedules the async handler. The factory is exposed as `hass.data[DOMAIN][entry_id]["pipeline_event_callback_factory"]`.
- Added `Esp32ConnectionAdapter.async_send_tts_play()`, delegating to the existing 7778 sender. The existing accepted-HELLO gate and single outbound Sequence remain authoritative; no offline queue was introduced.
- The TTS payload is exactly `{playback_id, url, mime_type}`; no Bearer header or second token field is added.
- Callback failures use a fixed warning that contains no URL or token.
- HA Core's `PipelineEventCallback` is supplied by the caller for each Pipeline run; P6b4 exposes a callback factory but does not monkeypatch HA Core or claim global interception. The future Pipeline caller supplies the returned callback through HA's `event_callback` argument.

## RED / GREEN

- Transport wire test first failed with missing `async_send_tts_play`; after the typed wrapper was added it passed and verified message type, exact payload and continued outbound sequence (TTS_PLAY sequence 3 after HELLO_ACK/status/MIC stop messages).
- New URL/event tests first failed because `audio_resource.py` did not exist. Implemented the helper/manager/callback and passed internal URL preference, LAN fallback, no-address failure, rejection of absolute/non-proxy URLs, stream-before-end timing, short-response timing, once-only dispatch, run isolation and callback scheduling.
- A concurrency test reproduced duplicate TTS_PLAY when intent-progress sending was suspended and tts-end arrived concurrently (2 sends, RED). The manager now marks a playback as attempted before awaiting the network send; the same test passes with one send.
- Missing internal URL does not send TTS_PLAY. Callback warning test confirms the opaque test token is not logged.
- TTS_PLAY before diagnostic handshake raises the existing HomeAssistantError; no deferred queue is created.

## Verification

- Focused:
  - `./scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_audio_resource.py tests/homeassistant/custom_components/tivoo/test_transport.py tests/homeassistant/custom_components/tivoo/test_audio_session.py -q` — 54 passed before final security assertions.
  - Final focused URL/resource + transport wire selection: 16 passed, 5 environment warnings.
- Final full Tivoo suite: `./scripts/test-ha.sh tests/homeassistant/custom_components/tivoo -q` — 225 passed, 16 warnings (existing Home Assistant/Python dependency deprecations and aiohttp test-fixture warnings).
- Ruff check and format check: passed.
- Python compileall: passed.
- `git diff --check`: passed.

## Device and scope status

- No firmware source changed; ESP-IDF build is not applicable to this HA-only batch.
- No NAS deployment, firmware flash or real Tivoo test was performed. The batch verifies URL selection and TVIO send behavior through HA tests; the real HTTP resource GET belongs to P6b5.
- No Pipeline cancellation, Satellite entity, decoder, audio output, playback completion or P7/P8 behavior was added.
- No push or merge performed.
- Commit: `feat(p6b4): add HA TTS proxy event dispatch` (local P6 branch HEAD).
