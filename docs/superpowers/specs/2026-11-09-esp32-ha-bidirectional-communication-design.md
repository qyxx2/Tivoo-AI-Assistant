# ESP32 ↔ Home Assistant 双向通信层规格书

> 状态：设计规格，待用户审阅  
> 日期：2026-11-09  
> 最近修订：2026-11-11（P5 最小网络/日志边界；单 I²S、AEC 与全局音频打断基线）
>
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
- **阶段边界：** P5 先实现 Wi-Fi、最小 7777 SPP 控制通路和 7778 诊断日志子集；P6 再完成双向控制、完整设备/音频消息及 HTTP 音频资源。P5 使用最终协议的子集，不另建临时端口或第二套日志协议，也不代表 P6 完成。

不在本规格范围：AstrBot 内部对话协议、HA Assist Pipeline 的 STT/TTS 算法实现、ESP32 GPIO 最终分配及供电/模拟线路电路细节、其他 Divoom 型号兼容、A2DP 主路线实现。麦克风与 DAC 模块及其数字音频接口基线见 §2.2–§2.3。

## 2. 已确认的设备事实

### 2.1 Tivoo 蓝牙通道

本工作区的 `BluetoothBridgeTest/tivoo/protocol-reference.md` 将设备身份区分为：

| 设备身份 | 类型 | 当前已知用途 |
|---|---|---|
| `Tivoo-light` | BLE | 设备广播身份；不是本项目的屏幕控制地址 |
| `Tivoo-audio` | Bluetooth Classic RFCOMM | 实际控制通道，当前记录的 RFCOMM 通道为 1 |

当前图形、文字、动画、亮度和已确认的内置功能命令均通过 Tivoo Classic SPP 控制。用户使用手机蓝牙扫描并人工确认 `Tivoo-audio` 的 Classic MAC，再将其填写到 HA Tivoo 集成的 `tivoo_bluetooth_mac` Config Entry 字段。该字段是整个系统唯一的 Tivoo SPP 目标地址来源；不得使用 `Tivoo-light` 的 BLE 地址。更换 Tivoo 时只修改 HA 该字段并重新加载集成，不修改或重刷 ESP32 固件。HA 不扫描/自动选择设备，ESP32 也不执行 Classic peer inquiry 或 BLE scan。

**BLE GATT 灯光控制不属于本项目实现目标。** 现有本地协议记录没有给出适用于该 Tivoo 的 GATT 服务/特征 UUID、可写特征或灯控命令；现有 `esp32-divoom` 代码也没有实现 BLE GATT Client。仅观察到 `Tivoo-light` BLE 身份存在，不足以证明它提供可用的 GATT 灯控接口。

本次实测记录：Tivoo 通过 AUX 播放外部音频时，保持 `Tivoo-light` 蓝牙连接，仍可通过 SPP 发送指令并显示图形。此结果是 Tivoo 设备侧 AUX 与 SPP 并行工作的实测证据，不代表 ESP32 需要建立或维持 BLE GATT 连接。

屏幕上的纯色/光效模式（若实际固件支持）属于 16×16 显示矩阵模式，使用 SPP 的 `0x45 0x01` 命令；它不是独立背光硬件，也不是 BLE GATT 灯控。

### 2.2 音频路线

- 麦克风模块：INMP441，I²S 数字输出。
- 主播放模块：PCM5102 I²S DAC，模拟线路输出接 Tivoo AUX。
- INMP441 RX 与 PCM5102 TX 使用 ESP32-WROVER-E 的**同一个 I²S 控制器标准模式全双工**，共享 BCLK/WS；不再按两个独立 I²S 控制器设计。
- ESP32 本地 I²S 总线采用 32 kHz、双声道、每 Slot 32 bit 的统一时钟基线。麦克风上行和 TTS 下行分别在 ESP32 内转换为该总线格式；这不改变 HA/Wyoming 或 TCP 7778 的音频合同。
- A2DP Source 仅作为 AUX 不可用时的备用路线，不属于本通信层首期必要功能。
- Tivoo AUX 播放与 SPP 图形控制的设备端并发已实测通过；ESP32 固件端 Wi-Fi、全双工 I²S RX/TX、SPP 同时运行的稳定性仍需实测。

### 2.3 单 I²S 全双工时钟与音频格式分层

本项目选定以下硬件基线，用于后续 ESP32 固件设计和联调：

| 项目 | 设计基线 |
|---|---|
| I²S Controller | 同一个 ESP32 I²S Controller，同时注册 RX 与 TX |
| I²S 模式 | Standard / Philips I²S |
| 时钟主从 | ESP32 为 Master，INMP441 与 PCM5102 为 Slave |
| I²S 采样率 / WS | 32,000 Hz |
| Slot 模式 | Stereo，两个 Slot |
| 每 Slot 位宽 | 32 bit |
| BCLK | 2.048 MHz（32,000 × 32 × 2）|
| MCLK | 首选不连接；PCM5102A 使用 BCK PLL 产生内部系统时钟 |
| RX | INMP441，取左 Slot 有效 24-bit signed PCM |
| TX | PCM5102，向左右 Slot 写入相同的单声道 PCM 样本 |

**全双工配置约束：**

- ESP-IDF 同一 I²S Controller 的 TX/RX 共享 BCLK 和 WS。两侧必须配置相同的采样率、Slot 数量、Slot 位宽和帧时序；不得将 RX 配成 16 kHz、TX 配成 22.05 kHz。
- 两个方向分别使用 TX/RX channel handle、DMA 缓冲和读写任务。共享时钟不代表 RX 与 TX 的 DMA 读写同步；ESP-IDF 驱动不保证两侧读写调用逐样本同步。
- 初始化时应按 ESP-IDF 对应版本的全双工 API 一次分配同一 Controller 的 TX/RX channel，再分别初始化为完全匹配的 Standard 配置。不要再为麦克风和 DAC 分配两个 Controller。
- INMP441 输出为 24-bit two's-complement I²S 数据，每个 WS stereo frame 为 64 个 SCK 周期（每 Slot 32 周期）；L/R 选择左声道。RX 侧按实际 DMA 字节布局提取有效 24 bit、正确符号扩展/缩放，不能未经验证就把 32-bit DMA word 强转为 16-bit PCM。
- INMP441 的未驱动时段为高阻。单麦克风接法按数据手册在 SD 数据线上配置约 100 kΩ 下拉，并核对模块板是否已带该电阻。
- PCM5102 TX 采用双 Slot 写入，左右声道放置相同样本。16-bit 或 24-bit 解码样本需按 32-bit TX Slot 的数据对齐要求扩展/放置；具体有效位对齐以所用 PCM5102 模块和 ESP-IDF I²S 配置的实测波形为准。
- PCM5102A 的 BCK PLL 允许以 BCK/WS/DIN 三线方式工作，故本设计不要求 ESP32 输出 MCLK；若实际模块板带有不同的时钟/跳线设计，应按模块原理图确认，不假设所有商品板引脚完全一致。

**音频格式边界（不得混为同一个采样率）：**

