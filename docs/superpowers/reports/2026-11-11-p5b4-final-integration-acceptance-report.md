# P5b4 Final Integration and Acceptance Report

**Date:** 2026-11-11
**Branch:** `feature/p5-esp32-minimal-firmware`
**Firmware source commit:** `b3af194b1315aebd0ceeb217e74f51a2a3eece21`
**Firmware version:** `0.1.0+b3af194`

## 1. Scope and result

P5b4 completed the final ESP32 integration work, host-side fault-injection coverage, ESP-IDF clean build, and Windows-ready release package.

The release and host-test work is complete. Physical-device acceptance remains pending because the remote development session did not have the ESP32 board and a Tivoo connected. Those hardware-only checks are deliberately recorded as **NOT RUN**, not simulated as PASS.

No Home Assistant integration source/configuration file required an update in this batch. HA already reads `tivoo_bluetooth_mac` as the selected Classic peer address, sends the 7777 connect command, and receives/forwards 7778 DIAGNOSTIC_LOG messages into the existing `custom_components.tivoo` logger. The new firmware authentication result is carried through that existing diagnostic message path.

## 2. Implementation

### 2.1 GAP authentication observability

- Added a required `auth_complete` observer to the GAP security-policy callback contract.
- Every `AUTH_COMPLETE` event now reports peer address, numeric status, numeric link-key type, target match, and final authenticated outcome.
- The production observer emits one structured log line and never logs a PIN, passkey or key material.
- The existing fail-closed gate is unchanged: only the configured target MAC with successful authentication can become an SPP-ready peer.
- The post-authentication ready log now includes the peer address and `bond_list=confirmed`, proving that the configured peer was found in the Bluedroid bond-address list before frame writes are accepted.

### 2.2 Combined 7777/7778 integration fault tests

Added a POSIX host harness which compiles the production TCP listener, control bridge, Tivoo frame-stream parser and diagnostics implementation. Only the ESP-IDF services and the external SPP worker are host-shimmed.

The tests cover:

1. Simultaneous 7777 raw control and 7778 TVIO HELLO/ACK/logging, including independent 7778 reconnect while the 7777 control connection remains usable.
2. One-shot SPP frame queue failure: 7777 closes the failed control session, while 7778 receives `spp_tx_queue_full` and continues to carry diagnostics.
3. Simulated IP loss and recovery: both TCP sessions close; after IP recovery, new sessions establish and a new control frame is accepted.

## 3. Automated verification

- Authentication/session/control focused regression after the callback change: **7 passed**.
- New combined 7777/7778 integration tests: **3 passed**.
- The new test was first run without the simulator sources and failed at compile/setup as expected; it passed after the host harness was added.
- Python Ruff check and formatting check for `tests/esp32/test_p5b4_integration.py`: passed.
- `git diff --check`: passed.
- Full P5b1–P5b4 + HA Tivoo regression suite: **182 passed, 7 warnings in 30.74s**.

Tests use the repository's HA pytest bootstrap:

```bash
PYTHONPATH=homeassistant .venv/bin/python - <<'PY'
import homeassistant
import pytest
raise SystemExit(pytest.main([
    "tests/esp32/test_p5b1_network_listeners.py",
    "tests/esp32/test_p5b2_diagnostics.py",
    "tests/esp32/test_p5b3_bootstrap.py",
    "tests/esp32/test_p5b3_control_bridge.py",
    "tests/esp32/test_p5b3_security.py",
    "tests/esp32/test_p5b3_session.py",
    "tests/esp32/test_p5b4_integration.py",
    "tests/homeassistant/custom_components/tivoo",
    "-q",
]))
PY
```

## 4. ESP-IDF clean build

Executed on the ARM64 Ubuntu development machine:

```bash
. /home/Gold/.espressif/tools/activate_idf_v6.1.sh
export IDF_TARGET=esp32
idf.py fullclean
idf.py build
idf.py size
```

**Result:** complete success. All 1,635 build steps completed. ESP-IDF reports v6.1.0, target `esp32`, and esptool v5.6.0.

