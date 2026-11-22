# P6.8 B8.2 — Qwen GCP、HA PCM 边界与本地 HTTP 预检报告

> 日期：2026-11-22
> 分支：feature/p6-8-s3-local-wake
> 基线：efb12029650cc253577fed990893d60c6845b962
> 范围：仅 B8.2。没有修改 HA / ESP32 生产桥接，没有部署 MCP，没有执行设备播放。
> 结论：**协议、VAD 尾帧、标点、同 socket 连续对话、重连恢复、会话隔离及 owner lease 预检通过。** 输入音频是本地现有测试 WAV 与离线生成样本，不是 Tivoo 实机录音；本报告不代表物理播放验收。

## 1. NAS 锁定版本与运行配置（只读）

| 项目 | 实测 |
|---|---|
| 容器 | qwen-audio-agent |
| 镜像 tag | local/qwen-audio-agent:2.1.0 |
| 镜像 digest | sha256:4a64b7fee162d368a65aba63af61e3d61c9ddb23c14a24a0cdd9a3954fcf5faf |
| Agent / Gateway 协议 | Qwen Audio Agent 2.1.0 / GCP 7.0.0 |
| Provider / 模型 | DashScope / qwen3.8-omni-flash-realtime |
| profile / turn detection | omni-v2 / semantic_vad_ec |
| 输入 / 输出 | 16 kHz mono PCM16 / 24 kHz mono PCM16 |
| DashScope provider adapter SHA256 | 86e183bbd2c82ebc669d28410a9f695eab8af0525642209644fe79576d19af7c |

运行中的 Gateway 健康检查为 ready。每轮测试结束后均核对 owner 状态；最终 inputActive=false，活动客户端列表为空。

本批只在 Qwen 容器内部读取运行时 Gateway 凭据并建立认证 WebSocket。没有把 Token 导出到开发机、日志、报告或 Git。

## 2. GCP 7.0 与 HA / ESP32 PCM 边界

### 2.1 客户端协议

以 NAS 安装包中的实际 schema 和运行时为准：

- 客户端先发 session.hello，协商协议 7.0.0，声明独立 client.instance_id 与 input.audio。
- Gateway 以 session.ready 返回 URL 中的 sessionId，并以 voice.ready 提供输入采样率。
- 音频输入使用已实现的 input_audio_buffer.append；Gateway 内部归一化为 audio.append。
- 锁定版 GCP 7.0 客户端 schema 不包含可用的 input_audio_buffer.commit。本批没有发送该事件，也没有猜测其他提交事件。
- voice.ownership=active 是当前前台 owner 的 lease 状态；本批不请求 takeover。
- Gateway 的 audio.done 是某个模型 response 的生成终态，不等于 Tivoo 物理播放完成。

真实握手中的 session.ready 与 session.hello event_id 匹配，session_id 与 WebSocket URL 隔离键一致，voice.ready.inputSampleRate=16000，主测试客户端取得 active ownership。

### 2.2 P6.8 PCM 输入契约

只读检查当前 P6.8 的 audio_session.py、transport.py、ESP32 audio_frontend.c：

- ESP32 microphone frame 为 16 kHz、mono、S16LE、20 ms。
- 每帧 320 个 int16 samples，即 640 bytes。
- HA ingress 验证相同的 16 kHz / S16LE 格式，并由匹配 MIC session 按序消费 PCM。
- 本批探针按完全相同的 20 ms / 640-byte 帧格式发送音频。

探针不连接 HA，不创建 HA 临时 PCM HTTP 资源，不调用 TTS_PLAY，不连接 UART/SPP，不访问 ESP32。收到的 audio.delta 仅解码并计数后丢弃；没有写入或播放设备。

### 2.3 本地 HTTP PCM 输出边界（只读预检）

对当前 P6.8 生产合同和 test/qwen-realtime-audio-bridge worktree 做了只读比对：

