# P6.8 B8.8：Sherpa STT → HA 本地意图 → Qwen 文本回退合同矩阵

> **状态：仅合同设计，未实施。**
> 基线分支：`feature/p6-8-s3-local-wake`，基线提交：`3e13378`。
> 本矩阵定义 B8.8 输入侧路由、HA 本地反馈与生命周期边界；**允许为本地成功/失败 ACK 做最小 S3 固件扩展，但现有 Qwen 音频输出链路与调度继续硬冻结**。
> Qwen 接口用途以 QwenAudio/qwen-audio-agent **v2.1.0 / commit a9f4478da8df400d04facbb099ac2933ce8b11bc** 源码为准，不依据事件名猜测用途。

## 1. 目标与非目标

目标链路固定为：

```text
ESP32-S3 local wake / VAD
        │
        │ 16 kHz mono PCM16（沿用现有 MIC_PCM）
        ▼
HA AudioSessionManager
        │
        │ 原有 audio_subscription，禁止新增重分块/重切割层
        ▼
Sherpa Wyoming device-endpoint STT
        │
        │ final transcript
        ▼
HA Core 本地 sentence trigger / local intent
        │
        ├─ 命中：HA 本地执行，本轮不进入 Qwen
        │
        └─ 未命中：同一 final transcript
                      │
                      ▼
             Qwen Audio Agent GCP 7.0
             conversation.item.create
                      │
                      ▼
             RealtimeInputRuntime.submit()
                      │
                      ▼
             frontend.sendUserInput()
                      │
                      ▼
             qwen3.8-omni-flash-realtime
                      │
                      │ 现有 audio.delta
                      ▼
          【冻结】现有 HA PCM 输出/HTTP/TTS_PLAY/S3 播放链路
```

B8.8 不做以下事项：

- 不改 WakeNet、AFE、双麦、VAD、AEC、S3 PCM 上传协议、S3 播放任务、Wi-Fi 调度或固件 task/core/priority。
- 不新增第二条 Qwen 音频输出路径，不调整现有 PCM buffer、HA SRC、HTTP stream、预缓冲、播放回执或设备侧播放调度。
- 不把原始 PCM 在 Sherpa 识别失败/本地未命中后重新 replay 给 Qwen。
- 不新增关键词解析器代替 HA Core 的本地 intent。
- 不让 HA 客户端自行模拟 Qwen Provider 的 `conversation.item.create` / `response.create` 内部细节。
- 不修改 HA Core；仅允许 Tivoo HA integration 与 Qwen Audio Agent 侧做必要适配。
- 本文件不安排实现步骤，不修改 B8.7/B9 进度，只定义后续实现门禁。

## 2. 已核对的真实接口基线

### 2.1 当前 P6.8 / HA / Sherpa

| 证据 | 已确认事实 |
|---|---|
| `homeassistant/custom_components/tivoo/audio_session.py` | `AudioSessionManager.audio_subscription()` 用 ingress offset/cursor 直接消费现有有界 history；`_iterate_ingress()` 返回现有 history 中的 bytes，除起始 offset 必要切片外不做固定帧重切割。 |
| P6.8 B5 软件验收 | S3 local 模式已有 16 kHz / mono / PCM16、20 ms / 640 B 帧；真实 HA→Wyoming 测试验证 64,000 B 逐字节一致、一次 `AudioStop`、无 HA 二次 VAD 截断。 |
| `assist_satellite.py::validate_local_pipeline()` | local 模式要求专用 Assist Pipeline，STT 必须为 `WyomingSttProvider`，且 ASR 名称为 `Sherpa ONNX Paraformer Device Endpoint`、`requires_external_vad=false`、`supports_transcript_streaming=false`、无 HA wake provider。 |
| Sherpa `providers/stt.py` / `run.py` | Paraformer 为 offline recognizer；音频自然结束后由 `AudioStop` 触发最终 `decode_stream()`，不是边收边形成最终 transcript。 |
| HA Core 2026.11.0 `assist_pipeline/default_pipeline.py` | 非 Home Assistant conversation agent 且非 intent-only 时，Core 顺序为：sentence trigger → 在 `prefer_local_intents=true` 时 `conversation.async_handle_intents()` → 两者都未产生 response 才 fallback 到配置的 conversation agent。 |

