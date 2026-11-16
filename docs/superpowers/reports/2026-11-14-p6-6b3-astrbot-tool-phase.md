# P6.6b3 — AstrBot tool phase → Tivoo tooluse

Date: 2026-11-16
Branch: `feature/p6-6-tivoo-expression-state-machine`
Baseline: `008149a` (P6.6b2)
Scope: P6.6b3 only; no mood Service/MCP (b4), NAS deployment, ESP32 flash or hardware acceptance (b5).

## Implementation and contract

- Existing AstrBot `plain.chain_type=tool_call/tool_call_result` is now exposed as **internal-only** `AstrBotSseEvent("phase", ...)` while `reasoning`/`agent_stats` remain ignored. The tool payload is not forwarded: only the phase name survives. Visible `plain`/`end`/ChatLog/TTS behavior is unchanged.
- Conversation fires the HA event `astrbot_phase` only for non-`None` `ConversationInput.satellite_id`, with exactly `satellite_id`, `context_id=user_input.context.id`, and `phase`. Web/text turns produce no phase event. This does not call any extra AstrBot API or change the existing cancellation/Stop owner.
- Tivoo Satellite listens on the HA bus only while added to HA and unsubscribes on removal. It accepts an event only for its own `entity_id`, the current `_Turn.context.id`, and the display coordinator's active generation, with a live session and no terminal/error/follow-up state. A stale event cannot affect the winner or any newer generation.
- `tool_call` submits `DisplayState.TOOLUSE` with existing `tooluse` preset; `tool_call_result` clears that intent. Existing priority recompute then reveals `THINKING` when valid or leaves higher `SPEAKING` untouched. No secondary screen state owner, SPP packet, protocol change or text-to-mood inference.
- Tivoo listens by event name without importing AstrBot modules, so its core installation is not accidentally coupled to the optional Conversation integration.

### HA Core 2026.11.0 source verification

- `assist_satellite/entity.py::async_accept_pipeline_from_satellite` accepts `context: Context | None`, calls `async_set_context(context)` and uses the current turn's supplied context.
- `assist_pipeline/default_pipeline.py` creates `ConversationInput(context=self.host.context, satellite_id=self.host.satellite_id)` and passes these unchanged through `conversation.async_converse()`. Thus this bridge uses **HA Context.id**, not AstrBot session/run/message IDs.

## Superpowers TDD / verification

1. **RED:** Added parser, Conversation and Tivoo bus/turn tests before implementation. Initial focused run: **4 failed, 20 passed** (expected missing phase behavior).
2. **GREEN:** Implemented only the internal phase side channel and Tivoo listener. The same focused selection: **24 passed**.
3. Expanded integration regression: `./scripts/test-ha.sh -q tests/homeassistant/custom_components/astrbot/test_sse.py tests/homeassistant/custom_components/astrbot/test_conversation.py tests/homeassistant/custom_components/tivoo/test_assist_satellite.py tests/homeassistant/custom_components/tivoo/test_display_state.py tests/homeassistant/test_assist_pipeline_tts_cancellation.py` — **87 passed, 33 warnings**.
4. Full HA regression before final isolated-import refinement and added TTS hidden-content assertion: `./scripts/test-ha.sh -q tests/homeassistant` — **425 passed, 221 warnings**, no failures.
5. Final focused rerun after the refinement (`streaming TTS`, six cancellation parametrizations, and all Tivoo assist tests) — **30 passed, 12 warnings**. The streaming test now injects hidden tool request/result text around visible chunks and confirms TTS receives only the original visible text. Existing cancellation variants still confirm exactly one Stop when required; error-path tests remain in the full suite.
6. Ruff lint / format check on all seven modified source/test files, compileall on modified production modules, and `git diff --check` passed. Warnings are from pre-existing HA/Python deprecations and aiohttp AppKey diagnostics, not new b3 failures.

## Acceptance and boundaries

- Automated ESM-C06/C10/C23 tool-phase, generation isolation, visibility and cancellation contracts: **PASS**.
- No changes to P6.5 VAD/KWS/STT/TTS timers, generation and playback ID ownership or P3 SSE Stop ownership.
- **DEFERRED to P6.6b5:** actual NAS/AstrBot/ESP32/Tivoo physical display acceptance and observation. Current test outcomes do not claim a physical-pixel acknowledgement.
- **NOT IMPLEMENTED:** P6.6b4 mood Service/MCP and P6.6b5 deployment/acceptance.
