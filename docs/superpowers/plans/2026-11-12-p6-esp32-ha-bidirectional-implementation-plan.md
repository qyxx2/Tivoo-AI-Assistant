# P6 ESP32 ↔ Home Assistant 双向通信实施计划

> **For agentic workers:** 每次只执行一个 P6 Batch。使用 `superpowers:executing-plans` task-by-task；每个新行为先使用 `superpowers:test-driven-development`，故障时使用 `superpowers:systematic-debugging`，提交前使用 `superpowers:verification-before-completion`。步骤使用 checkbox 跟踪。本计划与对应批次执行计划共同使用。

**Goal:** 在 P5 已验收实现上完成 7777 原始 SPP 双向透传、7778 TVIO v1 双向状态/会话消息、HA TTS Proxy URL 通知及 ESP32 HTTP 音频资源流读取，不实现 P7/P8 音频硬件运行时。

**Architecture:** 保留现有 HA `Esp32ConnectionAdapter` 的两条独立 TCP 连接、ESP32 `network_listeners` 两个监听端口、现有 TVIO v1 16-byte framing 和上游 `esp32-divoom` 的 SPP 反向字节语义。7778 扩展为双向消息，但不新增传输协议；HA 继续使用原生 TTS Proxy，ESP32 用 ESP-IDF HTTP Client 流式读资源，并通过一个 reader callback 将字节交给未来 P8 解码器。

**Tech Stack:** ESP-IDF v6.1 / ESP32-WROVER-E-N16R8 / FreeRTOS / BSD sockets / ESP-IDF HTTP Client；Home Assistant Core 2026.11.0 / Python 3.14 / asyncio；现有 pytest、POSIX C simulator 和 ARM64 Ubuntu 本地构建环境。

**Spec:** [P6 合同矩阵](../specs/2026-11-12-p6-esp32-ha-bidirectional-contract-matrix.md)（P6 唯一阶段合同）；上位设计 [ESP32 ↔ HA 双向通信规格书](../specs/2026-11-09-esp32-ha-bidirectional-communication-design.md)；P5 已完成依据 [P5 合同矩阵](../specs/2026-11-11-p5-esp32-minimal-firmware-contract-matrix.md) 及 [P5 收尾报告](../reports/2026-11-12-p5-memory-bond-artifact-closeout.md)。

---

## 1. Global Constraints

- 当前工作分支固定为 `feature/p6-esp32-ha-bidirectional-communication`；基线是创建分支时的 `main/a2b0127`。不得切换到 main 或其他阶段分支执行 P6。
- P6 合同矩阵 §11 的 P6-C01–P6-C20 是验收唯一依据。本计划只拆分执行步骤，不重定义消息语义、Payload、限制值或阶段边界。
- P5 的 TCP 7777/7778、HA Config Entry v2、`tivoo_bluetooth_mac` 唯一权威来源、Tivoo 原始帧、SPP Bond/NVS、TVIO v1 header、HELLO/ACK、ERROR/DIAGNOSTIC_LOG 必须兼容。
- ESP-IDF 固定 v6.1、target `esp32`；复用 P5 已有 dependency lock、sdkconfig、partition table 和 ARM64 Xtensa 工具链，不再建立新环境或更改版本。
- 所有开发、pytest、POSIX C simulator、Ruff、静态检查及 ESP-IDF build/merge-bin 都在 ARM64 Ubuntu 工作区执行。NAS 只用于必要的真实设备联调；Windows 只允许作为最终人工刷写站，不作为源码/测试/构建环境。
- HA 代码测试使用现有 `scripts/test-ha.sh` 和项目 Python 3.14 venv；ESP32 C 逻辑优先扩展现有 POSIX simulator，最终再用 ESP-IDF v6.1 编译真实固件。
- 网络边界按可信局域网处理：ESP32 只连接 HA/NAS 配置的内网地址，不新增账号认证、mTLS、证书固定、密钥交换或代理。TTS 资源首选 NAS 内网 HTTP；若 HA internal_url 配置为 HTTPS，则使用 ESP-IDF 自带标准 CA bundle 验证，不增加自签证书/逐设备证书配置。
- 7777 保持原始字节全双工；SPP DATA_IND 不增加 TVIO、JSON、长度前缀或 Base64。0x69/0x96 只按上游状态提示处理，不是命令级 ACK。
- 7778 继续使用 `TVIO` / version 1 / 16-byte little-endian header。JSON 最大 16 KiB；MIC_PCM 二进制 Payload 最大 4 KiB；接收必须支持 TCP 拆包/粘包；两个方向独立 Sequence。
- HA 是 7778 唯一主动发送 PING 的一端：每 15 秒一次；连续 45 秒没有有效 PONG 时只重连 7778，不关闭 7777、不重置 SPP。
- GET_STATUS 只能返回设备实际能够读取的 Wi-Fi、TCP、SPP 和 HTTP resource 状态；不得虚构电池、屏幕确认、麦克风/AEC/VAD 或音频播放完成状态。
- 麦克风数据合同固定为 16 kHz / Mono / signed 16-bit little-endian PCM；典型帧 20 ms / 320 samples / 640 bytes；P6 只提供协议和有界分发入口，不采集 I²S、不实现 AEC/VAD、不调用 Assist Pipeline。
- TTS URL 使用 HA Core 2026.11.0 的 `get_url()`：`allow_external=False`、`allow_cloud=False`、`allow_internal=True`、允许 LAN IP。使用 TTS Proxy 路径内已有 token，不再单独发送 Bearer/token，不新增 URL 配置项或音频代理。
- ESP32 HTTP 使用 IDF 自带 HTTP Client；HTTP 2xx、Content-Type media type 校验、支持 chunked/未知 Content-Length、按块交给 reader，不缓存完整音频文件，不实现解码器。
- 一个时刻只允许一个 TTS HTTP resource GET；第二个不同 playback_id 返回 `audio_busy`；AUDIO_STOP 只停止匹配的请求，幂等处理过期/重复停止。
- P6 AUDIO_STATE 只允许 `buffering`、`resource_ready`、`stopped`、`failed`。下载完成不等于播放完成；不得在 P6 发送 `completed`。
- Token、完整 TTS URL、Wi-Fi 凭据、原始 PCM、完整转写和 LLM 正文不得写入日志、错误消息、测试快照或持久化存储。
- 不新增 MQTT/WebSocket/消息总线、TCP 第三端口、ESP32 HTTP Server、通用 URL 文件代理、任意目录访问或新鉴权体系；不重写上游 Tivoo 帧解析和 SPP 逻辑。
- P6.5 是 P6 后的独立取消链路前置验证；本计划不执行其测试、不修改取消生产逻辑。P7 I²S RX/AEC/VAD/Assist Satellite 与 P8 解码/SRC/I²S TX/输出管理器均不属于 P6。

