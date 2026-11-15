# P6.5b0 — 环境基线与取消任务所有权清点

- 日期：2026-11-13
- 分支：`feature/p6-5-ha-cancellation-preflight`
- 基线：`489a405e338b2ef2ebd7e2ce4447bb3c19e56cfc`（main）
- 批次规格：[P6.5 cancellation preflight patch](../patches/2026-11-11-p6-5-ha-cancellation-preflight.patch.md)
- 范围：仅 P6.5b0。只固定开发环境版本并审查各层任务创建者、持有者、取消入口和清理边界；未运行取消行为测试，未修改生产逻辑。

## 1. 环境版本基线

本报告区分开发机测试环境、项目部署合同版本和本批未连接的外部服务，避免把本机依赖当成 NAS 正在运行的版本。

| 环境 | 版本 | 证据与说明 |
|---|---|---|
| Ubuntu 开发机 HA 测试解释器 | Python 3.14.4 | `.venv/bin/python` |
| Home Assistant Core | 2026.11.0 | `.venv` 的 `homeassistant-2026.11.0.dist-info/METADATA` |
| HA HTTP / 测试依赖 | aiohttp 3.14.5；pytest 9.0.3；pytest-asyncio 1.4.0；pytest-homeassistant 2026.11.0；pytest-socket 0.8.1；async-timeout 5.0.1；ruff 0.17.4 | 从 HA 测试虚拟环境 distribution metadata 读取 |
| Sherpa/Wyoming 开发解释器 | Python 3.11.18 | `.venv-sherpa/bin/python` |
| Sherpa TTS / Wyoming 服务依赖 | sherpa-onnx 2.0.1；wyoming 1.10.2；numpy 2.4.6；pytest 9.0.3；ruff 0.17.4 | 从独立 Sherpa venv distribution metadata 读取；与 HA 的 Python 3.14 venv 分离 |
| AstrBot 合同基线 | 4.29.4 | 项目 P3 合同矩阵及既有生产 E2E 报告记录；本批未连接 AstrBot 实例重新查询版本 |

说明：

- `scripts/test-ha.sh` 使用项目根目录的 `.venv`、HA Core 2026.11.0 和 pytest-homeassistant bootstrap。
- `.venv` 未安装 `wyoming` 或 `sherpa-onnx`；它们属于独立服务环境，不是缺失的 HA 依赖。P7A 服务的 Python 3.11 环境已安装上述固定版本。
- 本批未在 NAS 执行命令、重启容器或核对容器在线版本。HA 2026.11.0 为本机用于源码检查和后续测试的固定版本；AstrBot 4.29.4 为项目既有合同基线，不将其冒充本次远程实时观测。

## 2. 任务所有权清点

以下为 HA Core 2026.11.0 安装源码和项目 P3/P7A 代码的静态审查。表内“已确认”表示代码中存在该创建/持有/清理关系，不代表取消后的实际退出已经通过运行时测试。

