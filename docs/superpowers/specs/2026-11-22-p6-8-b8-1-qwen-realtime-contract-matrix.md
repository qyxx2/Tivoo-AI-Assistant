# P6.8 B8.1：Qwen Realtime 迁移合同矩阵

> **审查状态：产品策略已决策；B8.2 预检 PASS；B8.5/B8.6 仍须核销下述实现门禁。** 本矩阵仅记录当前代码、锁定上游协议和用户已明确选择的方案 A；不把项目级标点约定虚构为 Qwen 原生授权接口。
> 本文只记录当前 P6.8 代码与锁定上游协议能够证明的接口和边界。B81-Cxx 是本次审查追踪编号，不是新增运行时 API。凡尚不存在的接口均明确标为缺口，不预先分配路径、事件名或字段。

## 1. 审查范围与证据基线

| 项目 | 核验基线 |
|---|---|
| P6.8 工作树 | feature/p6-8-s3-local-wake；原审查基线 9be427d；本次补充基线 be9b93e（B8.2 已提交） |
| P6.8 新合同 | P68-HB 15 条 + AFE 12 条 + VOICE 10 条 + LIFE 8 条 + VIEW 4 条 = 49 条 |
| 旧合同 | B0.6 交叉审查记录 192 条旧合同及 19 条 H 项；本次只审阅受影响关系 |
| Qwen 上游 | QwenAudio/qwen-audio-agent v2.1.0；commit a9f4478da8df400d04facbb099ac2933ce8b11bc |
| Qwen 协议 | Gateway Client Protocol 7.0.0；以 v2.1.0 tag 源码和该 tag 文档为准 |
| HA MCP | 项目 P4 合同与现有 Assist MCP HTTP 测试；入口为既有 /api/mcp/assist |
| Qwen Omni | Alibaba Cloud Qwen-Omni-Realtime 在线协议文档；Provider 协议与 GCP 客户端协议分层 |

P6.8 证据文件：
- homeassistant/custom_components/tivoo/audio_session.py
- homeassistant/custom_components/tivoo/assist_satellite.py
- homeassistant/custom_components/tivoo/audio_resource.py
- homeassistant/custom_components/tivoo/transport.py
- homeassistant/custom_components/tivoo/__init__.py
- esp32/firmware/main/audio_resource.c
- esp32/firmware/main/audio_playback.c
- esp32/firmware/managed_components/espressif__esp_audio_effects/include/esp_ae_rate_cvt.h

Qwen v2.1.0 证据文件：
- shared/protocol/gateway-client-protocol.mjs
- shared/protocol/realtime-events.mjs
- shared/protocol/gateway-events.mjs
- server/src/transport/gateway-client-transport.mjs
- server/src/voice/realtime-session-runtime.mjs
- server/src/voice/realtime-input-runtime.mjs
- server/src/voice/realtime-presentation-runtime.mjs
- server/src/session/session-journal-registry.mjs
- server/src/app/session-conversation-history.mjs
- server/src/frontend/tools/mcp/frontend-mcp-config.mjs
- server/src/frontend/tools/mcp/frontend-mcp-client.mjs

## 2. B8.1 项目级合同矩阵