- 当前 P6.8 的 TtsResourceManager 只接受 HA TTS Proxy 相对路径（/api/tts_proxy/），再通过 HA internal URL 转成设备可访问 URL；TTS_PLAY 由当前 Esp32ConnectionAdapter 发送。它不是通用的 Qwen raw-PCM stream server。
- 当前 P6.8 的 async_send_tts_play() 支持 session_id。local-wake 模式下，transport 会要求 TTS_PLAY 的 session_id 与 AudioSessionManager 当前 active MIC session 一致；没有匹配身份会拒绝播放。这是 P6.8 生产合同，不应被试验分支绕开。
- 试验分支的 TivooQwenPcmView 使用 /api/tivoo/qwen/audio/{stream_id}、audio/x-tivoo-pcm-s16le-32000-mono、Cache-Control: no-store、单次 GET（重复 409、未知 404）和最大 128 个 chunk 的有界队列；URL 由 HA internal URL 构造，view 设置 requires_auth=False，随机 UUID stream_id 作为一次性能力 URL。当前分支没有安装此 route。
- 试验分支 QwenRealtimeBridge._open_output() 调用 async_send_tts_play() 时没有传当前 MIC session_id；该试验分支的旧 adapter 也没有此参数。把它原样移植到当前 P6.8，会违反当前 local-wake TTS_PLAY session fence，必须在 B8.5 按当前 adapter 合同传入正确的 session_id。
- 试验分支 24 kHz → 32 kHz 使用自制 Pcm16LinearResampler；它只作为试验记录，不应作为生产方案，SRC 继续由 B8.4 复用 ESP Audio Effects 实现。
- 试验分支 QwenPcmStream.finish() 通过 await queue.put(None) 投递结束标记；若队列已满且 HTTP 消费者未连接/已断开，结束阶段可能继续等待队列空间。B8.5 实现有界 PCM HTTP 资源时应明确 consumer disconnect / producer cleanup 的终止策略。

本批只审阅了上述路由、队列、MIME、内部 URL 和 TTS_PLAY 身份合同，没有在 test worktree 或当前 HA 安装中部署、运行或修改它们。B8.2 的实时验证范围是 Gateway WebSocket 输入/响应，不包含 HTTP PCM 输出或真实 ESP32 播放。

## 3. 本地 VAD EOF 与静音尾帧

### 3.1 样本来源与方法

使用两类既有测试音频：

1. 仓库 AISHELL3 VITS 模型离线生成的中文短句、长句、追问/回答句，原始 8 kHz mono PCM16，转换为 16 kHz。
2. 仓库现有 Paraformer STT 基准的三个 16 kHz mono PCM16 WAV：0.wav、1.wav、2-zh-en.wav。

WAV 尾部生成静音先裁剪，只保留最后一个 20 ms 边界帧；探针按 ESP32 帧大小发送音频，并在模拟本地 speech_end / iterator EOF 后追加连续零值 PCM。输出音频从未回送输入，因此不会把播放回声混入当前 turn。

这验证的是本地 VAD EOF 后的 PCM 边界及 Gateway VAD 响应，不等同于 Tivoo 实机麦克风声学验收。

### 3.2 尾帧时长扫描

短句控制样本“好的，已完成。”使用独立 session 测试：

| EOF 后附加静音 | 结果 | 观察 |
|---:|---|---|
| 240 ms | FAIL | Provider 有 speech_started，60 秒内没有 speech_stopped / 最终响应，最终以 provider response-stream timeout 收口 |
| 400 ms | FAIL | 没有完整 assistant final / response audio 终态 |
| 500 ms | FAIL | 没有完整 assistant final / response audio 终态 |
| 560 ms | FAIL | 没有完整 assistant final / response audio 终态 |
| 580 ms | FAIL | 没有完整 assistant final / response audio 终态 |
| 600 ms | PASS（该样本） | 得到 user/assistant transcript.final、response.started、audio.delta、audio.done |
| 800 ms | PASS（该样本） | 得到完整转写与匹配音频终态 |
| 1000 ms | PASS | 在后续不同语料测试中保持稳定 |

