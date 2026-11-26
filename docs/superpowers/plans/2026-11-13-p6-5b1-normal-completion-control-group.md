# P6.5b1 正常完成控制组实施计划

> **ARCHIVED / 历史轨迹（2026-11-26）**：本计划已退出活动开发，不再是 backlog、发布门禁或后续执行入口。`[x]` 仅表示已有实现、测试、报告或部署证据；未勾选项表示当时未执行、被后续架构替代，或因复现成本/发生概率不值得主动验收。若实际使用暴露问题，再建立专用分支与针对性计划处理。当前文档入口见 [文档地图](../../README.md)。


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 通过真实 HA Core 2026.11.0 Pipeline 与 TTS Proxy，建立 AstrBot SSE → Wyoming → P7A TTS 正常完成的任务生命周期基线。

**Architecture:** 测试 Satellite Entity 只调用 HA 基类公开的 `async_accept_pipeline_from_satellite()`。HA Wyoming 集成连接本地子进程启动的真实 P7A `WyomingEventHandler`，外部 AstrBot HTTP/SSE 和 Sherpa 模型由可控 fake 替代。使用 trace 记录任务结束、generator 关闭、TTS 缓存 producer 完成和无取消/Stop 的证据。

**Tech Stack:** Python 3.14 HA pytest environment, Python 3.11 Sherpa/Wyoming test service, aiohttp, pytest-asyncio.

**Spec:** `docs/superpowers/patches/2026-11-11-p6-5-ha-cancellation-preflight.patch.md` §P6.5b1；环境与 owner 清点见 `docs/superpowers/reports/2026-11-13-p6-5b0-cancellation-task-ownership-inventory.md`。

## Global Constraints

- HA Core 测试基线固定为 2026.11.0。
- P6.5b1 只验证正常完成，不实现取消传播或修改生产代码。
- Pipeline 必须从公开 `AssistSatelliteEntity.async_accept_pipeline_from_satellite()` 入口启动。
- HA Pipeline/TTS Proxy/Wyoming Provider 与项目 P7A handler 使用真实代码；AstrBot API 和推理模型可使用本地 fake。
- 任务同步使用事件/协议完成信号，不以固定 sleep 推断完成。
- 正常完成不得误调用 AstrBot Stop；不连接 NAS/ESP32，不部署服务。

## Review Focus

- SSE 正常 end 已发送但 HTTP reader 未关闭：必须确认 generator 与 transport 收尾。
- 大段流式文本触发 TTS 后，在 HTTP GET 前后缓存 producer 的任务状态。
- TTS Proxy GET 读取期间验证完整音频及最终缓存结果。
- Wyoming SynthesizeStop 正常到达后，写入 task、P7A input/worker task 与 handler connection task 均结束。
- P7A 正常 cleanup 会设置内部协作停止 Event；不得把该 Event 单独解释为用户取消。

---

### Task 1: P6.5b1 正常完成生命周期控制组

**Files:**
- Create: `tests/homeassistant/test_assist_pipeline_tts_cancellation.py`
- Create: `tests/helpers/p6_5_fake_wyoming_server.py`
- Create: `docs/superpowers/reports/2026-11-13-p6-5b1-normal-completion-control-group.md`
- Modify: `README.md` P6.5 阶段状态索引（只更新 b1 结果，不标记整个 P6.5 完成）

**Interfaces:**
- Test server starts `services/sherpa_wyoming/run.py:run_server()` using `ServiceConfig`, `ModelBundle`, fake KWS/STT/TTS model instances.
- Test Satellite subclass calls the inherited public `async_accept_pipeline_from_satellite(audio_stream, start_stage=PipelineStage.STT, end_stage=PipelineStage.TTS, context=...)`.
- HA pipeline uses a real `Pipeline` with the registered Wyoming STT/TTS entity IDs and `conversation.astrbot`.

- [x] Write one integrated normal-completion test. Assert Pipeline RUN_END, successful AstrBot SSE end, zero Stop calls, HTTP TTS Proxy 200 with complete WAV bytes, completed TTSCache producer, exhausted streaming text generator, completed HA Wyoming writer task, P7A input/worker/session cleanup, non-cancelled request task and finished connection handler.
- [x] Run the test and inspect the first failure.
- [x] Add the local fake P7A service/trace harness only; do not change production modules.
- [x] Run focused b1 test, then P3 Conversation regression and P7A TTS/server regressions using the patch commands.
- [x] Write report with versions, event/trace evidence, task owner/status and explicit scope exclusions.
- [x] Update README to say b1 control-group PASS while b2–b5 and overall P6.5 remain NOT RUN.
- [x] Run `git diff --check`, review changed files, commit b1 locally.

**Expected:** One stable end-to-end normal-completion control test; every owned task is done, no cancelled task/Stop call is recorded, and audio is fully available through the actual HA TTS Proxy. No cancellation conclusion is made by this batch.