## 2. Review Focus

以下五类输入/故障必须在对应批次设专门测试，不能仅靠最终实机冒烟覆盖：

1. **7777 反向队列与 TCP 发送背压：** SPP callback 不得阻塞；部分 send、EAGAIN、队列满和 TCP client 断开时，不能损坏后续字节或影响 SPP。由 P6b1 的 POSIX simulator 测试。
2. **7778 协议边界：** 拆包/粘包、错误 Sequence、非法长度、未知消息类型、二进制 MIC_PCM 上限及握手拒绝都必须保持连接/协议合同。由 P6b0 的 Python/C golden tests 测试。
3. **连接独立性与状态准确性：** 7778 心跳超时不得关闭 7777 或触发 SPP 重连；Wi-Fi/SPP 状态只在实际变化时报告。由 P6b2 的 fake-clock、状态转换和双端断线测试。
4. **麦克风会话迟到数据：** 旧 session 的 PCM/END/STOP 不得关闭新 session；满队列必须有界且有明确结束行为。由 P6b3 覆盖。
5. **TTS URL/HTTP 生命周期：** internal URL 优先、LAN IP fallback；流式 TTS 不能等 tts-end 才启动 GET；HTTP 非 2xx、MIME 不匹配、chunked/未知长度、busy、匹配/过期/重复 STOP 均有明确状态。由 P6b4/P6b5 覆盖。

## 3. 当前基线与文件职责

### 3.1 已存在并继续扩展的模块

| 路径 | 当前责任 | P6 责任 |
|---|---|---|
| `homeassistant/custom_components/tivoo/diagnostics.py` | TVIO v1 Python encode/decode、增量接收、P5 message constants | 扩展全部 P6 type、二进制 MIC_PCM 长度限制、保持原 codec API |
| `homeassistant/custom_components/tivoo/transport.py` | `Esp32ConnectionAdapter`；7777/7778 独立连接循环；P5 handshake/log/error | 7777 反向接收；7778 收发/dispatch/heartbeat/state；发送 P6 命令 |
| `homeassistant/custom_components/tivoo/__init__.py` | 建立 adapter、HA runtime 和 service 生命周期 | 注册音频会话/资源 helper，卸载时关闭队列与活动任务 |
| `esp32/firmware/main/network_listeners.c/.h` | 两个 IPv4 listener、每端口一个 client、共享 select worker | 7777 writable poll/反向发送；保持 7777/7778 生命周期分离 |
| `esp32/firmware/main/control_bridge.c/.h` | HA→ESP32 的控制字节流解析和 SPP FIFO 提交 | SPP 反向 bounded queue、socket send worker、上游状态提示 |
| `esp32/firmware/main/tivoo_spp.c/.h` | Classic SPP、Bond、发送队列、自动重连；DATA_IND 被忽略 | DATA_IND 原始数据交给 7777 queue；提供只读连接状态 |
| `esp32/firmware/main/diagnostics.c/.h` | TVIO v1 P5 HELLO/ACK、日志/错误队列 | 双向消息 framing、收发队列/dispatch、心跳和实时消息 |
| `esp32/firmware/main/wifi_station.c/.h` | Station 事件和 listener IP gating | 提供真实 Wi-Fi/IP 状态和变化事件 |
| `esp32/firmware/main/CMakeLists.txt` | P5 组件依赖 | P6b5 加入 IDF `esp_http_client` 依赖 |

### 3.2 P6 新增的最小模块

| 路径 | 职责 | 不负责 |
|---|---|---|
| `homeassistant/custom_components/tivoo/audio_session.py` | 一个活动 MIC session、有限 PCM 队列、session_id 匹配、向未来 Pipeline 提供 async iterator | 不创建 Assist Satellite、不启动 Pipeline、不实现 KWS/STT |
| `homeassistant/custom_components/tivoo/audio_resource.py` | TTS URL 内网构造、Pipeline event callback、playback_id 与 TTS_PLAY 关联 | 不创建 Satellite、不做 Pipeline/SSE 取消、不管理最终播放生命周期 |
| `esp32/firmware/main/audio_resource.c/.h` | 一个活动 HTTP GET、状态/MIME 校验、流式 reader callback、AUDIO_STOP | 不解码、不做 SRC、不写 I²S、不实现输出管理器 |

不新增独立协议库、MQTT client、HTTP proxy、资源发现服务或专门的“通用消息总线”模块。消息解析和转发继续留在现有 diagnostics/transport 模块；只有具有独立生命周期的音频 session/resource 才单独成文件。

### 3.3 P6 稳定接口

