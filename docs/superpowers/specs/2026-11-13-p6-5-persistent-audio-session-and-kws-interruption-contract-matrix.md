# P6.5 常驻音频会话与 KWS 确认打断合同矩阵

> 日期：2026-11-13  
> 分支：`feature/p6-5-ha-cancellation-preflight`  
> 状态：**P6.5 b6+ 实施合同，自动化已回归，现场声学待验收**（[b11 逐项证据](../reports/2026-11-13-p6-5b11-end-to-end-acoustic-acceptance.md)）\
> 适用：ESP32-WROVER-E、Home Assistant Core 2026.11.0、AstrBot 4.29.4、Sherpa Wyoming 现有 P7A 服务  
> 分批计划：[P6.5 b6 起分批执行计划](../plans/2026-11-13-p6-5-batch-execution-plan-from-b6.md)

## 1. 目的与权威关系

本矩阵将 P6.5 从 b0–b5 的取消链路前置调查扩展为可实机运行的常驻采集、跨 Pipeline 音频上传会话、KWS 确认打断和全双工 DAC 音频闭环。b0–b5 已完成的是调查、测试与责任边界记录，不代表本矩阵中的生产能力已经实现。

既有权威合同继续有效：

1. [P6 ESP32 ↔ HA 双向通信合同矩阵](2026-11-12-p6-esp32-ha-bidirectional-contract-matrix.md)：TVIO v1、TCP 7777/7778、MIC/TTS 消息、4 KiB MIC_PCM 上限及连接行为。
2. [ESP32 ↔ HA 双向通信层规格](2026-11-09-esp32-ha-bidirectional-communication-design.md)：WROVER-E 硬件、I2S、M/R AEC 输入、16 kHz 网络 PCM、DAC/AUX 输出链。**本矩阵替换其中“ESP32 VAD 检测到人声即可停止播放并发送 AUDIO_INTERRUPTED”的旧策略。**
3. [P7A Sherpa Wyoming 合同矩阵](2026-11-10-p7a-sherpa-wyoming-contract-matrix.md)：中文 KWS、Paraformer STT、Matcha TTS、Wyoming Provider 与模型部署保持不变。
4. [STT/TTS 端到端规格](2026-11-09-stt-tts-end-to-end-pipeline-spec.md)：HA Assist Pipeline → KWS/STT → AstrBot → TTS 业务顺序不变。
5. [P3 AstrBot Conversation 合同矩阵](2026-11-09-p3-astrbot-conversation-contract-matrix.md)：稳定 session_id、SSE reader、同 owner session Stop 和串行化约束。
6. [AstrBot HTTP OpenAPI 推理取消与 SSE 终止规格](2026-11-13-astrbot-http-sse-inference-cancellation-spec.md)：Stop 身份、请求顺序、complete/end 语义和真实 API 测试边界。
7. [P6.5 b0–b5 前置验证报告](../reports/2026-11-11-ha-cancellation-preflight-report.md)：HA TTSCache producer、HTTP consumer、Wyoming writer 和 P7A request 的 GAP 证据。

冲突时，本矩阵只覆盖新增音频生命周期、打断判定和 P6.5 新增消息；其他既有字段、端口、格式和服务仍以对应上位合同为准。

## 2. 总体决策

### 2.1 VAD 不再拥有播放停止权

**唯一采用：ESP32 VAD 负责语音活动门控/提示；NAS 侧现有 Sherpa KWS 的有效 Detection 才能确认播放期间的语音打断。**

ESP-SR AFE VAD 表示当前帧是否有人声活动，不判断讲话者身份、讲话内容或用户是否有撤回指令的意图。AEC 使用播放参考抑制本机扬声器回声，也不等于声源分离或说话人识别。当前 WROVER-E 经典 ESP32 固件固定使用 esp-sr 2.6.1、AFE_TYPE_SR / AEC_MODE_SR_HIGH_PERF；不得套用其他 target 的 FD 非线性 AEC 能力。

因此：

- VAD 可以启动空闲时的首次上传。
- VAD 可以发送 MIC_ACTIVITY，供播放结束后的 follow-up 窗口判断是否有新语音。
- **VAD 单独检测到人声时，绝不能发送 AUDIO_STOP、AUDIO_INTERRUPTED，不能取消 Pipeline、AstrBot 或 TTS，也不能停止 DAC。**
- 播放、AstrBot 处理和 SSE 输出期间保持 RX/AEC/VAD；AEC 后 PCM 上传 HA，由 HA 使用现有 KWS Provider 检测配置的唤醒词。只有有效 Detection(tivoo-wake) 才触发打断。
- KWS 未命中时继续原播放和对话；背景人声、电视人声或环境噪声不因 VAD 活动本身打断。
- AEC 是回声抑制，不是环境人声消除；KWS 也不是声纹验证。若背景人声清晰说出相同唤醒词，现有 KWS 仍可能命中。项目不承诺识别讲话者是否为设备主人。