| ID | 现有接口 / 源码依据 | 审查结论与合同边界 | 状态 |
|---|---|---|---|
| B81-C01 | HA AudioSessionManager.audio_subscription(session_id, start, consumer, on_pull, on_eof)；AssistSatellite 当前 turn runner | 复用现有 HA 内部 Python 订阅游标，获取当前 local-wake 轮次的有序 PCM。它不是新的 HTTP API。保留 session_id 过滤、按 offset 顺序、EOF drain 和 consumer close 语义；不得上传旧轮、提示音或下一轮 PCM。 | CONFIRMED |
| B81-C02 | Qwen Gateway Client Protocol：/api/realtime、session.hello、session.ready、voice.ready、session.ping/session.pong | GCP 握手使用 protocol min/max 7.0.0、client.type/version/instance_id 和 capabilities。voice.ready.inputSampleRate 是 Gateway 返回的输入采样率；必须等待 session.ready 与 voice.ready 后再发 PCM。只有协商 session.heartbeat 后才按 request_event_id 回复 session.pong。 | CONFIRMED |
| B81-C03 | GatewayClientProtocolEvent.INPUT_AUDIO_APPEND；GatewayClientEvent.AUDIO_APPEND；V6_CLIENT_EVENT_ALIASES | 客户端线上事件名是 input_audio_buffer.append，payload 含非空 base64 audio。Gateway 再将其归一化为内部 audio.append。audio.append 是 Gateway 内部事件名，不是客户端线上事件名。 | CONFIRMED |
| B81-C04 | GCP 客户端事件集合；realtime-input-runtime.mjs Provider 事件处理；P6.8 audio_session.py speech_end/input_finished/drain | GCP 7.0 客户端协议没有 input_audio_buffer.commit、speech_end、speech_stopped 或 voice.end。input_audio_buffer.speech_stopped / committed 属于上游 Provider 事件，不能由 HA Client 发送。HA 本地 speech_end 结束本地 PCM ingress，消费者仍须 drain 到 EOF；模型端点由 Gateway/Provider VAD 决定。B8.2 已验证 EOF 后追加 1000 ms 零值 PCM（50 帧）；这是有限语料候选，不是实机声学保证。早端点处理见 §2.1。 | 预检 PASS；生产接入归 B8.5 |
| B81-C05 | Gateway public server event schema；realtime-presentation-runtime.mjs | 已公开事件包括 voice.ready、voice.state、turn.started、response.started、audio.delta、audio.done、response.interrupted、transcript.delta/final/discard、tool.call。audio.delta 含 audio、sampleRate、responseId；audio.done 只含 responseId。没有公开的 GCP response.done。工具调用前的 audio.done 可能只是中间 response 终态，不能据此关闭整个 HA turn 或输出流；最终响应与异常终态的可观测性见 §2.1。 | PARTIAL；终态判定待核销 |
| B81-C06 | gateway-client-transport.mjs URL query sessionId；session-journal-registry.mjs ownerId + sessionId；Tivoo __init__.py ConfigEntry.entry_id | Qwen 对话历史由 WebSocket URL 的 sessionId query 标识，持久化按 ownerId + sessionId 分区；它不是 HA ChatSession。当前 Tivoo AssistSatellite 每轮新建 HA Context()，Tivoo 集成没有调用 ChatSession。项目映射采用稳定 ConfigEntry.entry_id 作为 Qwen sessionId；client.instance_id 使用 tivoo-<ConfigEntry.entry_id>。ownerId、sessionId、client.instance_id、设备 MIC session_id、HA Context.id、playback_id 彼此独立。此项是基于现有 ID 和 Gateway 规则作出的项目映射决策，不声称 HA 存在 ChatSession 接口。 | CONFIRMED（项目映射） |
| B81-C07 | P4 MCP 合同 §2.1；test_tivoo_p4b5_mcp_http.py；HA Core Assist MCP | 复用 HA 原生 /api/mcp/assist，MCP Streamable HTTP 与 Authorization: Bearer。Qwen Frontend MCP Client 使用标准 tools/list 和 tools/call 调用既有 HA 工具。不得另建 Tivoo MCP 路由、第二个 MCP Server 或用 GCP Client Action 代理 MCP。生产 allowlist 必须以 NAS 实际 tools/list 为准，不能冻结开发测试 fixture 的工具数量。 | CONFIRMED |
| B81-C08 | P4 MCP 合同 §2.1；HA Assist MCP 与 LLM Tools；Qwen normalizedPolicy | /api/mcp/assist 不是只读路由。访问边界来自 HA 用户身份、Assist 实体暴露范围、LLM Tool 注册和 Service 自身校验。Qwen Frontend MCP 配置明确拒绝 readOnly / approval 字段；不得把它们写成有效策略。写操作权限与确认必须由实际 HA Tool/Service 约束。 | CONFIRMED |
| B81-C09 | Qwen frontend-mcp-config.mjs normalizedUrl() | v2.1.0 只允许 HTTPS 远程 MCP；HTTP 仅对无额外 header 的 loopback 放行。LAN HTTP 加 Bearer header 当前会被拒绝。Streamable HTTP 与 header 环境变量引用已经支持。B8.3 已交付并测试 RFC1918 IPv4 HTTP + Bearer 的显式 opt-in 最小补丁，默认关闭；未全局放开 HTTP。NAS 运行安装包未修改，部署与真实 HA MCP 验收仍归 B8.7。 | 软件 PASS（B8.3）；部署待 B8.7 |
| B81-C10 | P6.8 transport.py async_send_tts_play；audio_resource.py build_internal_tts_url / TtsResourceManager；ESP32 audio_resource.c | 现有设备控制使用 TYPE_TTS_PLAY 0x30，携带 playback_id、url、mime_type，可包含既有 session_id；设备再通过 HTTP GET 拉取 URL。当前 HA URL 构造器只接受 /api/tts_proxy/ 相对路径，TtsResourceManager 只消费 HA Pipeline TTS 事件。生产代码没有供 Qwen audio.delta 使用的通用 PCM HTTP stream 路由。不得把试验 worktree 的路径写成现有合同，也不在 B8.1 臆造新路径。 | PARTIAL；raw PCM HTTP 资源不存在 |
| B81-C11 | Qwen audio.delta.sampleRate；ESP32 audio_playback.c configure_src()/output_frame()；ESP Audio Effects SRC API | 必须按每个 audio.delta 的 sampleRate 判断输入格式，不能把 24 kHz 写死为协议字段。ESP32 输出总线为 32 kHz mono；现有 esp_ae_rate_cvt_open/process/get_max_out_sample_num/close 已用于 MP3 解码路径，但不能据此推断 raw PCM 路径已支持 24→32 kHz。B8.4 需将有状态 SRC 接入 raw PCM 路径，并验证分块连续性、EOF 和 generation 隔离。 | PARTIAL；归 B8.4 |
| B81-C12 | Qwen response.cancel → 内部 GatewayClientEvent.INTERRUPT；realtime-session-runtime.mjs toolScope；frontend-mcp-client.mjs execute(signal)；P6.8 LIFE-C02/C03 | GCP 客户端取消事件名是 response.cancel，Gateway 内部归一化为 interrupt。该事件会取消 Provider response 并清除 Gateway playback。Frontend MCP 请求使用连接级 toolScope.signal；v2.1.0 只在 Gateway session close/disconnect 时 abort 该 signal，单独 response.cancel 不保证停止进行中的 MCP 请求。HA 必须先失效旧 generation、定向停止匹配播放，再发送 response.cancel 并关闭/回收旧 socket。已执行的 HA Service 副作用没有通用回滚保证，非幂等调用不得盲目自动重试。 | CONFIRMED（取消边界） |
| B81-C13 | Qwen responseId / turnId / tool.call.callId；ESP32 TYPE_AUDIO_STATE 0x32；P6.8 LIFE-C04/C06 与 VIEW-C02 | Gateway audio.done 表示模型 response 的音频生成结束，不代表 HTTP 流已被设备拉完，更不代表 ESP32 已播放完成。物理状态以匹配 playback_id 的 ESP32 AUDIO_STATE playing/completed/failed 为准。tool.call 的 callId、responseId、turnId 也各自独立，不可伪造成 HA Context.id 或 playback_id。VIEW-C02 tooluse 可由当前 generation 的真实 tool.call 事件驱动；speaking 仍以设备播放事实为准。首版沿用 HA/ESP32 播放回执，不宣称已启用 Qwen playback.receipts。 | CONFIRMED |
| B81-C14 | Qwen gateway-protocol.md §3；gateway-client-transport.mjs lease 与 close code | 同一个认证 owner 同时只允许一个活动 Gateway Client。相同 client.instance_id 重连可替换旧 socket；不同实例默认收到 client_occupied 并关闭。项目应给 Tivoo 使用独立 Gateway access key/owner，不与 Qwen WebUI 共享活动 owner。owner 占用冲突必须 fail closed，不上传音频、不伪造接管成功。 | CONFIRMED |
| B81-C15 | P6.8 LIFE-C06/LIFE-C07、VOICE-C07；Qwen 2.1.0 `realtime-presentation-runtime.mjs` 的 assistant `transcript.final`；`AudioSessionManager.grant_followup()`；ESP32 0x27 | Qwen GCP 7.0 没有原生 `continue_conversation` 字段、客户端事件或结构化续聊授权回执。用户已明确选择方案 A：由 Qwen 核心 Prompt 约定最终面向用户的完整助手回复，仅在真正期待用户补充/选择/确认时以 `？` 或 `?` 结尾；HA 只消费当前 generation 的 `transcript.final`（`role=assistant`），裁剪末尾空白后检查标点。它是项目应用层策略，不是原生 Qwen 授权字段，也不是确定性协议保证。只 arm 当前 turn 的 per-turn bool；必须等待匹配 playback_id 的 ESP32 `AUDIO_STATE=completed`，并满足现有有效输入/正常响应条件后，复用 `grant_followup()` 和现有 0x27，单次打开 4 秒 local_followup gate。新 follow-up 使用新 MIC UUID / HA Context，但立即续聊必须保持原活动 Gateway WebSocket，不得仅凭相同 sessionId 重连。失败、缺失最终文本、中断、普通标点、用户 transcript、transcript.delta、tool.call、audio.done、voice.state=idle 均不授权。B8.2 已验证标点及同 socket 连续上下文；正常最终响应判定与跨轮移交仍须按 §2.1 核销。 | DECIDED；B8.2 PASS；终态门禁未解除 |

