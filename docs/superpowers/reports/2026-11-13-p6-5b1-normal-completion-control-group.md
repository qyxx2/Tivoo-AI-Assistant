# P6.5b1 — 正常完成控制组验收报告

- 日期：2026-11-13
- 分支：`feature/p6-5-ha-cancellation-preflight`
- 基线：`7dab6a8`（P6.5b0 本地提交）
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

本次没有连接 NAS，也没有部署/重启 HA 或 Sherpa 容器。

## 2. 正常完成链路

测试通过测试 Satellite Entity 的公开入口：

`AssistSatelliteEntity.async_accept_pipeline_from_satellite()`

使用真实 HA Pipeline 完整执行 STT → Intent → TTS。断言收到 RUN_END、STT_END、INTENT_END、TTS_END，未收到 ERROR。AstrBot SSE 正常发送 end，reader context manager 正常关闭；Stop 路由调用次数为 0。

流式 Assistant 文本达到 HA 的流式阈值后，Pipeline 创建 TTS 文本 generator 和 TTSCache producer。Pipeline 正常结束后，测试从 TTS_END 读取 ResultStream token，再请求 `/api/tts_proxy/{token}`。HTTP 响应为 200、`audio/x-wav`，返回完整 RIFF/WAV 数据；缓存最终数据与 HTTP 响应逐字节一致，缓存无加载错误。流式文本 generator 已耗尽（`ag_frame is None`）。

测试记录了以下生命周期事件并断言顺序/结束状态：

1. Pipeline 开始并正常结束。
2. AstrBot SSE reader、服务端 SSE handler 正常结束；没有调用 Stop。
3. 流式文本 generator 创建，HA TTSCache producer 创建并完成。
4. Pipeline Config Entry task 正常完成，未取消且无异常。
5. TTS Proxy GET 在 Pipeline 结束后启动，并完整读完音频。
6. HA Wyoming `wyoming tts write` task 正常完成，未取消且无异常。
7. HA Wyoming TTS 专属 TCP client 执行 disconnect。
8. P7A TTS session 的 input/worker task 完成，collect task 完成，request reset，单次 TCP handler 的 run() finally 执行；该连接没有遗留 TTS task。

**格式范围补注（b6+ 文档核对）：** 本测试 P65ControlSatellite 显式设置 preferred_format=wav，因此该结果不代表生产 Proxy 默认输出 WAV，也未覆盖 WAV→MP3 的 FFmpeg 生命周期。生产 MP3 已见 P7A 端到端报告；b6 必须补测真实 MP3 转码取消，见 [矩阵 §2.3](../specs/2026-11-13-p6-5-persistent-audio-session-and-kws-interruption-contract-matrix.md#23-tts-格式证据与生产输出约定)。

## 3. P7A 请求级证据

测试 trace 文件由真实 P7A WyomingEventHandler / TTSStreamSession 生成。

| 对象 | 观测结果 |
|---|---|
| HA Satellite Pipeline task | done；未 cancelled；无 exception |
| AstrBot SSE reader | 正常退出；Stop 调用次数为 0 |
| TTS 文本 stream generator | 已耗尽 |
| TTSCache producer | done；未 cancelled；无 exception；缓存无错误 |
| TTS Proxy GET | HTTP 200；完整 WAV bytes |
| HA Wyoming `wyoming tts write` task | done；未 cancelled；无 exception |
| HA Wyoming TTS TCP client | disconnect 已执行 |
| P7A TTS input task | done |
| P7A TTS worker task | done |
| P7A input protocol | 已接收 SynthesizeStop（`input_stopped=true`） |
| P7A 合成结果 | `failed=false` |
| P7A collect task | done；`task_cancelled=false` |
| P7A request state | reset 后 `provider=None`，无待处理 TTS task |
| P7A 单次连接 handler | `last_provider=tts_stream`；`tts_task_pending=false`；handler run() finally 已执行 |

P7A 服务进程在单次连接关闭后继续监听，是服务的预期生命周期；报告中的 handler 结束指单次 Wyoming TCP 请求连接已退出，不代表服务进程应该退出。

注意：P7A cleanup 会设置内部协作停止 Event。该 Event 同样用于正常清理，不能单独解释为用户触发取消。本次结论依据的是 SynthesizeStop、input/worker/collect task 完成、未取消状态、request reset 和 handler 收尾证据。

## 4. 验证结果

| 命令 | 结果 |
|---|---:|
| `./scripts/test-ha.sh tests/homeassistant/test_assist_pipeline_tts_cancellation.py -q` | 1 passed |
| `./scripts/test-ha.sh tests/homeassistant` | **318 passed**, 75 warnings |
| `./scripts/test-sherpa-wyoming.sh` | **128 passed**, 1 warning |
| HA venv Ruff check + format check | PASS |
| Sherpa venv Ruff check + format check | PASS |
| `git diff --check` | PASS |

HA HTTP/aiohttp 的 deprecation / NotAppKey warnings、pytest_socket 测试中的预期拦截 warning，以及 Wyoming 测试环境 `audioop` deprecation warning，均不是测试失败。

**测试环境边界：** HA 测试使用 Python 3.14 venv，Sherpa/Wyoming 使用 Python 3.11 venv。直接用 `./scripts/test-ha.sh` 默认递归收集整个 `tests/` 会把 Sherpa 服务测试也放到 Python 3.14 环境，产生 8 个依赖导入错误（缺少 `numpy`、`wyoming`、`sherpa_onnx`）。因此按仓库既有脚本分开执行兼容的完整测试目录：HA 318 项及 Sherpa-Wyoming 128 项，均通过；不将跨 venv 的混合收集误报为全量通过。

## 5. 结论与边界

- **b1 正常完成控制组已通过。** 目前确认完整正常响应会依次结束 AstrBot SSE、HA Pipeline、TTS 文本流、TTSCache producer、HA Wyoming writer、P7A TTS input/worker/collect、request state 和单次 TCP connection handler。
- 本测试没有取消 Pipeline，也没有单独断开 TTS Proxy 消费端；因此不能推断取消时 TTSCache producer 或 Wyoming 请求是否会随 Pipeline 取消。
- 没有运行 AstrBot 4.29.4 真实实例或真实 Sherpa 模型推理；只验证 P3 API/SSE 合同形状及真实 HA/P7A 代码路径。
- 未连接 NAS、ESP32、麦克风或 DAC；未修改生产模块。
- b2（TTS 开始前取消）、b3（TTS Proxy 活动期间取消）、b4（仅 HTTP 消费端断开对照）和 b5（归属决策汇总）仍未执行。**P6.5 整体阶段未完成，取消传播仍为 NOT RUN。**

b1 给后续批次提供的是正常完成的任务生命周期对照，不是取消传播的通过结论。
