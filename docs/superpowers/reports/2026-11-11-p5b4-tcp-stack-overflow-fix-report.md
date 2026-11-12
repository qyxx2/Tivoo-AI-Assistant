# P5b4 TCP Task Stack Overflow Root-Cause and Fix Report

**Date:** 2026-11-11  
**Branch:** `feature/p5-esp32-minimal-firmware`  
**Base commit:** `95cfb43` (local fix is not committed)  
**Target:** ESP32 / ESP-IDF v6.1 / WROVER-E, 16MB flash, 8MB PSRAM

## 1. Result

The reset loop reported by the physical UART log is caused by a stack overflow in the `tivoo_tcp` FreeRTOS task after Wi-Fi obtains an IPv4 address. The source of the excessive stack use was identified in the compiled production code and fixed.

The fix moves the TCP receive buffer out of `check_client()`'s task stack and makes the two sequentially serviced TCP endpoints share one buffer. The P5b0–P5b4 host regression set passes, and the ESP-IDF production firmware builds successfully. Physical-board confirmation after flashing this fix remains pending.

## 2. Evidence and root cause

The supplied UART log shows this order:

1. Bluetooth controller and SPP initiator initialize.
2. Wi-Fi connects to the configured AP and obtains `192.168.3.27`.
3. `tivoo_wifi: station_connected` is emitted.
4. FreeRTOS reports `A stack overflow in task tivoo_tcp has been detected` and the device reboots.
5. The same sequence repeats after reboot.

The ELF SHA256 prefix printed by the board was `55e15b1a6`. The development workspace's pre-fix `tivoo_firmware.elf` had SHA256 `55e15b1a634bf300d9543c4502f4c952533cbe82b6b9890c7336b867c4fed77c`, proving it was the matching ELF for symbol analysis.

The supplied backtrace resolves to `panic_abort`, `esp_system_abort`, `vApplicationStackOverflowHook`, `vTaskSwitchContext`, `_frxt_dispatch`, and `_frxt_int_exit`. Since the captured trace is the overflow hook path, it does not retain the original application callsite; the matching ELF disassembly was therefore used to locate the excessive frame.

Before the fix, the Xtensa disassembly of `check_client()` began with:

```text
entry a1, 0xb60
```

`0xB60` is 2,912 bytes. `TCP_RECV_BUFFER_SIZE` is configured as `CONFIG_LWIP_TCP_MSS`, which is 1,440 bytes. `check_client()` had one 1,440-byte local array in the diagnostic endpoint branch and another 1,440-byte local array in the control endpoint branch. The compiler allocated both branch-local arrays in the function frame instead of reusing the same stack space.

The parent frames also consume stack (`poll_listeners`: 64 bytes; `listener_worker`: 112 bytes; `listener_task`: 32 bytes), before considering the nested lwIP `select()` / `recv()` path. The listener task was created with a 4,096-byte stack. The 2,912-byte `check_client()` frame alone left too little headroom for this call path.

This explains the timing: the task only reaches `select()` and `recv()` processing once the Wi-Fi GOT_IP event enables the listeners, immediately before the repeated overflow.

## 3. Production fix

Changed `esp32/firmware/main/network_listeners.c`:

- Added one file-scope `s_receive_buffer[TCP_RECV_BUFFER_SIZE]`.
- Removed both branch-local 1,440-byte arrays from `check_client()`.
- Both endpoint paths now call `recv()` into the same buffer and pass it to their existing data handlers.

This is safe for the existing design: one `tivoo_tcp` worker iterates the two endpoints sequentially; `check_client()` is not executed concurrently for the two endpoints. Both data consumers process the supplied bytes synchronously: the diagnostics handler copies them into its own `s_rx_buffer`, while the control bridge consumes the byte stream and copies parser state into its own storage. Neither retains the receive-buffer pointer after returning. The new symbol is located at `0x3ffc46cc` in the ESP32 internal DRAM `.bss` region, rather than the task stack. No TCP protocol, receive size, or data handler behavior was changed.