## 2.1 现有合同的最小实现补充（2026-11-22）

本节只细化 B81-C01/C04/C05/C06/C10/C12/C13/C15，不增加合同编号、设备消息、公开路由或 GCP 事件；原 49 条合同与方案 A 的产品行为保持不变。

| 适用合同 | 必须满足的边界 | 最小验收 / 归属 |
|---|---|---|
| C05/C15：最终响应 | `transcript.final` 是 response 的最终文本，不自动等于整轮最终成功。必须关联当前 turnId/responseId，排除工具中间响应并核对正常终态，之后才可用末尾问号计算续聊意图。锁定 v2.1.0 的 `realtime-presentation-runtime.mjs:#responseDone()` 对 cancelled/incomplete 仍可发送 audio.done；`realtime-session-runtime.mjs` 对这两种终态保持静默。已用该版本 runtime 复现：先发最终问句，再以 completed/cancelled/incomplete 结束，可产生相同客户端事件。因此无 error、audio.done 或 idle 均不能证明成功。 | B8.5 接入前先证明客户端可区分正常完成与取消/不完整，并覆盖工具中间文本；不能区分则该门禁保持 HOLD，不以默认成功或永久关闭成功续聊绕过。若确需上游变更，另行明确最小协议差异及兼容测试，本次不预定或实施新接口。 |
| C01/C06/C12/C15：连接移交 | 活动 socket 由该 ConfigEntry 对应的 bridge 持有，每轮只绑定当前 MIC session、HA generation、Gateway turnId/responseId。仅已授权且 parent_session_id 匹配的 local_followup 可在旧轮任务/流完成清理后接续原 socket；旧轮 retire 不关闭已保留给该续聊链的连接。新真实 wake、异常、超时及 unload 仍走取消/关闭/join。 | B8.5/B8.6 测试 follow-up 引发旧 on_end/retire 后 socket 不被误关；旧 turn/response 迟到事件不交付新轮；移交失败则关闭并收口，不通过重连冒充同 socket 续聊。 |
| C04/C12/C13：早端点与清播放 | 本地输入结束并 drain 前不得发送 TTS_PLAY；早到 PCM 只可进入 C10 的有界缓存，不能改变本地输入 gate。同一 MIC 输入出现第二个不同的 Gateway turnId 时按边界不一致收口，不自动拆成本地续聊。当前连接的 playback.clear 必须撤销待续聊、丢弃待播 PCM，并通过既有 session_id + playback_id 定向 stop；旧连接事件忽略。input.suspend/voice.deactivated 按当前轮不可继续处理，input.resume 不自行重开麦克风。 | B8.5/B8.6 覆盖本地 EOF 前 response/audio 到达、同 MIC 多 turnId、播放中 clear 和旧连接迟到 clear；仅收口 HA 语音交付，不新增远程 WakeNet/AFE 控制。已执行 MCP 副作用仍按 C12 不保证回滚。 |
| C10/C13：PCM 资源 | 每个 HTTP 流明确归属当前 MIC/generation、response 集合及 playback_id；流内采样率必须一致。实现时记录缓存字节上限和 GET 等待/读写停滞超时，不能只限制 chunk 数。满队列、GET 未启动或断连时，finish/cancel 也须有界退出并移除映射；一次性 URL 不记录日志或持久化。 | B8.5 覆盖满队列结束、无 GET、断连、取消与重复 GET。中间 audio.done 不关闭整轮资源；全部相关音频排尽才匹配物理 completed。最终文本晚于物理 completed 时在既有有界收尾内汇合条件，只授权一次；缺失文本或无实际播放不续聊。具体容量/时限由该批实现记录，不在本次另设参数体系。 |