### 2.2 Qwen Audio Agent v2.1.0：文本输入真实调用方法

以下均来自上游 tag `v2.1.0`，不是根据事件名推测：

| 上游源码 | 已确认调用语义 |
|---|---|
| `shared/protocol/gateway-client-protocol.mjs` | GCP 7.0 已实现 capability `input.text`；线上文本输入事件名为 `conversation.item.create`。该事件归一化为内部 `GatewayClientEvent.INPUT_MESSAGE`。 |
| `shared/protocol/gateway-events.mjs` | INPUT_MESSAGE payload 接受 `text` 或 `parts`；文本 part 的真实结构为 `{type:"text", text:"..."}`。 |
| `test/gateway-client-protocol.test.mjs` | 上游自己的协议测试实际使用 `conversation.item.create` + `parts:[{type:"text",text:"你好"}]`。 |
| `server/src/voice/realtime-session-runtime.mjs` | `INPUT_MESSAGE` / `TEXT_MESSAGE` 进入 `inputs.submit(event)`。 |
| `server/src/voice/realtime-input-runtime.mjs` | `submit()` 建立 manual input turn，发 `turn.started` / `voice.state=processing` / user `transcript.final`，随后调用 `ensureFrontend().then(() => getFrontend().sendUserInput(parts, inputContext))`。 |
| `server/src/voice/realtime-provider.mjs` | `sendUserInput()` 内部先 `applyUserInput(..., {contextOnly:false})`，再调用 `sendResponse()`；`sendResponse()` 最终由 Provider adapter 发 `response.create`。因此 GCP Client **只提交 `conversation.item.create`，不得再额外发送第二个 `response.create`**。 |
| `docs/gateway-protocol.md` | v2.1.0 文档将 `conversation.item.create` 定义为“Submit text, image, file, or mixed user input”；官方 hello 示例同时协商 `input.audio` 与 `input.text`。 |
| `shared/realtime-models/dashscope.mjs` | `qwen3.8-omni-flash-realtime` 是 v2.1.0 已注册的 DashScope Omni v2 realtime model。 |
| `docs/voice-frontends/qwen-omni-realtime.md` | Qwen3.8 Omni 在该 Agent 中使用 16 kHz 输入、24 kHz 输出和现有 DashScope realtime 路径。 |

B8.8 客户端线上最小文本提交合同固定为：

```json
{
  "type": "conversation.item.create",
  "event_id": "<current GCP client event id>",
  "parts": [
    {
      "type": "text",
      "text": "<Sherpa final transcript>"
    }
  ]
}
```

不新增、也不发送客户端侧 `response.create`。

## 3. B8.8 项目级合同矩阵

