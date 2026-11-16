# P6.7 语音等待提示音合同矩阵

> 日期：2026-11-16
> 基线：`main@e48c66a`（P6.6 已合入）；工作分支 `feature/p6-7-audio-prompts`
> 状态：待实施合同；验收状态初始为 NOT RUN，不能把既有播放/AEC 单测视为本功能实测
> 规格：[P6.7 语音等待提示音规格](2026-11-16-p6-7-ready-prompt-sound-design.md)
> 分批：[P6.7 分批执行计划](../plans/2026-11-16-p6-7-ready-prompt-sound-batch-execution-plan.md)

## 1. 权威关系与已核对接口

- **音频与打断权威**：[P6.5 常驻音频会话矩阵](2026-11-13-p6-5-persistent-audio-session-and-kws-interruption-contract-matrix.md)。`WAKE_WORD_END`→5 秒空命令计时、`_open_followup()`→8 秒、`STT_VAD_START`、side KWS 确认打断和持续 MIC/AEC 都不改变。
- **设备协议权威**：[P6 双向通信矩阵](2026-11-12-p6-esp32-ha-bidirectional-contract-matrix.md)。现有 `TTS_PLAY=0x30`、`AUDIO_STOP=0x31`、`AUDIO_STATE=0x32`、7778 transport/HTTP GET 可复用，不新增消息类型。ESP32 `audio_resource.c` 仅接收 `audio/mpeg` 或 `TIVOO_PCM_MIME`；`source` 仍为 `tts_http`。
- **显示权威**：[P6.6 表情矩阵](2026-11-14-tivoo-expression-state-machine-contract-matrix.md)。`wake_confirmed`、`followup_wait`、`speaking` 仍从原有 turn / **正常 TTS** 播放 ID 更新。提示音必须单独按 ID 路由，不能作为一次正常回答。
- **静态资源权威**：HA Core 2026.11.0 安装源码 `components/frontend/__init__.py` 注册 `hass.config.path("www")`→`/local`；`components/http/static.py` 按扩展名返回 MIME。对应资源所在 `www` 目录必须存在；MP3 的实际 200/Content-Type/HTTP 可达性由 b0 现场/服务检查锁定。
- **真实模块**：`assist_satellite.AudioSessionCoordinator`、`audio_resource.PipelineTtsEvents`、`transport.Esp32ConnectionAdapter`、ESP32 `audio_resource/audio_playback/audio_output_manager/audio_frontend`。P6.5b11 `P65-A13` 回声声学验收尚缺。
- **边界补充**：P6.5 禁止 **VAD-only 停止正常 TTS、取消 LLM 或触发打断**；本 P6.7 允许取消当前短提示音的 *专属* ID 以给用户命令/实际回答让路，不改变 P6.5 规则。

## 2. 正式合同

