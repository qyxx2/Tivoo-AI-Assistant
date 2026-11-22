# P6.8b0.5 打断、连续对话、音频所有权与表情协调规格及合同矩阵

> 2026-11-18；基线 05a144b。上承 [总体设计](2026-11-18-p6-8-b0-1-overall-design-baseline.md)、[硬件/桥接](2026-11-18-p6-8-b0-2-hardware-uart-spp-design.md)、[双麦 AFE](2026-11-18-p6-8-b0-3-audio-afe-design.md)、[HA STT/提示音](2026-11-18-p6-8-b0-4-ha-stt-prompt-design.md)。仅 b0.5 设计，b7/b8 实施，b5/b6 实现所需最小身份/owner 边界时遵循本合同。未作新板、生产或声学验收。

## 1. 核对依据及设计裁决

- 项目 assist_satellite.py 的 _Turn/AudioSessionCoordinator：旧 MIC session 可跨多 Pipeline；Context.id 是显示 generation；_event_turn 绑定公开 Satellite caller；_interrupt_turn 先按 ID stop、取消 caller、join/async_close；on_end 会清全轮；_open_followup 先 arm(8) 再请求 HTTP 提示音；STT_VAD_START 才置 command_started；on_playback 仅比较 playback_id。新模式必须改为每命令一 UUID（不是新 HA/AstrBot 聊天），避免无 UUID PCM 跨轮；不能将旧 on_end 用作正常 input EOF。
- audio_resource.py 的 TtsResourceManager 从 RUN_START 预备 playback UUID，INTENT_PROGRESS/tts_start_streaming 或 TTS_END 发一次 0x30；PipelineTtsEvents.stop_dispatch/async_close 已有 run-scoped owner。tts_lifecycle.py 的 PipelineTtsOwner 绑定 HA 2026.11.0 ResultStream token，stop_delivery、delete、Wyoming writer cancel/FIN→peer EOF（15s 上限）、FFmpeg producer join（5s 上限）；不是仅取消 GET 或 caller。保留这些边界。既有 async_stop_playback 发 0x31 request_id/expected_audio_id/reason，旧 TTS_PLAY 无 session_id；S3 必须新增 session 判断，单靠 HA cancel 或播放 UUID 去重不能阻止迟到旧 TTS。
- esp32/firmware/main/audio_resource.c 的 parse_tts_play/start_request/run_request/stop：现按 playback UUID 去重，单 active+pending、独立输出 generation、peer_generation 来自 7778 连接；stop 定向标记 stop_requested，调用 output_stop、shutdown HTTP socket 以唤醒 worker；worker 结束后 output_end，发 audio_id/source=tts_http/state/bytes_received/error_code，仍可能有旧 DMA 在途。audio_output_manager.h 有 generation 定向 begin/write/stop/drained/end，stop 不等价于物理静音。复用该单 owner 与 b0.3/4 的真实 TX 参考、排尽及声学尾部，不沿用旧板固定尾巴或把网络 terminal 当物理 drain。现诊断 generation 在断开清零，并非音频轮次；旧连接不可继承。
- 开发机同生产版本 .venv HA Core 2026.11.0：assist_satellite/entity.py:442–555 的 async_accept_pipeline_from_satellite 先 _cancel_running_pipeline、维护共享 _pipeline_task，finally 清它；不能并发/抢先调用导致旧 finally 清新指针。其 STT_START/INTENT_START/TTS_START/tts_response_finished 管公共实体状态，独立于 Tivoo 表情；公开 tts_response_finished 将实体置 IDLE。default_pipeline.py:879–888 用 ConversationResult.as_dict 发 INTENT_END 并记录 continue_conversation_agent；conversation/models.py:81–90 的 response/continue_conversation 是真实字段；helpers/intent.py:1528 起 response_type 区分 error 与成功。conversation/chat_log.py:394–411 的 continue_conversation 取最后 assistant 文本 strip 后以 ?、？或希腊问号 ; 结尾；项目 astrbot/conversation.py 返回 async_get_result_from_chat_log。保持原规则，不另写自然语言判断，也不把用户问号/每次 TTS 结束当续聊授权。
- astrbot/conversation.py 在 _conversation_lock 内运行 SSE；取消时先 deltas.aclose，若 response_accepted 且非 stream_completed，向该次捕获的 AstrBot session_id 发 stop（10s 上限），不丢弃已显示 partial ChatLog；api.py 真实 POST /api/v1/chat/sessions/{session_id}/stop，作用于 session 而非单 run（P3 已核对 AstrBot 4.29.4 上游及权限）。目前 stop 失败只日志；b7 必须使取消 owner 能获知失败，不把本地 Task 已取消当远端已停止。不用 MIC UUID 当 AstrBot session，不每轮 reset。已有手动/工具新对话入口保留。
- display_state.py 已有唯一 ExpressionCoordinator、ScreenPowerGate、generation guard、固定优先级、mood TTL/idle、SPP current-state 重放；transport.py 的 GET_STATUS/DEVICE_EVENT 校验、7777 stale writer 回收及迟到 control 建连重放继续复用；__init__.py unload 会销毁 runtime（gate 当前 RAM，不承诺 HA 冷启动持久化）。llm.py SetMood 经服务调用，services.py 当前按调用时 active_generation 投递，未验证远程 MCP 的原始 voice context。不可将无来源 MCP context 猜成某个旧/新轮。

