# Tivoo 表情状态机合同矩阵

> 日期：2026-11-14
> 分支：`feature/p6-6-tivoo-expression-state-machine`
> 状态：P6.6b0–b5 已执行并完成 C19 post-b5 修复；自动化合同及 ESP32 单独 reset 后 7777/SPP 恢复已通过，生产验收仍存在真人语音链 GAP
> 规格：[Tivoo 表情状态机与屏幕门控规格](2026-11-14-tivoo-expression-state-machine-design.md)
> 分批计划：[P6.6 表情状态机与屏幕门控分批实施计划](../plans/2026-11-14-p6-6-tivoo-expression-state-machine-batch-execution-plan.md)
> 验收报告：[P6.6b5 全量验收与生产部署](../reports/2026-11-14-p6-6-expression-state-machine-acceptance.md)

## 1. 权威关系

本矩阵只约束 Tivoo 屏幕状态、优先级、恢复和屏幕门控。P6.5 继续作为 MIC/KWS/STT/TTS/打断/播放生命周期的权威；P3 继续作为 AstrBot SSE、ChatLog 和 Stop 生命周期的权威；P4/2026-11-14 Tivoo capability expansion 继续作为 Tivoo service/MCP/SPP 能力的权威。

实现时不得为了显示状态改写这些既有业务语义，也不得把本矩阵中标为“新逻辑合同”的内部接口伪装成已存在的上游 API。

## 2. 合同

