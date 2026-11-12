# P5 SPP Stability Fix Report

**Date:** 2026-11-11  
**Branch:** `feature/p5-esp32-minimal-firmware`  
**Base commit:** `95cfb43` (changes remain uncommitted)  
**Target:** Waveshare ESP32-DEV-KIT-WROVER-E-M / classic ESP32 / ESP-IDF v6.1

## 1. Scope and result

This change addresses only the three defects identified from the user's UART log and source inspection:

1. SPP connect/auth wait busy-loop starving CPU 1 IDLE task.
2. Long animation sends overflowing the 32-item SPP worker queue.
3. No device-side recovery after an established SPP link is unexpectedly closed.

The implementation, host regression tests, contract clarification, ESP-IDF build and Windows update package are complete. The new image has **not yet been flashed to the physical board**, so real Tivoo long-text and reconnection acceptance remains pending.

## 2. Root causes

### 2.1 SPP connection wait starved IDLE1

The supplied task watchdog log reported `CPU 1: tivoo_spp` and `IDLE1` failing to reset the watchdog. Address resolution against the matching ELF placed the application frames in:

- `wait_for_open_and_auth()` — `tivoo_spp.c`
- `connect_peer()` — `tivoo_spp.c`
- `session_connect()` — `tivoo_spp.c`
- `tivoo_spp_session_process()` — `tivoo_spp_session.c`
- `spp_worker()` — `tivoo_spp.c`

The wait loop needs both `EVENT_OPEN` and `EVENT_AUTH_DONE`, but the previous `xEventGroupWaitBits()` call used `waitForAll=pdFALSE` with both event bits continuously in its wait mask. When either event arrived first, the wait returned immediately on every subsequent loop because the already-set event remained set. The worker therefore spun without blocking while waiting for the other event.

### 2.2 Queue rejected bursts immediately

The SPP queue capacity was 32 requests and `queue_request()` passed zero wait ticks to `xQueueSend()`. HA's animation codec splits a scrolling text animation into 200-byte Tivoo animation chunks. A 25-character Chinese test string generated 158 animation frames and 36 outgoing SPP packets; 38 Chinese characters generated 54 packets. A burst larger than the 32 free queue slots could therefore fail before the worker had time to drain the queue. The existing TCP control bridge intentionally closes the control socket when `spp_tx_queue_full` is returned.

The P5 contract already specifies a 1000 ms bounded queue-write wait; the zero-wait implementation did not match that contract.

### 2.3 Established SPP peer had no recovery loop

`ESP_SPP_CLOSE_EVT` previously cleared the handle/event bits but did not queue a reconnect. The SPP worker blocked forever with `xQueueReceive(..., portMAX_DELAY)`, so it could not notice link loss while idle. HA's TCP connection could remain established while SPP was disconnected, so the HA adapter had no TCP disconnect event that would resend `0x69 + MAC`.

## 3. Changes

### 3.1 Correct event-driven connection wait

Added the platform-independent `tivoo_spp_connection_wait_mask()` helper. The wait mask always includes `EVENT_FAILED`, and includes only whichever of `EVENT_OPEN` or `EVENT_AUTH_DONE` have not yet arrived. The loop now blocks for the missing event rather than repeatedly waking on an already-set event. A fixed deadline remains in place.

### 3.2 Bounded queue backpressure

`queue_request()` now waits up to `SPP_QUEUE_WRITE_TIMEOUT_MS=1000` using `pdMS_TO_TICKS()` when inserting into the existing 32-item queue. The TCP listener therefore yields receive progress while the SPP worker drains queued packets. Queue depth and the existing error contract are unchanged: if the queue still cannot accept a request before the bound expires, the existing `spp_tx_queue_full` error path remains in effect. The listener does not wait for SPP WRITE completion; that work remains in the SPP worker.

### 3.3 Worker-driven reconnect after unexpected link loss

- Added `EVENT_AUTO_RECONNECT` and `EVENT_LINK_LOST` EventGroup bits so the SPP callback and worker share the reconnect mode through the existing FreeRTOS event group.
- A successful HA `0x69 + MAC` request enables automatic recovery for the selected session.
- `ESP_SPP_CLOSE_EVT` reports a link-loss event only while automatic recovery is enabled.
- The worker now waits for queue work for at most 250 ms, then services pending recovery even when no new TCP data arrives.
- On unexpected loss, the worker marks the current session disconnected without clearing its peer MAC. It reconnects to that same HA-selected peer using the existing authenticated SDP/SCN and native Bluedroid Bond Key path.
- Failed recovery attempts are retried every 2000 ms.
- A matching explicit `0x96 + MAC` disables auto-reconnect before the disconnect operation and clears the session through the existing session policy. A mismatched `0x96` does not disable recovery for another peer.
- The change introduces no fixed/backup MAC, Classic Inquiry, BLE scanning, app-level Bond Key storage, or HA TCP disconnect side effect.

