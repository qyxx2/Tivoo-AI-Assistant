# P6.6 Tivoo 表情状态机与屏幕门控分批实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变 P6.5 音频/KWS/STT/TTS/打断合同和既有 Tivoo SPP 协议的前提下，让 HA 成为 Tivoo 16×16 屏幕的自动表情所有者，完成 idle/listening/thinking/tooluse/speaking/mood 的统一仲裁、可靠恢复和多来源息屏门控。

**Architecture:** 新增 `display_state.py`，其中 `ExpressionCoordinator` 维护 display intents、generation、TTL、idle 与 last-sent，`ScreenPowerGate` 维护 owner inhibit/temporary wake。P6.5 Satellite 只把真实生命周期翻译成 intent；AstrBot 只额外暴露内部 tool phase；现有 HA Service/MCP 与 SPP encoder/ESP32 transport 继续复用，不新增设备协议。

**Tech Stack:** Home Assistant Core 2026.11.0 / Python 3.14 test environment；现有 Tivoo custom integration、AstrBot Conversation integration、TCP 7777/7778、Classic SPP；pytest / Ruff；无新增运行时依赖。

**Spec:** [Tivoo 表情状态机与屏幕门控规格](../specs/2026-11-14-tivoo-expression-state-machine-design.md)
**Contract:** [Tivoo 表情状态机合同矩阵](../specs/2026-11-14-tivoo-expression-state-machine-contract-matrix.md)
**Status (2026-11-16):** P6.6b0–b5 已执行；b5 自动化/部署/idle/screen gate 通过，真人语音链与 ESP32 单独 reset 后 7777 自动恢复记 GAP。详见 [P6.6b5 验收报告](../reports/2026-11-14-p6-6-expression-state-machine-acceptance.md)。

## Global Constraints

- P6.5 继续拥有 MIC session、KWS、STT、TTS、AUDIO_STATE、8 秒 follow-up、打断与 generation 音频语义；P6.6 只消费这些事件。
- P3 继续拥有 AstrBot session/SSE/Stop/ChatLog；`tool_call/tool_call_result` 的新增观察不得进入用户回答或 TTS。
- 不新增 ESP32 TVIO 消息、SPP raw packet、固件功能或“当前真实像素”查询。
- speaking 只由当前 playback id 的真实 `AUDIO_STATE=playing` 驱动，不能使用 `TTS_START/TTS_END` 代替。
- `STT_END` 且当前 command 已开始、识别结果非空时才进入 thinking；`STT_START` 不进入 thinking。
- 显示优先级固定：`wake_confirmed > speaking > tooluse > thinking > active_listening > explicit_content > ai_mood > followup_wait > idle`。
- idle 池固定为 `standby/smiley/sleepy/sun/fish`；轮换 30–90 秒。
- 首次候选 listening：持续约 700 ms、35% 概率、10 秒冷却；KWS confirmed 不受概率/冷却限制。
- AI mood 白名单固定为 `happy/sad/angry/love/cool/cry/laugh/sleepy/shock/wink/sick/party/kiss/oops`，TTL 5 秒。
- 现有 `tivoo.set_screen_power(value: bool)` / `tivoo__SetScreenPower` 签名保持；旧 bool 只对应固定 compatibility owner，不新增未经规格定义的公开 owner 参数。
- current display 由 HA `desired/last_sent` 表示；不得把 transport 写成功称为物理像素确认。
- 开发/代码级测试仍在当前 Ubuntu 工作区完成；NAS 只在 P6.6b5 做生产部署和实机验收；P6.6 不需要 ESP32 build/flash。
- 每批只实现本批内容、先 RED 后 GREEN、完成聚焦回归与 `git diff --check` 后单独本地提交；未执行的真机项明确标记 GAP/DEFERRED。

## Review Focus

