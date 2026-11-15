# P6.6b2 — P6.5 voice lifecycle → Tivoo display intents

Date: 2026-11-16
Branch: `feature/p6-6-tivoo-expression-state-machine`
Scope: P6.6b2 only; no AstrBot phase bridge (b3), mood Tool (b4), NAS deployment, or ESP32 flash (b5).

## Implementation

- `assist_satellite.async_setup_entry()` passes the existing `runtime["display_coordinator"]` to the Satellite and its `AudioSessionCoordinator`; no second screen or audio owner is created.
- Each `_Turn` owns a fresh Home Assistant `Context`; `context.id` becomes the display generation and the same Context is passed to the real HA 2026.11.0 `async_accept_pipeline_from_satellite(..., context=turn.context)` call.
- Candidate speech uses the display coordinator's non-polling 700 ms hold, 35% random chance, and 10-second cooldown. `speech_end`, generation replacement, and shutdown cancel pending callbacks. First confirmed `WAKE_WORD_END` and successful side-KWS both bypass candidate randomness and submit `wake_confirmed/question`.
- Valid current `STT_END` must include nonempty `stt_output.text`, `command_started=True`, and no turn error to enter `thinking`; `STT_START` / empty STT never enter thinking.
- `speaking/music` is keyed exclusively to the current playback ID's physical `AUDIO_STATE=playing`. `TTS_START/TTS_END` do not enter speaking. `completed` switches to `followup_wait/standby` via existing `_open_followup()` and retains the original 8-second P6.5 timer; terminal failures continue the old stop path.
- A follow-up `speech_start` creates a fresh generation and immediately displays active listening. `on_end`/Pipeline ERROR clears the owning generation; stale playback, late events, and old timers cannot replace the new generation. Persistent explicit display and ScreenPowerGate are unchanged.
- Kept the P6.5 MIC/VAD/KWS/Stop/SSE and 3/15/5/8-second audio watchdogs; only visual intent hooks were added. No new SPP or network messages.

## Superpowers TDD and verification

- RED: New candidate display test failed because `ExpressionCoordinator.begin_candidate` was absent; Satellite integration test failed because `TivooAssistSatellite` did not accept a display coordinator. The new tests covered candidate noise/miss/hit/cooldown, shared runtime instance, `Context.id`, wake, STT, TTS vs actual playing, completed/follow-up, old playback, and session end.
- GREEN: `test_assist_satellite.py` + `test_display_state.py` passed. Existing side-KWS interruption parametrized tests additionally assert the new generation's confirmed display.
- Cancellation regression initially had three failures because an older P6.5 test fixture instantiated the Satellite with the previous three-argument constructor. Updated only that fixture to pass the new display dependency; retest of cancellation + the satellite/display tests: **47 passed**.
- The expanded final suite `./scripts/test-ha.sh -q tests/homeassistant/test_assist_pipeline_tts_cancellation.py tests/homeassistant/custom_components/tivoo --tb=short`: **323 passed, 155 warnings, 0 failed** (HA and third-party deprecations, aiohttp AppKey and blocked-test-socket warning).
- Final quality gates: Ruff lint and format check; Python compileall on affected integration modules; `git diff --check`.

## Acceptance / deferred

- Automated ESM-C03/C04/C05/C07/C08/C10/C21/C23 voice-side contracts are covered. No AstrBot `tool_call/tool_call_result` mapping was added here; that belongs to b3.
- No hardware display acceptance was performed: NAS and ESP32/Tivoo live visual verification remain explicitly deferred to P6.6b5. `last_sent` continues to describe transport submission, not physical pixels.