600 ms 对部分中文自然语音样本通过，但不能覆盖所有测试：英文短句 600 ms 未能触发端点，1000 ms 时正常收口。故统一候选采用 **1000 ms（50 帧、32,000 bytes）**，不把 600 ms 视为所有语言/语速下的通用值。1000 ms 是本次跨语料验证的最小已确认统一候选；本批未穷举 880–980 ms 所有档位，不宣称数学意义上的全局最短值。

### 3.3 1000 ms 候选覆盖

| 输入类别 | 次数 | 结果 |
|---|---:|---|
| 中文短句 | 多次 | PASS |
| 中文长句 | 多次 | PASS |
| 句中插入 500 ms 停顿的中文长句 | 1 | PASS，仍为一个完整用户 turn |
| 背景噪声混合（18 dB SNR）中文长句 | 1 | PASS |
| 50% 振幅中文长句（相对原样本降约 6 dB） | 1 | PASS |
| 25% 振幅中文长句（相对原样本降约 12 dB） | 1 | FAIL，Provider 未产生可用 speech turn；属于输入声压/检测边界，不是尾帧处理成功 |
| Paraformer 既有中文样本 0.wav | 1 | PASS |
| Paraformer 既有中文样本 1.wav | 1 | PASS |
| Paraformer 既有中英混合样本 2-zh-en.wav | 1 | PASS |
| 英文单句语音输入 | 1 | PASS，1000 ms；600 ms 未通过 |

三个 Paraformer 基准样本均以原始 16 kHz mono PCM16 发送，没有额外重采样。成功样本均产生 voice.state=processing、非空 user/assistant transcript.final、response.started、audio.delta 与匹配的 audio.done；audio.delta.sampleRate 实测为 24,000 Hz。

### 3.4 端点延迟统计

统计口径：从探针发送完最后一个语音帧，到 Gateway 公共 voice.state=processing 的时间差。数据来自独立 session，不含失败项。

| EOF 静音尾帧 | 样本数 | P50 | P95 | 最小 / 最大 |
|---:|---:|---:|---:|---:|
| 600 ms | 10 | 691.5 ms | 971.5 ms | 468 / 1084 ms |
| 800 ms | 1 | 804 ms | 804 ms | 804 / 804 ms |
| 1000 ms | 10 | 868.5 ms | 922.1 ms | 753 / 959 ms |

以上是当前有限测试集的描述性统计，不是生产麦克风下的置信区间。1000 ms 尾帧覆盖本批端点延迟 P95，并留下约 78 ms 的尾帧余量。

## 4. Assistant 最终文本与问号保真

判断对象仅是当前 generation 的 Gateway transcript.final；没有使用 transcript.delta 或用户侧文本推断 assistant 意图。

| 场景 | 实际 Gateway assistant final | 结果 |
|---|---|---|
| 英文自然语音输入 | “Oh, I can’t really give you an exact time ... What’s your goal with English?” | 末尾为 ASCII ?，PASS |
| 中文要求问句 | “你每天能练习多久？” | 保留全角 ？，PASS |
| 普通陈述 | “练个十分钟，跟往水里扔块石头似的，连个响儿都没有。” | 保留中文句号，PASS |
| 用户 transcript 自己带问号 | assistant final 为“收到。” | role=user 的问号未被误判为 assistant 续聊标记，PASS |

每个成功场景的 assistant transcript.final 都带匹配的 turnId 和 responseId；对应 audio.done.responseId 完全匹配。模型输出 PCM 采样率为 24 kHz。

## 5. 同一 WebSocket 连续对话、重连恢复和会话隔离

### 5.1 同一活动 WebSocket 三轮

最终加强断言复跑（sessionId=p68-b82-context-final-20261122，client.instance_id=tivoo-p68-b82-final-instance）在同一条 GCP 7.0 WebSocket 上连续完成三轮语音输入/响应：