| 处理层 | 上行麦克风 | 下行 TTS |
|---|---|---|
| 物理 I²S 总线 | 32 kHz / Stereo / 32-bit Slot | 32 kHz / Stereo / 32-bit Slot |
| 模块/服务源格式 | INMP441：24-bit I²S 数据 | Sherpa Matcha：22,050 Hz / Mono / S16LE PCM（Wyoming 到 HA） |
| ESP32 内部处理 | 左 Slot 提取/低通/32→16 kHz 得 M；最终输出 PCM 32→16 kHz 得 R；AFE AEC 输出增强 S16LE Mono | HTTP 解码 → 按解码器实际输出采样率重采样至 32 kHz → 全局输出管理器 → I²S TX；TX PCM 同时生成 AEC R 参考 |
| ESP32 ↔ HA 边界 | TCP 7778：16 kHz / Mono / S16LE PCM | TCP 7778 只发送 TTS_PLAY URL/Token/MIME；HTTP GET 获取编码音频资源 |
| HA / P7A 边界 | Assist Satellite / KWS / STT：16 kHz / Mono / S16LE | Sherpa Wyoming TTS：22,050 Hz / Mono / S16LE PCM；HA TTS Proxy 再封装/编码为 HTTP 音频资源 |

因此，32 kHz 只规定 ESP32 的本地 I²S 硬件时钟，不向 HA 上传 32 kHz 音频，也不要求 P7A 修改 16 kHz STT/KWS 输入或 22.05 kHz TTS Provider 输出。

**ESP32 侧转换职责：**

- 上行：32 kHz I²S RX 原始 Slot → 提取 INMP441 左声道有效 24-bit 样本 → 符号/位深转换、低通抗混叠和 2:1 降采样至 16 kHz，作为 AEC 麦克风 M 通道；最终输出 PCM 另路转换为 16 kHz 播放参考 R 通道。两路经 ESP-SR AFE AEC 后得到增强 S16LE Mono；此输出才供 VAD、预录环形缓冲和 TCP 7778 上传，避免 VAD 与网络上传使用不同音频流。
- 上行降采样不得简单丢弃每隔一个样本；必须先做适当的低通抗混叠处理。INMP441 24-bit 到 S16LE 的截位/舍入、增益和饱和处理须避免削波，并通过已知信号验证 DMA 数据位对齐。
- 下行：HTTP 接收编码数据 → 流式解码为 PCM → 读取解码器输出的真实采样率/声道 → 重采样到 32 kHz → 单声道复制到左右 Slot → 对齐为 32-bit I²S TX 数据。22,050 Hz 到 32,000 Hz 是非整数比例重采样，使用有状态 SRC，跨解码块保留滤波器状态，不可逐块独立重置或简单重复采样。
- 格式解码、SRC、AFE、网络写入和 I²S DMA 使用独立任务/有界缓冲；网络或模型处理不得直接阻塞 I²S DMA。
- 优先评估 Espressif esp_audio_codec 的流式 Simple Decoder 和 esp_audio_effects 的 Sample Rate / Bit Depth / Channel Conversion，复用成熟组件，不自行重写 MP3 解码或通用 SRC。选定 ESP-IDF 与组件版本后，必须验证目标 ESP32、MP3 22.05 kHz Mono 和 22.05→32 kHz 组合的实际支持及 CPU/RAM 占用。

### 2.4 AEC 回声消除与全局播放打断（首期必要能力）

AEC（Acoustic Echo Cancellation）和播放打断属于首期语音交互的必要能力，不是后续可选增强项。首期硬件继续使用 **ESP32-WROVER-E + INMP441 + PCM5102**，不增加 ESP32-S3；只有在 WROVER-E 实机验收证明处理能力或 AEC 效果无法满足体验要求时，才重新评估硬件。

**WROVER-E 的 AEC 能力边界：**

- WROVER-E 使用经典 ESP32。首版使用 Espressif `esp-sr` 经典 `esp32` target 的 AFE AEC，输入为 16 kHz signed 16-bit PCM，包含麦克风 M 通道与播放参考 R 通道；AEC 输出增强后的单声道音频。
- 经典 ESP32 target 的配置头文件将 AEC mode 标为 `AEC_MODE_SR_LOW_COST` / `AEC_MODE_SR_HIGH_PERF`；当前经典 ESP32 参考实现明确不支持 `SR_LOW_COST` 分支，因此首版设置 `aec_init=true`、`aec_mode=AEC_MODE_SR_HIGH_PERF`，以 **SR 高性能模式**作为基线。AFE 首版使用 `AFE_TYPE_SR`，输入格式 `MR`；VAD 启用且 `vad_mute_playback=false`。不得把 ESP32-S3 的 `AEC_MODE_FD_*`、非线性 NLP 或其资源表现当作 WROVER-E 已支持的能力。
- AFE 输入通道用 `M` 表示麦克风、`R` 表示播放参考，参考通道按当前 AFE 输入格式放在最后；输入帧长通过所选 ESP-SR 版本的接口获取，不在通信合同中硬编码。16 kHz、int16 对齐和交错排列必须用已知信号验证。
- 经典 ESP32 首版 AEC 以 SR 线性回声抵消为能力边界，不能保证消除扬声器失真引起的非线性残余回声，也不能消除与本机播放参考无关的电视、环境声或其他声源。单麦克风没有阵列波束形成能力；最终抑制程度必须用 Tivoo 实际扬声器音量、麦克风位置和房间环境验收。
- AFE 的 VAD 必须保持播放期间可用（配置 `vad_mute_playback=false`），并且只以 AEC 后的近端语音结果决定 barge-in；不得为了避免扬声器自触发而在播放期间关闭 VAD。回声抑制由 AEC 参考通道承担，误触发通过实机阈值调校验收。

**AEC 双路信号合同：**

1. 麦克风路：I²S RX 32 kHz → 提取 INMP441 左 Slot 有效 24-bit → 符号/位深转换、低通抗混叠 → 16 kHz S16LE Mono。
2. 播放参考路：从 `audio_output_manager` 的最终输出 PCM 取得参考，即在音量/混音等最终处理之后、送入当前实际输出后端之前取样；按 32 kHz → 16 kHz 转换为 S16LE Mono。不得使用 HTTP 编码数据、TTS 原始 PCM 或尚未经过最终音量处理的上游 PCM 代替实际播放参考。
3. 将麦克风与播放参考按 AFE 要求交错排列为 M/R 输入帧，送入 ESP-SR AFE AEC。没有本机播放时，R 通道提供相同时间轴上的静音样本。
4. AFE 输出的 16 kHz 增强单声道 PCM 是唯一的后处理麦克风流，统一供本地 VAD、预录环形缓冲、HA/KWS 输入和 TCP 7778 `MIC_PCM` 上传使用。禁止 VAD 使用未经 AEC 的原始麦克风流、而网络上传另一份处理结果。
5. 播放参考必须与麦克风采集帧在时间上对齐。实现需考虑 I²S TX DMA、输出队列和物理播放路径造成的固定延迟，用有界参考环形缓冲/帧队列补偿；不可假设 I²S RX/TX DMA 逐样本同步。参考帧欠载、错位或丢帧需计数并可诊断。停止播放后继续保留必要的参考尾帧以覆盖房间残余回声，不因一次打断就重置 AEC 自适应状态。
6. AEC、VAD、采集和网络上传不能阻塞 I²S DMA。AEC 所需 CPU、PSRAM/内部 RAM、帧处理时延及与 Wi-Fi/SPP 并发时的余量必须在 WROVER-E 实机测量。

**全局音频输出与打断合同：**

