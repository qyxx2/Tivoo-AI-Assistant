# ESP32 ↔ Home Assistant 双向通信层规格书

> 状态：设计规格，待用户审阅  
> 日期：2026-11-09  
> 适用项目：Tivoo AI Assistant  
> 范围：ESP32-WROVER-E-N16R8 自定义固件与 Home Assistant Tivoo 自定义集成之间的双向通信

## 1. 目标与边界

建立一套可供 ESP32 固件和 HA 自定义集成共同遵循的通信契约，覆盖屏幕控制、Tivoo SPP 转发、设备状态、麦克风音频上行、TTS 音频下行、连接管理和异常恢复。

设计原则：

- 以现有 `esp32-divoom` 的 TCP → SPP 桥接协议和蓝牙实现为基础，优先移植/适配，禁止重复实现已有协议能力。
- HA 是设备业务入口和会话管理者；ESP32 是网络客户端的服务端对端、Tivoo 蓝牙控制器及音频外设控制器。
- 7777 控制通道与 7778 音频/设备事件通道分离，避免持续 PCM 流阻塞图片、动画和控制命令。
- TTS 使用 HA 提供的音频资源 URL；ESP32 通过 HTTP 分块下载、解码为 PCM 并播放，不由 HA 再额外推送一份 PCM。
- 本规格只面向用户现有的 Divoom Tivoo，不将其他 Divoom 型号的键盘灯、背光或 BLE 灯控能力移植进来。

不在本规格范围：AstrBot 内部对话协议、HA Assist Pipeline 的 STT/TTS 算法实现、麦克风/DAC 硬件电路选型、其他 Divoom 型号兼容、A2DP 主路线实现。

## 2. 已确认的设备事实

### 2.1 Tivoo 蓝牙通道

本工作区的 `BluetoothBridgeTest/tivoo/protocol-reference.md` 将设备身份区分为：

| 设备身份 | 类型 | 当前已知用途 |
|---|---|---|
| `Tivoo-light` | BLE | 设备发现/广播身份 |
| `Tivoo-audio` | Bluetooth Classic RFCOMM | 实际控制通道，当前记录的 RFCOMM 通道为 1 |

当前图形、文字、动画、亮度和已确认的内置功能命令均通过 Tivoo Classic SPP 控制。

**BLE GATT 灯光控制不属于本项目实现目标。** 现有本地协议记录没有给出适用于该 Tivoo 的 GATT 服务/特征 UUID、可写特征或灯控命令；现有 `esp32-divoom` 代码也没有实现 BLE GATT Client。仅观察到 `Tivoo-light` BLE 身份存在，不足以证明它提供可用的 GATT 灯控接口。

本次实测记录：Tivoo 通过 AUX 播放外部音频时，保持 `Tivoo-light` 蓝牙连接，仍可通过 SPP 发送指令并显示图形。此结果是 Tivoo 设备侧 AUX 与 SPP 并行工作的实测证据，不代表 ESP32 需要建立或维持 BLE GATT 连接。

屏幕上的纯色/光效模式（若实际固件支持）属于 16×16 显示矩阵模式，使用 SPP 的 `0x45 0x01` 命令；它不是独立背光硬件，也不是 BLE GATT 灯控。

### 2.2 音频路线

- 主路线：ESP32 I²S TX → 外部 I²S DAC → 模拟 AUX → Tivoo。
- 麦克风：INMP441 → ESP32 I²S RX。
- A2DP Source 仅作为 AUX 不可用时的备用路线，不属于本通信层首期必要功能。
- Tivoo AUX 播放与 SPP 图形控制的设备端并发已实测通过；ESP32 固件端 Wi-Fi、I²S RX/TX、SPP 同时运行的稳定性仍需实测。

## 3. 总体架构

### 3.1 连接关系

两个 TCP 长连接由 HA 主动连接 ESP32；此外，ESP32 在收到资源 URL 后主动作为 HTTP Client 请求 HA 的音频资源。ESP32 运行两个 TCP Server；每个通道均为全双工 TCP 字节流：

| 通道 | 默认端口 | HA 角色 | ESP32 角色 | 主要用途 |
|---|---:|---|---|---|
| Tivoo 控制桥 | 7777 | TCP Client | TCP Server | 复用 esp32-divoom 既有协议，SPP 连接/断开、屏幕命令、图片/动画、SPP 返回数据 |
| 设备与音频 | 7778 | TCP Client | TCP Server | 设备握手/状态、麦克风 PCM 上行、TTS 播放通知/停止、播放状态、错误与心跳 |
| 音频资源获取 | HA 配置的 HTTP(S) 地址 | HTTP Server | HTTP Client | ESP32 收到 URL 后 GET TTS/其他明确指定的音频资源，流式获取音频数据并解码 |