The redundant `s_target_valid` flag was removed; the session state and current SPP handle already gate writes, avoiding a separate callback/worker-shared boolean.

## 4. Contract update

Added two clarifications to §6.2 of `docs/superpowers/specs/2026-11-11-p5-esp32-minimal-firmware-contract-matrix.md`:

- Queue insertion uses the existing 1000 ms bounded wait to apply TCP receive backpressure; it does not grow the 32-entry queue or wait for SPP WRITE completion.
- Unexpected loss of an established SPP peer triggers same-peer device-side reconnect at 2000 ms intervals; matching explicit `0x96` disables it. HA remains the only authority for the peer MAC.

No P5b0–P5b4 batch boundaries were redefined.

## 5. Tests and build verification

TDD was used for the new session wait/reconnect and worker/queue behavior assertions. The new regression checks were observed failing before the production changes, then passed after implementation.

Final verification on the current working tree:

| Check | Result |
|---|---:|
| P5b1 network listeners + P5b2 diagnostics + P5b3 bootstrap/control/security/session + P5b4 integration + HA Tivoo integration regression | **185 passed, 7 warnings** |
| Ruff check (`tests/esp32/test_p5b3_bootstrap.py`) | PASS |
| Ruff format check (`tests/esp32/test_p5b3_bootstrap.py`) | PASS |
| `git diff --check` | PASS |
| ESP-IDF v6.1 `ninja -C build`, target `esp32` | PASS, all 9 steps |
| Application image size check | PASS; 1,255,568 bytes in 8 MiB app partition |
| Update ZIP integrity and manifest/address validation | PASS |

The 7 pytest warnings are existing Home Assistant/Python dependency deprecation warnings, a pytest plugin rewrite warning, and the expected blocked non-loopback socket test warning. They did not cause test failures. The ESP-IDF build emitted existing Kconfig default/deprecation notices; linking, image generation and partition-size validation succeeded.

## 6. Firmware update artifact

Windows update package (bootloader + partition table + application, while preserving NVS):

`esp32/firmware/build/Tivoo-P5-SPP-Stability-Update-Preserve-NVS.zip`

Package directory:

`esp32/firmware/build/p5-spp-stability-update-preserve-nvs/`

Flash segments:

| File | Address |
|---|---:|
| `bootloader.bin` | `0x1000` |
| `partition-table.bin` | `0x8000` |
| `tivoo-app-p5-spp-stability-fix.bin` | `0x10000` |

The helper uses Espressif `esptool` and leaves NVS at `0x9000` and PHY data at `0xF000` untouched. Do not perform a whole-flash erase.

- ZIP SHA256: `3eed4c5195a23e6caacd4663944ad4edce0a83c854555dfcc8622ac39d74b5ca`
- ELF SHA256 (expected UART `ELF file SHA256`): `b63ece084fa940f21cc78ea0449d0bfc9841ce058a4645b5f57435f3d54c0591`
- App BIN size: `1,255,568` bytes
- App BIN SHA256: `748439bcc4097d547f33a3cf61cbb8a8c9a45062ecf6df31882340c98347cf33`

## 7. Physical acceptance still required

The board has successfully booted Wi-Fi and connected to Tivoo with the previous stack-fix image, but this new SPP stability image has not yet been flashed. After flashing this package, verify on the real board:

1. UART ELF SHA256 matches the value in §6.
2. Send a scrolling text whose animation contains more than 32 outgoing chunks; the 7777 control socket should not close due to an immediate queue-full rejection.
3. Confirm the Tivoo displays the full scroll.
4. Interrupt the Classic SPP link unexpectedly while the HA TCP channels remain connected; the ESP32 should log `spp_reconnected` after the peer becomes available.
5. After recovery, send another command. Then send a matching explicit `0x96` and confirm that the ESP32 does not reconnect until a new `0x69` is received.
6. Check that no `IDLE1` task watchdog or `spp_open_or_authentication_failed` busy-loop sequence recurs.

## 8. Repository state and review

Changes remain on `feature/p5-esp32-minimal-firmware`, uncommitted, unmerged and unpushed. The existing local P5b4 TCP stack-overflow fix files were preserved; this report covers the additional SPP stability work. A read-only self-review was performed because no reviewer subagent tool is available; it is not an independent fresh-context review.