终态依据固定为 v2.1.0 commit a9f4478da8df400d04facbb099ac2933ce8b11bc。以上是实现约束及验收出口，不代表生产桥接或相应反例测试已经完成。

## 3. P6.8 原 49 条合同核销

B0.6 交叉审查中的 49 条数量核对一致。本节只说明 Qwen 迁移的影响，不复制或改写原始合同。

| 原合同组 | 数量 | B8.1 处置 |
|---|---:|---|
| P68-HB01–HB14 | 14 | 硬件目标、双 target、flash、UART/COBS/CRC、TCP、SPP、连接恢复和并发边界不变。Qwen 不新增设备 wire protocol，不改变 7777/7778、UART 或 SPP 所有权。 |
| P68-HB15 | 1 | 保留 HA/MCP schema、权限、服务参数/错误/状态边界与 HA 显示 owner；Qwen 只复用现有 Assist MCP。 |
| AFE-C01–AFE-C12 | 12 | 双麦、16 kHz mono AFE、AEC/NS/VAD/WakeNet、常驻采集及资源有界合同继续生效。Qwen 输入复用当前本地 PCM；raw PCM 重采样尚未实现，不能从 MP3 SRC 推断已支持。 |
| VOICE-C01 | 1 | 保留本地唤醒、无远程候选 KWS、待机不传 PCM 和每轮新 MIC UUID。 |
| VOICE-C02 | 1 | 只在 Tivoo 本地语音链路将 HA Intent/AstrBot fallback 替换为 Qwen；HA AssistSatellite、turn/Context、设备 PCM ingress 和状态 owner 保留。旧链路不能并行处理同一 turn；共享服务是否删除留给 B9 消费者盘点。 |
| VOICE-C03 | 1 | Tivoo 语音路径不再调用旧 HA ASR/Intent；Qwen transcript 进入新路径。Sherpa/Wyoming 不能因此全局删除。 |
| VOICE-C04 | 1 | 保留 ready prompt、pull 才 ready、有限 PCM 缓存和 gate；Qwen 连接准备需与提示音并行，PCM 只在 gate 后上传。 |
| VOICE-C05 | 1 | 保留有效 gate、speech_start、PCM 顺序、尾部 padding、speech_end sample count 和无旧帧规则；本地 speech_end 不映射为虚构 GCP commit。 |
| VOICE-C06 | 1 | PCM EOF 不等于整轮完成；消费者 drain、模型 response、MCP tool continuation 和物理播放是不同阶段。 |
| VOICE-C07 | 1 | 原 3 秒首次 gate、15 秒命令和 4 秒 follow-up gate 时长保持；follow-up 采用方案 A；正常终态判定见 B81-C15/§2.1。 |
| VOICE-C08–C09 | 2 | 本地提示音素材池、唯一 DAC/TX、AEC/RX 常驻、提示音 gate 与普通 TTS 区分不变。 |
| VOICE-C10 | 1 | 保留 prompt、普通回复、display、follow-up 和 stale generation 分离；Qwen responseId/tool call ID 不得替代 HA generation 或设备 playback_id。 |
| LIFE-C01–C05 | 5 | 保留 epoch、MIC session、HA Context、playback_id、定向 stop、取消/join、stale callback 隔离。旧 SSE/AstrBot Stop 资源只在 Tivoo 迁移路径由 Gateway WebSocket/MCP 生命周期替代，不删除仍有共享用途的旧功能。 |
| LIFE-C06–C07 | 2 | Qwen 路径采用方案 A，保留物理完成和一次性 gate；正常响应证明仍受 §2.1 门禁约束，不得从音频终态推断授权。 |
| LIFE-C08 | 1 | 保留 unload、disconnect、S3 reset 后定向结束旧轮及物理身份隔离；Qwen sessionId 是独立长期历史键。 |
| VIEW-C01 | 1 | 保留状态优先级、显式内容、真实 wake/listening/thinking 事件和 idle 恢复。 |
| VIEW-C02 | 1 | tooluse 的事件源由旧 AstrBot phase 转为真实 Qwen tool.call，仍必须属于当前 generation；speaking 仍以设备 AUDIO_STATE 为准。 |
| VIEW-C03–C04 | 2 | Mood 白名单/Context 边界、OFF 硬门控、SPP 恢复与显示拥塞隔离继续有效；Qwen 不拥有第二套显示状态。 |