另有独立的 HTTP 资源通道，它是本通信层的必要组成部分，不取代两个 TCP 通道：

- HA 通过 TCP 7778 的 TTS_PLAY 将已经生成的资源 URL、MIME 类型、必要的访问凭据和 playback_id 通知 ESP32。
- ESP32 → HA HTTP Server：ESP32 使用 HTTP Client 对该 URL 发起 GET，流式下载实际 TTS 音频字节；解码后输出 PCM。
- 同一 HTTP Client 可获取 HA 明确提供的其他必要音频资源，例如预录提示音。资源必须由 HA 提供可访问 URL，不允许 ESP32 自行猜测 NAS 内部路径。
- 这里的 HTTP GET 获取的是音频资源内容，不是再次请求 URL 元数据；URL 元数据由 TCP 7778 传递。
- 图片、动画不经 HTTP 由 ESP32 下载；HA 在 NAS 上完成 Tivoo 图片协议编码后，通过 7777 发送最终二进制 Tivoo 帧。

ESP32 不开放 HTTP Server，也不直接连接 AstrBot、MCP Server、云端 LLM 或其他 NAS 容器。HA 是 ESP32 唯一的业务服务端。

### 3.2 数据流概览

```text
AstrBot / HA Automation / Assist Pipeline
                  |
                  v
        HA Tivoo Custom Integration
          |                    |
          | TCP Client         | TCP Client
          v                    v
     TCP 7777               TCP 7778
     Control                Audio / Events
          |                    |
          +--------- ESP32 ----+
                    |
        +-----------+------------+
        |           |            |
      SPP         I2S RX       I2S TX
        |           |            |
      Tivoo       Microphone    DAC → AUX
                                |
                              Tivoo

ESP32 HTTP Client ── GET 音频 URL ──> HA HTTP Resource（TTS / 预录提示音）
```

### 3.3 不采用的通信方式

- 不把每个 Tivoo 命令包装成单独 HTTP 请求。
- 不把 HA 原生 `/api/websocket` 当作 ESP32 音频协议。
- 不新增 MQTT Broker 作为本项目必需依赖。
- ESP32 不开放 HTTP Server；麦克风 PCM 上行走已建立的 7778 双向 TCP 连接，TTS/提示音资源则由 ESP32 HTTP Client 主动 GET HA 提供的 URL。
- 不使用 BLE GATT 作为 Tivoo 灯光/屏幕控制接口。

## 4. 通道 A：TCP 7777 Tivoo 控制桥

### 4.1 复用目标

以 `d03n3rfr1tz3/esp32-divoom` 为基准，复用其已有设计与协议行为：

- `TcpInput`：TCP Server、接收缓冲、数据队列及数据解析入口。
- `appendFrames()` / `getFrameSize()` / `isFramePending()`：从 TCP 字节流中组装完整 Tivoo 帧，处理 TCP 分段和粘连。
- `BluetoothSpp`：Classic Bluetooth 初始化、SPP 连接、发送队列、拥塞处理、发送完成事件、SDP RFCOMM 通道发现。
- `BluetoothHandler`：连接状态、断线重连、设备发现和 SPP 接收事件。
- `BluetoothOutput`：将收到的 Tivoo 原始二进制数据写入 SPP，并将设备返回数据转发回 TCP。

原仓库采用 Arduino/AsyncTCP 等平台层封装，而本项目固件基于 ESP-IDF。应复用协议逻辑和蓝牙实现思路，按 ESP-IDF 环境适配；不得为了复用而把整套 Arduino 网络运行时强行引入固件。

上游 TCP Server 默认端口为 7777，本项目保持该端口和线格式兼容。HA 端可参考 `hass-divoom` 的 `Divoom(host=...)` TCP 模式，不重新设计控制协议。

### 4.2 TCP 命令格式

该通道不是 JSON 协议，传输原始二进制字节。

**连接 SPP：**

```text
69 <MAC 的 6 个原始字节> [RFCOMM 通道]
```

- `0x69`：连接请求。
- MAC 是 6 个原始字节，不是 ASCII 十六进制字符串。
- 可选通道为一个字节；省略时按上游逻辑通过 SDP 查找通道。
- 若通道为 0，后续字节可作为查找失败时的 fallback channel。

**断开 SPP：**

```text
96 <MAC 的 6 个原始字节>
```

- `0x96`：断开请求。

**发送 Tivoo 原始协议帧：**

```text
01 <length_lo> <length_hi> <command + params> <checksum> 02
```

长度、校验和、转义规则沿用当前 Tivoo 协议编码实现。TCP 传输层不把十六进制文本当作数据；必须发送原始字节。

**ESP32 → HA 反向数据：**

