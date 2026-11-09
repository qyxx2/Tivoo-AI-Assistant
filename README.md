# Tivoo AI Assistant

> 基于 Divoom Tivoo、ESP32、Home Assistant 和 AstrBot 的个人 AI 语音终端。
>
> 当前阶段：**架构与项目目录已建立，尚未开始实现固件和服务代码。**

ESP32 与 HA 双向通信契约：[通信层规格书](docs/superpowers/specs/2026-11-09-esp32-ha-bidirectional-communication-design.md)（待审阅）。

P3 HA Conversation Agent 与 AstrBot HTTP/SSE 接口：[P3 接口合同矩阵](docs/superpowers/specs/2026-11-09-p3-astrbot-conversation-contract-matrix.md)（接口已定稿，待实现与验收）。

语音识别与合成端到端处理：[STT/TTS 链路规格](docs/superpowers/specs/2026-11-09-stt-tts-end-to-end-pipeline-spec.md)（待实现与验收）。

## 1. 项目目标

保留 Divoom Tivoo 原有的外观、扬声器、麦克风、AUX 输入、16×16 像素屏幕和按键，使用一块 ESP32-WROVER-E 作为专用硬件主控，将 Tivoo 接入 Home Assistant，并由 AstrBot 提供统一的 AI 对话能力。

最终希望实现：

- **自然语音交互**：Tivoo 通过唤醒词进入语音交互，完成语音输入和语音回复。
- **智能家居控制**：AI 理解自然语言，并调用 Home Assistant 中的设备、脚本和自动化。
- **日常助手能力**：时间查询、倒计时、提醒、状态查询等。
- **复杂 AI 对话**：接入云端 LLM，进行连续对话、复杂任务和信息检索。
- **人格与记忆**：由 AstrBot 统一管理人格、会话和长期记忆，避免简单指令与复杂对话表现成两个不同的助手。
- **MCP 扩展**：通过 MCP 接入记忆、搜索及其他外部工具。
- **Tivoo 表情反馈**：AI 根据对话内容选择表情、动画，也可以按需生成新的像素图片。
- **主动交互**：AI 可以按计划、事件或任务结果主动向 Tivoo 播报，也可以邀请用户继续对话。

## 2. 总体架构

采用三层结构，NAS 是服务端，ESP32 是 Tivoo 专用硬件控制器。

```text
┌──────────────────────────── NAS ─────────────────────────────┐
│                                                              │
│  AstrBot                                                     │
│  ├─ 云端 LLM / 人格 / 会话 / 记忆                             │
│  ├─ MCP Client：主动调用 HA 提供的工具                       │
│  └─ 插件 / 主动任务 / HTTP Chat API                          │
│       ▲                              │                       │
│       │ HA Conversation Agent       │ AstrBot 调用 HA MCP    │
│       │ 通过 HTTP 交付 STT 文本      ▼                       │
│  Home Assistant：MCP Server + Assist Pipeline                │
│  ├─ Wake Word / STT / AstrBot Conversation Agent / TTS       │
│  ├─ Tivoo 自定义集成 / Assist Satellite                       │
│  ├─ Tivoo 设备实体、服务和 LLM Tools                          │
│  └─ 家庭设备 / Timer / 自动化                                 │
│                 │                                            │
└─────────────────┼────────────────────────────────────────────┘
                  │ Wi-Fi：ESP32 只连接 HA
                  ▼
┌──────────────────── ESP32-WROVER-E ──────────────────────────┐
│  ESP-IDF 自定义固件                                           │
│  ├─ I2S RX：直接接收 INMP441 麦克风 PCM                        │
│  ├─ I2S TX：外部 I2S DAC 输出模拟音频至 Tivoo AUX（首选）      │
│  ├─ A2DP Source：可选备用音频输出路线                         │
│  ├─ SPP Client：屏幕、文字、动画和内置显示模式                │
│  └─ ESP-SR AFE VAD：本地人声门控、空闲时不上传音频             │
└─────────────────┬────────────────────────────────────────────┘
                  │ I2S 连接麦克风和外部 DAC；模拟音频接入 AUX；
                  │ Bluetooth Classic SPP 用于屏幕和内置功能控制
                  ▼
┌──────────────────────── Tivoo ────────────────────────────────┐
│  麦克风 · 扬声器 · AUX 输入 · 16×16 屏幕 · 原有按键            │
└───────────────────────────────────────────────────────────────┘
```

### 2.1 部署位置

| 组件 | 部署位置 | 主要职责 |
|---|---|---|
| Home Assistant | NAS | Assist Pipeline（HA 唤醒词检测、STT、AstrBot 对话、TTS）、设备管理和自动化 |
| AstrBot | NAS | 唯一 AI 主体、云端模型、人格、记忆、MCP、主动任务 |
| 必要 Linux 脚本 | NAS | 容器部署、备份、健康检查、日志维护 |
| Tivoo 自定义集成 | HA 内部 | ESP32 音频接入、Assist Satellite、Tivoo 实体/服务、LLM Tools |
| 中文 Wake Word Provider | NAS 服务（待选型） | 通过 Wyoming 或 HA 自定义集成向 Pipeline 提供中文唤醒词识别 |
| AstrBot Tivoo Bridge | AstrBot 插件 | 主动任务通知、HA 接口调用及交互桥接 |
| ESP32 固件 | Tivoo 专用开发板 | 本地 VAD、音频收发与播放、SPP 协议桥接及屏幕控制 |

**网络边界：ESP32 只连接 Home Assistant，不直接连接 AstrBot、云端 LLM、MCP 服务或其他 NAS 容器。**  
AstrBot 需要控制 Tivoo 时，统一经过 Home Assistant 提供的 Tivoo 工具和接口。

NAS 上的 AstrBot、HA 和辅助服务按实际 NAS 系统及容器环境部署。本目录保存部署文件和脚本；不会把它们安装到 ESP32。

## 3. AI 与语音交互设计

### 3.1 统一 AI 主体

AstrBot 是唯一的 AI 对话主体。简单指令和复杂问题都进入同一个 AI 会话，使用一致的人格和记忆。

Home Assistant 不作为另一个独立聊天机器人，也不在普通语音指令上绕过 AstrBot，直接给出与 AI 无关的机械式回答。Assist Pipeline 由 HA 负责唤醒词检测、STT、Conversation Agent 调度和 TTS；Conversation Agent 使用我们实现的 AstrBot 适配层。

**识别文本不能靠 AstrBot 调用 HA MCP 工具来“接收”。** MCP 的工具调用方向是 MCP Client 调用 MCP Server：本项目中 AstrBot 是 Client、HA 是 Server。因此，HA 得到 STT 文本后，应由自定义 Conversation Agent 通过 AstrBot HTTP API 把文本交给 AstrBot；反方向上，AstrBot 才通过 HA MCP 工具调用 HA 的设备和 Tivoo 服务。