- 三轮 session_id 和 client.instance_id 保持不变；同一 GatewayConnection 对象和底层 WebSocket 跨三轮保持活动。新版探针输出的 probe_socket_marker 只是本地探针标识，不宣称它是 Gateway 分配的 connection ID。
- 三轮 turnId 分别为 voice-1795346178497-1、voice-1795346190697-2、voice-1795346202140-3；assistant responseId 每轮唯一，三轮均有非空 audio.delta 和匹配 audio.done。
- 第一轮真实触发两个工具事件及两个 response/audio.done（第一个 response hasFunctionCall=true 且没有音频，随后 agent response 产生音频）；探针没有把中间 response 误认为最终回复，仍在同一 socket 上继续第二、三轮。
- 第二轮用户转写包含吉他零基础和每天约 20 分钟；第三轮 assistant 给出针对吉他的第一周练习计划，之后断开重连的第四轮又能基于相同上下文生成有针对性的练习安排。
- 三轮结束后原 WebSocket 仍 OPEN，journal 有 6 条消息；关闭后仍是 6 条。每轮 assistant final 的 turnId 与同轮 user final 一致，responseId 对应非空 audio.delta 与 audio.done。

这是方案 A 即时续聊必须采用的连接连续性路径。只复用 sessionId 字符串、关闭 socket 后再新建连接，不能替代同一活动 socket。

### 5.2 Lease 冲突

主 socket 保持 active 时，使用另一个 client.instance_id 连接同一 owner：

- 最终加强断言复跑时，第二客户端收到 Gateway client_occupied（Gateway already has an active Client connection），探针将其断言为 rejected_client_occupied。
- 没有请求 takeover。
- 主连接仍保持 OPEN，健康接口仍报告一个 active embedded Client；同 socket 三轮运行期间均未更换底层连接。

### 5.3 断开重连 journal 恢复

- 最终加强断言复跑中，主连接关闭前和关闭后 session history 都是 6 条消息。
- 使用相同 sessionId 和相同 client.instance_id 新建连接，Gateway history 仍有 6 条。
- 新连接再次询问第一周计划，assistant 继续使用吉他 / 20 分钟上下文。
- 重连后的新 turn 正常追加，history 增至 8 条。

### 5.4 新 session 隔离

- 最终加强断言复跑使用新的 sessionId=p68-b82-isolation-final-20261122，连接前后 history 都为 0。
- 新 session 单独询问第一周计划，模型返回通用编程练习计划，没有继承原 session 的吉他内容；独立回答后自身 history 为 2 条。

以上分别验证了 journal/history 重连恢复和新 session 隔离。重连恢复只覆盖独立新 wake / 重连场景；不能取代即时续聊对原活动 socket 的复用。

## 6. 可重复探针与自动化测试

本批新增：

- tests/integration/qwen_realtime/gateway_probe.mjs：直接连接现有 Gateway，支持单轮、尾帧扫描、同 socket 多轮、重连、隔离、lease 冲突。输入 PCM 由 stdin 传入，输出 JSON 证据。模型音频仅计数并丢弃。脚本会拒绝缺少 user/assistant final、turnId 不一致、缺少非空 audio.delta / audio.done、第二 owner 未被拒绝、socket 未保持活动或 session journal 丢失的结果。
- tests/integration/qwen_realtime/probe.py：本地 PCM 格式化、20 ms 分帧、静音尾帧、音量、停顿、噪声、尾静音裁剪和 WAV 重采样辅助函数。
- tests/integration/qwen_realtime/generate_fixtures.py：复用仓库 AISHELL3 VITS 模型离线生成语音夹具；音频保存在 Git 忽略的 .superpowers/sdd/.../fixtures/。
- tests/integration/qwen_realtime/test_probe.py：12 项单元测试通过，覆盖 20 ms / 640-byte 分帧、PCM 对齐、尾帧时长、音量裁剪、停顿插入、噪声确定性、尾静音边界及 8 kHz→16 kHz 重采样。