- HA TVIO codec 保留 `DiagnosticMessage(message_type, flags, sequence, payload)`、`encode_message(message_type: int, payload: bytes, sequence: int) -> bytes` 和 `DiagnosticFrameStream.feed(data: bytes) -> list[DiagnosticMessage]`；只扩展 message constants 与 payload 类型校验，不改 header。
- HA `Esp32ConnectionAdapter` 增加 `async_send_message(message_type: int, payload: bytes) -> None`，仅在 7778 已完成 HELLO_ACK 后发送；发送方向维护本连接独立 tx Sequence，并与接收 Sequence 分开。
- HA adapter 提供单一注册入口 `register_message_handler(message_type: int, handler: Callable[[DiagnosticMessage], Awaitable[None]]) -> None`。收到合法且已握手的业务消息时调用注册 handler；P5 的 ERROR/DIAGNOSTIC_LOG 保持原有 logger 行为。
- ESP32 diagnostics 接收层增加 `tivoo_diagnostics_send_message(uint8_t type, const uint8_t *payload, size_t size) -> bool`，所有调用只入有界发送队列，不在 Wi-Fi/SPP/Socket callback 中直接发送。
- ESP32 diagnostics 将合法的非 HELLO_ACK 入站消息分发给注册的业务 handler；handler 必须只做校验/入队或轻量状态操作，不能在 listener worker 内执行 HTTP 阻塞请求。
- 对 AUDIO_INTERRUPTED 注册轻量分发回调并校验 interrupt_id/audio_id/source/reason；P6 只将事件交给后续 P7/P8 owner，不执行 Pipeline/TTS/AstrBot 取消。
- HA `AudioSessionManager` 的公共操作固定为 `async_start_session(payload: dict) -> None`、`async_push_pcm(session_id: str, data: bytes) -> None`、`async_end_session(session_id: str, reason: str) -> None`、`async_stop_session(session_id: str, reason: str) -> None`、`async_audio_iterator(session_id: str) -> AsyncIterator[bytes]`。每个 config entry 只创建一个 manager。
- HA TTS helper 暴露 `async_handle_pipeline_event(event: AssistPipelineEvent) -> None`；由后续 Satellite 实现通过现有 Pipeline `process_event` 回调调用，本批不创建 Satellite Entity。
- ESP32 HTTP resource 暴露 `tivoo_audio_resource_start(playback_id, url, mime_type)`、`tivoo_audio_resource_stop(request_id, expected_audio_id, reason)` 和 `tivoo_audio_resource_set_reader(reader, context)`；reader 签名为 `esp_err_t reader(const uint8_t *data, size_t size, void *context)`。P8 后续只需注册解码器输入回调。

## 4. 批次总览与依赖

| 批次 | 目标 | 主合同 | 依赖 |
|---|---|---|---|
| P6b0 | TVIO v1 双向协议底座、message type、Sequence、HELLO 能力扩展 | C01、C05、C06、C10、C19 的协议基础 | P5 |
| P6b1 | 7777 SPP reverse raw channel + 上游状态提示 | C02、C03、C04、C19 | P6b0 |
| P6b2 | 7778 heartbeat、GET_STATUS、DEVICE_STATUS、DEVICE_EVENT、ERROR | C07、C08、C09、C10、C17 | P6b0 |
| P6b3 | MIC session schema、binary PCM 和 HA bounded dispatch | C11、C18 | P6b0、P6b2 |
| P6b4 | HA TTS Proxy URL helper、Pipeline event 触发与 TTS_PLAY 下发 | C12、C01 | P6b0、P6b2 |
| P6b5 | ESP32 HTTP GET streaming、reader callback、AUDIO_STOP 和状态回报 | C13、C14、C15、C16、C18 | P6b0、P6b4 |
| P6b6 | 双端集成、P5 regression、IDF build、真实设备验收和阶段收尾 | C01–C20 | P6b1–P6b5 |

P6b1 与 P6b2 在代码职责上可以并行，但本项目采用一个批次一个验收门的串行执行方式，不创建并行分支或额外协调层。

## 5. 批次执行计划


### P6b0 — TVIO v1 双向协议底座

**Files:**
- Modify: `homeassistant/custom_components/tivoo/diagnostics.py`
- Modify: `homeassistant/custom_components/tivoo/transport.py`
- Modify: `esp32/firmware/main/diagnostics.c`, `diagnostics.h`
- Modify: `esp32/tests/p5b2_diagnostics_simulator/diagnostics_host.c`
- Test: `tests/homeassistant/custom_components/tivoo/test_diagnostics.py`, `test_transport.py`
- Test: `tests/esp32/test_p5b2_diagnostics.py`

**Interfaces:**
- 保留现有 Python codec API；增加矩阵 §4 定义的全部 Message Type 常量及 MIC_PCM binary max=4096 校验。
- C 接口：`tivoo_diagnostics_send_message(uint8_t type, const uint8_t *payload, size_t size) -> bool`；该函数只复制/入有界发送队列，不执行 socket send。
- C 入站 dispatcher 接口：`typedef bool (*tivoo_diagnostics_message_handler_t)(uint8_t type, const uint8_t *payload, size_t size)`；注册函数 `tivoo_diagnostics_set_message_handler(handler)`。HELLO_ACK 仍由 diagnostics 层处理；其他合法消息转给业务 handler。
- HA 发送方向和接收方向的 Sequence 独立计数；每次 7778 TCP 重连后均从 0 开始。
- HELLO capabilities 固定为 `spp_control`、`spp_reverse`、`remote_diagnostics`、`device_status`、`device_events`、`audio_resource_http`、`audio_control`；不声明 P7/P8 能力。

**Tasks:**
- [x] 为 Python codec 写测试：矩阵内所有消息 type 均可编码；16-byte header 字段与 P5 相同；每个方向 Sequence 独立；MIC_PCM 4 KiB 内通过、超过 4 KiB 拒绝；16 KiB JSON 上限保持；非法 header/Sequence 失败；未知合法 type 忽略消息、记录一次 `protocol_unsupported_message`，且不破坏下一帧边界。
- [x] 运行 `./scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_diagnostics.py -q`，确认新增测试按预期 RED。
- [x] 扩展 `diagnostics.py` 的 constants、payload limit 检查和现有 `DiagnosticFrameStream`；不另建一套 codec。
- [x] 为 C simulator 增加相同 TVIO golden frame，测试所有 message type、拆包/粘包、方向 Sequence、超长 MIC_PCM/JSON、未知 type 只记录一次 `protocol_unsupported_message` 且不关闭合法流，以及 malformed header。
- [x] 扩展 `diagnostics.c/.h`：通用 message encode/receive、连接级 Sequence、有限发送队列和 message-handler 注册入口；保持 P5 的 16 条日志队列独立，实时消息队列不能饿死日志发送。
- [x] 更新 HELLO capabilities 和 HA HELLO 校验；保留 HELLO_ACK accepted/reason 的 P5 格式。
- [x] 运行 `./scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_diagnostics.py tests/homeassistant/custom_components/tivoo/test_transport.py -q`。
- [x] 运行 `.venv/bin/python -m pytest tests/esp32/test_p5b2_diagnostics.py -q`；确认 P5 handshake、日志补传和队列满测试仍通过。
- [x] 构建 `esp32/firmware` 的 ESP-IDF v6.1 / esp32 target，确认 C 接口及队列实现编译通过。