- Application binary: 770,736 bytes.
- Size-tool total image size: 770,619 bytes.
- IRAM: 100,999 / 131,072 bytes (77.06%).
- DRAM: 79,963 / 124,580 bytes (64.19%).
- RTC SLOW: 64 / 8,192 bytes (0.78%).
- Smallest app partition: 8MB; the generated app uses about 9% of it.
- Generated partition layout: NVS 24KB at `0x9000`, PHY init 4KB at `0xF000`, factory app 8MB at `0x10000`, storage 8128KB at `0x810000`.

The clean build emitted existing ESP-IDF/Kconfig deprecation and third-party component CMake include-directory warnings; no compile, link, partition-size or image-generation error occurred.

The local `sdkconfig` contains this development environment's Wi-Fi credentials. It was not displayed, copied into the package, staged or committed. Only the credential-free `sdkconfig.defaults` remains tracked.

## 5. Windows release package

Generated with the build-produced `flash_args`:

```bash
idf.py merge-bin --format raw --flash-offset 0x0 --pad-to-size 16MB \
  --output build/p5b4-release/tivoo-esp32-wrover-e-n16r8-p5b4-b3af194.bin
```

esptool confirmed the output is ready to flash at `0x0` and wrote exactly `0x1000000` bytes.

Release files are under:

`esp32/firmware/build/p5b4-release/`

| File | Purpose | Flash offset | Size |
|---|---|---:|---:|
| `tivoo-esp32-wrover-e-n16r8-p5b4-b3af194.bin` | Full raw image (bootloader + partition table + app) | `0x000000` | 16,777,216 bytes |
| `tivoo-esp32-app-p5b4-b3af194.bin` | App-only update image | `0x010000` | 770,736 bytes |
| `manifest.json` | Build provenance, flash settings, image sizes and SHA256 values | — | JSON |
| `flash_args.txt` | IDF-generated image input/offset map | — | Text |

Full-image SHA256:

`48d3cdd65035a1b99e30059b847a3fcd83405515156b72208d06c3a664a0f69b`

App-only image SHA256:

`63b714668487c7c625de5dc7dd0b3499e532d5189a1b10224c11e1b0d4fe9fb1`

Release `manifest.json` SHA256:

`a7f6c8ad565ae0e93fe0feacfa6ff1b20c83299e971e62c6e26902b1cfbb5c1b`

Flash configuration: ESP32, 16MB, DIO, 40MHz, raw full-flash image at `0x000000`.

### Important NVS handling

The full 16MB image spans the NVS address range. It is for first installation or deliberate full reinitialization; flashing it after pairing overwrites the existing NVS contents, including Bluetooth Bond Keys.

For a routine firmware update after successful pairing, use the app-only image at `0x010000`. Do not erase flash/NVS. The app-only image leaves the existing bootloader, partition table and NVS intact. This assumes the partition layout remains compatible.

### Windows flashing procedure

1. Copy the complete `p5b4-release` directory from the Ubuntu development workspace to the Windows flashing machine.
2. In PowerShell, verify the full image before flashing:
   `Get-FileHash .\tivoo-esp32-wrover-e-n16r8-p5b4-b3af194.bin -Algorithm SHA256`.
   Compare the result with `manifest.json`.
3. Open Espressif Flash Download Tool, select chip `ESP32`, the board's COM port, flash size `16MB`, mode `DIO` and frequency `40MHz`.
4. For first installation, select only the full image file and set its address to `0x000000`. Do not add separate bootloader, partition-table or app entries; they are already inside the merged image.
5. Start programming and require the tool to report successful write/verification. Reboot the board and inspect the serial boot log.
6. For a later app-only update, select the app-only image at `0x010000`; do not run an erase-all operation.

## 6. Physical-device acceptance — pending

All items below are **NOT RUN** in this development session. The board/Tivoo interoperability, actual radio pairing and persistent on-device Bond Key cannot be established by the POSIX simulator or by a successful cross-compile.

### A. First flash and startup

**Steps**

1. Connect the ESP32-DEV-KIT-WROVER-E-M by USB to the Windows flashing host.
2. Verify the full image SHA256 against the release manifest.
3. Flash the merged raw image once at `0x000000` with ESP32 / 16MB / DIO / 40MHz settings.
4. Reboot and observe the UART log; wait for Station to connect and obtain an IPv4 address.
5. Ensure the HA Config Entry contains the phone-confirmed Classic `Tivoo-audio` MAC, then reload the existing Tivoo integration.

