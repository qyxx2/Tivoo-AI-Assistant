# P6 ESP32 ↔ Home Assistant 双向通信合同矩阵

> **日期：** 2026-11-12
> **分支：** `feature/p6-esp32-ha-bidirectional-communication`
> **基线：** `main` / `a2b0127`
> **状态：** P6 范围与接口合同已确定；[详细实施计划](../plans/2026-11-12-p6-esp32-ha-bidirectional-implementation-plan.md)与[分批执行计划](../plans/2026-11-12-p6-esp32-ha-bidirectional-batch-execution-plan.md)已建立
> **范围：** 在 P5 已有固件和 HA Tivoo 集成上完成双向 7777/7778 通信、状态/事件/连接管理及 HA 音频资源 HTTP GET

## 1. 目的与权威依据

P6 在 P5 已验收的 TCP 7777、TCP 7778 基础上完成双向设备通信、设备状态/事件、连接管理及 HA 音频资源 HTTP GET。P6 不重做 P5，不另建第二套控制协议，也不把 P7/P8 的音频算法和硬件运行时提前并入。

本矩阵固定 P6 的阶段范围、接口、消息结构、实现边界和验收条件。权威关系如下：

1. 本矩阵是 P6 阶段合同。
2. 上位协议依据 [ESP32 ↔ Home Assistant 双向通信层规格书](2026-11-09-esp32-ha-bidirectional-communication-design.md)。
3. P5 已冻结行为依据 [P5 ESP32 最小固件合同矩阵](2026-11-11-p5-esp32-minimal-firmware-contract-matrix.md) 及 P5 实际代码/验收记录。
4. AstrBot SSE/session Stop 依据 [P3 合同矩阵](2026-11-09-p3-astrbot-conversation-contract-matrix.md)。
5. Wyoming TTS 请求及 PCM 格式依据 [P7A 合同矩阵](2026-11-10-p7a-sherpa-wyoming-contract-matrix.md)。
6. P6.5 取消链路前置验证依据 [P6.5 patch](../patches/2026-11-11-p6-5-ha-cancellation-preflight.patch.md)。P6.5 是 P6 之后的独立验证批次，不属于 P6 实现。

P5 已通过的端口、线格式、设备 MAC 来源、SPP Bond/NVS、日志和诊断子集必须保持兼容。需要扩展的地方应以新增消息或新增状态实现，不静默改变旧消息语义。

## 2. 当前真实状态与差距

### 2.1 P5 已有且必须保留

| 层 | 当前实现 | P6 处理 |
|---|---|---|
| HA 配置 | `esp32_host`、用户确认的 `tivoo_bluetooth_mac`、媒体目录；Config Entry v2 | 沿用；Tivoo Classic MAC 仍是唯一权威来源 |
| HA 7777 | `Esp32ConnectionAdapter` 独立连接/重连；发送 `0x69 + MAC` 和 Tivoo 原始帧；当前只读后丢弃 | 增加反向字节读取与状态提示解析 |
| HA 7778 | `diagnostics.py` 的 TVIO v1 头部/增量解析；HELLO、HELLO_ACK、ERROR、DIAGNOSTIC_LOG | 扩展现有 codec/transport，不替换 |
| ESP32 TCP | `network_listeners.c` 监听 7777/7778，各接受一个 HA client；两通道独立 | 保持端口、连接数量和独立生命周期；增加发送队列 |
| ESP32 7777 | `control_bridge.c` 处理 7 字节连接/断开命令和完整 Tivoo 帧；复用 frame-stream parser | 增加 SPP 返回数据透传 |
| ESP32 SPP | `tivoo_spp.c` 已完成 Classic SPP、SDP、FIFO 写队列、Bond/NVS 和断线重连；`ESP_SPP_DATA_IND_EVT` 当前忽略 | 将 SPP 接收数据送入 7777 反向发送队列 |
| ESP32 7778 | `diagnostics.c` 只处理 P5 HELLO/ACK 和诊断队列 | 扩展双向消息、状态与心跳，保留 P5 日志语义 |
| HTTP/音频 | HA Tivoo transport 与固件均未实现 TTS HTTP resource client | 增加流式 HTTP Client；音频解码/输出由 P8 接入 |

P5 代码与测试位置：

- 固件：`esp32/firmware/main/control_bridge.c`、`network_listeners.c`、`tivoo_spp.c`、`diagnostics.c`。
- HA：`homeassistant/custom_components/tivoo/transport.py`、`diagnostics.py`、`protocol.py`、`commands.py`。
- 测试：`tests/esp32/`、`tests/homeassistant/custom_components/tivoo/`。