| ID | 合同 | 边界 / 必须满足 | 状态 |
|---|---|---|---|
| B88-C01 | **S3 只允许本地 ACK 最小扩展** | B8.8 的 S3 变更只允许：新增一个 HA→S3 本地 ACK 播放消息、两条固化成功/失败语音资产及其最小调度/测试。不得借此修改 WakeNet/AFE/VAD/MIC 上传、HTTP/Qwen playback、SRC、buffer、task 绑核/优先级或现有 prompt gate 时序。 | DECIDED |
| B88-C02 | **PCM 只走一次现有 ingress** | S3 的有效命令 PCM 仍进入现有 `AudioSessionManager`。B8.8 不增加“为了 Sherpa”或“为了 Qwen fallback”的第二份 PCM producer、第二个 TCP upload、二次录音、二次 ring 或完整音频复制。 | DECIDED |
| B88-C03 | **禁止新增 PCM 重分块层** | Tivoo integration 必须把现有 `audio_subscription()` 直接交给现有 HA/Wyoming STT 流。不得先聚合成新固定块、再切成新固定块、转 WAV、Base64、重采样或落盘后再送 Sherpa。允许的切片仅为现有 ingress cursor 起始 offset 所需切片及 HA/Wyoming 自身既有协议封装。 | DECIDED |
| B88-C04 | **设备端点 STT 合同保持** | 继续使用 B5 已验收的专用 `Sherpa ONNX Paraformer Device Endpoint`，`requires_external_vad=false`。S3 `speech_end` 只冻结输入边界；HA cursor 必须自然 drain 到 final offset 后才结束 STT 输入，Wyoming 正常只产生一次 `AudioStop`、Sherpa 只执行一次最终 decode。 | CONFIRMED / REUSED |
| B88-C05 | **Sherpa final transcript 是用户文本权威** | 只有有效、非空的 HA `STT_END.stt_output.text` 可进入本地 intent 或 Qwen fallback。Qwen 后续产生的 user `transcript.final` 是 Agent 对已提交文本的 Gateway 表示，不再作为“STT 成功”或“command_started”权威。不得等待 Qwen 回显后才开始 thinking。 | DECIDED |
| B88-C06 | **HA 本地识别必须复用 Core 语义** | 本地判断不得新增 Tivoo 关键词表或正则路由。语义基线是 HA Core 当前顺序：sentence trigger 优先；启用 `prefer_local_intents` 时再走 `conversation.async_handle_intents()`；只有这些本地路径未返回 response 才属于 LLM fallback。实现可以选择最小接入点，但最终路由结果必须与该 Core 路径一致。 | DECIDED |
| B88-C07 | **“本地命中”与“本地未命中”严格区分** | sentence trigger 或 local intent 已匹配即视为本地命中，本轮不得再把同一 transcript 送 Qwen。已匹配后 Service 执行失败、权限失败或目标不可用属于“本地已处理但失败”，不能改判为未命中再让 Qwen 重试，防止重复副作用。只有 Core 本地匹配阶段确实无 response 才允许 Qwen fallback。 | DECIDED |
| B88-C08 | **本地命中不创建 Qwen turn** | 本地命中时不得发送 `conversation.item.create`，不得把这轮命令写入 Qwen conversation history，也不得让 Qwen MCP 再执行同一控制。若为降低延迟已预先建立空闲 Gateway 连接，只允许关闭/保留连接级资源，不得伪造一个模型 user turn。 | DECIDED |
| B88-C09 | **Qwen handshake 增加真实 `input.text` capability** | B8.8 在现有 GCP 7.0 `session.hello` 上协商上游已实现的 `input.text`。为避免无关改变 voice/output session 行为，首版可保留现有 `input.audio` capability 与当前 connection voice/output 设置，但 B8.8 正常 fallback **不得调用 `input_audio_buffer.append`**。是否日后移除未使用的 `input.audio` 单独评估，不属于本批。 | DECIDED |
| B88-C10 | **Qwen 文本提交只用上游已实现事件** | fallback 只发送 GCP `conversation.item.create`，payload 使用上游测试覆盖的 `parts:[{type:"text",text: transcript}]`。必须携带现有 `event_id`。不发 Provider-native item，不使用内部 `input.message` 作为线上事件。 | CONFIRMED / DECIDED |
| B88-C11 | **客户端禁止额外 response.create** | Qwen Audio Agent 的 `RealtimeInputRuntime.submit() → frontend.sendUserInput() → RealtimeProvider.sendUserInput() → sendResponse()` 已负责创建 Provider response。HA 不得在 `conversation.item.create` 后自行再发 `response.create`，避免双 response / 双音频 / tool 流冲突。 | CONFIRMED |
| B88-C12 | **文本 fallback 复用同一 Qwen Agent 能力** | 文本输入后仍由当前 Qwen Audio Agent frontend、Prompt、persona/memory、Frontend MCP、tool call continuation 与 qwen3.8 realtime model 处理。B8.8 不新增第二个普通 LLM endpoint，也不绕过 Audio Agent 直接请求模型 REST。 | DECIDED |
| B88-C13 | **新 wake 与 follow-up 的 Qwen 上下文边界不变** | 独立新 wake 继续遵守当前“新上下文”策略；只有已授权 immediate follow-up 才复用当前保留的活动 Gateway WebSocket。follow-up 也先走 Sherpa STT + HA 本地 intent：若本地命中，不把文本送 Qwen；若本地未命中，才把 transcript 提交到原活动 socket，从而保留当前 Qwen 多轮上下文。 | DECIDED |
| B88-C14 | **允许连接准备与 STT 并行，但禁止提前提交用户内容** | 为降低普通问答延迟，Gateway socket/handshake/voice-ready 等纯连接准备可以与 Sherpa STT 并行，只要不改变现有 owner/lease 规则。HA 尚未判定本地未命中前，不得向 Qwen发送 user text、user audio 或创建 conversation item。连接准备失败不得影响已可本地完成的 HA 命令。 | DECIDED |
| B88-C15 | **无音频 replay fallback** | 本地未命中后直接提交 Sherpa transcript；禁止把已缓存的原始 PCM 再按实时速度或 burst replay 给 Qwen。也禁止同时“文本 + 同一音频”双输入。该合同用于消除二次音频时长、Provider VAD 再端点和额外分块带来的延迟与不确定性。 | DECIDED |
| B88-C16 | **失败默认 fail closed** | 空 transcript、Sherpa error、STT timeout、ingress gap/overflow、取消、session superseded、HA unload 时均不得进入 Qwen fallback。Qwen 文本提交失败只结束当前 LLM fallback，不回退为“再 replay PCM”。已本地执行的副作用不因后续生命周期异常自动重试。 | DECIDED |
| B88-C17 | **打断与取消沿用现有 owner/generation** | B8.8 不建立第二套 turn state。当前 MIC session_id、HA Context/generation、Qwen turnId/responseId、playback_id 的身份隔离继续生效。新 wake/取消只淘汰当前 owner；迟到的旧 Qwen audio/tool/transcript 仍按现有 generation/response 关联丢弃。 | REUSED |
| B88-C18 | **不以 Qwen user transcript 驱动本地 UI gate** | `ACTIVE_LISTENING → THINKING` 的输入成功依据改为 Sherpa final transcript + 本地路由结果；Qwen user `transcript.final` 不得再次触发 STT 成功状态。tooluse/speaking/playback completed 仍使用现有 Qwen tool 与设备真实播放事件。 | DECIDED |
| B88-C19 | **禁止重复 TTS / 重复音频 owner** | 同一 turn 的响应音频只能属于三者之一：S3 本地 ACK、HA 动态本地 TTS、Qwen fallback audio。`action_done/partial_action_done/error` 走 ACK 后不得再跑 HA TTS；`query_answer`/sentence trigger 动态回复不得再播 ACK；Qwen fallback 不得再触发 HA TTS 或 ACK。 | DECIDED |
| B88-C20 | **本地命中按结果类型选择反馈** | HA typed local intent 的 `action_done` 使用 S3 固化成功 ACK；`partial_action_done` 与 `error` 使用 S3 固化失败 ACK；`query_answer` 保留 HA 动态 TTS 以读出真实查询内容。sentence trigger 只有返回文本、没有 `IntentResponseType`，不得根据文本猜执行成败，继续使用其动态回复。所有本地命中都不得送 Qwen。 | DECIDED |
| B88-C21 | **延迟合同：不增加人为等待** | STT 为 offline Paraformer，B8.8 接受其现有 decode 成本，但 STT final 后不得增加固定 sleep、音频 replay、二次 VAD、二次 ASR 或“等待 Qwen user transcript”阶段。本地未命中判定完成后应立即提交 text；连接准备应尽可能并行隐藏。性能验收记录 wake/gate→speech_end、Sherpa decode、local-route、text-submit、first Qwen audio、physical playing 各阶段耗时，不用总时长掩盖新增等待。 | DECIDED |
| B88-C22 | **MCP 行为保持** | Qwen 文本 fallback 仍走当前 Audio Agent frontend tool flow，因此现有 HA Frontend MCP allowlist、tool.call 生命周期、工具结果续接与终态判断不改。HA 本地已经命中的控制不得再通过 MCP 重复执行。 | REUSED |
| B88-C23 | **输出链冻结** | 从 Qwen server event `audio.delta` 开始直到 S3 `AUDIO_STATE` 物理终态，B8.8 不得修改数据格式、SRC、HTTP resource、stream buffer、TTS_PLAY、S3 fetch/playback、预缓冲、writer、任务绑核/优先级、AFE/播放协调或完成判据。详见 §4。 | HARD FREEZE |
| B88-C24 | **范围只扩到本地 ACK 必需代码** | 除 Tivoo HA integration 的 STT/local-routing/Qwen input adapter 与必要 GCP capability/config 外，只允许修改 ACK 所需的协议常量、S3 本地资产生成、local-turn 短 prompt 调度和测试。不得借 B8.8 顺手重构 Qwen 输出、普通 HTTP playback、AFE 或无关 lifecycle。 | HARD SCOPE |
| B88-C25 | **HA typed result 的 ACK 分类固定** | `IntentResponseType.ACTION_DONE` → `success`；`PARTIAL_ACTION_DONE` 与 `ERROR` → `failure`；`QUERY_ANSWER` → dynamic local TTS。已匹配的失败仍是 local hit，不允许改判 Qwen fallback。 | DECIDED |
| B88-C26 | **S3 固化两条 ACK 资产** | 新增 `local_success_01`（语义/文案“搞定”）与 `local_failure_01`（语义/文案“操作失败”）。源素材沿用 ready 提示音的生产音色约束一次性生成，固化为仓库 MP3，并在固件构建时按现有 `generate_prompts.py` 流程冻结 hash/长度、转 32 kHz mono S16LE、放入 app flash；运行时不做 TTS、HTTP fetch 或 MP3 解码。 | DECIDED |
| B88-C27 | **本地 ACK 使用独立薄协议** | 当前 `0x28` 在项目协议中未占用，定义 `TYPE_LOCAL_ACK_PLAY = 0x28`。HA 发送 `{session_id, playback_id, result}`，其中 `result` 仅允许 `success|failure`；不复用 `TYPE_TTS_PLAY`，不携带 URL/mime，不重载 `STT_READY/FOLLOWUP_OPEN` 等既有语义。 | CONFIRMED / DECIDED |
| B88-C28 | **ACK 复用现有 output owner 并报告真实终态** | S3 必须在现有 fetch/local-turn 上下文中复用 `tivoo_audio_resource_prompt_begin()` / `tivoo_audio_output_begin_prompt()` / `tivoo_audio_output_try_write()` / drain/release，不从 diagnostic RX 直接写 I2S。ACK 使用现有 `playback_id` 关联并通过既有 `TYPE_AUDIO_STATE` 报 `playing/completed/failed`；terminal 还必须进入现有 `tivoo_s3_local_turn_playback_finished(...)`/等价完成路径，使 HA/设备双方都以物理终态完成本轮/续聊 gate，不得用估算时长代替 completion。 | DECIDED |
| B88-C29 | **ACK 失败不升级为 Qwen/动态 TTS 重试** | 本地 intent 已执行成功或失败后，ACK 只是反馈层。ACK 消息发送失败、asset 不可用、audio busy 或 DMA fault 时按现有播放失败清理结束，不把同一命令重新送 Qwen，也不自动改走 HA TTS，避免重复副作用/双播。 | DECIDED |

