# P6.8b0.4 本地唤醒、HA STT 会话与短提示音规格及合同矩阵

> 2026-11-18；基线 9dd72ce。上承 [总体设计](2026-11-18-p6-8-b0-1-overall-design-baseline.md)、[硬件/桥接](2026-11-18-p6-8-b0-2-hardware-uart-spp-design.md)、[音频/AFE](2026-11-18-p6-8-b0-3-audio-afe-design.md) 与 [路线](../plans/2026-11-18-p6-8-s3-local-wake-roadmap.md)。仅设计 b5–b6 所需的接口和时序，不实施；打断、续聊授权、TTS owner、表情完整状态机归 b0.5，各行的生产验收尚未进行。

## 1. 真实生产基线及上游接口

2026-11-18 经 NAS SSH 只读核对（IPv6 host key 与已知 NAS IPv4 的 ED25519/ECDSA 指纹一致）：HA 容器镜像 ghcr.io/home-assistant/home-assistant:2026.11.0；Sherpa 镜像 ghcr.io/qyxx2/tivoo-sherpa-wyoming:sha-d320db56187431b46720b3117e791f42c3733e34，Wyoming 1.10.2。HA .storage/assist_pipeline.pipelines 的 preferred 为 Astrbot，conversation_engine=conversation.astrbot，prefer_local_intents=true，语言 zh，STT=stt.sherpa_onnx_paraformer（zh-CN），TTS=tts.sherpa_onnx_matcha_baker（zh-CN, voice 0），旧 wake= wake_word.sherpa_onnx_wake_word/tivoo-wake。另一 Home Assistant 英文 pipeline 没配置 STT/TTS。实体注册表有 assist_satellite.tivoo，无 Tivoo pipeline select。两个 custom_sentences/zh-CN/tivoo_colloquial.yaml、tivoo_local_fastpath.yaml 存在；本批不重做句式、不执行实体命令。不能根据 pipeline 数量断言手机/其他客户端从不使用旧 STT。保持原 preferred 及其它消费者的行为。

依据当前容器 /usr/src/homeassistant/homeassistant/components 内源码及开发机同版 .venv：