- ESP32 所有由本固件控制的声音输出统一经过 `audio_output_manager` 和当前选定的输出后端。首期至少包括 TTS HTTP 播放；后续提示音、通知音和其他本地/远端音频也必须接入同一管理层，不得各自直接写 I²S TX。
- 打断作用于**最终音频输出层**，不绑定 TTS 解码器或 TTS 输入任务。全局停止必须终止当前输出源及待播队列，取消相关 HTTP/解码/生成消费任务，清空 PCM 与后端待播缓冲，并在当前后端立即停止输出；不能只取消 TTS 文本输入或 HTTP 下载后仍让缓存音频继续播放。
- 用户在播放期间讲话时，ESP32 持续运行 I²S RX、AEC 和本地 VAD。VAD 只对 AEC 后的近端语音输出做判断；满足持续语音条件后，本地先调用全局输出停止，再向 HA 上报 `AUDIO_INTERRUPTED`。打断判断不要求用户先说唤醒词；该次新语音会话以 `PipelineStage.STT` 进入 HA。普通空闲 VAD 触发仍从 `PipelineStage.WAKE_WORD` 开始；VAD 持续时长/阈值通过实测确定。
- 打断后继续采集麦克风，不停止 RX/AEC；保留触发前预录缓冲和后续语音，形成 `trigger_source=barge_in` 的新 MIC 会话。`AUDIO_INTERRUPTED` 必须先于对应 `MIC_SESSION_START` 在 7778 上发送；HA 可在清理旧 Pipeline 的同时将新 PCM 暂存入有界队列。
- `MIC_CAPTURE_STOP` 只结束指定的网络上传会话，不代表关闭物理 I²S RX、AEC 或本地 VAD。物理采集在空闲监听和播放打断检测期间保持运行；只有设备级音频关闭/故障策略才允许停止硬件采集。
- 首期主输出是 I²S TX → PCM5102 → AUX，AEC 参考由该 TX 最终 PCM 取得。若未来切换到 A2DP 备用输出，必须为 A2DP 后端单独验证参考信号时序、编码/传输延迟与打断停止行为，不能直接假定 I²S 路径的 AEC 对 A2DP 同样有效。

## 3. 总体架构

### 3.1 连接关系

两个 TCP 长连接由 HA 主动连接 ESP32；此外，ESP32 在收到资源 URL 后主动作为 HTTP Client 请求 HA 的音频资源。ESP32 运行两个 TCP Server；每个通道均为全双工 TCP 字节流：

| 通道 | 默认端口 | HA 角色 | ESP32 角色 | 主要用途 |
|---|---:|---|---|---|
| Tivoo 控制桥 | 7777 | TCP Client | TCP Server | 复用 esp32-divoom 既有协议；P5 先实现 HA→ESP32→SPP 的单向命令子集，P6 补齐 SPP 返回数据及完整连接/结果处理 |
| 设备与音频 | 7778 | TCP Client | TCP Server | P5 先实现最终消息封装、HELLO/ACK 和诊断日志/错误；P6 补齐设备状态、音频上行/下行、事件与心跳 |
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
        +-----------+-------------------------------+
        |           |                               |
      SPP       I2S RX (32k)                    I2S TX (32k)
        |           |                               |
      Tivoo     INMP441                   PCM5102 → AUX → Tivoo
                   |                               |
             Mic 32k→16k M               最终 TX PCM 32k→16k R
                   \                             /
                    +── ESP-SR AFE AEC (M/R) ─────+
                                |
                       AEC 后 16k Mono
                         VAD / 缓冲 / MIC_PCM

        I²S RX/TX 共用同一 I²S Controller 与 BCLK/WS

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
- `BluetoothHandler`：连接状态、按上层明确给定的远端 MAC 执行连接/断线重连，以及 SPP 事件回调；不移植其 Classic peer inquiry 自动发现流程。
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

实际项目只使用 HA Config Entry 中由用户确认的 `tivoo_bluetooth_mac`。上面的 `0x00` 发现帧格式仅保留为上游协议兼容记录；本项目不通过 ESP32 设备扫描产生/消费首次配网选择，也不允许该帧自动修改 HA Config Entry。手机扫描和人工录入是唯一设备确认流程。

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
| 12 | 4 | Sequence | 小端消息序号；每个发送方向独立计数，每条 TCP 连接从 0 开始递增 |
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
| `0x02` | HELLO_ACK | HA → ESP32 | JSON：接受/拒绝状态；P5 只要求 `accepted`，P6 再加入会话参数和心跳间隔 |
| `0x03` | PING | HA → ESP32 | 空或 JSON 时间戳 |
| `0x04` | PONG | ESP32 → HA | 空或 JSON 时间戳 |
| `0x10` | GET_STATUS | HA → ESP32 | JSON：可选状态查询范围 |
| `0x11` | DEVICE_STATUS | ESP32 → HA | JSON：当前设备和模块状态 |
| `0x20` | MIC_SESSION_START | ESP32 → HA | JSON：音频格式、会话 ID、预录长度、`trigger_source`（`idle_vad` / `barge_in`）及可选 `interrupt_id` |
| `0x21` | MIC_PCM | ESP32 → HA | 二进制：AEC 后的 16 kHz S16LE Mono PCM 音频帧 |
| `0x22` | MIC_SESSION_END | ESP32 → HA | JSON：会话 ID、结束原因 |
| `0x23` | MIC_CAPTURE_STOP | HA → ESP32 | JSON：停止指定的网络上传会话；不停止物理 I²S RX/AEC/本地 VAD |
| `0x30` | TTS_PLAY | HA → ESP32 | JSON：播放 ID、音频 URL、Token、MIME 类型 |
| `0x31` | AUDIO_STOP | HA → ESP32 | JSON：请求 ID、全局停止范围、原因、可选预期活动音频 ID |
| `0x32` | AUDIO_STATE | ESP32 → HA | JSON：音频 ID/来源、缓冲/播放/完成/停止/打断/失败状态 |
| `0x33` | AUDIO_INTERRUPTED | ESP32 → HA | JSON：中断 ID、活动音频 ID（可空）、来源、近端语音打断原因 |
| `0x40` | DEVICE_EVENT | ESP32 → HA | JSON：状态变化事件 |
| `0x41` | ERROR | 双向 | JSON：错误代码、关联消息/会话 ID、简短说明 |
| `0x42` | DIAGNOSTIC_LOG | ESP32 → HA | JSON：日志级别、模块、事件/简短消息、设备运行时间及可选关联 ID/丢弃计数 |

未知消息类型不得导致连接进程崩溃；记录协议错误并忽略该消息。协议版本不兼容时，HELLO_ACK 返回不支持原因并关闭连接。

### 5.4 握手与连接状态

1. ESP32 开机后初始化 NVS/事件/Wi-Fi Station；取得 WLAN IP 后再启动 TCP 7777 与 7778 Server。
2. HA 根据配置的 ESP32 地址分别建立两个 TCP Client 连接。
3. 7777 连接建立后，HA 发送 `0x69 + 6-byte MAC` 请求 SPP 连接；P5 省略可选通道字节，由 ESP32 使用 SDP 发现 RFCOMM SCN，失败时回退至本机协议记录的通道 1。
4. 7778 建立后，ESP32 发送 HELLO；HA 校验协议版本并回复 HELLO_ACK。
5. 完成握手后，双方可在 7778 双向发送消息。
6. HA 使用 PING/PONG 判断 7778 是否仍可用；控制与音频通道的连接状态分别维护。
7. 任一通道断开时，HA 单独重连该通道。7778 重连不得重置仍正常工作的 SPP 连接；7777 重连后按需恢复 SPP 连接。
8. ESP32 网络断开时，停止新的网络音频会话；正在播放的受控音频按本地策略完成缓冲播放或由全局输出管理器停止，并上报可用的最终状态。

**P5 只实现上述最终协议的最小子集：**