裁决：采用设备先物理停止 + HA 序列化取消/准备，而非等待 HA 网络 stop 后才停响；采用每轮 UUID 与原 playback UUID 绑定，而非新一套全局数字计数器或复用旧持久 MIC session；采用一次 HA 授权设备本地 beep/gate，而非 HA 执行提示音或任意 VAD 自行续聊。继续复用 HA Display Coordinator。新字段是本项目设计；旧协议能力模式原样保留至 b9。没有改动或播放 NAS/设备，b0.4 的生产版本及 b0.2/3 的硬件/模型锁定证据继续有效。

## 2. 唯一所有权与 TVIO 合同

三种身份不混用：7778 连接 epoch（本地对象/peer_generation）；语音轮 session_id（设备 UUIDv4，对应一个 _Turn/Context.id，含本地 follow-up）；普通 TTS playback_id（HA UUIDv4，对应该轮一个资源）。S3 内部 output generation 由唯一 audio owner 分配，覆盖本地 prompt/普通回复，不能直接由网络字符串转换。HA ChatSession/conversation_id 和长期 AstrBot session_id 独立。所有操作跨 await 前后复核 owner；状态变更先同步换代，再关闭旧资源。新 UUID 不能重新用于同一连接，使用已接受 start 的 uptime_ms 单调边界（同 epoch 新 start 必须严格递增；重复当前 ID 直接幂等），旧连接身份不跨重连。start 由设备单 FIFO 顺序发送，旧未发 PCM 清空，旧已发帧必在新 start 前；无须为每个 PCM 另加 JSON。

以下仅在协商 local_wake_stt_v1 时生效；0x27 在现 diagnostics.py/C TVIO 消息枚举未占用，方向和枚举须在两端注册。其他字段继承 VOICE-C01–C10。新增并非上游 HA API。

| 消息/方向 | payload / 接收规则 |
|---|---|
| 0x20 MIC_SESSION_START S3→HA | local_wake：b0.4 的新 UUID/格式/uptime_ms/wake_word_phrase，当前任意非短提示 gate 阶段真实确认可取代旧轮；local_followup：同格式、新 UUID、trigger_source=local_followup、parent_session_id=被授权已完成回复的旧 UUID，无 wake_word_phrase。只有未消费的匹配授权可接受；不构造第二 wake 权限。 |
| 0x27 FOLLOWUP_OPEN HA→S3 | JSON session_id=当前已完成且获授权的旧 UUID；每旧轮最多一次，设备只在同 epoch+旧 UUID 仍 current 且未消费、普通回复已释放时接受，立即生成新 UUID，发 0x20 local_followup，异步本地 beep；重复不得再次开轮。0x20 即消费确认，无新增 ACK；若失败/未回复按下述 watchdog 关闭。 |
| 0x30 TTS_PLAY HA→S3 | 增加必须的 session_id，保留 playback_id/url/mime_type；仅当前 UUID 已正常 speech_end 的普通回复可接收（先校验当前轮、再建 worker/HTTP/DAC），同 ID 幂等，不接受旧代次、第二不同 playback 或远程 suppress_vad=true。 |
| 0x32 AUDIO_STATE S3→HA | 增加当前资源原 session_id，保留 audio_id=playback_id/source=tts_http/state/bytes_received/error_code。有效状态 buffering/playing/completed/stopped/interrupted/failed；按 epoch+UUID+ID 校验，终态一次、不倒退；旧终态只可用于其自身资源清理/诊断，不能改变新轮。prompt 不发该类型。 |
| 0x31 AUDIO_STOP HA→S3 | 保留 request_id/expected_audio_id/reason，增必填 session_id；必须匹配普通回复的真实资源或正在退役的旧资源，不能停本地 prompt/别的轮；无 ID stop 在新模式拒绝。迟到旧 stop 对已释放资源幂等无效。 |
| 0x22/0x23 MIC_SESSION_END / MIC_CAPTURE_STOP | 原 session_id/reason 匹配；取消整个轮次/正常结束，不是 STT EOF。当前轮停止时设备定向撤销命令 gate、prompt/回复 owner，恢复待机；迟到旧 stop 不影响当前。新 0x20 合法换代就是旧轮失效边界，不要求额外发旧 END/待其 ACK。0x33 AUDIO_INTERRUPTED 为 legacy，不作为新模式 wake 入口。 |