- assist_satellite/entity.py:442–555 的公开 async_accept_pipeline_from_satellite(audio_stream, start_stage=STT, end_stage=TTS, wake_word_phrase=None, *, context=None) 先取消既有 run、保留 chat session/device/satellite/context、处理 wake intercept/ask_question、设置内部状态、转发 Pipeline 事件。它调用 assist_pipeline.async_pipeline_from_audio_stream，并且只构造 AudioSettings(silence_seconds=self._resolve_vad_sensitivity())；不能向该方法传 is_vad_enabled / audio_settings 参数。_resolve_pipeline 取 pipeline_entity_id 所指 select 的名称，否则取 preferred。现 Tivoo 未提供此 select。
- assist_pipeline/__init__.py:100 起的 async_pipeline_from_audio_stream 支持 AudioSettings；models.py:133 起的 AudioSettings 默认 is_vad_enabled=True、noise/auto gain=0、volume=1。直接调用该下层函数可通过 is_vad_enabled=False 关闭 microVAD/segmenter，却不会自动完成上层 Satellite state、chat session、ask_question、intercept 和取消任务管理。禁止伪造私有字段或复制整个 Core 方法、全局 monkeypatch、修改 HA Core。
- assist_pipeline/default_pipeline.py:402–533 实际条件是 audio_settings.is_vad_enabled AND stt_provider.audio_processing.requires_external_vad 才创建 VoiceCommandSegmenter；vad.py 当前默认 0.3s speech、1s 最小 command、0.7s silence、15s timeout。STT_START 在调用 Provider 前发送，仅代表已到 STT 阶段，不证明 Wyoming socket 已建立。_speech_to_text_stream 无 segmenter 时逐块 yield 到自然 EOF，不产生 STT_VAD_START/END；有 segmenter 时可能在 yield 前 break、提前截断剩余数据。1051 起的 process_enhance_audio 按 10ms 块处理，余数不自动 flush；在仍启用 microVAD 情况下，确保末尾 PCM 为完整 10ms（本协议统一20ms）。
- wyoming/stt.py 的 WyomingSttProvider 从 Describe/Info 的 AsrProgram.requires_external_vad 建立 SpeechAudioProcessing，async_process_audio_stream 连接后先写 Transcribe 和 AudioStart，再分别启动上传和接收任务；_async_upload_audio 正常迭代完毕写一次 AudioStop，取消不应伪装正常 EOF。STT_END 在成功且有文本时产生。services/sherpa_wyoming/run.py build_wyoming_info 当前明确 requires_external_vad=True，supports_transcript_streaming=False；providers/stt.py 每请求先 create_stream、AudioChunk 接受16k s16 mono，AudioStop 才最终 decode_stream 一次；不把提前建立请求宣称为提前解码。已有 BoundedExecutor 单模型单 worker/有限 pending 保留；服务端默认最大300s/9600000B仅兜底，不是命令窗口。
- 开发机最小验证：.venv HA 2026.11.0，附加 .venv-sherpa 的 Wyoming 1.10.2 package 路径（没有安装/修改环境）；调用真实 _DefaultPipelineProcessor._speech_to_text_stream 与真实 _async_upload_audio，用内存 mock host/TCP writer、200块×10ms 标记 PCM（64,000B，前1s speech 后1s silence）。无 segmenter: 全64000B逐字节一致、无 VAD 事件、最后恰一次 AudioStop；默认 segmenter: 54080B、STT_VAD_START/END、恰一次 AudioStop，证明会先截断。该试验仅证明 EOF 与 segmenter 条件的路径，不是实际完整 Pipeline 或声学 PASS；首次尝试 .venv 缺 Wyoming import，使用已存在依赖路径重跑成功。
- 项目原 transport.py 的 MIC_PCM 依赖当前唯一 session 和 TCP 顺序；audio_session.py 现 persistent session 的 async_end_session 会触发 coordinator.on_end 取消整个 Pipeline，release_subscription 会立即结束 cursor，不能直接拿任一方法当设备正常断句；当前 assist_satellite.py 依赖 HA STT_VAD_START 标记 command_started/取消5s timer，STT_VAD_END 释放订阅，必须按新事件改造，不能等不存在的 HA VAD 事件。

## 2. STT 路径裁决：保留公开 Satellite API，不全局关闭 HA VAD

主路径采用同一 Sherpa 进程、同一个已加载 Paraformer 与同一 STT executor，新增一个仅供设备已断句 PCM 的 ASR-only Wyoming 入口。该入口独立 Describe，ASR 名称区分旧 Sherpa，requires_external_vad=False、supports_transcript_streaming=False，其余模型/语言/PCM 格式不变；仍使用原 STTProvider/STTSession，不修改模型推理或增加第二份模型，不启动第二个容器。现在 run_server 已支持 AsyncTcpServer 与共享 handler_factory/ModelExecutors；b5 给两个 listener 分别绑定 info，第二入口只接受 Describe 与 STT 请求，不暴露 wake/TTS，不自动发现给其他设备。保留现有10400的完整三 Provider 与 external VAD=true；新 listener 端口选择在 b5 依据实际 Docker 网络端口占用及 compose 配置核验（10401 为候选非现有端口），只在同一 HA 内网可达、不向公网上开放。新增 listener 启停、健康和失败清理归 b5；b9 再依据其他消费者证据决定旧 KWS/旧入口清理。HA Wyoming config_flow.py 的手工入口实际按 host/port 创建 config entry；旧 entry 不改名、不迁移 unique_id；额外实体只在部署后按实际 entity_id 选择，禁止预编造 ID。