普通语音回复不需要 AstrBot 再调用一个“转语音”MCP 工具：AstrBot 返回文本给 HA Conversation Agent 后，HA Assist Pipeline 执行 TTS。Assist Satellite 集成通过 Pipeline 事件取得音频 URL、Token 和 MIME 类型，再通知 ESP32 获取音频并播放；不是由 HA 直接通过 ESP32 音频通道推送原始 PCM。主动播报时，AstrBot 才调用 HA 提供的 announce/start-conversation 工具或动作。

语音链路（采用 ESP32 本地 VAD、HA 服务端唤醒词检测）：

1. INMP441 麦克风由 ESP32 I2S RX 持续本地采样；ESP-SR AFE VAD 只判断是否有人声。空闲时不上传麦克风音频，并保留短时预录缓冲，避免触发上传时截断语音开头。
2. VAD 检测到人声后，ESP32 通过 HA Tivoo 自定义集成建立音频会话。集成将音频流交给 `AssistSatelliteEntity.async_accept_pipeline_from_satellite()`，以 `PipelineStage.WAKE_WORD` 启动、以 `PipelineStage.TTS` 结束；由 HA 选择 Pipeline 并维护 HA conversation ID。项目采用 Assist Satellite 入口，不再让 ESP32 同时自行调用 `assist_pipeline/run` 管理同一条会话。
3. ESP32 先发送预录缓冲，再持续发送 16 kHz、16-bit、单声道 PCM。Pipeline 活跃期间必须继续发送麦克风音频（包括静音帧）；本地 VAD 只负责从空闲状态触发会话，不能在第一次静音时关闭音频流，否则 HA 无法正常判断唤醒词等待超时和指令结束。
4. HA 的 `wake_word` Provider 检测配置的唤醒词。命中后 Pipeline 自动进入 STT；在设定的静音超时内未命中，则 Pipeline 结束，ESP32 返回本地 VAD 空闲监听。
5. HA STT Provider 将指令音频识别为文字。指令结束由 HA Pipeline/Provider 的 VAD 或端点检测机制处理（取决于 Provider 能力）；这与 ESP32 仅用于启动上传的本地 VAD 门控是不同职责。
6. HA 自定义 Conversation Agent 将文字、稳定用户标识及映射后的 AstrBot `session_id` 发送到 AstrBot 自有 HTTP OpenAPI：`POST /api/v1/chat`（AstrBot v4.18.0+；`enable_streaming: true` 时使用 SSE）。这不是 OpenAI 兼容的 `/v1/chat/completions` 接口。
7. AstrBot 使用指定人格、会话上下文和检索到的长期记忆处理请求，并按需作为 MCP Client 调用 HA MCP Server 的工具，控制家庭设备或 Tivoo。
8. Conversation Agent 将 AstrBot SSE 增量内容转换为 HA Conversation 流式响应；HA Assist Pipeline 再调用 TTS Provider。是否能边生成边播放，还取决于 TTS Provider 是否支持流式输入，不能仅凭 AstrBot SSE 或离线 RTF 推断。
9. HA 通过 Assist Satellite 的 Pipeline 事件向 ESP32 通知 TTS 输出信息（音频 URL、Token、MIME 类型等）。ESP32 按返回的音频格式通过 HA 地址获取音频，解码/转换为 PCM，再由 I2S TX 驱动外部 I2S DAC，模拟音频接入 Tivoo AUX 播放；A2DP 保留为备用路线。播放结束后集成调用 `tts_response_finished()`，将 Satellite 状态恢复为空闲。
10. Assist Satellite 状态和 AstrBot 的情绪工具共同控制 Tivoo 的屏幕表现。音频走 AUX 时，屏幕控制仍通过 SPP。**设备端并发能力已于 2026-11-08 实测通过**：Tivoo 通过 AUX 播放外部音频时，保持 `Tivoo-light` BLE 连接，仍可通过 SPP 正常发送指令并显示图形。该测试只记录设备端 BLE 身份连接与 AUX/SPP 并行的现象；目前没有证据证明 `Tivoo-light` 提供本项目可用的 GATT 灯控接口，因此不要求 ESP32 建立 BLE GATT 连接。后续验证 ESP32 固件侧 Wi-Fi、I²S RX/TX 与 SPP 的长期并发稳定性。

### 3.2 Home Assistant 的职责

HA 作为语音和设备中枢，负责：

- Assist Pipeline：HA 唤醒词检测、STT、Conversation Agent 调度和 TTS。
- Tivoo Assist Satellite：接收设备音频流、启动和维护 Pipeline、处理 Pipeline 事件及播报/主动对话生命周期。
- Wake Word Provider：提供 HA 服务端唤醒词识别；中文引擎需要单独接入，当前尚未完成。
- Tivoo 自定义设备集成：屏幕模式、音频状态和内置工具。
- 家庭设备实体、Timer Helper、脚本和自动化。
- 向 AstrBot 提供 MCP 工具。

HA 的 Conversation Agent 通过 AstrBot HTTP OpenAPI 将 STT 文本交给 AstrBot，并将 SSE 文本增量逐段写入 HA ChatLog。当前单用户阶段使用专用 API Key 派生的 AstrBot username（`api_key:<key_id>`），独立 UUIDv4 session_id 由 HA Store 持久化，24 小时无活动后轮换；正常上下文压缩不触发轮换。接口、SSE 事件、取消语义及验收要求以 [P3 接口合同矩阵](docs/superpowers/specs/2026-11-09-p3-astrbot-conversation-contract-matrix.md) 为准。

### 3.3 AstrBot 的职责

AstrBot 负责：

- 云端 LLM 模型接入。
- 统一人格、系统提示词和对话上下文。
- 长期记忆的检索与保存。
- 通过 MCP 使用 HA 提供的设备、Tivoo 和自动化工具。
- 通过插件执行计划任务和主动交互。
- 根据对话内容决定 Tivoo 的情绪和表情。

长期记忆不能仅依赖 AstrBot 是否临时调用某个工具。若要求每轮都带入相关记忆，需要在对话入口或 Agent 工作流中明确执行记忆检索，并把检索结果注入当前上下文。

## 4. Tivoo 自定义 HA 集成

集成目录：`homeassistant/custom_components/tivoo/`

该集成是 ESP32 与 HA 之间唯一的应用层入口。它负责管理 ESP32 连接、接收实时 PCM 音频并提供给 Assist Satellite；由 Satellite 调用 `async_accept_pipeline_from_satellite()` 启动 Pipeline，并在 `on_pipeline_event()` 中处理事件和转发 TTS 音频信息。不要再为同一条会话同时实现独立的 `assist_pipeline/run` 生命周期。它不让 AstrBot 或其他容器直接访问 ESP32。

### 4.1 设备实体

初步规划的实体：

| 实体 | 作用 |
|---|---|
| `assist_satellite.tivoo` | 语音卫星状态、播报和对话 |
| `media_player.tivoo` | 扬声器状态及音量（以实际协议能力为准） |
| `select.tivoo_display_mode` | 16×16 屏幕显示模式（仅暴露实测支持的模式；纯色/光效如可用，通过 SPP 控制） |
| `switch.tivoo_screen` | 屏幕开关 |
| `number.tivoo_brightness` | 屏幕亮度 |
| `binary_sensor.tivoo_mic_ready` | I2S 麦克风采集链路状态 |
| `binary_sensor.tivoo_a2dp_connected` | 备用 A2DP 路线的连接状态；采用 AUX 时不作为音频可用性的依据 |
| `binary_sensor.tivoo_spp_connected` | SPP 状态 |
| `sensor.tivoo_battery` | 电池状态；需要实际接入电压采样后实现 |

