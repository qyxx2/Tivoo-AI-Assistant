# P6.5 常驻音频会话与 KWS 确认打断分批执行计划（b6 起）

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 在 P6.5 完成 ESP32 常驻 I2S/AEC/VAD、跨 Pipeline 的持续 MIC 上传、由 NAS KWS 命中确认的打断，以及全双工 PCM5102 播放闭环。

**Architecture:** 保留现有 7778 MIC_PCM、HA Assist Pipeline、P7A KWS/STT/TTS、AstrBot HTTP/SSE 和 TTS_PLAY + 单次 HTTP GET。把 ESP32 物理采集、网络 MIC session 和 Pipeline run 分离；HA 使用持久 ingress 和独立 KWS watcher。播放期间只有 KWS Detection 能抢占；VAD 仅负责空闲上传门控和播放结束后的短 follow-up。

**Tech Stack:** ESP-IDF / classic ESP32-WROVER-E；ESP-SR 2.6.1；esp_audio_codec 2.6.2；esp_audio_effects 1.4.5；Home Assistant Core 2026.11.0；AstrBot 4.29.4；现有 sherpa-onnx / Wyoming P7A 服务。

**Spec:** `docs/superpowers/specs/2026-11-13-p6-5-persistent-audio-session-and-kws-interruption-contract-matrix.md`；AstrBot 子链路：[HTTP/SSE 推理取消规格](../specs/2026-11-13-astrbot-http-sse-inference-cancellation-spec.md)。

## Global Constraints

- 仅在 `feature/p6-5-ha-cancellation-preflight` 从 HEAD `d2deacb` 继续；保留用户已有未提交修改，不 reset、不 stash、不覆盖。
- P6 既有 TCP 7777/7778、TVIO v1 16-byte header、Sequence、旧消息类型和 P5 SPP 行为保持兼容。
- MIC_PCM 16 kHz / Mono / S16LE、单载荷最大 4 KiB、20 ms 帧建议、有界队列。
- I2S 同一 controller 全双工 32 kHz / Stereo / 32-bit Slot；INMP441 M + 最终 TX PCM R；经典 ESP32 SR AEC High Performance。
- ESP32 开机后 RX/AEC/VAD 常驻；MIC_CAPTURE_STOP 只结束网络上传。
- **VAD 绝不单独触发 AUDIO_STOP、Pipeline cancel 或 AstrBot Stop；只有 NAS KWS Detection 可以中断正在处理/播放的回复。**
- 首次唤醒从 WAKE_WORD；KWS 确认打断和 follow-up 从 STT。
- 首次 KWS 候选：最近 MIC_ACTIVITY speech_end 后 3 秒无新 speech_start 即取消未命中 WAKE_WORD Pipeline；首次 speech_start 起 15 秒候选硬上限。两者由 AudioSessionCoordinator 实现，HA WakeWordSettings.timeout 默认 None，Assist Satellite 公开入口不暴露该参数。
- KWS 命中后：从 Detection 开始 5 秒 command-start watchdog；HA STT_VAD_START（VoiceCommandSegmenter 已检测到命令语音）时取消。超时仍无该事件则取消空 STT turn。
- HA VoiceCommandSegmenter 当前默认：0.3 秒起始 speech、1.0 秒 command_seconds、0.7 秒结束静音、15 秒 segment timeout；Sherpa STT_MAX_SECONDS=300 是另一层上限。follow-up 8 秒从物理播放完成起算。
- HA VoiceCommandSegmenter 当前默认 15 秒是最大单轮分段超时，不是 follow-up 时长。HA ChatSession 5 分钟和 AstrBot session 24 小时都不是 MIC upload window。
- P3 是 AstrBot SSE reader 和 owner-matched session Stop 唯一 owner；同一个 session 的 Chat/Stop 必须串行。
- TTS producer、generator、HTTP consumer queue、Wyoming writer、P7A request/worker 各自在真实 owner 边界释放；删除 token/关闭 GET 不代表 producer canceled。
- 保留 TTS_PLAY + ESP32 单次 HTTP GET；不新增原始 PCM TCP 推送，不将整段音频缓存进 ESP32 RAM。
- 不用 task 全局扫描、猜 task name、卸载整个 Wyoming Config Entry 或关闭服务来代替单轮取消。
- fake PCM、自动化、NAS 联调和真实麦克风/DAC 声学验收分开记录。