| ID | 可验证行为及禁止条件 | Owner / 接口 | 预计验收 |
|---|---|---|---|
| PR-C01 | 只在首次有效 `WAKE_WORD_END`、确认打断产生的命令等待、每轮实际 follow-up 等待各播放最多一次；`VAD` 候选、每个 `STT_START`、普通 TTS 生成不得误触发 | `AudioSessionCoordinator` | b2 |
| PR-C02 | 首次命中命令等待仍从 Detection 起计 5 秒；提示音不重置/延后计时 | `AudioSessionCoordinator` | b2 |
| PR-C03 | 确认打断后旧 turn owner 清理优先；新轮 STT_START 才启动 5 秒，MIC handoff 即使提示音未发出也不能丢 | `_interrupt_turn` / `_run_turn` | b2 |
| PR-C04 | 跟随实际正常 TTS `completed` 或无 TTS 的有效响应打开 8 秒 follow-up；提示音 `completed` 不得打开 follow-up | `_open_followup` / playback dispatcher | b2 |
| PR-C05 | follow-up `speech_start` 仍立刻启动免唤醒词 STT，且重置/取消原 8 秒等待按现有逻辑；提示音不等待 STT 才播放，STT 不等待提示音结束 | `on_activity` / Pipeline | b2 |
| PR-C06 | 唤醒后 STT 使用原 MIC ingress，提示音播放中 RX/AFE/VAD/MIC_PCM 持续；禁止短时收音屏蔽或关闭上传 | ESP32 AFE / HA ingress | b3 |
| PR-C07 | 四个预制短 MP3（`ready_01`…`ready_04`），32 kHz、mono、`audio/mpeg`、目标 ≤0.9 秒；实际素材来源/使用权限和时长留记录，运行时不 TTS | `homeassistant/prompt_assets/` / `/config/www/tivoo/prompts/` | b0 |
| PR-C08 | 随机选已配置文件且相邻两次不同；文件缺失/没有可用文件静默跳过，不产生推理或影响语音转移 | `PromptSoundPlayer` | b1 |
| PR-C09 | 生产 URL 使用 HA 内网基址 `/local/tivoo/prompts/<固定文件>.mp3`；ESP32 GET 200，Content-Type 为 `audio/mpeg`，不经认证重定向、不可使用外网/Cloud 位置 | HA 静态资源 / URL 构造 | b0/b3 |
| PR-C10 | 不扩大 `build_internal_tts_url()` 的 `/api/tts_proxy/` 限制；提示音 URL 单独限定为固定本地素材 | HA prompt URL helper | b1 |
| PR-C11 | 复用现有 `async_send_tts_play()` / `0x30`；ESP32 解码与 I²S TX 走唯一 `audio_output_manager`；不得新增设备协议、混音或另起 DAC owner | HA adapter / ESP32 audio_resource | b1/b3 |
| PR-C12 | 每个提示音具有区别于正常 TTS 的独立 `playback_id`，`AUDIO_STATE.source` 仍是 `tts_http`；**按 ID** 分发给提示音 owner 或 `_Turn.tts`，不可按 `source` 猜音频种类 | Satellite playback dispatcher | b1 |
| PR-C13 | 正常回答的 `playing/completed/stopped/failed` 行为、P6.6 speaking 表情与 follow-up 只接受当前真实 TTS ID；提示音终态绝不触发它们 | `on_playback` / ExpressionCoordinator | b1/b2 |
| PR-C14 | 新 turn/session 取消旧待发任务；旧 generation 迟到 `AUDIO_STATE` 或 stop 不能取消/覆盖新提示音或正常 TTS；重复入口不重复发声 | `PromptSoundPlayer` / generation | b1/b2 |
| PR-C15 | 播放占用互斥：旧 TTS 尚在活动时不抢占；提示音占用时正常 TTS 下发前必须先自然结束或定向停止并确认设备释放；不以设备 `audio_busy` 作为正常仲裁 | Prompt owner + TtsResource dispatch seam | b1/b2 |
| PR-C16 | 有效命令开始时优先用户：未发出的提示音直接取消，已播放提示音仅允许匹配自身 ID 的 `AUDIO_STOP`；不得发无 ID 的 STOP 或停正常回答 | `on_activity` / `STT_VAD_START` / prompt owner | b2 |
| PR-C17 | 短提示音取最终 TX PCM 作为 AEC R，`vad_mute_playback=false`，同音源播放时 MIC RX 不停；不额外运行声源分离模型 | ESP32 output manager / AFE | b3 |
| PR-C18 | 播放“嘟”和中文短句期间同时讲话：真实语音首字进入 STT；提示音自身不得诱发 follow-up 假启动或错误命令；不同距离/音量下记录 AEC ref misalignment/underrun、VAD、STT，实机失败明确 GAP | P6.7 现场声学验收 | b3 |
| PR-C19 | 提示音文件 HTTP 异常、DAC busy、断线、超时均安静跳过；不能把当前 Pipeline 标为失败、阻塞取消/收音或遗留音频 request | Prompt owner / transport | b1/b2 |
| PR-C20 | 新增提示音不改 P6.6 screen power gate/idle/priority，不触发 AstrBot SSE、ChatLog、LLM/工具调用或新对话 | Satellite / ExpressionCoordinator | b2/b3 |
| PR-C21 | NAS 实际部署包含四个静态文件，验证 LAN HTTP 获取/解码、真实输出/回声；b0/b1/b2 只表示独立软件证据，不冒充 b3 真人声学 PASS | 部署与验收报告 | b0/b3 |

## 3. 失效/竞态矩阵

| 场景 | 唯一允许的结果 | 主要合同 |
|---|---|---|
| 唤醒词后紧接命令 | 命令前缀不丢；提示音可取消/跳过 | C02、C05、C06、C16 |
| TTS 播放中被 side KWS 打断 | 旧 TTS 先停止并收尾，不能两音同时发给 ESP32；PCM handoff 保留 | C03、C14、C15 |
| 真正 TTS 恰在提示音发起时到达 | 正常回复优先，无 audio_busy / 额外 follow-up | C13、C15 |
| follow-up 提示音本身造成 VAD 活动 | AEC 现场确认无假 STT；若失败标 GAP 不假设 AEC 能完全消除 | C17、C18 |
| 8 秒超时刚好与 HTTP GET 交错 | 旧提示音不得继续造成有意义的后续动作；MIC session 按原超时关闭 | C04、C14、C19 |
| 提示音 HTTP 404 / MIME 不符 | 静默降级，既有语音对话不失败 | C09、C19 |
| ESP32/HA 重连与旧状态迟到 | 旧状态按 ID 忽略，不自动补播过期等待提示音 | C14、C19 |

## 4. 分批覆盖与完成标准

- **b0 素材/静态服务可用性**：C07、C09、C21 的素材与 HTTP 部分；必须有可重复的音频元数据和真实服务 HTTP 证据。
- **b1 独立播放 owner**：C08、C10–C15、C19 的单模块测试；不自动接入语音入口。
- **b2 语音生命周期集成**：C01–C06、C13–C16、C19、C20 的事件顺序与并发回归。
- **b3 实机验收与收尾**：C06、C09、C11、C17、C18、C20、C21；确认是否真能边放短句边收命令，并留下完整证据和 GAP。

完成判定：相关自动化绿灯 + 真实 ESP32/Tivoo 提示音出声 + 首次/打断/follow-up 触发正确 + 真人在提示音播放中下命令成功且未出现误识别/错误新轮，才可宣称 P6.7 整体完成。P6.5 P65-A13 不因为本功能代码存在而自动变成 PASS。