**Exit gate:** C05/C06 的跨语言 codec 和握手通过；P5 ERROR/DIAGNOSTIC_LOG/HELLO 行为保持；新的 outbound/inbound message API 已可供后续批次直接调用。此批不实现 P6 消息业务含义。

### P6b1 — TCP 7777 SPP 原始反向通道

**Files:**
- Modify: `esp32/firmware/main/control_bridge.c`, `control_bridge.h`
- Modify: `esp32/firmware/main/network_listeners.c`, `network_listeners.h`
- Modify: `esp32/firmware/main/tivoo_spp.c`, `tivoo_spp.h`
- Modify: `homeassistant/custom_components/tivoo/transport.py`
- Modify: `esp32/tests/p5b3_control_simulator/control_bridge_host_stub.c` and existing listener simulator
- Modify: `esp32/tests/p5b4_integration_simulator/tivoo_spp_host_stub.c` to keep the changed queue result signature consistent across existing host test targets
- Test: add `tests/esp32/test_p6_reverse_channel.py`; extend `tests/homeassistant/custom_components/tivoo/test_transport.py`

**Interfaces:**
- SPP callback to reverse queue: `bool tivoo_control_spp_data(const uint8_t *data, size_t size)`. Frame submission returns a small result enum (`QUEUED`, `CONNECTING`, `DISCONNECTED`, `QUEUE_FULL`) so the bridge can reproduce upstream behavior without buffering commands while disconnected.
- Listener worker checks `tivoo_control_client_has_pending(int client_fd) -> bool` and calls `tivoo_control_client_send_pending(int client_fd) -> bool` only when the 7777 socket is writable.
- HA control reader handles received bytes without terminating the existing independent 7777 connection loop; raw payload bytes are delivered unchanged to the registered SPP reverse consumer. 只有单独收到的 0x69/0x96 单字节 read 才作为 best-effort hint 更新提示态；合并/分段场景不尝试重组猜测，真实 SPP 状态以 7778 为准。

**Tasks:**
- [x] 在 POSIX simulator 中先写 SPP DATA_IND 注入接口和 TCP client 断线测试：从 SPP 注入任意多段 bytes，HA socket 必须按原顺序、原内容收到。
- [x] 为 bounded reverse queue 写 RED 测试：SPP callback 不调用 socket send；队列容量满时返回失败/记录 `reverse_queue_full`，不等待消费者；队列内不产生半包覆盖。
- [x] 为发送状态 hint 写 RED 测试：SPP 正在 connecting 时提交 frame 只回 0x69；SPP 已 disconnected 时只回 0x96；connected 时按 FIFO 提交原始 frame；检查 P5 当前发送队列不会在无连接状态把 frame 延迟到未来连接后发送。
- [x] 为 TCP sender 写测试：socket partial send/EAGAIN 后保留 offset，writable 恢复后继续发送，最终字节流不丢失、不重排、不重复。
- [x] 为 disconnect 写测试：7777 client 断开会清掉该 client 的待回传 bytes；不调用 SPP disconnect，也不影响 7778。
- [x] 将 `tivoo_spp_queue_frame` 的结果细分为 QUEUED/CONNECTING/DISCONNECTED/QUEUE_FULL：connected 时按原 FIFO 入队；connecting 时不保存该 frame、返回 0x69 hint；disconnected 时不保存该 frame、返回 0x96 hint；queue full 保持现有错误上报。
- [x] 在 `tivoo_spp.c` 的 `ESP_SPP_DATA_IND_EVT` 中复制数据并投递给 control bridge queue；不得在 Bluedroid callback 中执行 socket 操作或阻塞等待。
- [x] 在 `control_bridge.c` 实现固定容量 reverse queue；没有当前 7777 client 时立即丢弃该 session 的 SPP 返回数据，不缓存给下一个 client；在 `network_listeners.c` 的 select 中只对有 pending data 的 7777 client 注册 writable fd，发送成功后消费队列数据。
- [ ] 对照本地 `BluetoothBridgeTest/esp32-divoom` 的 `output_bluetooth.cpp`、`input_tcp.cpp` 和 `hardware_bluetoothctl.cpp` 实现 0x69（connecting）/0x96（not connected）原始状态提示；不增加消息包装、command_id 或 per-command ACK。 阻塞说明：三个源文件不在当前开发机工作区；行为按 P6 合同矩阵中已冻结的 0x69/0x96 语义实现。
- [x] 在 HA 7777 reader 中识别上游单字节状态提示并更新提示状态；其他返回字节保持 opaque raw bytes，不记录其内容，不把写入 TCP buffer 当成显示确认。
- [x] 运行 P6 reverse channel、P5b1 listener、P5b2 diagnostics、P5b3 control bridge、P5b4 integration host/POSIX 回归（项目 test-ha.sh wrapper）。
- [x] 运行 HA transport/services 测试（test-ha.sh wrapper）。
- [x] ESP-IDF v6.1 / ESP32 target build：通过本机已有 activate_idf_v6.1.sh 激活环境后，idf.py build 成功；生成 build/tivoo_firmware.bin。

**Exit 状态：** C03/C04/C19 的代码与 host/HA 验证通过；C02 已由 POSIX 注入模拟器验证数据路径。ESP-IDF v6.1 / ESP32 target 编译已通过；真实 Bluedroid SPP DATA_IND 与 Tivoo 回传硬件验收仍未验证，因此本批次真实硬件验收门保持 pending。

### P6b2 — TCP 7778 心跳、状态快照和设备事件

