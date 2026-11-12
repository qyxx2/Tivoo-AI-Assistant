# P5b4 Final Integration and Acceptance Implementation Plan

> **For agentic workers:** Execute this plan in order with test-driven development. The P5 contract matrix remains authoritative; this plan must not redefine P5b0–P5b4.

**Goal:** Complete P5 final firmware integration, prove the real 7777/7778 code paths together under host fault injection, produce a reproducible 16MB merged image package for Windows flashing, and record the physical Tivoo acceptance procedure and any unverified hardware gates.

**Architecture:** Keep ESP-IDF v6.1 and the existing production Wi-Fi/listener/diagnostics/control/SPP architecture. Add only the missing structured observation of GAP authentication completion; use a POSIX host executable to exercise the production 7777 and 7778 code together, then use the generated IDF flash arguments to create a single raw merged image.

**Tech Stack:** ESP-IDF v6.1, classic ESP32 target, C, POSIX host simulator, existing Python/pytest harness.

**Spec:** `docs/superpowers/specs/2026-11-11-p5-esp32-minimal-firmware-contract-matrix.md`, especially §§5–6, 7.3, 10–12 and P5-C07–C25.

## Global Constraints

- Work only on `feature/p5-esp32-minimal-firmware` in the selected checkout; do not create another branch/worktree or alter the P5 matrix.
- IDF remains v6.1 with `IDF_TARGET=esp32`; the local sdkconfig contains Wi-Fi credentials and must never be printed, committed, copied into the release package, or included in the manifest.
- Preserve the HA Config Entry `tivoo_bluetooth_mac` as the sole peer-address source; no firmware MAC, inquiry, BLE scan, name-based selection, or security downgrade.
- Keep 7777 one-way raw Tivoo control and 7778 TVIO diagnostics independent; do not add P6/P7/P8 features.
- Windows is only a final-image flashing host. All source, builds, host tests, and diagnostics analysis remain on the ARM64 Ubuntu development device.
- Do not report physical pairing, actual Tivoo command delivery, software-restart bond reuse, or full-power-cycle bond reuse as passed unless physically observed.
- Generated binary artifacts stay under the ignored firmware build directory; tracked documentation records hashes and exact flashing parameters without secrets.

## Review Focus

- GAP AUTH_CMPL for a wrong peer or nonzero status must be observable but never authorize the peer; test both cases.
- Authentication diagnostics must expose only peer address, numeric status, numeric link-key type, target-match and authenticated outcome; never PIN, passkey or key material.
- Closing/reconnecting either TCP channel or losing Wi-Fi must not make the other channel's state handling corrupt or silently imply an SPP disconnect.
- A failed SPP queue submission must reach HA over 7778 while the 7777 connection is closed cleanly.
- The merged raw image must be exactly 16MB, begin at flash offset 0, include the bootloader/partition table/application according to generated `flash_args`, and have a verified SHA256.

---

### Task 1: Observable GAP authentication result

**Files:**
- Modify: `esp32/firmware/main/bt_security_policy.h`
- Modify: `esp32/firmware/main/bt_security_policy.c`
- Modify: `esp32/firmware/main/tivoo_spp.c`
- Test: `esp32/tests/p5b3_security_simulator/security_host.c`
- Test: `tests/esp32/test_p5b3_security.py`

**Interfaces:**
- Add a required `auth_complete` observer in `tivoo_gap_callbacks_t`; it receives context, peer[6], status, link-key type, target-match and authenticated.
- Invoke it exactly once for every AUTH_COMPLETE policy event after storing the result.
- Production observer writes one structured 7778 diagnostic line. Link-key type and status remain numeric; no key/PIN/passkey data is logged.

- [x] Add host assertions for a successful target authentication and for a wrong-peer/nonzero-status event, including exact address, status, link-key type and authenticated result.
- [x] Run `tests/esp32/test_p5b3_security.py` and observe the expected compile/test failure because the observer contract is not implemented.
- [x] Add the observer API and invoke it from the production GAP policy.
- [x] Add the production diagnostics observer and retain existing fail-closed connection gating.
- [x] Re-run the focused test, then P5b3 security/session/control regressions.

### Task 2: Combined 7777/7778 integration and fault-injection test

**Files:**
- Create: `esp32/tests/p5b4_integration_simulator/firmware_host.c`
- Create: `esp32/tests/p5b4_integration_simulator/tivoo_spp_host_stub.c`
- Create: `esp32/tests/p5b4_integration_simulator/tivoo_spp_host_stub.h`
- Test: `tests/esp32/test_p5b4_integration.py`

**Interfaces:**
- Compile the actual `network_listeners.c`, `control_bridge.c`, `tivoo_frame_stream.c`, `diagnostics.c`, and cJSON with POSIX host shims only for ESP-IDF services and the external SPP worker.
- Host controls expose only deterministic fault toggles for the next SPP frame enqueue and simulated IP up/down; they do not replace production TCP parsers or diagnostics framing.

- [x] Add integration tests for concurrent 7777 control and 7778 TVIO handshake/log delivery, MAC and frame forwarding, and diagnostic reconnect independence.
- [x] Inject one SPP queue failure; verify the control TCP session closes, a `spp_tx_queue_full` ERROR reaches the still-connected 7778 client, and the other channel remains usable.
- [x] Inject IP loss/recovery; verify both TCP sessions close and fresh sessions re-establish with a new HELLO/ACK, then send a control frame again.
- [x] Run the new test and observe failure before implementing the simulator harness.
- [x] Implement the minimal host harness and run the new test to green.
- [x] Run existing P5b1 listener, P5b2 diagnostics, and P5b3 control/security/session regressions.

### Task 3: Final build, merged image, and P5b4 acceptance record

**Files:**
- Modify: `esp32/firmware/README.md`
- Create: `docs/superpowers/reports/2026-11-11-p5b4-final-integration-acceptance-report.md`
- Create: `docs/superpowers/plans/2026-11-11-p5b4-final-integration-acceptance-implementation-plan.md` (this plan)

- [x] Run the full P5 host/HA test group, Ruff checks for changed Python tests, and `git diff --check`.
- [x] Build the production ESP32 firmware from a clean-enough IDF v6.1 environment and record `idf.py size`; do not inspect or expose local credential-bearing sdkconfig.
- [x] Use `idf.py merge-bin` with the build-generated `flash_args` to create a single raw image padded to 16MB at offset 0. Copy the exact `flash_args` into the ignored package folder and generate a manifest containing only commit, IDF version, target, flash geometry, file size and SHA256.
- [x] Verify the image size is exactly 16,777,216 bytes and verify the recorded SHA256 independently.
- [x] Review the P5-C07–C25 and P5-C21 scope boundary line by line. Confirm no HA integration source change is required; the existing HA logger receives the new auth diagnostic.
- [x] Record exact Windows flashing instructions and physical test steps for first pairing, command transfer, 7778/7777 separation, software reset, full power cycle, bond list persistence, MAC replacement, and Wi-Fi fault/recovery. Separate local automated PASS from hardware NOT RUN.
- [x] Run final verification after the implementation commit so the embedded firmware version identifies the delivered source commit. Preserve the feature branch; do not merge or push.

**Completion gate:** All locally executable checks and release-package integrity checks pass. Physical-only C07/C10/C22–C25 checks are documented with explicit operator steps and pass conditions; they remain pending until the actual board and Tivoo are tested.