1. **旧 generation 迟到事件**：旧 `AUDIO_STATE`、AstrBot phase、TTL callback 到达时不能覆盖新 turn；P6.6b0/b2/b3 必须分别有 stale-generation 测试。
2. **屏幕 OFF 时的写入**：idle、系统状态、mood、可恢复显式内容不能把屏幕重新点亮；P6.6b0/b1 覆盖多 owner、OFF 期间 desired 更新和 ON 恢复。
3. **transport/SPP 重连**：断线不能丢 desired；`spp_connected` 后 OFF 重申 OFF、ON 强制重发赢家；P6.6b1 覆盖。
4. **AstrBot 内部事件泄漏**：tool phase 不得变成 ChatLog 文本、TTS 输入或普通文字会话的 Tivoo 状态；P6.6b3 覆盖。
5. **被高优先级压住的 mood/TTL**：mood 在 speaking/tooluse 期间照常过期，过期后不能补播；P6.6b4 覆盖。

---

## 1. 批次与依赖

| Batch | 内容 | 依赖 | 首次可部署 |
|---|---|---|---|
| P6.6b0 | 纯显示仲裁核心：intent、priority、generation、TTL、idle、ScreenPowerGate | 规格/矩阵 | 否 |
| P6.6b1 | HA 运行时接线：屏幕所有权、显式内容、息屏兼容、SPP 重连 | b0 | 是，屏幕基础层 |
| P6.6b2 | P6.5 语音生命周期 → listening/thinking/speaking/follow-up | b1 | 是 |
| P6.6b3 | AstrBot tool phase → tooluse，使用 HA Context 精确关联 turn | b2 | 是 |
| P6.6b4 | AI mood Service/MCP、5 秒 TTL、工具语义 | b3 | 是 |
| P6.6b5 | 全量回归、NAS/ESP32/Tivoo 实机验收和 P6.6 收尾 | b4 | 最终 |

依赖顺序固定为：

```text
P6.6b0 → P6.6b1 → P6.6b2 → P6.6b3 → P6.6b4 → P6.6b5
```

b0 只建立可测试核心，不接生产 runtime，避免出现“idle 已启动但现有屏幕开关/显式显示还没纳入仲裁”的中间状态。b1 一次接齐 screen ownership 后才启用 idle。

### 合同覆盖索引

- b0：ESM-C01、C02、C09、C10、C15、C17、C18、C19、C20 的核心状态语义。
- b1：ESM-C14、C15、C16、C17、C19、C20 的生产接线与恢复。
- b2：ESM-C03、C04、C05、C07、C08、C10、C21、C23。
- b3：ESM-C06、C10、C23。
- b4：ESM-C11、C12、C13。
- b5：逐项复核 ESM-C01–C23；C22 只验证 Coordinator 可复用边界，主动 announce/start-conversation 仍按合同保持预留，不在 P6.6 实现。

---

## 2. P6.6b0 — ExpressionCoordinator / ScreenPowerGate 核心

**Purpose:** 用纯 HA/Python 状态逻辑完成优先级、恢复、generation、TTL、idle 和屏幕 gate；不修改 Assist、AstrBot、service 注册或 transport。

**Files:**
- Create: `homeassistant/custom_components/tivoo/display_state.py`
- Create: `tests/homeassistant/custom_components/tivoo/test_display_state.py`
- Create: `docs/superpowers/reports/2026-11-14-p6-6b0-display-state-core.md`

**Interfaces:**
- Produce `DisplayState`：`WAKE_CONFIRMED, SPEAKING, TOOLUSE, THINKING, ACTIVE_LISTENING, EXPLICIT_CONTENT, AI_MOOD, FOLLOWUP_WAIT, IDLE`。
- Produce `build_expression_command(name: str) -> TivooCommand`，复用当前 `PRESET_REGISTRY` 生成现有 `set_expression` command 数据。
- Produce `ScreenPowerGate.async_acquire(owner: str)`、`async_release(owner: str)`、`async_temporary_wake(owner: str, ttl: float)`、`async_shutdown()`。
- Produce `ExpressionCoordinator.async_start()`、`async_shutdown()`、`begin_generation(generation: str)`、`async_end_generation(generation: str)`。
- Produce read-only `ExpressionCoordinator.active_generation: str | None`，后续 AstrBot phase 和 mood 只用这一处判断当前语音代次，不各自维护第二份 generation。
- Produce `ExpressionCoordinator.async_set_intent(state, command, *, generation=None, ttl=None)`、`async_clear_intent(state, *, generation=None)`、`async_force_recompute()`。
- Screen gate 只通过 Coordinator facade 对外：`async_acquire_screen_off(owner: str)`、`async_release_screen_off(owner: str)`、`async_temporary_wake(owner: str, ttl: float)`；service/Assist 不直接修改 gate 内部集合。
- `last_sent` 只在底层 `async_execute()` 成功后更新；send failure 保留 desired，等待后续重连/recompute。