### 2.2 上游复用依据

本地 `BluetoothBridgeTest/esp32-divoom` 的 `input_tcp.cpp`、`output_bluetooth.cpp`、`hardware_bluetoothctl.cpp` 已实现：

- TCP 命令转发到 SPP。
- SPP 的 `ESP_SPP_DATA_IND_EVT` 通过反向通道原始透传回 TCP。
- SPP 不可写时，通过单字节 `0x69`（连接中）/ `0x96`（无连接）提示上游。

P6 直接沿用这些既有语义；不创造第二种 7777 ACK 协议，不给原始 SPP 数据加包装。

当前 HA Core 固定版本为 **2026.11.0**。其 TTS Proxy 路径为 `/api/tts_proxy/{token}`，`TextToSpeechView.requires_auth=False`，GET 响应逐块写出 Provider 数据。TTS URL 中已经含有短时 token；P6 不再额外传 Bearer token，也不增加 URL query token 或自建音频代理。

## 3. P6 目标、非目标与实现原则

### 3.1 方案选择

本阶段比较了三种方向，最终采用第一种：

1. **保留上游 7777 原始双向透传 + 扩展既有 TVIO v1 + HA 原生 TTS Proxy HTTP GET（采用）。** 与本地 `esp32-divoom` 的 SPP 返回通道兼容，P5 已有的 7777/7778 可以直接增量扩展；HTTP 资源复用 HA 已有能力，不增加 NAS 服务和配置项。
2. **把 7777 返回数据包装成 JSON/TVIO，并增加逐命令 ACK（不采用）。** 会破坏现有上游反向字节语义，无法为多数 write-only Tivoo 命令提供真实显示确认，还要增加 ID、重试和关联状态，收益不足。
3. **另建 MQTT/WebSocket/HTTP 控制或自建音频资源服务（不采用）。** 与当前两个 TCP 长连接和 HA TTS Proxy 重复，增加部署和维护面，不符合本项目已有架构。

因此 P6 不新增控制协议、不新增消息总线、不新增命令级 ACK、不自建资源代理；只把项目已有协议补完整。

### 3.2 P6 必须完成

- 保持 P5 7777、7778 端口及已通过的 P5 子协议。
- 7777 双向透传：HA → ESP32 → Tivoo 的既有命令不变；SPP 返回字节及上游桥接状态提示可沿同一 TCP 连接回到 HA。
- 7778 完成 TVIO v1 双向消息处理：心跳、状态查询/上报、设备事件、麦克风会话消息、TTS 资源通知、停止/状态/打断消息及错误。
- 7777、7778 独立连接、独立重连；7778 重连不得重置仍正常工作的 SPP 会话。
- ESP32 收到 TTS_PLAY 后能够主动 GET HA 提供的资源 URL，并以有界内存流式读取；不得把完整资源读入 RAM。
- HA transport 对 7778 消息完成校验、分发和会话关联；为 P7/P8 提供稳定接入点。
- 所有设备状态必须来自实际可观测数据；不得虚构电量、显示确认或未实现的音频硬件状态。

### 3.3 后续阶段边界

| 阶段 | 专属工作 | P6 不代做 |
|---|---|---|
| P7 | I²S RX、INMP441、AEC/VAD、预录缓冲、真实 MIC_PCM 生产、HA Assist Satellite Pipeline、KWS/STT 联调 | P6 只完成 MIC 消息的协议解析、传输入口和有界分发 |
| P8 | MP3/WAV 解码、SRC、I²S TX、PCM5102/AUX、统一音频输出管理器、实际播放/停止和完成语义 | P6 只完成 TTS URL 获取与字节流接口，不实现解码和播放 |
| P9/P10 | AstrBot 表情/主动对话、长期并发与备用 A2DP 专项验证 | 不纳入 P6 |

P6 可以使用模拟消息和测试资源验证 MIC/TTS 传输合同；不得以此声称实际麦克风、AEC/VAD、解码或 AUX 播放已完成。

### 3.4 代码实现原则

- 优先移植/适配 `esp32-divoom` 的 SPP 反向回传和上游状态字节行为。
- HA 继续复用当前 Tivoo 命令、图片、动画和文字编码，不改变业务参数。
- 扩展当前 TVIO v1 codec 与 P5 transport，不引入新的协议库或消息总线。
- HTTP 使用 ESP-IDF 自带 HTTP Client；HA 音频资源使用 HA 原生 TTS Proxy。
- 采用固定心跳参数，不做心跳协商、重试策略矩阵或多套保活机制。
- 单设备、单 HA client、单活动 TTS 资源请求；不为尚不存在的并发场景建立复杂队列。