实体只暴露有可靠状态来源的属性。不能把命令发送成功直接当成 Tivoo 已经执行或显示成功。

### 4.2 HA 服务与 LLM 工具

初步规划的 HA 服务：

- `tivoo.set_expression`：设置预设表情。
- `tivoo.play_animation`：播放动画。
- `tivoo.show_text`：显示文字。
- `tivoo.show_image`：显示图片。
- `tivoo.set_brightness`：设置亮度。
- `tivoo.start_countdown`：启动 Tivoo 内置倒计时。
- `tivoo.stop_countdown`：停止 Tivoo 内置倒计时。

集成还需要实现 HA LLM API 工具平台（`llm.py`），把适合 AI 调用的 Tivoo 操作注册为 LLM Tools。Home Assistant 的 MCP Server 会将已注册的 LLM API 工具通过 MCP 暴露，因此 AstrBot 可作为 MCP Client 调用这些工具。无需再为同一组 HA 工具额外写一套独立 MCP Server。

需要区分：
- HA 的普通服务是集成提供给自动化和脚本使用的接口。
- LLM Tools 是向 HA 对话 Agent 注册的 AI 工具。
- MCP Server 是让 AstrBot 通过 MCP 调用这些 HA 工具的桥梁。

**方向约定：**
- HA → AstrBot：STT 识别文本通过自定义 Conversation Agent 调用 AstrBot HTTP Chat API。
- AstrBot → HA：AI 工具调用通过 AstrBot MCP Client → HA MCP Server。
- HA → Tivoo：普通回复由 Assist Pipeline TTS 输出；主动播报由 HA 的 Satellite announce/start-conversation 能力处理。

MCP 是工具调用协议，不是 HA 向 AstrBot 推送用户文本的消息通道。不要把这两条方向相反的链路混为一谈。

图片和动画使用独立的数据传输接口，不将大块图片数据塞进普通 JSON/MCP 参数。AI 工具负责发起任务，具体文件传输由 NAS 上的 Tivoo 服务和 HA 集成完成，再由 ESP32 通过 SPP 发送。

## 5. ESP32 自定义固件

目标硬件：ESP32-WROVER-E-N16R8（16MB Flash、8MB PSRAM、Bluetooth Classic；本项目使用 Classic SPP，不要求启用 BLE GATT）。

固件基于 ESP-IDF / C/C++，不把 HA、AstrBot、MCP 或 AI 模型部署到 ESP32。

### 5.1 外设接口与连接角色

| 功能 | ESP32 角色 | 用途 |
|---|---|---|
| 麦克风 | I2S RX | INMP441 数字麦克风直接连接 ESP32；安装位置和收音效果需实机验证 |
| 扬声器（首选） | I2S TX + 外部 I2S DAC | 输出模拟线路音频并接入 Tivoo AUX |
| 扬声器（备用） | A2DP Source | AUX 路线不可用或音质/电气条件不满足时，向 Tivoo 发送 TTS 音频 |
| 屏幕/内置显示模式 | SPP Client | 发送像素图、文字、动画、亮度及已确认的内置显示功能指令 |

### 5.2 固件任务

- 蓝牙连接与重连。
- I2S DMA 连续采集、PCM 环形缓冲与音频分帧。
- 将麦克风 PCM 输入 ESP-SR AFE VAD；空闲时只在本地检测人声，不上传麦克风音频；触发后发送预录缓冲并持续上送当前会话音频。
- 根据麦克风实际输出格式完成必要的采样率和位宽适配，向 HA 提供 16 kHz、16-bit、单声道 PCM。
- 接收 HA 通过 TCP 7778 发送的 TTS 音频 URL、Token 和 MIME 类型，再由 ESP32 HTTP Client 主动 GET 获取实际音频数据；对其他由 HA 明确提供的必要音频资源复用同一 HTTP 入口。音频流式解码/转换为 PCM 后，首选通过独立 I2S TX 驱动外部 I2S DAC，输出模拟线路音频至 Tivoo AUX。
- 将 A2DP Source 保留为可选备用输出，不与 AUX 主路线同时承担同一段音频播放。
- AUX 播放期间继续通过 SPP 接收屏幕和功能控制命令；Tivoo 设备端已实测确认 AUX 播放、保持 `Tivoo-light` 蓝牙连接与 SPP 图形控制可并行，ESP32 固件集成后的持续运行稳定性仍需验收。
- 接收 HA 控制命令并驱动 SPP；不实现独立 BLE GATT 灯控、键盘背光或背光控制。
- 上报连接状态、执行结果和错误信息。

ESP32 不解析复杂自然语言，也不做 LLM 推理。它只执行 HA 下发的明确操作。

### 5.3 TTS 音频输出：AUX 优先，A2DP 备用

新的首选输出路线是 **ESP32 I2S TX → 外部 I2S DAC → 模拟线路音频 → Tivoo AUX**。HA Assist Pipeline 完成 TTS 后提供音频 URL、Token 和 MIME 类型；Tivoo Assist Satellite 集成将这些信息交给 ESP32。ESP32 通过 HA 地址获取音频，按 MIME/实际编码解码或转换为 PCM，再做播放缓冲并送入 DAC，由 Tivoo 自身的音频输入电路和扬声器完成播放。

这条路线的预期收益：

- 不再通过 A2DP 传输 TTS 音频，省去 ESP32 侧 SBC 编码、Tivoo 侧 SBC 解码及 A2DP 音频传输占用。
- Wi-Fi 负责传送音频资源数据；ESP32 获取并解码为 PCM 后，由本地 I2S TX 持续输出，网络抖动由播放缓冲区吸收。
- SPP 用于屏幕、文字、动画和已确认的内置功能控制。AUX 替代的是音频传输，不替代 SPP 控制通道；本项目不依赖 BLE GATT 灯控。

**实测状态（2026-11-08）：设备端 AUX + SPP 并发已通过。** 用户在实际 Tivoo 上验证：AUX 输入正在播放外部音频时，设备仍保持与 `Tivoo-light` 的 BLE 连接，并能正常通过 SPP 发送指令、显示图形。该 BLE 连接仅作为本次设备端共存测试条件；现有协议资料将其记录为发现/广播身份，未确认可用的 GATT 控制特征，因此 ESP32 固件不需要维护该 BLE 连接。后续只需验证 ESP32 同时运行 Wi-Fi、I²S RX/TX 与 SPP 时的持续稳定性、控制响应和音频缓冲表现。

DAC 选择：

