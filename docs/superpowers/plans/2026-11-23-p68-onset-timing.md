# P6.8 Speech Onset Timing Implementation Plan

> **ARCHIVED / 历史轨迹（2026-11-26）**：本计划已退出活动开发，不再是 backlog、发布门禁或后续执行入口。`[x]` 仅表示已有实现、测试、报告或部署证据；未勾选项表示当时未执行、被后续架构替代，或因复现成本/发生概率不值得主动验收。若实际使用暴露问题，再建立专用分支与针对性计划处理。当前文档入口见 [文档地图](../../README.md)。


> **For agentic workers:** Use superpowers:executing-plans inline, task by task. The user has authorized this diagnostic experiment and its evidence-driven follow-up in the existing chat.

**Goal:** Identify the blocking boundary during real wake → prompt → command, then validate the smallest fix supported by the trace.

**Architecture:** Temporarily record bounded metadata in PSRAM with one esp_timer microsecond clock. Four owners (capture, feed, fetch/session, diagnostics TX) append fixed-size records; no PCM, allocation, JSON, or console output in the record path. Export once after the five-second observation window and a three-second quiet delay. Remove the probe from the retained production change.

**Tech Stack:** Existing ESP-IDF 6.1 / ESP-SR 2.6.1 / C and host Python.

**Spec:** User-approved approach in this chat: measure fetch-return-to-next-fetch, local turn/history work, vendor feed plus capture queue depth, enqueue-to-send latency. Only if confirmed, isolate the fetch/session boundary with bounded owned PCM.

## Global Constraints

- Existing dirty feature checkout is the real hardware reproduction baseline. Back up edited files; preserve all earlier user changes; do not create an unrelated clean-HEAD firmware.
- Keep priorities, cache, compiler optimization, models, reference, calibrated prompt values, all authorization gates and hardware wiring unchanged for the measurement.
- Record durations as wall time including scheduling, not CPU cost. Measure worker scheduling gaps separately from mutex waits and socket send duration.
- One bounded capture after the first authorized physical wake per boot; record saturation/truncation explicitly. Do not claim complete coverage on overflow.
- No PCM content, credentials, temporary waveform injection or gate bypass. Preserve UUID/epoch/FIFO behavior.
- Keep app-only flash with NVS/model partitions intact. Retain verified original app for rollback.

## Review Focus

1. Incomplete export must never become a diagnosis: parser rejects missing END or missing records.
2. Overflow must remain visible: parser rejects dropped records as complete timing coverage.
3. Interleaved owners/overlapping intervals are legal: sort by timestamp, do not infer sequence from export order.
4. Wall-time intervals include preemption: report observed durations without labeling them CPU runtime.
5. Instrumentation perturbation: capture callback has bounded record work and no synchronous logging; evaluate idle continuity before one real command.

### Task 1: Bounded instrumentation and decoder

**Files:** temporary main/p68_timing_probe.h; main/diagnostics.c; main/s3_afe.c; main/s3_local_turn.c; scripts/read-p68-timing.py; tests/esp32/test_p68_timing_log.py.

**Interfaces:** `tivoo_timing_arm(void)`, `tivoo_timing_record(unsigned kind, uint64_t at_us, unsigned duration_us, unsigned a, unsigned b)`; host/legacy stubs. Decoder consumes P68TIME BEGIN/DATA/END metadata lines, outputs JSON timing summaries and typed intervals.

- [x] Write parser tests for complete/out-of-order intervals, missing tail, dropped records, count mismatch and long TX wait with short send duration; run RED.
- [x] Implement parser; run GREEN.
- [x] Back up the exact current source and sdkconfig. Add RAM-only probes at capture queue delivery, feed read/feed call, fetch call/app gap/flow callback, turn tick/event, enqueue/pop/send, TX mutex/scheduling gap. Preserve all behavior.
- [x] Build incrementally without touching CMake or sdkconfig; run affected host tests and diff check. Archive temporary patch plus firmware hash.

### Task 2: Physical feedback loop and ruling

**Files:** evidence/2026-11-23-p68-onset-timing/* and this plan's progress ledger.

- [x] Verify NAS port mapping and no serial reader, upload app and flash/hash verify.
- [ ] Capture boot/idle counters; then ask for one physical wake and command while the bounded trace is armed.
- [x] Decode after export. Correlate callback duration, feed service, queue depth, message residence, mutex wait and send completion on the same clock.
- [x] Record whether history/session synchronous work is the primary blocked boundary, scheduling alone dominates, or another concrete boundary is supported. Never infer CPU saturation from wall time alone.
- [x] If the approved hypothesis is confirmed, implement the smallest bounded ownership separation with regression coverage at the actual callback seam; keep wire/physical gates unchanged. Otherwise record the evidenced next investigation and do not implement a speculative task split.
- [x] Remove temporary probes; verify source cleanup and appropriate tests. Restore original app unless a new candidate is verified. Report remaining actual hardware gaps honestly.

## Execution rulings

- Inline execution and continuing this existing feature checkout follow the user's repeated authorization in this chat; no new worktree/plan approval round is needed for the approved measurement.
- A short-lived diagnostic probe is not a product feature; production commits are deferred until a measured fix exists, to avoid committing earlier user work or temporary instrumentation.


## Execution result — 2026-11-23

The user subsequently requested an automated reproduction without speaking. The physical-wake step above was therefore not claimed as completed. A one-shot synthetic wake/VAD trigger was used only to exercise the real calibrated prompt, dual-mic I2S, ESP-SR enhanced PCM, 7778 transport, HA and Qwen path.

The trace localized the first failure to the bounded realtime TX queue/worker rather than I2S or AFE. The verified retained fix separates realtime TX from the diagnostic worker, uses a 64-frame bounded queue with MIC payloads in PSRAM, and rejects full-queue retries before allocation/copy. Temporary timing probes and all automatic trigger code were removed from the retained firmware.

The final normal app passed the strict 60 s AFE continuity gate and the ESP32 suite (146 passed). Full evidence and the priority/affinity exclusion matrix are in [2026-11-23-p68-uplink-backpressure-fix.md](../reports/2026-11-23-p68-uplink-backpressure-fix.md).
