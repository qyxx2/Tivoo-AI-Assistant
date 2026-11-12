# P5 SPP Initial-Connect Recovery and Diagnostics Fix

**Date:** 2026-11-12  
**Branch:** `feature/p5-esp32-minimal-firmware`  
**Base commit:** `95cfb436f822654fa833d324368283b17a8ac6fb`  
**Target:** ESP32-DEV-KIT-WROVER-E-M / classic ESP32 / ESP-IDF v6.1

## 1. Result

The current workspace now fixes a definite SPP session-state defect that prevented retry after the first failed connection. It also adds stage-specific diagnostics for SDP discovery, SPP client initiation/open/close, GAP PIN/SSP requests, authentication completion and the connection wait outcome.

The existing SPP auto-reconnect implementation for an established link, the 1000ms bounded transmit-queue wait, and the TCP task stack-buffer fix were preserved. The Bluetooth security mask remains `ESP_SPP_SEC_AUTHENTICATE | ESP_SPP_SEC_ENCRYPT`; no security downgrade, peer scan, fixed MAC, HA integration change or NVS erase was introduced.

The application builds successfully and the P5/HA regression suite passes. The image has **not yet been flashed to the physical ESP32**, so whether the original Tivoo SPP handshake now succeeds remains a hardware acceptance item. The new logs are deliberately designed to identify the first failing stage if the link still closes.

## 2. Evidence from the supplied UART log

The log establishes:

- Wi-Fi associated and obtained `192.168.3.28`.
- Bluetooth ACL connection completed with status 0.
- The SPP initiator initialized successfully.
- RFCOMM later closed and the application reported the generic `spp_open_or_authentication_failed`.
- The controller subsequently reported HCI disconnect reason `0x16`, which indicates disconnection initiated by the local host.

The supplied log does **not** contain the new `auth_complete`, `spp_open` or `spp_client_init` diagnostics, so it does not establish whether the missing condition was SDP/SCN discovery, SPP client initiation, SPP OPEN or GAP authentication. The 10-second interval is consistent with the configured connection wait deadline, but the old generic application error cannot by itself identify which event was missing.

The repeated `unknown PSM: 25` entries are AVDTP signalling attempts. This firmware is an SPP control client and does not register an A2DP/AVDTP endpoint. Those entries are not sufficient evidence that AVDTP caused the SPP close, and this fix does not add A2DP.

## 3. Definite session-state defect and fix

The existing automatic reconnect service already retried an established peer after unexpected link loss. However, the session policy had this failure path for the initial `0x69 + MAC` request:

1. Call the SPP connect backend.
2. If the backend returns failure, call `clear_peer(session)`.
3. Return `TIVOO_SPP_SESSION_CONNECT_FAILED`.

That cleared the only copy of the HA-selected peer before the worker's automatic-reconnect service could use it. The reconnect service checks `peer_valid`, so a first-attempt failure left it with no target and no way to retry.

The CONNECT transition now stores the HA-selected MAC and sets `peer_valid=true` / `connected=false` before the first backend attempt. If that attempt fails, the peer remains available for the next retry. The existing worker schedules the next attempt after `SPP_RECONNECT_RETRY_MS=2000`.

A matching explicit `0x96 + MAC` remains the normal operation that disables automatic retry and clears the peer session. A later `0x69 + MAC` selects the peer again. A failed retry retains the same MAC and remains disconnected; the worker retries again after 2000ms.

This does not authorize writes while disconnected. Frame writes still require an authenticated SPP handle and the session's connected state.

## 4. New connection-stage diagnostics

Added logs in `esp32/firmware/main/tivoo_spp.c`:

| Log | What it identifies |
|---|---|
| `spp_discovery_complete status=... scn_num=... scn0=...` | SDP completion status and returned RFCOMM SCN |
| `spp_discovery_unavailable ... fallback_scn=1` | Discovery API error or missing completion before using the contract fallback |
| `spp_connect_requested ... scn=... sec_mask=... api_err=...` | Actual selected SCN, security mask and immediate `esp_spp_connect()` return |
| `spp_client_init status=... handle=... sec_id=...` | `ESP_SPP_CL_INIT_EVT` result |
| `spp_open status=... handle=... peer=...` | `ESP_SPP_OPEN_EVT` result and remote address |
| `auth_complete peer=... status=... link_key_type=... target_match=... authenticated=...` | GAP `AUTH_CMPL` result |
| `spp_connect_wait_timeout open=... auth_done=... auth_ok=... failed=...` | Which required event was still missing at the 10-second deadline |
| `spp_bond_missing peer=...` | OPEN and authentication passed, but the target was not present in the Bluedroid bond list |
| `spp_connect_failed_events ...` | Event state when an asynchronous failure occurs |
| `spp_close status=... handle=... async=... port_status=...` | SPP close callback details |
| `gap_pin_request ... min_16_digit=...` | Legacy PIN request type, without logging the PIN |
| `gap_ssp_confirm_request_rejected ...` / `gap_passkey_request_rejected ...` | Unsupported SSP interaction path and why it was rejected |

The GAP auth callback continues to log only peer address, status, link-key type and authorization outcome; it never logs PIN, passkey or key material.

ESP-IDF v6.1 documents separate `ESP_SPP_CL_INIT_EVT` and `ESP_SPP_OPEN_EVT` callbacks for the initiator lifecycle. Both are now recorded rather than relying on one generic application error.

## 5. Verification

### TDD and focused tests