- 7777：HA 下发 Tivoo 原始帧，ESP32 转交 SPP；P5 不要求 SPP 返回数据回传、完整结果语义或设备 ACK。HA TCP 连接断开后可重新建立连接，并重新发送 `0x69 + MAC` 恢复 SPP 控制通道；P5 不实现额外的 SPP 自动状态同步/回执协议。
- 7778：使用相同的 16 字节 TVIO 头部，完成 HELLO/HELLO_ACK，并支持 DIAGNOSTIC_LOG 与 ESP32→HA ERROR；Sequence 每个发送方向独立计数、每条连接从 0 开始。P5 HELLO/ACK JSON 结构和日志队列行为见 §5.5。连接断开后允许 HA 客户端做基础重连并重新握手，以恢复日志回传。P5 不实现心跳、完整 DEVICE_STATUS、MIC、TTS、AUDIO 或 HTTP 音频资源。
- P6 在同一端口和封装上扩展其余消息及双向行为，不重新设计或替换 P5 已通过的基础通路。

P5 HELLO Payload：

```json
{
  "device_id": "tivoo-esp32",
  "firmware_version": "0.1.0+<git-short-sha>",
  "protocol_version": 1,
  "capabilities": [
    "spp_control",
    "remote_diagnostics"
  ],
  "reset_reason": "<ESP-IDF reset reason name>"
}
```

建议 DEVICE_STATUS 至少包含：

- Wi-Fi 已连接状态及信号强度（能可靠取得时）。
- TCP 7777 / 7778 连接状态。
- Tivoo SPP 连接状态。
- 麦克风 I²S RX、AEC 和本地 VAD 运行状态。
- 当前麦克风网络上传会话状态（与物理采集状态分开）。
- AEC 播放参考帧欠载/错位计数及处理耗时（诊断用途）。
- 当前全局音频输出来源、音频 ID 和播放状态。
- 音频欠载/溢出计数和可用内存（用于诊断，不要求高频上报）。

不要虚构电池电量、屏幕实际显示状态等没有可靠硬件/协议来源的数据。

### 5.5 日志与诊断

- 项目模块通过 `TIVOO_LOGE/W/I/D` 分级宏记录日志；宏同时调用对应 ESP-IDF `ESP_LOG*` 保留 UART/console 输出，并将明确的级别、TAG 和消息放入网络诊断队列。第三方组件内部日志仍保留本地 UART，不通过解析全局格式化日志字符串推断级别。DIAGNOSTIC_LOG JSON 字段为 `level`、`module`、`message`、`uptime_ms`，可选 `correlation_id`、`dropped_count`；`level` 为 DEBUG/INFO/WARNING/ERROR。HELLO 报告设备 ID、固件版本（含 Git 短 SHA）、协议版本、能力列表及 `esp_reset_reason()` 的实际原因。具体 P5 JSON schema 以 `2026-11-11-p5-esp32-minimal-firmware-contract-matrix.md` §7.3 为准。
- 网络日志进入有界 RAM 队列，由低优先级发送任务上传；日志宏只做有界格式化/入队，不调用 socket、不等待发送。P5 默认队列深度 16 条，单条 `message` 最多 384 UTF-8 bytes，序列化 JSON 最大 1 KiB；达到上限时丢弃新记录并累计 `dropped_count`，不阻塞调用者。
- 仅在 7778 HELLO_ACK `accepted=true` 后发送 DIAGNOSTIC_LOG；未连接时保留有限近期记录，重连并重新握手后按入队顺序补发。队列满时丢弃新记录并累计 `dropped_count`；该计数随下一条成功日志上报后清零。队列只在 RAM，设备重启后不保留普通日志；不将每条日志写入 Flash。P5 ERROR 使用项目合同矩阵 §7.3 定义的错误码集合。
- 普通日志不逐条写 Flash；P5 不要求持久日志数据库或 Core Dump 导出，确有现场故障证据需求时再单独评估。
- HA 将设备日志映射到 `custom_components.tivoo` 标准 Python logger，INFO 为常规基线、DEBUG 按需开启，并按级别写入 HA 主日志（Container 默认文件为 `/config/home-assistant.log`）。部署时确保 `/config` 挂载到 NAS 持久化目录；ESP32 不直接连接 NAS，也不另建日志存储服务。
- 日志不得包含 Wi-Fi 密码、Authorization/API Token、短时音频 URL 凭据、原始 PCM、完整转写或回答正文。可记录模块、事件、错误码、耗时和内部关联 ID。

## 6. 麦克风音频上行：ESP32 → HA

### 6.1 数据格式

**TCP 7778 / HA Assist Satellite 上行合同保持不变**，不随 ESP32 本地 I²S 总线改为 32 kHz 而改变：

| 参数 | 值 |
|---|---|
| Sample Rate | 16000 Hz |
| Channels | 1 |
| Sample Format | signed 16-bit little-endian |
| Encoding | PCM S16LE |
| 典型帧长 | 20 ms |
| 每帧样本数 | 320 |
| 每帧 Payload | 640 bytes |

ESP32 从 INMP441 采集 32 kHz / 双 Slot / 32-bit Slot 数据，提取左声道有效 24-bit 样本并完成低通、2:1 降采样和位深转换，得到 16 kHz S16LE Mono 麦克风通道。与此同时，`audio_output_manager` 从最终播放 PCM 提供时间对齐的 16 kHz S16LE Mono 播放参考通道。两路按 ESP-SR AFE 要求交错排列为 M/R 输入，执行 AEC。

AFE 输出的 16 kHz S16LE Mono 增强音频是本项目唯一对外的麦克风 PCM：本地 VAD、预录环形缓冲、KWS/HA Pipeline 和 TCP 7778 `MIC_PCM` 必须共用这份 AEC 后数据。`MIC_PCM` 不上传原始未消回声麦克风样本；不得把 I²S DMA 原始缓冲未经解析/转换就假定为 S16LE。HA/Sherpa KWS 与 Paraformer STT 继续接收 16 kHz S16LE Mono，不改变 P7A 合同。

### 6.2 会话流程

1. ESP32 的 I²S RX、麦克风处理和本地 AFE AEC/VAD 在空闲监听及扬声器播放期间持续运行；空闲状态不上传无关音频，播放期间也不关闭麦克风 RX。
2. 普通空闲 VAD 触发后发送 MIC_SESSION_START，`trigger_source=idle_vad`，包含唯一 session_id、音频格式和预录缓冲时长；HA 从 `PipelineStage.WAKE_WORD` 开始本轮 Pipeline。
3. ESP32 先发送触发前的 AEC 后预录音频，再持续发送 AEC 后 MIC_PCM。
4. HA 把 PCM Payload 放入当前会话的异步音频队列，并把队列迭代器交给 Tivoo Assist Satellite 的 `async_accept_pipeline_from_satellite()`。
5. Pipeline 活跃期间 ESP32 必须持续发送音频，包括静音 PCM 帧；本地 VAD 不得在说话间隙擅自结束已启动的 HA Pipeline 音频流。
6. TTS 或其他音频输出期间，若 AEC 后的近端语音 VAD 达到打断条件，ESP32 先在本地停止全局音频输出，再发送 AUDIO_INTERRUPTED；随后发送 `trigger_source=barge_in`、带对应 interrupt_id 的新 MIC_SESSION_START，并上传预录及实时音频。该新会话由 HA 在旧 Pipeline 取消收尾后从 `PipelineStage.STT` 开始，不再要求用户先说唤醒词。
7. HA Pipeline 正常结束、超时或取消后，HA 发送 MIC_CAPTURE_STOP；ESP32 只停止本次网络上传，保留物理 I²S RX、AEC 与本地 VAD，返回本地监听。
8. ESP32 在主动结束或设备异常时发送 MIC_SESSION_END；HA 关闭对应音频队列，使异步音频迭代器正常结束。