实机负样本必须覆盖环境人声、电视/音乐人声、TTS 本身、TTS 内容包含唤醒词、播放音量变化和房间回声；不得通过启用 VAD-only stop 来绕开这些问题。

### 2.2 保留现有 KWS / STT / TTS 推理链

- KWS 使用 HA 原生 Wyoming Wake Word Provider 和 `services/sherpa_wyoming/providers/wake.py`，不在 ESP32 增加 WakeNet，不更换模型。
- STT 继续使用 P7A Paraformer Wyoming Provider；对话继续使用 P3 AstrBot HTTP OpenAPI/SSE。
- TTS 继续使用 P7A Matcha、HA TTS Proxy、既有 TTS_PLAY 元数据通知和 ESP32 单次 HTTP GET。
- 当前 TTS 传输已经是“一次 TCP TTS_PLAY + 一次 HTTP GET + 响应体持续流式读取”，不是多次 GET。P6.5 不增加 TCP 原始 PCM 推送协议。
- ESP32 复用已锁定的 esp_audio_codec 2.6.2 和 esp_audio_effects 1.4.5 做 MP3 解码/SRC；不从零实现通用 MP3 解码器。

### 2.3 TTS 格式证据与生产输出约定

- 容器代码 `services/sherpa_wyoming/providers/tts.py` 的普通/流式输出均为 Wyoming AudioStart/AudioChunk，负载是 22,050 Hz / Mono / S16LE PCM，不是容器直接编码 MP3。
- HA Core 2026.11.0 `components/wyoming/tts.py` 返回 `TTSAudioResponse("wav", data_gen())`；`components/tts/__init__.py` 的默认格式是 mp3，按 preferred_format 判断并通过 `_async_convert_audio()` 转码。Satellite 基类把 tts_options 传入 Pipeline 的 tts_audio_output。
- [生产两轮验收](../reports/2026-11-10-ha-assist-astrbot-stt-tts-e2e-report.md) §3 已验证 Proxy 返回 audio/mpeg、FFprobe/FFmpeg 确认 MP3。b1/b3/b4 测试中的 `P65ControlSatellite` 显式设置 preferred_format=wav（`tests/homeassistant/test_assist_pipeline_tts_cancellation.py`），其 WAV 结果不是生产默认格式证据。
- b7 生产 Tivoo Satellite 显式设置 preferred_format=mp3；b10 维持流式 MP3 解码，其他 MIME 明确报格式不支持，不悄悄按 MP3 解码，也不新增无实际需求的 WAV 解码器。
- b6 必须验证生产格式下的真实 HA WAV→MP3 转码路径：除现有 owner 外，覆盖转换 generator、输入 writer task、FFmpeg process/pipes 的取消与等待。现有 WAV 用例保留作下游 owner 对照，不能替代 MP3 生产路径验收。

## 3. 时间窗口与语音交互状态

计时器必须按用途分离，不能把 HA ChatSession 清理、Assist Pipeline 整体超时或 AstrBot 24 小时 session TTL 当成语音助手聆听时间。

| 名称 | 首期值 | 起算点与行为 |
|---|---:|---|
| 首次 KWS 候选静音超时 | 3 秒 | 首次 VAD speech_start 开始上传后，HA 仍在 WAKE_WORD 阶段且未 Detection；从最近一次 MIC_ACTIVITY speech_end 起计时，有新 speech_start 则重置。由项目会话协调器取消未命中的 Pipeline 并结束上传；不是 HA 默认值 |
| 首次 KWS 候选总上限 | 15 秒 | 从首次 speech_start 起算的硬上限，不因环境中持续讲话而无限续期；到期仍未 Detection 则结束候选上传。此值是项目隐私/资源策略，不是 HA Pipeline timeout |
| 唤醒后等待用户开始指令 | 5 秒 | 首次唤醒从 HA 收到 KWS Detection 开始计时；打断交接从新轮 STT_START 开始计时（旧轮清理等待不计入）；新轮优先消费 handoff。HA 发出 STT_VAD_START（VoiceCommandSegmenter 已检测到命令语音）时取消。超时仍无 STT_VAD_START 则取消空 STT turn，不等 15 秒 segmenter 兜底；唤醒词后连续说命令仍走同一 STT Pipeline |
| 命令起始语音 | 0.3 秒 | HA Core 2026.11.0 VoiceCommandSegmenter.speech_seconds 默认值；连续达到阈值后发出 STT_VAD_START，项目用该事件取消 5 秒空命令 watchdog |
| 最小命令段 | 1.0 秒 | VoiceCommandSegmenter.command_seconds 默认值；含起始语音累计，不是额外增加 1 秒 |
| 指令结束静音 | 0.7 秒 | 用户命令已开始后，HA VoiceCommandSegmenter.silence_seconds 默认值；P7A 声明 requires_external_vad=true，因此该 segmenter 会被使用 |
| 最大单轮语音分段时长 | 15 秒 | HA Core 2026.11.0 VoiceCommandSegmenter.timeout_seconds 默认值；与 Sherpa STT 自身 300 秒请求硬上限不同 |
| 回答后的 follow-up 窗口 | 8 秒 | 从设备调用/确认 tts_response_finished（即最后 PCM 已实际播放完成）开始。8 秒内 VAD speech_start 可启动免唤醒词 STT；超时后结束上传，后续必须再次说唤醒词 |
| 连续对话中的每轮窗口 | 8 秒 | 每轮 follow-up 回答实际播放完成后重新开始；不从 TTS 生成开始计时 |
| AstrBot session TTL | 24 小时 | 仍由 P3 管理，仅为对话上下文保留；不控制 ESP32 麦克风上传 |
| HA ChatSession cleanup | 5 分钟 | HA 内部会话资源清理常量；不作为本项目的语音 follow-up 窗口 |