## Review Focus

1. 播放/Intent 期间普通环境人声或 VAD 活动：不能停止 TTS/取消 Pipeline；回答后的 8 秒 follow-up 误识别环境讲话只允许启动 STT，不得冒充播放中断（b8/b9/b11）。
2. TTS 回声或 TTS 文本含唤醒词：AEC R 必须取最终 TX PCM，并有专门 KWS 负样本（b10/b11）。
3. KWS hit 后用户已经继续说命令：同一有序 MIC ingress 不丢音；Detection 到 STT 接管最多缓存 15 秒/480,000 bytes，覆盖 AstrBot Stop 的 10 秒等待预算，按 HA ingress index 切分，不比较跨设备时钟（b7/b9）。
4. 已输出 partial plain 后取消：P3 必须关闭 SSE、同 owner Stop 一次，且无迟到文本（b6）。
5. HTTP GET 断开、Pipeline cancel、TTS producer cancel 是三个独立事件；首次 KWS miss 由 3 秒 speech-end watchdog 与 15 秒候选硬上限收口（b6/b7）。

## 模块边界

| 文件/位置 | 责任 | 批次 |
|---|---|---|
| `homeassistant/custom_components/tivoo/audio_session.py` | 持久 MIC ingress、跨 turn iterator、有界 pre-roll/handoff | b7 |
| `homeassistant/custom_components/tivoo/assist_satellite.py` | Satellite Pipeline caller、KWS watcher、generation、timer coordinator | b7/b9 |
| `homeassistant/custom_components/tivoo/tts_lifecycle.py` 或实证确认的既有 owner 文件 | 单轮 TTS producer/consumer cancel + await | b6 |
| `homeassistant/custom_components/tivoo/diagnostics.py` / `transport.py` | MIC_ACTIVITY 0x24、capability 与状态路由 | b7 |
| `homeassistant/custom_components/astrbot/conversation.py` | 仅 Tivoo Satellite 请求的 follow-up 意图；P3 仍拥有 Stop | b7 |
| `services/sherpa_wyoming/run.py` / `providers/tts.py` | 只在 EOF 测试复现残留时修复请求 owner | b6 |
| `esp32/firmware/main/audio_capture.c/.h` | I2S RX、INMP441 提取/降采样 | b8 |
| `esp32/firmware/main/audio_frontend.c/.h` | AFE M/R、常驻 AEC/VAD、MIC_ACTIVITY | b8 |
| `esp32/firmware/main/audio_output_manager.c/.h` | 最终 TX PCM、AEC reference tap、全局 stop | b10 |
| `esp32/firmware/main/audio_playback.c/.h` | HTTP GET、MP3 解码、SRC、PCM 输出 | b10 |
| `tests/homeassistant/`, `tests/services/`, `tests/esp32/` | lifecycle、协议、AEC/DAC 和 host 自动化 | b6–b11 |

若现有固件/HA 目录已存在同职责模块，复用原文件，不创建重复实现。

---

## P6.5b6 — 取消 owner 收口与 partial-SSE 实测

**Goal:** 修复/封装真实单轮 TTS producer 取消入口，并验证 AstrBot 已输出 plain 后的 Stop。b6 未通过前，后续端到端打断验收保持 BLOCKED。

### Task 1：真实 AstrBot partial-output Stop

**Files:** `tests/homeassistant/custom_components/astrbot/test_conversation.py`；必要时复用 `tests/homeassistant/test_assist_pipeline_tts_cancellation.py`；报告 `docs/superpowers/reports/2026-11-13-p6-5b6-cancellation-owner-closeout.md`。