## 4. TCP 角色与通用消息合同

### 4.1 端口与方向

| 通道 | HA 角色 | ESP32 角色 | 传输内容 |
|---|---|---|---|
| TCP 7777 | Client | Server | 上游 Tivoo 原始控制字节流，全双工 |
| TCP 7778 | Client | Server | TVIO v1 消息，全双工 |
| HTTP(S) | Server | Client | ESP32 主动 GET HA 提供的 TTS 资源 |

- 默认端口保持 7777/7778；每个 TCP 端口只接受一个 HA client。
- ESP32 不开放 HTTP Server，不直接连接 AstrBot、MCP Server 或云端 LLM。
- 7777 与 7778 的连接状态分别维护。任一通道断开只重连对应通道。

### 4.2 TVIO v1 固定头部

P6 沿用 P5 的 16-byte header，不改变字节布局：

| 偏移 | 长度 | 字段 | 语义 |
|---:|---:|---|---|
| 0 | 4 | Magic | ASCII `TVIO` |
| 4 | 1 | Version | `1` |
| 5 | 1 | Message Type | 消息类型枚举 |
| 6 | 2 | Flags | little-endian；v1 固定为 0 |
| 8 | 4 | Payload Length | little-endian uint32 |
| 12 | 4 | Sequence | little-endian uint32 |
| 16 | N | Payload | JSON UTF-8 或消息定义的二进制数据 |

- 每个发送方向独立计数；每条新 TCP 连接的 Sequence 从 0 开始，uint32 自然回绕。
- 接收方必须处理 TCP 拆包/粘包；不允许假定一次 recv/read 对应一条完整消息。
- JSON Payload 最大 16 KiB；单个 MIC_PCM 二进制 Payload 最大 4 KiB。检查长度后再分配/复制。
- Magic、Version、Flags、Sequence 或 Payload Length 非法时，关闭当前 7778 连接；不扫描后续字节猜测帧边界。
- 未知 Message Type 在帧结构合法时忽略该消息并记录一次协议错误，不使进程崩溃。

### 4.3 Message Type

| Type | 名称 | 方向 | Payload |
|---:|---|---|---|
| `0x01` | HELLO | ESP32 → HA | JSON：设备 ID、固件版本、协议版本、能力列表、Reset Reason |
| `0x02` | HELLO_ACK | HA → ESP32 | JSON：`accepted`，不兼容时含 `reason` |
| `0x03` | PING | HA → ESP32 | 空 |
| `0x04` | PONG | ESP32 → HA | 空 |
| `0x10` | GET_STATUS | HA → ESP32 | JSON：`request_id` |
| `0x11` | DEVICE_STATUS | ESP32 → HA | JSON：状态快照，回显 `request_id` |
| `0x20` | MIC_SESSION_START | ESP32 → HA | JSON：音频格式、session_id、trigger_source、preroll 和 interrupt_id |
| `0x21` | MIC_PCM | ESP32 → HA | 二进制：16 kHz S16LE Mono PCM |
| `0x22` | MIC_SESSION_END | ESP32 → HA | JSON：session_id、结束原因 |
| `0x23` | MIC_CAPTURE_STOP | HA → ESP32 | JSON：session_id、停止原因 |
| `0x30` | TTS_PLAY | HA → ESP32 | JSON：playback_id、绝对 URL、mime_type |
| `0x31` | AUDIO_STOP | HA → ESP32 | JSON：request_id、可选 expected_audio_id、reason |
| `0x32` | AUDIO_STATE | ESP32 → HA | JSON：audio_id、source、state、可选字节数/错误码 |
| `0x33` | AUDIO_INTERRUPTED | ESP32 → HA | JSON：interrupt_id、audio_id、source、reason |
| `0x40` | DEVICE_EVENT | ESP32 → HA | JSON：事件名、uptime_ms、事件数据 |
| `0x41` | ERROR | 双向 | JSON：error_code、module、message、uptime_ms、关联 ID |
| `0x42` | DIAGNOSTIC_LOG | ESP32 → HA | P5 诊断日志 JSON，字段和脱敏规则不变 |

HELLO 沿用 P5 的必需字段，要求 `device_id=tivoo-esp32`、非空 `firmware_version`、`protocol_version=1`、`reset_reason` 和能力列表。`capabilities` 在 P6 至少声明 `spp_control`、`spp_reverse`、`remote_diagnostics`、`device_status`、`device_events`、`audio_resource_http`、`audio_control`。不声明尚未实现的 I²S、AEC、VAD、mic_capture 或 audio_playback 能力。

