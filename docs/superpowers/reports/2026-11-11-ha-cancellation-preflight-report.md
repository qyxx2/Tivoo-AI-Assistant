# HA Assist Pipeline / TTS Proxy 取消链路前置验证汇总报告

- 实际汇总日期：2026-11-13
- 规划批次：P6.5b5
- 项目分支：`feature/p6-5-ha-cancellation-preflight`
- 本报告基线：`67df97a`（P6.5b4）
- 结果：**P6.5 前置调查与模块边界决策完成；活动 TTS 取消链路仍为 GAP**
- 范围：汇总 b0–b4 的既有证据并形成后续模块决策；本批不修改生产逻辑、不新增测试、不部署外部服务。

## 1. 执行结论

P6.5 已完成计划内的环境/owner 清点、正常完成控制组、TTS 前取消、活动 TTS 期间取消和 HTTP GET consumer 单独断开对照。证据足以确定主要缺口与后续责任边界：

1. **HA Satellite / Pipeline 取消本身有效。** 取消公开 Satellite caller 后，HA 持有的 Pipeline task 被取消并等待结束；取消异常向 caller 传播。
2. **P3 取消责任正常。** 同一轮已确认的 AstrBot session，其 SSE reader 被关闭，P3 使用 owner 匹配的 session Stop API 精确调用一次。P3 仍是 SSE reader 与 AstrBot Stop 的唯一 owner。
3. **HA TTS Proxy/Cache 有活动 TTS 取消缺口。** 一旦流式 TTSCache producer 和文本 generator 已经启动，Pipeline cleanup 仅删除 ResultStream token 映射；producer、generator、已建立的 HTTP response、HA Wyoming writer 及下游 P7A 请求不会随 Pipeline 自动结束。测试还直接推进了取消之后的 callback 和迟到文本，确认旧请求仍能继续生成 PCM。
4. **HTTP GET consumer disconnect 与 Pipeline cancellation 是两种独立事件。** 单独关闭 GET 只结束 Proxy response iterator；不会取消 Pipeline、关闭 P3 SSE/Stop、删除 token 或停止上游 TTS 生成。当前 HA Cache consumer queue 在 GET 提前关闭后仍登记，形成另一个消费端资源清理问题。
5. **P7A 的请求级清理实现与合同方向一致，但上游 GAP 阻止了端到端 TCP 断连验证。** P7A 现有单元测试覆盖 stream generator cancel、callback 协作停止和未收到 SynthesizeStop 的 EOF；b3/b4 期间 Wyoming TCP 未实际断开，因此不把 P7A handler/request/input/worker 的活动连接清理记为端到端 PASS。

因此，P6.5 的**调查与决策批次可以收尾**，但不能把端到端取消称为已通过。活动 TTS 场景仍然允许在旧 Pipeline 已结束后出现迟到 PCM；依赖该取消链的 HA 打断验收和 P8 端到端收尾必须继续 BLOCKED，直到 TTS producer 的真实 owner 提供定向关闭能力并有回归测试证明旧请求全部结束。

## 2. 测试环境与可信边界

| 项目 | 本次证据基线 |
|---|---|
| HA 测试环境 | Home Assistant Core 2026.11.0 |
| HA Python | 3.14.4（项目 `.venv`） |
| HA aiohttp / pytest | 3.14.5 / 9.0.3 |
| pytest-asyncio / pytest-homeassistant / pytest-socket | 1.4.0 / 2026.11.0 / 0.8.1 |
| Sherpa/Wyoming Python | 3.11.18（项目 `.venv-sherpa`） |
| sherpa-onnx / Wyoming / numpy | 2.0.1 / 1.10.2 / 2.4.6 |
| Ruff | 0.17.4（两个独立虚拟环境） |
| AstrBot 合同版本 | 4.29.4（项目既有 P3 基线；b1–b4 未重新连接远端实例查询） |

b1–b4 使用真实 HA Core 2026.11.0 Assist Satellite 基类、Assist Pipeline、TTS Proxy/Cache、Wyoming Provider，以及项目 P7A Wyoming TCP server/handler。AstrBot HTTP/SSE 端点与 Sherpa 推理引擎由本地可控 fake 提供，用于屏障和可重复时序；不是远端 AstrBot 服务或真实模型推理验收。