一个设备同一时间只允许一个活动网络麦克风上传会话。新会话不得静默覆盖旧会话；打断场景需先由 HA 结束旧 Pipeline 输入/取消旧响应，再接管新会话队列。物理麦克风采集可持续存在，不受上传会话结束影响。

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

`tts-end` 表示本轮 TTS 输入已提交/关闭，不表示音频已全部合成、下载或播放完成。HA TTS Proxy 会将 Provider 返回的音频数据生成器逐块写入 HTTP 响应；ESP32 仍按流式方式读取。最终播放完成以设备回报的 AUDIO_STATE 为准，再由 HA 调用 `tts_response_finished()` 结束 Satellite 播报生命周期。

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

1. 收到 TTS_PLAY 后创建 playback_id 对应的播放源任务；URL 元数据来自 7778，不再额外请求一次 URL。
2. 使用 ESP-IDF HTTP Client 向该 URL 发起 GET，按需附加 HA 提供的短时访问凭据。
3. HTTP 响应体是实际的编码音频字节；按流式方式接收，不要求先将完整音频下载到 RAM。
4. 对 HA 明确提供的其他必要音频资源，复用同一 HTTP Client 和下载入口；首期不增加独立资源发现协议或任意文件浏览接口。
5. 根据 MIME/实际编码选择解码器，将音频增量解码成 PCM。
6. 将 PCM 转换为 DAC/I²S 输出所需采样率、位宽和声道格式。
7. TTS PCM 提交给 `audio_output_manager`，由统一输出管理器写入有界输出缓冲并驱动 I²S TX；音源任务不得绕过管理器直接写硬件。
8. 正常播放结束后发送 AUDIO_STATE，`state=completed`、`source=tts_http`，且 `audio_id=playback_id`。
9. HTTP、解码或 I²S 播放失败时发送 AUDIO_STATE，`state=failed`，并包含简短错误代码。
10. 收到 AUDIO_STOP 后停止全部当前/排队音频源，而不只停止 TTS：取消 HTTP/解码/生产任务，清空 PCM 与后端待播缓冲并停止当前输出后端。若带 `expected_audio_id` 且与当前活动源不匹配，则忽略该过期停止请求。

AUDIO_STATE 状态至少包括 `buffering`、`playing`、`completed`、`stopped`、`interrupted`、`failed`。HA 仅在与当前 Satellite TTS 响应关联的音频最终完成/停止/打断/失败后，结束对应播报生命周期并调用一次 `tts_response_finished()`；普通提示音等非 Satellite 响应不能误改 Satellite 状态。

### 7.3 格式与资源边界

必须区分 Sherpa Wyoming 输出、HA TTS Proxy HTTP 资源和 ESP32 I²S 输出三个层次：

| 层次 | 当前已确认的格式 | 说明 |
|---|---|---|
| Sherpa Wyoming TTS → HA | 22,050 Hz / Mono / signed 16-bit PCM | P7A AudioStart / AudioChunk 合同；PCM 由 HA 接收，不直接通过 TCP 7778 发送给 ESP32 |
| HA TTS Proxy → ESP32 HTTP | 生产端到端实测为 audio/mpeg，MP3 / 22,050 Hz / Mono | 2026-11-10 两轮生产 HA → AstrBot → Matcha → TTS Proxy 测试均为该格式；这是当前部署路径的实测结果，不构成所有 HA 响应永久固定为 MP3 的保证 |
| ESP32 解码后 → I²S TX | 32,000 Hz / Stereo / 32-bit Slot | 根据 HTTP 响应实际格式解码，再由 ESP32 SRC 转换至本地全双工总线 |

处理规则：

- TTS_PLAY 中的 mime_type 是 HA 传递的资源类型元数据；ESP32 HTTP Client 还应检查响应状态码和响应 Content-Type，并结合实际容器/帧头识别结果确认格式。不得根据 URL 文件名推断格式。元数据、响应头和实际数据不一致时，报告明确的音频格式错误，不盲目播放。
- 当前生产路径的首要目标是 audio/mpeg / MP3。MP3 解码后按解码器报告的真实采样率与声道处理；22,050 Hz Mono 是本次生产实测值，不能硬编码成所有未来资源的无条件属性。
- 保留 HA Core 2026.11.0 Wyoming 流式 TTS 的未知长度 WAV 兼容要求：其流式头可能声明 nframes=0，后续 PCM 按块到达。若最终 Satellite/TTS Proxy 路径返回该资源，ESP32 必须在 HTTP EOF 前持续解析/输出，不能等待 RIFF/data 长度成为已知值或等待整个文件下载完成。该格式与 MP3 是不同的 HTTP 容器路径，不得把 Wyoming 侧 22.05 kHz PCM 简化描述为 HTTP 原始 PCM。
- ESP32 首期只增加有实际链路依据的解码能力：至少覆盖当前生产实测 MP3，并保留对未知长度流式 WAV 的验证/兼容路径；其他编码格式只有在 HA 实际返回且确有需要时再增加。若部署配置变化导致 HA 返回固件尚不支持的格式，应返回音频格式错误，或由 HA 侧明确配置兼容输出，不在固件中堆叠无需求的解码器。
- HTTP 数据、解码器输入、解码后 PCM、SRC 输出及播放缓冲均使用有界内存。MP3 帧、WAV header 和 HTTP chunk 边界不得被当成 PCM 样本边界；解码器/SRC 必须跨 HTTP chunk 保留解析及滤波状态。
- 解码输出统一经 SRC 转换到 32 kHz；随后复制为左右声道并适配 32-bit I²S Slot。若解码输出已是 32 kHz，则不执行不必要的 SRC。
- 播放欠载必须计数并上报；网络接收与解码任务不得直接阻塞 I²S TX DMA。
- AUX 为首选输出；A2DP 不与同一段 AUX 音频并行播放。

### 7.4 全局音频输出停止与近端语音打断

`audio_output_manager` 是 ESP32 所有受控声音的唯一最终输出入口。首期 AUX/I²S 后端至少支持 TTS HTTP 音频；后续加入的提示音、通知音或其他音频源必须复用该管理器。音频源有自己的 source/audio_id 和生产任务，但不能自行持有最终 I²S TX 写入权。首期输出按单一活动播放源串行管理，未播放项目进入有界队列。

**全局停止行为：**

- HA 发送 `AUDIO_STOP` 表示停止 ESP32 当前所有可控音频输出及待播队列，不限定为 TTS。可选 `expected_audio_id` 用于保护新播放不被迟到的停止命令误伤；不提供该字段时按全局停止处理。
- ESP32 的本地 VAD 打断也直接调用同一个 `audio_output_manager.stop_all()` 语义，不通过模拟 TTS 任务停止或仅取消 TTS HTTP Reader 实现。
- 停止时先阻止新的 PCM 被提交，再取消各活动音源的生产/下载/解码任务，清空软件队列和 I²S TX 待播数据，最后停止/静音当前硬件后端。为了避免爆音允许极短输出淡出，但不得让长缓冲音频在打断后继续播放。
- 停止成功后通过 AUDIO_STATE 报告每个受影响活动源的最终状态。停止命令必须幂等；重复或过期请求不得造成任务崩溃或意外重新播放。

**本地语音打断（barge-in）行为：**

