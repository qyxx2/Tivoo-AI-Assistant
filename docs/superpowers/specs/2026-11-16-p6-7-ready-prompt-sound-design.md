# P6.7 语音等待提示音规格

> 日期：2026-11-16
> 分支：`feature/p6-7-audio-prompts`（从已合入 P6.6 的 `main` 创建）
> 状态：b0–b3 已实施并部署；b3 发现并复现三条提示音自触发 VAD/MIC session。后续已采用仅提示音播放生命周期内的 VAD suppression 修复并完成实机复测；自触发故障按 prompt-only 人声检测 gate 关闭；按后续产品决策，提示音窗口内不再要求同时识别人声，普通 TTS 打断能力保持原行为
> 合同：[P6.7 合同矩阵](2026-11-16-p6-7-ready-prompt-sound-contract-matrix.md)
> 计划：[P6.7 分批计划](../plans/2026-11-16-p6-7-ready-prompt-sound-batch-execution-plan.md)

## 2026-11-17 首次唤醒顺序修订

用户明确采用“说唤醒词 → 听到我在/在的/你说 → 再说命令”。当存在可用提示音素材时，首次有效 KWS 结束旧 WAKE_WORD Pipeline，沿用既有取消/清理路径；播放提示音并等待其 completed/stopped/failed 后，以当前 ingress offset 开启新的 STT Pipeline。旧 Pipeline 的 wake tail、queued_audio 和提示音之前的 PCM 不进入命令识别。5 秒 command_timeout 从新的 STT_START 起算。提示音等待最多 5 秒，超时定向停止后降级进入 STT；缺素材或发送失败也不得永久阻塞。确认打断和免唤醒 follow-up 仍保留原时序，本修订只改变首次唤醒。

断连或真实 TTS 发送失败时，必须按原 playback_id 释放 HA 提示音播放器中的 TTS 占用，不能依赖已经不可能收到的旧连接终态。迟到旧 ID 不得释放新的 TTS 占用。

详见 [修复记录](../reports/2026-11-17-ready-prompt-wake-order-fix.md)。以下旧时序描述若与本节冲突，以本节为准。

## 1. 目标与边界

首次 KWS 唤醒成功、确认打断进入新一轮命令等待，以及 HA 明确返回 `continue_conversation=true` 后进入免唤醒词 follow-up 时，立即异步请求播放一条短暂的本地预制提示音。首次/确认等待使用三种 ready 候选短句“我在”“在的”“你说”，随机选择且不连续重复；follow-up 只使用独立 `followup_01.mp3`（“嗯？”），允许跨 generation 重复；不再使用“嘟”声。首次唤醒的 5 秒从提示音结束后的 STT_START 开始；确认打断和 follow-up 的 5/8 秒保持原时序；但提示音实际输出期间明确暂停人声检测与 MIC 上传，声学尾部结束后立即恢复。整句完全落在该短窗口内可能被忽略，这是本 workaround 的明确取舍；MIC RX/AFE/AEC 始终继续运行。

本功能只增强 P6.5 的音频会话层；P6.6 表情 Coordinator、screen gate、AstrBot 对话及 TTS 合成链保持各自所有权。提示音无须 LLM、无运行时 TTS、无第二套音频输出链或新 ESP32 TVIO message type。为区分提示音和正常 TTS，沿用 `0x30 TTS_PLAY` 并允许可选布尔字段 `suppress_vad`；省略/false 保持原语义，只有 `PromptSoundPlayer` 对预制提示音置 true。仅在本规格定义的实际“等待命令”入口播放。

## 2. 已核对的实现事实