选择依据：Google Home/Nest 智能音箱官方帮助明确约 8 秒；Google Assistant Pixel 手机约 10 秒，因此本项目采用更贴合音箱形态的 8 秒。2026 年 Google Gemini for Home 介绍了改进的 side-talk detection，但没有公开内部判定算法。Alexa Follow Up Mode 允许不重复唤醒词，但没有公开统一秒数，并明确承认可能把用户在房间里与他人讲话误认为 follow-up。OVOS hybrid listen 提供可配置窗口，示例为 45 秒，偏开放式连续监听，不适合本设备首期。3 秒 KWS 候选静音、15 秒候选总上限和 5 秒唤醒后命令起始窗口是本项目选择，不声称来自这些厂商。

**特别说明：** Google 设备的约 8/10 秒不是通用固定协议；Pixel 方案会使用语音及设备传感器信号，Gemini for Home 也另有 side-talk detection。Tivoo 目前没有这些厂商的辅助判定能力，因此采用保守边界：播放期间只能由 NAS KWS Detection 打断；TTS 播放结束后 8 秒窗口内的 VAD 仅可启动 STT，不能停止声音或取消任何活动回复。环境讲话可能导致无效 STT，这是短 follow-up 模式的已知限制。

### 3.1 状态与转移

- `IDLE_LOCAL`：本地 I2S RX/AEC/VAD 工作；不上传。首次 VAD speech_start 开启 MIC session，进入 `WAKE_WORD_WAIT`。
- `WAKE_WORD_WAIT`：上传 AEC PCM，HA 运行原有 WAKE_WORD Pipeline。项目协调器从 MIC_ACTIVITY speech_end 起累计 3 秒无新 speech_start；未 Detection 则取消 Pipeline 并回本地待机。首次 speech_start 起另有 15 秒硬上限，防止持续背景说话无限延长上传。
- `COMMAND_WAIT`：KWS 命中后继续同一 MIC session，HA 同一 Pipeline 进入 STT。AudioSessionCoordinator 首次唤醒从 Detection、打断交接从新轮 STT_START 开始 5 秒 watchdog；只要 HA 发出 STT_VAD_START 就取消 watchdog 并转为 `COMMAND_CAPTURE`。超时仍无 STT_VAD_START 时取消空 STT turn。
- `COMMAND_CAPTURE`：向现有 STT 输送同一 AEC PCM；按 HA 端点检测结束本轮 STT。
- `ASSIST_PROCESSING`：KWS 命中后进入 STT；Pipeline 发出 STT_START 时并行启动 side KWS watcher，STT 完成后继续保留该 watcher，覆盖 Intent/Conversation/SSE/TTS 阶段。VAD 活动只上传和观测。
- `PLAYBACK_ACTIVE`：设备正在播放。只有 NAS KWS Detection 可启动 interruption；VAD speech_start 不停止 DAC。
- `FOLLOWUP_WAIT`：关联 TTS 实际播放完成后，关闭 side KWS watcher，8 秒内等待 VAD speech_start；命中后从 STT 开新轮，不需要唤醒词。
- `IDLE_LOCAL`：8 秒到期或 follow-up 无有效语音后，停止网络上传，保持本地 RX/AEC/VAD。
- KWS 在 ASSIST_PROCESSING / PLAYBACK_ACTIVE 命中时，转入 `INTERRUPTION_HANDOFF`，先取消旧轮并保留新轮音频，再进入 `COMMAND_CAPTURE`。