0x25/26/24/21 严格使用 b0.4 顺序/格式及 sample_count。JSON 校验 UUID、合法枚举、非负 uptime/计数、方向、能力；旧 playback 发送失效前不占正常 owner、不构造当前 failed；不得用 AUDIO_STATE 的 source 或 DEVICE_STATUS 的 audio_resource 猜测 session。异常不关闭 7777/SPP。设备/HA 不重放 wake、授权或旧 TTS，诊断同连接 FIFO 与现有序号继续使用。

## 3. 正常、打断与取消时序

1. Idle→真实 WakeNet：S3 同步建立新 UUID、废弃旧历史、发送 local_wake START；本地 ready 与 HA STT 准备并行。VOICE-C04 的 gate/ready/缓冲、VOICE-C05/06 的 EOF 不变。HA 安装新身份/订阅及新显示 generation 即时生效，不等待旧网络/LLM；只有前一 public caller 完成清理后才可进入下一 async_accept_pipeline_from_satellite。STT_READY 仍必须等真实 provider pull。旧 cleanup 太慢则依 b0.4 gate 后1s ready/缓冲上限取消新轮，不偷偷扩大窗口、不丢首后继续。b7 记录 cleanup 和 ready 超时率，需调整容量时以实测另修合同。
2. 任意准备/收音/STT/intent/合成/普通 TTS/等待 follow-up 中确认真实新 wake：S3 同步失效旧 UUID、关闭旧命令/授权、停止旧输出输入与 HTTP worker（按旧资源/内部 generation），不等待 HA；即使旧 TTS 请求仍在 TCP 中，接收 0x30 时也因 session 不符拒绝。允许 AFE 常驻；只有新 token 的短 prompt 在旧输出 stop/drain/end 且声学尾部已确认后占 DAC。已提交 DMA 可能仍响，b7 测确认到最后旧音频的真实时延；不承诺零毫秒。若不能确认 drain/owner 释放，沿 b0.4 5s watchdog 安全失败，不混音、不以 audio_busy 作为正常切换。新 wake 不受旧候选固定数秒冷却，短提示及其尾部按 AFE-C09/mask 合同例外。
3. HA 收到有效新 START：先同步撤销旧 timers/followup/TTS dispatch 和旧 ingress，使旧 task/PCM 无法继续；安装新 _Turn/Context/generation。定向旧 playback AUDIO_STOP（若已有 ID，发送失败不能阻止本地 cancel）；取消/等待旧 public caller 和其子任务、旧 PipelineTtsEvents.async_close（含 token cache、Wyoming FIN/EOF、FFmpeg、SSE/stop），旧 caller finally 完成后才进入新 public caller。旧 cleanup 只持有捕获的对象，绝不从此时 self._turn 获取将被停止的 ID。旧资源关闭一次或复用同一 close task；仍未结束的 retiring cleanup 作为一个串行 barrier 往后传递，第二/第三次快速确认只保留最新待启动轮并取消其已过期前置任务，不创建多个并发 HA caller。HA 的诊断 reader 不能 await 这一串慢 cleanup；同步身份/有界 ingress 后由后台 task join。旧 _event_turn/event callback 的 late event、旧 task finally/timeout、tts_response_finished 必须被隔离，不能重置新 public state 或新表情。正常结束也按当前身份先使旧 dispatch 不再产生输出再释放。 **b0.6 明确结束握手：** 正常 run 已返回且真实普通播放 completed（或确认无 TTS 的正常回复）、无续聊授权时，HA 撤销本轮 dispatch/ingress，发送匹配 UUID 的 0x23 MIC_CAPTURE_STOP（reason="conversation_complete"（现 assist_satellite.py::_complete_response 对应正常结束字符串））；S3 只清该 current，释放 gate/owner 并回待机，连接可用时发匹配 0x22 终结一次；HA 将迟到 END 仅作为清理/诊断，不令其完成新轮。设备发起 timeout/error 则 0x22，HA 定向结束自身资源，不把 END 当 EOF。授权路径保持 0x27，不发旧轮正常 stop；合法新 START 本身使旧轮失效。断线/发送失败复用 LIFE-C08 本地清理，均不等待对端 ACK。intercept-only / STT-only 依 b0.4 无普通回复、无 grant 正常/定向结束。
4. AstrBot 未接受请求或已收到 SSE end 不额外 stop；活动已接受未完成时由现有 ConversationEntity 唯一 owner 发送一次 stop，保留 partial text、关闭 SSE；不要在 Tivoo 再调用第二 Stop 或轮换正常聊天。由于 stop 是 session-wide，下一共享 AstrBot session 请求不能超过旧 stop/lock 释放；现有 API 成功只证明请求成功，不证明已执行工具回滚。若 stop/peer EOF 未确认，当前替换轮按失败结束，不宣称打断完全成功；b7 需把失败从现有 best-effort 日志可观测地传回 owner，并禁止继续复用未确认停止的同一远端会话（可用现有明确新对话入口恢复，不能静默重置历史）；Wyoming 未确认的 owner 不准假装可用。已有 5s stop-send、15s peer EOF、5s conversion、10s AstrBot stop 上限仍各自管理；验证无永久 barrier，超限报告并释放本地任务/音频、安全回待机。
5. 普通 VAD/电视对白/自己的提示音无取消权；普通 TTS 保持真实 AEC/R+WakeNet，没有命令上送，不能把短 gate 扩到 TTS。真实说出唤醒词才可打断；含唤醒词的自身 TTS 与电视真人声学判别待 b4/b7 实测，单凭 AEC 不能证明声源身份，不增加一套猜测过滤。长回复继续遵循已有欠载填静音、真实终态、网络资源流，不把一段 SSE/PCM 的间歇当完成；terminal completed 必须正常输入 EOF 和真实 DMA drain，stop/error 不得冒充 completed。