合计：15 + 12 + 10 + 8 + 4 = **49 条**；原始规格行未被本批次重写。

## 4. 旧合同迁移索引的受影响项

| 旧合同 | B8.1 处置 |
|---|---|
| P7A-C01–C08 | 共享服务保持可用。Qwen 路径不再调用旧 ASR/TTS，但在 B9 实际盘点其他消费者前，不删除 Sherpa/Wyoming 或影响其他 HA Pipeline。 |
| P7A-C05、P7A-C17–C22 | 旧 Tivoo HA STT endpoint 被 Qwen transcript 路径替代；只替换本集成此语音路径，不代表旧 STT Provider 全局失效。 |
| P65-A01 | 保留常驻 AFE、双麦和并发实测。 |
| P65-A02–A04 | 本地 WakeNet 已替代远程候选上传；保持本地唤醒与 prompt gate，不恢复远程 KWS。 |
| P65-A05–A06 | 保留本地 endpoint、PCM ingress、MIC UUID、offset 和 drain；Qwen 服务端端点由 Provider VAD 决定；B8.2 尾帧预检已通过，早端点处理见 §2.1。 |
| P65-A07–A14、P65-A16 | 保留取消、HTTP/播放 owner、有效 WakeNet 打断、回声/AEC、全双工与 generation 隔离；response.cancel 不替代 HA 先失效/定向 stop。 |
| P65-A15、PR-C04、ESM-C08 | follow-up 产品策略已由方案 A 解决；终态可观测性仍是实现门禁（§2.1）。ESM-C08 的旧 8 秒等待已由 P6.8 LIFE-C06/C07 取代为安全 gate 后 4 秒，不得恢复旧 8 秒。 |
| PR-C01–C03、PR-C05–C08、PR-C17–C19 | 本地 ready/follow-up 提示素材、gate、AEC、RX 和错误有界语义继续适用；follow-up 提示音仍需有效授权。 |
| PR-C09–C10 | 旧提示音 HTTP 路径已改为本地 flash；正常 TTS 的 /api/tts_proxy 限制保留，不因 Qwen 输出放宽。 |
| PR-C11 | 复用现有 0x30 TTS_PLAY 与唯一 audio_output_manager；不新增 ESP32 message type。 |
| PR-C12–C16 | playback_id、session_id、source、generation 与物理播放 owner 继续隔离；Qwen responseId 不替代 playback_id。 |
| P3-11 / P3-T13 / P3-T15 | AstrBot SSE/Stop 是旧语音路径的资源生命周期；Qwen socket close 可触发 Gateway 连接级 MCP AbortSignal，但 HA 已执行的 Service 副作用没有通用回滚保证。 |

