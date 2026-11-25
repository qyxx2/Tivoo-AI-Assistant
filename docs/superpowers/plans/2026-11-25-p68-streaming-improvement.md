# P6.8 Streaming Improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore incremental Qwen PCM delivery and improve bounded S3 output supply without sacrificing AFE or interruption.

**Architecture:** HA retains stateful incremental 24→32k conversion and writes chunks before audio.done. S3 retains the PSRAM receive ring, uses static binary events for data/space/completion, and uses a DMA event for output queue space. Ordinary output re-enters its existing 120ms prefill after an underrun; clocks and actual TX reference continue through silence.

**Tech Stack:** Python asyncio/aiohttp, ESP-IDF 6.1 C11/FreeRTOS, host C harnesses, pytest.

**Spec:** `docs/superpowers/reports/2026-11-25-p68-streaming-playback-analysis.md`; user authorized implementation based on the investigation.

## Global Constraints

- Work on `feature/p6-8-s3-local-wake`, preserving existing dirty changes; no automatic commit or hardware playback.
- Keep 32kHz mono S16LE, 512KiB receive ring and 400ms initial receive prefill, existing task priorities/affinity and AFE settings.
- Preserve single-use HTTP, owner/generation cancellation, exact final PCM and physical DMA drain.
- Keep ISR work bounded/internal-memory only; diagnostic logging runs in task context.

## Review Focus

- Partial final block and short EOF must flush without waiting for prefill.
- STOP during producer/feeder/output wait must terminate and not leak a task handle.
- Notifications arriving before wait must not be lost; stale notifications must not bypass state checks.
- Rebuffering must preserve samples/order and actual AEC reference, and count inserted silence honestly.
- Provider failure and HTTP disconnect before audio.done must abort the owner and release the handler.

### Task 1: Restore HA incremental delivery

**Files:** `homeassistant/custom_components/tivoo/qwen_realtime.py`, `tests/homeassistant/custom_components/tivoo/test_qwen_realtime.py`.
**Interfaces:** Existing QwenPcmStream.chunks(), TivooQwenPcmView.get(), QwenRealtimeBridge._open_output(). No protocol change.

- [x] Add first-PCM-before-audio.done HTTP test, first playback command before final terminal test, and cancellation while waiting for next chunk.
- [x] Run RED on production classes, then remove body()/finished gates and restore bounded per-write timeout.
- [x] Run Qwen suite and relevant lifecycle/satellite tests.

### Task 2: Event-driven S3 supply and bounded rebuffering

**Files:** `esp32/firmware/main/audio_resource.c`, `audio_output_manager.c/.h`, `audio_capture.c`; `tests/esp32/p68_resource_worker_host.c`, `p68_dma_host.c`, `p68_audio_host.c`, `test_p68_audio.py`, `test_p68_prompt.py`.
**Interfaces:** tivoo_audio_output_dma_sent() returns whether ISR should yield; task-only output progress snapshot exposes queued/missing samples, underrun and recovery counts. Existing playback feed/stop/drain interfaces remain.

- [x] Add behavioral tests proving underrun does not resume fragmented PCM before prefill, EOF drains short remainder, writer waits for the DMA space event, and STOP wakes it.
- [x] Run RED, implement state and waiting flag protected by the existing output lock, and give static-lifetime event objects after releasing the lock; count partial missing blocks as well as full gaps.
- [x] Replace ring data/space/join polling with static binary events and bounded cancellation waits; finish input from feeder immediately after final PCM.
- [x] Extend worker tests for paced streaming, producer backpressure and cancel/error waits; verify sample order and no early completion.
- [x] Add throttled task-context starvation snapshots: receive/output levels, last receive age, feeder gap, missing samples/rebuffer count. Do not log audio or URLs.

### Task 3: Verification and review

- [x] Run ESP32 suite, HA relevant/full suite where environment supports it, lint and diff checks, and build S3 normal firmware.
- [x] Fresh reviewer checks changed code against investigation and cancellation/reference constraints; address material findings with RED/GREEN tests.
- [x] Record exact verification, artifact and unverified hardware limits in a report; leave deployment/physical acoustic claims separate.

## Execution ledger

Ruling: Continue in the user's existing p6.8 workspace instead of creating a new worktree, because its uncommitted changes are the investigation target. Pre-change files copied to `.superpowers/p68-streaming-improvement/before/`.

Ruling: User's request explicitly authorizes implementing the recommendations; proceed inline without another design/plan approval checkpoint. No automatic commits, deployment or device resets are necessary for the requested code improvements.

Pre-flight: Task 1 outputs PCM32k incrementally through the unchanged MIME; Task 2 consumes the same stream. EOF and cancellation remain distinct from a temporary lack of bytes.

Task 1: complete — first-PCM HTTP and first-delta dispatch tests RED→GREEN; 52 Qwen tests passed, then a tool-gap regression RED→GREEN brought the file to53 passing cases.

Task 2: complete — prefill/EOF/sample-order, DMA wake/STOP, forced-full ring wake/STOP and fragment read deadline tests RED→GREEN. Static binary semaphores replace the initial task-handle approach following review.

Ruling: ESP-IDF 6.1 forbids FreeRTOS calls in application critical sections. Stable internal static event storage lets ISR/task signals run after releasing the spinlock, without a task-handle deletion race. The feeder's atomic done store is its last parent-context access; only static completion storage is referenced afterwards.

Ruling: The producer's inter-audio wait uses the existing owner EVENT_TIMEOUT/TURN_TIMEOUT rather than IO_TIMEOUT; actual HTTP writes remain bounded and HA enables handler cancellation on disconnect. Tested a two-response tool gap three times the scaled write timeout.

Ruling: ESP-IDF read() fills its requested length across transport reads. Set only PCM body idle-read timeout to40ms and retry EAGAIN; connect/headers retain existing limits. This is not a hard upper bound on read() wall time.

Review: fresh reviewer found two Important issues above, fixed with failing regression tests; padding-accounting and diagnostic age/write-failure timing findings also corrected. First full ESP32 run163 passed; first full HA681 passed before final review fixes. Final complete checks recorded in the implementation report.

Task 3: complete — final HA/integration694 passed; ESP32166 passed; services140 passed using its existing Python3.11 environment; normal firmware build, Ruff and diff checks pass. One diagnostics reconnect failure in a prior full run is preserved; file-only recheck28 passed, then full clean recheck166 passed. Unified HA-environment collection cannot import Sherpa native dependencies; no global-environment green claim. See `docs/superpowers/reports/2026-11-25-p68-streaming-improvement.md` for artifact SHA and physical-test limits. Keep the user's p6.8 branch/workspace uncommitted and preserve backups; no integration/deployment action requested.