**RED / GREEN tasks:**
- [ ] RED：固定优先级逐层覆盖，清除赢家后恢复仍有效的下一 intent；不得写 A→B 成对回退。
- [ ] RED：`begin_generation(new)` 后旧 generation 的 clear/set/TTL callback 均不能改变当前赢家；`async_end_generation` 只清会话级 intent，不清 persistent explicit/idle。
- [ ] RED：mood/任意 TTL intent 在被更高状态覆盖时仍按真实时间过期，过期后不得“补播”。
- [ ] RED：idle 无其他 intent 时立即成为兜底，并按 30–90 秒重新选 `standby/smiley/sleepy/sun/fish`；测试用 monkeypatch 固定随机结果，不引入额外随机框架。
- [ ] RED：两个 screen-off owner 中任意一个未释放都保持 OFF；重复 acquire/release 幂等。
- [ ] RED：temporary wake 不删除 inhibit；多个 temporary wake 中一个到期不能提前熄灭另一个；全部结束且 inhibit 仍存在时回 OFF。
- [ ] RED：OFF 时 intent 可以更新 desired，但不发送显示 command；OFF→ON 后先恢复屏幕，再强制下发当前赢家。
- [ ] RED：adapter 写失败不伪造 `last_sent`，下一次 `async_force_recompute()` 能重试同一 desired。
- [ ] GREEN：实现最小 `display_state.py`；timer 使用 HA event-loop/现有 helper，不增加 dependency、不做轮询。
- [ ] 运行：`./scripts/test-ha.sh -q tests/homeassistant/custom_components/tivoo/test_display_state.py`。
- [ ] 运行 Ruff/format check、`python -m compileall homeassistant/custom_components/tivoo/display_state.py`、`git diff --check`。
- [ ] 更新 b0 报告，只记录真实 RED/GREEN 命令、结果和未接线边界。

**Exit gate:** ESM-C01/C02/C09/C10/C15/C17/C18/C19/C20 的纯状态部分有自动化证据；生产 HA 行为尚未改变。

**Commit:** `feat(p6.6b0): add Tivoo display state core`

---

## 3. P6.6b1 — 屏幕所有权、显式内容、息屏与 SPP 重连

**Purpose:** 把 b0 核心接入 Tivoo runtime，并在启用 idle 前一次性解决现有显式显示、screen power 与 SPP reconnect，避免自动 idle 覆盖用户画面或息屏。

**Files:**
- Modify: `homeassistant/custom_components/tivoo/__init__.py`
- Modify: `homeassistant/custom_components/tivoo/services.py`
- Modify: `homeassistant/custom_components/tivoo/transport.py`
- Modify: `tests/homeassistant/custom_components/tivoo/test_services.py`
- Modify: `tests/homeassistant/custom_components/tivoo/test_transport.py`
- Modify: `tests/homeassistant/custom_components/tivoo/test_display_state.py`
- Create: `docs/superpowers/reports/2026-11-14-p6-6b1-screen-ownership.md`