HA 测试运行于 Python 3.14 虚拟环境；Sherpa/Wyoming 测试运行于 Python 3.11 虚拟环境。二者按仓库既有脚本分开执行，未将不同解释器的依赖混合收集。本轮没有连接 NAS、部署/重启 HA 或 Sherpa 容器、连接或刷写 ESP32，也没有测试真实麦克风、DAC 或 Tivoo 播放链路。

## 3. b0–b4 结果总览

| 批次 | 场景 | 结果 | 能证明的内容 |
|---|---|---|---|
| b0 | 环境基线与任务所有权静态清点 | PASS（清点完成） | 固定测试依赖版本，识别 HA、P3、Wyoming/P7A 和设备各层的任务创建者/owner；静态源码不是运行时取消证据 |
| b1 | 完整正常响应控制组 | PASS | 正常结束时 Pipeline、SSE、文本 generator、TTSCache producer、HTTP GET、Wyoming writer 和 P7A 请求均能正常收尾 |
| b2 | TTS producer 尚未启动时取消 | PASS | caller 取消传播到 HA Pipeline；P3 关闭 SSE 并对同一 session Stop 一次；未启动的 TTS producer/Wyoming 请求没有迟到启动 |
| b3 | TTS Proxy 已活动时取消 Pipeline | GAP 已复现 | caller/Pipeline/P3 收尾成功；已启动的 TTSCache producer、文本 generator、HTTP response、Wyoming writer 和 P7A 请求仍 pending，取消后仍可产生 PCM |
| b4 | 只关闭 HTTP GET consumer，再独立取消 Pipeline | PASS（对照组完成）/ GAP 证据 | GET 关闭不等于 Pipeline/上游取消；consumer queue 仍登记；随后 Pipeline 取消仍未回收 detached producer/generator/Wyoming/P7A |

这里的 PASS 指该批次的测试目标/对照组已成功验证，不代表所有场景的取消链路均通过。尤其 b3/b4 的主要发现是**成功复现缺口**；P6.5 总体的活动 TTS 取消状态仍为 GAP。

## 4. 关键事件时间线

测试使用 `asyncio.Event`、task handle 和实际网络数据推进各阶段，不依赖固定 `sleep` 推断取消时序。各组按可控屏障观察到以下顺序：

### 4.1 b1 正常完成

1. 公开 `AssistSatelliteEntity.async_accept_pipeline_from_satellite()` 入口启动真实 HA Pipeline，完成 STT → Intent → TTS。
2. P3 AstrBot SSE 发出正常结束事件，reader/handler 正常关闭；session Stop 调用次数为 0。
3. 流式文本达到阈值后创建文本 generator 和 TTSCache producer；producer 正常完成并写入缓存。
4. Pipeline 结束后读取 ResultStream token，发起 HTTP Proxy GET，得到 HTTP 200 / `audio/x-wav` 和完整 WAV 数据。
5. HA Wyoming writer 完成并断开 TCP；P7A TTS input/worker/collect task 完成，request reset，单连接 handler finally 执行。

### 4.2 b2 TTS 前取消

1. Pipeline 启动并收到 P3 SSE 的 `session_id`；P3 SessionManager 确认本轮会话，服务端保持 SSE 打开。
2. 取消公开 Satellite caller task。
3. caller 收到原样传播的 `CancelledError`；HA Satellite `_pipeline_task` 变为 done/cancelled，入口释放 task 引用。
4. P3 关闭 SSE reader/response，并对同一个已确认 session_id 调用 Stop 一次。
5. TTS 阶段未开始；虽然惰性 ResultStream/token 曾准备过，但 producer、文本 generator、Wyoming TTS writer 和 P7A TTS 请求均没有启动。

### 4.3 b3 活动 TTS 期间取消