## 4. 连续对话：独立授权、物理窗口

只接受当前 _Turn 在有效 speech_start/非空 STT 和无 error 下的 INTENT_END.intent_output.continue_conversation is True；同时要求 response 为合法成功 response_type（非 error）。授权与完成是两个条件，必须等 public run 正常返回（RUN_END 无 ERROR、已 join 待处理 TTS dispatch）且普通 TTS 若已尝试则同 UUID+playback ID 的真实 completed；两者到达先后不限，只执行一次。TTS_START/生成或 dispatch 失败、send_failed、终态 stopped/interrupted/failed、空 STT/intercept-only、取消、断开、缺失或 false 均不授权。无 TTS 的有效正常 Intent 回复保留旧 PR-C04 例外：确认成功 INTENT_END、真实正常 run 结束、无普通 TTS 尝试/待发资源，不能单凭 playback_id is None 推断。若正常播放但授权 false，同样等待正常终态再结束（不截短回复）。调用原 public tts_response_finished 只对仍有权的旧 caller执行一次，在新 caller 启动前完成。

- 完成且授权：HA 同步记录待消费 grant 后发 0x27；S3 若旧 UUID 已被 wake/reset 取代则忽略；有效时创建新 UUID 并发 local_followup START，HA 原子消费 grant，以新 Context 启动 STT 准备，旧 normal output 已释放。不继续共享旧 MIC UUID 或重放旧音频。新轮关联同一 HA chat session/AstrBot 会话，wake_word_phrase=None，不假装用户再次唤醒。先前 Pipeline 正常退出，设备无需额外旧 stop ACK。
- 本地只播独立 followup_01 beep 一次，使用同 output manager 和 b0.4 drain+尾部 gate；不使用人声 ready 或生成 TTS。安全 gate 后4s 从设备单调时钟计时；HA 的4s 监察容纳 ready 缓冲/传输，设备已有 speech_start 即取消；后续命令按原 15s 限、1s ready 限、gate后前导/PCM/EOF。短提示期间不上传 VAD/PCM，不把 beep 当新唤醒或有效回复；完全在短 gate 内的话按现产品取舍忽略。真实新 wake（短 gate 外）优先于免唤醒 speech_start，执行 local_wake 并撤销 grant，改为 ready/3s 窗口。普通非授权回复不启动任何等待 gate。
- 发送 grant 失败、未收到对应 START：HA 用 b0.4 5s gate 前 watchdog 作为初始同量级 handoff 上限（从 grant 发出至收到 START，超时撤销并定向 MIC_CAPTURE_STOP 旧 UUID；若后到 START 无 grant，定向结束新 UUID），收到合法 START 后转入原 prompt watchdog；设备端同一 UUID 一次接受，不因重复网络事件重播。无命令4s/准备失败/提示异常无法确认无声则释放回待机；本地缺资产且安全无声按 b0.4 skip，窗口照常。没有额外自动续轮或 beep 循环。