**Acceptance**

- Boot completes without a reset loop.
- Wi-Fi obtains an IP address.
- HA establishes 7777 and the 7778 TVIO HELLO/ACK session.
- The firmware reports the expected firmware version `0.1.0+b3af194`.

### B. First Classic pairing and real control

**Steps**

1. Obtain the Tivoo Classic audio MAC using a Classic Bluetooth inquiry/scanner. Do not use the BLE `Tivoo-light` address.
2. Enter the address in HA `tivoo_bluetooth_mac`; do not set or compile a peer address in ESP32 firmware.
3. Reload the existing HA integration and observe the 7778 logs.
4. Invoke an existing HA Tivoo control service (for example, a simple display/text/brightness action supported by the current integration).

**Acceptance**

- Log shows the configured MAC, `status=0`, `target_match=1`, and `authenticated=1`.
- SPP-ready log for the same MAC contains `bond_list=confirmed`.
- The real Tivoo performs the requested action.
- No frame is written before authentication and bond-list confirmation.

### C. Bond Key reuse after software restart

**Steps**

1. After first pairing succeeds, keep the phone's Tivoo pairing and ESP32 NVS intact.
2. Attach a JTAG/OpenOCD GDB session and invoke ESP-IDF `esp_restart()` while the application is running.
3. Wait for Wi-Fi and HA channels to recover, then observe the authentication and SPP-ready logs.

**Acceptance**

- This is a software-triggered `esp_restart()`, not the EN button or a power cut.
- Same Classic MAC returns to `authenticated=1` and `bond_list=confirmed`.
- Connection resumes without a new pairing/PIN interaction.
- A real HA control command works after reconnect.

If no JTAG debugger is available, record this item as **NOT RUN**. An EN-button reset is not an equivalent test for the software-restart requirement.

### D. Bond Key reuse after complete power cycle

**Steps**

1. After the software-restart test, fully remove board power (USB and any other supply) for at least 10 seconds.
2. Restore power. Do not erase NVS or forget the Tivoo pairing on the phone.
3. Wait for Wi-Fi, HA 7777/7778 sessions and SPP to recover.

**Acceptance**

- The same configured Classic peer authenticates and is found in the Bluedroid bond list.
- No new pairing/PIN interaction is required.
- A real HA control command works.

### E. HA peer-address replacement

**Steps**

1. With a second real Tivoo available, identify its Classic `Tivoo-audio` MAC.
2. Change only HA `tivoo_bluetooth_mac` and reload the existing integration. Do not rebuild or reflash ESP32.
3. Observe the old SPP peer disconnect and the new address authentication/connect sequence.

**Acceptance**

- ESP32 attempts the new HA-selected address without a firmware change.
- New address is authenticated and bond-list confirmed before frame writes.
- The second Tivoo responds to a real HA command.

A deliberately incorrect MAC can additionally verify rejection (`target_match=0`, `authenticated=0`, no ready state); it does not count as a successful replacement-device pairing.

### F. Wi-Fi loss and recovery

**Steps**

1. While both TCP sessions are active, disable the Wi-Fi AP or otherwise disconnect the ESP32 from the network.
2. Observe HA/TCP disconnect behavior.
3. Restore Wi-Fi and wait for reconnect.

**Acceptance**

- Both old TCP sessions close on IP loss.
- Once a new IPv4 address is available, the 7778 HELLO/ACK handshake is repeated and 7777 is re-established.
- A new command reaches the Tivoo after reconnect.

## 7. HA integration change assessment

**HA integration files changed: none.** The current integration already consumes the configured MAC and routes 7778 DIAGNOSTIC_LOG messages through the existing logger. The added firmware authentication events use that same log path. P5b4 did not add new HA services, config fields, entities or protocol message types.

## 8. Git and scope

Implementation commits on the existing P5 feature branch:

- `c765e87 fix(p5b4): expose SPP authentication outcomes`
- `b3af194 test(p5b4): cover combined TCP fault recovery`

The P5b4 plan, README and this report are the final documentation changes. This batch does not merge the branch into main or push it, and it does not begin any later P5/P6/P7 work.