1. SSE 文本达到流式 TTS 阈值，确认 TTSCache producer 与 `tts_input_stream_generator` 已创建。
2. HA Wyoming 已通过 TCP 发起实际流式 TTS；P7A 收到文本并停在第一个模型 callback 屏障。
3. TTS Proxy HTTP GET 已返回首字节且正在读取。
4. 只取消公开 Satellite caller；caller/Pipeline 被取消，P3 reader 关闭且同一 session Stop 一次，ResultStream token 映射删除。
5. **旧 TTSCache producer 仍 pending、文本 generator 仍持有 frame、GET response 未 EOF、HA Wyoming writer 仍 pending，P7A handler/request/input/worker 仍 pending。**
6. Pipeline 取消完成后释放 callback 屏障，P7A callback 仍接受 PCM；再向旧文本 queue 写入迟到文本后，模型 fake 再次收到 generate/callback。说明不只是 task 状态暂未刷新，旧生成链实际上仍可被继续推进。

### 4.4 b4 HTTP GET 单独断开与随后 Pipeline 取消

1. 复用同一真实流式链路，等待 HTTP GET 收到 WAV 首字节。
2. 只关闭 HTTP 客户端 response；Proxy 的 `ResultStream.async_stream_result()` iterator 退出。
3. 此时 caller/Pipeline 仍 pending、token 仍可查询、SSE 保持打开、Stop 为 0；TTSCache producer 和文本 generator 继续活动，consumer queue 仍登记；Wyoming writer、TCP 和 P7A request/session 未关闭。
4. 释放模型 callback，观察到 GET 已关闭后仍有下一次 TTS generation/callback。
5. 再独立取消 Pipeline caller；caller/Pipeline 取消、P3 reader 关闭且 Stop 一次、token 删除，但 TTSCache producer/generator/Wyoming/P7A 仍 pending，TCP disconnect 仍未触发。

测试 finally 中对遗留 task、HTTP response、Config Entry 和本地 fake 服务的显式清理只用于恢复测试环境，不能计作产品取消成功。

## 5. 任务 owner 与退出证据

| 对象 | 创建者 / 生命周期 owner | 正常结束 | TTS 前取消 b2 | 活动 TTS 取消 b3/b4 |
|---|---|---|---|---|
| Satellite caller task | 调用公开入口的调用者 | done | cancelled，CancelledError 传播 | cancelled |
| HA Satellite `_pipeline_task` | HA AssistSatelliteEntity；ConfigEntry 跟踪 | done，未取消 | done/cancelled | done/cancelled |
| PipelineRun / processor | HA PipelineRun，位于 Pipeline task 内 | 正常 cleanup/end | BaseException cleanup/end | cleanup 删除 TTS token；未关闭下游独立 producer |
| P3 SSE reader / HTTP response | AstrBot Conversation Agent 消费栈 | 正常关闭 | 关闭 | 关闭 |
| AstrBot session Stop | P3 Conversation Entity / session manager | 不调用 | 同一 session 一次 | 同一 session 一次 |
| HA ResultStream token | Pipeline processor 创建/持有 ResultStream | 缓存/响应按正常路径结束 | cleanup 后查询 None | cleanup 后查询 None；已有 GET 持有的 stream 引用不会因 token 删除自动失效 |
| TTS 文本 generator 与输入 queue | Pipeline processor 创建；交给 TTSCache producer 消费 | sentinel 后耗尽 | 未启动 | b3/b4 仍有 active frame；迟到文本还可推进 |
| TTSCache producer task | HA SpeechManager 通过 `hass.async_create_background_task()` 创建；task handle 未保存在 ResultStream/TTSCache | done | 未启动 | pending、未 cancelled |
| TTSCache HTTP consumer queue | TTSCache stream iterator 注册 | 读到结束 sentinel 后结束 | 未建立 | GET 提前断开后仍登记（b4）；这是 consumer cleanup，不等同 producer task |
| HTTP Proxy response iterator | 每次 HTTP GET 请求 | 完整读到 EOF | 未建立 | GET close 时 iterator 退出；不代表上游停止 |
| HA Wyoming TTS writer | Wyoming Config Entry 的 background task 集合 | done | 未启动 | pending；上游 reader 没有因 GET close/Pipeline cancel 自动断开 |
| Wyoming TCP handler | Wyoming server 每连接 handler task | 正常 disconnect 后完成 | 无 TTS 连接 | b3/b4 未触发 disconnect，不能判定下游连接清理结果 |
| P7A `_tts_task` / TTSStreamSession input/worker | 当前 WyomingEventHandler 与请求级 TTSStreamSession | SynthesizeStop 后完成并 reset | 未启动 | pending；b3/b4 未发生真实 TCP EOF |
| Sherpa callback/model worker | TTSStreamSession + 有界 executor；运行线程以取消 Event 协作停止 | 正常结束 | 未启动 | b3 callback 在取消后仍能输出；当前观察不是 P7A 已收到断连后的表现 |
| ESP32 音频输出 | 固件 `audio_output_manager`（最终输出 owner） | 实际播放完毕后状态回报 | 未连接/未测试 | 未连接/未测试 |

