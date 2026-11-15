# Tivoo 表情状态机与屏幕门控规格

> 日期：2026-11-14
> 分支：`feature/p6-5-ha-cancellation-preflight`
> 状态：设计规格；本次只定义行为与边界，不实现生产代码
> 合同矩阵：[Tivoo 表情状态机合同矩阵](2026-11-14-tivoo-expression-state-machine-contract-matrix.md)
> 分批计划：[P6.6 表情状态机与屏幕门控分批实施计划](../plans/2026-11-14-p6-6-tivoo-expression-state-machine-batch-execution-plan.md)

## 1. 目标与边界

本规格为 Tivoo 16×16 屏幕定义一套由 Home Assistant 持有的自动表情状态机。它解决三个问题：

1. Tivoo 收到图片/GIF 后会持续显示，不能依赖设备自行“播完恢复”；HA 必须在业务状态变化时主动覆盖为下一状态。
2. 语音会话的 listening / thinking / tooluse / speaking / idle 与 AI 心情表情需要统一仲裁，避免互相覆盖。
3. 息屏必须高于所有自动画面；夜间自动化、AI 或脚本要求息屏时，idle 和会话状态不得把屏幕重新点亮。

本规格不改变 P6.5 的音频、KWS、STT、AstrBot、TTS、AEC 或打断合同，不增加 ESP32 协议消息，不实现 Tivoo 当前物理像素读取，也不在本批次实现主动播报。

### 1.1 方案选择

- **采用：HA intent 仲裁 + 独立 ScreenPowerGate。** 每个真实生命周期只提交/移除 intent，由 Coordinator 统一选赢家，能自然恢复被临时覆盖的 thinking、显式内容或 idle。
- **不采用：为每个状态硬编码 A→B 回退。** tooluse、speaking、KWS 打断、mood 和异常路径组合后会产生大量成对分支，容易恢复到已经失效的旧状态。
- **不采用：轮询 Tivoo 当前画面后决定恢复。** 当前上游、DEVICE_STATUS 和已验证 reverse SPP 都没有“当前 preset/真实像素”权威接口，不能把有限状态回显扩写成读屏能力。

## 2. 已核对的现状与上游事实

### 2.1 当前项目能力

- `tivoo.set_expression` 已从 `PRESET_REGISTRY` 生成帧并经现有 `command_adapter` 下发。
- 当前可直接复用的状态表情包括 `standby`、`question`、`thinking`、`tooluse`、`music`，idle 候选可用 `standby/smiley/sleepy/sun/fish`。
- `tivoo.set_screen_power(value: bool)` 与 MCP `tivoo__SetScreenPower` 已存在；本项目 `screen_power_payload()` 和 `tests/homeassistant/custom_components/tivoo/test_protocol.py` 已锁定 on/off golden payload。
- P6.5 当前真实事件源包括 `MIC_ACTIVITY speech_start/speech_end`、`WAKE_WORD_END`、`STT_START`、`STT_VAD_START`、`STT_END`、session end，以及 ESP32 `AUDIO_STATE`。
- `AUDIO_STATE=playing` 来自实际 ESP32 播放开始；`completed/stopped/interrupted/failed` 是设备播放终态，因此 speaking 必须以它为准，不能以 HA `TTS_START/TTS_END` 代替。
- AstrBot SSE 已识别 `plain.chain_type=tool_call/tool_call_result`，但当前 `sse.py` 将它们丢弃，不写 ChatLog、不送 TTS。表情状态机需要的只是内部 phase 信号，不得改变这一用户可见文本合同。

### 2.2 Tivoo 上游核对

项目固定的 `d03n3rfr1tz3/hass-divoom@0e9959a...` 中：

- `Divoom.send_on()` 调用 `show_light(color=[1,1,1], brightness=100, power=True)`。
- `Divoom.send_off()` 调用 `show_light(color=[1,1,1], brightness=0, power=False)`。
- Tivoo golden vector 与本项目现有 screen-power golden 一致：业务 payload 均为 `0x45 0x01 ...`，本项目已分别锁定亮屏 `45 01 01 01 01 64 00 01 00 00 00` 和息屏 `45 01 01 01 01 00 00 00 00 00 00`。
- `send_frames()` 对多帧内容只发送 `set animation frame (0x49)`，没有“动画完成后恢复原画面”的后续命令。