## 5. 表情：复用原 HA 仲裁，替换事件来源

| DisplayState（原优先级不变） | 新本地模式置位与退出；原 preset |
|---|---|
| wake_confirmed | 合法 local_wake START 100%，question；有效 gate/prompt 期间保持，到真实 command speech_start 时清除并进入 listening；取消/失败/换代清除。 |
| speaking | 当前普通 TTS AUDIO_STATE=playing，默认 music；当前有效 reply 调用 SetMood 则用最新白名单 mood 替代 music，仍是 speaking 状态；终态退出。buffering、TTS_START/END、prompt 不置位。 |
| tooluse | 当前 satellite_id + Context.id 的 astrbot_phase tool_call/tool_call_result，原 tooluse；退出/旧轮/错误清除。 |
| thinking | 仅有效命令的非空 STT_END，thinking；清 wake/listening/followup；后由更高优先级 speaking/tooluse 覆盖，完成清除。 |
| active_listening | gate 后真实 command speech_start，standby；清 wake 或 followup；speech_end 清 listening，STT_END 才进入 thinking，不从待机 VAD、STT_START 或 prompt 触发。 |
| explicit_content | 用户/自动化明确要求的既有内容；被高优先会话覆盖后仍有效则恢复。 |
| ai_mood | legacy 共存模式保留白名单/5s TTL 独立 intent。本地模式 SetMood 只设置当前 generation 的 speaking 内容，不独立参与优先级。不能由回答文本自动分类。 |
| followup_wait | 仅已授权且新 local_followup 的 COMMAND_GATE 安全开放后，standby；beep 内不置 followup_wait、不计4s；speech_start/超时/换代退出，不发 wake_confirmed。 |
| idle | standby/smiley/sleepy/sun/fish 原 30–90s 随机轮换，无候选显示概率/700ms/10s cooldown（legacy 共存可保留旧路径至 b9）。 |

所有显示更新只经 ExpressionCoordinator，begin_generation 原子清旧 session intents（含 mood/TTL），async_end_generation/异步回调按捕获 generation 检查。wake→listening、listening→thinking、followup→listening 通过同协调器一次状态转移/recompute，防止旧 wake_confirmed 优先级遮盖 listening。speech_end 到 STT_END 的短阶段不伪造 thinking；按现剩余 intent/idle 仲裁。旧候选/旧终态不能起屏，提示音不生成 speaking。HA 公开 Satellite state 仍由 Core 管理，不拿其 LISTENING 当真实听音要求。SPP 发送慢不阻塞诊断 reader/音频；显示任务复核 generation/gate，由现 lock 串行重算最新赢家，不回放每个过期画面。

**R10 产品裁决（2026-11-19，用户明确选择 TTS 输出区间替换默认图像）：** 本地模式有效非空 STT 后可接受 SetMood，最新一次覆盖旧值；从真实 matching playing 到终态使用该表情，不设 5s 截断，不新增 response-tail/timer/owner。播放前仅缓存，晚于 playing 的合法调用更新当前 speaking 内容；无 TTS、失败/取消、新 wake 或 followup、断线/unload 均清除；播放终态后拒绝提交，不补播。无 mood 时仍是 music，ESM-C09 优先级、硬 OFF、显式恢复、音频事件与 legacy 5s TTL 不变。