重要限定：
- HA ConfigEntry unload 可以清理其登记的 Wyoming writer，但这是配置卸载生命周期，不是当前对单轮 TTS 请求可用的定向取消入口；不能用卸载集成作为每轮打断方案。
- P7A 正常路径中收到 `SynthesizeStop` 是正常完成；HA/Pipeline 中止或 TCP EOF 才是取消/断连语义。
- 通过 token 查询得到 None 只说明映射删除；对已取得 ResultStream 的 HTTP consumer、producer 和 generator 不构成终止证据。

## 6. 后续模块职责决策

### 6.1 HA TTS Proxy / TTSCache：活动生成任务的首要 GAP

当前 HA Core 2026.11.0 的 TTSCache producer 由 TTS Manager 创建为 HA background task；b0 源码清点发现该 task handle 未保存在 ResultStream/TTSCache 中，b3/b4 的运行时测试确认 Pipeline cancel 和 GET disconnect 均未结束 producer。Pipeline processor cleanup 删除 token 映射，不会自动关闭已启动的文本 generator、producer 或已持有 stream 引用的 GET。

**决策：** 后续必须在实际拥有 producer 生命周期的 TTS Proxy/Cache 资源边界补充可访问的定向取消/关闭能力，并确保其同时关闭文本输入 generator 与当前 producer。后续设计先确认 HA Core 是否存在可用的受支持取消接口；若没有，另行评估由 Tivoo 自己持有 TTS 资源/producer 的可控适配边界。当前批不预设具体实现，不修改 HA Core，也不以 monkey patch、全局 task 扫描（例如 `asyncio.all_tasks()`）、猜测 task name、ConfigEntry 整体 unload 或删除 token 作为替代。

验收至少需要：取消后 producer/generator task 均 done；generator queue 被正确终止；不再接受迟到文本或 PCM callback；已建立 GET 按其自身响应关闭语义结束；旧任务清理完成后才能开始依赖同一音频资源的新 run。

### 6.2 HTTP TTS consumer：独立的登记清理问题

**决策：** HTTP GET close 只代表单个消费端停止下载，不代表用户取消对话，也不应由此取消仍可能被其他消费者使用的 producer。b4 发现提前断开后 TTSCache consumer queue 仍留在登记表中，因此后续需在 Cache consumer iterator 的创建/退出边界确保 queue 在 EOF、异常和客户端关闭时移除。这个工作与 producer task 的定向取消是两个独立合同，不能互相替代。

### 6.3 HA Wyoming writer 与 P7A TTS 请求

HA Wyoming TTS writer 由 Wyoming Config Entry 跟踪；其下游 TCP client 是响应音频 generator 的消费链。b3/b4 的 Pipeline cancel 没有让该 writer 关闭，因此也没有让 P7A 收到 disconnect。

**决策：**
- 只有在 TTS producer/stream owner 正确结束或关闭其输出流后，HA Wyoming writer 才应沿 generator finally 关闭对应 TCP client。
- P7A 继续只负责每条 Wyoming TCP 连接内部的 TTS request、TTSStreamSession、input/worker 和模型 callback；不承担 HA Pipeline、HTTP GET 或 AstrBot 的生命周期。
- P7A 现有单元测试已验证 stream generator cancel 会通知 callback 停止，模型线程以取消 Event 协作退出；提前 EOF 不会伪装成 SynthesizeStopped。正常 SynthesizeStop 与取消必须区别。
- 当前没有活动 TCP EOF 的 b3/b4 集成证据。后续 P7A 回归测试应直接断开正在合成的 TTS TCP client，并用事件/任务状态确认 handler、request task、input task、worker 和 callback 清理；若有残留，修复归 `services/sherpa_wyoming/run.py` / `providers/tts.py` 的连接/请求边界，不移入 Tivoo。

