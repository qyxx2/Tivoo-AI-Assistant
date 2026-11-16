# P6.7 预制语音等待提示音分批实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 首次唤醒、确认打断后的新命令等待、每轮回答后的 follow-up 等待，各播放一次预制短提示音；立即并行收音，提示音不进入实时 TTS/LLM。

**Architecture:** HA `AudioSessionCoordinator` 决定触发，独立 `PromptSoundPlayer` 管理素材选择和 playback_id，复用 7778 `TTS_PLAY` + HA `/local` HTTP 文件 + 现有 ESP32 解码/I²S/AEC 链。正常 TTS 与提示音共用一个物理播放 owner，按 playback_id 隔离状态和定向停止。尽量复用既有模块，不新建音频协议/状态机。

**Tech Stack:** Home Assistant Core 2026.11.0、Python、pytest、ESP-IDF classic ESP32 现有固件、FFmpeg/ffprobe（仅一次性素材制作/检测）、HA 静态文件路径、现有 TVIO v1。

**Spec:** [P6.7 语音等待提示音规格](../specs/2026-11-16-p6-7-ready-prompt-sound-design.md)
**Contract:** [P6.7 合同矩阵 PR-C01–C21](../specs/2026-11-16-p6-7-ready-prompt-sound-contract-matrix.md)
**Baseline:** `feature/p6-7-audio-prompts` 基于已合入 P6.6 的 `main@e48c66a`。本计划仅准备后续实现，不表示已经执行任一批次。

## Global Constraints

- 不改 P6.5 的 KWS/识别引擎、STT、AstrBot、5 秒/8 秒起点、MIC session、打断/取消 owner；提示音不得改变窗口起点或延长 timeout。
- 不增加 ESP32 消息/新 DAC 路径；`TTS_PLAY=0x30` / `AUDIO_STOP=0x31` / `AUDIO_STATE=0x32`、HTTP MP3 资源、真实最终 TX→AEC R 全部沿用。
- 首期四个 32 kHz mono MP3 文件，运行时不合成；asset 缺失/HTTP 错误时只跳过提示音。
- HA 负责 ID、generation、播放端互斥；正常 TTS 优先。`AUDIO_STATE.source` 仍为 `tts_http`，只能按 playback_id 区分提示音。
- MIC RX/AFE/VAD 持续，不在提示音期间关采集/压静音/推迟 STT；AEC 的实际声学效果必须实机验证。
- P6.6 的显示 intent/息屏 gate 不随提示音改变；P3 SSE/ChatLog/TTS owner 不接受提示音事件。
- 优先 Ubuntu 开发机做素材与测试；NAS 仅 b3 必要部署/实机验收；除非证据表明旧固件不能满足合同，否则不刷写 ESP32。
- 每批 RED→GREEN→聚焦回归→检查→独立本地 commit；不未经要求 push、merge 或扩大任务范围。

## Review Focus

1. **确认打断与旧 TTS 竞争**：新提示音不能在旧 TTS 的 AUDIO_STOP/终止前抢占 DAC；b2 模拟延迟 6 秒旧轮清理。
2. **提示音刚起、用户已开始讲话**：STT 必须继续消费 AEC PCM，待发提示音可丢弃，已发提示音只按自己的 ID 停止；b2 复现紧接命令。
3. **提示音终态被误认为回答结束**：既不能再开 8 秒窗口，也不能触发 P6.6 speaking；b1/b2 隔离旧/新 ID 测试。
4. **正式 TTS 与短提示音重叠**：先确认提示音释放，再发送正常 TTS_PLAY，避免设备 audio_busy；b1/b2 双向竞态测试。
5. **提示音回声冒充用户讲话**：软件测试验证无采集屏蔽；b3 用实体麦克风/扬声器在不同音量下检验 VAD/STT 首字和假 follow-up。

---

## 1. 批次与依赖

| 批次 | 可独立验收交付物 | 合同 | 首次部署 |
|---|---|---|---|
| P6.7b0 | 四个预制短音频、可复现素材检查和 HA `/local` 静态路径验证 | C07、C09、C21（素材部分） | 否 |
| P6.7b1 | 提示音播放 owner：固定素材选择、随机不连播、ID 路由、取消、独立 TTS 互斥 | C08、C10–C15、C19 | 否 |
| P6.7b2 | 实际等待入口触发、交接与连续对话完整时序，自动化回归 | C01–C06、C13–C16、C19、C20 | 是（具备端到端功能） |
| P6.7b3 | NAS + ESP32 + Tivoo 真实出声、并行说话/AEC 现场验收与收尾 | C06、C09、C11、C17、C18、C20、C21 | 是（生产验收） |