一个 MIC 网络会话可以跨多个状态和 Pipeline run；Pipeline run 结束不代表 MIC 网络会话结束。

## 4. ESP32 常驻音频运行时

### 4.1 设备启动职责

音频硬件初始化成功后持续运行：
1. I2S RX + DMA 采集 INMP441。
2. 输入格式转换与 ESP-SR AFE AEC。
3. AFE VAD，设置 `vad_mute_playback=false`。
4. AEC 后 PCM 的短时预录环形缓冲。
5. 从音频输出管理器最终 TX PCM 生成与麦克风时间轴对齐的 16 kHz 播放参考 R；无播放时 R 为零样本。

常驻采集不等于持续上传。空闲只在 ESP32 本地监听；首次 VAD 触发后才建立 TCP 7778 网络 MIC session。

### 4.2 固定格式

| 层 | 合同 |
|---|---|
| I2S 全双工 | 同一经典 ESP32 I2S Controller；32 kHz、Stereo、32-bit Slot；RX/TX 共用 BCLK/WS |
| INMP441 M | 取左 Slot 有效 24-bit 样本，低通抗混叠、32→16 kHz 降采样和位深转换 |
| DAC R | 从最终送往 I2S TX 的 PCM 取参考；32→16 kHz 单声道，与 M 时间对齐 |
| AFE 输入 | M/R 交错；经典 ESP32 SR AEC High Performance；帧长从锁定 API 获取 |
| 唯一 AFE 输出 | 16 kHz / Mono / S16LE，VAD、预录、MIC_PCM、KWS、STT 共用 |
| MIC_PCM | 16 kHz / Mono / S16LE；保留现有 20 ms 帧与 4 KiB 单载荷上限 |
| DAC 输出 | 实际解码 PCM → 有状态 SRC 到 32 kHz → Stereo / 32-bit Slot → PCM5102 → AUX |

禁止让 VAD 使用未经过 AEC 的原始 M 音频，或让 KWS/STT 上传另一份处理结果。

### 4.3 AEC 参考边界

- R 必须来自音量、SRC、声道转换之后真正送往 I2S TX 的最终 PCM。
- RX/TX DMA 不保证逐样本同步；用有界参考环形缓冲补偿固定播放延迟。参考欠载、错位、丢帧必须计数。
- 停止播放后保留必要 TX 尾帧和房间衰减参考。
- 经典 ESP32 SR 模式不保证消除扬声器失真导致的全部非线性残余，也不能识别其他环境声源。
- 网络写入、KWS/STT、解码和 SRC 不得阻塞 I2S DMA；所有软件缓冲有界。

## 5. 持续网络音频会话

### 5.1 三类生命周期分离

| 对象 | 开始 | 结束 |
|---|---|---|
| 物理 I2S RX / AEC / VAD | ESP32 启动且音频初始化成功 | 设备关机/硬件故障 |
| 网络 MIC session | 空闲 VAD 首次 speech_start，发送 MIC_SESSION_START | 3 秒 KWS miss / 15 秒首次候选硬上限 / 5 秒 command-start timeout / 8 秒 follow-up expiry / 故障或 HA unload；活动 Pipeline/TTS 时不计上传空闲超时 |
| Assist Pipeline run | 首轮 WAKE_WORD、KWS-confirmed STT 或有效 follow-up STT | 单轮正常结束或被新的 KWS Detection 取消 |
| side KWS watcher | 首轮 STT_START 时 | KWS hit、进入 follow-up、上传 session 结束或 HA unload |
| TTS playback | TTS_PLAY 对应的音频资源开始获取/播放 | AUDIO_STATE completed/stopped/interrupted/failed |

### 5.2 首次唤醒和上传

1. 空闲本地监听；AFE VAD 首次检测人声后开启网络 MIC session。
2. 先发送 MIC_SESSION_START（trigger_source=idle_vad），随后立即发送 MIC_ACTIVITY（speech_start），再发 AEC 预录缓冲和实时 MIC_PCM，包括静音帧。HA 在接收活动事件前已经有对应 session。
3. HA 从 `PipelineStage.WAKE_WORD` 启动原有 Assist Pipeline / Sherpa KWS。
4. KWS miss：项目协调器从最近 MIC_ACTIVITY speech_end 起累计 3 秒；若无新 speech_start，取消 WAKE_WORD Pipeline 并结束本次网络 MIC session。首次 speech_start 后 15 秒仍未 Detection 也结束候选，ESP32 保留本地监听。
5. KWS hit：同一个 Pipeline 进入 STT，继续消费同一 MIC session；不停止上传、不新开 TCP MIC session。
6. KWS 命中后，WAKE_WORD Pipeline 自动进入 STT。AudioSessionCoordinator 从 Detection 起启动 5 秒 command-start watchdog；HA Pipeline 的 STT_VAD_START 事件代表 VoiceCommandSegmenter 已检测到至少 0.3 秒命令语音，收到后取消 watchdog。连续说话、停顿后说话都使用同一规则；5 秒内没有该事件则取消空 STT turn。
7. Pipeline 发出 STT_START 时立即启动独立 KWS watcher，与当前 STT Pipeline 并行消费同一 ingress；该 watcher 在 STT、Intent、Conversation、SSE、TTS 生成和 DAC 播放期间保持运行。