## 4. 现有音频输出链：B8.8 硬冻结区

以下链路以当前 `3e13378` 为基线。B8.8 的文本输入最终必须汇入它，**不能复制、替换或“顺便优化”**：

```text
Qwen Gateway server event: audio.delta
        ↓
QwenRealtimeBridge._handle()
        ↓
QwenPcmStream
        ↓
QwenPcmStream.chunks()
  └─ 当前 HA AudioChunkConverter 负责必要的 provider rate → 32 kHz mono
        ↓
TivooQwenPcmView
  /api/tivoo/qwen/audio/{stream_id}
        ↓
QwenRealtimeBridge._open_output()
        ↓
Esp32ConnectionAdapter.async_send_tts_play()
        ↓
TYPE_TTS_PLAY / playback_id / existing HTTP URL
        ↓
S3 existing HTTP fetch + PCM playback
        ↓
existing audio output manager / AFE-playback coordination
        ↓
TYPE_AUDIO_STATE playing/completed/failed
        ↓
QwenRealtimeBridge.on_playback()
        ↓
现有 physical playback terminal / follow-up gate
```

B8.8 后续代码审查必须满足：

1. `esp32/firmware/**` 的 B8.8 diff 只允许本地 ACK 消息、两条固化资产、现有 short-prompt owner 接入及相应测试；Qwen/HTTP playback 与 AFE/WakeNet/MIC 相关实现不得改变。
2. 不修改 `QwenPcmStream` 的 buffering/SRC/EOF 语义。
3. 不修改 `TivooQwenPcmView` HTTP stream 语义。
4. 不修改 `QwenRealtimeBridge._open_output()` 的现有 playback dispatch。
5. 不修改 `_handle()` 中 `audio.delta` / `audio.done` 的输出处理与当前终态门禁。
6. 不修改 `Esp32ConnectionAdapter.async_send_tts_play()` wire contract。
7. 不修改 S3 预缓冲、HTTP consumer、PCM writer、core/priority、AFE 与播放协调。
8. B8.8 新的 text-input path 必须在 **Qwen response event 接收以前** 与现有桥汇合；不得在 audio.delta 以后另开分支。