依赖顺序：`b0 → b1 → b2 → b3`。不额外拆仅有状态清点价值的纯准备批次，不提前实现固件本地 Flash 播放。

## 2. P6.7b0 — 静态素材与资源路径

**Files**
- Create: `homeassistant/prompt_assets/ready_01.mp3` ... `ready_04.mp3`（版本管理的源素材，按需部署复制）
- Create: `tests/homeassistant/custom_components/tivoo/test_prompt_assets.py`
- Create: `docs/superpowers/reports/2026-11-16-p6-7b0-assets-and-static-url.md`（执行时新增）

**Interfaces:** `/config/www/tivoo/prompts/ready_0{1..4}.mp3` → `/local/tivoo/prompts/ready_0{1..4}.mp3`；`audio/mpeg`、mono、32 kHz。不得以 `/api/tts_proxy/` 代替。

- [ ] 读取当前合约和 HA frontend 静态路由源码，记录实际运行配置中是否启用了 frontend、`www` 是否存在；不得把 `/local` 路径当成已部署事实。
- [ ] 制作四个短文件：优先一次性离线生成/自行录制并固化，记录其来源和使用权；统一采样率/声道、电平与 ≤0.9 秒目标。不允许运行时 TTS 或导入未知许可的样例音频。
- [ ] 先写元数据失败测试，针对缺文件、文件格式不符、时长异常；运行看到失败，再补齐素材直至 `ffprobe`/测试通过。
- [ ] 在可运行的 HA HTTP 测试环境验证 `/local` 资源返回 200 + `audio/mpeg`，记录真实 URL 组成和 ESP32 所需无认证访问条件；生产 NAS 连通性由 b3 复核。
- [ ] 运行聚焦测试、`git diff --check`，记录 b0 证据并只提交 b0 文件。

**门禁：** 四个文件均可由相同 MIME 的 HTTP 接口获取；只有文件存在和 FFprobe 正确而尚未完成 HTTP 检查不得宣告 b0 整体通过。

## 3. P6.7b1 — PromptSoundPlayer 与物理出口所有权

**Files**
- Create: `homeassistant/custom_components/tivoo/prompt_audio.py`
- Modify: `homeassistant/custom_components/tivoo/audio_resource.py`（仅正常 TTS 准备发送之前的可选“让出提示音播放槽”回调）
- Test: `tests/homeassistant/custom_components/tivoo/test_prompt_audio.py`，原有 `test_assist_satellite.py` / `test_transport.py` 中相关回归
- Report: `docs/superpowers/reports/2026-11-16-p6-7b1-prompt-player.md`（执行时新增）

**Interfaces:** `PromptSoundPlayer` 在 HA 拥有当前 `generation`/`playback_id`，持有 `Esp32ConnectionAdapter.async_send_tts_play` 与定向 `TYPE_AUDIO_STOP`；向 Satellite 提供 `async_request(generation)`、`async_cancel(generation)`、`async_yield_to_tts()`、`on_playback(playback_id, state) -> bool`（名称如实现有确切必要可调整，但须维持单 owner 语义）。正常 TTS 的 `TtsResourceManager._send_once` 调用传入的 *可选* awaitable 准备回调；原 `/api/tts_proxy/` 验证不变。

- [ ] 先写 RED：无连续重复、四音之一、同入口去重、无素材/URL 失败不冒泡、当前/旧 generation 的状态隔离。
- [ ] 以固定文件名和 HA 内部 URL 实现最小选择/下发逻辑；只给短文件分配自己的 UUID，不注册额外 TVIO message。
- [ ] 先写 RED：提示音 `AUDIO_STATE` 不会进入 `turn.tts`、TTS 准备发送时有活动提示音必须先完成/定向停止并等待释放、旧 TTS 占用时不会播放提示音。
- [ ] 只在必要的 TTS 发出位置接入一次可选协作回调；把输出端互斥集中在提示音 owner，避免分散出多个状态机。
- [ ] 运行聚焦 + 既有 TTS resource/transport 测试；检查 `audio_busy` 不成为正常流程、取消不影响真实 TTS；`git diff --check`、报告、本地 commit。

**门禁：** 可在纯 HA 单元/集成测试独立证明播放 owner 和真实 TTS 互斥，未接语音事件也不得让测试误触发声音。