MCP/service schema 原样（name 等）；已有可信 HA voice context 的 mood 调用须通过捕获的 context→generation 校验，旧 context 拒绝。独立 MCP/手动调用无 voice context 时仅按当下有效 voice reply generation 提交（无 active reply 拒绝），明确不能识别所有上游无关联 ID 的延迟 MCP 请求；b8 验证边界，不编造 AstrBot→MCP 上游字段，不增加强制公共参数。旧 voice task 本地排队的 mood/phase 仍须捕获原 generation，不重绑定新轮。显式用户内容/实际工具副作用不是旧展示事件，不能假装已回滚。

ScreenPowerGate 硬门控：原固定 compatibility owner bool 接口，内部多 owner inhibit、temporary_wake TTL 原样；wake/打断/续聊不会自动释放关屏 owner 或调用 temporary_wake。OFF 仅更新 desired、不得发可见命令，ON 立即重算重发；SPP reconnect 按校验 DEVICE_STATUS/DEVICE_EVENT 同步，OFF 重申 OFF，ON 重发赢家。last_sent 仅证明 transport 写入；不从 opaque SPP reverse 猜物理像素。经典 ESP32 不知道 voice generation，不做表情仲裁；b0.2 的真实 bridge/SPP状态、断开与 7777 reconnect/mapping 是唯一运输边界。

## 6. 异常时序与恢复边界

| 场景 | 必须观察到的结果 |
|---|---|
| HA 未 ready/旧 cleanup 超时，或 wake 时网络不可用 | 已协商连接内按 VOICE-C04 1s gate 后上限，当前失败回 idle，旧仍定向清理；未协商/断线不承诺 ready、不缓存唤醒等待重播，AFE 常驻。 |
| 识别/思考/合成期间再次 wake，含未分配 playback ID | old dispatch 先失效，旧 pipeline/SSE/TTS owner 取消，新的 START 可先收、公开 caller 不并行；无 ID 不发泛 stop。 |
| 已播/旧 TTS 尚在路上、连续多次 wake | 本地停止旧音频，迟到 0x30 拒绝，旧 stop/state/PCM 无新轮权；最新 generation 唯一有效，旧 terminal 只处理其资源。 |
| beep/普通回复回声、长 TTS 饥饿 | 短 gate 内无命令或自身 wake；普通 TTS 不关闭 WakeNet、普通 VAD 不抢占；欠载不误完成；含词负样本与真人确认实测。 |
| 息屏期间打断、SPP 断开/经典 ESP32 重启 | 音频照常进行，旧 intents 清理而 inhibit 不变；桥不可用只影响显示/控制，真实重连后 OFF/当前赢家重申；无语音 reset。 |
| S3 重启/7778 失联或 HA unload/reload | S3 停旧输出及命令，清旧 connection epoch/授权、排尽再待机，绝不继续旧 HTTP 播放；HA async_disconnect/shutdown 定向取消 owners、收束 caller/计时/显示，重新握手无旧语音重放。7777 独立，S3 reset 按 b0.2 stale writer 回收、桥独立复位不影响语音。仅 7778 失联且 HA runtime 仍存活时 gate/inhibits 保持；HA unload 销毁内存 gate/显式内容，旧项目没有持久恢复合同。HA reload 新 runtime 按现默认 gate 与已校验 SPP 状态重算；若实际要求跨 HA 重载保持定时 OFF，需另行配置自动化重新施加/未来存储合同，本批不增加持久化、不得称 reload 后原 OFF 已恢复。 |

HA/设备双方失联清理不依赖对端再发 terminal；新握手前设备拒绝旧 owner，HA 不靠网络 stop 成功证明物理停止。SPP 重连和语音重连状态独立；涉及实际物理静音/屏幕均留 b10 实机证据。

## 7. 合同矩阵（设计出口，实施验收均未执行）