- [ ] 真实 AstrBot 4.29.4 Chat 收到 run_started 和至少一条 plain 后调用同 owner Stop。
- [ ] 记录 stopped_count、Stop 后 complete/end、plain 是否继续、session is_running/active_runs。
- [ ] 清理测试 session；API Key secret 不进入日志或文档。
- [ ] 扩展 fake endpoint：plain 前取消、plain 后取消、complete 无 end、Stop 403/timeout；断言 SSE close、Stop exactly once、原 CancelledError 传播、lock 释放。
- [ ] 运行 P3 Conversation tests 与 HA cancellation 集成测试，区分真实服务和 fake 证据。

### Task 2：TTS producer/consumer真实 owner

**Files:** 证据确认后修改 `homeassistant/custom_components/tivoo/tts_lifecycle.py` 或 `audio_resource.py`；测试 `tests/homeassistant/test_assist_pipeline_tts_cancellation.py`、`tests/services/sherpa_wyoming/test_server.py`。

- [ ] 用事件屏障追踪 Pipeline caller、ResultStream、TTSCache producer、data_gen、text generator、HTTP queue、Wyoming writer、P7A handler/request/input/worker/callback。
- [ ] 查找 HA Core 2026.11.0 可用的受支持资源 owner seam。若无，形成一个窄、版本锁定且可回归测试的项目 owner adapter；不得全局 task scan 或卸载 Config Entry。
- [ ] 冻结可定向调用的取消接口（例如 `async_cancel(playback_id)`），由真正创建 producer 的 owner 执行 cancel/close 并 await。
- [ ] GET close 只移除自己的 consumer queue；Pipeline cancel 必须取消该 run 的 producer。
- [ ] 模拟真实 TCP EOF，验证 P7A handler/request/input/worker/callback 全部结束；若有残留，在 P7A request owner 修复。
- [ ] 取消后无迟到 text/PCM/callback/TTS_PLAY；清理测试屏障不算产品 PASS。
- [ ] 若无法得到可证明的定向 producer handle，b6 记为 BLOCKED，暂停依赖该能力的端到端验收，不用“设备静音”冒充取消完成。

**Exit gate:** partial-plain Stop 证据；producer/consumer/Wyoming/P7A owner 清晰；所有旧任务退出、无迟到音频。

## P6.5b7 — HA 持久 MIC ingress 与会话协调

**Goal:** 一个 MIC session 跨越多轮 Pipeline，初始 KWS、STT、side KWS 和 follow-up 顺序消费同一条 ingress。

**Files:** `audio_session.py`、`diagnostics.py`、`transport.py`、`__init__.py`、新建/复用 `assist_satellite.py`、P3 `conversation.py`；测试 `test_audio_session.py`、`test_transport.py`、`test_assist_satellite.py`。