HELLO_ACK 保持最小结构：成功为 `{"accepted":true}`，拒绝为 `{"accepted":false,"reason":"unsupported_protocol_version"}`。心跳参数为固定合同值，不在握手中协商。

## 5. TCP 7777：Tivoo 原始控制桥双向合同

### 5.1 HA → ESP32：保持上游格式

- 连接 SPP：`0x69 + 6-byte Classic MAC`。
- 断开 SPP：`0x96 + 6-byte Classic MAC`。
- Tivoo 命令：`01 <length_lo> <length_hi> <command + params> <checksum> 02`。
- MAC 必须来自 HA Config Entry 的 `tivoo_bluetooth_mac`，不从设备扫描、设备状态或固件默认值推断。
- HA 按原始字节写入，保持现有动画 chunk 顺序和服务调用顺序。

### 5.2 ESP32 → HA：复用上游反向通道

- `ESP_SPP_DATA_IND_EVT` 收到的数据通过当前 7777 TCP 连接原始回传。
- SPP 返回数据不添加长度前缀、JSON、Base64 或 TVIO header。
- 兼容上游单字节提示：`0x69` 表示连接中，`0x96` 表示当前未连接/不可写。HA 将其作为提示状态，不把它当作某条 Tivoo 命令的 ACK。
- 真实 SPP 连接状态以 7778 DEVICE_STATUS/DEVICE_EVENT 为权威来源；原始 SPP 返回数据不等于屏幕显示确认。

### 5.3 命令结果语义

P6 不新增命令级 ACK，不增加 command_id，也不为每条 write-only 屏幕命令虚构 confirmed 结果。

- TCP `drain()` 成功只说明字节写入本机 TCP 缓冲。
- ESP32 接受完整帧进入 SPP 队列不代表 Tivoo 已接收。
- SPP WRITE_EVT 成功表示驱动写入完成，不代表屏幕已经显示。
- 只有 Tivoo 协议确实返回可关联的数据时，才把该返回内容交给 HA；不推断它属于哪一条命令。
- HA 服务调用继续保持“发送成功/失败”的传输层结果，不把它描述为屏幕已确认。

### 5.4 队列与断线

- SPP callback 不直接执行阻塞 socket send；通过固定深度有界队列交给 7777 发送 worker。
- TCP 发送队列暂时满时等待后续可写机会；队列满时丢弃新反向数据并记录 `reverse_queue_full`，不阻塞 SPP 回调。
- 7777 断开时丢弃属于该 TCP session 的待回传数据并清理解析状态，不自动断开健康的 SPP。
- 新 7777 连接由 HA 按 P5 逻辑重发 `0x69 + MAC`，恢复 SPP 控制。
- 7777 的反向发送失败不能影响 7778、诊断日志、Wi-Fi 或 SPP worker。

## 6. TCP 7778：心跳、状态和事件

### 6.1 心跳

- HA 是唯一主动发送 PING 的一方；ESP32 收到 PING 后立即回复空 Payload PONG。
- 间隔固定 **15 秒**；**连续 45 秒未收到有效 PONG**，HA 关闭并重连 7778。
- 7778 重连后重新执行 HELLO/HELLO_ACK，Sequence 重新从 0 开始。
- 7778 心跳超时不关闭 7777，不断开 SPP，也不终止正在运行的 Wi-Fi。
- 不增加第二种应用层 heartbeat、TCP keepalive 参数协商或指数退避。重连复用现有独立连接循环。

### 6.2 GET_STATUS / DEVICE_STATUS

HA 发送：

```json
{
  "request_id": "uuid"
}
```

ESP32 返回：

```json
{
  "request_id": "uuid",
  "device_id": "tivoo-esp32",
  "firmware_version": "0.1.0+<git-short-sha>",
  "uptime_ms": 123456,
  "wifi": {
    "state": "connected",
    "ip": "192.168.3.100",
    "rssi_dbm": -55
  },
  "tcp": {
    "7777": "connected",
    "7778": "connected"
  },
  "spp": {
    "state": "connected",
    "mac": "11:75:58:97:49:98"
  },
  "audio_resource": {
    "state": "idle",
    "playback_id": null
  }
}
```

字段合同：