**Interfaces:**
- Runtime 新增唯一 `runtime["display_coordinator"]`；底层仍保留真实 `runtime["connection_adapter"]`。
- b1 在 `ExpressionCoordinator` 增加 facade：`async_set_screen_power(value: bool)`、`async_set_explicit(command: TivooCommand)`、`async_execute_screen_action(command: TivooCommand)`、`async_on_spp_state(state: str)`；所有 service/transport 接线只调用这些 facade。
- `tivoo.set_screen_power(False)` → acquire 固定 compatibility owner；`True` → release。若还有其他 inhibit，True 不得点亮；若无其他 inhibit，必须发送现有 screen-on command 并 recompute。
- Transport 新增单一 SPP 状态观察入口 `register_spp_state_handler(handler)`；连接变化使用已验证的 `DEVICE_EVENT spp_connected/spp_disconnected`；HA/诊断通道重载时还使用已验证的初始 `DEVICE_STATUS.spp.state` 快照同步，7777 重建后可据此恢复；绝不把 `0x69/0x96` hint 当成物理连接确认。
- `spp_disconnected` 清除 `last_sent` 的可信发送缓存；`spp_connected` 时 OFF 重发 OFF，ON 强制重发 winner。
- 可恢复显式内容固定为当前可安全重放的显示命令：`set_expression`、`show_text`、`show_image`、`play_animation`、`show_clock`、`set_light`、`show_lyrics`、`show_scoreboard`、`show_design`、`show_effects`、`show_visualization`、`show_game`。
- `start/stop_countdown`、`set_timer`、`set_noise_meter`、`set_sleep_mode`、`game_control` 属于有设备运行副作用/时间状态的屏幕动作：gate ON 时维持原有直接执行；gate OFF 时明确拒绝，不缓存、不延迟执行，避免亮屏或恢复时重放旧副作用。
- `set_datetime/set_weather/set_alarm/set_memorial/set_audio_source/set_playstate/set_volume/set_brightness` 保持既有服务路径；没有已核实证据表明它们应被 P6.6 作为可恢复画面重放，因此不擅自改语义。

**RED / GREEN tasks:**
- [ ] RED：integration setup 创建一个 coordinator，unload 会 shutdown timer/gate；没有 host 时仍可正常 unload。
- [ ] RED：启用 b1 后 idle 才开始；显式 `SetExpression/ShowText/ShowImage/PlayAnimation` 会取代 idle，后续系统 intent 清除后恢复该显式内容。
- [ ] RED：上述 12 个 replayable display service 在 OFF 时只更新 desired、不写 7777；重新 ON 后发送 screen-on + 最新 explicit winner。
- [ ] RED：countdown/timer/noise/sleep/game-control 在 OFF 时返回明确 `HomeAssistantError`，不得假装成功、不得排队到未来执行。
- [ ] RED：两个内部 owner + compatibility bool 的组合不会被一次 `value=True` 误解锁。
- [ ] RED：`spp_disconnected → spp_connected` 时，ON 强制重发 winner；OFF 只重申 off，不发送 idle/expression。
- [ ] RED：SPP raw hint `0x69/0x96` 不触发屏幕恢复；只有 validated DEVICE_EVENT 触发。
- [ ] GREEN：服务层只做“command 构造 + 提交 coordinator / 原路径分发”，不把 SPP payload 或状态机复制进 `services.py`。
- [ ] GREEN：`__init__.py` 在 adapter/runtime 建好后创建 coordinator，负责 start/shutdown；不修改 ESP32 消息协议。
- [ ] 运行聚焦测试：`test_display_state.py test_services.py test_transport.py`。
- [ ] 运行现有 Tivoo service/MCP/protocol 回归，确认 27 个既有 Tool/Service 在 b4 前数量不变。
- [ ] Ruff/compileall/`git diff --check`，更新 b1 报告。

**Exit gate:** idle、explicit content、screen-off 和 SPP reconnect 已形成安全基础层；尚未接语音状态，也未新增 AI mood Tool。

**Commit:** `feat(p6.6b1): wire Tivoo screen ownership and power gate`

---

## 4. P6.6b2 — P6.5 语音生命周期 → 表情状态

**Purpose:** 只把已经存在并验证过的 P6.5 生命周期映射到 display intents；不改变任何音频计时器、KWS 判定或取消 owner。