## 5. HA 本地识别边界

B8.8 的“本地识别”不是简单调用 Home Assistant agent 后看自然语言结果，而是保持 HA Core 已有 local-first 路由语义：

```text
Sherpa final transcript
    ↓
HA sentence trigger
    ├─ response → LOCAL_HIT
    ↓ none
HA local intents（prefer_local_intents=true）
    ├─ action_done → LOCAL_HIT → S3 success ACK
    ├─ partial_action_done / error → LOCAL_HIT → S3 failure ACK
    ├─ query_answer → LOCAL_HIT → HA dynamic TTS
    ↓ none
QWEN_FALLBACK

sentence trigger 命中只有动态 response text、没有 `IntentResponseType`：
    → LOCAL_HIT → HA dynamic TTS
```

合同要求：

- 不把“本地执行后报错”当成 `none`。
- `action_done` 的成功 ACK 不使用 intent 自带的固定确认文本做运行时 TTS；`partial_action_done/error` 同理只播失败 ACK。详细错误仍保留在 HA result/log 中，但语音反馈固定且低延迟。
- `query_answer` 和 sentence trigger 的内容本身承载信息，继续走 HA 动态 TTS；不得用“搞定/操作失败”替代真实查询/触发器回复。
- 不因为 Qwen fallback adapter 的 feature flag 改变而静默扩大/缩小 HA local intent 的匹配集合；实现批必须用现有本地句式/实体控制回归语料对比。
- 不让 legacy AstrBot conversation fallback 在 B8.8 新路径中先被调用一次再转 Qwen。
- 不让 HA Pipeline 在 Qwen fallback 后继续为模型 assistant transcript 启动第二次 TTS。
- 若最终实现通过 HA conversation-agent fallback 槽接入 Qwen，必须证明它只承担“local miss 后的 handoff”，且不会改变上述 local-first 顺序；若采用其它 HA 侧接入点，也必须证明路由结果等价。合同不预造新的 HA Core API。