**Files:**
- Modify: `homeassistant/custom_components/tivoo/transport.py`
- Modify: `esp32/firmware/main/diagnostics.c/.h`
- Modify: `esp32/firmware/main/wifi_station.c/.h`
- Modify: `esp32/firmware/main/network_listeners.c/.h`
- Modify: `esp32/firmware/main/tivoo_spp.c/.h`
- Create: `esp32/firmware/main/device_status.c/.h`; register in `CMakeLists.txt` and `main.c`
- Test: extend HA `test_transport.py`, ESP32 `test_p6_device_status.py` and existing diagnostics/listener simulators

**Interfaces:**
- HA `Esp32ConnectionAdapter` stores latest validated DEVICE_STATUS; message handlers receive validated `DiagnosticMessage`.
- Device status read interfaces return actual Wi-Fi/IP/RSSI, 7777/7778 client state, SPP state/peer and HTTP resource idle/fetching. Missing optional observations are omitted. `tivoo_device_status_set_audio_resource()` is the small current-state seam for P6b5; this batch leaves it idle unless a producer explicitly marks an active fetch.
- `tivoo_device_status_handle_message(type, payload, size)` handles PING and GET_STATUS; PING queues empty PONG, GET_STATUS replies with DEVICE_STATUS and the exact request_id.
- `tivoo_device_status_report_event(event, data)` emits only state transitions through the shared TVIO sender.

**Tasks:**
- [x] HA transport tests with fake clock: PING every 15 seconds; each valid PONG refreshes liveness; 45 seconds without valid PONG closes only 7778 and starts its existing reconnect loop; 7777 writer stays open and SPP control remains connected.
- [x] Write tests for HELLO_ACK → exactly one GET_STATUS; DEVICE_STATUS request_id echo; malformed status rejection; unknown optional values omitted rather than filled with guessed values.
- [x] Add device status test stubs for Wi-Fi/IP, listener fd states, SPP peer and resource fetching; assert snapshot reflects injected state only.
- [x] Add event transition tests: wifi_connected/disconnected and spp_connecting/connected/disconnected emit once per actual transition; repeated identical state emits nothing.
- [x] Extend ESP32 dispatcher to answer PING and GET_STATUS using the state getters; Wi-Fi/SPP callbacks report events after the state change, not before.
- [x] Expose SPP status from the existing SPP session/event state; do not create a second SPP state machine. Expose TCP client status from existing listener endpoint fds.
- [x] HA parses PONG, DEVICE_STATUS, DEVICE_EVENT and P6 ERROR codes; keeps standard P5 logger mapping and redacts URL/token/PCM.
- [x] Run `.venv/bin/python -m pytest tests/esp32/test_p6_device_status.py tests/esp32/test_p5b1_network_listeners.py tests/esp32/test_p5b2_diagnostics.py -q` and `./scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_transport.py tests/homeassistant/custom_components/tivoo/test_diagnostics.py -q`.
- [x] Run ESP-IDF v6.1 build and inspect that 7778 reset path never calls SPP disconnect or 7777 reset.

**Exit gate:** C07–C10/C17 pass; 15s/45s timing is deterministic under fake clock; status snapshot has no synthetic fields; independent reconnect and P5 logger regression pass.


### P6b3 — 麦克风 session 消息和 HA 有界分发接口

**Files:**
- Create: `homeassistant/custom_components/tivoo/audio_session.py`
- Modify: `homeassistant/custom_components/tivoo/transport.py`, `__init__.py`
- Modify: `esp32/firmware/main/diagnostics.c/.h`（MIC_CAPTURE_STOP dispatch seam）
- Test: Create `tests/homeassistant/custom_components/tivoo/test_audio_session.py`; extend `test_diagnostics.py`、`test_transport.py`
- Test: extend `tests/esp32/test_p5b2_diagnostics.py` 或 P6 protocol simulator

**Interfaces:**
- `AudioSessionManager` 仅管理一条活动网络 session。队列固定 `asyncio.Queue(maxsize=16)`（最多 16 个消息，按 4 KiB 上限计算最多 64 KiB）；每条 MIC_PCM Payload 上限 4 KiB；`async_audio_iterator(session_id)` 是下游 P7 接口。
- `MIC_SESSION_START` 验证 session_id、16 kHz/Mono/S16LE、frame_duration_ms=20、trigger_source；barge_in 必须包含 interrupt_id。
- `MIC_CAPTURE_STOP` 由 HA 发往 ESP32，只请求停止对应 session 的网络上传。ESP32 提供一个可注册 stop callback；P6 尚无麦克风 producer，默认无活动 session 时按幂等 no-op 处理。

**Tasks:**
- [ ] 先写 manager RED tests：合法 start 后可消费 iterator；重复 start 不覆盖活动 session；第二条 session 明确拒绝；旧 session_id 的 PCM/END/STOP 不影响当前 session。
- [ ] 写格式测试：只接受 16000 Hz / 1 channel / s16le；典型 20 ms 数据为 640 bytes；单 Payload 不超过 4096 bytes；trigger_source 只允许 idle_vad/barge_in；barge_in 缺少 interrupt_id 时拒绝。
- [ ] 写 queue saturation 测试：16 个未消费块达到上限后，不扩大队列/占用内存；终止当前异常网络 session，清理队列并通过 MIC_CAPTURE_STOP 通知 ESP32；已结束 session 的后续消息幂等忽略。
- [ ] 实现 `AudioSessionManager` 的 start/push/end/stop/iterator；queue 元素只存 PCM bytes，不做 Base64/JSON，不复制到第二份无界 buffer。
- [ ] 在 `transport.py` 注册 MIC_SESSION_START/MIC_PCM/MIC_SESSION_END handler，将 TVIO binary Payload 原样送入 manager；错误 session 的数据不能关闭 transport 或覆盖新 session。
- [ ] 注册 AUDIO_INTERRUPTED 的最小 handler，校验矩阵字段并把事件交给 P7 将来注册的 callback；当前 P6 不取消 Pipeline、TTS Proxy 或 AstrBot session。
- [ ] 将 manager 纳入 HA config-entry runtime，unload 时关闭活动 iterator、队列和关联任务；不得留下 pending task。
- [ ] ESP32 diagnostics 校验 MIC_CAPTURE_STOP JSON 和 session_id；通过注册 callback 提供给未来 P7 mic uploader。P6 没有物理 MIC uploader 时，收到已结束/不存在 session 按合同 no-op。
- [ ] 写跨端模拟测试：模拟 ESP32 依次发送 START、多个 binary PCM、END；HA iterator 读取字节与发送内容完全一致；覆盖分段 TCP frame 和旧 session 消息。
- [ ] 运行 `./scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_audio_session.py tests/homeassistant/custom_components/tivoo/test_transport.py tests/homeassistant/custom_components/tivoo/test_diagnostics.py -q`、对应 ESP32 protocol tests、P5 regression 和 IDF build。