**Files:**
- Modify: `homeassistant/custom_components/tivoo/display_state.py`
- Modify: `homeassistant/custom_components/tivoo/assist_satellite.py`
- Modify: `homeassistant/custom_components/tivoo/assist_satellite.py` 的现有 `_Turn` / `AudioSessionCoordinator` 接口
- Modify: `tests/homeassistant/custom_components/tivoo/test_assist_satellite.py`
- Modify: `tests/homeassistant/custom_components/tivoo/test_display_state.py`
- Create: `docs/superpowers/reports/2026-11-14-p6-6b2-voice-display-lifecycle.md`

**Interfaces:**
- `assist_satellite.async_setup_entry()` 从现有 runtime 读取同一个 `display_coordinator` 并传入 `TivooAssistSatellite(..., display)`；`AudioSessionCoordinator` 只引用这一实例，不新建第二个 display state owner。
- `_Turn` 新增一个 HA `Context`；其 `context.id` 是 P6.6 display generation。
- `_start_turn(...)` 创建新 `Context()`，将它传给真实 `AssistSatelliteEntity.async_accept_pipeline_from_satellite(..., context=turn.context)`。该参数已在当前 HA Core 2026.11.0 源码中确认存在。
- `ExpressionCoordinator.begin_generation(turn.context.id)` 在新 turn 成为 owner 时同步执行；旧 turn 的 display intents 立即失效，但 P6.5 的异步音频 cleanup 保持原逻辑。
- candidate listening 策略由 display 层 timer 实现：首次 wake candidate 的 `speech_start` 持续约 700 ms 后仍 active 才抽 35%；显示成功后 10 秒 cooldown；`speech_end` 取消待触发并清 active-listening。
- follow-up `speech_start` 直接进入 `active_listening`，不走 35% 概率。
- 首轮有效 `WAKE_WORD_END.wake_word_output` 以及 side-KWS hit 后创建的新 generation 均 100% 设置 `wake_confirmed/question`。
- `STT_END` 必须同时满足当前 turn、`command_started=True`、`stt_output.text` 非空才清 listening/wake 并设置 `thinking`。当前 HA 2026.11.0 的 `STT_END` 已核实包含 `{"stt_output":{"text": ...}}`。
- 当前 playback id 的 `AUDIO_STATE=playing` 设置 `speaking/music`；同 id terminal state 清 speaking；`completed` 再设置 `followup_wait/standby`。
- session end/error/follow-up timeout 走 `async_end_generation`，回 explicit/idle；旧 playback id 仍按 P6.5 规则忽略。

**RED / GREEN tasks:**
- [ ] RED：首次短噪声 <700 ms 不显示 listening；700 ms 后 random miss 不显示；random hit 显示；10 秒 cooldown 内不重复。
- [ ] RED：KWS confirmed 无论 candidate 是否显示都 100% `question`；播放中的 side-KWS 新 generation 立即覆盖旧 speaking。
- [ ] RED：`STT_START` 不显示 thinking；空/失败 STT_END 不显示 thinking；有效 STT_END 才显示。
- [ ] RED：TTS_START/TTS_END 单独出现不能显示 speaking；真实 `AUDIO_STATE=playing` 才可以。
- [ ] RED：completed → followup_wait；8 秒内 speech_start → 新 generation active-listening；follow-up timeout/session end → explicit/idle。
- [ ] RED：旧 generation 的 delayed AUDIO_STATE/TTL/speech callback 不能影响新 turn。
- [ ] RED：把显式 `Context` 传给 HA Pipeline 后，现有 P6.5 cancel/Stop/followup 测试行为不变。
- [ ] GREEN：最小修改现有 `AudioSessionCoordinator`；不新增第二个音频状态机，不改 3/15/5/8 秒定时语义。
- [ ] 运行 `test_assist_satellite.py` + `test_display_state.py`，再运行 P6.5 cancellation 聚焦回归。
- [ ] Ruff/compileall/`git diff --check`，更新 b2 报告。

**Exit gate:** ESM-C03/C04/C05/C07/C08/C10/C21/C23 的语音侧已有自动化；AstrBot tooluse 尚未接入。

**Commit:** `feat(p6.6b2): map Assist lifecycle to Tivoo expressions`

