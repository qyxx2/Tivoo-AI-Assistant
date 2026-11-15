# P6.6b1 — HA display ownership, screen gate, and SPP restoration

Date: 2026-11-16
Branch: `feature/p6-6-tivoo-expression-state-machine`
Scope: P6.6b1 only. No P6.6b2 voice display events, b3 tool phase, b4 mood Tool, NAS deployment, or ESP32 flashing.

## Implemented

- Runtime: exactly one `runtime["display_coordinator"]` backed by the existing semantic `command_adapter`; `connection_adapter` remains the actual ESP32 transport. The coordinator starts only after runtime wiring; unload cancels its idle and gate timers before transport stops. Setup without an ESP32 host continues to work, with initial desired idle retained until transport is available.
- Facades: `async_set_screen_power`, `async_set_explicit`, `async_execute_screen_action`, `async_on_spp_state`. Existing bool `tivoo.set_screen_power` / `tivoo__SetScreenPower` maps exclusively to `compatibility` inhibit owner. Additional owner inhibits survive compatibility `True`.
- Reusable explicit visuals (12): set_expression, show_text, show_image, play_animation, show_clock, set_light, show_lyrics, show_scoreboard, show_design, show_effects, show_visualization, show_game. During OFF, only desired intent changes; ON restores the latest winner. Repeating the same visible explicit command resends it to preserve replay/restart semantics.
- Direct screen actions (6): start_countdown, stop_countdown, set_timer, set_noise_meter, set_sleep_mode, game_control. During OFF, these raise `HomeAssistantError`, never queue side effects; during ON, they retain direct execution.
- Other services retain their previous direct semantic path and schema. Existing 27 Tivoo Service/MCP tool names and parameter contracts remain unchanged.
- Transport: one SPP state observer consumes validated `DEVICE_EVENT` transitions; validated initial `DEVICE_STATUS.spp.state` also synchronizes screen state after HA/diagnostic reload, including control TCP 7777 becoming available later. Raw `0x69/0x96` hints never count as connected. Disconnection invalidates `last_sent`, keeps desired, stops idle scheduling. Reconnection resends OFF or the current winner according to gate. Transport failures do not claim physical pixel acknowledgement.

## TDD / verification evidence

- RED: facade tests failed on missing b1 methods; service tests failed on missing runtime `display_coordinator` and routing.
- RED: initial validated SPP snapshot test failed before snapshot reconciliation was added; GREEN: targeted transport check passed.
- RED: repeated identical explicit command failed to restart; GREEN: display state tests **17 passed**.
- Focused service/MCP regression after adapting the intentional ON→repaint expectation: **38 passed**.
- Final full Tivoo suite: `./scripts/test-ha.sh -q tests/homeassistant/custom_components/tivoo --tb=short` → **308 passed, 145 warnings, 0 failures**. The warnings are existing HA/third-party deprecations, aiohttp AppKey warnings, and a blocked-test-socket warning; no test failures.
- `.venv/bin/ruff check` and `.venv/bin/ruff format --check` on changed Python files → clean. `.venv/bin/python -m compileall -q` on modified integration files → exit 0. `git diff --check` → clean.

## Rulings / deferred

- The original b1 plan mentioned validated SPP `DEVICE_EVENT` only. A validated `DEVICE_STATUS` snapshot is also needed: HA can reload after SPP is already connected and no new `spp_connected` event occurs. Spec, contract matrix, and batch plan were amended narrowly; no new external protocol or polling was introduced.
- No live ESP32/Tivoo visual confirmation in b1; this remains the explicit b5 real-device acceptance. `last_sent` means only transport submission success, not physical screen confirmation.
- P6.6b2–b5 remain untouched.
