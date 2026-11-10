# P7A Sherpa Wyoming 语音服务合同矩阵

> 状态：**合同矩阵已定义，待按矩阵实施与验收；P7A 尚未实现。**
> 日期：2026-11-10
> 基线：Tivoo-AI-Assistant main，commit f9aedf1a2ac0ad2541fc1f47cae8b229e9d0a18b
> 适用版本：Home Assistant Core 2026.11.0；Sherpa-ONNX 2.0.1；Wyoming Python package 1.10.2；NAS Synology DS920（Intel Celeron 1005M，2 logical CPUs，约 3.89 GiB RAM）
> 范围：NAS 上一个独立 Sherpa Wyoming 容器，在一个 Wyoming TCP 监听端口上同时提供 Wake Word、STT、TTS 三个 Provider。
> 本文是 P7A 的唯一服务部署和跨 Provider 合同依据。STT/TTS 的端到端业务行为继续以现有 STT/TTS 链路规格为准；ESP32 TCP/HTTP、Assist Satellite 生命周期和 AstrBot HTTP/SSE 不在本文重新定义。

## 1. 目标与最终决策

P7A 是完整 P7 的前置阶段，先交付一个可被 HA 原生 Wyoming 集成发现和使用的独立语音服务容器，再进入 P5、P6。P7A 不依赖 ESP32 固件已实现，也不要求先有实际麦克风、TCP 7777/7778 或 HTTP 音频资源通路。

**已确认采用方案 B：一个容器、一个服务进程、一个 Wyoming TCP 监听端口、三个独立 Provider。**

三个 Provider 的职责和模型严格分开：

1. **Wake Word Provider（KWS）**：使用 Sherpa-ONNX KeywordSpotter 检测配置的中英文唤醒词，只返回唤醒检测结果，不生成转写文本。
2. **STT Provider**：使用项目已实测的 Paraformer zh-small INT8 OfflineRecognizer；整段音频输入结束后返回最终 Transcript。
3. **TTS Provider**：使用项目已实测的 Matcha Baker OfflineTts；支持普通完整文本合成，以及 HA Wyoming 流式文本事件、句子缓冲和 PCM callback 分块输出。

三个 Provider 通过同一个 Wyoming 服务端的 Info 元数据发布给 HA；HA 在同一个 Wyoming Config Entry 下创建 wake_word、stt、tts 三类实体。三个 Provider 使用独立模型对象、请求状态和错误处理，不共享音频缓冲、识别 Stream、TTS 句子缓冲或 PCM 队列。

### 1.1 方案取舍记录

| 方案 | 处理方式 | 结论 |
|---|---|---|
| A | STT/TTS 一个 Wyoming 服务，KWS 另设服务 | 不采用。会增加 HA Config Entry、端口、部署与监控对象，没有当前规模下的实际收益 |
| **B** | 一个容器/进程/端口，同时发布 KWS、STT、TTS | **采用。用户已确认。** 与 HA 2026.11.0 Wyoming 集成实际支持的多平台发现机制一致 |
| C | 一个容器内 KWS/STT/TTS 分成独立进程和多个端口 | 不采用。当前单用户、单 Tivoo 场景不需要额外进程管理和端口协调 |

### 1.2 目标

- 一个容器启动后常驻加载 KWS、Paraformer、Matcha 三个模型；模型不在每轮请求时重复加载。
- HA 通过一个 Wyoming 主机地址和 TCP 端口发现三个 Provider。
- KWS 在 HA Assist Pipeline 的 WAKE_WORD 阶段运行；只有命中后 Pipeline 才进入 STT。
- STT 使用整段离线识别，不声明伪流式转写。
- TTS 同时具备非流式兼容能力和真正的流式文本输入/PCM 分块输出能力。
- 模型、运行库版本、模型文件来源和 SHA-256 有可追溯记录。
- 服务启动失败、请求取消、模型错误及客户端断开均可诊断；不把异常伪装成空转写或正常完成。

### 1.3 非目标与明确排除

- 不在本容器实现 ESP32 I2S RX/TX、AFE VAD、麦克风采集、DAC、SPP、TCP 7777/7778 或 HTTP 音频资源服务。
- 不让 ESP32 直接连接 Sherpa 容器；ESP32 只连接 HA。
- 不在本容器实现 Assist Pipeline、Conversation Agent、AstrBot session、ChatLog 或 TTS Proxy。
- 不在 STT Provider 内执行唤醒词匹配；不将 STT 转写文字后再用字符串匹配代替 KWS。
- 不实现 Token 级在线 TTS。OfflineTts 仍以完整句子/短语作为一次输入。
- 不提供 OpenAI 兼容 HTTP API；不启用上游项目的 FastAPI 10500 端口。
- 不在本阶段做 Tivoo 真实麦克风的误唤醒率、识别距离、噪声和回声最终验收；这些留给 P7 真机联调。
- 不在本阶段拆成多个容器或引入 GPU/CUDA。

## 2. 权威文档和上游依据