---

## 5. P6.6b3 — AstrBot tool_call/tool_call_result → tooluse

**Purpose:** 在不改变 P3 可见 SSE 合同的前提下，把 AstrBot 已存在但当前丢弃的 tool phase 变成 HA 内部生命周期信号，并使用 `satellite_id + Context.id` 精确关联当前 Tivoo turn。

**Files:**
- Modify: `homeassistant/custom_components/astrbot/sse.py`
- Modify: `homeassistant/custom_components/astrbot/conversation.py`
- Modify: `homeassistant/custom_components/astrbot/const.py`
- Modify: `homeassistant/custom_components/tivoo/assist_satellite.py`
- Modify: `tests/homeassistant/custom_components/astrbot/test_sse.py`
- Modify: `tests/homeassistant/custom_components/astrbot/test_conversation.py`
- Modify: `tests/homeassistant/custom_components/tivoo/test_assist_satellite.py`
- Create: `docs/superpowers/reports/2026-11-14-p6-6b3-astrbot-tool-phase.md`

**Interfaces:**
- Extend `AstrBotSseEvent.type` with内部 `"phase"`；`data` 只允许 `"tool_call"` / `"tool_call_result"`。
- `reasoning`、`agent_stats` 继续完全忽略；`tool_call/tool_call_result` 不成为 `plain`、不加入 ChatLog、不交 TTS。
- AstrBot Conversation 仅当 `user_input.satellite_id is not None` 时 fire HA event `astrbot_phase`，payload 固定为 `satellite_id`、`context_id=user_input.context.id`、`phase`。
- Tivoo Satellite 在 `async_added_to_hass` 订阅，在 remove 时解除；只接受 `satellite_id == self.entity_id` 且 `context_id == current turn.context.id` 的事件。
- `tool_call` 设置 `TOOLUSE/tooluse`；`tool_call_result` 只清 TOOLUSE，让仍存在的 THINKING 自动恢复。

**RED / GREEN tasks:**
- [ ] RED：SSE parser 对 tool_call/tool_call_result 产生内部 phase，但最终可见文本与原 P3 测试完全一致。
- [ ] RED：普通 web/text Conversation（`satellite_id=None`）不 fire Tivoo phase event。
- [ ] RED：Satellite 请求 event 包含真实 `ConversationInput.context.id`，不是 AstrBot session_id/run_id/message_id。
- [ ] RED：错误 satellite_id、旧 context_id、session 已结束后的迟到 phase 都不能改 Tivoo screen。
- [ ] RED：tool_call 覆盖 thinking；tool_call_result 后恢复 thinking；随后 speaking 继续按优先级覆盖。
- [ ] RED：取消/异常 SSE 仍走原 P3 Stop owner，phase bridge 不调用 AstrBot API、不改变 stop 次数。
- [ ] GREEN：只增加内部 phase side-channel；不得把 tool JSON/data 内容转发给 Tivoo，状态机只关心 phase 名。
- [ ] 运行 P3 `test_sse.py test_conversation.py`、Tivoo assist/display 聚焦测试和 P3 cancellation 回归。
- [ ] Ruff/compileall/`git diff --check`，更新 b3 报告。

**Exit gate:** ESM-C06 与 stale phase 隔离通过；P3 用户可见回答/TTS/Stop 语义无变化。

**Commit:** `feat(p6.6b3): bridge AstrBot tool phase to Tivoo display`

---

## 6. P6.6b4 — AI mood Service / MCP Tool

**Purpose:** 提供一个受约束的低优先级 AI 心情入口，不允许 Persona 继续拿 `SetExpression` 冒充 listening/thinking/speaking。

