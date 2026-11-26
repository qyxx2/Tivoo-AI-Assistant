# P6.5b3 TTS Proxy 活动期间取消实施计划

> **ARCHIVED / 历史轨迹（2026-11-26）**：本计划已退出活动开发，不再是 backlog、发布门禁或后续执行入口。`[x]` 仅表示已有实现、测试、报告或部署证据；未勾选项表示当时未执行、被后续架构替代，或因复现成本/发生概率不值得主动验收。若实际使用暴露问题，再建立专用分支与针对性计划处理。当前文档入口见 [文档地图](../../README.md)。


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 通过真实 HA Core 2026.11.0 流式 TTS 路径验证 Satellite 外层 Pipeline 取消时 TTS Proxy producer、文本 generator、Wyoming writer/连接及 P7A 请求/session/worker 的实际生命周期。

**Architecture:** 复用 b1/b2 集成夹具、HA Wyoming Provider 和项目 P7A Wyoming TCP handler；仅扩展本地 fake Wyoming 测试服务器以提供 callback 屏障和任务快照。使用 fake AstrBot SSE 长文本触发 TTS Proxy，HTTP GET 读取 streaming WAV header 后取消外层调用 task，并验证取消后旧文本流是否还能推进。

**Tech Stack:** HA Core 2026.11.0 / Python 3.14 `.venv`、aiohttp/pytest、P7A Wyoming Python 3.11 `.venv-sherpa`。

**Spec:** `docs/superpowers/patches/2026-11-11-p6-5-ha-cancellation-preflight.patch.md` §P6.5b3；任务 owner 基线 `docs/superpowers/reports/2026-11-13-p6-5b0-cancellation-task-ownership-inventory.md`；b1/b2 控制与取消报告。

## Global Constraints

- 仅做 P6.5b3 测试验证与文档记录；不修改 HA Core、Tivoo/AstrBot、Sherpa/Wyoming 或 ESP32 生产代码。
- 必须通过 `AssistSatelliteEntity.async_accept_pipeline_from_satellite()` 的公开入口启动与取消外层 task。
- HA Pipeline、TTS Proxy、Wyoming Provider 和 P7A TCP handler 使用真实代码；仅 AstrBot HTTP/SSE 与模型推理使用可控 fake。
- 使用 `asyncio.Event`/明确任务状态控制时序，不用固定 sleep 猜测时序。
- 区分 token 删除、HTTP consumer 断开、后台 TTS producer 结束和 Wyoming/P7A 请求结束。
- 不连接 NAS、真实 ESP32、麦克风或 DAC；不部署、不刷写、不重启外部服务。

## Review Focus

- 已经打开的 Proxy GET 在 token 被 Pipeline cleanup 删除后是否继续持有并读取原 ResultStream。
- Pipeline 取消时文本 generator 及其 queue 是否仍处于等待状态。
- TTSCache producer 与 HA Wyoming writer 是否仍 pending，及其真实生命周期 owner。
- P7A 连接 handler、request/input/worker task 和线程 callback 的取消边界是否与 HTTP 断开同步。
- 取消后向旧文本 queue 输入新文本，是否仍产生迟到 PCM/音频事件。

---

### Task 1: TTS Proxy 活动期间取消生命周期测试

**Files:**
- Modify: `tests/homeassistant/test_assist_pipeline_tts_cancellation.py`
- Modify: `tests/helpers/p6_5_fake_wyoming_server.py`（只增加测试控制端口、callback barrier 和 task snapshot）
- Create: `docs/superpowers/reports/2026-11-13-p6-5b3-tts-proxy-active-cancellation.md`
- Modify: `README.md` P6.5 阶段索引，仅记录 b3 结论，b4/b5 及整体阶段仍 pending。
- Create: `.superpowers/sdd/2026-11-13-p6-5b3-tts-proxy-active-cancellation-implementation-plan/progress.md`

**Interfaces:**
- Reuse `P65ControlSatellite`, `LONG_ANSWER`, `_free_port`, fake AstrBot `/api/v1/chat` and `/stop`, and the real public Satellite Pipeline entrypoint.
- Extend fake P7A server with optional `--control-port` and `--hold-first-tts-callback`; a JSON-line `status` command returns active handler/request/input/worker task states, and `release_tts` releases the blocked first model call.
- Trace callback start/release and each TTS generation so post-cancellation stale text can be observed deterministically.

- [x] Write `test_cancel_during_active_tts_proxy_tracks_all_owners`: emit a long SSE response, wait for the streaming cache producer and Wyoming/P7A callback barrier, start `/api/tts_proxy/{token}` and read its first byte, then cancel the outer Satellite caller.
- [x] Run the focused test and observe the expected failure before adding helper support/remaining assertions.
- [x] Add the smallest test-only helper control/barrier/snapshot interface needed to expose P7A's actual active tasks; keep existing b1/b2 helper behavior unchanged by default.
- [x] Assert the caller/Pipeline cancellation result, SSE close and one matching Stop; snapshot the ResultStream/token, cache producer, text generator/queue, active HTTP consumer, HA Wyoming writer, and P7A tasks/callback before test cleanup.
- [x] After cancellation, release the fake model callback and place text on the captured old stream queue; record that the existing producer/writer/request generates another model call and PCM callback.
- [x] Explicitly clean test-only leaked tasks/connections and prove test services/processes close; do not add production cancellation logic.
- [x] Run focused b3/b1/b2 tests (3 passed), P3 Conversation regression (12 passed), full HA tests (320 passed), full Sherpa/Wyoming tests (128 passed), Ruff/format checks, and `git diff --check`.
- [x] Write the b3 report with exact observed task states, owners, trace ordering, late-data behavior, commands and test counts; update README without declaring b4/b5 or P6.5 complete.
- [x] Perform a separate self-review of the P6.5b3 diff; commit only b3 test/helper/plan/report/README changes locally; leave branch unmerged and unpushed.

**Expected:** The run reaches a real active HA TTS Proxy GET and a real P7A streaming TTS connection before cancellation. The report distinguishes every task's `done/cancelled/pending` state and records the owner and late-text/PCM outcome. A detected cancellation gap is a valid b3 finding; production code remains untouched.
