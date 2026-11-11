# P5b3 — TCP 7777 control bridge, Classic SPP and bond persistence

> **For the implementer:** Execute this plan in order with test-driven development. The P5 contract matrix remains authoritative. This batch does not change the existing P5b0–P5b4 boundaries and does not perform physical-board acceptance.

**Goal:** Replace the 7777 placeholder with HA-to-Tivoo raw-control forwarding, implement the ESP32 stream parser and Classic SPP initiator, and retain native Bluedroid Bond Keys in NVS.

**Architecture:** HA reads the single authoritative `tivoo_bluetooth_mac` from the Config Entry and sends `0x69 + 6-byte MAC` at each control TCP connection. HA serializes the existing semantic `TivooCommand` objects into upstream-compatible Tivoo frames. ESP32 demultiplexes fixed 7-byte connection/disconnect commands from complete Tivoo frames and queues them to one ordered SPP worker. The SPP worker performs selected-peer SDP, SCN-1 fallback, authenticated initiator connection, 330-byte write chunks and orderly disconnect. Bluetooth GAP policy is independently testable with a mock callback table.

**Global constraints**
- Contract: `docs/superpowers/specs/2026-11-11-p5-esp32-minimal-firmware-contract-matrix.md`, especially §§5, 6, 10 and C09–C12/C22–C25.
- Work only in the existing user-selected checkout on `feature/p5-esp32-minimal-firmware`; do not create a second worktree.
- Reuse the fixed upstream `esp32-divoom` commit `e90a77bbade7e92523bfb5b69bc5cb1e4d167520` and preserve its MIT notice; no Arduino/AsyncTCP runtime.
- Keep 7778 diagnostics behavior unchanged. No SPP DATA_IND reverse channel, no Classic Inquiry/BLE scanning, no app-layer bond key, no fixed ESP32 peer MAC.
- No NVS erase recovery. No board flashing, physical pairing acceptance, merge or push in P5b3.
- Python tests use `.venv` (Python 3.14); IDF build uses `/home/Gold/.espressif/tools/activate_idf_v6.1.sh`.

## Task 1 — HA command codec and 7777 control session

**Files:** `homeassistant/custom_components/tivoo/protocol.py`, `transport.py`, `__init__.py`, `UPSTREAM.md`, `tests/homeassistant/custom_components/tivoo/test_protocol.py`, `test_transport.py`.

1. Add tests first for the Tivoo outer frame golden vector (brightness 100), checksum/length, RGB palette/frame encoding, single-image and multi-frame animation chunk boundaries, every P5 service command mapping, and invalid/oversize payloads.
2. Run the new focused test file and observe failures for missing production behavior.
3. Implement the protocol codec using the local upstream MIT implementation for `_build_packet`, palette encoding, image-frame construction and 200-byte animation chunks. Preserve the MIT attribution in `UPSTREAM.md`; avoid copying unused CLI/Bluetooth bridge code.
4. Add command mapping for the current service set: brightness, volume, start/stop countdown, expression, text, still image, and animation. All pixel arrays are already generated on HA; ESP32 must not encode pixels.
5. Extend `Esp32ConnectionAdapter` with the Config Entry MAC, send exactly `69 + bytes.fromhex(mac)` after each successful TCP 7777 connection, and serialize encoded commands through that socket. A TCP reconnect sends the MAC again. Do not send `0x96` when the TCP socket closes. Keep diagnostics independent.
6. Test loopback TCP for initial/reconnect MAC bytes, command-frame bytes, concurrent calls preserving write order, unavailable connection behavior, and a new Config Entry adapter using a changed MAC.

**Expected:** `.venv/bin/python -m pytest tests/homeassistant/custom_components/tivoo/test_protocol.py tests/homeassistant/custom_components/tivoo/test_transport.py -q` passes.

## Task 2 — TCP byte-stream parser and SPP request boundary

**Files:** `esp32/firmware/main/tivoo_frame_stream.[ch]`, `control_bridge.[ch]`, `network_listeners.c`, `tests/esp32/test_p5b3_control_bridge.py`, `esp32/tests/p5b3_control_simulator/control_host.c`.