因此本规格把“恢复”定义为 HA 主动重新下发当前赢家画面；亮屏后也必须重新渲染当前赢家，不能假定设备保留并恢复先前内容。

当前 ESP32 `DEVICE_STATUS/DEVICE_EVENT` 以及已观察到的 SPP reverse 状态不足以证明屏幕当前真实像素或当前 preset。状态机以 HA 的 desired state 为权威，不增加轮询式“读屏”。

## 3. 结构

只增加两个逻辑层，底层继续复用现有 SPP 编码和 transport：

```text
ScreenPowerGate
  └─ 决定当前是否允许显示内容
       ↓
ExpressionCoordinator
  └─ 从 active intents 中选最高优先级画面
       ↓
现有 Tivoo command_adapter / SPP transport
```

`ExpressionCoordinator` 持有 `desired intent`、`generation`、过期时间和最近一次已发送目标。任何 intent 新增、移除、过期或 generation 切换都执行一次 `recompute`。只有赢家变化、亮屏恢复或 SPP 重连需要重新发送，不做持续轮询。

## 4. 表情状态与优先级

优先级只表达覆盖关系，不要求实现时使用这些具体数字：

| 顺序 | 状态 | 进入依据 | 退出依据 | 默认画面 |
|---|---|---|---|---|
| 1 | `wake_confirmed` | 首轮 `WAKE_WORD_END` 有有效输出；或 side KWS 确认打断 | 当前轮进入 STT 完成/失败或被新 generation 取代 | `question` |
| 2 | `speaking` | 当前 playback 的 `AUDIO_STATE=playing` | 同 playback 的 `completed/stopped/interrupted/failed` | `music` |
| 3 | `tooluse` | 当前 Tivoo satellite 对话收到 AstrBot `tool_call` phase | `tool_call_result`、turn 结束或取消 | `tooluse` |
| 4 | `thinking` | 当前非错误 turn 已 `STT_END` 且 command 已开始 | speaking、turn 结束/取消；tooluse 只临时覆盖 | `thinking` |
| 5 | `active_listening` | 首次候选人声通过下述自然化门槛；或 follow-up 中出现 `speech_start` | speech_end、KWS miss、STT/turn 转移 | `standby` |
| 6 | `explicit_content` | 用户/自动化明确要求显示表情、图片、文字等 | 被新的显式内容替换或调用方清除 | 现有显示命令内容 |
| 7 | `ai_mood` | AstrBot Persona 在有明确情绪表达价值时调用专用 mood 意图 | TTL、generation 结束或取消 | mood 白名单 |
| 8 | `followup_wait` | 实际 playback completed 后进入现有 8 秒 follow-up | 新 speech_start 或 8 秒超时 | `standby` |
| 9 | `idle` | 没有更高优先级 intent | 任意更高状态出现 | idle 池 |

KWS 确认高于 speaking，保证打断成功后屏幕立即反馈“已听见”，不会等旧播放终态才改变。

### 4.1 idle 与候选监听

- idle 默认池只使用当前已存在的 preset：`standby`、`smiley`、`sleepy`、`sun`、`fish`。
- idle 随机轮换首期采用 30–90 秒随机间隔；这是项目策略值，不是 Tivoo 协议。
- 空闲首次 `speech_start` 不应每次都触发表情。首期策略：持续约 700 ms 后仍有人声才参与一次 35% 概率触发，并设 10 秒冷却。三个值均为可调策略常量，不进入 SPP 合同。
- KWS 一旦确认则 100% 进入 `wake_confirmed`，不受上述概率和冷却限制。

### 4.2 thinking、tooluse 与 speaking

- thinking 不从 `STT_START` 开始，因为此时用户可能仍在讲话；以当前非错误 turn 的 `STT_END` 为处理阶段入口。
- AstrBot `tool_call/tool_call_result` 只新增内部 phase 观察；继续禁止写入 ChatLog 或 TTS。phase 仅对 `satellite_id` 指向当前 Tivoo satellite 且 generation 仍有效的 turn 生效。
- speaking 只认当前 playback id 对应的真实 `AUDIO_STATE=playing`。旧 generation 的迟到 AUDIO_STATE 必须忽略。

## 5. AI 心情与显式显示

