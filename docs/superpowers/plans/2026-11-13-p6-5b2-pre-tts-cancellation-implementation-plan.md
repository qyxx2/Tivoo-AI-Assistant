# P6.5b2 TTS 开始前取消实施计划

> **ARCHIVED / 历史轨迹（2026-11-26）**：本计划已退出活动开发，不再是 backlog、发布门禁或后续执行入口。`[x]` 仅表示已有实现、测试、报告或部署证据；未勾选项表示当时未执行、被后续架构替代，或因复现成本/发生概率不值得主动验收。若实际使用暴露问题，再建立专用分支与针对性计划处理。当前文档入口见 [文档地图](../../README.md)。


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 通过真实 HA Core 2026.11.0 Assist Pipeline 验证 TTS 启动前取消时，外层 Satellite 调用任务、HA Pipeline task 和 P3 AstrBot SSE/Stop 的取消收尾。

**Architecture:** 复用 P6.5b1 的测试 Satellite、HA Wyoming Provider 与本地真实 P7A Wyoming handler；AstrBot SSE 使用本地可控 aiohttp 服务。SSE 发送并确认 session_id 后保持打开，测试取消调用公开 Satellite 入口的外层 task，再追踪 Pipeline task、SSE reader、Stop 与所有尚未启动的 TTS 资源。

**Tech Stack:** Python 3.14 HA test venv、Home Assistant Core 2026.11.0、aiohttp、pytest-asyncio、Python 3.11 Sherpa/Wyoming test venv。

**Spec:** `docs/superpowers/patches/2026-11-11-p6-5-ha-cancellation-preflight.patch.md` §P6.5b2；任务所有权基线见 `docs/superpowers/reports/2026-11-13-p6-5b0-cancellation-task-ownership-inventory.md`；正常完成对照见 `docs/superpowers/reports/2026-11-13-p6-5b1-normal-completion-control-group.md`。

## Global Constraints

- HA Core 测试基线固定为 2026.11.0。
- 本批只验证，不修改 `homeassistant/custom_components/tivoo/`、AstrBot、HA Core、Sherpa 或 ESP32 生产逻辑。
- 取消必须由调用方取消 `async_accept_pipeline_from_satellite()` 外层 task 触发；不得直接取消内部 `_pipeline_task`。
- HA Assist Satellite、Pipeline、Wyoming Provider 和项目 P7A handler 必须使用真实代码；AstrBot HTTP/SSE 与推理模型可使用本地 fake。
- 使用 `asyncio.Event` 和显式 task 状态作为时序屏障；不以固定 sleep 推断进入/退出状态。
- TTS 尚未开始的判定要区分 Pipeline 预先分配的惰性 ResultStream token 与真正启动的 TTSCache producer / HTTP Proxy response / Wyoming TTS request。
- 不连接 NAS、ESP32、麦克风或 DAC；不部署、不刷写、不重启设备或服务。

## Review Focus

- 外层 Satellite task 被取消后，内部 HA Pipeline task 必须完成且处于 cancelled 状态，外层 `CancelledError` 必须继续传播。
- SSE 的 session_id 必须先由 P3 Conversation Agent 解析并确认；响应在取消发生前一直保持打开。
- Stop 请求必须使用当前 SSE 对应的同一个 session_id，且应在 SSE response reader 关闭后只调用一次。
- Pipeline 取消清理已预分配的 ResultStream token；不得创建 TTSCache producer、Wyoming TTS writer、P7A TTS request 或 TTS_START 事件。
- 测试服务释放屏障后能结束 handler；所有临时 task 和子进程均得到清理。

---

### Task 1: P6.5b2 外层取消与 TTS 未启动控制组

**Files:**
- Modify: `tests/homeassistant/test_assist_pipeline_tts_cancellation.py`
- Create: `docs/superpowers/reports/2026-11-13-p6-5b2-pre-tts-cancellation.md`
- Modify: `README.md` P6.5 阶段状态索引（只更新 b2 证据，不把 P6.5 标为完成）
- Create: `.superpowers/sdd/2026-11-13-p6-5b2-pre-tts-cancellation-implementation-plan/progress.md`

**Interfaces:**
- Use inherited `AssistSatelliteEntity.async_accept_pipeline_from_satellite()` as the only Pipeline entrypoint.
- Use the registered `conversation.astrbot` entity and its configured `AstrBotSessionManager`; pause the local `/api/v1/chat` SSE response after the session_id event.
- Capture Config Entry background task named `<entity_id>_pipeline`, TTS Manager ResultStream/cache registration, and Wyoming Config Entry task name `wyoming tts write`.
- The fake P7A server is `tests/helpers/p6_5_fake_wyoming_server.py`; no TTS request should reach its real `WyomingEventHandler` during this batch.

- [x] Add one integrated cancellation test with event barriers: wait for P3 to confirm the SSE session_id, cancel the outer Satellite caller task, and assert the expected cancellation propagation and ordering.
- [x] Run the focused test and inspect all task/trace evidence; record any observed GAP without changing production behavior.
- [x] Run P3 Conversation regression, HA test directory, and Sherpa/Wyoming test suite in their compatible virtual environments.
- [x] Run HA/Sherpa Ruff checks and format checks plus `git diff --check`.
- [x] Write the b2 report with exact commands, counts, task states, SSE/Stop order, token cleanup, and TTS-not-started evidence.
- [x] Update README to record b2's actual outcome while keeping b3–b5 and the overall P6.5 stage pending.
- [x] Review the diff, commit only P6.5b2 test/plan/report/README changes locally on `feature/p6-5-ha-cancellation-preflight`.

**Expected:** The public caller is cancelled with `CancelledError`; its HA Pipeline task is done/cancelled; P3 SSE reader closes before exactly one Stop call for the same confirmed session_id; the pre-created ResultStream token is removed; no TTS cache producer, TTS writer, P7A TTS connection/request, or `TTS_START` event is created. The fake service remains listening and no production module changes are made.
