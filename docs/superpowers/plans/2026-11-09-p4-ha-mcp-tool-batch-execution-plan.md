# P4 Home Assistant MCP / Tivoo LLM Tools — Batch Execution Plan

> Status: planning only; no P4 implementation has started.
> Branch: `feature/p4-ha-mcp-server`
> Base: `main` / `c40c40046b257a37c632a9738bf04ec2abc0ef76`
> Contract matrix: `docs/superpowers/specs/2026-11-09-p4-ha-mcp-tool-contract-matrix.md`
> Versions: Home Assistant Core 2026.11.0; AstrBot 4.29.4
> Date: 2026-11-09

## 1. First-release scope

P4 MVP has exactly three required business capabilities:

1. Start countdown with `MM:SS`.
2. Stop countdown with no parameters.
3. Set speaker volume from 0 to 100.

The purpose of this release is to validate the complete application-side path:

`AstrBot Persona → AstrBot MCP Client → HA /api/mcp/assist → HA LLM Tool → HA Service → Tivoo semantic command adapter`

No other Tivoo business function is part of the first release. All other capabilities found in the upstream repositories remain catalogued in the contract matrix as optional future extensions. They do not add work to these batches and do not block MVP acceptance.

P4 does not implement TCP 7777/7778, ESP32/SPP, Tivoo raw frame transport or real-device acknowledgements. The local test adapter proves application call flow. Real hardware execution is verified in P5/P6 after the production transport is integrated.

## 2. Files and architectural boundary

- HA integration root: `homeassistant/custom_components/tivoo/`.
- MVP services: `tivoo.start_countdown`, `tivoo.stop_countdown`, `tivoo.set_volume`.
- MVP tools: `tivoo__StartCountdown`, `tivoo__StopCountdown`, `tivoo__SetVolume`.
- All three tools call the corresponding HA service. No Tool contains its own device logic or payload encoding.
- Service handlers call one small, typed Tivoo semantic command adapter. The adapter supports only the three MVP actions; it is not a general RPC/message bus.
- Tests use an in-memory adapter to capture the requested action and parameters. The production adapter reports unavailable until P6 installs the actual transport. Never return success for an unavailable production adapter.
- Do not add media_directory configuration, entities, media services, optional display services, or other optional tool schemas in the MVP.

## 3. Batch overview and dependencies

| Batch | Scope | Depends on | Deliverable |
|---|---|---|---|
| P4b0 | Source/version and local test preflight | None | Current HA/AstrBot contracts, test command and Tivoo command reuse boundary confirmed |
| P4b1 | HA integration skeleton and three MVP services | P4b0 | Configurable/loadable integration, service schemas, semantic adapter seam and service tests |
| P4b2 | Three HA LLM Tools | P4b1 | Assist API exposes only the three project Tivoo tools; every tool calls its HA service |
| P4b3 | AstrBot MCP connection and full application-path test | P4b2 | Target Persona discovers and calls all three tools through HA MCP |
| P4b4 | MVP acceptance, P3 regression and closeout | P4b3 | Evidence-backed MVP pass/partial/blocked report and local commit |

Dependency order:

`P4b0 → P4b1 → P4b2 → P4b3 → P4b4`

Do not parallelize optional Tivoo feature work while these batches are in progress.

## 4. P4b0 — Source and local test preflight

**Purpose:** Confirm the implementation interfaces and test environment before adding code. This batch is inspection and record-keeping only.

**Tasks:**

- [ ] Confirm the actual HA Core 2026.11.0 LLM Tool callback, Tool/ToolResult types, Assist API filtering and Config Entry loading contract.
- [ ] Confirm AstrBot 4.29.4 Streamable HTTP configuration, Authorization header support, tool discovery/call and reconnect behavior.
- [ ] Confirm `/api/mcp/assist` is the intended route and ordinary HA-user credentials are sufficient; do not use the management API.
- [ ] Confirm the local test runner, existing P3 regression tests, Ruff and compile checks.
- [ ] Verify the upstream countdown start/stop semantics: start takes MM:SS; stop has no parameters and must not depend on the previous duration.
- [ ] Verify volume range 0–100 and the upstream conversion to device scale 0–15; confirm 0 remains a valid value throughout the service/adapter path.
- [ ] Check the license/provenance of the local Tivoo Python SDK before reusing any payload builder. Never import from an absolute path in another workspace and never copy BluetoothBridge Transport into HA.
- [ ] Record any discrepancy that prevents a contract-faithful service implementation. Do not guess or silently change a field.