AI 心情不承担 listening/thinking/tooluse/speaking 等系统状态。后续实现应提供专用低优先级 mood 意图（建议 MCP 名称 `tivoo__SetMood`，这是本项目新接口，不是上游 Tivoo 接口），只允许情绪白名单，例如 `happy/sad/angry/love/cool/cry/laugh/sleepy/shock/wink/sick/party/kiss/oops`。

Mood 的触发条件放在 AstrBot Persona / Tool description：只有回答确实需要非语言情绪表达时才调用，正常回答不必每轮调用。HA 负责白名单、优先级、generation 和 TTL；首期默认 TTL 5 秒。Mood 被更高状态压住时仍按真实时间过期，过期后不补播。

现有 `SetExpression`、ShowImage/ShowText 等显式显示能力不能被 Persona 当作系统处理状态接口。后续接入 Coordinator 时，它们属于 `explicit_content`；系统会话状态可暂时覆盖，系统状态退出后可恢复仍有效的显式内容。

## 6. 屏幕门控

ScreenPowerGate 高于所有显示 intent。只要 gate 判定为 OFF：

- idle、listening、thinking、tooluse、speaking、AI mood 和 explicit content 都可以继续更新内部 desired state；
- 不允许这些状态向 Tivoo 下发可见内容；
- 只有屏幕电源命令本身和必要的连接恢复动作可以通过。

底层继续复用已存在的 `tivoo.set_screen_power(value: bool)` / `tivoo__SetScreenPower` 和现有 SPP payload，不新增“息屏协议”。

逻辑层采用 owner-based inhibit：`acquire(owner)`、`release(owner)`。任一 inhibit 存在就保持 OFF。现有 HA service 与 MCP tool 的对外 `value: bool` 签名必须保持兼容；后续接入 Gate 时，无 owner 的旧调用只能映射到一个固定 compatibility owner，`false` 获取、`true` 释放。**这个旧 bool 接口本身不能表达多个独立 owner。** 夜间自动化、AI 主动任务等若需要互不误解锁，必须通过 Coordinator 的稳定 owner 调用路径；若要把该能力公开给 HA 自动化，应在后续实现批次单独定义并测试扩展 schema，不在本规格猜测字段或修改现有上游接口。

预留内部 `temporary_wake(owner, ttl)`：临时亮屏只覆盖 gate，不删除原 inhibit；TTL 结束后若 inhibit 仍存在则再次息屏。是否暴露为新的 HA service/MCP tool 留给后续实现计划，本规格不固定未实现的公开名称。

从 OFF 切回 ON 时，必须立即 `recompute` 并重新发送当前赢家，因为上游 on/off 本身使用显示模式命令，不能假设恢复先前 GIF。

## 7. 恢复、重连与真实状态

- session/turn 正常结束、错误、取消、follow-up timeout 或 generation 替换时，统一清除该 generation 的会话级 intents，然后 recompute；不写 A→B 的成对回退分支。
- SPP 重连后：若 gate OFF，重新确保 OFF；若 gate ON，重新发送当前赢家。
- HA 重载但 SPP 已连时，以校验通过的初始 `DEVICE_STATUS.spp.state` 同步一次；7777 控制连接晚于诊断快照时仍重放当前 desired，不依赖重新出现 `spp_connected` 事件。原始 `0x69/0x96` 仅为 hint，不用于认定物理 SPP 已连。
- `last_sent` 只表示 HA 已成功提交对应 transport 写入，不等于物理 16×16 像素已确认。
- 不基于当前 opaque reverse SPP 字节构造“当前表情/当前像素”状态 API；后续只有获得经过型号实机验证的明确上游协议后才能增加。

## 8. 主动任务预留

未来 NAS 温度告警、主动提醒等功能必须复用同一 Coordinator，而不是并行发送“表情 + TTS”。主动播报开始时可以提交 `notify`/显式内容 intent，实际 `AUDIO_STATE=playing` 仍覆盖为 speaking；结束后按当时 gate 和剩余 intents 恢复。

HA Assist Satellite 的 announce/start-conversation 能力、自动化入口和主动任务调度不属于本规格实现范围；这里只保证状态机有可复用入口，不提前定义未核对的调用参数。

## 9. 非目标

- 不新增 ESP32 固件协议或 Tivoo raw packet。
- 不实现情感分类模型，不从回答文本自动猜 mood。
- 不解析/伪造 Tivoo 当前真实像素状态。
- 不把 VAD 改成播放停止条件。
- 不在本次修改生产代码、测试、部署或分批实施计划。