沿用上游 TCP 桥接行为，将 SPP 返回数据转发到 HA TCP 连接。设备发现广播帧按现有格式保留：

```text
00 <MAC 的 6 个原始字节> <name_length> <UTF-8 name bytes>
```

实际项目固定使用已配置的 Tivoo 地址，不要求 AI 每次重新发现设备；设备发现事件可用于诊断和首次配网。

### 4.3 图形、图片与动画

- HA 负责把语义化服务参数转换成 Tivoo 二进制协议帧。
- HA 端复用工作区现有 `BluetoothBridgeTest/tivoo` 的图像与动画编码逻辑，包括图片缩放、RGB 调色板、像素索引打包、图像帧构建和外层包校验。
- `esp32-divoom` 的 TCP 输入层只负责识别/转发完整帧，不负责解码 PNG/JPG，不负责重新量化像素。
- 单帧图像按 Tivoo 的 `0x44` 命令格式发送；动画按 Tivoo `0x49` 分块协议发送，保持同一 SPP 会话并按顺序写入。
- HA 必须按序发送同一动画的所有分块；发送失败或连接断开时终止该动画，不继续发送后续残片。
- 沿用上游 TCP pacing 和 SPP 拥塞队列机制；首轮联调后再根据 Tivoo 实际显示稳定性调整 pacing，不另建复杂调度系统。

### 4.4 命令执行结果语义

必须区分三种状态：

1. `accepted`：ESP32 收到完整帧并接受进入发送队列。
2. `sent`：ESP32 的 SPP 驱动报告写入/发送完成。
3. `confirmed`：只有 Tivoo 协议确实提供可关联的设备响应时才可报告。多数屏幕写命令是 write-only，不能把 SPP 写入成功说成屏幕已显示成功。

HA 实体状态不得仅因 TCP 写入成功就假定设备画面已经改变。

## 5. 通道 B：TCP 7778 设备与音频协议

### 5.1 设计目的

该通道承载需要持续双向交互、但不属于 Tivoo 原始 SPP 帧的消息。采用一个长连接完成设备控制、状态反馈和音频上行；TTS 大文件本体仍由 ESP32 通过 HTTP GET 下载。

控制消息使用 UTF-8 JSON；PCM 数据使用二进制帧。两者共用同一 TCP 字节流，通过固定头部区分类型。

### 5.2 统一二进制封装

每条消息由 16 字节固定头部和 Payload 组成：

| 偏移 | 长度 | 字段 | 说明 |
|---:|---:|---|---|
| 0 | 4 | Magic | ASCII `TVIO` |
| 4 | 1 | Version | 当前为 `1` |
| 5 | 1 | Message Type | 消息类型枚举 |
| 6 | 2 | Flags | 小端；v1 暂保留为 0 |
| 8 | 4 | Payload Length | 小端无符号长度 |
| 12 | 4 | Sequence | 小端消息序号，按连接递增 |
| 16 | N | Payload | JSON UTF-8 或指定二进制格式 |

接收方必须按 Payload Length 组装完整消息，不得假定一次 `recv()` 恰好返回一条消息。允许 TCP 拆包和粘包。

初始资源限制：

- JSON 控制消息建议不超过 16 KiB。
- 单个 PCM Payload 建议控制在 4 KiB 以内。
- 超过限制的消息应返回错误并丢弃，不允许据声明长度无限分配内存。
- 7778 首期不传图片、动画和完整 TTS 文件，避免重复传输与内存占用。

### 5.3 消息类型

| Type | 名称 | 方向 | Payload |
|---:|---|---|---|
| `0x01` | HELLO | ESP32 → HA | JSON：设备 ID、固件版本、协议版本、能力列表 |
| `0x02` | HELLO_ACK | HA → ESP32 | JSON：接受状态、会话参数、心跳间隔 |
| `0x03` | PING | HA → ESP32 | 空或 JSON 时间戳 |
| `0x04` | PONG | ESP32 → HA | 空或 JSON 时间戳 |
| `0x10` | GET_STATUS | HA → ESP32 | JSON：可选状态查询范围 |
| `0x11` | DEVICE_STATUS | ESP32 → HA | JSON：当前设备和模块状态 |
| `0x20` | MIC_SESSION_START | ESP32 → HA | JSON：音频格式、会话 ID、预录长度 |
| `0x21` | MIC_PCM | ESP32 → HA | 二进制：PCM 音频帧 |
| `0x22` | MIC_SESSION_END | ESP32 → HA | JSON：会话 ID、结束原因 |
| `0x23` | MIC_CAPTURE_STOP | HA → ESP32 | JSON：停止当前采集/上传会话 |
| `0x30` | TTS_PLAY | HA → ESP32 | JSON：播放 ID、音频 URL、Token、MIME 类型 |
| `0x31` | TTS_STOP | HA → ESP32 | JSON：播放 ID、停止原因 |
| `0x32` | TTS_STATE | ESP32 → HA | JSON：下载、缓冲、播放、完成或失败状态 |
| `0x40` | DEVICE_EVENT | ESP32 → HA | JSON：状态变化事件 |
| `0x41` | ERROR | 双向 | JSON：错误代码、关联消息/会话 ID、简短说明 |