**Exit gate:**

- [ ] HA/AstrBot source interfaces and local tests have current evidence.
- [ ] StartCountdown, StopCountdown and SetVolume service input contracts are frozen.
- [ ] Local test commands are documented and can run.
- [ ] Reuse of the existing pure payload builders is either cleared or explicitly not used in MVP; this decision does not block defining the semantic adapter contract.
- [ ] No implementation code is added. Do not create an empty commit if this batch yields no file changes.

**Commit:** only if preflight documentation is materially changed; otherwise proceed without an empty commit.

## 5. P4b1 — HA integration skeleton and three MVP services

**Purpose:** Build the smallest loadable Tivoo integration and implement the three normal HA services. No MCP Tool is added in this batch.

**Expected files:**

- Create the minimum integration files under `homeassistant/custom_components/tivoo/`: manifest, setup/unload, constants and Config Flow if required by the chosen HA installation path.
- Create `services.py` and `services.yaml` for exactly the three MVP services.
- Create the smallest semantic command adapter seam and its in-memory/unavailable implementations.
- Add focused tests under the project's existing HA test layout.

**Tasks:**

- [ ] Write RED tests for integration loading/unloading and service registration/unregistration.
- [ ] Add `tivoo.start_countdown` with required `countdown: string`. Validate strict MM:SS, minute 00–99 and second 00–59; map to semantic action `start_countdown`.
- [ ] Add `tivoo.stop_countdown` with an empty service schema. Reject unexpected input; map to semantic action `stop_countdown`. Do not query or cache the previous duration.
- [ ] Add `tivoo.set_volume` with required integer `volume` in range 0–100 inclusive. Preserve 0 exactly; map to semantic action `set_volume`.
- [ ] Keep service Schema and services.yaml field declarations aligned.
- [ ] Use one minimal semantic adapter method for these three named actions. Do not accept arbitrary operation names, raw bytes or caller-supplied protocol frames.
- [ ] The in-memory test adapter captures action and parameters. The production adapter raises a clear unavailable error until P6 transport integration.
- [ ] If existing builders are reused, call only the verified builder after P4b0's license check. Do not implement an alternative wire encoder in the service layer.
- [ ] Service success means the adapter completed its current responsibility. Do not claim the physical Tivoo acted without a device acknowledgement.

**Exit gate:**

- [ ] The HA integration loads and unloads cleanly.
- [ ] Exactly three MVP services register; no optional Tivoo service is registered.
- [ ] StartCountdown rejects malformed strings and boundary overflows.
- [ ] StopCountdown requires no fields and sends no previous duration.
- [ ] SetVolume accepts 0 and 100, rejects values outside the range and preserves 0.
- [ ] Tests prove all three service calls reach the in-memory adapter with the expected semantic action and payload.
- [ ] Production adapter unavailability is an explicit service error, never a fake success.
- [ ] Focused tests, relevant P3 regression, Ruff and `git diff --check` pass.

**Commit:** `feat(p4): add Tivoo countdown and volume services`

## 6. P4b2 — Three HA LLM Tools

**Purpose:** Expose only the three MVP HA services through Home Assistant's LLM Tools platform. This batch does not add device or business logic.

**Expected files:**

- Create/modify `homeassistant/custom_components/tivoo/llm.py`.
- Add tests for API filtering, discovery, schemas, service delegation and failures.

**Tasks:**

- [ ] Write RED tests confirming HA discovers the integration's synchronous `async_get_tools(hass, llm_context, api_id)` callback according to HA Core 2026.11.0.
- [ ] Return tools only for `api_id == "assist"`; return None for other API IDs. Do not put llm.py into entity `PLATFORMS`.
- [ ] Register `tivoo__StartCountdown` with required `countdown` string and the same MM:SS constraints.
- [ ] Register `tivoo__StopCountdown` with an empty input schema.
- [ ] Register `tivoo__SetVolume` with required integer `volume` in range 0–100.
- [ ] Each Tool invokes only its corresponding HA service with `blocking=True` and the LLM context; no direct adapter or protocol call from the Tool.
- [ ] Set `integration="tivoo"` and explicit ToolAnnotations on all three tools: read_only=False, destructive=False and open_world=False. Set idempotency per contract: StartCountdown false, StopCountdown true, SetVolume true.
- [ ] Return JSON-object ToolResult data. Service/validation/adapter failures must propagate as MCP tool errors.
- [ ] Verify the tool list contains exactly these three project Tivoo tools, while allowing unrelated tools from other HA integrations to remain present.