### 5.3 跨 Pipeline 分发

- TCP MIC ingress 与单轮 Pipeline consumer 解耦。一个 MIC session 持续跨多轮 Pipeline；RUN_END 不能自动触发 MIC_CAPTURE_STOP。
- HA ingress 统一顺序接收 MIC_PCM，再提供给当前 Pipeline 或 side KWS watcher；同一段 PCM 不得在两个主消费者之间重复或遗漏。
- 首次 WAKE_WORD 使用 HA 自身 KWS→STT 交接；side KWS 在 STT_START 后监听。side watcher 运行期间维护有界预录；命中后把预录、Provider queued_audio、尚未消费的 ingress 与后续 PCM 按 ingress index 连续交给新 STT，重叠只交付一次。不得等 Detection 回调到达才开始缓存。
- `providers/wake.py` 返回的 Detection.timestamp 是触发识别结果的 AudioChunk.timestamp，不是模型给出的精确唤醒词结束点。timestamp 只用于关联 ingress，不能据它硬切掉此前全部 PCM。HA `assist_pipeline/default_pipeline.py` 也支持检测前缓冲和 queued_audio；其 WakeWordSettings.audio_seconds_to_buffer 默认 0，不可声称默认已提供预录保护。
- side watcher 的检测前预录首期取 1 秒/32,000 bytes，属于本项目参数；b9 用“唤醒词紧接命令”和延迟 Detection 用例验证开头不丢失，b11 再按实际声学结果调校，不把该值当成上游保证。
- 预录与 Detection 到下一 STT subscription 接管音频的 handoff 总上限固定为 15 秒/480,000 bytes（16 kHz S16LE Mono，约 469 KiB），覆盖 P3 Stop 最长 10 秒的现有等待预算并留调度余量；HA 以 ingress index 合并预录及后续音频并去重。超过上限记录明确错误并终止该轮，不无限缓存或静默丢弃开头。
- 网络背压不得阻塞 ESP32 I2S DMA。P6 的 4 KiB MIC_PCM 载荷上限保持不变。

## 6. NAS KWS watcher 与确认打断

### 6.1 watcher 生命周期

- 首轮 Pipeline 的 WAKE_WORD 阶段由该 Pipeline 自身的 Wake Word Provider 监听，不重复启动 side watcher。
- 首轮 Pipeline 发出 STT_START 时，首次 WAKE_WORD 阶段已成功返回 Detection；AudioSessionCoordinator 此时启动独立 KWS watcher。Watcher 与当前 STT Pipeline 并行消费同一 MIC ingress，因而 STT 期间、Intent/Conversation、SSE、TTS 生成和 DAC 播放期间都能检测下一次唤醒词。
- Follow-up STT turn 发出 STT_START 时也启动 side KWS watcher，覆盖该轮 STT 和后续回复阶段。
- watcher 使用 HA 现有 WakeWordDetectionEntity 的公开 `async_process_audio_stream()` 和项目已配置 Wyoming KWS Provider；不自行重写 Wyoming wire protocol，不在 ESP32 增加模型。
- watcher 与 Pipeline task/queue 分离；覆盖 AstrBot 尚未返回 plain、SSE 正在输出、TTS 正在生成、HTTP 下载和 DAC 播放期间。
- 进入 FOLLOWUP_WAIT 后关闭 watcher；follow-up 由 8 秒窗口内的 VAD speech_start 启动 STT。

### 6.2 只有 Detection 才抢占

播放或 AI 处理期间，MIC_ACTIVITY speech_start 仅为活动观测，不发送 AUDIO_STOP、不取消 Pipeline、不调用 AstrBot Stop。