## 5. 会话与资源身份映射

| 身份 | 来源与用途 | 不可混用的对象 |
|---|---|---|
| ConfigEntry.entry_id | HA 配置实例稳定 ID；本项目映射为 Qwen URL query sessionId | MIC session_id、HA Context.id |
| Qwen ownerId | Gateway access credential 解析出的认证主体 | sessionId 不承担认证 |
| Qwen sessionId | Gateway 持久化对话历史的 URL query key，journal 按 ownerId + sessionId 分区 | HA ChatSession、物理 MIC session |
| Qwen client.instance_id | GCP session.hello 的稳定客户端/lease 身份 | ownerId、sessionId、responseId |
| ESP32 MIC session_id | 单轮本地 wake/follow-up 收音、PCM ingress 和 stop 过滤 | 长期 Qwen sessionId |
| HA Context.id | 当前 AssistSatellite turn 的 Context；当前代码每轮创建新 Context() | 当前代码不存在的长期 ChatSession.conversation_id |
| Qwen responseId / turnId / tool.call.callId | 分别标识 Gateway 音频 response、模型 turn 和工具调用 | 相互之间及 HA/ESP32 ID |
| ESP32 playback_id | HA 为设备输出分配、用于定向 stop 和 AUDIO_STATE 归属 | responseId、MIC session_id |

项目映射建议：一个 Tivoo ConfigEntry 使用稳定的 Qwen URL sessionId = ConfigEntry.entry_id；GCP client.instance_id = tivoo-<ConfigEntry.entry_id>。认证 ownerId 使用 Gateway 凭据确定，与以上两个值独立。此映射是一项本项目决策，不表示 HA ChatSession 已存在或被调用。

## 6. 必须保留的事件时序

### 6.1 输入