| 层级 / 对象 | 创建者 | 持有者 / 生命周期 owner | 取消入口与清理代码（源码观察） | b0 结论 |
|---|---|---|---|---|
| Satellite 外层调用任务 | 调用 Satellite 实体公开入口的集成调用者；HA 基类不替调用者创建此 task | 调用方持有其调用 task。当前分支尚无生产 Tivoo Assist Satellite caller；P7 才接入 | 调用方取消外层 task；HA 基类公开入口为 `AssistSatelliteEntity.async_accept_pipeline_from_satellite()` | 调用方与 HA 内部 Pipeline task 是两个不同对象；生产 caller 的具体创建位置留待 P7 |
| HA Pipeline task | `AssistSatelliteEntity.async_accept_pipeline_from_satellite()` 使用 `ConfigEntry.async_create_background_task()` 创建 | `AssistSatelliteEntity._pipeline_task` 持有引用；Config Entry 同时登记其生命周期 | `_cancel_running_pipeline()` 执行 task.cancel() 并 await；入口结束时置空引用。Config Entry unload/shutdown 会清理登记的后台 task | HA 基类提供明确的 task handle 和取消/等待入口，后续需用可控测试验证上游取消是否完整 |
| PipelineRun / processor | `async_pipeline_from_audio_stream()` 构造 `PipelineInput` / `PipelineRun`；processor 在 PipelineRun 初始化时创建 | 不是独立 asyncio task；在 Satellite 的 `_pipeline_task` 中运行，由 PipelineRun 持有 processor | `PipelineRun.async_execute()` 在 BaseException 路径调用 processor.cleanup() 并重新抛出，finally 调用 end()；end() 停止 debug recording thread 并注销 run | 取消异常会进入清理路径；processor 清理具体能终止哪些下游对象需继续核实 |
| TTS ResultStream / token | Pipeline processor 的 `prepare_text_to_speech()` 调用 `tts.async_create_stream()` | `_DefaultPipelineProcessor.tts_stream` 持有 ResultStream；ResultStream 持有指向 TTSCache 的 future | processor.cleanup() 调用 `ResultStream.delete()`；HA 的 delete 只从 `token_to_stream` 删除 token | 删除 URL/token 登记不等于取消 TTSCache producer；两者必须分开追踪 |
| 流式 TTS 文本 generator | Pipeline processor 的 `recognize_intent()` 内部创建 `tts_input_stream_generator()`，从 `asyncio.Queue` 读取文本；正常路径在对话处理完成后向队列放入 `None` | generator 被交给 ResultStream/TTSCache 的音频生成链；实际消费由 TTSCache producer 驱动 | 正常结束通过队列 sentinel 结束；本批源码审查未发现 Pipeline 取消清理路径显式关闭该 generator 或向该队列补发 sentinel | generator 的取消/关闭结果必须在 b1/b3 观察，不能从 ResultStream token 删除推断 |
| HA TTSCache background producer | `SpeechManager.async_cache_message_stream_in_memory()` 创建 TTSCache 后，调用 `hass.async_create_background_task(_load_data_into_cache(...))` | HA 全局 background-task 生命周期；TTSCache 持有 `data_gen`、partial bytes 与 consumer queues；该 producer task handle 未保存在 ResultStream/TTSCache 中 | producer 由 `_load_data_into_cache()` 驱动 `cache.async_load_data()`；缓存读取异常时从 mem_cache 删除。ResultStream.delete() 不触碰 producer task | 这是独立于 Satellite/Pipeline task 的重要追踪对象。后续测试必须直接观察 producer/generator，而不能只验证 token 消失 |
| HA Wyoming TTS text writer | `WyomingTTS.async_stream_tts_audio()` 通过 `ConfigEntry.async_create_background_task()` 创建 `_write_tts_message()` | Wyoming Config Entry 的 `_background_tasks` 集合登记 task；方法本地未保留 task handle | writer 负责发送 SynthesizeStart/Chunk/Synthesize/Stop；音频 data generator 的 finally 调用 `client.disconnect()`。Config Entry unload/shutdown 可取消登记的后台任务 | writer 与读音频的 data generator 为并行方向；客户端断开后 writer 的结束行为尚未实测 |
| Wyoming TCP connection handler | Wyoming 1.10.2 `AsyncTcpServer._handler_callback()` 为每条 TCP 连接创建 `asyncio.Task(handler.run(), name="wyoming event handler")` | AsyncServer 的 `_handlers` 映射追踪连接 task 与 handler | `AsyncEventHandler.run()` finally 调用 handler.disconnect() 后关闭 writer；EOF/异常进入相同 disconnect 清理流程 | TCP 连接 task 是每连接边界，不等于 HA Wyoming 的文字 writer task |
| P7A 连接内 TTS request task | 项目 `WyomingEventHandler._start_streaming_tts()` 创建 `_forward_streaming_tts()` task | 当前连接 handler 的 `_tts_task` 持有引用；handler 同时持有 request-local `TTSStreamSession` 与输入队列 | `disconnect()` 对 `_tts_task` cancel + gather，然后 reset request；`_forward_streaming_tts()` finally 记录请求结果 | 连接断开到请求 task 的取消链代码明确；实际断连回收需要 b3/b4 运行时证据 |
| P7A TTSStreamSession 子任务 | `TTSStreamSession.stream()` 为输入 reader 和 PCM generator 各创建一个 task：`_input_task`、`_worker_task` | 当前 TTSStreamSession 持有两 task 的引用及 PCM 队列、取消 Event | stream finally 调用 `_cleanup()`：设置取消 Event、cancel 输入 task、等待 worker 和 input task、清空 PCM 队列 | 两个 asyncio 子任务都有引用和清理路径；模型执行线程是否及时结束须区分“callback 停止生产”和“线程返回” |
| P7A Sherpa model worker / PCM callback | `_generate_pcm()` 通过 `asyncio.to_thread()` 或 `BoundedExecutor.run()` 执行阻塞模型；Sherpa 调用 PCM callback | `TTSStreamSession` 持有执行协程、callback cancellation Event；BoundedExecutor 管理线程池和 slot | callback 检测取消 Event 后返回 0；BoundedExecutor 对运行中的线程采用协作停止并在 future 完成后释放 slot，不宣称强杀正在运行的模型线程 | 取消是协作式；后续应记录连接关闭后 task 与模型线程各自何时退出 |
| P3 AstrBot SSE reader | P3 Conversation Agent 的 `async_deltas()` 进入 `api_client.async_chat()`，迭代 response.content 并解析 SSE | 当前 `_async_handle_message()` / ChatLog 消费栈持有 generator；Conversation Entity 使用 `_conversation_lock` 串行化共享 session | 捕获 CancelledError 时显式 `await deltas.aclose()`；HTTP async context 负责关闭 response。finally 也关闭 generator | 本地 reader 有明确关闭路径，但这不会自动终止 AstrBot 独立的上游 Agent run |
| P3 AstrBot session Stop | P3 Conversation Entity 的取消/流错误分支调用 API client `async_stop_session()` | `astrbot` 集成拥有 API client 与 session mapping；AstrBot 服务拥有远端 session/run | 调用 `POST /api/v1/chat/sessions/{session_id}/stop`；在 response accepted 且 stream 未正常完成时执行，受 stop timeout 限制；停止失败只记录 warning，不伪称远端已停 | Stop 是 session 级 API，必须使用匹配的 `api_key:<key_id>` owner；远端任务是否真正停止由后续测试确认 |