1. I²S RX 在播放时继续运行；AFE 同时接收 16 kHz 麦克风 M 通道和最终播放参考 R 通道，执行 AEC。
2. 本地 VAD 仅检查 AEC 输出的近端语音。满足配置的持续时间/能量条件后，将当前音频输出标记为 interrupted，立即停止全局输出；不要求用户先说 wake word。
3. ESP32 发送 AUDIO_INTERRUPTED（包含 interrupt_id、活动 audio_id/source、`reason=near_end_speech`），随后发送带 `trigger_source=barge_in` 和相同 interrupt_id 的 MIC_SESSION_START，并开始传送预录/实时 AEC 后 PCM。TCP 7778 上必须保持此消息顺序。
4. 停止输出后继续采集和 AEC；参考环形缓冲保留实际 TX 的尾帧/房间回声衰减所需的数据，避免立即清空参考状态导致残余回声误触发。
5. 本能力覆盖所有经过 ESP32 `audio_output_manager` 的声音源；不声称可以停止 Tivoo 自身独立播放、其他设备或外部音源。若启用 A2DP 后端，同样必须实现全局停止；其 AEC 参考时序需单独验收。

**HA 收到 AUDIO_INTERRUPTED 后的取消顺序：**

1. 按 interrupt_id 幂等处理并检查事件是否过期。若 `audio_id` 关联当前 Satellite 响应，则取消该响应；若音源是提示音等非 Satellite 响应，则不取消无关 Pipeline，但仍应接受这次真实近端语音并准备新的 STT 会话。只有与已结束/已被新播放替代的旧音频对应的迟到事件才忽略。
2. 只有当被打断音频关联到当前 Satellite 响应时，才关闭/取消该响应的 TTS Proxy 消费和流式输出，并阻止后续旧响应 TTS_PLAY/音频事件继续下发；非 Satellite 音源不应误取消其他对话响应。
3. 若存在与该响应关联的活动 `async_accept_pipeline_from_satellite()` Pipeline run，则取消并等待其收尾；取消必须传播到 Conversation Agent，关闭 AstrBot SSE reader，并按既有 P3 合同调用 owner 匹配的 AstrBot session stop。P3 的 stop 操作作用于整个 session，不是单独 run；不得另起一条 `assist_pipeline/run` 绕过 Satellite 的第二套生命周期。若中断音源没有关联旧 Satellite 响应，则不创建虚假的取消对象，也不取消其他 Pipeline。
4. 对已经进入 Satellite `RESPONDING` 的旧响应，在取消清理后将其播报状态收尾；`tts_response_finished()` 对同一响应最多调用一次。若中断的是非 Satellite 音源，则不调用该方法改变无关 Satellite 状态。该调用只结束 Satellite 播报状态，不能代替取消 Pipeline、TTS Proxy 或 AstrBot。
5. 对紧随其后的 `trigger_source=barge_in` 麦克风会话，在旧 run 的取消/清理完成后启动新 Pipeline，`start_stage=PipelineStage.STT`；若新 PCM 已经到达，先放入有界队列，不能因等待旧任务退出而丢失用户语音。普通 `idle_vad` 会话仍从 `PipelineStage.WAKE_WORD` 启动。
6. 如果 HA 上游取消失败或超时，设备端本地停止仍然有效；HA 必须报告取消未确认、阻止旧响应重新向设备输出，并按 P3 取消合同处理 AstrBot stop 失败，不能伪称上游已停止。

**HA 主动停止播放：** HA 发起停止时先向 ESP32 发送 `AUDIO_STOP`，让设备立即终止最终输出；同时取消与该音源关联的 TTS Proxy、Pipeline/Conversation Agent SSE，并按 P3 约定停止 AstrBot session。设备回报 AUDIO_STATE 后再完成 Satellite 收尾。不能等待模型/HTTP 取消完成后才停止扬声器；若音源不关联当前 Satellite 响应，只停止设备音频，不取消无关对话。

HA 的 Assist Satellite 公开接口要求通过 `async_accept_pipeline_from_satellite()` 运行 Pipeline，并在设备播放结束时调用 `tts_response_finished()`；具体如何中止正在运行的 Pipeline task 必须按项目固定的 HA Core 版本验证可用取消路径。不能把未公开的内部方法当成跨版本稳定 API。

## 8. HA 集成职责

HA 自定义集成是所有上层功能的唯一入口：

- 管理 ESP32 host、端口、TCP Client 连接及重连。
- 管理 7777 Tivoo 控制桥，并把 HA 服务调用编码成 Tivoo 二进制帧。
- 复用现有 Python Tivoo 协议/图片编码能力，不在 ESP32 重复图片编码。
- 管理 7778 握手、消息解析、音频队列和状态更新。
- P5 接收 DIAGNOSTIC_LOG/ERROR，按设备日志级别映射到 Tivoo 集成标准 logger；使用 HA 现有日志配置持久化，不直接写入自建文件或另开 NAS 接收服务。
- 将 MIC_PCM 流交给 Assist Satellite Pipeline。
- 监听 Pipeline 事件：在 `run-start` 保存 TTS URL、Token、MIME 和 `stream_response`；流式路径在 `intent-progress` 的 `tts_start_streaming=true` 时发送 TTS_PLAY，短回答/非流式路径在 `tts-end` 时发送 TTS_PLAY。
- 确保下发 URL 是 ESP32 可直接访问的 HA LAN 地址，并在需要时提供短时 HTTP 访问凭据。
- 复用 HA TTS Proxy 等现有音频资源服务；其他必要音频资源也通过明确的 HTTP URL 提供，不在首期另造资源发现 API。
- 接收 AUDIO_STATE，按 audio_id 关联当前 Satellite TTS 响应，并在正常完成/停止/打断/失败后正确结束 Satellite 播报状态。
- 处理 AUDIO_INTERRUPTED：如果活动音源关联当前 Satellite 响应，则取消对应 Pipeline/TTS Proxy/Conversation Agent 链路并收尾旧响应；否则不取消无关会话。两种情况下均停止迟到音频输出，并按 STT 阶段接收有效的 barge-in 新语音。
- 管理每个 Satellite 当前 Pipeline run、TTS playback_id 和 interrupt_id 的关联；确保取消幂等、不会误取消新一轮会话。
- 接收 AUDIO_STOP 相关结果；HA 主动停止服务与设备本地语音打断均调用统一取消收尾流程。
- 向 HA 暴露屏幕控制服务、Assist Satellite、SPP 状态和麦克风/AEC/播放诊断实体。
- 为 AstrBot MCP 工具提供稳定的业务服务接口；AstrBot 不直接连接 ESP32。

HA 服务参数使用语义化数据，例如亮度值、图片路径、文字内容；由 HA 端的 Tivoo 编码层生成最终 SPP 字节。

## 9. ESP32 固件职责

固件以 ESP-IDF 为基础，按模块划分：