1. 本地 WakeNet 确认并创建新的 ESP32 MIC session_id。
2. 本地 ready prompt gate 完成后，HA 对当前轮打开现有 audio_subscription。
3. HA 建立 GCP socket，完成 session.hello / session.ready，并等待 voice.ready；按 voice.ready.inputSampleRate 校验输入格式。
4. PCM 使用 GCP 客户端线上事件 input_audio_buffer.append 发送，audio 字段为 base64；Gateway 内部才转换为 audio.append。
5. 本地 speech_end 结束 HA PCM ingress；订阅消费者 drain 到 EOF。Qwen 模型端点由 Provider VAD 决定，不把本地 EOF 当作 GCP commit 或整轮完成。
6. EOF 后追加 B8.2 已验证的 1000 ms 零值 PCM（16 kHz mono S16LE，20 ms/640 bytes，共 50 帧）；取消或边界失效不伪装正常 EOF，不继续补尾帧。

### 6.2 模型、MCP 与音频输出

1. transcript.delta / transcript.final 表示 Gateway 识别/文本事件，不表示物理播放。
2. response.started 标识某次模型 response 开始。
3. tool.call 可以触发 Gateway Frontend MCP Client 调用现有 HA /api/mcp/assist 的 tools/list / tools/call。
4. 含工具调用的 response，其 audio.done 可能只结束中间 response；等待工具结果回到同一 Gateway 会话和之后的模型语音 response，不提前关闭整轮输出资源。
5. 每个 audio.delta 以自身 sampleRate 标记格式；不使用未经核验的固定采样率。
6. audio.done 只表示该 response 的音频生成结束；不代表 ESP32 HTTP GET 已读完，也不代表播放 completed。
7. 物理完成由匹配 playback_id 的设备 AUDIO_STATE 决定；HA 保留当前播放 owner 和 generation。

首版沿用 HA/ESP32 自身的播放回执，不宣称协商或使用 Gateway playback.receipts。Gateway voice.state 是模型语音状态，不替代设备状态；如以后启用 Gateway playback.receipts，必须另行定义 responseId 与设备真实播放之间的映射并增加测试。

## 7. 当前不存在、不得预写为既有接口的内容

| 项目 | 当前证据 | B8.1 允许的写法 | 禁止写法 |
|---|---|---|---|
| Qwen 原始 PCM HTTP 资源 | P6.8 只有 HA TTS Proxy URL 构造及 Pipeline TTS manager；设备 0x30 可以拉 URL，但当前 manager 只处理 HA TTS Proxy | B8.5 需实现并测试有界、可取消、可清理的 PCM HTTP 资源；路径等实现后从真实路由提取 | 不把试验 worktree 的某一路径写成生产接口；不在 B8.1 预定新 URL |
| RFC1918 HTTP + Bearer | Qwen 2.1.0 validator 拒绝非 loopback HTTP；有 header 时 loopback HTTP 也拒绝 | B8.3 实施显式私网 HTTP opt-in，并测试公网 HTTP 仍拒绝 | 不声称 Qwen 当前原生支持；不全局关闭 HTTPS 校验 |
| HA ChatSession / conversation_id | 当前 Tivoo AssistSatellite 每轮创建 Context()；集成没有 ChatSession 调用 | 使用 ConfigEntry.entry_id 映射稳定 sessionId | 不虚构 ChatSession.get/create、conversation_id 或 HA API |
| GCP input_audio_buffer.commit / speech_end | v2.1.0 GCP 客户端事件表不存在；speech_stopped/committed 属于上游 Provider 事件 | 只发已定义的 input_audio_buffer.append；真实端点按 B8.2 测试 | 不向 GCP 客户端 socket 发送 Provider event |
| Qwen continue_conversation | GCP 7.0 schema/事件没有原生字段或授权事件；项目选择方案 A | 以 assistant `transcript.final` 的末尾 `？`/`?` 作为 HA 应用层续聊意图约定；详细合同见 [Qwen Realtime 条件续聊设计](2026-11-22-p6-8-qwen-realtime-followup-design.md)。B8.2 相关预检已通过；生产实现仍须核销 §2.1，问号本身不能绕过真实播放完成、当前 generation、一次性 0x27/4 秒 gate | 不把标点说成 Qwen 原生结构化授权；不把 delta/user transcript/tool.call/audio.done/voice.state=idle 作为信号 |
| Qwen MCP readOnly / approval | v2.1.0 normalizedPolicy 明确拒绝这些配置字段 | 使用 HA Token、Assist 暴露范围、Tool annotations 与实际 Service 校验 | 不在 Qwen 配置中添加 readOnly / approval 并宣称有效 |
| 公共 response.done | Provider 内部处理有 response.done，但 GCP 公共 server event 集合没有该事件 | 用 GCP 实际公开的 response.started、audio.delta、audio.done、tool.call 等 | 不要求 HA 监听不存在的 GCP response.done |