### 6.4 P3 AstrBot Conversation Agent

**决策：** `astrbot` 继续独占 SSE reader、HTTP response 和 owner session Stop。取消时先停止向 HA ChatLog 写入并关闭 SSE reader，再按 P3 合同对匹配的 session_id 调用一次 Stop；Stop 失败时保留取消传播，不声称远端已成功停止。Tivoo Satellite / audio session 不直接请求 AstrBot Stop，也不复制 P3 的 session owner 逻辑。P3 的 Stop 是 session 级语义，不是单独 run_id；同一 session 的并发串行化继续由 P3 负责。

### 6.5 Tivoo HA 集成与 P6 音频会话

- `tivoo/transport.py`：只处理 ESP32 TCP 7777/7778 传输、事件与连接状态，不持有 AstrBot、TTS producer 或 Wyoming 推理任务。
- `tivoo/assist_satellite.py`（P7 新增）：拥有 Assist Satellite 实体对 HA 公开 Pipeline 入口的调用生命周期，保留自己的 caller/run handle；中止时取消并等待公开入口对应的调用任务，让 HA 基类按公开生命周期收尾。不复制 HA 内部 Pipeline 调度器，不调用私有 `_pipeline_task`。
- `tivoo/audio_session.py`：现有 P6 的职责仍是 MIC session、PCM 有界缓冲与设备端停止通知。P7 可在此边界或其上层协调器关联 MIC session 和 Pipeline run，提供幂等取消、等待旧 run 收尾；新的 barge-in PCM 保持有界，在旧 run 完全结束前不得启动新的 STT Pipeline。不得在此模块扫描或猜测 HA TTSCache 后台 task。
- `tts_response_finished()`：只表示设备实际播放状态收尾，不是 Pipeline/TTS/AstrBot 的取消入口。

### 6.6 ESP32 最终音频输出与 P7/P8 阻塞范围

ESP32 的 `audio_output_manager` 是所有受控音源最终输出层的 owner。收到本地 near-end barge-in / AUDIO_STOP 时，固件应立即停止受控输出、清理本地待播 PCM，并并行通知 HA；不能等待网络、模型或 HA task cancellation 完成后才静音。

**阶段决策：**
- P7 可以继续做 I²S 麦克风、AEC/VAD、MIC_PCM 传输、HA Satellite 接入以及不依赖活动 TTS 中断的正常对话路径。
- P7 完整 barge-in 验收（旧 Pipeline、TTS Proxy、Wyoming 和 AstrBot 同时正确终止，且新输入不会与旧 run 重叠）保持 **BLOCKED**，直到 HA TTS producer owner 缺口有单独设计并有测试证明。
- P8 的解码/DAC/AUX 与设备端立即停止功能可以独立实施；但依赖 HA 活动 TTS 取消的端到端打断、无迟到 PCM 和完整 P8 收尾验收保持 **BLOCKED**。
- 不把这个 GAP 扩大成阻止所有 P7 音频输入工作的理由，也不因设备端可以立即静音就认为上游生成已取消。

## 7. 测试命令与结果索引

以下为 b1–b4 报告记录的本机测试命令和结果。测试文件随着每个批次增加用例，故生命周期文件与 HA 全量测试的通过数按批次变化；每一项均来自对应批次完成时的独立运行记录。