收到 `Detection(tivoo-wake)` 后，按一个 interrupt generation 幂等执行：
1. 原子标记旧 run interrupted，禁止旧 run 的迟到 Pipeline 事件、TTS_PLAY 和播放状态覆盖新 run。
2. 若有属于旧 run 的活动 playback_id，向 ESP32 发送匹配 expected_audio_id 的 AUDIO_STOP；没有活动播放时不发无关 stop。
3. 取消并 await 旧 `async_accept_pipeline_from_satellite()` caller，由 HA 基类完成 Pipeline task 取消。
4. P3 关闭旧 SSE reader，并按 AstrBot 取消规格对 owner 匹配 session Stop 一次；在旧 Stop / 清理完成前不对同一 session 并发发新 Chat。
5. 通过真实 owner 定向取消旧 TTS producer、text generator、HTTP consumer queue、Wyoming writer/TCP 和 P7A request/input/worker/callback。只删除 token、只关闭 GET 或只调用 tts_response_finished 都不算取消成功。
6. 保留 KWS Detection 前后对应的有界 AEC PCM handoff；旧轮收尾后从 `PipelineStage.STT` 启动新 Pipeline，不要求重复唤醒词。此新轮的 5 秒 command-start watchdog 从 STT_START 起算，先交付 handoff；旧轮 Stop 等待不触发空命令超时。
7. 新旧 turn 使用独立 generation/playback_id；旧 AUDIO_STATE 或 stop 不得影响新播放。

### 6.3 误触发边界

- 播放期间普通人声即使使 VAD 活动，也不停止输出；需经过现有 KWS 完整命中。
- AEC 参考对齐正确的本机 TTS 不应持续触发 KWS；实机需包含 TTS 文本含唤醒短语的负样本。
- 背景人员清晰说出完全相同的唤醒词仍可能命中；本项目不具备声纹/摄像头意图识别能力，不做此类保证。
- 若 KWS 假阳性来自本机 TTS，先检查最终 TX→R 对齐、AEC 残留和当前 KWS 模型阈值；不得退回 VAD-only stop。

## 7. Follow-up 窗口

- 回答后窗口从 ESP32 报告关联 TTS 的实际 completed 状态开始，不从 Pipeline tts-end、TTS URL 创建或 MP3 下载开始。
- 8 秒内首次 VAD speech_start 启动免唤醒词 STT；HA 为 Tivoo Satellite 的 ConversationResult 设置 continue_conversation=True，使下一轮继续路由到同一个 AstrBot Conversation Agent；普通非 Satellite 文字对话保持 False。设备不在播放期间因为 VAD 活动做任何停止动作。该窗口内环境人声可能启动一次无效 STT，但不能抢占活动播放（此时最后一段 TTS 已完成）。
- 一次 follow-up 开始后取消 8 秒 idle timer；下一轮回答实际播放完成后再打开新的 8 秒窗口。
- 8 秒内无 VAD speech_start，HA 停止 MIC 网络上传并回到本地监听；下一次对话需要重新说唤醒词。
- 无 TTS 文本/无播放的 turn，以 Satellite 明确完成响应状态作为窗口起点。
- Follow-up VAD 仅作输入门控，不是身份识别。若环境人声触发，仍可能启动 STT；通过短窗口、现有 VAD speech 门槛和 STT/Intent 结果处理空输入，不把该事件用于打断正在运行的回复。
- 不采用 HA 5 分钟 ChatSession cleanup 作为 follow-up 窗口；P3 的 AstrBot 24 小时 session TTL 不受影响。

## 8. TTS 下行与 DAC

- 保留 HA Pipeline 事件发送一次 TTS_PLAY，包含 playback_id、LAN 可达 URL 与 MIME。
- ESP32 对 playback_id 发起一次 HTTP GET，增量读取，不把整段音频放入 RAM。
- 通过已锁定音频组件流式解码 MP3，并按实际解码格式做有状态 SRC。
- 解码 PCM 转为 32 kHz / Stereo / 32-bit Slot，通过唯一 audio_output_manager 输出至 PCM5102 → AUX。
- 最终 TX PCM 另一路生成时间对齐的 AEC R 参考。
- audio_output_manager 是所有受控音源最终输出的唯一 owner；AUDIO_STOP 匹配 audio_id 后立即禁止新的 PCM 入队、清理 decoder/HTTP 与待播缓冲并停止 TX。
- 停止播放不停止 RX/AEC/VAD/MIC session。

## 9. 新增/扩展 TVIO 消息

| Type | 名称 | 方向 | Payload |
|---:|---|---|---|
| `0x24` | MIC_ACTIVITY | ESP32 → HA | JSON：session_id、state（speech_start/speech_end）、uptime_ms |

MIC_ACTIVITY 仅在 VAD 状态切换时发送，不按帧发送能量/置信度；只在有效 MIC session 里发送，与 MIC_PCM 共用 7778 TCP Sequence。它只代表人声活动，不表示 KWS 命中或用户意图。

