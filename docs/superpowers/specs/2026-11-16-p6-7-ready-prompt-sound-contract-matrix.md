# P6.7 语音等待提示音合同矩阵

> 日期：2026-11-16
> 基线：`main@e48c66a`（P6.6 已合入）；工作分支 `feature/p6-7-audio-prompts`
> 状态：b0–b3 已执行；b3 的提示音自触发缺陷已通过 prompt-only VAD suppression 修复并实机复测关闭。按后续产品决策，提示音 gate 内不再要求同时识别人声；普通 TTS 的 VAD/KWS 打断能力必须保持。详见 [b3 验收报告](../reports/2026-11-16-p6-7b3-device-acceptance.md) 与 [VAD suppression 修复报告](../reports/2026-11-16-p6-7-prompt-vad-suppression-fix.md)
> 规格：[P6.7 语音等待提示音规格](2026-11-16-p6-7-ready-prompt-sound-design.md)
> 分批：[P6.7 分批执行计划](../plans/2026-11-16-p6-7-ready-prompt-sound-batch-execution-plan.md)

> 2026-11-17 修订：首次唤醒采用“提示音结束后才开始命令 STT”，覆盖旧版 Detection 起计及提前 VAD 取消提示音规则；确认打断/follow-up 保持原行为。新增断连/发送失败释放 TTS 占用要求。见 [修复记录](../reports/2026-11-17-ready-prompt-wake-order-fix.md)。

## 1. 权威关系与已核对接口

- **音频与打断权威**：[P6.5 常驻音频会话矩阵](2026-11-13-p6-5-persistent-audio-session-and-kws-interruption-contract-matrix.md)。`WAKE_WORD_END`→5 秒空命令计时、`_open_followup()`→8 秒、`STT_VAD_START`、side KWS 确认打断和持续 MIC/AEC 都不改变。
- **设备协议权威**：[P6 双向通信矩阵](2026-11-12-p6-esp32-ha-bidirectional-contract-matrix.md)。现有 `TTS_PLAY=0x30`、`AUDIO_STOP=0x31`、`AUDIO_STATE=0x32`、7778 transport/HTTP GET 可复用，不新增消息类型。P6.7 仅给 `TTS_PLAY` 增加向后兼容的可选布尔 `suppress_vad`（默认 false，只有提示音为 true）；ESP32 `audio_resource.c` 仍只接收 `audio/mpeg` 或 `TIVOO_PCM_MIME`，`source` 仍为 `tts_http`。
- **显示权威**：[P6.6 表情矩阵](2026-11-14-tivoo-expression-state-machine-contract-matrix.md)。`wake_confirmed`、`followup_wait`、`speaking` 仍从原有 turn / **正常 TTS** 播放 ID 更新。提示音必须单独按 ID 路由，不能作为一次正常回答。
- **静态资源权威**：HA Core 2026.11.0 安装源码 `components/frontend/__init__.py` 注册 `hass.config.path("www")`→`/local`；`components/http/static.py` 按扩展名返回 MIME。对应资源所在 `www` 目录必须存在；MP3 的实际 200/Content-Type/HTTP 可达性由 b0 现场/服务检查锁定。
- **真实模块**：`assist_satellite.AudioSessionCoordinator`、`audio_resource.PipelineTtsEvents`、`transport.Esp32ConnectionAdapter`、ESP32 `audio_resource/audio_playback/audio_output_manager/audio_frontend`。b3 已取得本机提示音触发 VAD/MIC session 的真实回授证据，但未完成声学延迟标定、含唤醒词 KWS 负样本与真人并行讲话，因此 P6.5b11 `P65-A13` 仍不能标 PASS。
- **边界补充**：P6.5 禁止 **VAD-only 停止正常 TTS、取消 LLM 或触发打断**；本 P6.7 允许取消当前短提示音的 *专属* ID 以给用户命令/实际回答让路，不改变 P6.5 规则。

## 2. 正式合同

