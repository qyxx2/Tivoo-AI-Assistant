# P6.5b3 — TTS Proxy 活动期间取消验收报告

- 日期：2026-11-13
- 分支：`feature/p6-5-ha-cancellation-preflight`
- 基线：`449bc1f`（P6.5b2）
- 批次：P6.5b3
- 结果：**PASS（复现并定位取消传播 GAP）**
- 范围：仅 TTS Proxy 活动期间取消；未实现生产取消逻辑，未执行 P6.5b4/b5。

## 1. 环境与测试方法

| 项目 | 版本 |
|---|---|
| Home Assistant Core | 2026.11.0 |
| HA 测试 Python | 3.14.4（项目 `.venv`） |
| HA aiohttp / pytest | 3.14.5 / 9.0.3 |
| Sherpa/Wyoming Python | 3.11.18（项目 `.venv-sherpa`） |
| sherpa-onnx / wyoming | 2.0.1 / 1.10.2 |

测试通过真实 `AssistSatelliteEntity.async_accept_pipeline_from_satellite()` 启动 STT → AstrBot Conversation → 流式 TTS Pipeline。AstrBot HTTP/SSE 使用本地可控 aiohttp fake；HA Assist Pipeline、HA TTS Proxy/Cache、HA Wyoming Provider 和项目 P7A Wyoming TCP handler/TTSStreamSession 使用真实代码。Sherpa 模型使用带 callback 屏障的确定性 fake。

测试屏障确认以下条件后才取消外层调用 task：

1. 长 SSE 文本达到 HA 流式 TTS 阈值，真实 `tts_input_stream_generator`、TTSCache 与 `tts_load_data_into_cache` producer 已创建。
2. HA Wyoming 已发起实际 TCP TTS 请求，P7A 收到 SynthesizeStart/文本并进入第一个模型 callback 屏障。
3. `/api/tts_proxy/{token}` 实际返回 HTTP 200、`audio/x-wav`，GET consumer 已读到首字节并仍在流式读取；TTSCache 记录了活动 consumer queue。

测试随后只取消公开入口的外层 caller task，没有直接取消 HA `_pipeline_task`、TTSCache producer、Wyoming task 或 P7A task。首次 P7A `_audio_callback` 被明确安排在 Pipeline 取消之后才执行，便于验证取消后的 PCM 是否仍被接受。

## 2. Pipeline 取消后即时状态

| 追踪对象 | 取消后的实测状态 | 生命周期 owner / 证据 |
|---|---|---|
| Satellite 外层 caller | `cancelled=True`；`CancelledError` 原样传播 | 调用方 task |
| HA Satellite `_pipeline_task` | `done=True`、`cancelled=True`；`satellite._pipeline_task is None` | HA Assist Satellite 基类；Pipeline cancellation 正常收尾 |
| P3 SSE reader | response context manager 已关闭 | P3 Conversation Agent |
| AstrBot session Stop | 精确调用 1 次，使用本轮已确认的相同 `session_id`；Stop 到达时 SSE reader 已关闭 | P3 是唯一 Stop owner |
| HA TTS ResultStream token | `tts.async_get_stream(hass, token) is None` | Pipeline cleanup 删除了 token 映射；这只说明公开 token 不再注册 |
| 已启动的 HA TTS Proxy GET | HTTP response 仍未 EOF；活动 consumer queue 仍存在 | HTTP request handler 已经取得 ResultStream 引用，不因 token map 删除而自动关闭 |
| HA TTSCache producer | `done=False`、`cancelled=False`（`pending`） | `SpeechManager.async_cache_message_stream_in_memory()` 通过 `hass.async_create_background_task()` 创建；该 task handle 不由 ResultStream/Pipeline 持有 |
| `tts_input_stream_generator` | `ag_frame` 仍存在，停在 `tts_input_stream.get()`；queue 当时为空 | Pipeline processor 创建 generator，TTSCache producer 消费；Pipeline cleanup 未关闭 generator或向 queue 发结束 sentinel |
| HA Wyoming `wyoming tts write` | `done=False`（`pending`） | Wyoming Config Entry background task；与读音频的 generator 是并行方向 |
| P7A TCP handler | `pending` | Wyoming server 的单连接 handler task |
| P7A `_forward_streaming_tts` request task | `pending` | 当前 `WyomingEventHandler._tts_task` |
| P7A input reader / PCM worker | 均 `pending` | 当前 TTSStreamSession `_input_task` / `_worker_task` |
| P7A session cancellation Event | `False` | TTSStreamSession；callback 屏障仍在等待 |

关键区别：取消后 token 查询为 `None`，并不表示之前已经建立的 Proxy GET、TTSCache producer、文本 generator 或下游合成任务被取消。

## 3. 迟到文本与 PCM 生成证据

