# P6.5b4 HTTP TTS Proxy 消费端断开对照组实施计划

> 使用 Superpowers 的执行计划与 TDD 工作方式；P6.5 patch 保持权威，b4 只补充该批次的测试证据。

**Goal:** 区分“关闭已建立的 HTTP TTS Proxy GET”与“取消 Assist Pipeline”两种事件，观察 TTSCache producer、文本流、HA Wyoming writer 和 P7A 请求的生命周期。

**Architecture:** 复用 b1/b2/b3 的真实 HA Core 2026.11.0 Pipeline、TTS Proxy、Wyoming Provider 与 P7A TCP handler；继续使用可控 AstrBot SSE 和 fake Sherpa model。先建立活动 GET 并关闭客户端响应，在 Pipeline 仍运行时用 callback/generation 事件确认上游继续工作；然后取消公开 Satellite 入口的外层 task，再采集第二组状态。

**Global constraints**
- 仅修改集成测试与批次文档，不修改 HA Core、Tivoo、AstrBot、Sherpa/Wyoming 或 ESP32 生产代码。
- Pipeline 必须通过 AssistSatelliteEntity.async_accept_pipeline_from_satellite() 启动；仅测试公开 caller task 的取消传播，不直接取消内部 task。
- HTTP 消费端断开前后和 Pipeline 取消前后都要有显式事件/任务状态证据，不用固定 sleep 推断时序。
- 真实 HA Pipeline/TTS Proxy/Wyoming Provider/P7A handler；AstrBot SSE 和模型推理由本地 fake 控制。
- 不连接 NAS/ESP32，不部署、刷写或重启外部服务。

## Task 1 — HTTP GET disconnect vs Pipeline cancellation
**Files**
- Modify: tests/homeassistant/test_assist_pipeline_tts_cancellation.py
- Create: docs/superpowers/reports/2026-11-13-p6-5b4-http-consumer-disconnect.md
- Modify: README.md P6.5 状态索引
- Create: .superpowers/sdd/2026-11-13-p6-5b4-http-consumer-disconnect/progress.md

**Test requirements**
- [x] 建立真实流式 Pipeline、TTSCache producer、HA Wyoming writer、P7A TTS request 和 HTTP Proxy GET；确认 GET 已收到音频首字节。
- [x] 仅关闭 HTTP GET 客户端响应；服务端 Proxy stream 退出有明确证据。
- [x] Pipeline caller、Pipeline task、TTSCache producer、文本 generator、Wyoming writer 与 P7A handler/request/input/worker 的断开后状态均被检查。
- [x] 在 GET 已断开且 Pipeline 仍运行时，释放首个 callback 并确认后续 TTS generation/callback 仍发生；此时不得触发 AstrBot Stop。
- [x] 再取消公开 Satellite caller；确认 caller/Pipeline/SSE/Stop/token 状态变化，并确认脱离 Pipeline 的 TTS producer/Wyoming/P7A owner 状态没有被 HTTP 断开或 Pipeline 取消自动回收。
- [x] finally 显式清理本测试创建的遗留任务与本地服务，确保测试隔离。
- [x] 运行聚焦测试、HA 全量测试、P3 Conversation 回归、Sherpa/Wyoming 全量测试、Ruff/format、py_compile 与 diff check。
- [x] 写报告并更新 README：b4 结果单独记录，b5 和 P6.5 整体仍未完成。
- [x] 自查改动范围，仅提交 b4 文件；不合并、不推送。

**Expected result:** HTTP GET disconnect completes only the consumer response iterator; the Pipeline and upstream generation remain active. A later Pipeline cancellation affects the caller/Pipeline/P3 session path but does not reclaim detached TTS producer and Wyoming/P7A tasks. This is evidence for b5, not a production fix.
