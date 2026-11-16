# P6.7 语音等待提示音规格

> 日期：2026-11-16
> 分支：`feature/p6-7-audio-prompts`（从已合入 P6.6 的 `main` 创建）
> 状态：b0–b3 已实施并部署；b3 声学验收发现三条提示音均会自触发 VAD/MIC session，PR-C18 FAIL，P6.7 整体未通过
> 合同：[P6.7 合同矩阵](2026-11-16-p6-7-ready-prompt-sound-contract-matrix.md)
> 计划：[P6.7 分批计划](../plans/2026-11-16-p6-7-ready-prompt-sound-batch-execution-plan.md)

## 1. 目标与边界

首次 KWS 唤醒成功、确认打断进入新一轮命令等待，以及每轮回答完成后进入免唤醒词 follow-up 时，立即异步请求播放一条短暂的本地预制提示音。首期固定三种候选短句“我在”“在的”“你说”，随机选择且不连续重复；不再使用“嘟”声。播放时已开始收集用户命令，不能因为提示音占用 DAC 而阻塞麦克风、STT、计时器或取消逻辑。

本功能只增强 P6.5 的音频会话层；P6.6 表情 Coordinator、screen gate、AstrBot 对话及 TTS 合成链保持各自所有权。提示音无须 LLM、无运行时 TTS、无第二套音频输出链或新 ESP32 TVIO 消息。仅在本规格定义的实际“等待命令”入口播放，不能在每个 STT_START、候选 VAD、思考中、普通回答开始时误播。

## 2. 已核对的实现事实

- `homeassistant/custom_components/tivoo/assist_satellite.py` 的 `AudioSessionCoordinator`：`WAKE_WORD_END` 成功时启动 5 秒 `command_timeout`；确认打断从 `_start_turn(STT, confirmed=True)` 经旧轮清理进入新 STT，5 秒从 `STT_START` 起算；`_open_followup()` 在对应 TTS 的 `AUDIO_STATE=completed` 后开启 8 秒 `followup_timeout`，无 TTS 的有效轮次亦能进入 follow-up。
- `audio_session.py` 保留单个 MIC session 的 AEC 后 PCM 与跨 turn 订阅，follow-up 中 `speech_start` 立即开启 STT；不依赖提示音结束。
- `transport.py` 有 `async_send_tts_play(playback_id, url, mime_type)`，通过既有 `0x30 TTS_PLAY` 发送；回放状态 `0x32 AUDIO_STATE` 已由 `register_playback_handler` 交给 Satellite。
- ESP32 `audio_resource.c` 已接受 `audio/mpeg` 或项目的原始 PCM MIME，增量 HTTP GET 并以 `playback_id` 进行单音源排他、重复去重、`AUDIO_STOP` 定向停止，终态为 `completed/stopped/failed`；设备状态消息中的 `source` 固定是 `tts_http`，即便复用该通道播放提示音也不会变成新 source。
- `audio_output_manager.c` 为唯一 32 kHz DAC PCM owner，最终 I²S TX 派生 16 kHz AEC 回声参考；`audio_frontend.c` 的 RX/AFE/VAD 开机常驻，`vad_mute_playback=false`，现有参考延迟 80/16000 秒只是配置值，实际声学消除能力仍需现场验证。
- HA 2026.11.0 安装源码的 `frontend/__init__.py` 将 `hass.config.path("www")` 注册为 `/local` 静态路径；`http/static.py` 按文件扩展名返回 MIME。Python MIME 表将 `.mp3` 识别为 `audio/mpeg`。ESP32 实际 HTTP 响应、路径及板端解码仍需在 P6.7b0 验证。
- P6.5b11 声学报告的 P65-A13 仍为 BLOCKED；不能把已有 AEC 数字参考等同于提示音/真人同时讲话的已验收证据。

## 3. 方案与文件

`HA AudioSessionCoordinator` 作为触发决策 owner；新建轻量 `PromptSoundPlayer` 管理独立提示音 `playback_id`、去重随机选择、异步下发、终态与定向取消。接在既有 Adapter 的状态回调路径中，按 `playback_id` 将提示音事件分流，不将其当作 `_Turn.tts.playback_id`，不得影响正常 `_open_followup()` 或 P6.6 `speaking` 显示。

素材源文件建议置于仓库 `homeassistant/prompt_assets/`，生产副本放 HA 的 `/config/www/tivoo/prompts/`，LAN URL 为 `http(s)://<HA内部地址>/local/tivoo/prompts/<文件名>.mp3`。首期固定三个文件 `ready_01.mp3`…`ready_03.mp3`；32 kHz、单声道、MP3、`audio/mpeg`、尽量不超过 0.9 秒。三个短句必须使用当前生产 HA Pipeline 实际绑定的同一 TTS Provider/模型/voice 参数一次性生成（当前为 `tts.sherpa_onnx_matcha_baker`、voice `0`、Matcha Baker + Vocos、`sid=0`、`speed=1.0`），不得用其它“可用 TTS”替代；转码前后只允许为适配播放加入必要静音和采样率/封装转换，不做改变音色的额外处理。每条文件前后都要保留可检测的短静音，避免掐头去尾；**每次播放只读取已存在的文件**。首期不做素材上传 UI 或配置页面；更换素材替换对应文件即可。资产制作与来源/使用权限记录在 b0，不把第三方模型示例语音当作可随意重分发素材。