| ID | 可验证行为及禁止条件 | Owner / 接口 | 预计验收 |
|---|---|---|---|
| PR-C01 | 只在首次有效 `WAKE_WORD_END`、确认打断产生的命令等待、每轮实际 follow-up 等待各播放最多一次；`VAD` 候选、每个 `STT_START`、普通 TTS 生成不得误触发 | `AudioSessionCoordinator` | b2 |
| PR-C02 | 首次命中且有可用素材时，结束旧 wake Pipeline，等待提示音终态后以新鲜 PCM 启动 STT；5 秒从新 STT_START 起计，wake tail 不得取消提示音或进入命令 | `AudioSessionCoordinator` | b2 |
| PR-C03 | 确认打断后旧 turn owner 清理优先；新轮 STT_START 才启动 5 秒，MIC handoff 即使提示音未发出也不能丢 | `_interrupt_turn` / `_run_turn` | b2 |
| PR-C04 | 仅当当前 turn 的 `INTENT_END.intent_output.continue_conversation` 严格为 `true` 时，跟随实际正常 TTS `completed` 或无 TTS 的有效响应打开 8 秒 follow-up；`false`/缺失时结束 MIC session；提示音 `completed` 不得打开 follow-up | `_open_followup` / playback dispatcher | b2 + 2026-11-17 fix |
| PR-C05 | 非提示音 gate 期间的 follow-up `speech_start` 仍立刻启动免唤醒词 STT。提示音 gate 内不产生新的 VAD/MIC_ACTIVITY/MIC_PCM；整句完全落在该短窗口内可能被忽略，这是明确产品取舍。gate 恢复后下一次 `speech_start` 仍按原逻辑启动 STT | `on_activity` / Pipeline / ESP32 AFE | b2 + post-b3 fix |
| PR-C06 | `suppress_vad=true` 的提示音 gate 中 MIC RX/AFE/AEC 必须持续；VAD/MIC_ACTIVITY/MIC_PCM 向 HA 的输出明确暂停，已有 speech 状态最多归零一次。禁止停 RX/AEC，也禁止把 gate 扩大到普通 TTS | ESP32 AFE / HA ingress | b3 + post-b3 fix |
| PR-C07 | 四个预制短 MP3：`ready_01`…`ready_03`（“我在/在的/你说”）和 follow-up 专属 `followup_01`（“嗯？”）；32 kHz、mono、`audio/mpeg`、目标 ≤0.9 秒；必须由当前生产 HA 实际 TTS Provider/模型/voice 参数一次性生成，前后保留短静音避免掐头去尾；运行时不 TTS | `homeassistant/prompt_assets/` / `/config/www/tivoo/prompts/` | b0 + 2026-11-17 phase split |
| PR-C08 | `ready/wake/confirmed` 只从 `ready_01..03` 随机选择且相邻两次不同；`followup` 只使用 `followup_01` 并允许跨 generation 重复。对应素材缺失时静默跳过，不回退到其它素材池、不产生推理或影响语音转移 | `PromptSoundPlayer` | b1 + 2026-11-17 phase split |
| PR-C09 | 生产 URL 使用 HA 内网基址 `/local/tivoo/prompts/<固定文件>.mp3`；ESP32 GET 200，Content-Type 为 `audio/mpeg`，不经认证重定向、不可使用外网/Cloud 位置 | HA 静态资源 / URL 构造 | b0/b3 |
| PR-C10 | 不扩大 `build_internal_tts_url()` 的 `/api/tts_proxy/` 限制；提示音 URL 单独限定为固定本地素材 | HA prompt URL helper | b1 |
| PR-C11 | 复用现有 `async_send_tts_play()` / `0x30`；只增加可选 `suppress_vad` 布尔字段且默认 false，不新增 message type；ESP32 解码与 I²S TX 仍走唯一 `audio_output_manager`，不得混音或另起 DAC owner | HA adapter / ESP32 audio_resource | b1/b3 + post-b3 fix |
| PR-C12 | 每个提示音具有区别于正常 TTS 的独立 `playback_id`，`AUDIO_STATE.source` 仍是 `tts_http`；**按 ID** 分发给提示音 owner 或 `_Turn.tts`，不可按 `source` 猜音频种类 | Satellite playback dispatcher | b1 |
| PR-C13 | 正常回答的 `playing/completed/stopped/failed` 行为、P6.6 speaking 表情与 follow-up 只接受当前真实 TTS ID；提示音终态绝不触发它们 | `on_playback` / ExpressionCoordinator | b1/b2 |
| PR-C14 | 新 turn/session 取消旧待发任务；旧 generation 迟到 `AUDIO_STATE` 或 stop 不能取消/覆盖新提示音或正常 TTS；重复入口不重复发声 | `PromptSoundPlayer` / generation | b1/b2 |
| PR-C15 | 播放占用互斥：旧 TTS 尚在活动时不抢占；提示音占用时正常 TTS 下发前必须先自然结束或定向停止并确认设备释放；不以设备 `audio_busy` 作为正常仲裁 | Prompt owner + TtsResource dispatch seam | b1/b2 |
| PR-C16 | 首次唤醒的旧 Pipeline 事件不得取消待播提示音；其它入口有效命令开始时优先用户：未发出的提示音直接取消，已播放提示音仅允许匹配自身 ID 的 `AUDIO_STOP`；不得发无 ID 的 STOP 或停正常回答 | `on_activity` / `STT_VAD_START` / prompt owner | b2 |
| PR-C17 | 短提示音仍取最终 TX PCM 作为 AEC R，全局 `vad_mute_playback=false`；仅 `suppress_vad=true` 提示音在真实输出期间 runtime disable/reset VAD，并暂停 MIC_ACTIVITY/MIC_PCM。数字输出结束后按已标定 760 samples / 47.5 ms 声学尾部（实现 48 ms）再 enable/reset；普通 TTS VAD/MIC/KWS 打断不受影响 | ESP32 output manager / AFE | b3 + post-b3 fix |
| PR-C18 | 提示音 gate 内不得出现由提示音造成的 VAD speech_start、MIC_ACTIVITY 或 MIC_PCM 上送；用户语音在该 gate 内被有意忽略。gate 关闭后必须立即恢复检测；同一音频以普通 TTS（无 `suppress_vad`）播放时必须仍能产生 VAD/MIC，证明正常 TTS 打断链未被全局关闭 | P6.7 现场声学验收 | post-b3 fix |
| PR-C19 | 提示音文件 HTTP 异常、DAC busy、断线、超时均安静跳过；不能把当前 Pipeline 标为失败、永久阻塞取消/收音或遗留音频 request；断连/真实 TTS 发送失败按 ID 释放 HA TTS 占用；首次提示音等待上限 5 秒 | Prompt owner / transport | b1/b2 |
| PR-C20 | 新增提示音不改 P6.6 screen power gate/idle/priority，不触发 AstrBot SSE、ChatLog、LLM/工具调用或新对话 | Satellite / ExpressionCoordinator | b2/b3 |
| PR-C21 | NAS 实际部署包含三个静态文件，验证 LAN HTTP 获取/解码、真实输出/回声；b0/b1/b2 只表示独立软件证据，不冒充 b3 真人声学 PASS | 部署与验收报告 | b0/b3 |