- `homeassistant/custom_components/tivoo/assist_satellite.py` 的 `AudioSessionCoordinator`：`WAKE_WORD_END` 成功时启动 5 秒 `command_timeout`；确认打断从 `_start_turn(STT, confirmed=True)` 经旧轮清理进入新 STT，5 秒从 `STT_START` 起算；当前 turn 记录 `INTENT_END.intent_output.continue_conversation`，仅值严格为 `true` 时在对应 TTS `AUDIO_STATE=completed` 或无 TTS 的有效轮次结束后调用 `_open_followup()`；否则结束当前 MIC session。
- `audio_session.py` 保留单个 MIC session 的 AEC 后 PCM 与跨 turn 订阅。正常路径的 follow-up `speech_start` 仍立即开启 STT；所有预制提示音实际输出期间 ESP32 暂停 VAD 判定以及 MIC_ACTIVITY/MIC_PCM 上送，RX/AFE/AEC 继续；gate 结束后下一次真人语音可重新产生 `speech_start`。
- `transport.py` 有 `async_send_tts_play(playback_id, url, mime_type)`，通过既有 `0x30 TTS_PLAY` 发送；回放状态 `0x32 AUDIO_STATE` 已由 `register_playback_handler` 交给 Satellite。
- ESP32 `audio_resource.c` 已接受 `audio/mpeg` 或项目的原始 PCM MIME，增量 HTTP GET 并以 `playback_id` 进行单音源排他、重复去重、`AUDIO_STOP` 定向停止，终态为 `completed/stopped/failed`；设备状态消息中的 `source` 固定是 `tts_http`，即便复用该通道播放提示音也不会变成新 source。
- `audio_output_manager.c` 为唯一 32 kHz DAC PCM owner，最终 I²S TX 派生 16 kHz AEC 回声参考；`audio_frontend.c` 的 RX/AFE 开机常驻且全局 `vad_mute_playback=false`。AEC 固定参考延迟已实测标定为 760 samples / 47.5 ms；仅当当前 `TTS_PLAY` 明确带 `suppress_vad=true` 时，ESP-SR VAD 在该提示音实际播放 owner 生命周期内 disable/reset，终态 enable/reset。普通 TTS 不进入此路径。
- HA 2026.11.0 安装源码的 `frontend/__init__.py` 将 `hass.config.path("www")` 注册为 `/local` 静态路径；`http/static.py` 按文件扩展名返回 MIME。Python MIME 表将 `.mp3` 识别为 `audio/mpeg`。ESP32 实际 HTTP 响应、路径及板端解码仍需在 P6.7b0 验证。
- P6.5b11 声学报告的 P65-A13 仍为 BLOCKED；不能把已有 AEC 数字参考等同于提示音/真人同时讲话的已验收证据。

## 3. 方案与文件

`HA AudioSessionCoordinator` 作为触发决策 owner；新建轻量 `PromptSoundPlayer` 管理独立提示音 `playback_id`、去重随机选择、异步下发、终态与定向取消。接在既有 Adapter 的状态回调路径中，按 `playback_id` 将提示音事件分流，不将其当作 `_Turn.tts.playback_id`，不得影响正常 `_open_followup()` 或 P6.6 `speaking` 显示。

素材源文件建议置于仓库 `homeassistant/prompt_assets/`，生产副本放 HA 的 `/config/www/tivoo/prompts/`，LAN URL 为 `http(s)://<HA内部地址>/local/tivoo/prompts/<文件名>.mp3`。当前固定 `ready_01.mp3`…`ready_03.mp3` 加 `followup_01.mp3`；32 kHz、单声道、MP3、`audio/mpeg`、尽量不超过 0.9 秒。所有短句必须使用当前生产 HA Pipeline 实际绑定的同一 TTS Provider/模型/voice 参数一次性生成（当前为 `tts.sherpa_onnx_matcha_baker`、voice `0`、Matcha Baker + Vocos、`sid=0`、`speed=1.0`），不得用其它“可用 TTS”替代；转码前后只允许为适配播放加入必要静音和采样率/封装转换，不做改变音色的额外处理。每条文件前后都要保留可检测的短静音，避免掐头去尾；**每次播放只读取已存在的文件**。首期不做素材上传 UI 或配置页面；更换素材替换对应文件即可。资产制作与来源/使用权限记录在 b0，不把第三方模型示例语音当作可随意重分发素材。

内部 URL 由 HA 现有 LAN 地址推导，复用 `get_url(... allow_internal=True, allow_external=False, allow_cloud=False, allow_ip=True)` 的限制；单独构造、校验 `/local/tivoo/prompts/` 下的固定文件名。不得把 `audio_resource.build_internal_tts_url` 的 `/api/tts_proxy/` 白名单放宽；该函数继续只处理 TTS Proxy。

## 4. 事件时序