- `request_id` 必须原样回显，便于 HA 匹配查询结果。
- `wifi.state`：`connected` 或 `disconnected`；IP/RSSI 仅在实际取得时提供。
- `tcp`：分别报告 7777、7778 当前 client 状态。
- `spp.state`：`disconnected`、`connecting` 或 `connected`；MAC 为当前目标 peer，未知时省略。
- `audio_resource.state`：`idle` 或 `fetching`；有活动请求时回报 playback_id，没有活动请求时为 null。下载完成或失败通过 AUDIO_STATE 上报，不保留一份与当前状态矛盾的历史快照。
- P6 不输出 mic/AEC/VAD、播放完成、DAC、电池或屏幕显示状态。这些状态在对应阶段具备真实数据源后再加入。

HELLO_ACK 成功后 HA 可发送一次 GET_STATUS；之后状态变化通过 DEVICE_EVENT 上报，HA 不需要高频轮询。

### 6.3 DEVICE_EVENT

统一结构：

```json
{
  "event": "spp_connected",
  "uptime_ms": 123456,
  "data": {
    "mac": "11:75:58:97:49:98"
  }
}
```

P6 固定事件名：

- `wifi_connected` / `wifi_disconnected`
- `spp_connecting` / `spp_connected` / `spp_disconnected)

事件只在状态发生变化时发送；HA 收到后更新缓存状态。状态丢失或重新连接后，HA 通过 GET_STATUS 获得完整快照。

### 6.4 ERROR

P6 扩展 P5 error_code 集合，至少包括：

- `protocol_invalid_header`
- `protocol_invalid_payload`
- `protocol_unsupported_message`
- `reverse_queue_full`
- `audio_busy`
- `audio_http_failed`
- `audio_http_status`
- `audio_content_type_mismatch`
- `operation_cancelled)

保留 P5 已有错误码；错误消息必须有 module、message、uptime_ms，并在可用时包含 playback_id/session_id/request_id。不得写入短时 URL、token、Wi-Fi 凭据或 PCM 正文。

## 7. TCP 7778：麦克风会话传输合同（为 P7 提供接口）

P6 建立消息 schema、字节流处理、Sequence 和 HA 分发入口；实际 I²S 采集/AEC/VAD/MIC_PCM 生产属于 P7。

### 7.1 MIC_SESSION_START

```json
{
  "session_id": "uuid",
  "sample_rate": 16000,
  "channels": 1,
  "sample_format": "s16le",
  "frame_duration_ms": 20,
  "preroll_ms": 500,
  "trigger_source": "idle_vad"
}
```

- `trigger_source` 仅允许 `idle_vad`、`barge_in`。
- barge-in 时必须包含 `interrupt_id`；普通 idle_vad 不需要。
- 采样格式固定为 16 kHz / Mono / signed 16-bit little-endian，和 P7A KWS/STT 输入合同一致。

### 7.2 MIC_PCM

- 二进制 Payload，不使用 Base64/JSON。
- 典型帧长 20 ms：320 samples、640 bytes。
- 单个 Payload 不超过 4 KiB。
- P7 产生的内容必须是 AEC 后的唯一音频流；P6 不接收或转发未经 AEC 的原始麦克风音频。

### 7.3 MIC_SESSION_END / MIC_CAPTURE_STOP

ESP32 → HA：

```json
{
  "session_id": "uuid",
  "reason": "completed"
}
```

HA → ESP32：

```json
{
  "session_id": "uuid",
  "reason": "pipeline_finished"
}
```

- 同一设备最多一个活动网络 MIC 上传 session。
- HA 必须以 session_id 匹配；迟到的旧 session 消息不能关闭新 session。
- MIC_CAPTURE_STOP 只停止指定的网络上传 session，不关闭物理 I²S RX/AEC/VAD；该硬件语义由 P7 实现。若目标 session 已结束或不存在，按幂等 no-op 处理。
- HA transport 将 MIC_SESSION_START/MIC_PCM/MIC_SESSION_END 分发给后续 audio_session 接口；P6 不调用 Assist Pipeline，不实现 wake word/STT 生命周期。

## 8. TTS 音频 HTTP 资源获取合同

### 8.1 HA URL 生成

- HA 从 Assist Pipeline 的 `run-start` / `tts-end` 事件取得 TTS Proxy 相对 URL 和 mime_type。
- 使用 HA Core `homeassistant.helpers.network.get_url()` 选择内网地址，调用约束：`allow_external=False`、`allow_cloud=False`、`allow_internal=True`、允许普通 LAN IP。
- 将内网 base URL 与 TTS Proxy 相对路径合成为 ESP32 可访问的绝对 URL。优先使用 HA 配置的 internal_url；未配置时使用 HA Core 可检测的本机 LAN IP。
- 不新增 ESP32 HTTP Host、URL 前缀或第二个 HA 地址配置项。
- 若 HA Core 无法取得可用内网地址，HA 记录明确的 TTS resource URL 错误，不向 ESP32 发送不可达 URL。