为 Tivoo 建立专用 Assist Pipeline（复制上述 Astrbot 的语言、conversation、prefer_local_intents、现有 TTS/voice；STT 改选设备断句 entity，wake provider 不参与）。使用 HA assist_pipeline/select.py 的 AssistPipelineSelect(hass, domain, unique_id_prefix, index=0) 与 AssistSatelliteEntity.pipeline_entity_id 公开属性接入标准选择；真实注册实体 ID 由 registry 得到，不硬编码。仅本地 wake 协议模式必须验证所选 pipeline 的 STT 满足设备端点合同；未配置、选错 legacy provider、服务不可用时报明确错误并回待机，不私自修改系统 preferred 或回退远程 KWS。legacy 固件仍用原流程、原 pipeline（并存期避免从新 select 把旧 wake run 送到已断句 provider；b5/b9 按能力隔离）。正常入口仍是 async_accept_pipeline_from_satellite(..., start_stage=PipelineStage.STT, wake_word_phrase=实际官方检测词, context=turn.context)，续聊不伪造唤醒词；保持 P3 及本地 intent、ChatLog、AstrBot SSE、用户已有新对话入口与真实 TTS。

此方案的取舍：第二 listener + Tivoo 专用 pipeline，而非修改共享服务 metadata 影响其他设备、或复制 HA Satellite 内部方法；上游接口已经核对，尚无新增 listener/完整 pipeline 实测，b5 实施前先用开发机真实 HA+假 Wyoming endpoint 验证完整 STT_START→无 HA VAD 事件→尾 PCM→AudioStop→STT_END→只读本地 intent/模拟 AstrBot，验证同一模型服务双 socket 不重复加载并隔离并发。HA 仍可能计算 microVAD 概率（AudioSettings 默认 true），但不使用它截断；不保证消除该计算开销。若完整验证失败不得声称本地端点已生效：先定位源码/配置，必要时另审使用公开低层 AudioSettings(is_vad_enabled=False) 的方案及上层会话兼容；不把旧 HA VAD 双重断句当正式验收。无需在 b0.4 改 HA 或部署。

## 3. 7778 私有 TVIO 合同（以下新增字段/消息是本项目设计，不是 HA 上游接口）

沿用 b0.2 TVIO v1 16B header、JSON/opaque PCM 长度限制、TCP 序号/方向、HELLO/ACK、heartbeat、旧 7777/SPP/资源接口。现 diagnostics.py/h 中 0x20–0x24 已用，0x25/0x26 未分配给 TVIO（SPP 私有命令命名空间独立）；本地模式 HELLO 新 capability local_wake_stt_v1，双方匹配后才启动新合同。旧固件没有该能力时保留原合同；新固件遇不支持的 HA 不发送环境 PCM/不假装 ready，报告不兼容。b5 双向实现并测试能力协商，b9 再移除旧模式；不同时跑两套 KWS。HELLO_ACK 在现 accepted/reason schema 增加可选 capabilities 数组，仅新 capability 请求才回显该数组，旧固件仍接收原样 ACK；S3 必须收到该能力回显才允许新语音，保留旧 ACK 兼容性；不能只根据 TCP 已连接判断 HA 已支持。

