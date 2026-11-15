# P6.6b0 — Tivoo display state core implementation

Date: 2026-11-16
Branch: `feature/p6-6-tivoo-expression-state-machine`
Scope: Only P6.6b0. No HA runtime wiring, NAS deployment, ESP32 build or flashing.

## Delivered

- `homeassistant/custom_components/tivoo/display_state.py`:
  - `DisplayState` priority: wake_confirmed > speaking > tooluse > thinking > active_listening > explicit_content > ai_mood > followup_wait > idle.
  - `build_expression_command(name)` builds the existing `set_expression` payload using `PRESET_REGISTRY` (lazy import to avoid next-batch circular imports).
  - `ExpressionCoordinator` tracks authoritative `active_generation`, intents, TTL, desired state, last successfully sent command, priority restoration and idle 30–90 s rotation.
  - Session-scoped intents cannot update without an active generation; an explicit stale generation is ignored. A new generation clears the old session intents but preserves persistent explicit content.
  - `ScreenPowerGate` tracks independent screen-off owners and expiring temporary wake leases. OFF blocks all display writes while still allowing desired state changes. OFF→ON resends the winning command after screen power ON.
  - Adapter exceptions do not advance `last_sent`; force-recompute retries desired display and reasserts OFF while inhibited.
  - The state cache is HA intent / transport submission state, **not physical pixel acknowledgment**.
- `tests/homeassistant/custom_components/tivoo/test_display_state.py`: 13 isolated contract tests covering precedence/restore, stale turn/TTL, suppressed TTL, idle timing, multiple inhibit owners, overlapping wake leases, OFF→ON redraw, send failure and force-recompute.

## Evidence

| Stage | Command | Observed result |
|---|---|---|
| RED | `./scripts/test-ha.sh -q tests/homeassistant/custom_components/tivoo/test_display_state.py` | Collection error: expected `ModuleNotFoundError: custom_components.tivoo.display_state` before new module existed |
| GREEN | same command after implementation | **13 passed**, 5 pre-existing dependency warnings |
| Tivoo regression | `./scripts/test-ha.sh -q tests/homeassistant/custom_components/tivoo` | **285 passed**, 126 warnings, 64.19 s |
| Static check | `.venv/bin/ruff check` on both new files | All checks passed |
| Formatting | `.venv/bin/ruff format --check` on both new files | 2 files already formatted |
| Syntax | `.venv/bin/python -m compileall -q homeassistant/custom_components/tivoo/display_state.py` | Exit 0 |

## Deferred by batch contract

P6.6b0 deliberately does not register a HA runtime coordinator, change existing screen-power services/MCP, hook Assist/AstrBot lifecycle events, subscribe to ESP32 SPP connection recovery, or expose a mood tool. These integration and hardware checks belong to b1–b5. The full Tivoo regression validates compatibility of current code; it is **not** production visual acceptance.