- HELLO capability 新增 `mic_activity_events`；旧固件未声明 capability 时仍使用原 MIC 消息。
- 在 ASSIST_PROCESSING / PLAYBACK_ACTIVE，activity 不能启动第二个 STT 或取消旧 run。
- 在 FOLLOWUP_WAIT，speech_start 可启动 STT follow-up。
- 保留 MIC_SESSION_START 0x20、MIC_PCM 0x21、MIC_SESSION_END 0x22、MIC_CAPTURE_STOP 0x23、TTS_PLAY 0x30、AUDIO_STOP 0x31、AUDIO_STATE 0x32。
- AUDIO_INTERRUPTED 0x33 不再由 VAD-only 触发；NAS KWS 确认的中断由 HA 发送现有 AUDIO_STOP 表达。

## 10. 资源 owner 与禁止事项

| 资源/动作 | 唯一 owner | 必须完成 |
|---|---|---|
| I2S RX/AEC/VAD | ESP32 audio runtime | 开机常驻，独立于 MIC session 和 Pipeline |
| MIC 网络 session | HA AudioSessionCoordinator + ESP32 producer | 跨轮持续；仅到期/故障/unload 停止 |
| Pipeline caller | Tivoo Assist Satellite | 保存 handle、cancel/await 公开入口 |
| KWS watcher | AudioSessionCoordinator；推理由 HA Wake Word Provider/P7A | hit 或会话结束时关闭 iterator/Wyoming |
| AstrBot SSE/Stop | P3 astrbot | 关闭 reader，再 owner-matched Stop 一次 |
| TTS producer/generator/MP3 转码 | 实际创建资源的 owner | 单资源定向 cancel/await；包括转换 generator、writer、FFmpeg process/pipes |
| HTTP consumer queue | 当前 cache consumer | GET EOF/取消时移除自身登记 |
| Wyoming/P7A 请求 | 对应 TCP/request owner | EOF/取消后 writer、request、input、worker、callback 收尾 |
| 最终 PCM/I2S TX | ESP32 audio_output_manager | 所有播放源统一停止 |

禁止：
- 禁止 VAD 单独触发 AUDIO_STOP、Pipeline cancel 或 AstrBot Stop。
- 禁止每轮 RUN_END 自动发送 MIC_CAPTURE_STOP。
- 禁止只关闭 HTTP GET、删除 token 或调用 tts_response_finished 就声称 producer 已取消。
- 禁止 task 全局扫描、猜任务名、卸载整个 Wyoming Config Entry 或停止整个 HA/AstrBot 服务代替单轮取消。
- 禁止为了降低误触发而在播放期间关闭 RX/AEC/VAD。
- 禁止无依据增加 TCP 原始 PCM 推送协议或将整段 TTS 缓存进 ESP32 RAM。

## 11. 验收矩阵

| ID | 验收 | 必须结果 |
|---|---|---|
| P65-A01 | 常驻采集 | I2S RX/AEC/VAD 初始化并持续运行；IDLE 不发 MIC_PCM |
| P65-A02 | 首次 VAD 上传 | MIC_SESSION_START + AEC 预录；WAKE_WORD Pipeline；同一 MIC session 进入 STT |
| P65-A03 | wakeword miss | 最近 speech_end 后 3 秒无新 speech_start 或从首次 speech_start 起 15 秒候选硬上限，结束本轮与上传；本地 RX/AEC/VAD 不停 |
| P65-A04 | wakeword hit 后命令等待 | 首次唤醒从 Detection、打断交接从新轮 STT_START 起 5 秒内必须出现 STT_VAD_START；旧轮清理超过 5 秒时已有缓存命令仍能识别；连续讲话不增加等待，空命令被取消且不等 15 秒 VAD timeout |
| P65-A05 | STT endpoint | 验证 P7A requires_external_vad=true 确实使用 HA VoiceCommandSegmenter；默认 0.3 秒起始 speech、1.0 秒最小 command、0.7 秒 silence、15 秒 segmenter timeout；Sherpa 自身硬上限另为 300 秒 |
| P65-A06 | 跨 Pipeline session | 同一 MIC session 跨两轮以上 Pipeline；队列有界、顺序正确、无旧 PCM 串轮 |
| P65-A07 | partial SSE 取消 | AstrBot 已输出 plain 后 Stop 生效；reader 关闭、owner Stop 一次、无迟到 plain |
| P65-A08 | 活动 TTS 取消 | producer/generator/MP3 转码 writer/FFmpeg/consumer/Wyoming/P7A 全部退出，无迟到 PCM/TTS_PLAY |
| P65-A09 | HTTP GET 对照 | GET 单独断开只移除自身 consumer；Pipeline cancel 可定向停止该 run producer |
| P65-A10 | VAD 误触发防护 | 普通环境人声/电视/噪声的 VAD 活动不停止 TTS、不取消 Pipeline |
| P65-A11 | KWS 确认打断 | 活动期间真实 KWS Detection 后匹配 AUDIO_STOP、取消旧 run、新 STT 从 STT 开始 |
| P65-A12 | AstrBot/SSE 阶段打断 | KWS hit 在首个 plain 前、plain 后、TTS 前均可中断，不等待 TTS_START |
| P65-A13 | TTS 回声负样本 | 最终 TX→R 对齐时本机 TTS 不应持续触发 KWS；含唤醒词 TTS 单独记录 |
| P65-A14 | 全双工 DAC | DAC 播放期间 RX/AEC/VAD/MIC/KWS/7777 SPP 并行，RX 不重启 |
| P65-A15 | follow-up 窗口 | 播放完成后 8 秒内 speech_start 启动 STT；8 秒无输入后停止上传并要求再次唤醒 |
| P65-A16 | generation 隔离 | 旧 AUDIO_STATE/TTS_PLAY/stop 不影响新 turn/playback_id |