Pipeline 取消完成后，测试先释放第一个模型 callback 前的屏障。首次模型调用随后执行实际 P7A `_audio_callback` 并返回 `1`，表明取消后 PCM 仍被旧 session 接收。测试再向仍被旧 `tts_input_stream_generator` 持有的 queue 写入 `取消后迟到文本。`；实际 P7A TTS 代码再次调用模型 fake 的 `generate()`，第二次 `_audio_callback` 同样成功。测试通过两个 callback trace 事件验证结果，不以固定 sleep 推断。

在执行测试夹具的显式资源清理前：

- 旧 TTSCache producer 和 Wyoming writer 仍 pending。
- 活动 HTTP GET 尚未 EOF。
- P7A 未产生 `tts_session_cleanup` 或 `handler_finished` trace。
- 已取消的 Pipeline 所属文本流仍可被推进，并再次触发 P7A 合成及 PCM callback。

因此，**P6.5b3 确认 HA Core 2026.11.0 中 Pipeline cancellation 不会自动终止已经启动的 TTS Proxy producer/streaming text generator，也不会立即关闭其 HTTP consumer、Wyoming writer 或 P7A 请求。** 这不是 token 清理就能解决的问题。

测试 finally 会释放 fake callback、关闭 HTTP response、取消本批创建的遗留 producer、等待 Wyoming 断连，并卸载测试 Config Entry；这些是测试隔离清理，不计为产品取消路径成功。

## 4. 架构归属判断

- **HA TTS Proxy / TTSCache 是当前首要 GAP。** 其 streaming producer 由 HA 全局 `hass.async_create_background_task()` 创建，Pipeline processor 的 `ResultStream.delete()` 仅删除 token，未持有 producer task handle。后续要解决此问题，需要由真正拥有 producer 生命周期的 HA TTS Proxy/Cache 边界提供可用的定向取消/关闭路径；不能在 Tivoo 中用 `asyncio.all_tasks()` 猜任务，不能用删除 token 冒充取消。
- **HTTP GET 是独立消费端。** 已建立的请求持有 stream 引用；需要在 b4 单独验证仅断开 GET 时 producer 是否仍运行，不能将其与 Pipeline cancellation 混为一谈。
- **HA Wyoming writer 与音频 reader 分属并行任务。** b3 观察到 writer pending；它由 Wyoming Config Entry 跟踪，不能仅凭读端准备断连就推断 writer 已完成。
- **P7A 的代码连接断开清理边界已明确，但 b3 的 Pipeline cancel 没有触发该边界。** 当前测试 snapshot 显示 request/input/worker 都 pending；在测试 cleanup 真正关闭 TCP 后，连接 handler 才进入 disconnect 清理。P7A 不应承担 HA Pipeline 的取消责任。
- **P3 取消链保持正常。** SSE reader 关闭和同一 owner session 的一次 Stop 与 b2 一致，P3 仍是 Stop 唯一 owner。

后续 b4 应继续对 HTTP GET consumer 单独断开做对照；b5 再结合 b1/b2/b3/b4 的证据决定生产模块边界。当前报告不安排或实现修复。

## 5. 验证结果

| 命令 | 结果 |
|---|---:|
| `./scripts/test-ha.sh tests/homeassistant/test_assist_pipeline_tts_cancellation.py -q` | **3 passed**（b1/b2/b3） |
| `./scripts/test-ha.sh tests/homeassistant/custom_components/astrbot/test_conversation.py -q` | **12 passed**, 17 warnings |
| `./scripts/test-ha.sh tests/homeassistant -q` | **320 passed**, 77 warnings |
| `./scripts/test-sherpa-wyoming.sh` | **128 passed**, 1 warning |
| HA Ruff check + format check（b3 集成测试文件） | PASS |
| Sherpa venv Ruff check + format check（fake Wyoming test helper） | PASS |
| `python -m py_compile tests/helpers/p6_5_fake_wyoming_server.py` | PASS |
| `git diff --check` | PASS（最终提交前复验） |

HA 与 Sherpa/Wyoming 按仓库既有 Python 3.14/3.11 独立环境执行。HA warnings 是当前 aiohttp/HA API deprecation、NotAppKey 和 pytest_socket 预期拦截提示；Sherpa warning 为依赖 `audioop` deprecation，均非失败。

## 6. 范围与阶段状态

- 仅新增/修改 P6.5 测试与测试辅助服务、b3 计划/报告/ledger 和 README 状态索引。
- 未修改 HA Core、`homeassistant/custom_components/tivoo/`、AstrBot、Sherpa/Wyoming 生产逻辑或 ESP32 固件。
- 未连接 NAS、未部署/重启任何服务、未刷写或操作 ESP32、麦克风、DAC。
- **P6.5b3 的验证任务完成，观察到明确 GAP；取消链路没有因此获得 PASS。** P6.5b4（HTTP consumer 单独断开对照）和 b5（汇总与模块边界决策）仍未执行，P6.5 整体阶段仍未完成。
