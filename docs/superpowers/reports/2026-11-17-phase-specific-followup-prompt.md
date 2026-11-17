# Phase-specific follow-up prompt implementation record

- Date: 2026-11-17
- Branch: `fix/ready-prompt-stale-tts-owner`
- Scope: phase-specific prompt asset selection only. No change to HA question-mark continuation semantics, 8-second follow-up timing, ESP32/AEC/VAD, transport protocol, or real-TTS ownership.

## Root behavior reproduced

Before implementation:
- `followup_01.mp3` was rejected by the fixed prompt URL whitelist.
- `PromptSoundPlayer.async_request()` accepted no phase and every wait used the ready pool.
- A real `continue_conversation=true` follow-up integration test emitted a `ready_02.mp3` URL instead of a follow-up-specific URL.

The new focused tests were run first and failed on those exact behaviors.

## Implementation

- `ready/wake/confirmed` -> `ready_01.mp3..ready_03.mp3`.
- `followup` -> only `followup_01.mp3`.
- Ready prompts preserve adjacent-repeat suppression.
- The single follow-up asset is intentionally repeatable across generations.
- Unknown phases raise instead of falling back to ready.
- Existing single `PromptSoundPlayer`, playback IDs, `suppress_vad=true`, AUDIO_STOP routing and real-TTS arbitration are unchanged.

## Asset provenance

`followup_01.mp3` contains “嗯？” and was synthesized without playback through the running production Sherpa Wyoming endpoint. The endpoint returned 22,050 Hz mono S16LE PCM using the deployed Matcha Baker + Vocos path (sid/voice 0, speed 1.0). Raw duration was 0.404626 s.

Only the existing asset adaptation was applied: 120 ms leading silence, 180 ms trailing silence, then conversion to 32 kHz mono MP3.

Final asset:
- duration: 0.704656 s
- leading detectable silence: 0.186938 s
- trailing detectable silence: 0.233 s
- SHA256: `6c8b87fe382b02bf93d790dbc0cd843b123c838db31fcef0ca27cddc33f4070f`

## Verification

- Prompt player + satellite focused suite: 45 passed.
- Prompt asset suite: 12 passed, including real HA `/local` serving.
- All Tivoo tests: 380 passed.
- Full Home Assistant tests: 490 passed.
- Sherpa Wyoming tests: 132 passed.
- Ruff check: pass.
- Ruff format check: pass after formatting one test line.
- `git diff --check`: pass.

No audible device acceptance was triggered during implementation; production deployment verification is file/hash/HTTP/log based.