**Exit gate:**

- [ ] Assist API discovers exactly three project Tivoo Tools; other API IDs do not.
- [ ] Each Tool delegates to its matching service with the correct arguments.
- [ ] Invalid inputs and service/adapter errors do not become successful ToolResult values.
- [ ] No additional Tivoo Tool or service is registered.
- [ ] P3 tests remain unchanged and pass.

**Commit:** `feat(p4): expose countdown and volume as HA LLM tools`

## 7. P4b3 — AstrBot MCP connection and full application-path test

**Purpose:** Prove the full application-side flow with AstrBot 4.29.4. Device transport and actual Tivoo execution remain P5/P6 work.

**Configuration contract:**

- Transport: `streamable_http`.
- URL: `http(s)://<HA LAN address>:8123/api/mcp/assist`.
- Header: `Authorization: Bearer <HA Long-Lived Access Token>`.
- Use an ordinary dedicated HA user. Never put the real token in Git, tests, logs or screenshots.

**Tasks:**

- [ ] Add the HA MCP server through the existing AstrBot 4.29.4 MCP Client configuration; do not write a custom MCP client.
- [ ] Confirm initialize succeeds and the server is connected.
- [ ] Confirm the target Persona is authorized to use the three project Tivoo tools.
- [ ] Confirm the Persona tool list includes StartCountdown, StopCountdown and SetVolume, and no optional Tivoo tools.
- [ ] Through AstrBot, call SetVolume with representative values (0 and 100); verify the HA service and in-memory adapter receive the exact values.
- [ ] Through AstrBot, call StartCountdown with a valid MM:SS value; verify the exact string reaches the HA service/adapter.
- [ ] Through AstrBot, call StopCountdown with an empty argument object; verify it reaches the HA service/adapter with no duration.
- [ ] Verify invalid inputs are rejected before the adapter and an unavailable/failed HA service is returned as a tool error.
- [ ] Verify an invalid Token is rejected and a normal HA user's valid Token can use Assist MCP.
- [ ] Observe AstrBot's actual reconnect/retry behavior. Do not introduce an extra retry layer; document the duplicate-start risk for StartCountdown if the response is lost after execution.
- [ ] If a live HA/AstrBot instance or credentials are unavailable, mark only the runtime check BLOCKED. Do not search local/NAS files for credentials and do not claim runtime success from static configuration.

**Exit gate:**

- [ ] AstrBot 4.29.4 completes MCP initialize and tool discovery over Streamable HTTP.
- [ ] The target Persona can call all three tools and the calls reach the HA service and test adapter.
- [ ] Parameter validation and service failure propagation are demonstrated end to end.
- [ ] No optional Tivoo tools are visible from this project.
- [ ] Token is not present in repository or test output.

**Commit:** `test(p4): verify AstrBot countdown and volume MCP flow`

## 8. P4b4 — MVP acceptance, P3 regression and closeout

**Purpose:** Close the first release with evidence for the three required actions and the full application-side flow.

**Tasks:**

- [ ] Trace P4-C01–C13 against actual automated tests, MCP runtime output or controlled observations.
- [ ] Run `./scripts/test-ha.sh -q` and the existing P3 regression suite; confirm P3 HTTP Chat, SSE, session and ChatLog are unchanged.
- [ ] Run Ruff check/format, compileall, pip check where applicable and `git diff --check`.
- [ ] Confirm the Tivoo integration creates only three MVP Services and only three MVP LLM Tools.
- [ ] Confirm optional extensions are listed as backlog only and have not accidentally entered code, config schema, tool discovery or acceptance gates.
- [ ] Review the production adapter: before P6 it must fail clearly as unavailable, not simulate successful hardware execution.
- [ ] Record the difference between application-path PASS and real-device execution DEFERRED to P5/P6.
- [ ] Review changed files, commit locally, do not push or merge.

