# P6.5b1 — 正常完成控制组验收报告

- 日期：2026-11-13
- 分支：feature/p6-5-ha-cancellation-preflight
- 基线：7dab6a8（P6.5b0 本地提交）
- 批次：P6.5b1
- 结果：**PASS**
- 范围：只建立正常完成基线；没有实现或验证任何取消场景。

## 1. 测试环境

| 项目 | 版本 |
|---|---|
| Home Assistant Core | 2026.11.0 |
| HA 测试 Python | 3.14.4 |
| aiohttp / pytest | 3.14.5 / 9.0.3 |
| pytest-asyncio / pytest-homeassistant / pytest-socket | 1.4.0 / 2026.11.0 / 0.8.1 |
| Sherpa/Wyoming 测试 Python | 3.11.18 |
| sherpa-onnx / wyoming / numpy | 2.0.1 / 1.10.2 / 2.4.6 |
| Ruff | 0.17.4（两个独立虚拟环境） |

测试完全运行在开发机。AstrBot HTTP/SSE 使用本地可控端点；Sherpa KWS、STT、TTS 推理使用 fake model。实际 HA Assist Satellite 基类、Pipeline、TTS Proxy、Wyoming integration/provider、项目 P7A Wyoming handler 和 TTSStreamSession 均运行真实代码。

## 2. 正常完成链路

测试通过测试 Satellite Entity 的公开入口：

**AssistSatelliteEntity.async_accept_pipeline_from_satellite()**

使用真实 HA Pipeline 完整执行 STT → Intent → TTS。断言已收到 RUN_END、STT_END、INTENT_END、TTS_END，未收到 ERROR。AstrBot SSE 正常发送 end，reader context manager 正常关闭；Stop 路由调用次数为 0。

HA Pipeline 完成后，测试从 TTS_END 读取真实 ResultStream token，再请求 /api/tts_proxy/{token}。HTTP 响应为 200、audio/x-wav，返回完整 RIFF/WAV 数据；缓存中的最终数据与 HTTP 响应逐字节一致，缓存无加载错误。流式文本 generator 已耗尽（ag_frame is None）。

生命周期跟踪记录并断言：
1. Pipeline 开始并正常结束。
2. Pipeline 结束后才开始 TTS Proxy GET。
3. GET 触发 TTS 文本流、TTSCache producer 和 Wyoming TTS 写任务。
4. Wyoming writer task 正常完成，未取消且无异常。
5. TTSCache producer 正常完成，未取消且无异常；HTTP GET 读取完毕。
6. Wyoming TCP 客户端断开后，P7A 当前 TTS 连接 handler 的 run() finally 已执行，当前请求已无待处理 TTS task。

## 3. P7A 请求级证据

测试 trace 文件由真实 P7A WyomingEventHandler / TTSStreamSession 生成，关键字段如下：

| 对象 | 观测结果 |
|---|---|
| HA Pipeline background task | done；未 cancelled；无 exception |
| TTSCache producer | done；未 cancelled；无 exception |
| TTS 文本 stream generator | 已耗尽 |
| HA Wyoming wyoming tts write task | done；未 cancelled；无 exception |
| P7A TTS input task | done |
| P7A TTS worker task | done |
| P7A input protocol | 已接收 SynthesizeStop（input_stopped=true） |
| P7A 合成结果 | failed=false |
| P7A collect task | done；task_cancelled=false |
| P7A 请求连接 handler | 最终 last_provider=tts_stream；tts_task_pending=false |

P7A 服务进程在单次连接关闭后继续监听，是服务的预期生命周期；报告中的 handler 结束指单次 Wyoming TCP 请求连接已退出，不代表服务进程应该退出。

注意：P7A cleanup 会设置内部协作停止 Event。该 Event 同样用于正常清理，不能单独解释为用户触发取消。本次结论依据的是 SynthesizeStop、input/worker/collect task 完成、未取消状态和 handler 收尾证据。

## 4. 回归结果

| 命令 | 结果 |
|---|---:|
| ./scripts/test-ha.sh tests/homeassistant/test_assist_pipeline_tts_cancellation.py -q | 1 passed |
| ./scripts/test-ha.sh tests/homeassistant/custom_components/astrbot/test_conversation.py -q | 12 passed |
| ./scripts/test-sherpa-wyoming.sh tests/services/sherpa_wyoming/test_tts_stream.py tests/services/sherpa_wyoming/test_server.py -q | 11 passed |
| HA venv Ruff check + format check | PASS |
| Sherpa venv Ruff check + format check | PASS |
| git diff --check | PASS |

HA HTTP/aiohttp 依赖发出的 deprecation / NotAppKey warnings，以及 Wyoming 测试环境 audioop deprecation warning，均不是测试失败。

## 5. 结论与边界

- **b1 正常完成控制组已通过。** 目前确认完整正常响应会依次结束 AstrBot SSE、HA Pipeline、TTS 文本流、TTSCache producer、HA Wyoming writer、P7A TTS input/worker/collect 和单次 TCP connection handler。
- 本测试没有取消 Pipeline，也没有单独断开 TTS Proxy 消费端；因此不能推断取消时 TTSCache producer 或 Wyoming 请求是否会随 Pipeline 取消。
- 没有运行 AstrBot 4.29.4 真实实例或真实 Sherpa 模型推理；只验证 API/SSE 合同形状及真实 HA/P7A 代码路径。
- 未连接 NAS、ESP32、麦克风或 DAC；未修改生产模块。
- b2（TTS 开始前取消）、b3（TTS Proxy 活动期间取消）、b4（仅 HTTP 消费端断开对照）和 b5（归属决策汇总）仍未执行。**P6.5 整体状态仍为 NOT RUN / 未验收通过。**

b1 给后续批次提供的是正常完成的任务生命周期对照，不是取消传播的通过结论。