## 6. 输入、会话与输出时序

### 6.1 独立新 wake

```text
S3 wake confirmed
  ↓
现有 ready/gate + MIC session
  ↓
PCM → HA ingress → Sherpa
  ├───────────────────────────┐
  │                           │ 可并行
  │                    Qwen Gateway connection prepare
  ↓                           │ （无用户内容）
Sherpa final text             │
  ↓                           │
HA local-first route          │
  ├─ LOCAL_HIT ───────────────┴→ typed action: S3 success/failure ACK；query/trigger: HA dynamic TTS；Qwen 无 user turn
  │
  └─ LOCAL_MISS
        ↓
conversation.item.create(parts[text])
        ↓
Agent submit/sendUserInput
        ↓
现有 response/tool/audio lifecycle
        ↓
【冻结】现有音频输出链
```

### 6.2 immediate follow-up

```text
上一轮 Qwen 回复满足现有 follow-up 合同
  ↓
physical playback completed
  ↓
现有 follow-up gate / 新 MIC UUID / 新 HA Context
  ↓
Sherpa STT
  ↓
HA local-first
  ├─ LOCAL_HIT → typed action 播 S3 ACK / query-trigger 走 HA dynamic TTS；不向保留 socket 创建新 Qwen turn
  │
  └─ LOCAL_MISS
        ↓
在“上一轮已保留的同一个活动 Gateway WebSocket”上
conversation.item.create(parts[text])
        ↓
继续现有 Qwen 上下文
        ↓
【冻结】现有音频输出链
```