| 新合同 | 不变量 | 实施及具体验收 | 原合同/来源 |
|---|---|---|---|
| LIFE-C01 | epoch+session UUID+Context+playback 唯一对应；新 START 同步换代，FIFO 无旧 PCM、重复/旧 start inert | b5/b7 双端 codec、同包旧 PCM/end/start、新 ready、旧/重复 UUID/uptime、legacy；b10 抓包 | P65-A06/A16、VOICE-C01/05/06、PR-C14 |
| LIFE-C02 | 本地确认任一有效阶段可停止旧 DAC/HTTP；普通 VAD 不可；短 gate 唯一例外 | b7 fake worker+实际 stop/drain、未 ready/STT/合成/播放/续聊各打断、连续3次；b4/b6/b10 声学/延迟/电视 | P65-A10–A14、PR-C03/C06/C16–C18、H07–H09 |
| LIFE-C03 | HA 先失效 dispatch、定向 stop、取消 join caller/owner；诊断 RX 不等待旧 cleanup；最新轮不越过旧 public caller | b7 cancellation barrier、caller finally、stop 前未有 ID/已发 ID、连续确认、slow/failed cleanup、b0.4 ready timeout；b10 | P65-A07/A08/A11/A12/A16、PR-C03/C14–C16、P3-11 |
| LIFE-C04 | 普通 TTS 必须匹配 UUID+ID+epoch；单 output manager、stop/drain 后释放，旧请求不建 HTTP/新 owner，旧 terminal 不改新 | b5/b6 基础绑定、b7 stale 0x30/0x31/0x32、pending、hold/duplicate terminal、stop drain、长间隙/错误；b10 实机 | P65-A08/A09/A14/A16、PR-C11–C17、H08/H10 |
| LIFE-C05 | 原 ResultStream token/producer/GET/Wyoming FIN→EOF/FFmpeg 与 AstrBot session Stop 所有权；partial 文本保留、失败不假装成功 | b7 真实 HA/Wyoming mock cancellation、SSE 已接受/结束/失败/stop timeout，唯一 stop、锁顺序、未确认禁止复用；b10 实际服务 | P3-11/P3-T13/P3-T15、P65-A07–A09/A12、H12 |
| LIFE-C06 | 严格 true+有效 Intent+正常 run+真实 completed，或已证实无 TTS 的有效回答；只开一次授权 | b7 双事件先后/早 terminal/普通回复、缺失/false/error/取消/无 TTS有效 vs send 失败、duplicate grant；b10 | P65-A15、PR-C04/C12/C13、ESM-C08、H11 |
| LIFE-C07 | 0x27 单次授权→新 local_followup UUID/独立 beep，4s 从安全 gate，之后有效 speech 启 STT，真 wake 优先 | b7 codec/假钟 4s（beep前不计）、5s handoff watchdog、旧 grant、ready race、无命令/新 wake/短提示自触发，b6素材，b10真人 | P65-A04/A06/A15、PR-C01–C08/C14/C19、H11 |
| LIFE-C08 | 失联/unload/S3 reset 定向关旧语音，身份不跨连接；经典 ESP32/SPP/7777 状态不重置语音 | b7 双端 disconnect/timeout/reload/旧消息，b2桥独立，b8重连表情，b10独立重启 | P65-A06/A16、VOICE-C01/C07/C10、P68-HB15 |
| VIEW-C01 | 复用原优先级、idle/显式内容；wake、listening、thinking 按真实事件；移除本地模式候选随机显示 | b8 fake clock/事件序列、idle 30–90s、wake 100%、gate/speech/STT成功/空/错误/结束、覆盖恢复；b10 | ESM-C01–C05/C09/C14/C21/C23 |
| VIEW-C02 | tooluse/speaking/followup 只接收当前 generation 的真实事件，prompt 不作 ordinary TTS；旧事件/TTL/stop 不恢复旧 | b8 context/satellite/playback/UUID、乱序/重复/迟到、取消/新轮/续聊，b10 | ESM-C06–C10/C23、PR-C12–C14/C20 |
| VIEW-C03 | mood 白名单/本地 speaking 内容生命周期（legacy TTL）/上下文、显式内容、同一 gate/owner 与已有 schema；无 context 调用边界明示 | b8 原工具服务 schema 回归、已知旧 context/mood TTL、显式恢复、外部无 context 负样本；b10 | ESM-C11–C18/C22（未来功能仍后置）、P4-C01/C04/C05/C07–C14 |
| VIEW-C04 | OFF 硬门控，SPP 重连 OFF/当前赢家，真实 status 和 stale 7777 处理，显示拥塞不阻断语音，last_sent 非像素证明 | b2/b8 OFF wake/打断/多 owner/temporary TTL、双 socket 顺序、bridge reset/HA reload初始同步；b10实机 | ESM-C15–C20/C23、P68-HB15 |