未知消息类型不得导致连接进程崩溃；记录协议错误并忽略该消息。协议版本不兼容时，HELLO_ACK 返回不支持原因并关闭连接。

### 5.4 握手与连接状态

1. ESP32 开机后启动 TCP 7777 与 7778 Server，并尝试连接 Wi-Fi。
2. HA 根据配置的 ESP32 地址分别建立两个 TCP Client 连接。
3. 7777 连接建立后，HA 按需发送 `0x69 + MAC + channel` 建立 SPP。
4. 7778 建立后，ESP32 发送 HELLO；HA 校验协议版本并回复 HELLO_ACK。
5. 完成握手后，双方可在 7778 双向发送消息。
6. HA 使用 PING/PONG 判断 7778 是否仍可用；控制与音频通道的连接状态分别维护。
7. 任一通道断开时，HA 单独重连该通道。7778 重连不得重置仍正常工作的 SPP 连接；7777 重连后按需恢复 SPP 连接。
8. ESP32 网络断开时，停止新的音频会话；正在播放的 TTS 按本地策略完成缓冲播放或停止，并上报可用的最终状态。

建议 HELLO Payload：

```json
{
  "device_id": "tivoo-esp32",
  "firmware_version": "0.1.0",
  "protocol_version": 1,
  "capabilities": [
    "spp_control",
    "mic_pcm_upload",
    "tts_url_playback",
    "i2s_dac_output"
  ]
}
```

建议 DEVICE_STATUS 至少包含：

- Wi-Fi 已连接状态及信号强度（能可靠取得时）。
- TCP 7777 / 7778 连接状态。
- Tivoo SPP 连接状态。
- 麦克风 I²S 与采集状态。
- 当前麦克风会话状态。
- TTS 下载/缓冲/播放状态。
- 音频欠载/溢出计数和可用内存（用于诊断，不要求高频上报）。

不要虚构电池电量、屏幕实际显示状态等没有可靠硬件/协议来源的数据。

## 6. 麦克风音频上行：ESP32 → HA

### 6.1 数据格式

首期格式固定为：

| 参数 | 值 |
|---|---|
| Sample Rate | 16000 Hz |
| Channels | 1 |
| Sample Format | signed 16-bit little-endian |
| Encoding | PCM S16LE |
| 典型帧长 | 20 ms |
| 每帧样本数 | 320 |
| 每帧 Payload | 640 bytes |

ESP32 根据 INMP441 实际采样格式完成通道选择、位宽和采样率适配后再发送。不得把 I²S DMA 原始缓冲未经转换就假定为 S16LE。

### 6.2 会话流程

1. ESP32 空闲时本地采集并运行 ESP-SR AFE VAD，不持续上传无关音频。
2. VAD 触发后发送 MIC_SESSION_START，包含唯一 session_id、音频格式和预录缓冲时长。
3. ESP32 先发送触发前预录音频，再持续发送 MIC_PCM。
4. HA 把 PCM Payload 放入当前会话的异步音频队列，并把队列迭代器交给 Tivoo Assist Satellite 的 `async_accept_pipeline_from_satellite()`。
5. Pipeline 活跃期间 ESP32 必须持续发送音频，包括静音 PCM 帧；本地 VAD 不得在说话间隙擅自结束已启动的 HA Pipeline 音频流。
6. HA Pipeline 正常结束、超时或取消后，HA 发送 MIC_CAPTURE_STOP；ESP32 停止本次上传并回到本地 VAD 空闲监听。
7. ESP32 在主动结束或设备异常时发送 MIC_SESSION_END；HA 关闭对应音频队列，使异步音频迭代器正常结束。

一个设备同一时间只允许一个活动麦克风会话。新会话不得静默覆盖旧会话；需先结束/取消旧会话。

### 6.3 流控与实时性

- 音频帧按 Sequence 顺序发送；接收方可发现丢帧或乱序。
- HA 处理速度低于输入速度时，应使用有界队列。达到上限时优先终止当前异常会话并记录错误，不能无限占用 NAS 内存。
- ESP32 侧使用环形缓冲和有界发送队列；网络发送不得阻塞 I²S DMA 读取。
- 不使用 Base64，不将 PCM 放进 JSON。
- 20 ms 为首期建议帧长；实际合帧/发送周期可在联调中优化，但不能引入明显的语音截断或延迟。

## 7. TTS 音频下行：HA → ESP32