**Files:**
- Modify: `homeassistant/custom_components/tivoo/const.py`
- Modify: `homeassistant/custom_components/tivoo/display_state.py`
- Modify: `homeassistant/custom_components/tivoo/services.py`
- Modify: `homeassistant/custom_components/tivoo/services.yaml`
- Modify: `homeassistant/custom_components/tivoo/llm.py`
- Modify: `tests/homeassistant/custom_components/tivoo/test_services.py`
- Modify: `tests/homeassistant/custom_components/tivoo/test_tivoo_p4b4_llm.py`
- Modify: `tests/homeassistant/custom_components/tivoo/test_tivoo_p4b5_mcp_http.py`
- Modify: `tests/homeassistant/custom_components/tivoo/test_display_state.py`
- Create: `docs/superpowers/reports/2026-11-14-p6-6b4-ai-mood.md`

**Interfaces:**
- 新项目 Service：`tivoo.set_mood(name)`；这是 P6.6 项目接口，不宣称为 Tivoo 上游协议。
- 新 MCP Tool：`tivoo__SetMood`，只委派 `tivoo.set_mood`。
- Mood 白名单固定使用规格中的 14 个当前 preset；拒绝 `thinking/tooluse/question/standby/music` 等系统状态。
- `ExpressionCoordinator.async_set_mood(name)` 只能绑定当前 active generation；没有活动 Tivoo voice generation 时明确失败，不把 mood 变成持久 idle 表情。
- TTL 固定 5 秒；被 speaking/tooluse 等覆盖时不暂停计时。
- `tivoo__SetMood` description 明确：仅用于“有明显非语言情绪价值”的 active Tivoo voice reply；neutral response 不要求调用；不得用于 listening/thinking/tool/speaking。
- 更新 `tivoo__SetExpression` description：只用于用户明确要求显示某 preset，不用于助手内部处理状态。
- 不在仓库里伪造/替换 AstrBot Persona 全文；若生产 Persona 使用显式 Tool allowlist，b5 只补授权 `SetMood`，其余 Persona 配置保持原样。

**RED / GREEN tasks:**
- [ ] RED：14 个 mood 全接受；系统状态 preset 和未知 name 拒绝。
- [ ] RED：无 active generation 时 Service/MCP 返回明确错误；active generation 时提交 5 秒 mood intent。
- [ ] RED：mood 低于 active-listening/thinking/tooluse/speaking，高于 followup_wait/idle。
- [ ] RED：mood 在 speaking 覆盖期间过期后，speaking 结束不得短暂补播旧 mood。
- [ ] RED：MCP tools/list 从当前 27 个增加到 28 个且只有新增 `SetMood`；现有 27 个工具 schema/名称保持。
- [ ] RED：MCP SetMood → HA Service → coordinator，不直接调用 raw adapter；SetExpression 仍走 explicit content。
- [ ] GREEN：实现最小 service/tool，保持现有 P4 Tool delegation 结构。
- [ ] 运行 LLM/MCP/service/display 聚焦测试，再运行全 Tivoo custom-component 测试。
- [ ] Ruff/compileall/`git diff --check`，更新 b4 报告。

**Exit gate:** ESM-C11/C12/C13 完成；AI mood 生命周期由 HA 强制，不依赖 prompt 自律。

**Commit:** `feat(p6.6b4): add session-scoped Tivoo mood tool`

---

## 7. P6.6b5 — 全量验收、生产部署与收尾

**Purpose:** 证明 P6.6 在真实 HA → ESP32 → Tivoo 屏幕链路中工作，并确认没有破坏 P6.5 音频、P3 AstrBot、P4/MCP 或现有 7777/7778 通信。

**Files:**
- Create: `docs/superpowers/reports/2026-11-14-p6-6-expression-state-machine-acceptance.md`
- Modify: P6.6 spec/contract/plan 的状态与验收链接
- Modify only if evidence requires: 项目阶段总览文档；不得为了“收尾”顺带增加主动播报/announce 功能

**Local verification:**
- [ ] 运行 `./scripts/test-ha.sh -q tests/homeassistant/custom_components/tivoo tests/homeassistant/custom_components/astrbot`。
- [ ] 运行 P6.5 cancellation/Assist Pipeline 聚焦回归，确认 3/15/5/8 秒、KWS-only interruption 和真实 playback id 隔离不变。
- [ ] Ruff check/format、compileall、pip check、`git diff --check`。
- [ ] 合同逐项对照 ESM-C01–C23；预留的主动播报公开入口仍标 DEFERRED，不伪装成 PASS。