**Exit gate:** C11/C18 通过；HA 已有可由 P7 直接接入的单 session 有界 PCM iterator 和停止接口；不创建 Satellite、Pipeline、I²S、AEC 或 VAD runtime。

### P6b4 — HA TTS Proxy URL 与 Pipeline 事件触发

**Files:**
- Create: `homeassistant/custom_components/tivoo/audio_resource.py`
- Modify: `homeassistant/custom_components/tivoo/transport.py`, `__init__.py`
- Test: Create `tests/homeassistant/custom_components/tivoo/test_audio_resource.py`; extend `test_transport.py`
- Reference integration behavior: HA Core 2026.11.0 Assist Pipeline event payload and existing `tests/homeassistant/custom_components/astrbot/test_conversation.py` streaming bridge test

**Interfaces:**
- `async_handle_pipeline_event(event)` 接受 HA Pipeline event；run-start 保存 TTS Proxy 相对 URL、mime_type、stream_response；intent-progress 在 tts_start_streaming=true 时提前发送；tts-end 处理非流式/短回答。
- `build_internal_tts_url(hass, relative_url) -> str` 使用 HA `get_url()` 的 internal/LAN-only 参数；相对路径内已有 token，原样附加到内网 base URL。
- 通过 `Esp32ConnectionAdapter.async_send_message(TYPE_TTS_PLAY, payload)` 下发 `{playback_id,url,mime_type}`；不得把 token 拆成第二个 payload 字段或 Authorization header。

**Tasks:**
- [ ] 为 URL builder 写测试：配置 internal_url 时优先使用；没有 internal_url 时使用 HA Core LAN IP fallback；不返回 cloud/external URL；保留 `/api/tts_proxy/{token}` 完整 path；不可取得内网地址时明确失败且不发送 TTS_PLAY。
- [ ] 为 Pipeline event handler 写 RED tests：run-start 保存资源 metadata，不立即发送；流式路径在 intent-progress 的 `tts_start_streaming=true` 发送 TTS_PLAY，必须早于 tts-end；非流式/短回答在 tts-end 发送。
- [ ] 验证一个 Pipeline run 最多发送一次 TTS_PLAY；流式已经发送后到达的 tts-end 只结束输入，不重发；新 run 的 playback_id 不继承旧 URL。
- [ ] 实现 `audio_resource.py` helper 和最小 playback metadata；不创建 Assist Satellite Entity，不在本批执行 Pipeline，不实现 TTS Proxy 取消逻辑。
- [ ] 集成 adapter outbound TVIO sender，确认发送方向 Sequence 连续、与接收方向独立；7778 未完成握手时拒绝 TTS_PLAY，不排入脱离连接生命周期的缓存队列。
- [ ] 测试日志、异常和诊断不包含完整短时 URL/token；测试数据只使用 opaque fake token，不快照生产凭据。
- [ ] 运行 `./scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_audio_resource.py tests/homeassistant/custom_components/tivoo/test_transport.py tests/homeassistant/custom_components/tivoo/test_audio_session.py -q` 以及 HA Tivoo 全部回归。

**Exit gate:** C12 通过；真实 HA Pipeline event helper 可按流式/非流式规则下发 TTS_PLAY；不实现 Satellite 生命周期、Pipeline cancel、AstrBot Stop 或音频播放完成状态。

### P6b5 — ESP32 HTTP 音频资源 GET、流式 reader 和 AUDIO_STOP