### 7.1 控制通知与 HTTP 资源获取分离

HA 初始化 TTS ResultStream 时，`run-start` 事件会提供 `tts_output.url`、`token`、`mime_type`，并在可流式回馈时提供 `stream_response=true`。只有当 Conversation Agent 声明并实际输出增量文本、且 TTS Provider 支持流式文本输入时，该标记才为 true。

对于流式回答，HA 在 `intent-progress` 事件中发出 `tts_start_streaming=true`，表示 TTS 文本流已经启动。HA 集成使用此前保存的 URL/Token/MIME，通过 7778 向 ESP32 发送 TTS_PLAY；ESP32 随即 HTTP GET，能够在 AstrBot 仍生成后续文本时开始接收和播放音频。短回答或不支持流式的回退路径，则在 `tts-end` 事件后发送 TTS_PLAY。

`tts-end` 表示本轮 TTS 输入已提交/关闭，不表示音频已全部合成、下载或播放完成。HA TTS Proxy 会将 Provider 返回的音频数据生成器逐块写入 HTTP 响应；ESP32 仍按流式方式读取。最终播放完成以设备回报的 TTS_STATE 为准，再由 HA 调用 `tts_response_finished()` 结束 Satellite 播报生命周期。

TTS 文件本身不通过 TCP 7778 传输。

收到 TTS_PLAY 后，ESP32 使用 HTTP Client 向 HA 提供的 URL 发起 GET 请求，获取实际的音频响应体。HTTP 以流式方式提供编码音频数据，ESP32 边接收、边解码、边填充 PCM 播放缓冲区。HTTP 通道因此是本项目必要的第三个数据通路，而不是可有可无的实现细节。

资源通道的职责范围：

- 必须支持：HA TTS Pipeline 生成的音频资源。
- 可复用支持：HA 提供的其他必要音频资源，例如本地预录提示音或项目明确配置的音频片段。
- 不负责：图片和动画。此类资源由 HA 侧编码成 Tivoo 协议帧后，通过 TCP 7777/SPP 发送。
- 不负责：麦克风 PCM 上行。麦克风 PCM 使用 TCP 7778 的 MIC_PCM 二进制消息。

示例：

```json
{
  "playback_id": "tts-unique-id",
  "url": "http://ha-address:8123/api/tts_proxy/...",
  "mime_type": "audio/mpeg",
  "token": "short-lived-access-token"
}
```

字段说明：

- `playback_id`：用于关联播放、停止和结果消息。
- `url`：ESP32 可在局域网访问的完整 HA 音频 URL。
- `mime_type`：HA 实际返回的 MIME 类型，供 ESP32 选择解码器。
- `token`：仅在 URL 无法直接访问且 HTTP 请求确实需要时携带；使用短时凭据，不写入普通日志、不持久保存。

HA 必须提供 ESP32 可达的 LAN URL，不得把仅 NAS 容器内部可解析的 hostname 或不可达的容器地址发给 ESP32。

### 7.2 ESP32 播放流程

1. 收到 TTS_PLAY 后创建 playback_id 对应的播放任务；URL 元数据来自 7778，不再额外请求一次 URL。
2. 使用 ESP-IDF HTTP Client 向该 URL 发起 GET，按需附加 HA 提供的短时访问凭据。
3. HTTP 响应体是实际的编码音频字节；按流式方式接收，不要求先将完整音频下载到 RAM。
4. 对 HA 明确提供的其他必要音频资源，复用同一 HTTP Client 和下载入口；首期不增加独立资源发现协议或任意文件浏览接口。
5. 根据 MIME/实际编码选择解码器，将音频增量解码成 PCM。
6. 将 PCM 转换为 DAC/I²S 输出所需采样率、位宽和声道格式。
7. 写入有界播放缓冲，达到启动阈值后开始 I²S TX；下载和解码持续进行。
8. 正常播放结束后发送 TTS_STATE=completed。
9. HTTP、解码或 I²S 播放失败时发送 TTS_STATE=failed，并包含简短错误代码。
10. 收到匹配的 TTS_STOP 后取消当前 HTTP 请求、清空对应播放缓冲并停止/淡出 I²S 输出。

TTS 播放状态至少包括 `downloading`、`buffering`、`playing`、`completed`、`stopped`、`failed`。HA 收到最终状态后完成 Satellite 的播报生命周期，包括调用 `tts_response_finished()`。

### 7.3 格式与资源边界