- [ ] RED tests：MIC_SESSION_START 创建长期 ingress；多个顺序 iterator/订阅可开始结束而不结束 device upload；session end/stop 只影响匹配 UUID。
- [ ] 将单次 iterator_claimed 改为一个 ingress + 有界 per-turn subscription/handoff；保持 4 KiB MIC_PCM 上限和旧 session ID 丢弃规则。KWS Detection 后用于新 STT 的 handoff 固定为 15 秒/480,000 bytes，覆盖 P3 Stop 最长 10 秒的现有等待预算，按 HA ingress index 截取 Detection 后的音频。
- [ ] 添加有界 pre-roll、KWS-to-STT handoff、队列深度/overflow 结果；不累积无限 PCM。
- [ ] 新增 MIC_ACTIVITY 0x24：严格校验 UUID、speech_start/speech_end、uptime_ms；仅 HELLO 声明 mic_activity_events 时处理。首次上传顺序为 MIC_SESSION_START → MIC_ACTIVITY speech_start → pre-roll MIC_PCM；验证 TCP Sequence 顺序。
- [ ] AudioSessionCoordinator 独占 session、turn generation、pipeline handle、KWS watcher、playback_id 和 timer；transport 只负责消息分发。
- [ ] Pipeline RUN_END 不停止 MIC session；只有 wake miss、首次候选 15 秒硬上限、command timeout、follow-up timeout、异常/unload 关闭上传。
- [ ] 首轮窗口：WAKE_WORD 阶段由 AudioSessionCoordinator 监控 MIC_ACTIVITY；最近 speech_end 后 3 秒无新 speech_start 时取消未命中 Pipeline；从首次 speech_start 起 15 秒候选硬上限。不要依赖 HA WakeWordSettings 默认值（实际为 None），也不要复制 Satellite 基类未公开的参数。
- [ ] KWS Detection 时启动 5 秒 command-start watchdog；HA STT_VAD_START（VoiceCommandSegmenter 检测到至少 0.3 秒命令语音）到达时取消。超时没有 STT_VAD_START 就取消空 STT turn，不触发 AstrBot Stop（P3 Chat 尚未开始）。
- [ ] 定义命令端点测试：HA VoiceCommandSegmenter 默认 0.3 秒起始 speech、1.0 秒 command_seconds、0.7 秒 silence 和 15 秒 timeout；P7A requires_external_vad=true 必须使用此 segmenter，STT_VAD_START 用于取消 5 秒空命令 watchdog。
- [ ] Follow-up：仅在设备报告真实 playback completed 后启动 8 秒定时器；speech_start 取消 timer 并从 STT 开新 turn；到期 MIC_CAPTURE_STOP 一次，物理采集不停止。
- [ ] P3 ConversationResult：保留 async_get_result_from_chat_log() 的 response/conversation_id；当 user_input.satellite_id 非 None 且有正常回复时，构造 continue_conversation=True 的 ConversationResult，使 HA 下一轮沿用 AstrBot agent。无 satellite_id 时原样返回 HA ChatLog 派生的 continue_conversation，不改普通文字会话原生问句续聊行为。测试 Satellite override 与普通文字原生行为两条分支。
- [ ] fake clock 测试：Pipeline/TTS 活跃期间 timer 不推进；follow-up speech 重置窗口；wake miss 和 command timeout 不串入 AstrBot session TTL。
  
**Exit gate:** 一个 MIC session 跨 2+ Pipeline；顺序消费、队列上限和过期清理正确；VAD event 不会取消活动回复。

## P6.5b8 — ESP32 常驻 I2S RX / AEC / VAD / MIC producer

**Goal:** 设备开机常驻物理采集/AEC/VAD；空闲时 VAD 开启上传；活动 MIC session 中持续上传 AEC PCM，VAD 不拥有 stop 权限。

**Files:** 新建 `audio_capture.c/.h`、`audio_frontend.c/.h`；修改 `main.c`、`CMakeLists.txt`、`diagnostics.c/.h` 和 MIC send seam；测试 `tests/esp32/`。

- [ ] Host tests：INMP441 左 Slot 解码、sign extension、anti-alias/downsample、16 kHz S16LE 输出、pre-roll ring、session start/stop。
- [ ] 配置同一 I2S controller 32 kHz/Stereo/32-bit 全双工；RX/TX DMA 分离，沿用已冻结 GPIO/wiring。
- [ ] 使用 esp-sr 2.6.1 初始化 M/R AFE、经典 ESP32 SR High Performance AEC 和 VAD；vad_mute_playback=false，帧长取 API。
- [ ] 无播放时 R 输入零样本；播放时从音频输出管理器取得最终 TX 参考。
- [ ] RX/AEC/VAD 成功初始化后常驻；VAD 只维护 speech activity 状态并发送 MIC_ACTIVITY，不调用 AUDIO_STOP / AUDIO_INTERRUPTED。
- [ ] IDLE speech_start 打开 MIC session，先发送 AEC pre-roll，再持续发送 AEC PCM（含静音）。
- [ ] MIC_CAPTURE_STOP 仅停止网络上传；I2S RX/AEC/VAD 继续运行。
- [ ] 网络写入、AFE、DMA 不互相阻塞；检查 Wi-Fi/SPP 并发时任务栈和 buffer。
- [ ] 设备日志有 AEC underrun/misalignment、VAD transition、PCM drop 计数。