**NAS / real-device acceptance:**
- [ ] 部署当前 HA Tivoo/AstrBot custom-component 代码并重启/重载 HA；不刷 ESP32 固件。
- [ ] 确认 7777/7778 恢复 ESTABLISHED，AstrBot MCP tools/list 为 28 个 Tivoo tools；若当前 Persona 有 Tool allowlist，只新增授权 `tivoo__SetMood`。
- [ ] 空闲观察至少两次 idle 切换；确认只在无高优先级 intent 时变化。
- [ ] 真人完成一次：候选人声 → KWS confirmed → command/STT → thinking → TTS real `AUDIO_STATE=playing` → speaking → completed → followup_wait → session timeout → idle。candidate listening 的概率行为只记录观察，不用单次未出现判失败。
- [ ] 让 AstrBot 执行一个不会改变 Tivoo 屏幕内容的真实工具调用（优先选择已验证且低风险的 volume/read-context 类调用），确认 tooluse 临时覆盖 thinking，tool result 后恢复 thinking。
- [ ] 在 TTS 正在实际播放时说唤醒词，确认 `wake_confirmed` 立即覆盖 speaking，并且原 P6.5 音频打断/新命令仍正常。
- [ ] 在 active voice generation 的 follow-up 窗口内，通过 HA Service 或 MCP 调用 `SetMood(happy)`：显示 5 秒 mood，随后回 followup/idle；再验证 neutral reply 不要求强制 mood。
- [ ] 用两个内部 owner 的自动化测试/服务测试证明多 owner；生产上至少执行 compatibility `SetScreenPower off` 后触发 idle/语音/mood，确认均不能重新点亮，再 `on` 后恢复当前 winner。
- [ ] 使用 NAS 已有 esptool/串口条件做一次**仅 reset、不刷写**的 ESP32 重启以产生真实 SPP reconnect：gate ON 时恢复 winner；另一次若成本可接受，在 gate OFF 状态重启确认仍保持 OFF。若硬件重启无法安全自动化，自动化 DEVICE_EVENT reconnect 测试必须 PASS，并把该真机子项记 GAP 而不是伪称通过。
- [ ] 检查 HA/AstrBot/ESP32 日志无新增未处理异常、SPP reconnect loop 或重复 display storm；不依据 reverse bytes 宣称物理像素 ACK。

**Exit gate:**
- [ ] ESM-C01–C23 中所有非预留合同都有自动化证据。
- [ ] 真实 Tivoo 至少通过 idle、KWS、thinking、tooluse、speaking、followup、screen-off、screen-on 恢复链路。
- [ ] P6.5 音频链、P3 SSE/Stop、27 个旧 MCP Tool 全部回归；新增 SetMood 为第 28 个。
- [ ] 未新增 ESP32 firmware/protocol，也未实现主动 announce/start-conversation。
- [ ] 验收报告记录真实 PASS/GAP，随后单独本地提交。

**Commit:** `test(p6.6b5): verify Tivoo expression state machine`

---

## 8. 执行约定

每个 Batch 开始时重新读取本计划、规格、合同矩阵和当前代码；先确认 branch/HEAD/working tree。实施 P6.6 时从包含本规格、合同矩阵和本计划的提交创建 `feature/p6-6-tivoo-expression-state-machine`，不要在未提交的 P6.5 文档工作区上直接混入生产代码。

每批按顺序执行：RED 测试 → 最小 GREEN → 聚焦回归 → 静态检查 → 更新当批报告 → verification-before-completion → 只 stage 本批文件 → 本地 commit。除非用户另行要求，不 push、不 merge main。

如果实现时发现真实 HA 2026.11.0 API、AstrBot 4.29.4 SSE 或现有 Tivoo 上游证据与本计划接口冲突，先停止当前批、用实际源码/测试证据更新规格/合同/计划；禁止通过新增第二套状态机、猜测 SPP 状态或降低验收标准绕开。