- **wifi_station**：Wi-Fi Station 配置、连接状态及基础重连。
- **network_control**：TCP 7777 Server，兼容上游 raw Tivoo bridge 协议；P5 先支持单向 SPP 控制，P6 扩展完整双向行为。
- **network_audio**：TCP 7778 Server 和统一消息封装；P5 先支持 HELLO/ACK、DIAGNOSTIC_LOG、ERROR，P6 扩展完整状态/音频消息。
- **diagnostics_log**：封装 ESP-IDF 日志、启动/Reset Reason 记录和有界异步网络发送队列。
- **tivoo_spp**：复用/适配 esp32-divoom 的 Classic Bluetooth SPP、SDP channel discovery、发送队列和连接管理。
- **audio_capture**：共享全双工 I²S Controller 的 RX channel/DMA、INMP441 左 Slot 24-bit 提取、32 kHz → 16 kHz 转换、麦克风 M 通道准备和持续采集。
- **audio_frontend**：对齐播放参考 R 通道、构造 AFE M/R 交错输入、运行 ESP-SR 经典 ESP32 target 的 AEC/VAD，并输出唯一的 16 kHz 增强 Mono PCM 供预录与网络发送。
- **audio_playback**：HTTP Client、流式音频解码、PCM/SRC 转换和有界音源队列；不得自行绕过输出管理器写硬件。
- **audio_output_manager**：统一接收 TTS/提示音/其他音频源，管理活动源与待播队列、最终 PCM/音量处理、播放参考 tap、全局停止和输出状态；负责驱动当前 I²S TX 后端，未来可替换为实现同一接口的其他后端。
- **device_state**：聚合 Wi-Fi、TCP、SPP、麦克风和播放状态。

职责边界：

- ESP32 收到 7777 的完整 Tivoo 原始帧后，直接进入 SPP 发送队列；不解析图片文件、不生成调色板、不理解上层 AI 语义。
- ESP32 收到 7778 的 TTS 通知后负责 HTTP 获取和解码，再交给全局音频输出管理器；任何音源停止都在最终输出层执行，不只取消 TTS 输入/解码。
- `MIC_CAPTURE_STOP` 仅终止网络音频上传，不关闭物理采集和播放期间的 AEC/VAD；AEC 后音频才允许进入预录和 MIC_PCM。
- ESP32 本地 near-end VAD 打断后立即停止所有受控输出，并将 AUDIO_INTERRUPTED 与新的 barge-in 麦克风会话按序通知 HA。
- ESP32 不实现 BLE GATT 灯控，不维护键盘/背光控制任务。
- ESP32 的任何长耗时任务都不得阻塞 I²S DMA 和 SPP 发送队列。

## 10. 连接与错误处理

### 10.1 连接策略

- HA 是两个 TCP 通道的主动连接方。
- 7777、7778 分别报告连接状态，分别重连。
- TCP 断开后不得假报 SPP 断开；SPP 是独立状态。
- SPP 断开时由 ESP32 蓝牙模块进行有限重连；超过重试次数后报告不可用，等待 HA 请求或既有重连策略恢复。
- 重新建立 7777 后，HA 检查/恢复 SPP 连接，再发送屏幕任务。
- 重新建立 7778 后重新握手；已断开的麦克风上传会话不自动续传；未完成的音频输出根据 audio_id 和设备实际状态由 HA 决定重发或全局停止。

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
| `aec_init_failed` | ESP-SR AEC/AFE 初始化失败 |
| `aec_reference_underrun` | AEC 播放参考帧欠载或错位 |
| `audio_stop_failed` | 全局音频输出未能按时停止 |
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
| `esp32-divoom/components/divoom/hardware_bluetoothctl.cpp` | 设备发现、连接/重连和 SPP 事件回调 | 只复用按指定 MAC 连接/重连的状态机和回调职责；不复用 Classic peer inquiry 自动发现流程 |
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
- 新增代码限于 ESP-IDF 适配、Wi-Fi/既定 7777/7778 通信、诊断日志及音频采集/播放与 HA Assist Satellite 对接；Tivoo 协议和图片编码仍优先复用现有实现。

## 12. 验收标准

### 12.0 P5 最小固件

- ESP32 可连接配置的 Wi-Fi，并向 HA 提供 TCP 7777/7778；不要求配网门户或复杂网络管理功能。
- HA 通过 7777 下发一条现有 Tivoo 原始命令，ESP32 能经 Classic SPP 发送并在 Tivoo 实机观察到效果；P5 不验收 SPP 反向数据。
- HA 通过 7778 完成 HELLO/HELLO_ACK，并接收 DIAGNOSTIC_LOG/ERROR；日志按级别写入 HA 日志，并随 NAS 的 `/config` 持久化挂载保存。
- HELLO 报告设备 ID、固件版本和已实现能力；启动后上报 Reset Reason。诊断日志包含模块/级别及 uptime，不得出现凭据、原始音频或完整对话正文。
- 7778 断开、队列满或 HA 不可用时，日志发送不会阻塞 SPP；重连后补发队列中保留的记录并报告丢弃数。
- P5 不以 SPP 返回数据、完整 DEVICE_STATUS/心跳、MIC_PCM、TTS、HTTP 音频资源、I²S、AEC/VAD 或 Core Dump 导出作为验收条件。

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
- 同一 I²S Controller 的 RX/TX 能以 32 kHz、Stereo、32-bit Slot 完成 Standard/Philips 全双工运行；TX/RX 使用相同的 BCLK/WS 和 Slot 配置。
- INMP441 左 Slot 有效 24-bit 样本能正确解析并转换为 16 kHz S16LE Mono 麦克风 M 通道，降采样前有抗混叠滤波；M 与最终输出参考 R 经 AEC 后的增强 PCM 才供 VAD、预录和网络上传。
- ESP32 能上送预录 PCM 和实时 16 kHz S16LE mono PCM；HA 可将流交给 Assist Satellite Pipeline。
- Pipeline 活跃时静音帧仍持续上送；结束后音频迭代器能正常结束。
- INMP441 16 kHz 麦克风样本与最终播放参考能按 M/R 交错输入 WROVER-E 的 ESP-SR AFE AEC；输出为单声道增强 PCM，且 VAD、预录与 MIC_PCM 使用同一份处理结果。
- 播放参考从最终输出 PCM 获取，能正确转换为 16 kHz，并通过参考缓冲补偿 I²S TX/DMA 时延；停止播放后仍处理必要的回声尾部。
- HA 下发 TTS_PLAY 后，ESP32 能依据响应 MIME/实际容器流式解码；当前生产 MP3 路径可播放，未知长度 WAV（`nframes=0`）路径不得等待 HTTP EOF 后才开始处理。
- AUDIO_STOP 能停止当前和排队的所有 ESP32 受控音频源，不限 TTS；终止源任务、清空软件/硬件待播数据并反馈 AUDIO_STATE。
- 解码 PCM 能通过有状态 SRC 转为 32 kHz，并正确填入双声道 32-bit TX Slot；SRC/解码必须跨 HTTP chunk 保留状态，不因 chunk 边界产生断音。
- INMP441 转出的 16 kHz M 通道和最终播放 16 kHz R 通道按正确时间关系送入 AFE；AFE 的 VAD 播放静音开关保持关闭，以便用户在播放期间仍可打断。
- 播放期间用户近端说话时，AEC 后 VAD 能在配置阈值内检测并打断当前音频输出；TTS、提示音及其他纳入输出管理器的音源均能被同一全局停止操作终止。
- 播放期间扬声器自身回声不能稳定触发 barge-in；无播放时参考通道为静音，AEC/VAD 不出现持续误触发。
- AUDIO_INTERRUPTED 先于对应 barge-in MIC_SESSION_START 到达 HA；HA 能取消旧 Pipeline/TTS Proxy/AstrBot SSE，并在清理后以 STT 阶段接收新语音。
- HA 取消失败时设备仍保持本地停止，不允许旧响应恢复播放；Satellite 状态不会卡在 RESPONDING。
- TTS 完成、停止、打断和失败均能反馈到 HA，Satellite 能结束对应播报生命周期且不重复收尾。
- 音频传输期间 SPP 屏幕命令仍能正常执行；I²S 不出现不可接受的 DMA 阻塞/欠载。

### 12.3 设备端最终联调