**Exit gate:** ESP-IDF build/host tests PASS；实机 RX/AEC/VAD 常驻，首次 VAD 开启上传，MIC_CAPTURE_STOP 不停止物理音频运行时。

## P6.5b9 — NAS KWS watcher、确认打断与 PCM handoff

**Goal:** AstrBot/SSE/TTS 活动期间的新唤醒词由 NAS KWS 确认后才取消旧 run，保留随后命令音频。

**Files:** `assist_satellite.py`、`audio_session.py`、`audio_resource.py`；测试 `test_assist_satellite.py`、`test_audio_session.py`、`test_audio_resource.py`。

- [ ] RED tests：side KWS 在主 Pipeline 发出 STT_START 时立即启动，与 STT 消费并行；覆盖 STT 本身、AstrBot 首个 plain 前、plain 后和 TTS 播放；WAKE_WORD 主阶段不得重复建 watcher。follow-up STT turn 也启动 watcher。
- [ ] 使用 HA 公开 `WakeWordDetectionEntity.async_process_audio_stream()` 和当前选定的 Wake Word entity；复用 Sherpa Wyoming Provider。Watcher 从 STT_START 并行消费，不等 STT_END，因而 STT 阶段也能被下一次唤醒词打断。
- [ ] watcher 消费同一有序 AEC ingress，可独立取消；KWS hit、follow-up start、session expiry、HA unload 时关闭。
- [ ] KWS Detection 命中时只创建一个 interrupt generation；activity-only 事件不得触发 cancel。
- [ ] 若旧 playback_id 活动，发送匹配 AUDIO_STOP；随后 cancel/await 旧 public Satellite caller。
- [ ] P3 负责关闭 SSE 并 Stop；Tivoo 不直接调用 AstrBot API。
- [ ] 等 b6 TTS owner 和下游 Wyoming/P7A request 清理完成后才启动新 STT。
- [ ] 把 Wyoming Detection.timestamp 映射到 HA 单调 ingress index，保留 Detection 后音频直至新 STT 接管；不得将 ESP32 uptime_ms 与 HA monotonic 直接比较。handoff 上限 15 秒/480,000 bytes，超限显式失败。
- [ ] 新 Pipeline 从 STT 开始，conversation/session ID 延续 P3；旧 run 迟到事件按 generation 丢弃。
- [ ] 测试连续两次快速 KWS hit、KWS miss、旧 Stop 延迟、旧 AUDIO_STATE 迟到；新 run 不受旧消息影响。

**Exit gate:** AstrBot 尚未回应时和 SSE 输出期间 KWS 可打断；普通 VAD 活动不打断；新命令 PCM 无丢失且从 STT 开始。

## P6.5b10 — ESP32 解码/DAC 全双工与播放终态

**Goal:** 把现有 HTTP 资源 reader 接到真实流式 MP3 decode、32 kHz SRC、I2S TX、PCM5102；共享最终 TX 参考给 AEC。

**Files:** 新建/复用 `audio_output_manager.c/.h`、`audio_playback.c/.h`；修改 `audio_resource.c`、`main.c`、`CMakeLists.txt`；测试 `tests/esp32/`。

