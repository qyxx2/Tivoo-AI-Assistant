# P6.5b4 — HTTP TTS Proxy 消费端断开对照组报告

- 日期：2026-11-13
- 分支：feature/p6-5-ha-cancellation-preflight
- 基线：c106509（P6.5b3）
- 批次：P6.5b4
- 结果：**PASS（HTTP consumer 断开与 Pipeline 取消已区分）**
- 范围：仅 HTTP TTS Proxy consumer disconnect 对照；未修改生产逻辑，未执行 P6.5b5。

## 1. 环境与测试方法

| 项目 | 版本 |
|---|---|
| Home Assistant Core | 2026.11.0 |
| HA 测试 Python | 3.14.4（项目 .venv） |
| HA aiohttp / pytest | 3.14.5 / 9.0.3 |
| Sherpa/Wyoming Python | 3.11.18（项目 .venv-sherpa） |
| sherpa-onnx / wyoming | 2.0.1 / 1.10.2 |

本批复用 b1/b2/b3 测试夹具：通过真实 AssistSatelliteEntity.async_accept_pipeline_from_satellite() 公开入口启动 Pipeline，使用真实 HA Core Assist Pipeline、TTS Proxy/Cache、Wyoming Provider 和项目 P7A Wyoming TCP handler/TTSStreamSession。AstrBot HTTP/SSE 与 Sherpa 推理模型由本地 fake 控制。没有连接 NAS、真实 AstrBot 实例或 ESP32。

测试等待真实 TTSCache producer 创建、P7A 首个模型 callback 屏障、HTTP GET 已收到 WAV 首字节后，**先仅关闭 HTTP GET 客户端响应**。释放 callback 后以新的 TTS generation/callback 事件确认生成继续，并等待 HA ResultStream.async_stream_result() 退出。此时 Pipeline caller 仍保持运行。随后才单独取消公开 Satellite caller，观察 Pipeline/SSE/Stop/token 变化。

整个时序使用 asyncio.Event、明确的 task 状态和 P7A 控制端；未使用固定 sleep 推断生命周期。

## 2. HTTP GET 单独断开后的观测

| 追踪对象 | HTTP GET 关闭后的状态 | 证据 |
|---|---|---|
| HTTP 客户端响应 | closed | 客户端显式关闭响应 |
| HA Proxy 的 ResultStream.async_stream_result() | 已退出 | 包装器 finally 触发 proxy_stream_finished |
| Satellite 外层 caller | pending | caller_task.done() == False |
| HA Satellite Pipeline task | pending | pipeline_task.done() == False，Satellite 仍持有同一 task |
| ResultStream token | 仍可查询 | tts.async_get_stream(hass, token) 返回原 ResultStream |
| AstrBot SSE reader / handler | 仍打开 | reader/handler finished Event 未触发 |
| AstrBot session Stop | 未调用 | stop_calls == [] |
| TTSCache producer | pending，未 cancelled | producer task handle 仍未完成 |
| 流式文本 generator | 仍有活动 frame | generator.ag_frame is not None |
| TTSCache consumer queue | 仍登记 | cache._consumers 仍非 None，长度为 1 |
| HA Wyoming TTS writer | pending | Config Entry 跟踪的 wyoming tts write task 未完成 |
| HA Wyoming TCP disconnect | 未触发 | disconnect Event 未触发，计数为 0 |
| P7A handler / request / input / worker | 全部 pending | 测试控制端 status snapshot |
| P7A session cancellation Event | false | status snapshot |

在 HTTP GET 断开之后释放模型 callback，P7A 仍产生后续 TTS generation 和 PCM callback；HA Proxy 的响应迭代器已退出，Pipeline/SSE 仍处于活动状态。该证据证明**HTTP 下载端停止消费不会自动停止上游 TTSCache producer、文本流或 Wyoming/P7A 合成请求**。

另一个明确观测是 TTSCache consumer queue 在 GET 断开后仍留在 _consumers 中。当前 HA 实现的 TTSCache.async_stream_data() 将 queue 加入 consumers，并在读取到结束 sentinel 后自然结束；HTTP 提前断开时本次测试未观察到 queue 被移除。该队列不是模型任务，也不能将其状态等同于 producer 退出；它是后续生命周期决策应一并处理的消费端残留。

## 3. 随后单独取消 Pipeline 的对照

HTTP GET 已经断开后，再取消公开入口的外层 caller task：