- **优先评估外部 I2S DAC 模块。** 它把 ESP32 的数字 PCM 转换为线路级模拟音频，音质、噪声和输出电平通常比芯片内部 DAC 更适合作为 AUX 输入源。具体 DAC 模块、供电、输出电平、接地和耦合方式需根据 Tivoo AUX 输入实测确定。
- **ESP32 内置 DAC 仅作低成本实验选项。** 原版 ESP32 的内部 DAC 为 8-bit，模拟输出质量和动态范围有限；通常还需要低通滤波、交流耦合及电平匹配，不应默认作为最终音频输出方案。不得把 DAC 输出直接接到扬声器单元；目标是接 Tivoo 的 AUX 线路输入。
- 麦克风 I2S RX 与 DAC I2S TX 需要分别配置和测试。WROVER-E 所用经典 ESP32 提供两个 I2S 控制器，设计时应为采集和播放分别分配接口、DMA 缓冲与时钟配置，避免让音频播放任务阻塞麦克风采集。

AUX 路线可以消除 A2DP 音频流及其 SBC 编解码负担，但**不会消除所有无线共存问题**：Wi-Fi 仍与 Bluetooth Classic SPP 共用 2.4GHz 无线环境，仍需验证音频连续性和控制响应。PCM 通过 Wi-Fi 传输、分块和播放缓冲仍然需要实现；模拟输出也不意味着端到端延迟为零。

备用路线：如果 AUX 的电气条件或音质不满足要求，保留 ESP-IDF A2DP Source 作为可切换的替代输出。A2DP 与 AUX 使用同一上层 TTS PCM 接口，尽量只在 ESP32 音频输出后端做切换。采用 A2DP 备用路线时，也必须单独验证 Tivoo 在 A2DP 播放期间仍能接收并响应 SPP 命令；不能假定切换到 A2DP 后就自动满足控制并发要求。

### 5.4 人声活动检测与唤醒词

**选定分工：ESP32 本地 VAD 负责决定何时开始上传；Home Assistant 负责识别真正的唤醒词。** 不在当前主流程中运行 ESP32 WakeNet。

- ESP32 使用乐鑫 ESP-SR AFE 的 VAD 检测当前音频帧是否存在人声。AFE 支持经典 ESP32，并可通过 `vad_state` 获取检测状态；若启用 VAD cache，应将缓存的语音前段与触发后的音频衔接，避免丢失开头。
- 空闲状态持续本地采样和运行 VAD，但不上传麦克风音频；保留短时预录缓冲。VAD 触发后启动 HA Assist Satellite 音频会话并发送预录缓冲。
- 会话启动后持续上传麦克风 PCM，包括静音帧，直到 HA Pipeline 结束。VAD 只负责空闲到会话的门控，不能在第一次静音时停止上传；HA 需要连续音频中的静音来判断唤醒词等待超时，并供 Pipeline/Provider 的指令端点检测使用。
- HA 从 `PipelineStage.WAKE_WORD` 开始，使用配置的 `wake_word` Provider 检测唤醒词。识别成功后自动进入 STT；未在超时窗口内识别到唤醒词则结束 Pipeline，ESP32 恢复本地 VAD 空闲监听。
- 首选输入格式为 16 kHz、16-bit signed、单声道 PCM，与 HA Assist Satellite 的要求一致。ESP32 本地预录缓冲用于保留 VAD 触发前的语音开头；HA Pipeline 的唤醒词检测缓冲属于另一层，不应混为同一功能。

**中文唤醒词的 Provider 缺口：**

- Home Assistant 需要一个 `wake_word` Provider 实体，Assist Pipeline 本身只负责调用 Provider，并不内置任意中文唤醒词模型。
- Home Assistant 官方 openWakeWord 接入目前面向英文唤醒词，不适合作为中文唤醒词的默认方案。
- `sherpa-onnx` 提供中英关键词检测模型（例如 `sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20`），但模型/运行库本身不是 HA Provider。需要将它封装为 Wyoming Wake Word 服务，或实现 HA 自定义 `wake_word` 集成；优先评估 Wyoming 适配，尚未确认可直接部署的现成中文服务。

因此当前需要单独验证中文关键词、误唤醒率和真实 Tivoo 收音效果。若以后改回设备本地唤醒词，ESP32 可在本地识别后从 `PipelineStage.STT` 启动，并传入 `wake_word_phrase`；这属于备用模式，不与当前 HA 服务端唤醒词流程同时启用。