## 8. B8.1 结论与放行门禁

### 已确认
- 原 P6.8 49 条新增合同数量和来源已核实，逐组审阅；原合同文件未被重写。
- P6.8 设备、AFE、HA turn、音频 owner、显示 owner、MCP endpoint 与服务权限边界可保留。
- GCP 客户端线上事件、Gateway 内部事件及 Provider VAD 事件已分层。
- Qwen sessionId/client.instance_id 采用 ConfigEntry.entry_id 的项目映射；不引用不存在的 HA ChatSession API。
- HA Assist MCP、Qwen Frontend MCP HTTP 限制、现有 ESP32 TTS_PLAY 与设备 playback_id 状态链均有代码或既有测试依据。
- 未实现的 raw PCM HTTP 路由和 raw PCM SRC 已明确留给后续批次真实实现；本矩阵不臆造其接口。

### 续聊策略决策与技术门禁（2026-11-22 更新）

P6.8 原合同 LIFE-C06/LIFE-C07 的设备侧安全条件继续有效：当前 turn/generation 必须有效、输入必须正常结束/完成 drain、模型响应不能失败或中断，并且必须等匹配 playback_id 的 ESP32 `AUDIO_STATE=completed`，随后只可通过现有 `AudioSessionManager.grant_followup()` 与 `TYPE_FOLLOWUP_OPEN (0x27)` 打开一次 4 秒 local_followup gate。现有 beep、声学安全 gate、真实播放 owner 和 stale-generation 约束均保留。旧 AstrBot/HA Pipeline 分支原有 `INTENT_END.continue_conversation` 语义不变。

针对 Qwen Realtime，用户选择方案 A：在 Qwen Agent 的核心 `PROMPT.md` overlay 中规定只有真正期待用户下一步信息/选择/确认时，最终面向用户的完整助手回复才以中文 `？` 或英文 `?` 结尾；HA 只处理当前 generation 的助手 `transcript.final`，对 `content.rstrip()` 检查末尾标点。问号只设置本轮续聊意图，不立即打开麦克风。用户文本、`transcript.delta`、工具调用中间响应、`audio.done`、`voice.state=idle` 和响应失败/中断均不触发续聊。未收到完整助手 final transcript 或普通标点时默认不续聊。

该约定是用户选择的项目应用层策略，不是 Qwen GCP 7.0 原生 `continue_conversation` 字段/事件，也不是确定性授权回执；模型未遵守 Prompt 的可能性通过 fail-closed、4 秒设备 gate、匹配物理播放完成和 generation 检查限制影响。HA 不新增 MCP 工具、Client Action、GCP 私有事件或第二套状态机。优先复用现有 per-turn `continue_conversation` bool、`grant_followup()` 和 0x27。

即时续聊的关键连接条件：问号响应播放完成后保持**原活动 Gateway WebSocket**；设备使用新 MIC UUID、HA 新 Context/generation，输入音频继续通过原 socket 上传，Gateway 为新 turn/response 生成新 ID。仅保留 URL `sessionId` 后关闭并重连不能替代同一活动连接的上下文连续性。普通回复未 arm、follow-up 超时或失败收口才关闭当前 socket。ConfigEntry.entry_id 到 Qwen `sessionId` 的稳定映射和 client.instance_id 身份继续沿用。

产品策略决策及 B8.2 的标点、同 socket 多轮、独立重连 journal、session 隔离与 lease 预检已完成，证据见 [B8.2 报告](../reports/2026-11-22-p6-8-b8-2-qwen-gcp-pcm-preflight.md)。1000 ms 尾帧仍是有限语料候选，25% 振幅样本未触发有效 speech turn；实机声学和物理播放验收仍归原后续批次。

**当前状态：B8.2 预检 PASS；B8.5/B8.6 的正常终态可观测性门禁 HOLD。** B8.3/B8.4 可按原范围推进；B8.5 接入前先核销 §2.1 的终态门禁，其余条目随 B8.5/B8.6 实现验收。此补充不表示生产代码或 NAS 配置已修改。