- AUX 播放与 SPP 图形控制并行运行。
- ESP32 同时运行 Wi-Fi、同一 I²S Controller 的 32 kHz RX/TX 全双工、AEC/VAD 和 SPP 时，语音上行、播放、语音打断及屏幕控制均可持续工作。
- WROVER-E 实机在不同 Tivoo 音量和实际摆放条件下完成播放回声误触发率、近端语音打断成功率和处理资源测量；未达到体验要求时记录证据，再评估更换硬件。
- 不要求 BLE GATT 连接或灯控测试通过。

## 13. 测试策略

优先使用现有测试，不为已有逻辑重复建立平行测试框架：

### P5 网络与日志基线

- 验证 Wi-Fi、7778 HELLO/ACK 和诊断日志进入 HA 主日志。
- 验证 7777 单向 SPP 控制能在 Tivoo 实机生效。
- 覆盖 7778 断线、有限队列溢出、重连补发和 Reset Reason 上报，确认日志发送不阻塞 SPP。

### 后续阶段验证

1. **协议 Golden 测试**：沿用 `esp32-divoom/test/goldens` 思路和本地 Tivoo 协议测试，检查命令/图像编码字节不发生意外变化。
2. **TCP 帧测试**：复用 `util.cpp` 的拆包/粘包用例，补充 ESP-IDF TCP 收包边界测试。
3. **7778 协议测试**：测试头部编码、长度边界、未知类型、错误版本、粘包/拆包和 Sequence。
4. **HA 集成测试**：使用模拟 ESP32 TCP Server 验证连接、服务下发、音频队列接收、TTS 事件通知和断线恢复；额外验证 AstrBot ChatLog 增量、`stream_response=true`、`tts_start_streaming` 触发提前下载，以及短回答通过 `tts-end` 回退通知。Wyoming TTS 服务测试还需覆盖 `SynthesizeStart/Chunk/Stop`、HA 兼容性完整 `Synthesize` 不会导致重复合成，以及服务以 `SynthesizeStopped` 正常结束音频流。
5. **AEC 基线测试**：使用 ESP-SR 对应经典 ESP32 target，验证 16 kHz M/R 交错输入、AFE 输出帧、播放参考通道和 VAD；用已知播放参考 + 近端语音/纯回声录音测量回声残留、近端语音保留和资源占用。
6. **音频联调**：先用已知 PCM/正弦信号验证 32 kHz 全双工 RX/TX、INMP441 24-bit 对齐、32→16 kHz 抗混叠转换和播放参考的 32→16 kHz 时序对齐；再用生产 HTTP MP3 和 nframes=0 WAV 流验证解码、22.05→32 kHz SRC、PCM 缓冲及 I²S 输出。
7. **全局停止与打断测试**：分别从 HA AUDIO_STOP 和本地 AEC/VAD near-end 触发停止；验证 TTS 与其他输出源、HTTP/decoder tasks、软件 PCM 队列和 I²S TX 待播缓冲全部停止，麦克风 RX/AEC 不停止。
8. **HA 取消联调**：模拟 AUDIO_INTERRUPTED 后 HA 取消 Assist Pipeline、TTS Proxy、Conversation Agent SSE 和 AstrBot session stop；验证旧播放不会迟到恢复，新 barge-in 音频不丢失，并从 STT 阶段启动新一轮。
9. **实机验收**：最后在 Tivoo AUX 播放时持续发送 SPP 图片/动画，同时运行麦克风采集、AEC、VAD 和播放打断。

## 14. 设计约束与待实现时确认项

以下是实现阶段必须通过测试确认的参数，不阻止本规格作为通信契约使用：

- 当前 ESP-IDF 版本与 esp32-divoom SPP 代码适配所需的最小改动；全双工 API 及 TX/RX channel 配置必须与该版本匹配。
- GPIO 最终分配、模块板供电/接地、PCM5102 模块输出电平及 Tivoo AUX 模拟线路连接。
- INMP441 RX DMA word 的有效位位置、符号处理和增益；必须用已知信号验证 24-bit → S16LE 转换。
- 实际 HA TTS Proxy 的 MIME/容器覆盖范围，以及 MP3 和未知长度 WAV 在最终 Satellite 路径上的流式解码表现。
- esp_audio_codec / esp_audio_effects 的组件版本、MP3 解码支持、22,050 → 32,000 Hz SRC 能力及实际 CPU/RAM 占用。
- 当前 ESP-SR 版本对经典 ESP32 target 的 AEC/AFE 具体实现、M/R 通道配置、AEC frame size、内存布局及 WROVER-E 上的 CPU/RAM/实时余量；首版不假设 S3 FD AEC 可在经典 ESP32 使用。
- I²S TX DMA、播放缓冲和声学传播延迟形成的实际播放参考对齐偏移，以及 AEC 参考帧欠载、错位和房间回声尾部的处理参数。
- WROVER-E 实际播放音量、麦克风位置和 Tivoo AUX 声学环境中的回声残留与 near-end 语音检测效果。
- HA Core 固定版本中取消 `async_accept_pipeline_from_satellite()` 所管理 Pipeline 的可用方式；验证 TTS Proxy、Wyoming TTS 流、Conversation Agent 和 AstrBot stop 的取消传播及收尾顺序。
- 32 kHz I²S 总线时钟精度、DMA buffer 数量/长度、7778 有界队列长度和播放预缓冲阈值；按实测 Wi-Fi 抖动、时钟误差和播放连续性调整。
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
- [ESP-IDF I²S API](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/i2s.html) — ESP32 Standard I²S、TX/RX 全双工及共享 BCLK/WS 配置。
- [INMP441 数据手册](https://invensense.tdk.com/wp-content/uploads/2015/02/INMP441.pdf) — 24-bit I²S、64 SCK/WS stereo frame、L/R 选择及 SD 高阻行为。
- [PCM5102A 产品/数据手册](https://www.ti.com/product/PCM5102A) — 32-bit PCM 接口及 BCK PLL。
- [Espressif ESP Audio Codec](https://docs.espressif.com/projects/esp-adf/en/latest/basic-components/audio-codec/esp-audio-codec.html) — 流式 Simple Decoder 与音频格式解码。
- [Espressif ESP Audio Effects](https://docs.espressif.com/projects/esp-adf/en/latest/basic-components/effects/esp-audio-effects.html) — Sample Rate、Bit Depth 和 Channel Conversion。
- [ESP-SR classic ESP32 AFE configuration](https://github.com/espressif/esp-sr/blob/master/include/esp32/esp_afe_config.h) — 经典 ESP32 target 的 AEC mode 与 M/R 输入格式。
- [ESP-SR classic ESP32 AFE implementation](https://github.com/espressif/esp-sr/blob/master/src/esp_afe_sr_1mic.ref) — 经典 ESP32 上 SR AEC LOW_COST 分支的限制及当前实现。
- [ESP-SR AEC overview](https://docs.espressif.com/projects/esp-sr/en/latest/esp32/acoustic_echo_cancellation/README.html) — SR/FD/VOIP 模式的能力差异；FD 专有非线性处理不作为 WROVER-E 基线。
- [Home Assistant Assist Satellite developer documentation](https://developers.home-assistant.io/docs/core/entity/assist-satellite/) — `async_accept_pipeline_from_satellite()` 与 `tts_response_finished()` 生命周期。
- [P3 AstrBot Conversation Agent cancellation contract](2026-11-09-p3-astrbot-conversation-contract-matrix.md) — HA 取消向 SSE reader 和 AstrBot session stop 的传播规则。
