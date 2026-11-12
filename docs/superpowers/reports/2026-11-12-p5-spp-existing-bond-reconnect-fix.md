# P5 SPP Existing-Bond Reconnect Fix

**Date:** 2026-11-12  
**Branch:** `feature/p5-esp32-minimal-firmware`  
**Base:** `79a3bf0`  
**Firmware:** ESP-IDF v6.1 / ESP32-D0WD-V3

## 1. Reproduced symptom

The HA diagnostic log repeatedly showed:

1. SDP discovery succeeded and returned RFCOMM SCN 1.
2. `esp_spp_connect()` returned `ESP_OK`; client initialization succeeded.
3. `ESP_SPP_OPEN_EVT` arrived with `status=0` for the configured Tivoo MAC.
4. No successful `ESP_BT_GAP_AUTH_CMPL_EVT` arrived within 10 seconds.
5. The SPP worker timed out, explicitly disconnected the handle, and retried after 2 seconds.

This established an application-created close/retry loop, not an unexplained physical link loss.

## 2. Root cause

ESP-IDF v6.1 Bluedroid reports successful `AUTH_CMPL` on the new-link-key path. When an existing BR/EDR Bond Key is reused successfully, a successful `AUTH_CMPL` callback is not guaranteed. The failure callback still reports authentication failures.

The firmware treated both `OPEN` and `AUTH_CMPL` as mandatory for every connection. On a previously bonded peer, RFCOMM OPEN therefore succeeded but the application waited until its 10-second deadline and then disconnected a valid session.

The SPP API already passed `ESP_SPP_SEC_AUTHENTICATE | ESP_SPP_SEC_ENCRYPT` into Bluedroid's RFCOMM security-level check before creating the RFCOMM connection. OPEN success under this security mask is the relevant transport/security result for a reused Bond Key.

## 3. Fix

- Check whether the configured target MAC is already present in the Bluedroid Bond List before starting the SPP connection.
- For an existing Bond, accept the connection only after RFCOMM OPEN succeeds; re-check that the same target remains in the Bond List before marking the peer ready.
- For first pairing or a newly created Link Key, continue requiring a successful, target-matched `AUTH_CMPL` plus the post-connect Bond List check.
- Any received authentication failure remains fail-closed.
- Preserve the original AUTHENTICATE + ENCRYPT security mask. No security downgrade, fixed MAC, key copy, NVS erase, or HA integration change was introduced.
- Add `spp_bond_reused_after_open` / `spp_bond_created_after_auth` diagnostics and a host regression for the no-AUTH_CMPL existing-Bond path.
- Clarify P5-C24 in the contract matrix.

## 4. Automated verification

- Regression test first failed against the old implementation, then passed after the fix.
- Focused SPP/session and bootstrap tests: **12 passed**.
- P5 ESP32 and HA Tivoo regression scope: **187 passed, 6 warnings**.
- Ruff check, Ruff format check, and `git diff --check`: passed.
- ESP-IDF v6.1 `idf.py reconfigure`, `idf.py build`, and `idf.py size`: passed.
- Final firmware reports `0.1.0+79a3bf0`; image SHA256: `42ec82201e83a33dbc3a85cf04a43c1d4e30b2c8cde459b5cd5b0fe81c4c1b71`.
- App image size: 1,257,488 bytes; factory app partition: 8 MiB.

## 5. Physical ESP32 acceptance

The app image was flashed through the NAS-attached `/dev/ttyACM0` using esptool 4.8.1. Both writes targeted only `0x10000`; esptool reported the erase range `0x10000–0x143fff` and verified the written image hash. The NVS partition at `0x9000` (24,576 bytes) was backed up before flashing to:

`/tmp/tivoo-nvs-before-p5-bond-reuse.bin`

No NVS erase or HA container restart was performed.

After the final reconfigured build was flashed, a direct TVIO diagnostic client received HELLO version `0.1.0+79a3bf0`. A 7777 control connection then sent the configured `0x69 + 11:75:58:97:49:98` request. The device reported:

- `spp_open status=0`
- `spp_bond_reused_after_open ... security=authenticate+encrypt`
- `authenticated_spp_peer_ready ... bond_list=confirmed`

The diagnostic connection remained open for 36 seconds, crossing the former 10-second timeout by over three times, with no `spp_close`, `spp_connect_wait_timeout`, or retry event.

A second 7777 TCP connection sent the same `0x69 + MAC` while SPP was already connected. The device reported `spp_connect_duplicate_ignored`; no new SPP OPEN/CLOSE or reconnect occurred during the following 15 seconds.

These checks exercised the real NAS-attached ESP32, its existing Bond Key, the production TCP control parser, and the production SPP worker.

## 6. Scope and repository state

- No HA integration source or container configuration was changed.
- The P5 contract matrix was updated for the real Bluedroid existing-Bond event semantics.
- Changes remain uncommitted on `feature/p5-esp32-minimal-firmware`; no merge or push was performed.
