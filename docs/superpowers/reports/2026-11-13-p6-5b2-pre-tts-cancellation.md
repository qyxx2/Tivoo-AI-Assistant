# P6.5b2 — TTS 开始前取消验收报告

- 日期：2026-11-13
- 分支：`feature/p6-5-ha-cancellation-preflight`
- 基线：`2bc0a2a`（P6.5b1 正常完成控制组）
- 批次：P6.5b2
- 结果：**PASS**
- 范围：仅验证 TTS 开始前取消；未修改生产代码，未执行 P6.5b3–b5。

## 1. 测试环境与方法

| 项目 | 环境/版本 |
|---|---|
| Home Assistant Core | 2026.11.0 |
| HA 测试 Python | 3.14.4（项目 `.venv`） |
| HA aiohttp / pytest | 3.14.5 / 9.0.3 |
| Sherpa/Wyoming Python | 3.11.18（项目 `.venv-sherpa`） |
| sherpa-onnx / wyoming | 2.0.1 / 1.10.2 |

测试从真实 `AssistSatelliteEntity.async_accept_pipeline_from_satellite()` 公开入口运行真实 HA Pipeline、AstrBot Conversation Agent、HA Wyoming Provider 和项目 P7A Wyoming TCP handler。AstrBot HTTP/SSE 使用本地可控 aiohttp 服务，Sherpa 模型使用 fake；没有连接 NAS、真实 AstrBot 实例或 ESP32。

取消屏障设置在 SSE `session_id` 事件被 P3 Conversation Agent 解析并由 `AstrBotSessionManager.async_confirm_session()` 确认之后。服务端保持该 SSE response 打开，测试取消调用公开入口的外层 asyncio task；没有直接取消 HA 内部 `_pipeline_task`。

## 2. 取消链路结果

| 追踪对象 | 实测结果 |
|---|---|
| Satellite 外层调用 task | `cancel()` 后完成，状态 `cancelled=True`；`CancelledError` 原样传播给调用方 |
| HA Satellite `_pipeline_task` | `done=True`、`cancelled=True`；入口 finally 清空 `_pipeline_task` 引用 |
| P3 AstrBot SSE reader | response context manager 已关闭；服务端观察到客户端连接关闭，SSE handler 随后结束 |
| AstrBot session Stop | 精确调用 1 次；Stop 的 session_id 与本轮已确认的 SSE session_id 相同；调用 Stop 时 reader 已关闭且服务端 transport 正在关闭 |
| HA TTS ResultStream | Pipeline 准备阶段曾创建惰性 ResultStream/token；取消清理后 token 查询返回 `None` |
| HA TTSCache / producer | 未启动；没有创建 streaming cache，也没有创建 `tts_load_data_into_cache` 后台 task |
| HA Wyoming TTS writer | 没有创建 `wyoming tts write` task |
| Pipeline TTS 阶段 | 未发出 `TTS_START` |
| P7A Wyoming | STT 请求连接正常结束；没有 TTS stream handler、TTS generate/callback、TTS session cleanup 或 collect trace |

这里区分了 HA 的惰性 ResultStream 分配与实际 TTS 启动：HA Core 2026.11.0 在准备阶段可先创建 token；实际流式文本 generator、TTSCache producer 和 Wyoming TTS 请求要等到 Intent 流式文本达到阈值并调用 `async_set_message_stream()` 后才会启动。b2 实测为 token 已分配后被 Pipeline cleanup 删除，而实际 TTS producer 和 Wyoming TTS 请求均未启动。

## 3. 关键判断

- **P6.5b2 通过。** 外层 Satellite 调用 task 的取消会传递到 HA 持有的 Pipeline task；取消异常不会被转换成正常完成。
- P3 仍是 AstrBot SSE reader 关闭和远端 session Stop 的唯一 owner。取消顺序符合合同：先关闭 SSE response/generator，再对本轮 session_id 发起一次 Stop。
- 本批确认的是 TTS 开始前取消路径。它没有测试 TTSCache producer 启动后的取消，也没有测试仅关闭 HTTP Proxy GET 消费者的情况。
- 本地 fake SSE 服务和 fake Sherpa 模型用于控制时序；结果不代表真实 AstrBot 实例或模型推理的远端部署验收。

## 4. 验证结果

| 命令 | 结果 |
|---|---:|
| `./scripts/test-ha.sh tests/homeassistant/test_assist_pipeline_tts_cancellation.py -q`（含 b1/b2；最终代码状态） | **2 passed**, 9 warnings |
| `./scripts/test-ha.sh tests/homeassistant/custom_components/astrbot/test_conversation.py -q` | **12 passed**, 17 warnings |
| `./scripts/test-ha.sh tests/homeassistant -q` | **319 passed**, 76 warnings |
| `./scripts/test-sherpa-wyoming.sh` | **128 passed**, 1 warning |
| HA Ruff check + format check（b2 集成测试文件） | PASS |
| Sherpa Ruff check + format check（fake Wyoming helper、服务及其测试，共 25 个文件） | PASS |
| `git diff --check` | PASS |

警告来自当前 HA/aiohttp API deprecation、NotAppKey、pytest_socket 预期拦截以及 Wyoming `audioop` deprecation；未观察到测试失败。HA 与 Sherpa/Wyoming 按项目既有独立 Python 环境分开运行，未混合收集。

## 5. 范围与后续状态

- 仅新增 P6.5b2 测试、实施计划和本报告，并更新 README 的 P6.5 状态索引。
- 未修改 `homeassistant/custom_components/tivoo/`、`homeassistant/custom_components/astrbot/`、HA Core、Sherpa/Wyoming 或 ESP32 生产代码。
- 未连接 NAS、未部署/重启服务、未刷写或操作 ESP32 硬件。
- P6.5b3（TTS Proxy 活动期间取消）、b4（HTTP 消费端单独断开对照）和 b5（汇总与模块边界决策）仍未执行。**P6.5 整体阶段仍未完成；本报告只把 b2 记为 PASS。**