| 追踪对象 | Pipeline cancel 后状态 |
|---|---|
| Satellite 外层 caller | cancelled；CancelledError 原样传播 |
| HA Satellite _pipeline_task | done + cancelled；入口 finally 清空引用 |
| P3 AstrBot SSE reader | 已关闭 |
| P3 AstrBot session Stop | 精确调用 1 次，session_id 与已确认的本轮 session 相同 |
| HA TTS ResultStream token | 查询返回 None |
| TTSCache producer / 文本 generator | 仍 pending / frame 仍存在 |
| HA Wyoming writer / TCP disconnect | writer 仍 pending；disconnect 未触发 |
| P7A handler / request / input / worker | 全部仍 pending；session cancellation Event 仍 false |

这与 GET close 阶段的区别明确：GET close 不取消 Pipeline、不触发 P3 Stop，也不删除 token；Pipeline cancel 会取消 Satellite Pipeline 并触发 P3 的 SSE/Stop 清理、删除 token，但仍不能回收已经脱离 Pipeline 所有权的 TTSCache producer、文本 generator、Wyoming writer 或 P7A 请求。

测试 finally 显式关闭 HTTP response、取消测试创建的缓存 producer、等待 Wyoming 断连、卸载 Config Entry 并终止本地 fake 服务。这些是测试隔离清理，不计入产品取消成功证据。

## 4. 架构判断输入（不在本批实施修复）

- **HTTP consumer 生命周期与 Pipeline 生命周期相互独立。** 不能把 GET disconnect 当成用户取消或 Pipeline cancel。
- **TTSCache producer 是首要独立 owner。** 它由 HA TTS Manager 创建为全局后台 task；ResultStream/HTTP consumer 并未持有 producer task handle。b3 已证明 Pipeline cancel 不会结束该 producer，b4 证明 GET disconnect 同样不会结束它。
- **consumer queue 需要进入 b5 决策。** 提前断开后 queue 仍登记，说明 GET 侧的消费资源清理也没有随 Proxy iterator 退出完成。
- **Wyoming writer 与 P7A 请求仍属于下游独立边界。** GET disconnect 本身不会关闭 Wyoming TCP；Pipeline cancel 也没有触发其断连。P7A 仍按自身的连接断开边界清理，不承担 HTTP/Pipeline 的取消责任。
- **P3 仍是 AstrBot SSE reader 与 session Stop 的唯一 owner。** 本批只在后续 Pipeline cancel 阶段观测到一次 Stop；单独 GET close 不调用 Stop。

b5 应结合 b1 正常完成、b2 TTS 前取消、b3 活动 TTS 期间取消和 b4 GET 单独断开四组证据，确定后续 P7/P8 的 producer/consumer 定向关闭责任和限制。**本批不实现 HA Core 补丁、Tivoo 生产取消机制、asyncio.all_tasks() 清理或其他推测式任务查找。**

## 5. 验证结果

| 命令 | 结果 |
|---|---:|
| ./scripts/test-ha.sh tests/homeassistant/test_assist_pipeline_tts_cancellation.py -k http_tts_proxy_disconnect -q（格式化后复跑） | **1 passed** |
| ./scripts/test-ha.sh tests/homeassistant/test_assist_pipeline_tts_cancellation.py -q | **4 passed** |
| ./scripts/test-ha.sh tests/homeassistant/custom_components/astrbot/test_conversation.py -q | **12 passed** |
| ./scripts/test-ha.sh tests/homeassistant -q | **321 passed** |
| ./scripts/test-sherpa-wyoming.sh | **128 passed** |
| HA Ruff check + format check（集成测试文件） | PASS |
| .venv/bin/python -m py_compile tests/homeassistant/test_assist_pipeline_tts_cancellation.py | PASS |
| git diff --check | PASS |

HA warnings 来自 HA/aiohttp API deprecation、NotAppKey 和 pytest_socket 的预期拦截；Sherpa warning 为依赖 audioop deprecation，均非测试失败。HA 与 Sherpa/Wyoming 分别使用项目 Python 3.14/3.11 虚拟环境执行。

## 6. 范围与阶段状态

- 只修改 P6.5 生命周期集成测试、b4 计划/报告/SDD ledger 和 README 状态索引。
- 未修改 HA Core、homeassistant/custom_components/tivoo/、AstrBot、Sherpa/Wyoming 生产模块或 ESP32 固件。
- 未连接 NAS、未部署/重启服务、未刷写或操作 ESP32、麦克风、DAC。
- **P6.5b4 对照组通过；已将 HTTP consumer 断开与 Pipeline cancel 的差别及 consumer queue 残留记录为证据。**
- P6.5b5（汇总与模块边界决策）仍未执行；P6.5 整体阶段仍未完成。