### 8.2 TTS_PLAY Payload

```json
{
  "playback_id": "uuid",
  "url": "http://192.168.3.94:8123/api/tts_proxy/<opaque-token>",
  "mime_type": "audio/mpeg"
}
```

- URL 必须是绝对 HTTP(S) URL，路径包含 HA TTS Proxy token。
- P6 不单独传 `token` 字段、不使用 Authorization header；HA Core 2026.11.0 的 TTS Proxy 已通过路径 token 标识资源且 `requires_auth=False`。
- `mime_type` 来自 Pipeline 事件，是预期类型；ESP32 仍检查 HTTP 响应 Content-Type。
- HA 只在流式 TTS 的 `intent-progress` 出现 `tts_start_streaming=true` 后发送 TTS_PLAY；短回答/非流式路径在 `tts-end` 发送。
- `tts-end` 不等于播放完成。P6 的 HTTP fetch 完成也不冒充音频播放完成。

### 8.3 ESP32 HTTP Client

- 复用 ESP-IDF HTTP Client；支持 HTTP 和标准 CA 可验证的 HTTPS，不跳过 TLS 证书验证。
- 只接受 HA 下发的绝对 HTTP(S) URL；不提供任意文件路径、NAS 内部路径或自行拼接资源路径的接口。
- 发起 GET，要求 HTTP 2xx；读取响应 Content-Type，并与 TTS_PLAY 的 mime_type 比较 media type（忽略大小写及参数差异）。
- 响应格式不匹配时返回 `audio_content_type_mismatch`，不将错误内容交给后续解码层。
- 使用 HTTP data callback/流式 read 将数据块交给后续消费者；每次传递有界数据块，不完整缓存文件，不要求 Content-Length 存在。
- HTTP chunk 边界不是音频帧边界；不在 P6 做解码。P8 解码器负责跨 chunk 保持容器/codec 状态。
- 连接/读取失败或非 2xx 返回明确 ERROR/AUDIO_STATE；不记录完整 URL。
- 同一时刻只允许一个活动资源 GET。第二个不同 playback_id 到达时返回 `audio_busy`；不在 P6 建立未被当前业务需要的并发下载队列。
- HTTP 资源流通过明确的 reader/callback 接口暴露给 P8；P6 测试用可控 sink 验证完整流式传递，P8 将其接入 decoder。不得为 P6 编写临时音频解码器或将文件整体放入 RAM。

### 8.4 AUDIO_STATE / AUDIO_STOP

P6 使用的 AUDIO_STATE：

```json
{
  "audio_id": "uuid",
  "source": "tts_http",
  "state": "buffering",
  "bytes_received": 4096
}
```

P6 资源状态：

- `buffering`：HTTP GET 已开始，正在读取资源。
- `resource_ready`：HTTP 响应体正常结束，资源字节流完整交给消费者。
- `stopped`：对应 HTTP 请求被停止。
- `failed`：HTTP、状态码或 Content-Type 失败，附 error_code。

P8 增加 `playing`、`completed`、`interrupted` 等真实输出状态；P6 不在资源下载结束时发送 `completed`。

AUDIO_STOP：

```json
{
  "request_id": "uuid",
  "expected_audio_id": "uuid",
  "reason": "user_stop"
}
```

- 有 expected_audio_id 时只停止匹配的资源请求；不匹配则忽略过期 stop。
- 缺少 expected_audio_id 时停止当前唯一活动请求。
- 取消 HTTP task、释放当前请求资源并回报 stopped；重复停止必须幂等。
- P6 的 AUDIO_STOP 只结束 HTTP resource fetch；P8 扩展为停止 decoder、PCM 缓冲和最终音频后端。

## 9. 连接管理与错误恢复

- HA 分别持有 7777、7778 的连接循环，复用当前 `Esp32ConnectionAdapter` 模型。
- 7777 断开：重建 7777，重新发送 `0x69 + MAC`；不因为 TCP 断开而假报 SPP 已断开。
- 7778 断开：清理本连接 parser/Sequence/心跳状态，重连并重新 HELLO/HELLO_ACK；不重启 SPP。
- 7778 HELLO_ACK 前不接受业务消息；HELLO_ACK accepted 后发送一次 GET_STATUS。
- Wi-Fi 地址丢失时 ESP32 关闭两个连接并等待重新获得 IP；恢复后重新监听，HA 两条连接分别恢复。
- 重连不自动续传 MIC session 或 HTTP 音频资源；由 HA 当前 session/playback_id 状态决定是否重新发起。
- P5 有界诊断队列和日志补发行为不被新消息发送队列饿死；诊断队列、7777 反向队列和 7778 实时消息队列相互独立。