| 批次 | 命令 | 结果 |
|---|---|---|
| b1 | `./scripts/test-ha.sh tests/homeassistant/test_assist_pipeline_tts_cancellation.py -q` | 1 passed |
| b1 | `./scripts/test-ha.sh tests/homeassistant` | 318 passed, 75 warnings |
| b1 | `./scripts/test-sherpa-wyoming.sh` | 128 passed, 1 warning |
| b2 | `./scripts/test-ha.sh tests/homeassistant/test_assist_pipeline_tts_cancellation.py -q` | 2 passed |
| b2 | `./scripts/test-ha.sh tests/homeassistant/custom_components/astrbot/test_conversation.py -q` | 12 passed |
| b2 | `./scripts/test-ha.sh tests/homeassistant -q` | 319 passed, 76 warnings |
| b2 | `./scripts/test-sherpa-wyoming.sh` | 128 passed, 1 warning |
| b3 | `./scripts/test-ha.sh tests/homeassistant/test_assist_pipeline_tts_cancellation.py -q` | 3 passed |
| b3 | `./scripts/test-ha.sh tests/homeassistant/custom_components/astrbot/test_conversation.py -q` | 12 passed |
| b3 | `./scripts/test-ha.sh tests/homeassistant -q` | 320 passed, 77 warnings |
| b3 | `./scripts/test-sherpa-wyoming.sh` | 128 passed, 1 warning |
| b4 | `./scripts/test-ha.sh tests/homeassistant/test_assist_pipeline_tts_cancellation.py -k http_tts_proxy_disconnect -q` | 1 passed |
| b4 | `./scripts/test-ha.sh tests/homeassistant/test_assist_pipeline_tts_cancellation.py -q` | 4 passed |
| b4 | `./scripts/test-ha.sh tests/homeassistant/custom_components/astrbot/test_conversation.py -q` | 12 passed |
| b4 | `./scripts/test-ha.sh tests/homeassistant -q` | 321 passed |
| b4 | `./scripts/test-sherpa-wyoming.sh` | 128 passed |

b1–b4 每批也记录了相应 HA / Sherpa 虚拟环境内的 Ruff check、format check；按测试文件/辅助代码需要执行了 `py_compile`，最终修改前执行 `git diff --check`，均为 PASS。HA warnings 为当时依赖组合的 deprecation、NotAppKey 及 pytest_socket 预期拦截提示；Sherpa warning 为 `audioop` deprecation，不是测试失败。完整命令输出与边界解释见各批报告。

## 8. 文件范围与阶段状态

- b0–b4 的测试代码和报告均保留在各自批次提交中；b5 只新增本汇总报告、b5 计划/ledger，并更新 README 与本 patch 的状态/结果索引。
- 本批不修改 HA Core、`homeassistant/custom_components/tivoo/`、`homeassistant/custom_components/astrbot/`、`services/sherpa_wyoming/`、ESP32 固件或任何生产逻辑。
- 本批不重新运行已由 b1–b4 报告记录的测试；只对 b5 文档做 diff、链接、范围与格式验证。后续代码修复必须按新批次独立计划实施并增加针对 owner 的回归测试。
- P6.5 的前置调查阶段：**COMPLETE**。
- 活动 TTS producer/generator cancellation：**GAP / NOT FIXED**。
- HTTP consumer queue cleanup：**GAP / NOT FIXED**。
- P7A 活动 TCP EOF handler 端到端验证：**BLOCKED / NOT PROVEN**。
- P7 正常 MIC/STT 与非打断路径：可继续；完整 HA barge-in 验收：**BLOCKED**。
- P8 设备端输出链路可独立实施；依赖 HA 取消的全链路打断验收：**BLOCKED**。

## 9. 权威依据与批次记录

- [P6.5 原始前置验证 patch](../patches/2026-11-11-p6-5-ha-cancellation-preflight.patch.md)
- [b0 环境与任务 owner 清点](2026-11-13-p6-5b0-cancellation-task-ownership-inventory.md)
- [b1 正常完成控制组](2026-11-13-p6-5b1-normal-completion-control-group.md)
- [b2 TTS 前取消](2026-11-13-p6-5b2-pre-tts-cancellation.md)
- [b3 活动 TTS 取消 GAP](2026-11-13-p6-5b3-tts-proxy-active-cancellation.md)
- [b4 HTTP GET consumer 对照](2026-11-13-p6-5b4-http-consumer-disconnect.md)
- [P3 AstrBot Conversation 合同](../specs/2026-11-09-p3-astrbot-conversation-contract-matrix.md)
- [STT/TTS 端到端规格](../specs/2026-11-09-stt-tts-end-to-end-pipeline-spec.md)
- [P7A Sherpa/Wyoming 合同](../specs/2026-11-10-p7a-sherpa-wyoming-contract-matrix.md)
- [P6 ESP32 ↔ HA 双向通信合同](../specs/2026-11-12-p6-esp32-ha-bidirectional-contract-matrix.md)