- 以 HA 实际下发的 MIME 类型为准，不能把所有 URL 假定为 WAV 或 MP3。HA Core 2026.11.0 的 Wyoming TTS 流式适配会先发送一个 `nframes=0` 的 WAV 流头，再逐块发送 PCM；这是未知总长度的流式 WAV，不是已完成封装、长度已知的普通 WAV 文件。ESP32 必须验证解码器能在 HTTP 响应未结束时持续读取该格式，不能依赖 RIFF/data 长度提前确定整个文件大小。
- sherpa-onnx Matcha Baker 当前输出为 22.05 kHz 单声道；Wyoming `AudioStart` 应报告模型实际采样率/声道/位宽，HA 返回的 MIME/采样规格仍以实测响应为准。若设置了 HA 音频输出转码，ESP32 按最终资源的实际格式解码。
- ESP32 首期只实现实际测试确认所需的解码格式；若 HA 默认 TTS 格式超出固件解码能力，应在 HA 侧提供兼容格式/转码，而不是在 ESP32 堆叠大量不使用的解码器。
- 下载数据、解码输入、PCM 播放缓冲均使用有界内存。
- 播放欠载必须计数并上报；不得让网络下载任务直接阻塞 I²S TX。
- AUX 为首选输出；A2DP 不与同一段 AUX 音频并行播放。

## 8. HA 集成职责

HA 自定义集成是所有上层功能的唯一入口：

- 管理 ESP32 host、端口、TCP Client 连接及重连。
- 管理 7777 Tivoo 控制桥，并把 HA 服务调用编码成 Tivoo 二进制帧。
- 复用现有 Python Tivoo 协议/图片编码能力，不在 ESP32 重复图片编码。
- 管理 7778 握手、消息解析、音频队列和状态更新。
- 将 MIC_PCM 流交给 Assist Satellite Pipeline。
- 监听 Pipeline 事件：在 `run-start` 保存 TTS URL、Token、MIME 和 `stream_response`；流式路径在 `intent-progress` 的 `tts_start_streaming=true` 时发送 TTS_PLAY，短回答/非流式路径在 `tts-end` 时发送 TTS_PLAY。
- 确保下发 URL 是 ESP32 可直接访问的 HA LAN 地址，并在需要时提供短时 HTTP 访问凭据。
- 复用 HA TTS Proxy 等现有音频资源服务；其他必要音频资源也通过明确的 HTTP URL 提供，不在首期另造资源发现 API。
- 接收 TTS_STATE，结束或更新 Satellite 播报状态。
- 向 HA 暴露屏幕控制服务、Assist Satellite、SPP 状态和麦克风/播放诊断实体。
- 为 AstrBot MCP 工具提供稳定的业务服务接口；AstrBot 不直接连接 ESP32。

HA 服务参数使用语义化数据，例如亮度值、图片路径、文字内容；由 HA 端的 Tivoo 编码层生成最终 SPP 字节。

## 9. ESP32 固件职责

固件以 ESP-IDF 为基础，按模块划分：

- **network_control**：TCP 7777 Server，兼容上游 raw Tivoo bridge 协议。
- **network_audio**：TCP 7778 Server、消息封装解析、HELLO/心跳、状态事件及音频消息。
- **tivoo_spp**：复用/适配 esp32-divoom 的 Classic Bluetooth SPP、SDP channel discovery、发送队列和连接管理。
- **audio_capture**：I²S RX、DMA、PCM 格式转换、VAD 输入和预录环形缓冲。
- **audio_playback**：HTTP Client、音频解码、PCM 转换、播放缓冲和 I²S TX。
- **device_state**：聚合 Wi-Fi、TCP、SPP、麦克风和播放状态。

职责边界：

- ESP32 收到 7777 的完整 Tivoo 原始帧后，直接进入 SPP 发送队列；不解析图片文件、不生成调色板、不理解上层 AI 语义。
- ESP32 收到 7778 的播放通知后负责 HTTP 获取、解码和输出；不请求 AstrBot，也不运行 TTS 模型。
- ESP32 不实现 BLE GATT 灯控，不维护键盘/背光控制任务。
- ESP32 的任何长耗时任务都不得阻塞 I²S DMA 和 SPP 发送队列。

## 10. 连接与错误处理

### 10.1 连接策略

- HA 是两个 TCP 通道的主动连接方。
- 7777、7778 分别报告连接状态，分别重连。
- TCP 断开后不得假报 SPP 断开；SPP 是独立状态。
- SPP 断开时由 ESP32 蓝牙模块进行有限重连；超过重试次数后报告不可用，等待 HA 请求或既有重连策略恢复。
- 重新建立 7777 后，HA 检查/恢复 SPP 连接，再发送屏幕任务。
- 重新建立 7778 后重新握手；已断开的麦克风会话不自动续传；未完成的 TTS 根据 playback_id 和设备实际状态由 HA 决定重发或取消。

### 10.2 错误代码建议