- Added a regression that makes the first connect backend call fail, verifies the HA peer address remains valid and disconnected, and then verifies a subsequent RECONNECT can succeed. It failed before the session fix and passed afterwards.
- Added a lifecycle-diagnostics source regression. It failed before `ESP_SPP_CL_INIT_EVT` handling was added and passed afterwards.
- Host SPP session executable: passed (`P5b3 SPP session ordering checks passed`).
- P5b3 bootstrap tests: **10 passed**.
- Full P5b1 network + P5b2 diagnostics + P5b3 bootstrap/control/security/session + P5b4 integration + HA Tivoo tests: **186 passed, 7 warnings in 47.53s**.
- Ruff check and Ruff format check for the changed Python test files: passed.
- `git diff --check`: passed.

The seven pytest warnings are dependency deprecations/plugin rewrite and the expected pytest-socket block from a test that tries a documentation-only non-loopback IP. No test failed.

### ESP-IDF build

Executed on the ARM64 Ubuntu development machine using ESP-IDF v6.1.0 and `IDF_TARGET=esp32`:

```bash
. /home/Gold/.espressif/tools/activate_idf_v6.1.sh
export IDF_TARGET=esp32
idf.py build
idf.py size
```

**Result:** PASS; all 1635 build steps completed, application linked and partition-size check succeeded.

- Application BIN: 1,256,992 bytes.
- Size-tool total image: 1,256,871 bytes.
- IRAM: 104,067 / 131,072 bytes (79.4%).
- DRAM: 99,719 / 124,580 bytes (80.04%).
- Factory app partition: 8MB; ample remaining partition space.

The build emitted existing ESP-IDF Kconfig deprecation/default notices. No source compile, link or app-partition size error occurred.

## 6. Windows update package — preserve NVS

The new package is:

`esp32/firmware/build/Tivoo-P5-SPP-Recovery-Fix-Preserve-NVS.zip`

Package directory:

`esp32/firmware/build/p5-spp-recovery-fix/`

Contents:

- `tivoo-esp32-app-p5-spp-recovery-fix.bin`
- `manifest.json`
- `README-Windows.txt`

**Flash only the application image at `0x010000`.** Configure ESP32 / 16MB / DIO / 40MHz.

Application image:

- Size: `1,256,992` bytes
- SHA256: `8c06809caefff85b95a7076a2359291f0b2989d34e81fd5e0c107c422e66b11e`

ELF SHA256 (the board UART reports the leading portion as `ELF file SHA256`):

`70b38a1973d3245d6a58b2a2777f24c3688cf88f721fd4b94c478e6a3e8c79fc`

ZIP SHA256:

`614533ba7b2c8767f82b4fa6f6ea8f25c9ca13548babfb2c32efcd082109881b`

**Do not erase flash/NVS and do not flash the previous 16MB merged image for this update.** This app-only write leaves NVS at `0x9000` and the existing Bluedroid Bond Keys untouched.

## 7. Physical acceptance procedure

After verifying the Windows ZIP and app-image SHA256:

1. In Espressif Flash Download Tool select ESP32, 16MB, DIO, 40MHz. Select only `tivoo-esp32-app-p5-spp-recovery-fix.bin` at address `0x010000`. Do not enable erase-all and do not program a full merged image.
2. Boot the board and confirm Wi-Fi obtains an IP and the existing HA 7777/7778 connections recover.
3. Send the HA `0x69 + configured Classic MAC` connect request. Observe the new SPP lifecycle log sequence.
4. Leave the device idle for at least 10 minutes after a successful connection. Require one `auth_complete ... status=0 ... target_match=1 authenticated=1`, followed by `authenticated_spp_peer_ready ... bond_list=confirmed`, with no unexpected `spp_close`.
5. Send a real HA text/display command and confirm Tivoo responds.
6. If first connection fails, verify that the same peer is retried after about 2 seconds. Do not send another `0x69` just to trigger the retry.
7. Once connected, interrupt the Bluetooth link unexpectedly while leaving HA TCP connected. Verify `spp_reconnected` after the same Tivoo becomes available, followed by a working real command.
8. Send a matching explicit `0x96 + MAC`; verify automatic reconnect stops. Send a new `0x69 + MAC`; verify automatic retry is enabled again.

### Reading the next UART log

The next UART capture should include the first connection attempt and at least one retry. The decisive patterns are:

- `spp_discovery_complete status=0 scn_num=1 scn0=1` (or the actual returned SCN), followed by the selected `spp_connect_requested`.
- If `spp_client_init` reports a nonzero status, inspect that status first.
- If `spp_open status` is nonzero or absent, the failure is before successful SPP open.
- If `spp_open status=0` but `auth_done=0` at timeout, the missing stage is GAP authentication completion.
- If `auth_complete ... status!=0`, use the numeric status and key type to decide the next security investigation; do not downgrade the security mask without that evidence.
- If `auth_complete status=0` and `spp_open status=0` but no `authenticated_spp_peer_ready`, inspect the bond-list verification stage.
- After a failed attempt, expect another `spp_connect_requested` for the same MAC after the 2000ms retry interval.

The board has not been connected to the development host during this work; all physical items above remain NOT RUN. The actual first-link failure mechanism therefore remains to be distinguished by the new UART diagnostics.

## 8. HA and repository scope

- HA integration/configuration files changed: **none**. The configured `tivoo_bluetooth_mac` remains the only target source and the existing 7778 logger carries the new diagnostics.
- The existing dirty TCP stack-buffer fix, bounded SPP queue backpressure and established-peer reconnect work were preserved.
- Existing local P5 changes remain uncommitted. Nothing was merged, pushed or discarded.