| 内容 | 权威依据 |
|---|---|
| 总体架构、P5/P6/P7 阶段关系、ESP32 只连接 HA | 项目主文档 README.md |
| STT/TTS 处理时序、Paraformer 选择、分句缓冲、PCM callback、取消及验收 | docs/superpowers/specs/2026-11-09-stt-tts-end-to-end-pipeline-spec.md |
| ESP32 16 kHz PCM、HA Satellite、TCP/HTTP 音频通路及设备边界 | docs/superpowers/specs/2026-11-09-esp32-ha-bidirectional-communication-design.md |
| HA/AstrBot 文字桥接和 SSE | docs/superpowers/specs/2026-11-09-p3-astrbot-conversation-contract-matrix.md |
| Paraformer 模型来源、STT SHA-256 和基准限制 | benchmarks/voice/stt/README.md、STT_COMPARISON.md、MODEL_SOURCES.md |
| Matcha Baker 的实际测试配置、22.05 kHz 输出和模型 SHA-256 | tts-benchmark-matcha-melo/README.md、scripts/benchmark.py、models/SHA256SUMS、models/MODEL_SOURCES.md |
| NAS Matcha Baker 单线程 RTF | benchmarks/voice/tts/nas/README.md |
| HA Wyoming 多平台发现和 Provider 接口 | HA Core 2026.11.0 的 wyoming/data.py、wake_word.py、stt.py、tts.py |
| HA Pipeline WAKE_WORD → STT 顺序、音频缓冲和默认 5 分钟 timeout | HA Core 2026.11.0 的 assist_pipeline/default_pipeline.py、models.py、const.py |
| Wyoming Wake、Info、TTS 事件字段 | [Wyoming 1.10.2 wake.py](https://github.com/OHF-Voice/wyoming/blob/v1.10.2/wyoming/wake.py)、info.py、tts.py；[AsyncEventHandler EOF/disconnect 生命周期](https://github.com/OHF-Voice/wyoming/blob/v1.10.2/wyoming/server.py) |
| Sherpa KWS 模型、具体 ONNX 文件和自定义关键词 CLI 格式 | https://k2-fsa.github.io/sherpa/onnx/kws/pretrained_models/ |
| Sherpa 2.0.1 KWS Python API 示例 | https://github.com/k2-fsa/sherpa-onnx/blob/v2.0.1/python-api-examples/keyword-spotter.py、keyword-spotter-from-microphone.py |
| Sherpa 2.0.1 源码安装备用 text2token.py | https://github.com/k2-fsa/sherpa-onnx/blob/v2.0.1/scripts/text2token.py |
| Sherpa 2.0.1 OfflineTts callback 签名 | https://github.com/k2-fsa/sherpa-onnx/blob/v2.0.1/sherpa-onnx/python/csrc/offline-tts.cc |

### 2.1 复用项目基线

首选复用项目：**ptbsare/sherpa-onnx-tts-stt**，上游 main 固定到 commit **c307e6835a079157e71df28545f17d76bca1cbc2**。本矩阵对照了该提交的 run.py、Dockerfile、model_utils.py、models/stt/sherpa-onnx-paraformer-zh-small-2024-03-09.py、models/tts/matcha-icefall-zh-baker.py、api.py 和 DOCS.md。

直接复用/移植的基础能力：

- Wyoming AsyncTcpServer、AsyncEventHandler、Describe/Info 及现有 STT/TTS 事件骨架。
- Paraformer 模型加载及 AudioStart/AudioChunk/AudioStop 离线识别路径。
- OfflineTts 模型常驻、Synthesize 请求处理和 AudioStart/AudioChunk/AudioStop 输出的基础代码。
- 现有模型下载、模型目录和启动时初始化思路。

必须新增或调整的能力：

- 新增 Wyoming Wake Word Detect/Detection/NotDetected 处理和 Sherpa KeywordSpotter 模型加载。
- 修正 Wyoming Info，使它如实声明三种 Provider、各自模型和语言。
- 修正 STT 异常与空转写语义。
- 扩展 TTS 流式文本输入、分句、callback PCM 输出、SynthesizeStopped、取消和有界队列。
- 使用本项目已经实测的 Vocos Matcha 配置，不照搬上游 Matcha loader 的 HiFi-GAN 配置。
- 固定 Sherpa/Wyoming 依赖，不沿用上游 Dockerfile 的未固定 pip 安装。
- 关闭无关的 FastAPI/OpenAI 格式 API，只运行 Wyoming TCP 服务。

上游 GitHub 元数据没有声明 license，仓库树也未发现 LICENSE 文件。按用户明确确认的个人实验、非商业用途，本项目直接复用并修改该上游代码，不重复造轮子；保留上游仓库、固定 commit 和来源说明，不把上游代码错误标成 MIT/Apache。本阶段只服务于用户自己的实验环境，不将衍生镜像或源码作为公开分发目标。

## 3. 组件边界和调用关系

### 3.1 组件职责

| 组件 | P7A 职责 | 不负责 |
|---|---|---|
| Sherpa Wyoming 容器 | 常驻 KWS/STT/TTS 模型；提供单一 Wyoming TCP 服务；处理对应事件、请求和错误 | 不管理 HA Pipeline、AstrBot、设备状态或 ESP32 |
| Wyoming KWS Provider | 接收 HA 音频流，检测配置唤醒词，返回 Detection 或 NotDetected | 不转写普通语音、不决定是否调用 AstrBot |
| Wyoming STT Provider | 接收唤醒命中后的音频流，AudioStop 后执行 Paraformer 离线识别 | 不监听唤醒词、不做第二套 VAD、不生成中间 Transcript |
| Wyoming TTS Provider | 接收 HA 文本/文本流，分句调用 Matcha，输出 PCM AudioChunk | 不直接向 ESP32 传音频，不生成 HA Proxy URL |
| HA 原生 Wyoming Integration | Describe/Info、建立同一个 Config Entry、创建 wake_word/stt/tts 三类实体 | 不加载 Sherpa 模型 |
| HA Assist Pipeline | WAKE_WORD → STT → Conversation Agent → TTS；维护 VAD、端点、会话和音频生命周期 | 不自行实现 KWS/STT/TTS 模型 |
| P3 AstrBot Conversation Agent | 接收最终 STT 文本，调用 AstrBot HTTP/SSE，将回复增量写入 ChatLog | 不直接调用 Sherpa 或输出 PCM |
| ESP32/Tivoo | P7A 不参与；P6/P7 后续接收 HA 音频/设备通路 | 不连接 Sherpa 服务 |

### 3.2 语音处理顺序

1. P7 后续实现的 ESP32 本地 AFE VAD 只负责从空闲状态触发上传；它不是唤醒词识别器。
2. ESP32 把音频交给 HA Assist Satellite；HA Pipeline 从 WAKE_WORD 阶段开始。
3. HA 的 Wyoming Wake Word Provider 将 16 kHz PCM 音频流发送到本服务。服务使用 KWS KeywordSpotter 检测指定关键词。
4. 未命中时不产生 Detection；HA Pipeline 按其 wake-word timeout/输入结束规则终止本轮，不进入 STT 和 Conversation Agent。
5. 命中时返回 Wyoming Detection；HA Pipeline 将缓冲及后续音频送给 STT Provider。
6. STT Provider 在输入音频结束后使用 Paraformer 返回最终 Transcript。
7. HA Conversation Agent 将最终文字交给 AstrBot；P7A 不改变 P3 HTTP/SSE 合同。
8. HA 把 AstrBot 回复交给 Wyoming TTS Provider。TTS 按完整句子调用 Matcha Baker，PCM 通过 Wyoming 返回 HA。
9. HA TTS Proxy 和 Assist Satellite 的 URL 通知、ESP32 HTTP GET、DAC 播放及播放完成状态，继续按现有 STT/TTS 和 ESP32 通信规格执行，不属于 Sherpa 容器。

**重要：** 唤醒词检测不是 STT 转写后的文字过滤。是否进入 STT/Conversation Agent 由 HA Pipeline 的 WAKE_WORD 阶段决定。KWS 和 STT 是同一服务中的两个独立 Wyoming Provider。

### 3.3 服务拓扑

- 一个容器：sherpa-wyoming。
- 一个 Python 服务进程：同一进程初始化三个模型对象并运行一个 Wyoming AsyncTcpServer。
- 一个服务端口：TCP 10400，作为首期固定默认值；若部署环境变更，仍只允许通过同一个 Wyoming 端口提供三类能力。
- HA 是 Wyoming TCP Client；服务不主动连接 HA，不连接 AstrBot，不连接 ESP32。
- HA 手动添加一个 Wyoming Integration Config Entry（host + 10400）即可发现三个平台；不需要分别创建三个 Wyoming 服务。
- 多个 HA Provider 请求可以建立各自的 TCP 连接；每个连接/请求持有独立状态。模型对象可以常驻共享，但不能共享某个连接的音频缓存、KWS Stream、STT Stream、TTS 文本缓冲或 PCM 队列。

## 4. 容器、目录和运行合同

### 4.1 项目目录

P7A 实现阶段按以下目录归档，不把语音模型服务塞入 Tivoo Gateway 或 HA 自定义集成：

| 路径 | 用途 |
|---|---|
| services/sherpa_wyoming/ | 基于固定上游 commit 的 Wyoming 服务代码、模型加载适配、依赖锁定和 Dockerfile |
| deploy/nas/compose/sherpa-wyoming.yml | NAS 独立容器 Compose 文件 |
| deploy/nas/config/sherpa-wyoming/ | 不含模型二进制的配置模板/关键词源文件示例 |
| NAS 持久化模型目录（通过 Compose bind mount 配置） | KWS、STT、TTS 模型文件和生成的 keywords 文件；不提交大型模型权重 |
| .superpowers/sdd/2026-11-10-p7a-sherpa-wyoming/ | P7A 实施过程日志、测试证据和任务批次文件（本地忽略目录） |

现有 services/audio/ 继续存放音频格式转换、测试和诊断工具；不把长期运行的 Wyoming Provider 服务放在这个工具目录里。

### 4.2 运行环境和依赖

- NAS 容器基线：Linux amd64、Python 3.11 系列、CPU Provider。
- Sherpa-ONNX 固定为 **2.0.1**，与项目 Paraformer/Matcha 测试版本一致。
- Wyoming Python package 固定为 **1.10.2**，与 HA Core 2026.11.0 的 Wyoming Integration requirements 一致。
- 不使用上游 Dockerfile 中的浮动 sherpa-onnx、git HEAD Wyoming 依赖或 NVIDIA 自动探测。
- CPU 为唯一首期 Execution Provider；不安装 CUDA，不因 NAS 上可能存在其他 GPU 环境自动改变 Provider。
- 其他 Python 运行依赖应在实现批次中通过 requirements/lock 文件固定，禁止构建时无版本约束地自动升级。

### 4.3 网络和端口

| 端口 | 协议 | 用途 | 规则 |
|---:|---|---|---|
| 10400 | TCP | Wyoming Describe/Info、Wake、STT、TTS | 唯一对 HA 暴露的服务端口 |
| 10500 | TCP | 上游项目的 FastAPI/OpenAI 格式接口 | 本项目不启用、不映射、不作为备用入口 |

- 仅允许 HA 所在 NAS/Docker 私有网络访问 10400；不发布到公网，不在路由器做 WAN 端口转发。
- Wyoming 服务端不新增自有 HTTP API、WebSocket、MQTT 或 ESP32 直连入口。
- Wyoming 协议本身不提供本项目所需的应用层 Bearer 鉴权；网络隔离由 NAS/Docker 私有网络承担。
- 日志不得记录未来可能使用的 HTTP 音频 Token、访问凭据、原始 PCM 或完整转写文本。

### 4.4 模型持久化和启动

- 容器代码层不打包大模型权重；模型通过持久化挂载目录提供，推荐统一挂载到容器 /models。
- 三类模型分别存放在 /models/kws、/models/stt、/models/tts；关键词源文件及生成文件放在 KWS 模型配置目录。
- 第一次准备模型时下载官方 release asset；已有模型先校验文件存在和 SHA-256，不因容器重建重复下载。
- 每个模型的下载来源、版本、必要文件、文件大小和 SHA-256 进入模型清单；KWS 首次下载时必须计算并保存官方 release 包和实际加载文件的 SHA-256，不能凭文件名判断完整性。
- 服务只有在三个模型均成功加载、关键词配置有效、Wyoming Info 可完整构造后才开始对外监听；任一必需模型失败则容器启动失败并输出明确错误，不得静默隐藏某个 Provider。
- 模型文件缺失/损坏不得静默回退到其它模型或自动换用未知模型。
- 容器重启不恢复旧 KWS/STT/TTS 请求；旧连接终止，由 HA 为新请求重新建立 Provider 会话。模型文件和配置保留。

### 4.5 线程和资源

初始 CPU 线程配置以已有测试和 NAS 两逻辑 CPU 条件为基线：

| 模型 | 初始线程数 | 依据 |
|---|---:|---|
| KWS | 1 | 小型 3M KWS 模型；尚无本项目 NAS 实测，作为首轮测量起点 |
| STT | 2 | NAS Paraformer 对照中 2 线程 RTF 约 0.089–0.091 |
| TTS | 1 | NAS Matcha Baker 单线程 RTF 约 0.598，已快于实时 |

- 模型线程数可通过环境配置覆盖，但默认值必须在配置模板中明确。
- 同一个 Assist Pipeline 的 KWS、STT、TTS 按阶段顺序执行；服务不得创建无限制推理线程或无限队列。
- 首轮组合部署时记录容器启动加载耗时、常驻 RSS、推理期间峰值 RSS、CPU 占用、KWS 实时处理滞后和 TTS 队列水位。现有单模型/分开进程 RSS 不能代替三个模型同进程实测。
- 在取得组合实测前不伪造精确内存占用，也不设置缺乏依据的硬性内存上限；部署验收必须记录 NAS 实际可用内存与服务峰值 RSS，确认不会造成 HA/AstrBot OOM。

## 5. Wyoming Info 和 HA Provider 发现合同

### 5.1 Describe / Info

HA 连接后发送 Wyoming Describe；服务返回一个 Info。Info 必须同时声明并标记 installed 的 wake、asr、tts 项目。三个 Provider 不使用三个端口或三份独立 Info 服务。

### 5.2 Wake Word 元数据

- Info.wake 恰好包含一个已安装 WakeProgram。
- 首期 WakeModel 恰好包含一个运行时配置的唤醒词；phrase 是用户配置的实际文字，不在代码中猜测或硬编码为某个具体词。
- WakeModel.name 使用稳定服务 ID **tivoo-wake**，HA Pipeline 的 wake_word_id 与 Detection.name 均使用该 ID。
- WakeModel.languages 声明模型支持的中文和英文语言，使用 HA 可匹配的语言标识 zh-CN、en-US。
- WakeModel.phrase 返回 WAKE_WORD_PHRASE 当前配置值；未配置或关键词文件构建失败时，服务启动失败。
- 修改 phrase 后需重新生成 keywords 文件并重载服务；重载前后不得让 Info 继续声明与实际 keywords 文件不一致的 phrase。

### 5.3 STT 元数据

- Info.asr 恰好包含一个已安装 AsrProgram 和一个已安装 AsrModel。
- AsrModel.name 为 sherpa-onnx-paraformer-zh-small-2024-03-09。
- AsrModel.languages 声明 zh-CN、en-US；Paraformer 是中英双语模型，不得因上游 Add-on 默认 language=zh-CN 就在 Info 中错误地只声明中文。
- AsrProgram.supports_transcript_streaming=false；本模型使用 OfflineRecognizer，不产生中间转写。
- AsrProgram.requires_external_vad=true；OfflineRecognizer 不负责实时语句端点判断，HA Pipeline 负责 STT 阶段的端点检测。
- 不向 HA 错误声明 STT Provider 自带 VAD。ESP32 的空闲 VAD 门控、HA WAKE_WORD 超时与 HA STT 端点检测是三个不同职责。

### 5.4 TTS 元数据

- Info.tts 恰好包含一个已安装 TtsProgram。
- TtsProgram.name 使用稳定的 Matcha Baker 服务名称。
- TtsProgram.supports_synthesize_streaming=true；只有在第 8 节的完整流式事件合同和验收通过后，才允许对 HA 声明 true。
- 首期只声明一个真实可用的 TTS Voice，voice name/speaker ID 为 **0**，语言为 zh-CN。
- Matcha Baker 是单 speaker 模型；禁止沿用上游 run.py 中 0–100 的通用 speaker 列表。不得让 HA 展示模型不存在的音色或 speaker。
- TTS 不声明 en-US 支持；STT/KWS 双语不意味着 TTS 也支持英语。

### 5.5 HA 侧发现结果

一次 HA Wyoming Config Entry 必须同时创建：

| HA 平台 | 预期实体 | 预期能力 |
|---|---|---|
| wake_word | Wyoming Wake Word Detection Entity | 显示配置唤醒词并能对音频流返回检测结果 |
| stt | Wyoming Speech-to-Text Entity | 支持 zh-CN/en-US、16 kHz PCM、最终转写 |
| tts | Wyoming Text-to-Speech Entity | 支持 zh-CN、voice 0、非流式与流式文本输入 |

HA 原生集成实际按 Info 中 installed 的 wake/asr/tts 项目创建 Platform.WAKE_WORD、Platform.STT、Platform.TTS。P7A 不另写 HA 自定义 KWS/STT/TTS 集成，也不在 Tivoo 自定义集成中实现模型 Provider。

## 6. 模型和音频格式合同

### 6.1 KWS 模型

- 模型：sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20。
- 官方模型 release：kws-models 下同名 tar.bz2。
- 首期选用 chunk-16、left-64 模型组合；其模型文档标示 chunk latency 约 320 ms。chunk-8 约 160 ms，但通常以准确度为代价，不作为未经对照测试的默认值。
- 首期 CPU 使用官方发布包内 chunk-16/left-64 组合：`encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx`、`decoder-epoch-13-avg-2-chunk-16-left-64.onnx`、`joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx`；即 int8 encoder + fp32 decoder + int8 joiner。`tokens.txt`、`en.phone` 与模型文件来自同一个官方发布包。
- 运行库为 Sherpa-ONNX 2.0.1。必须用 2.0.1 Python API 验证此模型可以加载和实际检测，不能因当前 sherpa-onnx master 示例能运行就推定 2.0.1 一定兼容。
- Python API 复用 sherpa_onnx.KeywordSpotter、create_stream、accept_waveform、is_ready、decode_stream、get_result、reset_stream；不自行编写关键词模型解码算法。

### 6.2 KWS 唤醒词配置

- 首期一个用户可配置唤醒词；不在合同中预设具体词语。
- WAKE_WORD_PHRASE 保存原始中/英文短语。容器使用 pip 安装的 Sherpa-ONNX 2.0.1 时，优先复用官方 `sherpa-onnx-cli text2token` 子命令，使用模型 `tokens.txt`、`tokens-type phone+ppinyin` 和 `en.phone` 生成 KeywordSpotter 使用的 keywords 文件；只有从 Sherpa 源码安装时才使用仓库内等价的 `scripts/text2token.py`。
- 原始关键词文件每行按 Sherpa 文档格式同时包含待识别词和 `@` 原文标签；多词英文 label 中以 `_` 代替空格，例如 `HEY TIVOO @HEY_TIVOO`。中文转拼音、英文转音素由 Sherpa 工具完成，不手工猜测 token 序列。示例调用：

  ```bash
  sherpa-onnx-cli text2token --tokens /models/kws/tokens.txt --tokens-type phone+ppinyin --lexicon /models/kws/en.phone keywords.raw.txt /models/kws/keywords.txt
  ```

  源码安装时的等价备用命令为 `python3 scripts/text2token.py --text keywords.raw.txt --tokens /models/kws/tokens.txt --tokens-type phone+ppinyin --lexicon /models/kws/en.phone --output /models/kws/keywords.txt`。
- KWS score、threshold、num_trailing_blanks 可配置；首轮默认按 Sherpa 2.0.1 示例的 keywords_score=1.0、keywords_threshold=0.25、num_trailing_blanks=1 起测。它们不是实机最终误唤醒率承诺，必须结合负样本与实际收音调整。
- 关键词文件生成后执行一次启动校验；文件内容与 Info 中的 phrase 必须一致。

### 6.3 STT 模型和输入

- 模型：sherpa-onnx-paraformer-zh-small-2024-03-09 INT8。
- 官方 release asset：asr-models/sherpa-onnx-paraformer-zh-small-2024-03-09.tar.bz2。
- 本项目已记录 SHA-256：model.int8.onnx = 3ef6c19369b912f7caf3cef8e545c5ccd1a33d9d7ec792a46668dc41c4b229ec；tokens.txt = 4b2d964e18b9cf139b473003b6698fb2ed9a2a5ec55b93daa677b28f578897aa。
- 输入：16,000 Hz、单声道、signed 16-bit little-endian PCM；Wyoming AudioStart、AudioChunk、AudioStop。
- HA Wyoming STT Provider 向服务发送 Transcribe(language=...)，随后发送 AudioStart、多个 AudioChunk，最后 AudioStop。
- 服务为每个请求创建独立 OfflineRecognizer Stream；按顺序收集音频，AudioStop 后 decode_stream 一次并返回 Transcript。
- 不返回中间 Transcript；不将每个 AudioChunk 当成独立语句；不跨 AudioStop 复用上轮音频。
- Paraformer 模型本身处理中英文内容；Transcribe.language 是 Provider 请求元数据，不通过切换模型来实现语言识别。
- 有效音频解码成功但没有识别出文字时，返回 Transcript(text="")；空输入、协议错误、模型异常、超时和服务失败返回 Wyoming Error，不得把异常吞掉后返回空 Transcript。
- STT 预处理只做必要的 PCM 格式转换和模型要求的音频归一化；不在 STT 中额外运行一套 KWS。HA 端点检测结束时再执行 OfflineRecognizer。

### 6.4 TTS 模型和输出

- TTS：Matcha Baker，模型包 matcha-icefall-zh-baker。
- 声学模型：model-steps-3.onnx；词典 lexicon.txt；tokens.txt；规则 FST 使用项目实测配置的 phone.fst、date.fst、number.fst。
- Vocoder：**vocos-22khz-univ.onnx**。本项目 tts-benchmark-matcha-melo/scripts/benchmark.py 的实测加载配置使用该 Vocos 文件，输出 22,050 Hz。
- 不照搬 ptbsare 上游 models/tts/matcha-icefall-zh-baker.py 中默认的 hifigan_v2.onnx；这与本项目已有基准使用的 vocoder 不同。
- 本项目当前 SHA256SUMS 已记录：model-steps-3.onnx = 78a9fd17e9a6c20198dca4e69d18f941303f8ab39ec61dde04cfc7595262ddfd；lexicon.txt = 38b886d46aefa50da6322a64d72fd595d5f4fae1051adb160d647541b1e0a4a2；vocos-22khz-univ.onnx = 0574a135aa1db2de6e181050db2ec528496cacd4a4701fc5d7faf9f9804c0081。P7A 模型清单还必须补齐实际加载的 tokens.txt、phone.fst、date.fst、number.fst 等文件的校验值；现有 SHA256SUMS 不应被误认为已覆盖全部 TTS 依赖文件。
- sherpa_onnx.OfflineTts.generate 输入完整句子，sid=0、speed=1.0；Sherpa 2.0.1 callback 签名为 `callback(samples: np.ndarray, progress: float) -> int`，返回 `1` 继续生成、返回 `0` 提前停止。callback 产生的 samples 必须复制后再交给异步发送端，不能引用 callback 返回后失效的临时内存。
- 输出：22,050 Hz、单声道、signed 16-bit PCM。Wyoming AudioStart/AudioChunk 负责描述和传输 PCM；HA 再封装为 TTS Proxy 使用的 WAV 流。Sherpa 容器不生成 ESP32 专用音频 URL，也不把文件写入 ESP32。
- 服务不在 Wyoming 内擅自重采样成 44.1 kHz；最终 DAC/I2S 格式转换由既有 ESP32 音频链路合同负责。

## 7. Wyoming KWS 事件合同

### 7.1 请求顺序

每个 KWS 请求是独立 TCP 连接和独立 KWS Stream：

1. HA 发送 Detect(names=["tivoo-wake"])；names 为空或未提供时，服务按协议处理为默认已配置唤醒词。
2. HA 发送 AudioStart(rate=16000, width=2, channels=1)。
3. HA 连续发送有序 AudioChunk；chunk 携带的音频按 16 kHz、16-bit、mono PCM 解释，timestamp 原样保留。
4. 服务将 PCM 转为模型所需 float32 波形，按输入顺序送入该连接独立的 KeywordSpotter stream；模型 ready 时调用 decode_stream/get_result。
5. 命中后立即返回 Detection(name="tivoo-wake", timestamp=当前已处理音频块的 timestamp)，随后结束该次连接；不返回 Transcript。Sherpa KeywordSpotter 返回关键词标签而不是精确声学起始偏移，因此 timestamp 表示检测被确认时对应的输入块时间，不得宣称为关键词第一个音素的精确起始时间。
6. HA Core 2026.11.0 的 WyomingWakeWordProvider 不会因收到 NotDetected 事件立即返回，而是在连接关闭且没有 Detection 时返回 None；其当前实现也不会在上游音频迭代器结束时发送 AudioStop，而是通过关闭 Wyoming TCP 连接结束输入。因此服务必须把 TCP EOF 视为正常的未命中终止条件，不能只等待 AudioStop。复用 Wyoming 1.10.2 AsyncEventHandler 时，EOF 会使基类 run() 跳出读取循环，并在 writer.close() 前调用 disconnect()；可在请求未命中且未发送错误/Detection 时，于 disconnect() 中发送 NotDetected。发送后连接由基类关闭。不能在已经发送 Detection/Error 的请求上再发送 NotDetected，也不能让未命中请求继续保持连接。
7. 客户端断开或请求取消时释放当前 Stream，不影响其他连接。

### 7.2 KWS 响应和异常

| 条件 | 服务响应 |
|---|---|
| 命中指定唤醒词 | Detection.name 必须等于 Info 中 WakeModel.name；附检测时间戳；结束本请求 |
| 正常输入结束但未命中 | NotDetected，然后关闭本请求；不伪造 Detection |
| Detect.names 指向未声明模型 | Wyoming Error，说明模型 ID 不支持 |
| AudioStart 格式不支持 | Wyoming Error；不把错误格式音频送入模型 |
| 模型运行错误 | Wyoming Error，记录服务端错误类别和关联请求，不把错误伪装成 NotDetected |
| 客户端取消/断开 | 清理 Stream 和请求任务，不影响已加载的全局模型 |

HA 的 WAKE_WORD timeout 与 Pipeline VAD 是会话控制；Sherpa KWS 只判断关键词。KWS 不额外创建第二条麦克风连接，也不依赖 STT Transcript。

## 8. Wyoming STT 事件合同

### 8.1 请求顺序

1. HA 连接 10400，发送 Transcribe(language=当前 Pipeline STT language)。
2. HA 发送 AudioStart(16000 Hz、16-bit、mono)。
3. HA 按顺序发送 AudioChunk。
4. HA 结束输入并发送 AudioStop。
5. 服务完成当前请求 OfflineRecognizer decode_stream，返回一个 Transcript(text=最终文本)。
6. 连接结束或请求完成后清除该 Stream 和本轮音频缓存。

### 8.2 STT 行为

- 同一个 AudioStart/AudioStop 之间只形成一次识别请求；多轮识别不能互相拼接。
- 单个请求的音频块严格按 TCP/Wyoming 到达顺序处理。
- 每个 STT 请求的累计输入时长上限默认 **300 秒**（HA Core 2026.11.0 默认 Assist Pipeline timeout 为 5 分钟）；按 16 kHz、16-bit、mono 计算，原始 PCM 缓存上限为 9,600,000 bytes。到达上限后返回 Wyoming Error 并释放请求，不继续追加；若项目以后显式提高 HA Pipeline timeout，再同步调整该上限。
- 输入 PCM 转换和缓存必须有界；不能因无 AudioStop 或恶意超长输入无限增长。
- 接收取消/连接断开后释放请求缓存；取消的旧请求不得延迟污染下一轮。
- STT 的 endpoint 由 HA Pipeline 按 AsrProgram.requires_external_vad=true 处理；ESP32 本地 VAD 不是该 endpoint。
- 当前 Paraformer 是离线整段识别，不得声明 supports_transcript_streaming=true。

## 9. Wyoming TTS 事件合同

### 9.1 非流式请求

当 HA 只发送完整 Synthesize(text, voice) 时：

1. 服务校验 voice ID=0，按 Matcha Baker OfflineTts 生成完整文本。
2. 返回一次 AudioStart(rate=22050,width=2,channels=1)。
3. 返回一个或多个 AudioChunk，保持 PCM 样本顺序。
4. 返回 AudioStop。
5. 错误时返回 Wyoming Error，不发送伪造的正常 AudioStop。

非流式路径是 HA Wyoming TTS Provider 的兼容基线，不得因增加流式功能而回归。

### 9.2 流式输入事件

HA Core 2026.11.0 的 Wyoming TTS Provider 在流式请求中依次发送：

- SynthesizeStart（可包含 voice）
- 零个或多个 SynthesizeChunk(text)
- 一条携带完整合并文本的 Synthesize（为旧服务兼容）
- SynthesizeStop

服务必须识别当前连接已经进入流式状态。流式会话中的最后一条完整 Synthesize 是兼容性重复事件，不得再合成一次或把全文重复追加到句子缓冲。只有未进入流式状态的普通 Synthesize 才走非流式路径。

### 9.3 分句规则

- 文本按到达顺序追加，不重排、不丢失、不重复。
- 优先按中文句末标点 。！？ 和常用英文句末标点 .!? 切分。
- 逗号、顿号等弱停顿不作为默认强制提交边界。
- 首次实现的 max_sentence_chars 默认值为 80 个 Unicode 字符；达到上限仍无强句末边界时按字符边界提交，不能无限等待标点。
- 每次提交一段非空完整文本后立即开始一次 OfflineTts.generate；不等待整个 AstrBot 回答结束。
- 收到 SynthesizeStop 时，将缓冲区剩余非空文本作为最后一段提交。
- 不做复杂 NLP 改写；不因拆分而丢字、重复字或更改原文顺序。
- max_sentence_chars 可配置，但任何调整必须通过首段延迟、自然停顿和长句听感测试，不以主观猜测当成性能结论。

### 9.4 PCM callback 和流式输出

- 每个句子调用 OfflineTts.generate(text, sid=0, speed=1.0, callback=...)。
- Sherpa 2.0.1 callback 接收一段 float32 samples 和 progress；callback 返回继续或停止。样本必须复制，转换为 int16 little-endian 后才进入发送队列。
- 流式 TTS 请求只发送一次 AudioStart(22050 Hz、16-bit、mono)；之后每个句子的 callback 产生 AudioChunk，多个句子共用同一音频流，不能每句重新发送 AudioStart。
- AudioChunk 的 rate/width/channels 与该次 AudioStart 完全一致；chunk 边界保持 16-bit sample frame 对齐。
- 不等待整句/整段音频生成完成再输出；第一块 PCM 到达后即可发送。
- 发送端不得在 callback 中直接执行网络写入；生成和网络消费必须解耦。

### 9.5 有界队列和背压

首期合同值：

- 每个活动 TTS 请求的 PCM 输出队列上限：**128 KiB**。
- 单个发送 AudioChunk 的 PCM payload 上限：**4 KiB**，并保持 16-bit sample frame 对齐。
- 队列达到上限时采用背压暂停/阻塞当前 callback 的后续生产；不得丢弃 PCM、无界增长或把完整回答攒入内存。
- callback 应能在取消/断连时尽快返回停止状态；不可把正在等待队列的线程永久遗留。
- 若队列无法恢复或生产/消费任务失败，终止当前 TTS 请求并报告 Error。

### 9.6 流式结束和兼容语义

- 处理完 SynthesizeStop、提交最后缓冲句并确认全部 PCM AudioChunk 已按序写出后，服务发送 **SynthesizeStopped**。
- 流式完成标记必须是 SynthesizeStopped；不能只发送 AudioStop。HA Core 2026.11.0 的流式 Wyoming 接收器以 SynthesizeStopped 作为结束事件。
- 非流式请求继续使用 AudioStop；不得把两种结束事件混用。
- 不能在 SynthesizeStopped 之前结束 TCP 连接，也不能在正常完成后继续发送迟到的 AudioChunk。

### 9.7 取消和异常

| 场景 | 合同 |
|---|---|
| 收到 SynthesizeStop | Flush 剩余句子，等待全部 callback chunk 入队并发送，最后 SynthesizeStopped |
| HA 取消或连接断开 | 停止后续句子提交；通知 callback 停止；清空未发送队列；释放本请求任务 |
| 模型生成异常 | 发送 Error 并关闭请求；不得用 SynthesizeStopped 伪装正常完成 |
| 队列背压 | 暂停生产，不允许静默丢块 |
| 空文本请求 | 不调用模型生成空音频；返回 Wyoming Error 并结束请求，不构造虚假 AudioChunk 或正常完成事件 |
| 服务进程重启 | 旧 TTS 请求不恢复、不补播；HA 为新请求重新连接 |

## 10. 并发、状态和生命周期

- KWS、STT、TTS 的模型对象在服务启动时分别加载一次；运行请求不重新初始化模型。
- 每个 Wyoming 连接的 KWS Stream、STT Stream、TTS request、句子缓冲和 PCM 队列均为请求级对象。
- 不使用全局 self.audio、全局当前 TTS 请求或可被不同客户端覆盖的共享缓冲。
- KWS decode、STT decode_stream、TTS generate 都是阻塞型 Sherpa 调用，不得直接在 Wyoming asyncio event loop 中执行；放入有界 worker/executor 入口运行。每类模型的并发度先按第 4.5 节配置限制，同一模型对象在未证明线程安全前按请求串行执行。
- 当前产品按单 HA 用户、单 Tivoo Satellite 使用；P7A 不要求多家庭、多设备的并行推理 SLA。Describe/Info 探测不得等待一次长 TTS 合成完成。
- 允许 KWS/STT/TTS 在不同 TCP 连接上存在独立请求状态；若推理需要串行化，等待队列必须有界，取消请求必须能从等待队列移除。
- 单轮 KWS 完成后释放其 Stream；单轮 STT 在 AudioStop/异常后释放音频和 Stream；单轮 TTS 在 SynthesizeStopped/Error/取消后释放缓冲与任务。
- 容器退出或模型加载失败时不得保留旧会话状态；重启后重新加载模型并重新发布 Info。

## 11. 日志、可观测性与健康检查

### 11.1 必须记录的指标

- 启动：Sherpa/Wyoming/Python 版本、模型 ID、模型加载耗时、CPU provider、线程数、输出采样率。
- KWS：每次请求持续时间、处理音频时长、检测/未检测/错误结果、模型处理是否落后于输入音频。
- STT：输入音频时长、decode 耗时、RTF、返回空文本/非空文本/错误状态。
- TTS：完整文本字符数（不记录正文）、首句提交时间、首块 PCM 时间、各句合成耗时、队列峰值和背压持续时间、最终完成/取消/错误。
- 容器：启动成功、健康状态、重启次数、常驻 RSS 和推理期间峰值 RSS。

### 11.2 日志隐私

- 不记录原始 PCM/音频内容。
- 不记录完整用户转写文本或完整 TTS 回答文本。
- 不记录 API Token、Authorization、短时 URL 凭据；Wyoming 服务本身不需要此类 token。
- 可以记录请求类型、内部关联 ID、耗时、错误类别和模型版本。

### 11.3 健康检查

- 容器健康检查通过本地 Wyoming Describe 请求，必须取得包含 installed WakeProgram、AsrProgram、TtsProgram 的 Info。
- 仅 TCP 端口可连接但三个模型未加载，不算健康。
- 启动时任何必需模型失败，服务不应先启动一个只提供部分 Provider 的监听端口。

## 12. 合同矩阵与验收追踪

状态定义：MUST = P7A 必须实现；DEFERRED = 明确由 P7/P5/P6 承担；N/A = 不属于本服务。所有 MUST 当前状态均为 **待实现/待验收**，本文冻结的是接口和验收要求，不代表功能已经存在。

| ID | 提供方 → 消费方 | 合同 | 要求/验收证据 | 优先级 |
|---|---|---|---|---|
| P7A-C01 | P7A → 项目 | 一容器、一进程、单 Wyoming TCP 入口 | Compose 仅启动一个 sherpa-wyoming 服务进程；10400 同时提供三类能力 | MUST |
| P7A-C02 | HA → P7A | Describe/Info | HA 对单一 host:10400 能成功 Describe 并收到完整 Info | MUST |
| P7A-C03 | P7A → HA | Provider 发现 | 同一个 HA Wyoming Config Entry 创建 wake_word、stt、tts 三类实体 | MUST |
| P7A-C04 | P7A → HA | Info.wake | installed WakeProgram + 配置的 WakeModel；语言 zh-CN/en-US；ID tivoo-wake；phrase 与配置一致 | MUST |
| P7A-C05 | P7A → HA | Info.asr | Paraformer zh-small 2024-03-09；语言 zh-CN/en-US；requires_external_vad=true；不声明 transcript streaming | MUST |
| P7A-C06 | P7A → HA | Info.tts | Matcha Baker；仅 voice 0 / zh-CN；supports_synthesize_streaming=true 之前必须通过 C24–C30 | MUST |
| P7A-C07 | P7A → HA | 单一服务端口 | 10400/tcp 可达；不暴露 10500 或其它模型/API 端口 | MUST |
| P7A-C08 | 构建 → 运行时 | 依赖固定 | Sherpa-ONNX 2.0.1、Wyoming 1.10.2、Python 3.11 系列、CPU provider；依赖无浮动安装 | MUST |
| P7A-C09 | KWS 模型 → KeywordSpotter | 模型来源 | 官方 zh-en 3M 2025-12-20 release；chunk16/left64；模型文件 hash 清单存在 | MUST |
| P7A-C10 | 配置 → KWS | 关键词生成 | WAKE_WORD_PHRASE 经 text2token(phone+ppinyin)生成 keywords 文件；Info phrase 与 keywords 文件一致 | MUST |
| P7A-C11 | HA → KWS | Detect 请求 | 接受 Detect(names=["tivoo-wake"])；拒绝不支持的模型 ID | MUST |
| P7A-C12 | HA → KWS | KWS 音频输入 | AudioStart 16 kHz/16-bit/mono；AudioChunk 顺序、timestamp 保留 | MUST |
| P7A-C13 | KWS → HA | 命中结果 | 命中返回 Detection(name="tivoo-wake") 和对应时间戳；不返回 Transcript | MUST |
| P7A-C14 | KWS → HA | 未命中结果 | 正常无命中返回 NotDetected 并结束连接；不能无限挂起或伪造 Detection | MUST |
| P7A-C15 | KWS → HA | KWS 错误和取消 | 不支持格式/模型错误返回 Error；连接取消后释放独立 Stream | MUST |
| P7A-C16 | KWS → HA Pipeline | 阶段顺序 | 未命中不进入 STT/Conversation Agent；命中后进入 STT | MUST |
| P7A-C17 | STT 模型 → OfflineRecognizer | 模型来源和校验 | 使用 Paraformer zh-small INT8 2024-03-09；model.int8.onnx、tokens.txt 与既有 SHA-256 一致 | MUST |
| P7A-C18 | HA → STT | STT 输入事件 | Transcribe + 16 kHz S16LE mono AudioStart/AudioChunk/AudioStop | MUST |
| P7A-C19 | STT → HA | 最终 Transcript | AudioStop 后仅 decode 一次，返回一个最终 Transcript；不提供中间转写 | MUST |
| P7A-C20 | STT → HA | 空结果和错误区分 | 有效无语音可返回空 Transcript；异常、无效输入、超时返回 Wyoming Error | MUST |
| P7A-C21 | STT 请求 → STT 请求 | 会话隔离和缓存上限 | 两轮音频不串接；单请求默认最多 300 秒/9,600,000 bytes；超限 Error；取消/断开清理 Stream 和缓存 | MUST |
| P7A-C22 | HA STT Pipeline → P7A | 端点职责 | AsrProgram.requires_external_vad=true；由 HA 执行 STT 端点，P7A 不再实现第二套 VAD/KWS | MUST |
| P7A-C23 | TTS 模型 → OfflineTts | 实测配置复用 | Matcha Baker + 本项目 benchmark.py 相同 Vocos 22 kHz vocoder、FST、tokens、lexicon；不误用上游 HiFi-GAN 配置 | MUST |
| P7A-C24 | HA → TTS | 非流式兼容 | Synthesize → AudioStart/AudioChunk/AudioStop；有效 WAV 能由 HA 接收 | MUST |
| P7A-C25 | HA → TTS | 流式事件解析 | SynthesizeStart/Chunk/Synthesize/Stop；识别最后的完整兼容 Synthesize，不重复合成 | MUST |
| P7A-C26 | TTS → HA | 分句输入 | 中文/英文句末标点切分；长文本按 max_sentence_chars=80 回退；文本原顺序、无丢失/重复 | MUST |
| P7A-C27 | TTS → HA | Sherpa callback | 每句调用 OfflineTts callback；callback samples 复制、转换并进入输出队列；模型生成与网络发送解耦 | MUST |
| P7A-C28 | TTS → HA | PCM 格式 | 单次流一个 AudioStart；22,050 Hz、16-bit mono；所有 AudioChunk 格式一致且帧对齐 | MUST |
| P7A-C29 | TTS → HA | 有界队列 | 每请求 128 KiB、AudioChunk 最大 4 KiB；满载背压、不丢音频、不无限增长 | MUST |
| P7A-C30 | TTS → HA | 流式正常结束 | Flush 最后句、发送完所有 PCM 后发送 SynthesizeStopped；不能仅 AudioStop | MUST |
| P7A-C31 | TTS → HA | 取消/异常 | 断开时停止 callback/后续句子并清理请求；模型错误/队列错误返回 Error，不伪造正常结束 | MUST |
| P7A-C32 | 多请求 → 服务 | 请求状态隔离 | KWS、STT、TTS 和多个连接之间不共享可变请求状态；执行入口和等待队列有界 | MUST |
| P7A-C33 | 容器 → 模型目录 | 持久化 | 容器重建后模型无需重复下载；模型版本和校验清单可追踪 | MUST |
| P7A-C34 | 容器 → 运维 | 启动失败与健康 | 任一模型不可用时启动失败；Describe/Info 健康检查确认三类 Provider installed | MUST |
| P7A-C35 | 服务 → 运维 | 性能和资源证据 | 记录三个模型加载耗时、组合 RSS、KWS 实时处理滞后、STT RTF、TTS 首块/队列指标 | MUST |
| P7A-C36 | P7A → 网络 | 访问边界 | 只允许 HA 私网访问 Wyoming；不发布公网、不接 ESP32、不暴露 FastAPI 10500 | MUST |
| P7A-C37 | P7A → 日志 | 敏感数据 | 不记录 PCM、完整识别/回答正文、token 或短时 URL 凭据 | MUST |
| P7A-C38 | HA Pipeline → P3 Agent | 文字链路回归 | 使用测试音频验证命中后最终 Transcript 进入现有 P3 Conversation Agent；未命中不得触发 Agent | MUST |
| P7A-C39 | P7A → P5/P6 | 阶段依赖 | P7A 服务和 HA Provider 验收完成后，P5/P6 才以其作为稳定语音服务依赖 | MUST |
| P7A-C40 | Tivoo 实际麦克风 → KWS | 真实声学验收 | INMP441 位置、噪声、误唤醒率、漏唤醒率、距离和回声 | DEFERRED：P7 |
| P7A-C41 | ESP32 → HA | 物理音频传输 | I2S RX、AFE VAD、TCP 7778 MIC_PCM、Satellite 音频会话 | DEFERRED：P6/P7 |
| P7A-C42 | HA TTS Proxy → ESP32 | 设备音频播放 | HTTP GET、WAV 解码、PCM 缓冲、I2S DAC/AUX、TTS_STATE | DEFERRED：P6/P8 |
| P7A-C43 | ESP32 ↔ Tivoo | 屏幕/SPP 和硬件并发 | TCP 7777、SPP、显示控制、设备回执 | DEFERRED：P5/P6/P10 |
| P7A-C44 | P7A 容器 → AstrBot | 直接模型调用 | P7A 不直接连接 AstrBot、不持有 session_id、不调用 TTS 模型的 OpenAI API | N/A：禁止新增 |

## 13. P7A 验收标准

P7A 只有在以下所有 MUST 项均有可复现证据后才可标记完成。

### 13.1 服务和 HA 发现

- 容器在 NAS amd64 CPU 环境成功启动；三个模型一次加载并常驻。
- HA 只配置一个 Wyoming host:10400，即可发现一个 wake_word、一个 stt、一个 tts Provider。
- Describe/Info 包含全部三种能力且标记 installed；重启 HA 或 Sherpa 容器后能恢复连接。
- 未暴露 10500、未引入额外服务端口；ESP32 不直接连接该容器。

### 13.2 KWS

- 使用 Sherpa 官方模型测试 WAV 和配置的自定义中文唤醒词 WAV 完成检测。
- 负样本、近似词和无语音样本不应被错误映射为目标 Detection；阈值调优过程保留样本和记录。
- Detection.name 与 HA Info 的 WakeModel.name 一致。
- 未命中返回 NotDetected 并正常结束；HA Pipeline 不触发 STT 和 Conversation Agent。
- 命中后 HA Pipeline 进入 STT；音频缓冲使唤醒词后的指令不会因检测延迟而丢失。
- 该阶段只证明固定测试音频的模型和协议能力，不证明 Tivoo 内部安装的 INMP441 误唤醒率。

### 13.3 STT

- 项目官方测试 WAV 的转写结果与既有基准一致；中英文混合样本能返回最终 Transcript。
- 同一请求只返回一个最终 Transcript；不出现增量假象。
- 多轮、空输入、异常结束、取消和模型错误均按合同区分并清理状态。
- HA 负责 STT endpoint；服务不把 ESP32 idle VAD 当作 STT endpoint。

### 13.4 TTS

- 非流式合成可以通过 HA Wyoming Provider 返回有效音频。
- 流式测试中，HA 尚在发送后续句子时，首句已开始合成；callback 产生 PCM 时能够立即输出 AudioChunk。
- 每个流只出现一个 AudioStart；多个句子按原文顺序输出；重复兼容 Synthesize 不重复合成。
- 非流式使用 AudioStop，流式使用 SynthesizeStopped；两种路径分别通过 HA Core 2026.11.0 接收代码验证。
- 长回答队列有界、背压生效、没有丢块或重复块；取消后不再输出迟到音频。
- 输出采样率为 22,050 Hz，Matcha 实测配置与 Vocos vocoder 校验一致。

### 13.5 资源与恢复

- 记录三模型同时常驻时的 NAS 实际 RSS 和 CPU；不得拿 STT/TTS 分开测试 RSS 推断组合服务内存。
- KWS 连续音频处理不持续落后输入；STT/TTS 推理耗时记录并与既有 NAS 基准对照。
- 模型目录持久化；模型损坏或依赖缺失会明确阻止服务进入健康状态。
- 服务进程重启后只恢复模型，不恢复旧音频/文本请求；新连接可正常使用三个 Provider。

### 13.6 P7A 最终阶段门

P7A 完成后必须能得到一个清晰结果：**NAS 上一个可独立运行的 Sherpa Wyoming 容器，HA 用一个 Wyoming Config Entry 同时获得中文/英文 KWS、Paraformer STT 和中文 Matcha TTS。**

此结果是 P5、P6 的语音服务前置条件。P7A 完成不代表 ESP32 麦克风、真实 Tivoo 唤醒、TTS AUX 播放或完整 P7 已通过。

## 14. 当前已知限制和后续验证

- Sherpa KWS 官方中英双语模型提供 chunk-16 与 chunk-8 变体；本矩阵选 chunk-16 作为准确度优先的初始配置，之后是否换 chunk-8 必须用相同负/正样本对照。
- 现有 KWS 模型基准资料不是 Tivoo 机内麦克风样本；P7 阶段必须补录实际噪声环境和安装位置音频。
- Paraformer 既有测试无人工逐字真值和 CER/WER；不能把 RTF 或官方样例结果描述成真实识别准确率。
- Matcha NAS 基准证明整段生成快于实时，不等于 callback 流式首块延迟已经通过；PCM callback 与 HA 流式事件仍须专门验收。
- 三模型组合常驻的 NAS 内存峰值尚未测量；不得沿用分开模型测试的 RSS 当组合值。
- Wyoming 没有本项目的认证层；必须通过 Docker/NAS 私网限制访问，不能对公网开放。

## 15. 实现阶段与文档关系

- P7A 实施批次计划应以本矩阵为合同依据，并引用现有 STT/TTS 链路规格、HA Core 2026.11.0 源码和上述模型基准。
- P7A 实施不修改 P3 HTTP/SSE 合同，不复制 P3 的会话状态，不改变 P5/P6 通信字段。
- P7A 完成后，更新本矩阵验收状态和 README 阶段状态；未通过的设备声学验收仍保持 DEFERRED，不提前标记整个 P7 完成。
- 本文只定义合同和验收门，不包含代码实现、实现批次拆分、NAS 部署执行或真实设备测试。