内部 URL 由 HA 现有 LAN 地址推导，复用 `get_url(... allow_internal=True, allow_external=False, allow_cloud=False, allow_ip=True)` 的限制；单独构造、校验 `/local/tivoo/prompts/` 下的固定文件名。不得把 `audio_resource.build_internal_tts_url` 的 `/api/tts_proxy/` 白名单放宽；该函数继续只处理 TTS Proxy。

## 4. 事件时序

| 等待入口 | 调用点 | 计时与提示音关系 |
|---|---|---|
| 初次唤醒 | 当前 turn 的有效 `WAKE_WORD_END`（含 `wake_word_output`） | 原有 5 秒从 Detection 起算；异步播放，不等待 MP3 |
| 确认打断 | side KWS 成功引起新 `_start_turn(STT, confirmed=True)` | 优先完成旧轮定向 AUDIO_STOP / owner 清理；新 STT 仍先获得 handoff PCM；原有 5 秒从新 `STT_START` 起算；提示音不得抢占旧 TTS |
| 连续对话等待 | `_open_followup()` 首次进入等待阶段 | 原有 8 秒从相关播放真实 completed / 无 TTS 的有效结束起算；立即启用 VAD→STT 门控，异步请求提示音 |
| 后续新增命令等待入口 | 仅在明确接入 `AudioSessionCoordinator` 的真实状态转移后 | 必须显式登记、复用同一触发 API；不能靠每个语音事件通用推断 |

提示音的开始、结束、失败、跳过均不得重置 5/8 秒定时器，不得调用 `tts_response_finished()`、不触发另一次 follow-up、不影响用户当前的 Pipeline/ASTRBOT 结果。音频请求失败时安静跳过，不让等待命令或对话因提示音失败而失败。

## 5. 播放所有权、冲突与取消

ESP32 当前只支持单一受控音源；`TTS_PLAY` 是沿用的传输消息名，不表示素材必经 TTS 推理。HA 必须跟踪提示音 ID 和正常 TTS ID：

1. 一个等待入口最多一个提示音请求，新的 generation/会话结束则撤销旧的待发送请求；同一入口重复事件不得重复播。
2. 若已存在上一轮真实 TTS，确认打断路径先执行旧轮已有的匹配 ID `AUDIO_STOP` 和清理，再允许提示音下发；不要因为设备 `audio_busy` 就用重试队列无限排队。
3. 用户开始命令时不抑制上传；若提示音还没下发可直接跳过，若已播放则可对**提示音的 ID** 定向停止。`STT_VAD_START` 代表有效命令语音；follow-up `speech_start` 只是开始 STT 的门控，不得由此取消正常 TTS 或触发全局停止。
4. 如正常 TTS 准备占用同一音频出口，先确认提示音已 completed/stopped（或将其停止并等待设备释放），再发送实际 TTS_PLAY；不能发送两个并行音频请求而依赖 `audio_busy` 作为正常流程。
5. 提示音 `AUDIO_STATE` 必须只由提示音 owner 接收；旧 generation 的迟到状态与停止消息不能影响新 generation 或真实 TTS。短音频结束不能驱动 P6.6 speaking、follow-up 或表情清理。

首期不混音、不加入第二条独立 DMA 输出、不做“先播完提示音再听人说话”的队列。

## 6. AEC 与现场边界

提示音与正常回答走同一 `audio_output_manager`/PCM5102；AEC R 取最终下发的 TX PCM，麦克风 RX/AFE/VAD 不因提示音暂停。首次唤醒后的现有 STT 和 follow-up 的 VAD→STT 可在提示音播放中处理真人命令。

回声能否避免自触发只能通过现场实测判定，尤其检查“我在/在的/你说”残余导致的 `speech_start` 或 STT 误识别、命令首字丢失、KWS 错误检测、参考错位/欠载。先采用简短、适度音量的素材与既有 AEC；不通过静音麦克风、延后 STT、强制屏蔽播放前几百毫秒来掩盖缺陷。若声学样本证明有实质干扰，再优先调提示音长度/电平与参考时间轴，而非无证据增加模型/状态机。

## 7. 不在 P6.7 实现

不扩展 ESP32 固件协议、Flash 本地存储播放器、配置面板、音频素材自动生成服务、主动广播/announce、LLM 控制提示音、Tivoo 屏幕状态或 P6.6 表情优先级。只有实际 HTTP 首声延迟不满足体验时，另开决策评估 Flash 本地短音频；不能在本批预先增加一套本地解码路径。