| 等待入口 | 调用点 | 计时与提示音关系 |
|---|---|---|
| 初次唤醒 | 当前 turn 的有效 `WAKE_WORD_END`（含 `wake_word_output`） | 存在素材时先结束旧 WAKE_WORD Pipeline，再等待提示音结束；新 STT 从新鲜 PCM 开始并启动 5 秒计时 |
| 确认打断 | side KWS 成功引起新 `_start_turn(STT, confirmed=True)` | 优先完成旧轮定向 AUDIO_STOP / owner 清理；新 STT 仍先获得 handoff PCM；原有 5 秒从新 `STT_START` 起算；提示音不得抢占旧 TTS |
| 连续对话等待 | 当前 turn 的 `continue_conversation=true` 且回答完成后 `_open_followup()` 首次进入等待阶段 | 8 秒从相关播放真实 completed / 无 TTS 的有效结束起算；异步请求提示音。`false`/缺失时不进入该阶段并结束 MIC session。提示音实际输出期间暂停 VAD/MIC_ACTIVITY/MIC_PCM，RX/AFE/AEC 继续；最后 TX 样本再等待实测 47.5 ms 声学尾部后恢复 VAD→STT 门控 |
| 后续新增命令等待入口 | 仅在明确接入 `AudioSessionCoordinator` 的真实状态转移后 | 必须显式登记、复用同一触发 API；不能靠每个语音事件通用推断 |

除上述首次唤醒改为提示音之后起计 5 秒外，提示音事件不得重置现有等待定时器，不得调用 `tts_response_finished()`、不触发另一次 follow-up、不影响用户当前的 Pipeline/ASTRBOT 结果。音频请求失败时安静跳过，不让等待命令或对话因提示音失败而失败。

## 5. 播放所有权、冲突与取消

ESP32 当前只支持单一受控音源；`TTS_PLAY` 是沿用的传输消息名，不表示素材必经 TTS 推理。HA 必须跟踪提示音 ID 和正常 TTS ID：

1. 一个等待入口最多一个提示音请求，新的 generation/会话结束则撤销旧的待发送请求；同一入口重复事件不得重复播。
2. 若已存在上一轮真实 TTS，确认打断路径先执行旧轮已有的匹配 ID `AUDIO_STOP` 和清理，再允许提示音下发；不要因为设备 `audio_busy` 就用重试队列无限排队。
3. 若用户语音在提示音 gate 尚未开启前已形成有效 `speech_start/STT_VAD_START`，仍按既有逻辑优先用户并取消/跳过提示音；一旦提示音 gate 已开启，该短窗口内不再产生 VAD/MIC 上传，也不依赖其中的讲话去停止提示音。gate 恢复后下一段语音重新按原逻辑进入 STT。正常 TTS 的打断路径不变。
4. 如正常 TTS 准备占用同一音频出口，先确认提示音已 completed/stopped（或将其停止并等待设备释放），再发送实际 TTS_PLAY；不能发送两个并行音频请求而依赖 `audio_busy` 作为正常流程。
5. 提示音 `AUDIO_STATE` 必须只由提示音 owner 接收；旧 generation 的迟到状态与停止消息不能影响新 generation 或真实 TTS。短音频结束不能驱动 P6.6 speaking、follow-up 或表情清理。

不混音、不加入第二条独立 DMA 输出；首次唤醒明确采用先播完提示音再开启命令 STT。

## 6. AEC 与现场边界

提示音与正常回答走同一 `audio_output_manager`/PCM5102；AEC R 取最终下发的 TX PCM。麦克风 RX、AFE、AEC 始终运行；仅 `suppress_vad=true` 的提示音实际输出期间关闭 ESP-SR VAD，并暂停 MIC_ACTIVITY/MIC_PCM 向 HA 上送。数字输出结束后继续保持 gate 到实测 TX→mic 延迟 760 samples / 47.5 ms（实现取整 48 ms）结束，再恢复 VAD/MIC。普通 TTS 仍保持 VAD 可用，因此回答播放中的唤醒打断能力不受影响。

b3 与 47.5 ms AEC 延迟标定后的现场复测都证明三条提示音仍会自触发 VAD；额外增益矩阵也没有得到稳定可用的电平阈值。因此允许采用**提示音 owner 生命周期绑定**的 VAD suppression，而不是固定毫秒静音窗：当前产品决策不再要求提示音与真人讲话同时识别：gate 内暂停 VAD/MIC_ACTIVITY/MIC_PCM，RX/AFE/AEC 仍运行；普通 TTS 不进入 gate。代价是整句落在约 0.7–0.9 秒提示音窗口内可能被忽略。

## 7. 不在 P6.7 实现

不新增 ESP32 message type、第二套音频协议、Flash 本地存储播放器、配置面板、音频素材自动生成服务、主动广播/announce、LLM 控制提示音、Tivoo 屏幕状态或 P6.6 表情优先级。`0x30 TTS_PLAY` 仅增加向后兼容的可选 `suppress_vad` 布尔字段，默认 false；不得把它扩展成全局“播放即关闭 VAD”。只有实际 HTTP 首声延迟不满足体验时，另开决策评估 Flash 本地短音频。