## 10. 安全、隐私与网络边界

- 7777/7778 只用于可信 LAN，不做公网端口映射；P6 不新增 PKI、账号体系、MQTT 或通用 API 鉴权。
- 7777 保持上游兼容的原始协议；7778 校验 TVIO version、device_id、HELLO/ACK 和消息长度。
- HTTP 只获取 HA 明确下发的音频 URL；当前 TTS Proxy 使用路径 token，不增加独立 Bearer。
- Token 仅存在短时 URL 路径和必要的运行时内存，不写入 NVS、诊断日志、ERROR、普通日志或测试快照。
- 不记录 Wi-Fi 密码、完整 URL、Authorization、原始 PCM、完整转写和 LLM 回答正文。

## 11. P6 合同矩阵

| ID | 合同 | 优先级 | 验收证据 |
|---|---|---|---|
| P6-C01 | P5 的端口、MAC 来源、Tivoo 原始帧和 P5 7778 codec 行为保持兼容 | MUST | P5 全量测试 + P6 回归 |
| P6-C02 | 7777 SPP DATA_IND 原始回传到当前 TCP client | MUST | ESP32 mock/socket test + 真实 SPP 返回数据测试 |
| P6-C03 | 7777 兼容单字节 0x69/0x96 状态提示，不创建命令级 ACK | MUST | 上游对照测试 + HA 解析测试 |
| P6-C04 | 反向数据使用有界队列，不阻塞 SPP callback；TCP 断开不影响 SPP | MUST | 队列压力、断线/重连测试 |
| P6-C05 | TVIO v1 双向 codec 支持所有 P6 message type，拆包/粘包和 Sequence 正确 | MUST | Python/C codec 单元测试、跨语言 golden tests |
| P6-C06 | HELLO 扩展能力声明；HELLO_ACK 保持 accepted/reason 简单格式 | MUST | HA/ESP32 handshake tests |
| P6-C07 | HA PING 每 15 秒；45 秒未收到 PONG 后只重连 7778 | MUST | fake clock/controlled socket tests |
| P6-C08 | GET_STATUS 返回真实 Wi-Fi/TCP/SPP/HTTP resource 状态，request_id 正确回显 | MUST | state snapshot tests + 实机 HA diagnostics |
| P6-C09 | DEVICE_EVENT 按固定事件名上报，只在状态变化时发送 | MUST | event transition tests |
| P6-C10 | ERROR 扩展 P6 error_code；P5 log/error 仍工作且敏感字段脱敏 | MUST | schema tests + log redaction/source review |
| P6-C11 | MIC_START/PCM/END/CAPTURE_STOP schema 和 bounded dispatch 接口完成 | MUST | binary payload/schema tests + mock HA receiver |
| P6-C12 | TTS URL 由 HA Core 内网 URL helper 构造，无新增配置项；不单独传 Bearer/token | MUST | HA unit test 覆盖 internal_url 与 LAN IP fallback |
| P6-C13 | TTS_PLAY 触发 ESP-IDF HTTP GET，校验状态码和 Content-Type | MUST | local HTTP test server + ESP-IDF host/device test |
| P6-C14 | HTTP response body 按块流式交给 reader，未知 Content-Length 可用，不缓存完整文件 | MUST | chunked response、长资源和受控 sink 测试 |
| P6-C15 | 同时只允许一个 HTTP resource GET；重复/过期 AUDIO_STOP 按 playback_id 处理且幂等 | MUST | busy、匹配 stop、不匹配 stop、重复 stop tests |
| P6-C16 | HTTP 错误和资源状态正确回报；P6 不把 resource_ready 说成 playback completed | MUST | status/error state tests |
| P6-C17 | 7777/7778 独立重连；7778 断开不重置 SPP；7777 断开不停止 7778 | MUST | 双端独立断线/重连集成测试 |
| P6-C18 | P6 不实现 I²S RX/AEC/VAD、codec/SRC、I²S TX/播放管理器或完整 Assist Pipeline | MUST boundary | source/scope review |
| P6-C19 | 原始 SPP 反向内容不附加包装；不新增命令级 ACK、消息总线或通用音频代理 | MUST boundary | source review + golden/negative tests |
| P6-C20 | P5 全量回归通过，新增 P6 单元/集成测试通过，IDF 固件可构建 | MUST | ARM Ubuntu test suite、IDF v6.1 build、git diff --check |