| 消息/方向 | 本地模式 payload 与语义 |
|---|---|
| 0x20 MIC_SESSION_START S3→HA | 复用已有 UUID session_id, sample_rate=16000, channels=1, sample_format=s16le, frame_duration_ms=20, preroll_ms=0（确认时尚无命令前导），trigger_source=local_wake；新增 wake_word_phrase（实际官方模型确认字符串，非固定旧词）、uptime_ms（设备单调时钟）。这是确认唤醒事件及开轮的合一入口，仅真正 WakeNet 确认发一次；无独立重复 wake 事件。续聊的 local_followup 入口和授权见 [b0.5 生命周期与表情合同](2026-11-18-p6-8-b0-5-lifecycle-display-design.md) §2/4，在该模式必须区分真实 wake。 |
| 0x25 STT_READY HA→S3 | JSON session_id，仅在当前 STT Provider 已开始 pull 本轮 iterator 时发送一次；实际 Wyoming 路径已先写 Transcribe/AudioStart，STT_START 不作为 ready。以背景发送避免阻塞 RX。失败使用既有 MIC_CAPTURE_STOP；不是 HA 指令执行确认。 |
| 0x26 COMMAND_GATE S3→HA | JSON session_id, uptime_ms, prompt_result（completed/skipped/failed）；按本轮物理 prompt drain+标定尾部或确认无输出且无尾巴之后发一次，表示可开始命令（HA 可能仍正在准备）；不是实际 speech_start。 |
| 0x24 MIC_ACTIVITY S3→HA | 保留 session_id,state=speech_start/speech_end,uptime_ms；speech_end 新增 pcm_samples（累计实际已发送样本，含最后补零）。仅在 gate 后有效 VADNet 事件；start 必须先于该轮 PCM，end 必须在全部尾部 PCM 的同一 TX FIFO 之后，禁止照搬旧前端每帧活动事件先于该帧 PCM 的 end 排序。 |
| 0x21 MIC_PCM S3→HA | 保留无 JSON header 的 640B（320样本×s16LE），单活跃命令及可靠 FIFO 关联；仅 local_wake/local_followup 的合法 gate+speech_start 后发送，不能拼接另一 UUID。末尾不足320样本以零补齐到完整20ms，记录 valid/padded 数量于设备诊断；不因 padding 产生新 speech。 |
| 0x22 MIC_SESSION_END S3→HA / 0x23 MIC_CAPTURE_STOP HA→S3 | 保留 session_id,reason；用于完整轮次结束/取消/失败（含 timeout/overflow/disconnect），匹配 UUID，不当作正常 STT EOF。S3 发送 speech_end 后保持该轮身份直到完整生命周期结束；正常语音之后仍允许 TTS/Intent。b0.5 定正常回复后释放、重新唤醒及旧 owner 停止顺序。 |

一条诊断连接 epoch + session UUID 绑定一个 HA _Turn/Context 与当前唯一 ingress，后续 playback ID 映射见 [b0.5 生命周期与表情合同](2026-11-18-p6-8-b0-5-lifecycle-display-design.md) §2；Context 不在 S3 伪造。仅同一 epoch+当前 UUID 可推进状态，重复 start/gate/活动/ready 不重新启动 pipeline 或播放（幂等/诊断）。同 TCP 内 MIC_PCM 不额外加 UUID，必须由唯一发送队列按 session 管理：新 start 前丢弃旧未发帧或先完成合法旧帧终止；不允许旧 PCM 排在新 start 后。重连丢掉旧连接队列/身份，不重放旧唤醒。b5 校验 payload 类型、UUID、enum、非负时钟、整帧、字节计数、方向，未知/越序失败只影响语音轮，不影响 SPP。speech_end 必须在 FIFO 最后有效数据之后且计数准确，否则取消该轮（不能将截断语音交给 Intent）。

## 4. 正常时序、缓冲、终止与超时