如果本地命中的 follow-up 结束了此次连续对话，保留 socket 的释放继续走现有 lifecycle/owner 清理；不得为了维持 Qwen 上下文而复制本地命令到模型。

## 7. 与既有 P6.8 合同的迁移关系

| 既有合同/结论 | B8.8 处置 |
|---|---|
| B0.4 / B5：S3→设备端点 Sherpa STT、HA `prefer_local_intents`、未命中再 fallback | **恢复并复用输入侧设计**。不恢复 AstrBot fallback；fallback 改为 Qwen Audio Agent 文本输入。 |
| B8.7：Tivoo Qwen 路径不再调用旧 Sherpa STT | **被 B8.8 输入侧新决策有意替代**。仅恢复设备端点 Sherpa STT；不恢复旧 KWS/TTS 作为 Qwen 问答链路。 |
| B8.5/B8.6：Qwen response/tool/audio、物理 playback、follow-up 生命周期 | **全部保留**。B8.8 只把 Qwen 的用户输入源从 PCM 改为“local miss 后的 Sherpa transcript”。 |
| 2026-11-25 当前 HA 侧 SRC / streaming playback 决策 | **硬冻结**。B8.8 不重新迁移 SRC、不改分块/缓存/预缓冲。 |
| P6.8 S3 AFE/WakeNet/VAD/PCM ingress | **全部保留**。不因重新使用 Sherpa 而改采集链；唯一 S3 新增范围是 local ACK 资产与薄播放入口。 |
| P6.8 B6 short-prompt / audio_resource owner | **复用**。local ACK 作为“回答播放”复用同一 short-prompt/output owner，但额外使用 `playback_id + AUDIO_STATE` 报真实终态；ready/followup prompt 本身仍保持原行为。 |
| Qwen Frontend MCP / Prompt / persona / memory | **全部保留**。文本输入仍进入同一个 Audio Agent frontend。 |

因此 B8.8 不是回滚到旧 STT→AstrBot→TTS 架构，而是：

```text
保留当前 S3 local wake + 当前 Qwen Audio Agent + 当前 Qwen PCM output
只把“Qwen 的输入端”改为：
S3 PCM → Sherpa STT → HA local-first → text fallback
```

## 8. 后续实现验收门禁（本批不执行）

后续实现 B8.8 时至少必须证明以下条件，未证明不得宣告完成：