## 3. 失效/竞态矩阵

| 场景 | 唯一允许的结果 | 主要合同 |
|---|---|---|
| 唤醒词后紧接命令 | 首次唤醒要求等待提示音；提示音结束之前的 PCM 不进入新命令 STT，之后的新鲜 PCM 才用于命令 | C02、C05、C06、C16 |
| TTS 播放中被 side KWS 打断 | 旧 TTS 先停止并收尾，不能两音同时发给 ESP32；PCM handoff 保留 | C03、C14、C15 |
| 真正 TTS 恰在提示音发起时到达 | 正常回复优先，无 audio_busy / 额外 follow-up | C13、C15 |
| follow-up 提示音本身造成 VAD 活动 | 已实测证明仅靠 AEC 不足；提示音 owner 使用 `suppress_vad=true`，真实输出及声学尾部内暂停 VAD/MIC_ACTIVITY/MIC_PCM，RX/AFE/AEC 持续；普通 TTS 不使用该标记 | C17、C18 |
| 8 秒超时刚好与 HTTP GET 交错 | 旧提示音不得继续造成有意义的后续动作；MIC session 按原超时关闭 | C04、C14、C19 |
| 提示音 HTTP 404 / MIME 不符 | 静默降级，既有语音对话不失败 | C09、C19 |
| ESP32/HA 重连与旧状态迟到 | 旧状态按 ID 忽略，不自动补播过期等待提示音 | C14、C19 |

## 4. 分批覆盖与完成标准

- **b0 素材/静态服务可用性**：C07、C09、C21 的素材与 HTTP 部分；必须有可重复的音频元数据和真实服务 HTTP 证据。
- **b1 独立播放 owner**：C08、C10–C15、C19 的单模块测试；不自动接入语音入口。
- **b2 语音生命周期集成**：C01–C06、C13–C16、C19、C20 的事件顺序与并发回归。
- **b3 实机验收与收尾**：C06、C09、C11、C17、C18、C20、C21；确认是否真能边放短句边收命令，并留下完整证据和 GAP。

完成判定按后续 workaround 决策更新：相关自动化绿灯 + 真实 ESP32/Tivoo 提示音出声 + 首次/打断/follow-up 触发正确 + 提示音 gate 内无自触发/MIC 上送 + gate 结束后恢复检测 + 普通 TTS 播放时 VAD/MIC/KWS 打断入口仍可用，即满足 P6.7 提示音自触发修复目标。提示音 gate 内真人语音被有意忽略，不再作为 P6.7 PASS 门禁。P6.5 P65-A13 不因为本 workaround 自动变成 PASS。