1. 待机 AFE/WakeNet 常驻，零 MIC_PCM、零候选 MIC_SESSION_START。确认→设备生成 UUID、tail/history 清除、发 0x20；并行开始本地 ready，不等 HA 网络往返。HA 立即为该 UUID 创建 bounded ingress/订阅并启动 STT run，设备不上传 wake tail 或提示音。HA 旧 WAKE_WORD_END/watch_wake_word/3s miss/15s候选流程在本地模式不运行。
2. 设备 prompt gate 内 RX/AFE/AEC/真实 TX reference 继续，屏蔽命令 VAD 事件及该提示音自身的 wake 确认；丢掉该 gate 内的历史/candidate，恢复时按 b0.3 样本时间轴剔除处理延时跨 gate 的旧样本。COMMAND_GATE 从物理安全边界起算；不能因 STT_READY 未到而在用户听完时继续无声地丢弃命令。gate 后立即开始有效 VAD/前导收集；若 HA 未 ready，在设备本地有界暂存，ready 才按序发送 start+preroll+PCM。先到 ready 则无额外等待。gate 与 ready 两者必需，start 不早于两者；事件在同队列顺序发送。
3. 沿用 b0.3 的 25帧/500ms 前导、50帧/1s (32KB) ring 初始上限，前导不得跨 gate。HA 在准备期间等待 iterator，设备最多保留1s未发送命令（包含已选前导与尾帧，不能覆盖未发样本）；gate 后最多1s等 STT_READY，未 ready/缓冲将溢出即取消（不丢首音后继续识别）。1s 是依据既有 ring 容量的初设，不是网络实测；b5/b6 记录 ready P50/P95、最大 pending、失败率，必要时依据内存与实测仅调整该限。若 speech_end 早于 ready 且所有有效音频在限内，ready 后依次 flush start/PCM/end；不得提前发 end。HA 保留现有有界 cursor/480000B 未消费上限，溢出取消，不阻塞 transport reader；不得在建立订阅前把可用历史丢弃。
4. 首次命令等待3s自 COMMAND_GATE 实际设备时刻，不从 STT_START 或 KWS 候选开始；speech_start 取消3s timer。HA 根据 gate 事件接收时刻设置失联监察，设备单调时钟为执行权威；HA 监察须容纳有界 ready 缓冲及正常传输偏差，不能先于设备的有效命令窗口取消。跨时钟不直接相减。gate 前 prompt fault watchdog 上限沿用原5s；超时必须定向停止并确认/排尽物理输出，若无法确认安全 gate 则失败回待机，不能无限等。命令持续时间初始上限15s（继承 HA 旧超时数量级，以有效 speech_start 起计，前导最多0.5s），超时/无命令/断连/AFE gap/HA 错误取消，不把不完整指令作为正常 EOF 提交。后续4s followup 计时自独立嘟声安全 gate，具体授权/交接与启动 STT 的方式归 b0.5；不得沿用现 _open_followup 先计时再播放的偏差。
5. speech_start 成为 command_started 与 listening 的真源，取消 HA 对应命令等待监察 timer；无 HA STT_VAD_START 的正常路径不能误判 pipeline_failed。S3 VADNet speech_end（b0.3 初始500ms静音）冻结本轮 end offset，按 FIFO flush 最后完整 PCM→MIC_ACTIVITY speech_end(pcm_samples)。HA 验证收到计数与边界，标记本轮 PCM input_finished/最终 offset，iterator 继续 drain 所有未读数据，到 final offset 后正常 return。不得在 speech_end 立刻 release_subscription 或 _finish_session/on_end；这两者分别会跳过未读数据或取消 pipeline。单独区分 input EOF vs whole turn cancellation。Wyoming 正常生成一次 AudioStop，Sherpa 解码一次，STT_END 仅非空有效命令流入既有 intent；空/错误无 TTS owner/续聊，及时释放。取消需先使旧 iterator/pipeline 失效而非让未完成输入正常 return，避免断线后触发残缺命令；b5 要覆盖取消期间 AudioStop/Transcript 与新 run 不串轮。
6. 原 HA PipelineTtsEvents/正常资源流/真实 playback owner 保留（32k mono，URL/代理与长 TTS 间隙不变）；S3 不直接访问 STT、LLM、TTS 服务。HA 原意图优先本地，未命中才 AstrBot。普通 TTS 期间保持 WakeNet，不开启命令 VAD 上传；收到本地真实 wake 才交 b0.5 定向取消，不以候选/VAD/提示音完成取消旧 TTS。故障报告脱敏，不上传持续环境数据。b5 首批可以用测试 prompt 验证 gate，量产真实资产/drain/声学留 b6。

## 5. 本地短提示音：素材、流程及验收