### 2.1 重点源码事实

1. HA Satellite 基类确实持有自己的 `_pipeline_task`，并在 `_cancel_running_pipeline()` 中 cancel 后 await：`homeassistant/components/assist_satellite/entity.py:442-553`。
2. `PipelineRun.async_execute()` 在取消等 BaseException 路径执行 processor cleanup、重新抛出异常，并在 finally 执行 run end：`homeassistant/components/assist_pipeline/run.py:240-273`。
3. Pipeline processor 的 cleanup 只调用 `tts_stream.delete()`；`ResultStream.delete()` 最终只删除 token 映射：`homeassistant/components/assist_pipeline/default_pipeline.py:194-198`、`homeassistant/components/tts/__init__.py:940-942,1158-1161`。
4. HA TTS streaming cache producer 由 `SpeechManager.async_cache_message_stream_in_memory()` 单独创建为 HA background task，task handle 未被 ResultStream/TTSCache 保存：`homeassistant/components/tts/__init__.py:1268-1287`。
5. HA Wyoming provider 把 `_write_tts_message()` 作为 Config Entry background task 启动，而响应 generator 在 finally 断开 TCP client：`homeassistant/components/wyoming/tts.py:208-226`。Config Entry 会追踪其 background tasks，并在 entry unload/shutdown 时取消：`homeassistant/config_entries.py:1548-1573`。
6. Wyoming 1.10.2 的 `AsyncEventHandler.run()` 在 finally 调用 `disconnect()`；TCP server 为每条连接创建单独 handler task：`.venv-sherpa/lib/python3.11/site-packages/wyoming/server.py:14-47,94-103`。
7. P7A TTS request task 在 handler.disconnect() 中 cancel + gather；session 内 input/worker tasks 由 session cleanup 管理：`services/sherpa_wyoming/run.py:331-430,478-497`、`services/sherpa_wyoming/providers/tts.py:240-241,589-600`。

## 3. 取消观测状态与未完成项

本批只进行环境核对和源码责任追踪，以下均未执行：

- 未创建测试 Satellite Entity 并通过 `async_accept_pipeline_from_satellite()` 启动受控 Pipeline。
- 未验证正常完成时 Pipeline、TTSCache、Wyoming 和 Sherpa task 的实际退出顺序。
- 未取消外层 Pipeline，也未观察 AstrBot SSE reader / session Stop 的运行时终止结果。
- 未测试 TTS Proxy 已启动时的 producer/generator/HTTP GET/Wyoming 请求清理。
- 未做 HTTP GET consumer 单独断开对照。
- 未判断 HA TTS Proxy 是否需要后续补充定向取消机制；静态代码已经指出需要追踪的 producer handle 缺口，但这不是完整运行时 GAP 结论。

因此，**P6.5b0 完成只代表环境版本基线和源码任务所有权清点完成；P6.5 取消传播验证仍为 NOT RUN。** 后续 b1–b5 状态不变，必须分别按 patch 执行，不能把本报告中的静态源码事实当成取消 PASS。

## 4. 本批范围与验证

- 仅新增本 b0 报告并更新 README 阶段索引。
- 未修改 HA Core、Tivoo、AstrBot、Sherpa 或 ESP32 生产代码。
- 未创建 P6.5b1–b5 测试或提前实现取消逻辑。
- 未连接 NAS、未部署 HA、未重启容器、未刷写设备。

已执行的基线核验：

- HA venv：版本元数据读取成功，HA Core 2026.11.0 / Python 3.14.4。
- Sherpa venv：版本元数据读取成功，Sherpa 2.0.1 / Wyoming 1.10.2 / Python 3.11.18。
- 对 HA Assist Satellite、Assist Pipeline、TTS Proxy、Wyoming TTS、项目 AstrBot Conversation 与 Sherpa Wyoming 源码完成静态定位。
- 最终提交前另行执行 `git diff --check` 和仓库状态核验。