**Files:**
- Create: `esp32/firmware/main/audio_resource.c`, `audio_resource.h`
- Modify: `esp32/firmware/main/diagnostics.c/.h`, `main.c`, `CMakeLists.txt`
- Modify: `esp32/firmware/sdkconfig.defaults`（固定标准 CA certificate bundle）
- Modify: `esp32/firmware/README.md`
- Test: add focused HTTP test instructions/fixture under `tests/esp32/`; extend P6 diagnostics simulator for TTS_PLAY/AUDIO_STOP message validation
- Reference: [ESP-IDF v6.1 HTTP Client](https://docs.espressif.com/projects/esp-idf/en/v6.1/esp32/api-reference/protocols/esp_http_client.html)

**Interfaces:**
- `tivoo_audio_resource_start(playback_id, url, mime_type)` 创建唯一活动 HTTP GET task；`tivoo_audio_resource_stop(request_id, expected_audio_id, reason)` 仅取消匹配活动请求；`tivoo_audio_resource_set_reader(reader, context)` 注册 P8 decoder input sink。
- Reader callback：`esp_err_t reader(const uint8_t *data, size_t size, void *context)`；每次接收只提交本次有限 chunk，调用者不得保留 HTTP event 的临时 data 指针。
- HTTP 在独立 FreeRTOS task 中调用 `esp_http_client_perform()`；AUDIO_STOP 使用 IDF 的 `esp_http_client_cancel_request()` 终止活动 socket/request，task 完成后统一 cleanup。
- HTTP 状态只报告 buffering/resource_ready/stopped/failed；P6 不报告 playing/completed/interrupted。

**Tasks:**
- [ ] 写 HTTP 测试用本地可控 server：提供 200 + audio/mpeg、非 2xx、错误 Content-Type、chunked transfer、无 Content-Length、响应中途断开和大于普通 RAM 缓冲区的响应体。
- [ ] 在 `sdkconfig.defaults` 固定 ESP-IDF 标准 CA bundle 的默认开关，复用 IDF 内建证书；只用于 HA 内网地址确实配置为 HTTPS 的情况。HTTP 是当前局域网首选，不要求部署证书，不增加自签证书或逐设备证书配置。HTTPS 时通过 `crt_bundle_attach=esp_crt_bundle_attach` 使用标准 CA 验证，不得设置跳过验证。当前本机 sdkconfig 已启用该选项，但 tracked defaults 尚无，需补齐可复现默认值。
- [ ] 在 `CMakeLists.txt` 添加 ESP-IDF 内置 `esp_http_client` 和 `mbedtls` 依赖（后者用于内置 CA bundle API）；不新增第三方 HTTP 库。
- [ ] 写 URL/协议测试：只接受 HA 下发的绝对 HTTP(S) URL；拒绝空 URL、非 HTTP(S) scheme 和超长字段；不开放任意本地文件路径或 URL 自发现接口。错误日志不得包含 URL/token。只做协议所需校验，不增加 URL 白名单服务或通用鉴权框架。
- [ ] 实现 `audio_resource.c/.h`：单一 active playback_id、独立 HTTP task、HTTP_EVENT_ON_DATA chunk callback、2xx 校验、Content-Type media type 比较（忽略大小写和参数）、未知长度流读取、reader callback、资源状态和错误回报。
- [ ] Content-Length 不得用于预分配整段音频缓存；HTTP chunk 边界不得被解释为 MP3/WAV frame boundary；data callback 失败转为 failed 并清理 request。
- [ ] 新的不同 playback_id 在活动 GET 期间到达，返回 ERROR `audio_busy`；不建立并发/等待队列。AUDIO_STOP 带 expected_audio_id 时只停止同 ID；ID 不匹配是 no-op；缺省 ID 停止当前唯一请求；重复 STOP 幂等。
- [ ] HTTP 正常 EOF 后在所有 chunk 已交给 reader 的前提下发送 `resource_ready`；STOP 发送 `stopped`；状态码/MIME/连接错误发送 `failed` 和对应 error_code。实现并验证 `protocol_invalid_header`、`protocol_invalid_payload`、`protocol_unsupported_message`、`reverse_queue_full`、`audio_busy`、`audio_http_failed`、`audio_http_status`、`audio_content_type_mismatch`、`operation_cancelled`；正常用户 STOP 只报告 `stopped`，不把预期取消记成失败。禁止发送 completed。
- [ ] diagnostics dispatcher 处理 TTS_PLAY/AUDIO_STOP，仅做 payload 校验和启动/停止请求，不在 7778 listener/select worker 内调用阻塞 HTTP perform。
- [ ] 建立受控 HTTP server 与开发板联合测试：板卡从 HA/NAS 内网 HTTP 地址 GET，验证分块到达 reader、未知 Content-Length 持续传递、MIME/HTTP 状态校验、活动请求 STOP。若实际 HA internal_url 使用 HTTPS，再验证内建 CA bundle；不为测试专门引入自签证书设施。
- [ ] 运行 ESP-IDF v6.1 build、P5/P6 protocol tests；检查编译配置中 `esp_http_client` 生效；HTTPS CA bundle 选项保持可用。

**Exit gate:** C13–C16/C18 通过；GET 在独立 task 中流式工作，资源读取完成不被误报为播放完成；STOP 仅取消目标 HTTP request；未引入 decoder、SRC、I²S TX 或 AUX 输出。

### P6b6 — 全链路集成、回归和 P6 验收

**Files:**
- Modify: `README.md`、`esp32/firmware/README.md`（阶段状态/接口文档，按真实验收结果更新）
- Create: `docs/superpowers/reports/2026-11-12-p6-acceptance-report.md`
- Modify: only tests/files required to repair demonstrated P6 contract defects; no unrelated cleanup

**Tasks:**
- [ ] 检查 branch、HEAD、工作区和 P6b0–P6b5 每批实现提交；确认不存在 P6 外改动、未完成测试或仅靠手动现象标 PASS 的合同。
- [ ] 运行 HA Tivoo 整套回归：`./scripts/test-ha.sh tests/homeassistant/custom_components/tivoo -q`；另跑 P3 conversation/session/SSE regression。
- [ ] 运行 ESP32 所有 P5/P6 POSIX tests：`.venv/bin/python -m pytest tests/esp32 -q`；运行 HA protocol golden tests，确保 C/Python 产生的 TVIO header、type、Sequence、payload 字节一致。
- [ ] 在 ARM Ubuntu 用 ESP-IDF v6.1 / esp32 target 执行 clean build；检查 warnings/errors、sdkconfig defaults、dependencies.lock、分区和现有 16MiB/8MiB 配置未漂移。
- [ ] 实机验收 7777：现有 HA command 正向控制仍有效；Tivoo SPP 返回字节能原样返回 HA；0x69/0x96 hint 只更新提示状态；连续控制/动画时反向队列无明显丢失；7777 断开不释放正常 SPP。
- [ ] 实机验收 7778：HELLO/ACK 能力正确；15s PING/PONG；模拟失联 45s 后只重连 7778；GET_STATUS 包含真实 Wi-Fi/TCP/SPP；Wi-Fi/SPP 事件按状态变化上报；7778 reconnect 不重置 SPP。
- [ ] 实机验收 TTS URL/HTTP：HA 流式回复在 tts_start_streaming 后触发 TTS_PLAY；ESP32 从 HA LAN TTS Proxy 获取 HTTP 资源；chunk 持续传入 reader；短回答走 tts-end；错误状态、AUDIO_STOP、过期 STOP 和 HTTP busy 行为符合合同。此项只验收到 HTTP resource reader，不把“无声音输出”记成失败或“已播放”记成通过。
- [ ] 验证 7777/7778 独立断线恢复、Wi-Fi 断开/恢复后的 listener/HA 自动重连；确认 token/URL/PCM/凭据未进入日志。
- [ ] 真实设备更新仅使用 app-only image `0x10000`，保留 NVS/Wi-Fi/SPP Bond；不 erase flash、不刷写覆盖 NVS 的 merged image，除非用户另行明确要求。
- [ ] 运行 Ruff、HA 测试、ESP32 tests、ESP-IDF build、Markdown relative link check、`git diff --check`；逐条对照 P6-C01–C20。
- [ ] 报告区分 Python/C 自动化、IDF build、真实硬件观察和未执行项；任何硬件未测、网络不可达或测试缺口标记 BLOCKED/NOT RUN，不得折算 PASS。
- [ ] 只有 C01–C20 全部有证据后，才更新 README 将 P6 标记为完成；不修改 P6.5/P7/P8 的状态，不将 HTTP resource_ready 写成 audio playback completed。

**Exit gate:** P6-C01–C20 全部通过；P5 全量回归及 P6 自动化、IDF build、必要实机合同均有可追溯证据；工作区差异仅包含 P6 已验收交付。


## 6. 合同覆盖与阶段边界

| 合同 | 主批次 | 补充验证 |
|---|---|---|
| P6-C01 | P6b0/P6b6 | 所有 P5 config、帧、端口和 logger 回归 |
| P6-C02–C04 | P6b1 | 7777 raw SPP reverse queue、部分发送、断线与真实 DATA_IND |
| P6-C05–C06 | P6b0 | Python/C golden frames、HELLO capability 与 ACK |
| P6-C07–C10 | P6b2 | fake clock、状态 getter、事件去重、错误脱敏 |
| P6-C11 | P6b3 | session schema、binary PCM 和 bounded async iterator |
| P6-C12 | P6b4 | HA internal_url/LAN fallback 与 TTS event 时序 |
| P6-C13–C16 | P6b5 | 本地 HTTP server + 真实 ESP32 HTTP Client；STOP/状态/error |
| P6-C17 | P6b2/P6b6 | 两端口独立重连、Wi-Fi 断开恢复及 SPP 连续性 |
| P6-C18–C19 | P6b1/P6b3/P6b5/P6b6 | 文件范围与源代码 review；不引入 P7/P8 功能、不包装 SPP |
| P6-C20 | P6b6 | P5 全回归、P6 测试、ESP-IDF v6.1 build、实机报告 |

### 6.1 明确的交接点

- **交给 P7：** HA `AudioSessionManager.async_audio_iterator(session_id)`、MIC_CAPTURE_STOP dispatch seam 和稳定的 16 kHz S16LE PCM 消息合同。P7 负责创建 Satellite/Pipeline、I²S RX、AFE/AEC/VAD 和 MIC producer。
- **交给 P8：** ESP32 `tivoo_audio_resource_set_reader()` 提供编码音频 bytes；P8 负责 decoder、跨 HTTP chunk 的容器/codec 状态、SRC、PCM queue、I²S TX 和真实 playback lifecycle。
- **交给 P6.5：** P6 的 HTTP STOP 和 transport disconnect 只证明 ESP32 资源请求可停止，不代表 HA Pipeline/TTS Proxy/AstrBot 的取消已传播；该验证必须由 P6.5 单独提供证据。
- **SPP 上游复用：** P6b1 只移植 `esp32-divoom` 的 SPP backward → TCP output 语义和 0x69/0x96 hint；不得移植其新协议、MQTT 或其它无关模块。

### 6.2 P6.5 单独阶段

P6.5 依据 `docs/superpowers/patches/2026-11-11-p6-5-ha-cancellation-preflight.patch.md`，安排在 P6b6 完成后、依赖完整取消/打断的 P7/P8 runtime 验收之前。仓库当前没有 `docs/superpowers/reports/2026-11-11-ha-cancellation-preflight-report.md`；因此计划明确将 P6.5 标记为 NOT RUN，P6 不得代替其验收或提前更新其状态。

## 7. 单批执行与提交规则

1. 每个批次开工前核对当前分支、HEAD 和工作区；识别上批遗留差异，不覆盖其它工作。
2. 重新阅读本计划对应批次和 P6 合同矩阵对应章节；矩阵与代码事实冲突时先停止受影响行为，核实源码后更新合同/计划。
3. 每个新行为先补测试并运行确认 RED，再实现最小改动，运行 GREEN 和指定回归。不得先完成实现再补一个无法证明旧行为失败的测试。
4. 每批只修改本批 Files 清单及必要的关联 README；发现下游必需的接口缺口时，当前批次只定义并测试稳定接口，不提前实现下游行为。
5. 每批至少运行聚焦 pytest、相关 P5 regression、Python lint/compile（改 Python 时）、ESP32 host simulator（改 C 时）及 `git diff --check`。涉及固件源文件/组件依赖的批次执行 IDF build。
6. 每批结束记录基线 SHA、文件范围、RED/GREEN 命令与退出码、测试数量、IDF build 结果、合同 ID、未执行/阻塞的真实设备检查。
7. 一个批次一个本地 commit，commit 只包含该批次的实现、测试、文档和报告；不自动 merge main、不推送远端、不刷写设备。只有用户另行明确要求时才做 push/merge/flash。
8. 不可运行的硬件测试标记 BLOCKED/NOT RUN 并说明原因；不能以 POSIX 模拟、源码 review 或编译通过替代真实 SPP/HTTP 设备验收。
9. P6b6 只有在 P6-C01–C20 均具备证据时才能将 README 标记为 P6 完成；否则逐项记录缺口，不降低合同门槛。
10. 若没有可用独立 reviewer/subagent，执行者完成自审并如实记录，不伪称外部 reviewer 已审查。

## 8. 总体完成条件

- P6-C01–C20 全部有对应自动化、构建或真实设备证据；每条证据能指向具体测试/输出/报告章节。
- P5 功能和行为完整保留；7777/7778 独立连接；SPP 返回数据原样透传；设备状态/事件只反映真实观测。
- MIC 会话入口有界、按 session_id 隔离，并可由后续 P7 直接消费；P6 不开始真实收音。
- HA TTS event → 内网 TTS Proxy URL → 7778 TTS_PLAY → ESP32 HTTP GET → reader callback 的数据链路通过；HTTP resource stop 和状态正确；P6 不产生声学播放结论。
- ESP-IDF v6.1 / esp32 target 构建成功，P5/P6 测试通过，真实设备验收与自动化证据在报告中分开。
- README 阶段状态只反映 P6 已验收范围；P6.5 报告缺失状态、P7/P8 未实现边界均被保留。