1. Write host-simulator tests first for split 0x69/0x96 commands, split Tivoo frames, coalesced frames, adjacent commands/frames, embedded 0x69/0x96 in a frame payload, malformed starts/checksums, extra TCP clients, and parser reset on TCP disconnect without SPP disconnect.
2. Port the upstream `getFrameSize`, `isFramePending`, and `appendFrames` frame-boundary/checksum/escape implementation with its 4608-byte buffer and MIT copyright/license header. Do not substitute a single-recv frame parser.
3. Add a byte-at-a-time command/frame demultiplexer. Fixed control commands require exactly seven accumulated bytes. Once a frame starts, control opcode bytes inside it are data until the upstream parser finishes the frame. Because the upstream generic append callback also forwards unframed data and its pending threshold is two bytes larger than a minimum 2-byte-checksum frame, correct the pending minimum and revalidate that each handler input is exactly one valid checksummed Tivoo frame before SPP enqueue. Unknown starts/checksum-invalid candidates fail closed and report the existing `tcp_control_malformed` / `tivoo_frame_malformed` error codes.
4. Hand complete operations to the SPP request interface in TCP receive order. On control client disconnect, clear only parser buffers; never enqueue SPP disconnect as a side effect.
5. Integrate the parser with listener endpoint 7777 while retaining the existing one-client listener policy.

**Expected:** `.venv/bin/python -m pytest tests/esp32/test_p5b1_network_listeners.py tests/esp32/test_p5b2_diagnostics.py tests/esp32/test_p5b3_control_bridge.py -q` passes; 7778 regression tests remain unchanged.

## Task 3 — Bluedroid SPP initiator, GAP policy and NVS bond safety

**Files:** `esp32/firmware/main/tivoo_spp.[ch]`, `tivoo_spp_session.[ch]`, `bt_security_policy.[ch]`, `wifi_station.[ch]`, `main.c`, `CMakeLists.txt`, `tests/esp32/test_p5b3_session.py`, `tests/esp32/test_p5b3_security.py`.

1. Write mock-GAP policy tests first: explicit IO_CAP_NONE, Legacy PIN replies (16 ASCII zeroes or 1234), rejection of SSP CFM_REQ and KEY_REQ, ignoring KEY_NOTIF without exposing passkeys, AUTH_CMPL target-address matching and success/failure state, and bond-list membership by address only.
2. Implement a small platform-independent GAP policy module driven by a callback table so production uses ESP-IDF GAP reply APIs and host tests use recording mocks.
3. Implement a single FIFO SPP worker with a bounded 32-item queue. Keep worker/session policy in `tivoo_spp_session.[ch]` behind a small callback table so host mocks verify peer switching (including same-MAC reconnect), FIFO order, 330-byte chunk boundaries, per-chunk WRITE completion, 15 ms frame pacing, and disconnect ordering. The IDF backend owns SDP discovery, SCN-1 fallback, master-role connect with AUTHENTICATE|ENCRYPT, auth+OPEN gating, bond-list confirmation, CONG/WRITE waits and 500 ms open settle. Keep all Bluetooth waits outside the TCP listener task.
4. Initialize Controller/Bluedroid, explicitly set IO_CAP_NONE, register GAP/SPP callbacks, and call `esp_spp_enhanced_init()` in callback mode. Do not start any device inquiry or BLE scan.
5. Remove automatic whole-NVS erase from `initialize_nvs()`. Make NVS initialization a non-destructive prerequisite before Bluetooth initialization; propagate failure and do not initialize Bluetooth or Wi-Fi after NVS initialization fails.
6. Compile production firmware with IDF v6.1. Host mock tests prove policy callbacks, FIFO SPP backend calls and bond behavior; physical pairing remains P5b4.

**Expected:** focused `.venv/bin/python -m pytest tests/esp32/test_p5b3_security.py -q` passes and `idf.py build` succeeds for `IDF_TARGET=esp32`.

## Task 4 — End-to-end contract verification and batch record

**Files:** firmware README, P5b3 implementation plan/progress ledger, P5b3 implementation report, tests touched by integration.

1. Run focused Python codec/transport tests, POSIX parser/SPP-session/GAP-security tests, and all P5b1/P5b2 regressions.
2. Run full HA/ESP32 test group, Ruff format/check for changed Python, `git diff --check`, and fresh IDF build.
3. Review C09–C12/C22–C25 and P5b3 exit criteria line-by-line; verify IDF receive buffer uses `CONFIG_LWIP_TCP_MSS`, no fixed MAC, no device scans, no key/PIN logging, no SPP reverse channel, and no NVS erase path. Confirm BlueDroid's native BR/EDR Link Key path persists through its NVS config backend.
4. Write README instructions and a report separating automated evidence from P5b4 physical acceptance. Record firmware size/memory/build result and pin the IDF source path proving native bond persistence.
5. Perform a separate self-review of the final diff (no reviewer subagent tool is available). Commit only P5b3 changes. Leave the branch unmerged and unpushed.

**Expected:** all required local test groups and IDF build are green, report explicitly states board was not flashed and P5b4 remains responsible for device acceptance.