| ID | 合同 | 真实依据 / 边界 | 状态 |
|---|---|---|---|
| ESM-C01 | Tivoo GIF/多帧表情不以“播放完成”作为恢复依据；任意业务状态退出后由 HA `recompute` 主动发送下一赢家 | 固定 hass-divoom `send_frames()` 只发送 `0x49` animation chunks，无恢复命令；用户已实测动画常驻 | 新逻辑合同 |
| ESM-C02 | 没有更高 intent 时必须存在 `idle` 兜底；idle 首期只从当前已存在的 `standby/smiley/sleepy/sun/fish` 选取 | 当前 `PRESETS/EMOTION_PRESETS` | 新逻辑合同 |
| ESM-C03 | idle 首期 30–90 秒随机换一次；空闲候选人声约持续 700 ms 后按 35% 概率显示 `active_listening`，10 秒冷却 | 均为项目策略常量，不是 Tivoo/HA 上游协议；必须可独立调整 | 新逻辑合同 |
| ESM-C04 | 有效首轮 `WAKE_WORD_END.wake_word_output` 或 side KWS Detection 必须 100% 提交 `wake_confirmed` | 当前 `AudioSessionCoordinator` 已有两个真实 KWS 路径 | 新逻辑合同 |
| ESM-C05 | `thinking` 只能在当前非错误、已开始命令的 turn 到达 `STT_END` 后进入；不得从 `STT_START` 提前进入 | 当前 Pipeline event 路径；STT_START 时用户仍可能在说话 | 新逻辑合同 |
| ESM-C06 | 当前 Tivoo satellite 的 AstrBot `tool_call` 提交 `tooluse`；对应 `tool_call_result` 移除它并重新仲裁 | P3/SSE 已识别这两个 chain_type，但当前明确丢弃；只能增加内部 phase 观察，不得写 ChatLog/TTS | 新逻辑合同 |
| ESM-C07 | `speaking` 只由当前 playback id 的真实 `AUDIO_STATE=playing` 进入；`completed/stopped/interrupted/failed` 退出 | 当前 ESP32/transport/playback handler；HA TTS_START/TTS_END 不能替代物理播放状态 | 新逻辑合同 |
| ESM-C08 | 仅当前 turn 的 `continue_conversation=true` 且 `AUDIO_STATE=completed` 后进入 8 秒 follow-up；等待期可显示弱 `followup_wait`，新的 `speech_start` 再进入 active listening/STT。`false`/缺失时结束会话并回 idle | P6.5 `_open_followup()` 与 8 秒 timer | 2026-11-17 修订 |
| ESM-C09 | 覆盖顺序固定为：`wake_confirmed > speaking > tooluse > thinking > active_listening > explicit_content > ai_mood > followup_wait > idle` | 这是显示仲裁策略；KWS 高于 speaking 用于打断确认即时反馈 | 新逻辑合同 |
| ESM-C10 | 每个会话级 intent 必须绑定当前 turn/generation；旧轮取消、失败、session end、follow-up timeout 或新 generation 替换时统一清除旧 intents；迟到事件不得恢复旧画面 | P6.5 已有旧 playback/generation 隔离语义 | 新逻辑合同 |
| ESM-C11 | AI mood 只能提交低优先级、session-scoped、有限 TTL 的 mood intent；首期 TTL 5 秒；不自动从回答文本做情绪分类 | 当前已有 mood preset；Persona 可决定是否调用，HA 必须强制生命周期 | 新逻辑合同 |
| ESM-C12 | AI mood 白名单首期限定当前已有 `happy/sad/angry/love/cool/cry/laugh/sleepy/shock/wink/sick/party/kiss/oops`；系统状态表情不进入 mood 白名单 | 当前 `EMOTION_PRESETS` | 新逻辑合同 |
| ESM-C13 | 后续可增加项目自有 mood Tool；它必须提交 intent 而不是直接发送 SPP。规格中建议名 `tivoo__SetMood` 仅是项目接口命名，不是上游 Tivoo API | 当前不存在该 Tool；实现前仍须在对应批次固定 schema/测试 | 预留，不得视为已实现 |
| ESM-C14 | 用户/自动化明确要求的 `SetExpression/ShowImage/ShowText` 等属于 `explicit_content`；瞬态系统状态可覆盖，退出后若内容仍有效则恢复 | 现有显示 service/MCP 已真实存在；“lease/恢复”是新增协调逻辑 | 新逻辑合同 |
| ESM-C15 | ScreenPowerGate 为硬门控：OFF 时所有 idle/会话/mood/explicit content 只能更新 desired state，不得下发可见内容 | 防止夜间/人工息屏被自动待机或语音状态重新点亮 | 新逻辑合同 |
| ESM-C16 | 底层屏幕电源继续复用现有 `tivoo.set_screen_power(value: bool)` / `tivoo__SetScreenPower`；不得新增 raw SPP 息屏协议 | 当前代码、protocol golden、固定 hass-divoom send_on/send_off 已核对 | 已实现底层能力 |
| ESM-C17 | 多来源息屏在内部使用 owner inhibit：任一 owner 未释放则 gate 仍为 OFF；现有公开 bool service/MCP 保持兼容并只能映射到固定 compatibility owner。需要独立 owner 的自动化/AI 必须走 Coordinator 稳定 owner 路径；公开 owner schema 留待实现批次定义 | owner 是 HA 侧协调概念，不是上游协议字段；当前 bool 接口无法表达多 owner | 新内部合同；公开扩展延后 |
| ESM-C18 | 预留内部 `temporary_wake(owner, ttl)`：只临时绕过 gate，不删除 inhibit；到期后若仍有 inhibit 必须再次 OFF | 用于未来高优先级告警；是否暴露公开 service/MCP 不在本批次定义 | 新内部合同；公开扩展延后 |
| ESM-C19 | OFF→ON 后必须立刻 recompute 并重新发送当前赢家；SPP 重连时 OFF 要重申 OFF，ON 要重发赢家；重载后已连 SPP 的初始已校验 DEVICE_STATUS 也应触发一次同步；ESP32 单独 reset 后若其已校验 `tcp["7777"]` 与 HA 旧 control socket 状态冲突，必须回收 stale 7777 并走既有重连 | 上游 on/off 本身是 `0x45 0x01` 显示/灯效模式，不保证恢复原 GIF；2026-11-16 真机 reset 验证 ON/OFF 均恢复 | 新逻辑合同；真机 PASS |
| ESM-C20 | HA 的 `desired_state/last_sent` 是本状态机权威；`last_sent` 只证明 transport 写入，不证明物理像素；当前不得从 opaque SPP reverse 推导“当前表情/当前像素” | P6 reverse 只验证有限状态回显；现有 DEVICE_STATUS 不是完整显示状态 API | 必须保持 |
| ESM-C21 | 状态表情优先复用现有 preset；若后续新增专用 listening/speaking 动画，只替换角色到 preset 的映射，不改变状态机事件/优先级合同 | 避免把视觉素材名称耦合进生命周期 | 新逻辑合同 |
| ESM-C22 | 未来主动告警/主动播报必须复用同一 ScreenPowerGate/ExpressionCoordinator；其 announce/start-conversation 调用接口由后续独立规格核对后再定义 | 本批次不实现主动交互，不猜 HA 公开参数 | 预留 |
| ESM-C23 | 表情状态机不得改变 P6.5 的 VAD/KWS 打断权、8 秒 follow-up、playback id/generation 规则，也不得改变 P3 的 SSE 可见文本和 Stop owner | 本矩阵只消费既有生命周期事件 | 必须保持 |

## 3. 最小验收边界（供后续实现计划引用）

后续实现至少要证明：状态优先级和回退不靠成对硬编码；旧 generation 的迟到事件不能改屏；`tool_call/tool_call_result` 只影响内部显示；真实 playback 状态驱动 speaking；OFF gate 能阻止 idle/会话/mood/显式内容重新点亮；多个 inhibit 不会被单个 release 误解除；temporary wake 到期恢复原 gate；ON/reconnect 会重发当前赢家；当前不存在物理像素确认时不会伪报“设备正在显示某表情”。

本矩阵不要求本次创建测试、生产实现、部署或分批计划。