| 验收项 | 必须证明 |
|---|---|
| PCM 直通 | 同一测试 PCM 从现有 ingress 到 Wyoming 的样本字节与顺序保持；B8.8 没有新增 reframe/copy stage。 |
| 单次 ASR | 每轮正常输入只有一次 Sherpa decode；local miss 不做第二次 ASR，不 replay PCM 给 Qwen。 |
| 本地命中 | 本地灯光/状态查询等命中后 Qwen socket 无 `conversation.item.create`，MCP 无重复调用。 |
| 本地动作成功 | `action_done` 只下发一次 `TYPE_LOCAL_ACK_PLAY(result=success)`，S3 播 `local_success_01`，并收到匹配 playback_id 的 `AUDIO_STATE playing→completed`；无 HA TTS/Qwen audio。 |
| 本地动作失败 | `partial_action_done/error` 只下发一次 `TYPE_LOCAL_ACK_PLAY(result=failure)`，S3 播 `local_failure_01`，并收到匹配终态；无 Qwen fallback、无重复 service side effect。 |
| 本地动态回复 | `query_answer` 与 sentence trigger 不播 ACK，继续播真实动态文本；Qwen 无 user turn。 |
| 本地未命中 | 只发送一次 `conversation.item.create`，payload 是 Sherpa final transcript；客户端无第二个 `response.create`。 |
| Qwen 工具 | 文本 fallback 仍可走现有 Frontend MCP tool call → tool result → final audio。 |
| 输出零回归 | Qwen `audio.delta` 之后的函数、HTTP resource、PCM/SRC、TTS_PLAY、S3 playback 与 AUDIO_STATE 时序与基线一致。 |
| S3 限定 diff | S3 diff 仅包含本地 ACK 消息、成功/失败固化资产与现有 short-prompt owner 接入；WakeNet/AFE/MIC/Qwen HTTP playback/SRC/调度无功能变化。 |
| 无双播 | 单个 local hit 只允许 ACK 或 HA dynamic TTS 之一；Qwen fallback 不触发 ACK/HA TTS；本地命中不触发 Qwen audio。 |
| follow-up | 本地未命中的 follow-up 在原活动 socket 上提交 text；本地命中的 follow-up 不复制给 Qwen。 |
| cancellation | STT、local-route、text submit、tool、audio/playback 任一阶段被新 wake supersede 时，旧 generation 不产生迟到副作用/播放。 |
| 延迟 | 分阶段记录 Sherpa decode 与 local-route 增量；没有固定 sleep、音频 replay、等待 Qwen user transcript 或额外预缓冲。 |
| 输出代码冻结 | 对 §4 所列 Qwen 输出函数做 diff/必要时函数级 hash；S3 diff 逐文件证明仅属于 local ACK，不改变 HTTP/Qwen playback、AFE 或调度。 |

## 9. 本矩阵最终裁决

1. **S3 的语音采集与 Qwen/HTTP 输出保持现状；只增加本地成功/失败 ACK 的最小固件入口与固化资产。**
2. **现有 MIC_PCM 直接进入已有 HA ingress，尽量原样交给 Sherpa，不新增 B8.8 音频分块层。**
3. **Sherpa final transcript 先进入 HA Core local-first 语义。**
4. **只有本地真正未命中时，才把同一 transcript 用 GCP `conversation.item.create(parts[text])` 提交给 Qwen Audio Agent。**
5. **HA Client 不额外发送 `response.create`；该动作由 Qwen Audio Agent 的 `sendUserInput() → sendResponse()` 内部完成。**
6. **不再把原始 PCM replay 给 Qwen。**
7. **Qwen 文本输入仍使用当前 Agent、MCP、Prompt、persona/memory 与 qwen3.8 realtime model。**
8. **从 Qwen `audio.delta` 起的现有音频输出、HA SRC、HTTP stream、TTS_PLAY、S3 playback、AUDIO_STATE 与 follow-up 调度全部硬冻结。**
9. **HA typed local action：`action_done→S3 success ACK`，`partial_action_done/error→S3 failure ACK`；`query_answer` 和 sentence trigger 保留动态本地 TTS。**
10. **除本地 ACK 明确列出的 S3 最小扩展外，B8.8 仍只做 HA/Qwen 输入侧适配；不得顺带修改 Qwen/HTTP 输出链、AFE 或其它 S3 生命周期。**