fake PCM、自动化测试、真实 NAS 联调、真实麦克风/DAC 声学验收必须分别记录；fake 不能替代声学验收。

## 12. 实现参考

- [ESP-SR AFE](https://docs.espressif.com/projects/esp-sr/en/latest/esp32/audio_front_end/README.html)：AEC/VAD 输入输出和 VAD 活动语义。
- [ESP-SR AEC](https://docs.espressif.com/projects/esp-sr/en/latest/esp32/acoustic_echo_cancellation/README.html)：SR 与 FD AEC 能力边界。
- [Home Assistant Assist Pipelines](https://developers.home-assistant.io/docs/voice/pipelines/)：Pipeline 生命周期和 audio buffer；HA Core 2026.11.0 的 WakeWordSettings.timeout 默认 None，3 秒候选静音 watchdog 是本项目协调器的显式策略。
- [Home Assistant Assist Satellite](https://developers.home-assistant.io/docs/core/entity/assist-satellite/)：Satellite 状态与真实播放完成回调。
- [Google smart speaker Continued Conversation](https://support.google.com/assistant/answer/9249169)：官方称音箱/屏幕回答后约 8 秒可继续提问。
- [Google Assistant Pixel Continued Conversation](https://support.google.com/assistant/answer/10004407)：官方称 Pixel 手机约 10 秒；并提及语音和传感器信号用于判断是否继续。
- [Google Gemini for Home Continued Conversation](https://blog.google/products-and-platforms/devices/how-to-use-gemini-continued-conversation/)：2026-04-21 官方称改进了 AI side-talk detection，减少将家庭闲聊误作指令；内部模型/判定过程没有公开，本项目不声称具备同等能力。
- [Amazon Alexa Follow Up Mode](https://digprjsurvey.amazon.com/csad/help/node/GX7EJ9WHEPYBV94J)：免重复唤醒词 follow-up 逻辑；[Alexa FAQ](https://digprjsurvey.amazon.com/csad/help/node/201602230) 明确提示可能将用户与房间内其他人讲话误认为 follow-up，未公开统一固定秒数。
- [OVOS Dinkum Listener](https://github.com/OpenVoiceOS/ovos-dinkum-listener)：hybrid listen 与 listen_timeout 配置参考；其 45 秒示例不作为本项目首期值。
- `esp32/firmware/main/idf_component.yml`：esp-sr 2.6.1、esp_audio_codec 2.6.2、esp_audio_effects 1.4.5。
- `homeassistant/custom_components/tivoo/audio_session.py`、`transport.py`、`audio_resource.py`：现有 P6 接入。
- `services/sherpa_wyoming/providers/wake.py`、`services/sherpa_wyoming/run.py`：现有 KWS request/model owner。
- 当前 HA Core 2026.11.0 的 `assist_pipeline/vad.py`：VoiceCommandSegmenter 默认 speech_seconds=0.3、command_seconds=1.0、silence_seconds=0.7、timeout_seconds=15.0；P7A STT 声明 requires_external_vad=true，故该 segmenter 会被调用。STT_VAD_START 在 segmenter.in_command 变为 true 时发出；Sherpa P7A 自身 `STT_MAX_SECONDS` 默认 300 秒，是另一层硬上限。
- 当前 HA Core 2026.11.0 的 `assist_pipeline/models.py`：WakeWordSettings.timeout 默认 None；`assist_satellite/entity.py` 的公开 `async_accept_pipeline_from_satellite()` 不暴露 wake_word_settings 参数。因此 3 秒 KWS miss watchdog 由本项目 AudioSessionCoordinator 根据 MIC_ACTIVITY 实现，不得写成 HA 默认值。
- 当前 HA Core 2026.11.0 的 `helpers/chat_session.py`：5 分钟 ChatSession cleanup；不作为本项目 8 秒 follow-up 值。