**Exit gate:**

- [ ] P4-C01–C09 and C11–C13 have MVP evidence; C10 is explicitly deferred as optional media scope; C14 is deferred to P5/P6.
- [ ] AstrBot → HA MCP → LLM Tool → HA Service → in-memory semantic adapter works for StartCountdown, StopCountdown and SetVolume.
- [ ] P3 regression, type/lint checks and diff checks pass.
- [ ] The report does not claim physical Tivoo actions before P5/P6.
- [ ] All changes are locally committed on `feature/p4-ha-mcp-server`; main and remote remain unchanged.

**Commit:** `test(p4): close first-release Tivoo MCP contracts`

## 9. Optional extension backlog — not part of first release

The following capabilities remain in the contract matrix with upstream sources, model constraints and parameter notes. They must be scheduled separately only after MVP passes:

- Display: presets/emotions, scrolling text, brightness, screen on/off, clock, date/time, weather, 16×16 panel light effects, lyrics, scoreboard, design.
- Media: static images, GIF animation, media_directory and file handoff.
- Device tools: built-in timer, noise meter, alarms, memorial reminders, audio source/radio, sleep mode.
- Other playback control: previous/pause/play/next, subject to the future media_player ownership decision.
- Restricted modes: effects, visualization, games and game control remain Service-only until Tivoo-specific valid indexes/state are established.

The following remain excluded because the Tivoo-specific upstream driver marks them unsupported or they bypass the intended architecture: equalizer, keyboard LED control, standalone temperature mode, signal mode, other-model clock_id, MiniToo/Tiivoo2 volume1..8, raw frame commands, and LLM-managed connect/disconnect.

## 10. Contract-to-batch traceability

| Contract | MVP batch | Acceptance |
|---|---|---|
| P4-C01 MCP route | P4b0/P4b3 | HA /api/mcp/assist is reachable |
| P4-C02 Streamable HTTP | P4b0/P4b3 | AstrBot initialize and Bearer header |
| P4-C03 Tool discovery | P4b2/P4b3 | Exactly three project Tivoo Tools appear |
| P4-C04 Auth boundary | P4b0/P4b3 | Normal HA user works; invalid Token fails |
| P4-C05 Assist scope | P4b2/P4b3 | Tools are only Assist-facing and do not become arbitrary entity/service access |
| P4-C06 API filter | P4b2 | Only api_id=assist gets the three Tools |
| P4-C07 Service reuse | P4b1/P4b2 | Tool delegates to the matching service |
| P4-C08 Error propagation | P4b1–P4b4 | Validation and unavailable adapter errors propagate |
| P4-C09 MVP parameter bounds | P4b1–P4b3 | MM:SS, no-arg Stop, volume 0–100 |
| P4-C10 Media paths | Deferred | Optional media extension |
| P4-C11 P3 regression | P4b4 | HTTP Chat/SSE/session/ChatLog unchanged |
| P4-C12 Retry behavior | P4b3 | AstrBot actual reconnect behavior and countdown duplicate risk recorded |
| P4-C13 Transport boundary | P4b1–P4b4 | No direct ESP32/TCP/SPP connections |
| P4-C14 Real Tivoo action | P5/P6 | Physical volume/countdown behavior |

## 11. Global execution rules

- One batch per task and one local commit per completed batch. Execute only the current batch.
- Write an observable RED test before implementing each new behavior, then make the smallest change that turns it GREEN.
- Reuse HA Core's Config Entry, Service Registry, LLM Tools, Assist API, MCP Server and existing P3 test scaffolding.
- Service and Tool schemas must share the same business contract even if implemented with different HA and probatio schema types.
- Await HA service completion and propagate service/adapter errors. Enqueueing work is not proof that it completed.
- The test adapter is only for development tests. Production must fail unavailable until P6 transport exists.
- Do not run heavy tests on the NAS. Use the Ubuntu development machine; perform only necessary runtime connection checks.
- Record changed files, test commands/results, static checks, commit SHA and blocked items after each batch.
- No production deployment, no NAS configuration edits, no real non-idempotent Tivoo action, no push and no merge unless separately authorized.