| Code | 含义 |
|---|---|
| `not_connected` | Tivoo SPP 未连接 |
| `spp_write_failed` | SPP 写入失败/发送队列拒绝 |
| `unsupported_protocol_version` | 7778 版本不兼容 |
| `invalid_frame` | TCP 控制帧格式错误 |
| `queue_full` | 有界队列已满 |
| `mic_unavailable` | I²S 麦克风不可用 |
| `audio_http_failed` | TTS HTTP 下载失败 |
| `audio_decode_failed` | TTS 音频解码失败 |
| `audio_buffer_underrun` | 播放缓冲欠载 |
| `i2s_output_failed` | I²S/DAC 输出失败 |
| `operation_cancelled` | 操作被取消 |

错误消息应包含关联的 command/message/playback/session ID（可用时）和简短描述；避免记录认证 Token 或完整带凭据 URL。

### 10.3 局域网与认证边界

- 两个 TCP 端口只在可信 LAN 内开放，不配置公网端口映射。
- 7777 为兼容上游的原始桥接协议，本身没有新增握手认证；由网络隔离和 HA/ESP32 固定地址配置限制访问。
- 7778 至少校验协议版本和设备 ID；若部署网络并非可信 LAN，再增加轻量共享密钥握手，不在首期引入复杂 PKI。
- Token 仅用于 TTS HTTP 请求，按短时凭据处理，不保存在 NVS 或日志中。

## 11. 复用清单与许可证

### 11.1 必须优先复用

| 来源 | 已有能力 | 本项目使用方式 |
|---|---|---|
| `BluetoothBridgeTest/esp32-divoom/components/divoom/input_tcp.cpp` | TCP 7777 接入、命令识别、反向数据发送 | 保留协议兼容，按 ESP-IDF 适配网络层 |
| `esp32-divoom/components/divoom/util.cpp` | Tivoo 帧拆分/组装、TCP 拆包与粘包处理 | 优先复用 `appendFrames` 和帧长度校验 |
| `esp32-divoom/components/divoom/bluetooth_spp.cpp` | SPP 连接、SDP、发送队列、拥塞处理 | 作为 ESP-IDF SPP 模块主要实现参考 |
| `esp32-divoom/components/divoom/hardware_bluetoothctl.cpp` | 设备发现、连接/重连和 SPP 事件回调 | 复用状态机和回调职责 |
| `esp32-divoom/components/divoom/output_bluetooth.cpp` | 原始数据向 SPP 转发 | 沿用简单转发边界 |
| `BluetoothBridgeTest/tivoo/tivoo.py` | 图片缩放、像素编码、帧构建、外层校验 | HA 侧复用，不在 ESP32 重写 |
| `BluetoothBridgeTest/tivoo/commands.py` | 常见 Tivoo 命令 Payload Builder | HA 端按需复用/移植 |
| `d03n3rfr1tz3/hass-divoom` | HA 连接 ESP32 TCP 7777 的既有方式及 Tivoo 服务组织 | 参考 TCP client 和 HA 服务组织，不照搬旧实体/通知架构 |

### 11.2 许可证

`esp32-divoom` 和 `hass-divoom` 当前公开仓库标注 MIT License。复用代码时保留原版权和许可证声明，记录来源；不得直接复制文件后删除版权头。实现前检查工作区实际版本与许可证文件。

### 11.3 禁止重复造轮子

- 不新写一套 Tivoo SPP 包格式或校验算法。
- 不在 ESP32 实现 PNG/JPG/GIF 图片量化和调色板编码。
- 不新建与 `appendFrames` 功能重复的 TCP 帧解析器，除非 ESP-IDF 适配测试证明现有实现不适用。
- 不重写 SPP 发送拥塞队列、SDP 通道发现等已有能力。
- 新增代码限于 ESP-IDF 适配、7778 消息协议、音频采集/播放及 HA Assist Satellite 对接。

## 12. 验收标准

### 12.1 控制桥

- HA 可通过 TCP 7777 连接 ESP32，并控制 Tivoo SPP 连接/断开。
- 亮度命令可从 HA 传到屏幕；命令字节与现有 Tivoo golden/protocol 测试一致。
- HA 可发送单帧图片和多帧动画；屏幕显示正确，动画分块顺序正确。
- TCP 故意拆包、粘包时，ESP32 仍只向 SPP 转发完整 Tivoo 帧。
- SPP 收到的返回数据可通过同一 TCP 连接回到 HA。
- SPP 写入成功与设备实际显示确认在 HA 状态中明确区分。

### 12.2 设备/音频通道