沿用生产既有素材，NAS /config/www/tivoo/prompts 与 repo homeassistant/prompt_assets 下四个 MP3 的 SHA256 全一致。三条 ready 来源见 [P6.7b0](../reports/2026-11-16-p6-7b0-assets-and-static-url.md)，生产 Matcha Baker + Vocos，22.05k、sid=0、speed=1.0；11-17 phase report 的“嗯？”已被 d79775f 更新为独立正弦嘟声，不能用旧报告哈希/音频。开发机 ffprobe/ffmpeg 实际解码为 s16le mono 32k，以下为源文件和无头 PCM 试验大小（未写入新文件、未播放）：

| 文件 | 内容 | PCM bytes / 秒（32000×2B/s） | 源 MP3 SHA256 |
|---|---|---|---|
| ready_01.mp3 | 我在 | 47402 / 0.740656 | 17727761db1100511d7728038d5212ec896e1aa141e666283a1c474d12e92d80 |
| ready_02.mp3 | 在的 | 47784 / 0.746625 | f4e90f5588f87d23b49adf76fca2907422bf92e41da77ab76b8c352326a88c67 |
| ready_03.mp3 | 你说 | 53254 / 0.832094 | 22e7ec8ce43ee406de94f95b46a988ac7a44cf0c838d93b05cfed80a166634a7 |
| followup_01.mp3 | 单次嘟声 | 30720 / 0.480000 | 67b5d7ccced82fa74b52dc0e0fe56388dbc6386022f662f54f855b66674cb978 |

总 PCM 179160B（约175KiB），设计使用构建时从上述源生成并嵌入 S3 app flash 的只读 PCM，不占 model 分区、不运行时解 MP3 或联系 HA、不全部读入 SRAM；b6 记录源/目标 hash、FFmpeg 版本和确定性转换命令（-f s16le -ac 1 -ar 32000），检查 app image/partition 余量，短块按现 output API 消费。三个 ready 随机相邻不重复，首次 wake/确认打断各一次；follow-up 只用固定 beep，可重复。缺少资产只静默跳过不跨池回退，不在运行时生成。保持头尾静音及完整语音、音量与当前 production 同音色，b6 真人在听到最后声音后自然开始说话时须无漏首；若源资产剩余静音与新布局声学尾部叠加导致漏首，依据实际波形减少多余静音并重做不截断/声学负样本验收，不直接照抄旧48ms。

唯一 audio_output_manager，现 audio_output_manager.h 已有 tivoo_audio_output_begin/write/finish_input/drained/stop/end(generation)，使用同一 DMA、最终 TX 参考及独立短提示 owner（与正常回复 ID 不混）。已知有限 PCM 不额外等待旧网络预填时长，优先验证 b0.3 的首声目标。gate 持续至最后有效 DMA 排尽 + 本机重新标定的声学尾部，不能用 playing/completed 网络到达时间或固定 sleep 代替；AFE 边界依 b0.3 的 16k 样本轴，保留真实 R。提示音终态不得产生普通 TTS AUDIO_STATE/回答完成/聊天或显示 speaking；COMMAND_GATE 单独通知。不存在旧 audio owner 或已确认释放才播放，旧 TTS cleanup/stop 定向、提示音失效/正常 TTS 仲裁由 b0.5。仅 b6 为本地缺失/失败不影响已授权正常收音（已确认无声才 skip）；普通长 TTS 禁套提示 gate。旧 HA HTTP prompt/PromptSoundPlayer/suppress_vad 只在 legacy 路径保留，b9 迁移清理；正常 TTS URL 范围保持。

## 6. 合同矩阵（设计出口；实施验收均未执行）