参考：
- [ESP-SR AFE / VAD](https://docs.espressif.com/projects/esp-sr/en/latest/esp32/audio_front_end/README.html)
- [ESP-SR VADNet](https://docs.espressif.com/projects/esp-sr/en/latest/esp32/vadnet/README.html)
- [Home Assistant Assist Pipeline](https://developers.home-assistant.io/docs/voice/pipelines)
- [Home Assistant 唤醒词机制](https://www.home-assistant.io/voice_control/about_wake_word)
- [sherpa-onnx 中文/英文 KWS 模型](https://github.com/k2-fsa/sherpa-onnx/tree/master/docs/source/onnx/kws/pretrained_models)

## 6. 主动对话与表情

### 6.1 AI 主动发起对话

AstrBot 的主动任务或插件负责决定何时、为什么主动联系用户。AstrBot 插件通过 HA MCP 工具（或经过授权的 HA WebSocket/REST 接口）请求 HA 发起播报；不直接连接 ESP32。

主动输出统一交给 HA：
- 单向播报：HA 集成封装 `assist_satellite.announce` 能力。
- 主动播报并邀请用户继续对话：HA 集成封装 `assist_satellite.start_conversation` 能力。

`start_conversation` 能否与 AstrBot 连续会话配合，取决于自定义 Conversation Agent 是否正确维护并恢复 conversation/session ID，需要在集成阶段实现和验证。

HA 再通过 Tivoo Assist Satellite 集成控制 ESP32 播放语音，并按会话状态启用或停止 I2S 麦克风采集。

AstrBot 侧计划实现 `astrbot_tivoo_bridge` 插件。它负责将 AstrBot 主动任务连接到 HA，而不是让 AstrBot 直接连接 ESP32。

### 6.2 情绪与屏幕反馈

运行状态与 AI 情绪分开管理：

- 设备运行状态：Idle、Listening、Processing、Speaking、Error，由 HA Assist Satellite 事件驱动。
- AI 情绪：Happy、Curious、Empathetic、Excited、Sad、Neutral 等，由 AstrBot 根据人格和对话上下文决定。

AstrBot 通过 HA MCP 工具调用 `tivoo.set_expression` 或 `tivoo.play_animation`。

日常使用预设表情，优先保证响应速度。只有用户明确要求或 AI 判断有必要时，才调用图像生成模型生成新像素图。

## 7. 图片与音频数据通路

### 7.1 图片

图片生成、缩放、16×16 像素量化和动画帧制作放在 NAS 的 Python 服务中。复用现有 Tivoo Python SDK 的协议构建逻辑。

数据通路：

```text
AstrBot / AI 图像生成
        ↓
NAS Tivoo Service（Pillow）
        ↓
HA Tivoo Integration
        ↓
ESP32
        ↓ SPP
Tivoo 屏幕
```

### 7.2 麦克风输入

```text
INMP441 麦克风
    ↓ I2S 数字 PCM
ESP32 I2S RX + DMA
    ↓ ESP-SR AFE VAD（空闲时仅本地处理）
检测到人声：发送预录缓冲并建立音频会话
    ↓ Wi-Fi 音频通道
HA Tivoo Integration / Assist Satellite
    ↓ PipelineStage.WAKE_WORD
HA Wake Word Provider
    ↓ 唤醒词命中
STT → AstrBot Conversation Agent → TTS
```

当前方案不通过 HFP/SCO 获取麦克风音频，改由 INMP441 数字麦克风通过 I2S 直接连接 ESP32。ESP32 使用 AFE VAD 做本地人声门控；空闲时不上传麦克风音频，检测到人声后再启动 HA 音频会话。会话期间持续发送 16 kHz、16-bit、单声道 PCM（包括静音帧），直到 HA Pipeline 结束，不能由本地 VAD 在短暂静音时提前断流。

项目通过自定义 `AssistSatelliteEntity.async_accept_pipeline_from_satellite()` 启动 Pipeline，并使用 `PipelineStage.WAKE_WORD` 让 HA 检测唤醒词。Assist Satellite 要求输入音频为 16 kHz、16-bit、单声道 PCM。只有将来改用 ESP32 本地唤醒词时，才从 `PipelineStage.STT` 启动并传入 `wake_word_phrase`；这不是当前选定路线。

参考：
- [Assist Satellite 开发文档](https://developers.home-assistant.io/docs/core/entity/assist-satellite/)
- [Assist Pipeline 文档](https://developers.home-assistant.io/docs/voice/pipelines)

### 7.3 扬声器输出

**首选：AUX 模拟音频**

```text
AstrBot 返回文字
    ↓
HA Assist Pipeline TTS
    ↓ tts-end / Pipeline 事件
Assist Satellite 集成取得音频 URL、Token、MIME 类型
    ↓ 通知 ESP32
ESP32 通过 HA 地址 HTTP 获取音频并按格式解码
    ↓ PCM 播放缓冲区
I2S TX → 外部 I2S DAC（模拟线路输出）
    ↓ 3.5mm / AUX 音频线
Tivoo AUX 输入 → Tivoo 扬声器
```

HA Pipeline 事件提供音频资源信息，不应描述为直接通过设备音频通道推送原始 PCM。ESP32 按返回的 URL、Token 和 MIME/编码获取音频，并转换成 I2S 所需 PCM。实际输出格式、鉴权方式、HTTP 地址可达性和解码器需要在固件联调时确认。ESP32 内置 8-bit DAC 可用于早期验证信号链，但不作为默认最终音质方案。正式实现优先使用外部 I2S DAC，并按 Tivoo AUX 输入规格确认线路电平、交流耦合、滤波、接地和左右声道连接。

**备用：A2DP**

```text
HA TTS 音频 URL / Token / MIME 信息
        ↓ ESP32 HTTP 获取并解码
ESP32 PCM 缓冲区
        ↓
A2DP Source
        ↓ SBC 编码 / Bluetooth Classic
Tivoo A2DP Sink
```

AUX 与 A2DP 复用同一上层 PCM 接口，具体采用哪种输出后端由固件配置决定。

## 8. NAS 部署规划

NAS 运行 Home Assistant、AstrBot 和必要的 Linux 服务。具体 Docker Compose、环境变量、挂载路径、用户权限和网络模式需在确认 NAS 实际部署环境后编写。

规划目录：

- `deploy/nas/compose/`：HA、AstrBot 和辅助服务的 Compose 文件。
- `deploy/nas/scripts/`：安装、更新、备份、恢复、健康检查等脚本。
- `deploy/nas/config/`：示例配置和环境变量模板，不存放真实密钥。
- `services/tivoo_gateway/`：Python 图像处理、文件传输及其他必要的 Tivoo 辅助服务；语音 Pipeline 由 HA Assist 原生管理，不另设通用音频 Gateway。
- `services/audio/`：音频格式转换、测试和诊断工具。

密钥、API Token、Wi-Fi 密码和真实 NAS 路径不提交到版本库。使用独立的本地环境文件，并提供不含秘密的示例模板。

## 9. 项目目录

```text
Tivoo-AI-Assistant/
├── README.md
├── docs/                         # 架构、协议、决策和测试记录
├── deploy/
│   └── nas/
│       ├── compose/              # NAS 容器部署文件
│       ├── scripts/              # Linux 部署和维护脚本
│       └── config/               # 配置模板，不含真实密钥
├── homeassistant/
│   ├── custom_components/
│   │   ├── astrbot/              # P3：AstrBot Conversation Agent（当前已完成 Config Flow 基线）
│   │   └── tivoo/                # Tivoo 自定义集成
│   ├── blueprints/
│   │   └── automation/           # 自动化蓝图
│   └── scripts/                  # HA 脚本示例
├── astrbot/
│   └── plugins/
│       └── astrbot_tivoo_bridge/ # AstrBot 与 HA 的主动交互插件
├── esp32/
│   ├── firmware/
│   │   ├── main/                 # 固件入口
│   │   └── components/           # 蓝牙、音频、AFE VAD、网络等组件
│   └── tests/                    # 硬件与协议测试
├── services/
│   ├── tivoo_gateway/            # Ubuntu/NAS 侧 Tivoo 服务
│   └── audio/                    # 音频测试和处理
├── benchmarks/
│   └── voice/
│       ├── stt/                   # NAS 与 ARM Ubuntu 的 STT 测试
│       └── tts/                   # NAS TTS 测试脚本、结果与试听样本
├── tts-benchmark-matcha-melo/    # ARM Ubuntu 的 Matcha / MeloTTS 完整测试
└── tests/                        # 跨模块集成测试
```

### HA 自定义集成本地测试

在 Ubuntu 开发机使用与 HA Core 2026.11.0 匹配的测试环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements_test.txt
./scripts/test-ha.sh
```

测试仅从 `tests/` 收集；NAS 上的语音基准脚本不属于 pytest 单元测试。

## 10. 实施顺序

按可验证的闭环逐步推进，不一次性开发所有模块。

| 阶段 | 工作 | 验收目标 |
|---|---|---|
| P0 | 核实 NAS 运行环境、网络、存储路径 | 明确容器和脚本部署方式 |
| P1 | NAS 部署 HA、AstrBot | 两个服务稳定运行 |
| P2 | AstrBot 云端模型、人格和会话 | 文本对话正常，统一使用指定人格 |
| P3 | HA AstrBot Conversation Agent（HTTP OpenAPI、单用户会话映射、SSE → ChatLog） | HA Assist 接收 STT 文本后调用 AstrBot；24 小时活动会话可跨 HA 重启复用；逐段写入 ChatLog 并返回标准 ConversationResult |
| P4 | HA MCP Server 暴露 Tivoo/设备工具，AstrBot 调用 | AI 能通过 MCP 控制 HA 设备 |
| P5 | ESP32 最小固件与 Tivoo SPP | 能通过 HA 控制 Tivoo 屏幕 |
| P6 | ESP32 ↔ HA 双向通信层（TCP 7777/7778 + HTTP 资源请求） | HA 可通过 7777 控制屏幕并接收 SPP 返回数据；通过 7778 获取设备状态、接收麦克风 PCM、发送 TTS URL；ESP32 再通过 HTTP GET 获取 TTS/其他指定音频资源 |
| P7 | I2S 麦克风采集、ESP-SR AFE VAD、HA 中文 Wake Word Provider、STT 与 AstrBot Conversation Agent | 空闲时不上传音频；人声触发后由 HA 识别唤醒词，命中后完成识别并进入 AstrBot |
| P8 | I2S TX + 外部 DAC → AUX TTS 输出；完成 ESP32 端到端并发联调 | AI 回复通过 Tivoo AUX 播放；验证 ESP32 获取/解码、I²S 输出与 SPP 控制并行运行稳定；Tivoo 端 AUX + SPP 已实测通过；内置 DAC 仅作对照测试 |
| P9 | AstrBot 表情工具与主动对话 | AI 能根据情绪显示表情，并主动播报 |
| P10 | I2S RX、I2S TX/DAC、SPP 与 Wi-Fi 并发测试；另测备用 A2DP | 连续运行稳定、无明显音频断流，SPP 控制及时响应 |

## 11. STT / TTS 实测结果

本节汇总 NAS 与 ARM Ubuntu 上已经完成的语音识别和语音合成测试。详细测试脚本、逐次数据、日志、模型来源和 WAV 样本保存在链接的测试目录中。

### 11.1 语音识别（STT）

使用同一份 sherpa-onnx Paraformer zh-small INT8（2024-03-09）模型和同一批官方测试 WAV，分别在 Synology NAS 和 ARM Ubuntu 上运行。每段音频先 warm-up 一次，再测量 5 次并取中位数。RTF = 推理耗时 / 音频时长。

| 设备 | 线程 | 0.wav：5.03s | 1.wav：5.15s | 2-zh-en.wav：8.10s | 模型加载 | 峰值 RSS |
|---|---:|---:|---:|---:|---:|---:|
| NAS DS920 | 1 | 0.651s / 0.129 | 0.659s / 0.128 | 0.998s / 0.123 | 2.865s | 170.4 MB |
| NAS DS920 | 2 | 0.447s / 0.089 | 0.462s / 0.090 | 0.736s / 0.091 | 2.839s | 170.0 MB |
| ARM Ubuntu | 1 | 0.134s / 0.0266 | 0.139s / 0.0270 | 0.214s / 0.0264 | 1.434s | 186.6 MB |
| ARM Ubuntu | 2 | 0.104s / 0.0206 | 0.103s / 0.0199 | 0.149s / 0.0184 | 1.481s | 186.9 MB |
| ARM Ubuntu | 4 | 0.068s / 0.0134 | 0.068s / 0.0132 | 0.101s / 0.0125 | 1.497s | 186.1 MB |

表中每个音频单元格为“中位识别耗时 / RTF”。NAS 为 Intel Celeron 1005M、2 逻辑 CPU、约 3.89 GiB RAM；ARM Ubuntu 为 Cortex-A77、8 逻辑 CPU、10 GiB RAM。NAS 测试容器内存上限为 1 GiB；ARM Ubuntu 使用原生 ARM64 Python wheel，无 Docker。

同一批测试音频在两台设备上得到相同转写文本。ARM Ubuntu 4 线程约为 74–80 倍实时；NAS 2 线程约为 11 倍实时。这里测的是离线整段识别耗时，不是流式首字延迟。测试音频来自模型官方样例，不是 Tivoo 麦克风录音，也没有人工真值用于计算 CER/WER。

详细数据、复现脚本和日志：
- [STT 对比报告](benchmarks/voice/stt/STT_COMPARISON.md)
- [STT 测试目录与运行说明](benchmarks/voice/stt/README.md)
- [NAS 原始测试日志](benchmarks/voice/stt/nas/nas_stt_benchmark_20261107.log)
- [ARM Ubuntu 逐次 JSONL 结果](benchmarks/voice/stt/arm-ubuntu/results.jsonl)

### 11.2 语音合成（TTS）

**ARM Ubuntu：Matcha Baker 与 MeloTTS**

同一段中文文本，在 ARM Ubuntu 原生 CPU 环境中分别测试 1、2、4 线程。下表是每个进程第二次生成（warm）的数据。

| 模型 | 线程 | 输出音频时长 | 合成耗时 | RTF | 输出采样率 | 模型加载 | 峰值 RSS |
|---|---:|---:|---:|---:|---:|---:|---:|
| Matcha Baker | 1 | 11.985s | 2.985s | 0.249 | 22.05 kHz | 2.120s | 248.5 MB |
| Matcha Baker | 2 | 12.010s | 1.864s | 0.155 | 22.05 kHz | 2.119s | 246.8 MB |
| Matcha Baker | 4 | 11.979s | 1.309s | 0.109 | 22.05 kHz | 2.208s | 248.3 MB |
| MeloTTS（full precision） | 1 | 11.047s | 22.221s | 2.012 | 44.1 kHz | 3.605s | 414.2 MB |
| MeloTTS（full precision） | 2 | 11.214s | 13.122s | 1.170 | 44.1 kHz | 3.754s | 414.9 MB |
| MeloTTS（full precision） | 4 | 11.233s | 8.988s | 0.800 | 44.1 kHz | 3.765s | 414.9 MB |

当前 ARM Ubuntu 测试中，Matcha Baker 4 线程合成 12 秒左右语音约需 1.31 秒，具备较大实时余量。MeloTTS 只有 4 线程时 RTF 低于 1，性能余量有限。MeloTTS 测试实际使用 model.onnx 完整精度；随包的 model.int8.onnx 是 133 字节 Git LFS pointer，并非可运行的量化模型权重。两种模型包在本次测试中都只有一个 speaker。主观音质没有自动评分，需要试听 WAV 样本判断。

完整 ARM Ubuntu 测试报告、原始 CSV/JSONL、模型文件、日志和试听音频：
[Matcha Baker / MeloTTS 测试目录](tts-benchmark-matcha-melo/README.md)

**NAS：多种 TTS 模型初步筛选**

NAS 为 Intel Celeron 1005M、2 逻辑 CPU；以下为 NAS Docker CPU 测试结果，模型和测试文本并不完全相同，因此用于筛选，不应把不同模型间的 RTF 当作音质排名。

| 模型 | 线程 / 音色 | 输出采样率 | 音频时长 | 合成耗时 | RTF |
|---|---|---:|---:|---:|---:|
| VITS AISHELL3 | 1 / sid 21 | 8 kHz | 5.929s | 2.193s | 0.370 |
| VITS AISHELL3 | 1 / sid 41 | 8 kHz | 5.857s | 2.020s | 0.345 |
| VITS AISHELL3 | 1 / sid 45 | 8 kHz | 5.330s | 1.881s | 0.353 |
| VITS AISHELL3 | 2 / sid 21 | 8 kHz | 5.929s | 1.427s | 0.241 |
| VITS AISHELL3 | 2 / sid 41 | 8 kHz | 5.857s | 1.372s | 0.234 |
| VITS AISHELL3 | 2 / sid 45 | 8 kHz | 5.330s | 1.574s | 0.295 |
| VITS AISHELL3 | 2 / 长句 | 8 kHz | 10.361s | 2.305s | 0.222 |
| Kokoro INT8 | 1 / zf_001 | 24 kHz | 13.114s | 80.938s | 6.172 |
| Kokoro INT8 | 1 / zm_009 | 24 kHz | 12.866s | 80.371s | 6.247 |
| Matcha Baker | 1 | 22.05 kHz | 11.985s | 7.171s | 0.598 |
| MeloTTS 中文 | 1 | 44.1 kHz | 11.229s | 55.336s | 4.928 |
| ZipVoice Distill INT8 | 2 / 短句 | 24 kHz | 2.517s | 48.051s | 19.088 |

AISHELL3 含 174 个可选 speaker，速度表现最好，但输出为 8 kHz，带宽有限。NAS Matcha Baker 单线程也达到 RTF 0.598，输出为 22.05 kHz。Kokoro、MeloTTS 和本次 ZipVoice 配置没有达到实时生成速度。NAS 测试的 AISHELL3 短句样本、其他模型音频和 NAS 原始 Python 脚本均已保留。

详细 NAS TTS 结果和试听样本：
- [NAS TTS 测试报告](benchmarks/voice/tts/nas/README.md)
- [NAS TTS 脚本](benchmarks/voice/tts/nas/scripts/)
- [NAS TTS WAV 样本](benchmarks/voice/tts/nas/samples/)
- [NAS TTS 模型权重](benchmarks/voice/tts/nas/models/)
- [NAS TTS 模型来源与 SHA-256](benchmarks/voice/tts/nas/MODEL_SOURCES.md)

NAS 的 AISHELL3、Kokoro、ZipVoice 和 Vocos 24 kHz 权重已完整归档。NAS 与 ARM Ubuntu 使用的 Matcha Baker、MeloTTS、Vocos 22 kHz 核心模型文件已逐一计算 SHA-256，确认相同，因此共用 tts-benchmark-matcha-melo/models/ 中的文件，不重复保存。

### 11.3 对当前项目的阶段性判断

- **STT：** Paraformer zh-small INT8 在 NAS 和 ARM Ubuntu 上都远快于实时需求。当前离线整段识别方案的推理耗时足够低，后续重点是 Tivoo I2S 采音质量、音频格式适配、端点检测、噪声和识别准确率。
- **TTS：** ARM Ubuntu 首选 Matcha Baker 作为第一版候选；其 RTF 有较大余量，适合后续实现分句合成、音频队列和边播放边生成。AISHELL3 可作为 NAS 侧多音色备选，但 8 kHz 输出必须经过实际试听评估。
- **测试边界：** 模型官方样例与合成测试不能替代 INMP441 在 Tivoo 内部预定安装位置的真实采音、Tivoo AUX/DAC 模拟输出链路（以及备用 A2DP 链路）和实际对话延迟测试。尚未完成的项目不应视为已验收。

后续实施时应将模型推理与硬件传输分开测量：STT 记录从音频结束到文本可用的时间；TTS 记录首段音频产生时间、队列水位和播放期间是否断流。

### 11.4 HA Wyoming / Provider 接入与流式回馈判断

端到端组件职责、STT/TTS 处理时序、分句策略、实施顺序和验收条件见独立的 [STT/TTS 链路规格](docs/superpowers/specs/2026-11-09-stt-tts-end-to-end-pipeline-spec.md)。本节保留 HA 2026.11.0 与 Wyoming 的源码核对结论，避免重复展开。

**STT：现有 Paraformer 可以直接适配。** HA Core 2026.11.0 的 Wyoming STT Provider 按 16 kHz、16-bit、mono PCM 接收 AudioStart/AudioChunk，并在 AudioStop 后取得 Transcript；这与当前 ESP32 音频格式一致。现有 sherpa-onnx Paraformer zh-small INT8 是 OfflineRecognizer，适配层只需接收/缓存音频块，在语句结束后执行 decode_stream 并返回最终文本。它不会在语音尚未结束时持续输出增量转写，这符合当前 VAD/端点检测后再识别的规划。直接实现 HA SpeechToTextEntity 也可行，输入同样是异步音频块。

**TTS：模型可复用，流式文本输入需要适配。** HA Core 2026.11.0 的 Wyoming TTS Provider 支持 SynthesizeStart / SynthesizeChunk / SynthesizeStop；服务端在 Info.TtsProgram 中声明 supports_synthesize_streaming 后，HA 才会逐段发送文本，并并行接收 AudioStart / AudioChunk。直接 Provider 的对应接口是 TextToSpeechEntity.async_stream_tts_audio() 与 async_supports_streaming_input()。

当前 Matcha Baker、MeloTTS 使用 sherpa-onnx OfflineTts。generate(text, callback=...) 的 text 参数仍然要求一段完整文本；callback 可以在该段文本的音频生成过程中逐块提供 PCM。因此它们不具备任意 token 级的在线文本输入能力，但可以采用句子/分句缓冲适配：持续接收 AstrBot 文本，遇到完整句子边界后调用 generate()，随后立即输出该句的音频块，同时继续接收后续文本。这样能够让 TTS 与 LLM 后续文本生成重叠，不必等整段回答结束。分句边界、首段延迟及播放缓冲欠载仍需实测。

**可复用实现：** [ptbsare/sherpa-onnx-tts-stt](https://github.com/ptbsare/sherpa-onnx-tts-stt) 已支持本项目使用的 Paraformer zh-small 2024-03-09 和 Matcha Baker，并提供 Wyoming 服务。其现有 STT 采用整段离线识别，适合直接复用；但其 TTS 当前只处理完整 Synthesize 请求，且未声明 supports_synthesize_streaming，生成完整音频后才分块发送。因此它是可复用的基础，不是已经具备流式输入的成品。建议以它为基础扩展 Wyoming TTS 流式事件处理，并固定 sherpa-onnx 版本为本项目已测的 2.0.1，避免构建时自动升级造成行为变化。

流式适配有两个协议细节必须处理：HA Core 2026.11.0 会发送 `SynthesizeStart`、多个 `SynthesizeChunk`，结束时又额外发送一条完整文本 `Synthesize`（向旧服务兼容），最后发送 `SynthesizeStop`。新服务必须识别当前连接已处于流式会话，不能把兼容用的完整文本再合成一次；流式音频输出在 `AudioStart`/`AudioChunk` 后必须发送 `SynthesizeStopped` 结束响应，不能只发送普通 `AudioStop`，因为 HA 的流式接收器等待的是 `SynthesizeStopped`。

**HA 端的必要条件：** 仅让 TTS 服务支持流式还不够。AstrBot Conversation Agent 必须把 SSE 文本增量写入 HA ChatLog，并声明 supports_streaming；TTS Provider 也必须真实支持 streaming input。两端均满足时，HA 2026.11.0 的 run-start 会提供 TTS URL 与 stream_response=true；回答达到内部启动阈值后，intent-progress 会发出 tts_start_streaming。Tivoo Satellite 应在该事件发生时使用 run-start 保存的 URL 提前通知 ESP32 下载；短回答或非流式情况则在 tts-end 后通知。HA 的 TTS Proxy 会逐块写出 HTTP 响应，设备可边下载边播放。tts-end 不是播放完成事件，最终仍以 ESP32 的 TTS_STATE 和 tts_response_finished() 完成播报生命周期。

**本项目选择：** 首期使用 Wyoming，而不是在 Tivoo HA 集成内再实现一套模型 Provider。Paraformer 复用现有整段识别；Matcha Baker 作为 NAS 首选 TTS，并为其 Wyoming 服务增加分句输入和音频块输出。ARM Ubuntu 的 Matcha RTF 0.109、NAS 的 Matcha RTF 0.598 说明有继续验证实时播放的价值，但都不是首段延迟或完整流式联调结果。当前尚未完成流式适配和 Tivoo 实机端到端验收。

实现参考：
- [HA Core 2026.11.0：Wyoming STT](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/wyoming/stt.py)
- [HA Core 2026.11.0：Wyoming TTS](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/wyoming/tts.py)
- [HA Core 2026.11.0：Assist Pipeline](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/assist_pipeline/pipeline.py)
- [HA Core 2026.11.0：TTS 流与 HTTP Proxy](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/tts/__init__.py)
- [sherpa-onnx 2.0.1：OfflineTts Python callback](https://github.com/k2-fsa/sherpa-onnx/blob/v2.0.1/sherpa-onnx/python/csrc/offline-tts.cc)
- [ptbsare：Wyoming 服务实现](https://github.com/ptbsare/sherpa-onnx-tts-stt/blob/main/run.py)

## 12. 已有可复用成果

现有工作区 `BluetoothBridgeTest` 中已经有可复用的研究和代码，不直接把它当成最终项目目录：

- `tivoo/`：Tivoo Python 显示协议、图片和动画编码、命令构建。
- `bluetooth_bridge.py`：当前 Android Bluetooth Bridge 的 Python HTTP 客户端；最终 ESP32 路线不再依赖 Android Bridge。
- `esp32-divoom/`：已有 ESP32 Divoom C++/SPP 实现，可研究和复用其中的协议与 SPP 代码。

上游参考：
- [Tivoo Control](https://github.com/solar2ain/tivoo-control)
- [ESP32 Divoom](https://github.com/d03n3rfr1tz3/esp32-divoom)
- [Espressif ESP-SR](https://github.com/espressif/esp-sr)

## 13. 当前边界与未确认事项

以下内容不能仅凭 API 文档认定已经实现，必须实机测试：

- ESP32 同时运行 I2S RX、ESP-SR AFE VAD、I2S TX/DAC、SPP 和 Wi-Fi 的资源与稳定性。BLE GATT 不属于本项目运行要求。
- Tivoo AUX 播放期间的设备端 SPP 控制并发：已于 2026-11-08 实测通过（AUX 播放外部音频、保持 `Tivoo-light` BLE 连接，并通过 SPP 正常发送指令显示图形）；该 BLE 连接不是固件必需控制通道。尚未验证的是 ESP32 固件在 Wi-Fi/I²S/SPP 同时工作时的稳定性。
- I2S 采集与 DAC 播放并发时，音频缓冲是否欠载或溢出；若启用备用 A2DP，再验证 A2DP 与 Wi-Fi/SPP 的并发稳定性。
- INMP441 的 I2S 接线、时钟关系、PCM 格式，以及安装到 Tivoo 机内后的实际采音质量。
- 中文 Wake Word Provider 的 Wyoming/自定义集成适配，以及真实 Tivoo 收音条件下的唤醒词误触发率和识别距离。
- Tivoo 内置倒计时是否有可读取的剩余时间或完成事件。
- 屏幕命令是否有设备端确认，以及动画数据的实际最大传输速度。
- HA Tivoo 集成仍需实现 ESP32 到 HA 的设备音频传输层（连接认证、音频分帧、会话结束和断线处理）；`AssistSatelliteEntity` 负责接管 Pipeline 生命周期，但不会自动提供 ESP32 的网络传输协议。
- STT/TTS 的 HA 接入方式和流式边界已核实：Paraformer 可通过 Wyoming 接收音频块并在 AudioStop 后执行离线识别；Matcha Baker 可复用，但现有测试只覆盖整段合成。HA 2026.11.0 支持 Wyoming/Provider 流式 TTS；要实现 AstrBot 边生成、Tivoo 边播放，仍需让 AstrBot Conversation Agent 输出 HA ChatLog 增量，并扩展 Wyoming TTS 服务按句接收文本、逐块输出音频。具体判断见 11.4。
- ESP32 获取 TTS 音频 URL 时的 HA 地址可达性、Token 传递、实际 MIME/编码及解码资源占用。
- 外部 I2S DAC 或 ESP32 内置 DAC 输出的线路电平、底噪、失真、交流耦合和 Tivoo AUX 输入兼容性。
- AUX 音频播放与 SPP 命令接收：Tivoo 设备端并发已通过上述实测；仍需在自制 ESP32 固件接入后确认完整链路及长时间运行稳定性。AUX 保持首选方案，A2DP 作为备用输出路线。

项目文档中的接口名称是规划接口，不代表相应固件或集成代码已完成。

---

## 官方技术文档

- [Home Assistant Assist Pipeline 开发文档](https://developers.home-assistant.io/docs/voice/pipelines)
- [Home Assistant Assist Satellite Entity 开发文档](https://developers.home-assistant.io/docs/core/entity/assist-satellite/)
- [Home Assistant Conversation Entity 开发文档](https://developers.home-assistant.io/docs/core/entity/conversation/)
- [Home Assistant Wake Word 机制](https://www.home-assistant.io/voice_control/about_wake_word)
- [Home Assistant openWakeWord 接入](https://www.home-assistant.io/voice_control/install_wake_word_add_on/)
- [HA Core 2026.11.0：Assist Pipeline WebSocket API](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/assist_pipeline/websocket_api.py)
- [HA Core 2026.11.0：Assist Pipeline 执行逻辑](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/assist_pipeline/pipeline.py)
- [HA Core 2026.11.0：Pipeline 阶段与设置模型](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/assist_pipeline/models.py)
- [AstrBot HTTP OpenAPI / SSE](https://docs.astrbot.app/dev/openapi.html)
- [ESP-SR AFE / VAD for ESP32](https://docs.espressif.com/projects/esp-sr/en/latest/esp32/audio_front_end/README.html)
- [sherpa-onnx 中文/英文 KWS 模型](https://github.com/k2-fsa/sherpa-onnx/tree/master/docs/source/onnx/kws/pretrained_models)
- [ESP-IDF Bluetooth](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-guides/bluetooth.html)