- HA 与 ESP32 可在 TCP 7778 完成 HELLO/HELLO_ACK。
- 心跳能检测断线，7778 重连不破坏仍正常工作的 7777/SPP。
- ESP32 能上送预录 PCM 和实时 16 kHz S16LE mono PCM；HA 可将流交给 Assist Satellite Pipeline。
- Pipeline 活跃时静音帧仍持续上送；结束后音频迭代器能正常结束。
- HA 下发 TTS_PLAY 后，ESP32 能使用 URL/认证信息分块下载并播放；能响应 TTS_STOP。测试流式 WAV（`nframes=0`）时，必须在 HTTP EOF 前持续解码和播放，并验证不能因 RIFF 声明长度未知而等待完整文件。
- TTS 完成、停止和失败均能反馈到 HA，Satellite 能结束播报生命周期。
- 音频传输期间 SPP 屏幕命令仍可正常执行；I²S 不出现不可接受的 DMA 阻塞/欠载。

### 12.3 设备端最终联调

- AUX 播放与 SPP 图形控制并行运行。
- ESP32 同时运行 Wi-Fi、I²S RX、I²S TX 和 SPP 时，语音上行、TTS 播放及屏幕控制均可持续工作。
- 不要求 BLE GATT 连接或灯控测试通过。

## 13. 测试策略

优先使用现有测试，不为已有逻辑重复建立平行测试框架：

1. **协议 Golden 测试**：沿用 `esp32-divoom/test/goldens` 思路和本地 Tivoo 协议测试，检查命令/图像编码字节不发生意外变化。
2. **TCP 帧测试**：复用 `util.cpp` 的拆包/粘包用例，补充 ESP-IDF TCP 收包边界测试。
3. **7778 协议测试**：测试头部编码、长度边界、未知类型、错误版本、粘包/拆包和 Sequence。
4. **HA 集成测试**：使用模拟 ESP32 TCP Server 验证连接、服务下发、音频队列接收、TTS 事件通知和断线恢复；额外验证 AstrBot ChatLog 增量、`stream_response=true`、`tts_start_streaming` 触发提前下载，以及短回答通过 `tts-end` 回退通知。Wyoming TTS 服务测试还需覆盖 `SynthesizeStart/Chunk/Stop`、HA 兼容性完整 `Synthesize` 不会导致重复合成，以及服务以 `SynthesizeStopped` 正常结束音频流。
5. **音频联调**：先用本地 PCM 文件测试网络→解码→I²S，再接入 Assist Pipeline 的实时麦克风与 TTS 生命周期。
6. **实机验收**：最后在 Tivoo AUX 播放时持续发送 SPP 图片/动画，并同时运行麦克风采集与 TTS 播放。

## 14. 设计约束与待实现时确认项

以下是实现阶段必须通过测试确认的参数，不阻止本规格作为通信契约使用：

- 当前 ESP-IDF 版本与 `esp32-divoom` SPP 代码适配所需的最小改动。
- HA TTS 实际返回的 MIME/编码集合，以及 ESP32 首期必须支持的解码器。
- DAC 最终采样率、声道与 I²S 时钟配置。
- 7778 音频队列长度和播放预缓冲阈值，按实际 Wi-Fi 抖动与音频延迟调整。
- ESP32 固件的设备 ID 和 7778 协议版本升级策略。

这些参数应通过实际 HA/Tivoo 联调确定，不提前加入复杂抽象或多套备用协议。

## 15. 参考资料

- [esp32-divoom](https://github.com/d03n3rfr1tz3/esp32-divoom) — ESP32 Classic SPP/TCP 桥接实现。
- [hass-divoom](https://github.com/d03n3rfr1tz3/hass-divoom) — HA 侧 TCP 控制与 Tivoo 协议实现参考。
- [Bluetooth SPP protocol reference in this workspace](../../../BluetoothBridgeTest/tivoo/protocol-reference.md) — 本机实测与协议记录。
- [Tivoo Python protocol implementation in this workspace](../../../BluetoothBridgeTest/tivoo/tivoo.py) — 图片/动画编码参考。
- [Home Assistant Assist Satellite Entity](https://developers.home-assistant.io/docs/core/entity/assist-satellite/) — HA 卫星实体接口。
- [Home Assistant Assist Pipeline](https://developers.home-assistant.io/docs/voice/pipelines) — 音频会话生命周期与流式响应事件。
- [Home Assistant Wyoming Protocol](https://www.home-assistant.io/integrations/wyoming/) — STT/TTS 外部服务接入。
- [Sherpa ONNX TTS/STT Wyoming 实现](https://github.com/ptbsare/sherpa-onnx-tts-stt) — 可复用的 Paraformer/Matcha 基础实现（当前 TTS 尚不支持流式文本输入）。
- [ESP-IDF Bluetooth API](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-guides/bluetooth.html) — Classic Bluetooth/SPP。
- [ESP-IDF HTTP Client](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/protocols/esp_http_client.html) — TTS 资源下载。
- [ESP-IDF I²S API](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/i2s.html) — PCM 采集与 DAC 输出。