| 新合同 | 不变量与判定 | 实施/验收证据 | 原合同/来源 |
|---|---|---|---|
| VOICE-C01 | 握手区分 local_wake_stt_v1/legacy；待机零 PCM，无候选远程 KWS，确认新 UUID 单次 | b5 两端 codec、未知能力/重连/重复/乱序/旧固件，b9 清理，b10 抓包 | P6-C05–C11、P65-A02/A03、P7A-C09–C16 |
| VOICE-C02 | local wake 仅 STT→TTS，保留 Satellite/chat/context 及本地 intent 优先、AstrBot fallback、普通 TTS | b5 真实 HA pipeline mock Provider、只读本地状态/模拟 LLM，b10 实机 | P3-01–P3-12（相关保留项）、P7A-C38、H17 |
| VOICE-C03 | 独立 ASR metadata=false/shared model 与 executor；legacy true；Tivoo 专用 pipeline 选择正确，拒绝错配 | b5 双 Describe、隔离注册/并发/失败 health、真实 HA 完整 stream 至一 AudioStop；其他客户端旧 VAD 回归 | P7A-C05/C17–C22、P65-A05 |
| VOICE-C04 | 唤醒→提示与 STT 准备并行，真正 pull 才 ACK ready；gate 后收音不丢首，有界 ring/超时 | b5 STT_START 不等于 ready、ready 前后/早端点/阻塞/overflow/fast command，b6 真人自然抢首，b10 延迟 | P65-A04/A06、PR-C01/C02/C03/C19、AFE-C10 |
| VOICE-C05 | 有效 gate、speech_start、ordered PCM、尾部 padding、speech_end sample count、无提示/旧帧 | b5/b6 标记数据逐字节、20ms/10ms 对齐、cache 去重、末帧与 end 同包、错计数 abort | P6-C11、P65-A05/A06、P7A-C18–C22/C41 |
| VOICE-C06 | input EOF 不取消全轮，完整 drain 才正常 return/AudioStop/一次 decode；错误和取消不执行残缺指令 | b5/b6 real HA→fake/实际 STT、无 VAD 事件、短词/长词/断开/空文本/晚 transcript，b10 | P7A-C05/C17–C22、P65-A05/A06 |
| VOICE-C07 | 首次3s 从 gate、15s 命令、准备/播放/网络失败有界；续聊4s 独立 gate 由 b0.5 授权 | b5/b6 fake clock/ready race/3s 无命令/长命令/timeout，b7 4s followup，b10 | P65-A04–A06/A10–A13、PR-C02/C03/C19 |
| VOICE-C08 | 已核验四源素材，构建 PCM flash、ready 相邻不重复、followup beep 独立，不用网络 | b6 hash、解码/Flash 分区容量、随机/缺失/不跨池、断 HA 不产生远程请求，b10 | PR-C07–C10/C21、H11 |
| VOICE-C09 | 本地 prompt 共用唯一 DAC/实时 TX，drain+重新标定后开放 gate；不停止 RX/AFE，不扩大普通 TTS gate | b6 输出/声学/提示自触发负样本、真实首声和首尾，b3/b4 参考回归，b7 打断 | PR-C06/C11/C15/C17/C18、AFE-C03/04/05/09 |
| VOICE-C10 | 本地 prompt 与真实 TTS/显示/续聊终态分离，旧 UUID/断连不抢占；普通 TTS、长音频无退化 | b6 独立事件，b7/b8 owner/表达式矩阵，b10 端到端 | PR-C01/C04/C05/C12–C16/C20、P65-A08/A10–A16、H08/H10/H11 |

P7A-C22 从旧 HA VAD end 迁移为设备端点→迭代器 EOF→原 Wyoming AudioStop；未改 P7A 模型/格式/请求隔离。P3、P6/P7A 其它保留项仍按 [旧合同迁移索引](2026-11-18-p6-8-legacy-contract-migration-index.md)，本表不是旧 ID 的完整核销。b0.5 对以上事件/UUID/gate 的次序、follow-up 与 stop/owner/显示作跨域补充；b0.6 统一审阅每个旧 ID 及实现批次。开发机同版最小验证与 NAS 只读基线是设计证据；新 listener、真实完整 pipeline、物理 prompt、实际延迟均待实施 gate。本批无生产代码、配置、服务、刷机、语音或设备状态变更。