本地命令：

    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -c /dev/null -p no:cacheprovider tests/integration/qwen_realtime/test_probe.py -q
    node --check tests/integration/qwen_realtime/gateway_probe.mjs
    .venv/bin/ruff check tests/integration/qwen_realtime/*.py
    .venv/bin/ruff format --check tests/integration/qwen_realtime/*.py

实时探针在 NAS 容器内运行。重复测试时通过 SSH stdin 将 gateway_probe.mjs 放入容器临时路径，再通过 docker exec -i ... node /tmp/p68-b82-probe.mjs 接收本地 JSON/PCM 输入；Token 只由容器内部进程读取。

## 7. 回归、限制与安全收尾

- **生产代码：** 没有修改 homeassistant/custom_components/tivoo、ESP32 固件、MCP 集成或其他生产桥接。
- **NAS：** 没有修改 compose、镜像、环境变量、HA 配置或持久化配置；只在 Qwen 容器 /tmp 放置本批临时探针，收尾时删除。
- **音频：** 没有连接真实 ESP32，没有发送 TTS_PLAY、HTTP PCM 播放请求或 UART/SPP 控制指令。模型输出音频在探针内丢弃。
- **输入限制：** 既有 STT WAV 和本地合成样本可验证 GCP PCM/VAD 边界，但不等同于 Tivoo 实机 AFE 输出声压/噪声分布；实机麦克风与物理播放仍须后续硬件验收。
- **HTTP/SRC 限制：** B8.2 只读核对了试验分支 HTTP PCM view 与当前 P6.8 TTS_PLAY session fence，没有发起实际 HA HTTP GET 或 ESP32 播放。试验分支输出队列结束标记潜在等待问题、缺少 session_id 的 TTS_PLAY 调用和线性 SRC 均记录为后续 B8.5 / B8.4 的实现约束，不在 B8.2 修复。
- **低声压边界：** 当前样本 50% gain 可通过，25% gain 未能触发 Provider speech turn。不得仅凭本批结果承诺低于该输入电平也能可靠识别。
- **HA 回归：** 使用项目入口 PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath" bash scripts/test-ha.sh tests/homeassistant -q -p no:cacheprovider，结果 592 passed、270 warnings。
- **ESP32 host 回归：** 使用 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -c /dev/null -p no:cacheprovider tests/esp32 -q，结果 117 passed、1 failed。唯一失败为既有 tests/esp32/test_p6_device_status.py::test_device_status_ping_events_and_p6_error_codes：模拟器执行 audio fetching playback-42 后，status.audio_resource 仍为 idle / playback_id=None，而测试期望 fetching / playback-42；独立重跑仍复现。B8.2 未修改该测试、模拟器或 ESP32 生产代码，因此不在本批修复范围。
- **Sherpa Wyoming 回归：** 使用 bash scripts/test-sherpa-wyoming.sh，结果 140 passed、1 warning。
- **B8.2 新增测试与静态检查：** tests/integration/qwen_realtime 单元测试 12 passed；Ruff check、Ruff format --check、Node --check 和 git diff --check 通过。最终同 socket/lease/reconnect/isolation 真实 Gateway 加强断言复跑成功，报告输出摘要保存在被忽略的 fixtures/same-socket-final-output.json。
- **测试入口说明：** 一次裸 pytest 尝试没有使用项目的专用 HA / Sherpa 测试入口，产生环境路径/依赖导入错误；随后按仓库已有脚本和独立虚拟环境重跑对应子集，以上述结果为准。

## 8. B8.2 结论

- GCP 7.0 真实输入事件、16 kHz PCM、24 kHz 输出和 VAD EOF 尾帧路径均得到 NAS 运行实例证据。
- 1000 ms 零值 PCM 尾帧作为当前跨语种/语料候选通过；较短档位的覆盖不一致。
- assistant final 中全角 ？、ASCII ? 和普通句末标点均得到真实 transcript.final 验证；用户侧问号不误触发 assistant 意图。
- 同一活动 WebSocket 多轮上下文、断开重连恢复、新 session 隔离和 owner lease 冲突均通过。
- 没有发送未实现协议事件，没有部署生产桥接，没有触发真实 Tivoo / ESP32 声音。

**B8.2 Gate：PASS。** 独立代码审查记录见 [B8.2 Probe 代码审查](2026-11-22-p6-8-b8-2-probe-code-review.md)。后续 B8.5 / B8.6 的文本问号续聊实现可按原计划进入后续批次；本报告不代表 B8.3 MCP、B8.4 SRC、B8.5 / B8.6 HA 生产实现或 B8.7 NAS 部署已经完成。