## 4. P6.7b2 — 三个等待入口与无阻塞收音

**Files**
- Modify: `homeassistant/custom_components/tivoo/assist_satellite.py`
- Modify: `homeassistant/custom_components/tivoo/audio_resource.py`（仅 b1 所需回调接线，如已完成不再修改）
- Test: `tests/homeassistant/custom_components/tivoo/test_assist_satellite.py`、`test_prompt_audio.py`、既有 `tests/homeassistant/test_assist_pipeline_tts_cancellation.py`
- Report: `docs/superpowers/reports/2026-11-16-p6-7b2-waiting-lifecycle.md`（执行时新增）

**Interfaces:** `WAKE_WORD_END` 确认 → 请求提示音；`_open_followup()` → 请求提示音；新 `confirmed` turn 在 `_run_turn` 中 **旧轮清理后**、新 STT 启动时请求提示音。所有请求异步，不将播放完成作为收音/计时前置条件。复用已注入的播放状态监听，优先将对应提示音 ID 路由给 owner，再处理真实 TTS ID。

- [ ] 先写 RED：初次 KWS 命中提示音一次，候选语音/重复事件不播放；5 秒 watchdog 不改变，命令在提示音中间立即被消费。
- [ ] 先写 RED：TTS completed → follow-up 8 秒提示音一次；提示音 completed 不产生额外 follow-up；speech_start 立即开始免 KWS STT；8 秒到期关闭上传。
- [ ] 先写 RED：side KWS interruption 旧播放清理 6 秒，旧 TTS 定向停音之后发提示音；新 STT 接收 handoff PCM，5 秒从新 STT_START 开始；过期 generation 不播。
- [ ] 实现三处最小事件接线与提示音取消；仅取消提示音自身 ID，绝不通过 VAD 停正常 TTS 或推迟 STT；错误只记录并跳过。
- [ ] 运行 P6.5/P6.6 关键回归，包括 `AUDIO_STATE` 迟到、正常回答完成、P6.6 表情门控；`git diff --check`、报告、本地 commit。

**门禁：** 三入口、重复/过期、并发/打断测试通过；不以模拟声学代替 b3 真人测试。

## 5. P6.7b3 — NAS 部署、真实声学与收尾

**Files:** b0 的素材副本部署到 NAS HA `/config/www/tivoo/prompts/`；同步 HA 集成变更；记录 `docs/superpowers/reports/2026-11-16-p6-7b3-device-acceptance.md`；仅在验收结论需要时更新 README/矩阵状态，不额外扩展代码。

- [ ] 在 Ubuntu 运行聚焦测试与 `scripts/test-ha.sh` 的必要回归；确认本地 `git diff --check`。仅部署 P6.7 相关 HA 文件与四个素材，不默认改 ESP32 固件。
- [ ] 从 ESP32 可达的 HA 内网地址 GET 四个 MP3，检查 HTTP 200、`audio/mpeg`、真实播放 ID、音频解码、DAC 出声与 `completed`；记录首声延迟、设备 `audio_busy`、断连时静默降级。
- [ ] 真人验证首次“大肥鱼”命中、唤醒词后立即连说命令、正常回答结束 8 秒 follow-up、对话中再次 KWS 打断并接命令；每轮提示音只播一次，提示音和实际 TTS 不重叠。
- [ ] 在“嘟”“我在”“在的”“你说”期间直接讲话，检查首字、STT 输出与回声自触发；覆盖不同音量、距离与提示音连续轮次，比较 RX overruns、reference underrun/misalignment、AFE/VAD、MIC 上传和 stop/playing/completed 日志。
- [ ] 对照 PR-C01–C21 逐项给出 PASS/GAP/FAIL，明确标出 P65-A13 仍缺或已有的现场证据。只有声学闭环真正通过才可写 P6.7 全部完成。
- [ ] 验证部署文件和开发分支相符、工作区干净；按需本地提交验收报告。除非用户另行要求，不 push、merge main。

## 6. 执行约定

每批开始重新检查 `git status -sb`、`HEAD`、本规格与矩阵，并按 Superpowers 的 RED→GREEN→verification-before-completion 执行；每批只交付当前批。若实际 HA HTTP 路由、ESP32 busy/stop 行为或声学结果否定本计划的事实前提，先记录测得的证据和必要的合同修订，不用新增第二条音频通道、盲目扩大重试/超时逻辑或静音麦克风规避。