Post-fix disassembly reports:

```text
entry a1, 32
```

The `check_client()` frame fell from 2,912 bytes to 32 bytes, a reduction of 2,880 bytes. The 1,440-byte receive storage now occupies static memory once, instead of consuming two such arrays in the TCP task frame.

## 4. Test harness synchronization correction

The existing P5b4 SPP queue-failure test sent the simulator's `fail_next_frame` command and immediately sent a TCP frame. The host simulator processes stdin on its main thread, while the TCP listener has a separate worker thread. Without an acknowledgement, the listener could receive the frame before the main thread enabled the failure injection, causing a nondeterministic false failure.

The host simulator now emits and flushes `COMMAND fail_next_frame` after enabling the one-shot failure flag. The test waits for that acknowledgement before sending the TCP frame. This changes only the POSIX test harness, not firmware behavior.

## 5. Verification

- The new regression assertion failed against the pre-fix source because the shared static buffer did not exist.
- P5b4 integration tests after the production fix and test harness synchronization: **4 passed**.
- Complete P5b0–P5b4 test file set: **26 passed**.
- Broader P5b1–P5b4 plus HA Tivoo regression suite: **183 passed, 7 warnings in 31.01s**.
- Ruff check: passed for the two changed Python test files.
- Ruff format check: passed for the two changed Python test files.
- `git diff --check`: passed.
- ESP-IDF v6.1 production build completed all 1,635 Ninja steps successfully for `CONFIG_IDF_TARGET="esp32"` and `CONFIG_LWIP_TCP_MSS=1440`.
- Generated app image: 1,255,104 bytes; app partition: 8 MiB; partition size check passed.
- Post-fix ELF SHA256: `6e8a357eb90e6a1f815d5dbd3dd3ee2b4765669ae2bd34053dbd594b5e35e737`.
- Post-fix app image SHA256: `a9a63d8f16fc4dc49d41e548205301a5dcb2dca904505807c67732fe3df9ca80`.
- App-only update package: `esp32/firmware/build/p5b4-tcp-stack-fix/tivoo-esp32-app-p5b4-tcp-stack-fix-95cfb43.bin`, flash offset `0x010000`, size 1,255,104 bytes.
- Package manifest SHA256: `f7bd55bbf29627cd9facb544038e76b7cf9a14532bba74509d4dc0345d55cf39`.
- The on-device firmware version string remains `0.1.0+95cfb43` because the base branch commit was not changed; the new build is distinguished by its UART ELF SHA256 prefix `6e8a357eb9` and the app image SHA256 above.

## 6. Physical verification still required

The development workspace does not have the user board attached, so this fix has not yet been physically flashed or observed on the device. Do not report the hardware reset loop as resolved on-board until the user flashes the app-only image and the UART confirms:

- Wi-Fi obtains an IP address.
- No `stack overflow in task tivoo_tcp` appears during startup or continued operation.
- HA 7777 and 7778 connections remain connected.
- The 7778 TVIO HELLO/ACK handshake succeeds and diagnostics remain available.

After TCP stability is demonstrated, resume the P5b4 Bluetooth authentication, real Tivoo command, Bond Key software-restart, and full power-cycle acceptance items from the original P5b4 report.

For an already initialized or paired board, update only the factory application at offset `0x010000`. Do not erase flash/NVS and do not use the 16MB merged image for this routine update, because that image overwrites NVS and Bluetooth Bond Keys. The image hash and exact path are recorded in the generated stack-fix package under `esp32/firmware/build/`.

## 7. Scope and repository state

No P5 contract, batch definition, Home Assistant integration, TCP protocol, Bluetooth security policy, or later P6/P7 work was changed. The firmware source fix, regression assertions, P5b4 simulator synchronization, and this report are local changes on the existing P5 branch. No merge or push was performed.