## 12. 测试策略

优先扩展现有 P5 测试工具与路径，不另造测试框架：

### 12.1 HA 测试

新增/扩展 `tests/homeassistant/custom_components/tivoo/`：

- `test_diagnostics.py`：扩展 message type、JSON schema、Sequence、最大长度、未知消息。
- `test_transport.py`：7777 反向接收、0x69/0x96 状态提示、独立连接/重连、7778 heartbeat、设备状态事件 dispatch。
- 新增 HTTP URL builder 测试：internal_url 优先；无 internal_url 时用 HA LAN IP；不使用 external/cloud URL。
- 新增 TTS resource transport 测试：TTS_PLAY 数据、MIC session 消息、AUDIO_STOP 匹配与幂等。
- 测试不得使用真实短时 token；使用伪造 opaque token，并断言日志不输出完整 URL。

### 12.2 ESP32 测试

扩展 `tests/esp32/`：

- 7777 反向 SPP DATA_IND → TCP sender、发送队列满、client 断开清理。
- 7778 encode/decode golden tests；覆盖拆包/粘包、Sequence、未知 type 和 payload size 边界。
- 心跳响应、状态快照、状态变化事件。
- HTTP Client 用本地受控测试 server 验证 2xx、非 2xx、Content-Type 不匹配、chunked/未知 Content-Length、断开和 stop。
- 验证 HTTP data callback 每次只提交有界 chunk，不构造整文件缓存。

### 12.3 构建与实机

- 开发、测试和 ESP-IDF v6.1 构建均在 ARM Ubuntu 工作区完成。
- NAS 只用于最终实机联调；不在 NAS 上构建容器或运行大型测试。
- 首轮实机验收：7777 双向 SPP 原始数据回传、7778 状态/事件/心跳、TTS Proxy HTTP GET 可达及流式读取、两端口独立重连。
- P6 不要求连接麦克风、DAC/AUX 或执行真实音频播放；这些在 P7/P8 验收。

## 13. 批次规划输入与阶段衔接

本分支创建时仓库没有独立 P6 Implementation Plan 或 Batch Execution Plan。现已按该矩阵建立两份计划；详细文件与接口任务见实施计划，批次顺序/阶段门见分批执行计划。其依赖顺序如下，不重新定义合同：

1. **P6b0**：TVIO v1 shared codec、HA dispatcher 和 ESP32 message send path。
2. **P6b1**：7777 SPP reverse channel 与 HA receive path。
3. **P6b2**：7778 heartbeat、status、device event 和 error 扩展。
4. **P6b3**：MIC session transport contract 与 bounded HA dispatch seam。
5. **P6b4–P6b5**：HA TTS URL 生成、ESP32 HTTP resource client、AUDIO_STOP。
6. **P6b6**：P5 regression、P6 full integration、IDF build 和实机验收。

P6.5 继续按既有 patch 执行，插入顺序为 P6 之后、P7 完整打断/取消验收之前。当前未找到 P6.5 报告文件，因此不能把其取消传播验证记为已完成；P6 的消息/资源传输实现不替代该验证。

## 14. 明确不做的事

- 不重写 Tivoo 帧协议、SPP 状态机、图片/动画编码或 HA TTS Proxy。
- 不新增命令级 ACK、command_id、第二套控制协议或 MQTT。
- 不新增 HA 配置项让用户重复填写 TTS URL/Token。
- 不将音频完整缓存到 ESP32 RAM，不把 PCM Base64 化。
- 不建立通用 URL 文件代理、资源发现 API、任意目录读取或用户鉴权框架。
- 不在 P6 提前做 AEC/VAD、唤醒、解码、SRC、DAC/AUX、A2DP 或完整播放生命周期。
- 不把 7778 心跳超时扩大为设备重启或 SPP 断连。

## 15. 参考资料

- 本地上游：`BluetoothBridgeTest/esp32-divoom/components/divoom/input_tcp.cpp`、`output_bluetooth.cpp`、`hardware_bluetoothctl.cpp`。
- ESP-IDF HTTP Client：<https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/protocols/esp_http_client.html>
- Home Assistant Core 2026.11.0 TTS Proxy：<https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/tts/__init__.py>
- Home Assistant Core 2026.11.0 URL helper：<https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/helpers/network.py>
- Home Assistant Assist Pipeline：<https://github.com/home-assistant/core/tree/2026.11.0/homeassistant/components/assist_pipeline>
