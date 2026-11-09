# Tivoo STT / TTS 端到端处理链路规格

> 状态：架构规格，待实现与端到端验收  
> 适用范围：NAS 语音服务、Home Assistant Assist Pipeline、AstrBot Conversation Agent，以及 ESP32/Tivoo 语音输入输出链路。  
> 本文定义语音处理服务的职责和端到端行为。已有的设备通信字段、HA 事件字段、模型实测数值和底层协议不在此重复，均引用项目现有文档。

## 1. 设计目标与边界

本项目采用 **HA 管理语音会话、AstrBot 管理对话、独立 Wyoming 服务执行本地 STT/TTS、ESP32 管理物理音频 I/O** 的分层方式。

目标链路：

- 上行：Tivoo 麦克风 → ESP32 采集与本地 VAD 门控 → HA Assist Satellite → HA Wyoming STT → Paraformer 最终转写 → AstrBot。
- 下行：AstrBot SSE 增量文本 → HA Conversation Agent → HA Assist Pipeline/TTS Proxy → Wyoming TTS → 分句合成及 PCM 分块 → ESP32 HTTP 流式接收 → 解码与 I²S DAC → Tivoo AUX。
- STT/TTS 模型和推理依赖运行在独立容器中，不装入 HA Core，也不装入 ESP32 固件。
- 普通语音回复由 HA Pipeline 完成 TTS 调度；AstrBot 不直接调用 TTS 模型，也不直接向 ESP32 发送音频。
- 首期不实现 Token 级在线 TTS。通过句子缓冲将 OfflineTts 的完整文本输入限制在单句/短语范围，并利用生成回调输出音频块。

不在本文重新定义 ESP32 与 HA 的 TCP/HTTP 通信协议，也不重新描述 Assist Satellite 生命周期细节。

## 2. 权威文档与信息归属

