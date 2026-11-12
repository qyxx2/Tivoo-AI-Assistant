# P5 Persistent SPP Connection and Idempotent Connect Fix

**Date:** 2026-11-12  
**Branch:** `feature/p5-esp32-minimal-firmware`  
**Target:** ESP32-DEV-KIT-WROVER-E-M / ESP-IDF v6.1

## 1. Expected SPP lifecycle

The Classic RFCOMM/SPP session is a persistent transport, not a per-command connection. Once OPEN, authentication and Bond List checks succeed, the connection remains open while idle and carries subsequent display commands. The worker's 250 ms queue polling is only an internal scheduling wait; it does not close or recreate the Bluetooth connection.

Only these conditions should cause a new SPP connection attempt:

- Initial connection has not succeeded yet.
- The active Bluetooth link is unexpectedly lost.
- HA explicitly selects a different Classic MAC.

A duplicate connect request for the same already-connected MAC must not cause a disconnect/reconnect cycle.

## 2. Root cause found in the current workspace

The HA transport opens TCP control port 7777 and sends `0x69 + configured MAC` once for each TCP control connection. Its control connection loop reopens TCP after the TCP peer closes or the connection fails, so a later TCP connection legitimately sends `0x69 + MAC` again.

Before this fix, the ESP32 session policy treated every `TIVOO_SPP_REQUEST_CONNECT` as a forced session replacement:

1. If a peer was already selected, call the disconnect backend.
2. Clear the current session.
3. Connect to the requested peer, even if it was the exact same MAC.

Thus a repeated HA `0x69 + same MAC` could actively close an otherwise healthy, already-connected SPP session. This was especially inappropriate for a TCP reconnection: TCP and Bluetooth are independent links, and rebuilding the TCP channel must not interrupt a healthy Bluetooth RFCOMM session.

## 3. Changes

### 3.1 Same-MAC connect is idempotent

Updated `tivoo_spp_session_process()`:

- Same MAC + session already connected: return success without calling disconnect or connect. Existing SPP handle remains untouched.
- Same MAC + session marked disconnected: call connect for the same peer without a preliminary disconnect.
- Different MAC + an existing peer: orderly disconnect the previous peer, then connect the newly selected MAC.
- No existing peer: store the HA-selected MAC before attempting connect, retaining the earlier fix that allows automatic retries after the first failure.

The SPP worker emits `spp_connect_duplicate_ignored` when it receives a repeated same-MAC connect request while the session is already connected.

### 3.2 Auto-reconnect remains failure-driven

- Successful SPP connection is retained indefinitely while idle; no periodic connection timer or keepalive reconnect was added.
- Unexpected `ESP_SPP_CLOSE_EVT` continues to mark the session disconnected and retain the selected MAC.
- Failed connect attempts continue to retry the same HA-selected MAC after 2000 ms.
- A matching explicit `0x96 + MAC` still disables auto-reconnect and clears the selected session.
- A changed MAC is still switched in FIFO order.

### 3.3 Contract and plan

Updated the P5 contract and P5b3 implementation plan to define same-MAC idempotency and different-MAC peer switching. The earlier P5b3 implementation report records the old behavior historically; this follow-up supersedes that same-MAC reconnect detail.

No HA integration source change was needed. HA should continue to send `0x69 + MAC` once after each new 7777 TCP connection.

## 4. Verification

- Host session test verifies duplicate same-MAC connect while connected produces no disconnect/connect backend calls.
- Host session test verifies same-MAC connect after a marked link loss initiates a new connect without first disconnecting.
- Host session test verifies a different MAC still disconnects the old peer before connecting the new peer.
- Focused host SPP session executable: passed.
- P5b3 bootstrap tests: **10 passed**.
- Full P5b1 network + P5b2 diagnostics + P5b3 bootstrap/control/security/session + P5b4 integration + HA Tivoo tests: **186 passed, 7 warnings in 29.37s**.
- Ruff check and format check: passed.
- `git diff --check`: passed.
- ESP-IDF v6.1 production build and `idf.py size`: passed; app partition size check succeeded.

The seven test warnings are existing dependency deprecations/plugin rewrite and the expected pytest-socket blocked non-loopback connection warning. No tests failed.

## 5. Updated Windows package — preserve NVS

The latest combined firmware package is:

`esp32/firmware/build/Tivoo-P5-SPP-Persistent-Connection-Fix-Preserve-NVS.zip`

Package directory:

`esp32/firmware/build/p5-spp-persistent-connection-fix/`

Application image:

`tivoo-esp32-app-p5-spp-persistent-connection-fix.bin`

- Flash offset: `0x010000`
- Flash configuration: ESP32 / 16MB / DIO / 40MHz
- Application image size: `1,257,168` bytes
- Application SHA256: `851be828012753c14996be98e752ba1c974369745485549c9d36050388258c3e`
- ELF SHA256: `15dbee53484a5673b06fd1461851397c5a4c152274ce74e18a35968422751dd4`
- ZIP size: `788,066` bytes
- ZIP SHA256: `c358819ab7f51c43f4ec298d5fb1e170f45ae0d91a91833b9418bd993d373302`

The ZIP was integrity-checked, and the packaged application binary hash was checked against its manifest. The built image contains the new `spp_connect_duplicate_ignored`, `spp_reconnected` and `spp_bond_missing` diagnostic strings.

**Flash only the application image at `0x010000`.** Do not erase flash/NVS and do not program a full merged 16MB image. The update preserves existing Wi-Fi configuration and Bluedroid Bond Keys.

## 6. Physical acceptance

The new image has not yet been flashed to the physical board. After flashing, verify:

1. The ESP32 establishes SPP and reports `authenticated_spp_peer_ready`.
2. Leave HA 7777 connected and the Tivoo idle for 10 minutes. There should be no repeated `spp_close` or new `spp_connect_requested`.
3. Reconnect only HA's 7777 TCP control channel while leaving the Tivoo Bluetooth link untouched. HA will send another same-MAC `0x69`; ESP32 should report `spp_connect_duplicate_ignored`, with no SPP close/open cycle.
4. Send multiple display commands over the same active SPP connection.
5. Interrupt Bluetooth deliberately; after the link loss, the ESP32 should retry the same MAC and report `spp_reconnected` after recovery.
6. Send a matching explicit `0x96 + MAC`; confirm auto-reconnect stops.

The physical board is not claimed to be stable until this idle-retention and TCP-reconnect acceptance is observed over UART.

## 7. Repository state

All changes remain uncommitted on `feature/p5-esp32-minimal-firmware`. Existing TCP stack fix, initial-connect retry fix, security policy, diagnostics, and NVS-preservation behavior remain in the working tree. No merge or push was performed.