本表覆盖 b0.5 分域，不代替 b0.6 对全部历史 ID 的闭环审计；主动播报/对话 P9 保持后置。b7/b8 均需针对自动化用例先红后绿，真实 HA/模拟服务测试与 b10 声学/两板/生产复验分开。历史 GAP/FAIL 原样保留。本批按路线 §2.2 对上述正常/异常时序与现有实现逐项自审（当前无独立 reviewer 工具）；b0.6 全量交叉评审仍未执行。当前只写设计、交叉引用及矩阵；无新包安装、生产代码/配置/部署/刷机/工具执行或实体状态修改。


---

## 8. Qwen Realtime 条件续聊适配（2026-11-22）

> 本节只为 B8 Qwen Realtime 路径补充续聊意图来源。前述 LIFE-C06/LIFE-C07 原始合同仍是设备 gate、真实播放完成、单次授权、4 秒窗口和 generation 生命周期的权威，不重写旧 AstrBot/HA Pipeline 的实现语义。

### 8.1 意图来源

Qwen GCP 7.0 没有原生 `continue_conversation` 字段或客户端/服务端续聊授权事件。P6.8 Qwen 路径采用用户已选择的方案 A：

- Qwen Agent 核心 `PROMPT.md` overlay 要求：只有真正需要用户进一步补充、选择或确认时，最终面向用户的完整回复才以中文“？”或英文“?”结尾；正常完成的答复不得加礼貌性反问。
- HA 只消费当前 turn/generation 的助手 `transcript.final`，去除末尾空白后检查是否以“？”或“?”结尾。
- `transcript.delta`、用户 role transcript、工具调用中间 response、`tool.call`、`audio.done`、`voice.state=idle` 以及 response failed/cancelled/incomplete 均不构成续聊意图。
- 该约定是 Prompt + HA 的应用层行为，不是 Qwen 原生结构化授权回执。未收到完整助手 final 文本、普通结束标点或任何失败/中断时默认不续聊。

旧 AstrBot/HA Pipeline 路径仍使用 HA 现有 `INTENT_END.intent_output.continue_conversation`，不得把 Qwen 的问号规则改成所有 Pipeline 共用规则。

### 8.2 物理续聊授权条件不变

问号只设置当前 turn 的待续聊意图，不立即开启 MIC。仍必须同时满足：
1. 当前 HA turn/generation 尚有效，助手最终响应正常完成且无中断/错误；
2. 本轮有效输入已经结束并按现有 ingress 规则 drain；
3. 对应 response 的物理输出具有匹配 playback_id；
4. ESP32 报告该 playback_id 的真实 `AUDIO_STATE=completed`；
5. 本轮续聊授权未消费、未被更高优先级的新 wake/interrupt 取消。

之后复用现有 `AudioSessionManager.grant_followup(session_id)` 和 `TYPE_FOLLOWUP_OPEN (0x27)`，只打开一次现有 4 秒 local_followup gate。既有 beep、beep 播放完成/声学尾部的安全 gate、真 wake 优先和旧 generation 隔离不变。不得用 Qwen `audio.done` 替代设备播放完成，也不得恢复已废弃的 8 秒 follow-up 规则。

### 8.3 Qwen session 与设备 turn 的连接边界

- 问号响应完成后，**保持原活动 Gateway WebSocket**，等待实际播放结束和 4 秒设备 gate；用户续聊音频经原 socket 发送，交由同一个 Realtime 会话处理。
- 第二轮仍创建新 HA Context/generation 和 ESP32 MIC UUID；Gateway 生成新的 turnId/responseId。上述 ID 不相互复用。
- 稳定 ConfigEntry.entry_id 映射到 Qwen URL sessionId，稳定 client.instance_id 表示 Tivoo Gateway 客户端/lease。它们不替代活动 socket。
- 普通回复无问号、follow-up 超时、失败或被打断时按现有资源所有权规则完成连接清理。若后续独立 wake 必须断线重连，session journal 的历史恢复需单独验收，不能假设重连等同 immediate follow-up 同 socket 上下文。
- 不增加 HA ChatSession、额外 MCP 工具、GCP 自定义授权事件或第二套续聊状态机；优先复用当前 per-turn `continue_conversation` bool 和 LIFE-C06/LIFE-C07。

详细合同与实现批次：[Qwen Realtime 条件续聊设计](2026-11-22-p6-8-qwen-realtime-followup-design.md)。助手文本标点保真和同活动 WebSocket 两轮上下文必须先由 B8.2 实测；其通过后再由 B8.5/B8.6 实现和测试，B8.7 才安装持久 PROMPT overlay。