| 内容 | 权威位置 |
|---|---|
| 全项目总体架构、职责边界、语音会话流程 | [项目主文档 §2–§4](../../../README.md) |
| P3 AstrBot Conversation Agent 的 HTTP OpenAPI、单用户 session_id、SSE、ChatLog 和取消合同 | [P3 接口合同矩阵](2026-11-09-p3-astrbot-conversation-contract-matrix.md) |
| 已核实的 HA 2026.11.0 Wyoming/Provider 能力、协议兼容细节及流式事件条件 | [项目主文档 §11.4](../../../README.md#114-ha-wyoming--provider-接入与流式回馈判断) |
| STT/TTS 模型测试数据、设备环境、RTF、内存和样本 | [项目主文档 §11](../../../README.md#11-stt--tts-实测结果) 与 [benchmarks/voice](../../../benchmarks/voice/) |
| ESP32 麦克风 PCM 上行、TTS URL 通知、HTTP 拉流、播放状态和 Satellite 结束条件 | [ESP32 ↔ HA 双向通信规格 §6–§8、§12](2026-11-09-esp32-ha-bidirectional-communication-design.md) |
| Paraformer 实测方法与限制 | [STT 对比报告](../../../benchmarks/voice/stt/STT_COMPARISON.md) |
| TTS 模型测试及试听材料 | [NAS TTS 测试报告](../../../benchmarks/voice/tts/nas/README.md)、[ARM Ubuntu Matcha/Melo 测试](../../../tts-benchmark-matcha-melo/README.md) |

若本文与以上协议/测试记录对具体字段或实测值存在差异，以对应权威文档为准；本文只规定跨组件的处理顺序、职责和验收要求。

## 3. 服务部署与组件职责

### 3.1 独立 Sherpa Wyoming 服务

在 NAS 部署一个语音服务容器，首期由同一服务进程提供 Wyoming STT 和 TTS 两种能力：

- STT Provider：接收 HA 转发的音频流，完成端点结束后的 Paraformer 离线识别，并返回最终文本。
- TTS Provider：接收 HA 转发的文本流，进行句子缓冲，逐句调用 sherpa-onnx OfflineTts，并将生成的 PCM 分块交回 HA。
- 模型常驻内存，避免每轮对话重新加载。
- STT 与 TTS 任务使用相互独立的会话状态和有界队列，不能因一个方向的阻塞污染另一个方向。
- 首期不拆成两个容器。只有实测表明模型推理互相争抢 CPU/内存并影响首段播放或识别时，才考虑拆分。

服务以 Wyoming 暴露给 HA，不提供 ESP32 直连入口，也不负责管理 Assist Pipeline、AstrBot 会话或 Tivoo 播放状态。

### 3.2 Home Assistant

HA 负责：

- 通过原生 Wyoming 集成连接语音服务，向 Assist Pipeline 提供 STT/TTS Provider。
- 接收 Assist Satellite 的音频会话，并把音频交给 Pipeline。
- 通过 Conversation Agent 将 STT 文本交给 AstrBot，并将 AstrBot 增量文本转成 HA 可消费的流式对话响应。
- 决定 TTS 何时开始、维护 TTS Proxy URL/访问凭据，并将音频资源入口通知 ESP32。
- 根据 ESP32 最终播放状态结束 Satellite 播报生命周期。

HA 不加载 sherpa-onnx 模型，不在自定义 Tivoo 集成中实现第二套 STT/TTS 推理框架。

### 3.3 AstrBot Conversation Agent

Conversation Agent 是 HA 与 AstrBot 的文本桥梁：

- 接收 HA 提供的最终 STT 文本及会话上下文。
- 按稳定用户标识映射 AstrBot session_id，保持连续对话落入正确会话。
- 调用 AstrBot HTTP OpenAPI，并启用 SSE。
- 将 SSE 文本增量按顺序写入 HA ChatLog；必须正确处理流结束、异常和取消。
- 声明并实现 HA Conversation streaming 能力。不能只声明支持流式却仍等待完整回答后一次性返回。
- 不自行分句合成、不持有 TTS 模型，也不绕过 HA 直接把音频发给设备。

### 3.4 ESP32 固件

ESP32 只负责物理音频与设备侧实时任务：

- I²S 采集、预录缓冲、本地 VAD 门控及麦克风 PCM 上行。
- 按 HA 通知的 URL 获取 TTS 音频流，增量解码、PCM 缓冲并驱动 I²S TX/DAC。
- 把播放完成、停止或失败状态反馈给 HA。
- 音频播放期间保持 SPP 显示控制可用。

音频格式、帧结构、TCP 端口、消息字段和播放状态名称以通信规格为准。

## 4. STT 上行处理链路

### 4.1 处理顺序

1. ESP32 在空闲状态持续本地采样，VAD 只负责判断是否启动上传；保留短时预录数据，避免丢失语音开头。
2. VAD 触发后，ESP32 建立本轮麦克风会话，先上传预录音频，再持续上传实时 PCM。
3. HA Assist Satellite 将音频流交给 Assist Pipeline。HA 服务端唤醒词 Provider 判断是否命中唤醒词；未命中时按 Pipeline 既定规则结束本轮。
4. 唤醒词命中后，Pipeline 将音频交给 Wyoming STT Provider。Provider 将收到的音频块按顺序交给当前识别会话。
5. 当 HA 结束本轮音频输入并关闭 Wyoming 音频会话时，STT 服务调用 Paraformer OfflineRecognizer 完成整段识别。
6. Wyoming 服务返回最终 Transcript；HA Pipeline 将文本交给 Conversation Agent。
7. Conversation Agent 调用 AstrBot，进入对话处理阶段。

### 4.2 STT 实现约束

- 模型：Paraformer zh-small INT8，模型版本为项目已测试的 2024-03-09。
- 推理方式：sherpa-onnx OfflineRecognizer；每轮输入完整音频后解码，不实现伪流式的中间转写。
- sherpa-onnx 版本首期固定为 2.0.1，与已完成的测试环境保持一致。
- 音频采样规格和 HA/Wyoming 事件转换沿用项目主文档及通信规格，不在此另设格式。
- 单个识别会话按顺序接收音频；会话关闭后清理缓存并返回最终结果，不跨轮复用上一轮音频。
- 对空音频、异常结束、解码失败和超时返回明确的 Provider 错误，不将空字符串伪装成有效识别结果。
- 不在 STT 服务中自行做第二套 VAD 或唤醒词检测；端点与唤醒职责由 ESP32 门控和 HA Pipeline 分层承担。

### 4.3 STT 当前能力边界

当前模型测试证明的是整段音频离线推理速度，不代表 Tivoo 实际麦克风的识别准确率，也不提供语音过程中的增量转写。首期按“说完一句/一轮后识别”的交互方式实现。真实收音质量、噪声、回声和端点行为须使用 Tivoo 内部安装位置的麦克风实测。

## 5. TTS 下行处理链路

### 5.1 处理顺序

1. AstrBot 收到用户文本后开始生成回答，通过 SSE 逐段输出文本。
2. Conversation Agent 将增量文本写入 HA ChatLog。HA 只有在 Conversation Agent 和 TTS Provider 两侧都真实支持流式输入时，才走流式 TTS 路径。
3. HA Assist Pipeline 将增量文本传给 Wyoming TTS Provider。Provider 持续接收文本片段，并维护当前合成请求的句子缓冲区。
4. 句子缓冲器检测到可提交的完整句子后，将该句作为一次 OfflineTts 输入提交给 Matcha Baker。
5. sherpa-onnx TTS callback 在当前句音频生成过程中逐块产出 PCM；Provider 将 PCM 块按顺序封装为 Wyoming 音频事件，交给 HA。
6. HA TTS Proxy 将音频数据逐块写入 HTTP 响应。达到 HA 流式启动条件后，Assist Satellite 集成向 ESP32 发送播放通知。
7. ESP32 使用 HTTP GET 获取 TTS Proxy 响应，边接收边解码/转换并写入有界播放缓冲；达到启动阈值后开始 I²S 输出至外部 DAC 和 Tivoo AUX。
8. TTS 文本输入结束后，HA 关闭 TTS 流；这不代表 ESP32 已播放完毕。ESP32 必须在最后一个 PCM 样本实际输出后报告完成，HA 再结束 Satellite 播报生命周期。

具体 HA 事件触发时机、Wyoming 结束事件和未知长度 WAV 处理以项目主文档 §11.4 及通信规格 §7 为准。

### 5.2 分句缓冲规则

OfflineTts 的输入必须是一段完整文本，因此 Provider 需要在文本流与模型调用之间设置轻量句子缓冲器。

首期规则：

- 按文本到达顺序累积，不重排、不丢弃文本。
- 优先在中文句末标点（。！？）及对应英文句末标点处切分；逗号、顿号等弱停顿不作为默认强制提交边界，避免过度切碎语义。
- 一次提交后立即启动该句合成，不等待整个 AstrBot 回答结束。
- 当前文本很长且迟迟没有句末标点时，允许按合理长度上限切分，避免长时间没有首段音频；切分不得丢字或重复字。
- 流结束时，将缓冲区剩余的非空文本作为最后一段提交。
- 对代码块、URL、连续数字或缩写不做复杂 NLP 重写；首期以简单标点和长度规则为主，后续根据真实听感修正。
- 分句器只决定模型何时开始处理一段完整文本；PCM callback 分块则决定音频如何逐步输出。这是两个独立阶段。

具体长度上限、首段启动阈值和播放预缓冲量通过端到端测试确定，不在没有实测依据时写死。

### 5.3 TTS 合成与音频队列

- TTS 模型常驻，避免每个句子重新加载。
- 每个 HA 合成请求具有独立 request/session 状态；同一请求内句子严格按原顺序合成和输出。
- callback 产生的 PCM 应尽快交给有界输出队列，不应先拼接成整段 WAV 再返回。
- 模型生成线程不能直接等待网络发送或 ESP32 播放；HA/Wyoming 发送端按队列节奏消费 PCM。
- 队列达到上限时采用明确的背压/失败策略，禁止无限缓存完整回答。
- 收到取消或断开时停止后续句子提交，并尽可能终止当前可取消的生成任务；已输出的音频由 HA/设备端按取消语义处理。
- 首期一个服务进程同时承载 STT/TTS，但任务队列和会话状态隔离。优先保证 TTS 首段输出与播放连续性，不能让长时间 STT 任务无界阻塞 TTS。

## 6. 模型与运行时选择

### 6.1 STT

采用已测试的 Paraformer zh-small INT8。NAS 与 ARM Ubuntu 的推理测试均明显快于实时，当前不需要为了增量转写而更换 OnlineRecognizer。先完成 Wyoming Provider 适配和真实麦克风质量验证。

### 6.2 TTS

首期以 Matcha Baker 作为主要候选：

- NAS 实测可达到低于实时的合成耗时，具备继续实现分句与 PCM callback 输出的基础。
- ARM Ubuntu 上的测试显示更大的推理余量，可作为服务迁移或性能对照依据。
- 其实际输出采样规格由模型/Provider 报告；HA 对设备暴露的最终 MIME 和音频封装必须以运行时响应为准。

AISHELL3 可保留为 NAS 多音色备选，但 8 kHz 输出的听感需要单独评估。其他模型不因 RTF 单项指标自动进入首期方案。详细数据及模型来源引用第 2 节，不在本文复制。

### 6.3 运行时约束

- 固定 sherpa-onnx 版本及模型文件版本/校验值，模型文件放在持久化挂载目录，不打入每次重建的临时容器层。
- 容器启动时加载模型并报告加载失败；模型不可用时 Wyoming Provider 应明确失败，不能静默切换到未知模型。
- 首期采用 CPU 推理，不引入 GPU、复杂模型路由或多模型热切换。
- 通过日志记录每轮 STT 音频时长/推理耗时，以及每轮 TTS 首句提交时间、首块 PCM 时间、合成耗时和队列欠载情况；日志不得包含访问 Token。
- 监控指标用于判断瓶颈，不要求高频写入数据库。

## 7. 异常与取消行为

| 场景 | 处理要求 |
|---|---|
| STT 音频会话提前结束 | 释放该会话缓存；若已有完整有效音频则按 Provider 语义处理，否则返回明确错误 |
| STT 模型加载或推理失败 | 返回 Wyoming/HA 可识别的失败状态，记录关联会话 ID 和简短错误 |
| AstrBot SSE 中断 | Conversation Agent 结束当前 HA 对话流并传播取消，不把未完成回答当成正常完成 |
| TTS 流没有完整句末标点 | 流结束时提交剩余文本；流仍持续且缓冲过长时按长度上限提交 |
| TTS 生成失败 | 终止当前合成流并报告错误，不伪造正常 AudioStop 完成 |
| HA/ESP32 取消播放 | 停止后续 TTS 生成/传输；设备侧取消 HTTP 与播放任务，最终状态以通信规格为准 |
| ESP32 下载或播放失败 | 由设备报告失败；HA 结束或清理对应播报生命周期 |
| 服务重启 | 旧请求不恢复、不重复播放；新请求重新建立会话，HA/ESP32 清理失效状态 |

具体 Wyoming 协议终止事件、ESP32 播放状态字段和 Satellite 收尾动作见权威文档，不在本表重复定义。

## 8. 实施顺序

1. **服务基础**：基于 ptbsare/sherpa-onnx-tts-stt 评估并复用现有 Wyoming 实现；固定 sherpa-onnx 2.0.1，接入已测试的 Paraformer 与 Matcha Baker 模型。
2. **STT Provider**：验证 HA 能发现 Provider、传入完整音频会话、收到 Paraformer 最终 Transcript；先用测试 WAV，再接真实 ESP32 音频。
3. **TTS 非流式基线**：先让 HA 可调用 Matcha Baker 并正常播放完整回答，确认音频格式与 ESP32 解码链路。
4. **PCM callback 输出**：将 OfflineTts callback 的 PCM 块直接送入 Wyoming 音频输出，不再等待整句音频文件写完。
5. **分句流式输入**：实现 SynthesizeStart/Chunk/Stop 会话管理、句子缓冲和逐句合成，正确处理 HA 兼容性事件，防止同一文本重复合成。
6. **AstrBot SSE 接入**：Conversation Agent 真正逐段写入 HA ChatLog，确认 HA 进入流式 TTS 路径。
7. **HA Proxy 到 ESP32**：验证 HTTP 响应未结束时设备已能持续收到、解码和播放音频。
8. **并发与长回答**：验证持续生成时队列不会无界增长，TTS 播放不中断，取消和异常能正确收尾。
9. **实机验收**：使用 Tivoo 实际麦克风、AUX、DAC 与 SPP 并发运行完整对话。

每一步保留可复现日志和明确通过条件；不把模型离线 RTF 测试等同于流式链路验收。

## 9. 验收标准

### 9.1 STT

- HA 能通过原生 Wyoming 集成连接独立服务。
- 同一段输入音频在服务端只形成一次识别请求，返回正确的最终 Transcript。
- STT 只在输入会话结束后提交 OfflineRecognizer，不误报为实时增量识别。
- 多轮音频会话互不串音；空输入、取消和异常均能释放资源。
- Tivoo 实际收音条件下完成唤醒词、端点、噪声和识别效果测试。

### 9.2 TTS

- HA 可通过 Wyoming Provider 合成完整文本并返回有效音频。
- 流式模式下 AstrBot 尚在输出后续文本时，首个完整句子已进入合成流程。
- sherpa-onnx callback 产生的音频块能在整句生成完成前送入 HA 音频流。
- 连续多句严格按原文本顺序播放，不丢字、不重复句子、不重复处理 HA 兼容性完整文本事件。
- 服务端不需要先生成完整回答音频文件；ESP32 不需要等 HTTP EOF 才开始播放。
- 长回答无明显欠载，队列有界；取消、失败和正常结束均可正确区分。
- 设备实际播放结束后，HA Satellite 才结束播报状态。

### 9.3 全链路

- 一次真实语音交互可以从 ESP32 麦克风采集开始，经 HA 唤醒词/STT、AstrBot SSE、分句 TTS，最终从 Tivoo AUX 播放。
- 语音播放期间 Tivoo SPP 屏幕控制持续可用。
- 记录从音频输入结束到 STT 文本可用、AstrBot 首段文本、首个 PCM 块、设备开始播放及播放完成的时间点，以区分各阶段延迟。
- 连续多轮和较长回答测试中，无会话串线、重复播放、资源持续增长或无法退出的忙碌状态。

## 10. 当前未验收事项

以下均为后续实测项，不能从现有模型基准或 HA 源码支持能力推定已通过：

- Wyoming 服务扩展后的真实流式 TTS 输入与 callback 音频输出。
- 分句策略对首段延迟、语气和句间停顿的影响。
- HA TTS Proxy 的未知长度流式响应在 ESP32 端的持续解码能力。
- Matcha Baker 在 NAS 同时承担 STT/TTS 时的资源争用及播放连续性。
- Tivoo 实际麦克风录音下的 STT 准确率、噪声和回声表现。
- 完整语音链路在 Wi-Fi 抖动、取消、重连和长回答下的稳定性。

完成这些测试后再更新状态，不提前把候选架构标记为已实现或已验收。

## 11. 上游实现与版本参考

- [ptbsare/sherpa-onnx-tts-stt](https://github.com/ptbsare/sherpa-onnx-tts-stt)：首选复用基础，需扩展流式 TTS 输入与 PCM 逐块输出。
- [Home Assistant Core 2026.11.0 Wyoming STT](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/wyoming/stt.py)
- [Home Assistant Core 2026.11.0 Wyoming TTS](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/wyoming/tts.py)
- [Home Assistant Core 2026.11.0 Assist Pipeline](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/assist_pipeline/pipeline.py)
- [sherpa-onnx 2.0.1 Offline TTS callback](https://github.com/k2-fsa/sherpa-onnx/blob/v2.0.1/sherpa-onnx/python/csrc/offline-tts.cc)