- [ ] RED tests：playback_id 状态、HTTP EOF/error/stop、decoder error、PCM queue 清空、旧 AUDIO_STOP 不影响新播放。
- [ ] 用 esp_audio_codec 2.6.2 做实际 MP3 流式解码，不整段缓存；按实际 decoder PCM rate/channel 做 SRC。
- [ ] 统一最终输出到 32 kHz Stereo/32-bit Slot，驱动 PCM5102 AUX；所有受控声音源进入同一 manager。
- [ ] 从最终 TX PCM 同步生成 16 kHz Mono R，处理 RX/TX 延迟；R underrun/misalignment 可诊断。
- [ ] AUDIO_STOP 匹配 expected_audio_id 后停止 HTTP reader/decoder/队列/I2S TX；不停止 RX/AEC/VAD/MIC session。
- [ ] 只有实际 PCM 已播放完毕并清空 TX queue，才发送 AUDIO_STATE completed；TTS tts-end 不能代替播放结束。
- [ ] 对旧播放的 stop、HTTP EOF、AUDIO_STATE 终态按 playback_id 去重；generation 隔离新播放。
- [ ] ESP32 build + host tests；再进行真实 PCM5102/Tivoo AUX 播放及 SPP 并发测试。

**Exit gate:** MP3 流式播放、实际 PCM5102 输出、全双工采集和 AEC R 参考联动；AUDIO_STOP 可在 DAC 端快速停音且麦克风不停止。

## P6.5b11 — 端到端声学验收、计时调校与阶段收尾

**Goal:** 在真实 Tivoo 环境跑通完整唤醒、打断、follow-up 与 session timeout，留下可复现报告。

**Files:** 修复项按 owner 修改；新增 `docs/superpowers/reports/2026-11-13-p6-5b11-end-to-end-acoustic-acceptance.md`；更新 README 和本矩阵状态。

- [ ] 实测首次 WAKE_WORD 最近 speech_end 后 3 秒未命中取消、首次 speech_start 起 15 秒硬上限、KWS hit 后 5 秒 command-start timeout、连续 utterance 不额外等待。
- [ ] 实测 VoiceCommandSegmenter 的 0.3 秒 speech start、1.0 秒最小命令、0.7 秒 end-of-speech 和 15 秒单轮 timeout；与 Sherpa 300 秒请求硬限制区分。
- [ ] 实测 TTS playback active 时普通环境人声/电视声使 VAD activity，但不会停止播放或取消任务。
- [ ] 实测 NAS KWS 对真实用户唤醒词的命中，并在 AstrBot 等待、SSE plain 后、TTS 生成和 DAC 播放四个阶段分别打断。
- [ ] 采集 TTS 自回声、含唤醒词 TTS、不同音量/距离和环境讲话负样本；报告命中/误触发样本，不杜撰准确率阈值。
- [ ] 实测 PCM5102 输出期间 RX/AEC/VAD/MIC upload/KWS 和 SPP 屏幕控制同时工作。
- [ ] 实测 TTS 实际播放结束后 8 秒 follow-up，无输入到期后停止网络上传并回本地监听；下一轮需要 wake word。
- [ ] 记录实际 memory、CPU、Wi-Fi/Spp、DMA underrun、AEC reference lag、PCM drop 与队列高水位。
- [ ] 回归 P3、P6、P7A 与 b6 取消用例；确认取消后无旧 plain、PCM、TTS_PLAY。
- [ ] 更新 README：P6.5 新范围、b6–b11 状态与剩余限制；保持 P7/P8 文档边界一致。
- [ ] 本批完成后由用户决定是否把后续计划 P7/P8 中已被前移的条目标为 superseded，不擅自删除历史合同。

**Exit gate:** P65-A01–A16 有独立证据和 PASS/GAP/BLOCKED 标记；真实声学测试通过才可宣称全双工 KWS 打断已验收。

## 执行顺序与阶段门

`b6 → b7 → b8 → b9 → b10 → b11`。b7 可先用 fake ingress 做 API/state tests，但真实跨轮验收依赖 b8；b9 的端到端取消依赖 b6；b10 的 AEC R 物理验证依赖 b8。b11 汇总所有真实组件联调。

每批先读本矩阵、上位协议/P3/P7A 规格和对应代码；使用 SuperPower brainstorming（若变更范围产生新选择）、TDD、executing-plans/subagent-driven-development 与 verification-before-completion。每批只完成当批，运行相关测试，更新报告，再本地提交。禁止在 b6–b11 中顺带实现与当前批次无关的 P9 功能。
