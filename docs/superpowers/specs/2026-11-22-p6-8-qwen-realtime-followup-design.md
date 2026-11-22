# P6.8 Qwen Realtime 条件续聊设计

> - 日期：2026-11-22
> - 状态：方案 A 不变；B8.2 预检、B8.5 Bridge 与 B8.6 条件续聊软件验收通过。正常终态门禁在 B8.5 最小兼容补丁源码副本核销；NAS 尚未安装补丁，生产部署与实机验收仍归 B8.7。
> - 范围：仅适用于 P6.8 的 Qwen Realtime 语音路径；旧 AstrBot/HA Pipeline 路径及其既有 INTENT_END.continue_conversation 语义不变。

## 1. 已确定的产品行为

采用“Qwen 最终助手文本问号约定 + HA 本地判断”的条件续聊方式：

- Qwen 最终面向用户的完整回复确实需要用户提供下一条信息、选择或确认时，末尾使用中文全角问号 \`？\` 或 ASCII 问号 \`?\`。
- 不需要用户进一步回答的完整答复，使用句号等非问号结尾；不添加“还需要其他帮助吗”等礼貌性反问。
- HA 仅在收到当前 turn 的助手最终文本事件后判断结尾标点。
- 只有结尾为 \`？\` 或 \`?\` 才设置待续聊标记；无文本、文本事件缺失、其他标点、响应失败或中断，全部按不续聊处理。
- 即使模型表达了问句，HA 仍须等待匹配的 ESP32 真实播放完成，再通过现有 0x27 打开一次 4 秒 local_followup gate。
- 一次 follow-up 输入消费本次授权；第二轮模型回复重新按同一规则判断是否还需续聊。

这是项目对模型输出制定的**应用层约定**，不是 Qwen 模型原生的授权字段或事件。它不能被描述成结构化、强保证的授权回执。通过失败默认关闭、短时设备 gate、实际播放完成和当前 generation 约束，把标点误判的影响限制在一次短暂的续聊窗口内。

## 2. Prompt 注入位置与约定文本

### 2.1 使用真实的 PROMPT.md 覆盖机制

锁定的 Qwen Audio Agent 2.1.0 源码已确认：

- \`server/src/core/config.mjs\` 读取 \`QWEN_AUDIO_AGENT_FRONTEND_PROMPT_DIR\`；未设置时默认使用包内 \`config/frontend-agent\`。
- \`server/src/conversation/frontend-agent-context.mjs\` 的 \`loadFrontendPrompt()\` 从该目录读取固定文件名 \`PROMPT.md\`，最大内容长度为 16,000 字符。
- \`ASSISTANT.md\` 由 \`loadAssistantProfile()\` 单独读取，主要用于默认身份、人格、关系和表达风格；Qwen 2.1.0 指令层级明确限制其不能覆盖 PROMPT.md 的工具、路由、权限和核心规则。
- \`USER.md\` 是用户明确的长期偏好；\`MEMORY.md\` 是事实/决定材料，不应拿来承载应用协议。

因此，本项目的续聊规则应作为 PROMPT overlay，不能仅写入 ASSISTANT.md、USER.md 或 MEMORY.md。

部署方式（B8.7 执行，不在设计阶段改 NAS）：

1. 从正在部署的、已锁定镜像中复制完整的 \`config/frontend-agent/PROMPT.md\`，保留原规则。
2. 将本节 2.2 的 P6.8 规则追加到副本末尾，不能用短片段替换整个 PROMPT.md。
3. 将完整文件放在当前 Qwen 持久配置卷内的独立目录，例如 \`/root/.config/qwaudio/p68-prompt/PROMPT.md\`。
4. 设置 \`QWEN_AUDIO_AGENT_FRONTEND_PROMPT_DIR=/root/.config/qwaudio/p68-prompt\`。
5. 重启 Gateway 后核对有效配置目录、PROMPT.md 内容/hash 和总字符数不超过 16,000。
6. 后续升级 Qwen Agent 时，必须用新版本包内 PROMPT.md 重新 rebase overlay；不得永久冻结旧版系统规则。

实际 NAS 当前没有设置 \`QWEN_AUDIO_AGENT_FRONTEND_PROMPT_DIR\`；生产 Prompt 覆盖与重启留给 B8.7。

### 2.2 P6.8 续聊 Prompt overlay

以下为需追加的项目规则，不是新的 Gateway 配置字段：

\`\`\`markdown
## P6.8 Tivoo 语音续聊约定

只对直接面向用户的最终完整回复执行本规则：

1. 只有确实需要用户提供下一条信息、选择或确认，才能继续当前交流或任务时，才以中文全角问号“？”或英文问号“?”作为最终回复的最后一个有效字符。
2. 当前任务已经完成、不需要用户再回答时，以句号等非问号标点结束；不要追加“还有其他需要吗”“要不要我继续”等礼貌性反问。
3. 不要为了显得自然而将陈述句改成问句。问号表示确实期待用户下一条输入，不表示普通寒暄或修辞问句。
4. 调用工具前、工具执行中、工具结果尚未汇总时的内部过程，不是最终面向用户的回复；完成所有必要工具调用后，只根据最终回复决定是否使用问号。
5. 不输出单独的续聊标记、状态字段或解释本规则；保持正常自然语言和语音表达。
\`\`\`

规则应保持简短，避免扩展为新的工具或任务状态协议。

## 3. Agent 实际可用文本事件

Qwen Audio Agent v2.1.0 的实际源码映射：

- 上游 \`response.audio_transcript.done\` / \`response.output_audio_transcript.done\` 进入 \`RealtimePresentationRuntime.#audioTranscriptDone()\`。
- 上游 \`response.text.done\` 进入 \`#textDone()\`。
- 两条路径最终调用 \`#emitTranscript(final=true)\`，公开 Gateway 事件 \`transcript.final\`，字段包括 \`role=assistant\`、\`content\`、\`responseId\`、\`turnId\`。
- 对应增量事件是 \`transcript.delta\`，只用于展示，不用于续聊判断。
- 若 Gateway 启用了 playback receipts，部分助手 transcript 可能暂存到播放开始才发出；因此 HA 不能依赖 delta 的到达时间，也不能假设文本一定先于播放事件。

HA 判断的唯一输入：

- \`type == transcript.final\`
- \`role == assistant\`
- 事件属于当前有效 HA turn/generation
- \`content\` 是非空字符串
- 对内容执行末尾空白裁剪后，最后一个字符是 \`？\` 或 \`?\`

不采用 \`transcript.delta\`、用户角色 transcript、\`tool.call\`、\`audio.done\`、\`voice.state=idle\` 或模型响应状态推断续聊。

伪代码只描述判定，不代表新增 API：

\`\`\`python
def wants_followup(text: str) -> bool:
    return text.rstrip().endswith(("？", "?"))
\`\`\`

如果同一 turn 的最终助手文本没有到达，按 false 处理。不要从音频反向 ASR，也不要增加第二个 LLM 做二次分类。

## 4. 会话与输入架构

### 4.1 同一 WebSocket 继续当前对话

对一次由问号触发的 immediate follow-up，必须保持原 Gateway WebSocket 活着：

1. 当前用户 PCM 经原 GCP 7.0 socket 输入。
2. 模型输出语音与最终文本；HA 判断问号并暂存续聊意图。
3. 等待该 response 对应的 ESP32 playback_id 收到真实 \`AUDIO_STATE=completed\`。
4. 复用现有 HA follow-up 授权与 ESP32 0x27，打开一次 local_followup gate。
5. 用户通过新 MIC UUID / 新本地 turn 录入音频；HA 将这轮音频继续送入**原来的 Gateway WebSocket**。
6. Qwen 在同一活动 Realtime 会话上下文中接收下一轮；Gateway 为新输入产生新的 turnId/responseId。
7. 新响应再次判断是否续聊，形成下一轮相同流程。

不要只保存 sessionId、关闭 socket 后立即用相同字符串重连，再假定上下文必然还在。配置中的稳定 URL \`sessionId\` 是会话历史键，不等价于原来的活动 WebSocket。断开后 journal 恢复已由 B8.2 单独预检验证。

普通答复没有问号时，等匹配设备播放完成并正常结束 turn 后关闭 Gateway socket。问号触发后则保留 socket，直至续聊输入到达并完成后续响应，或 4 秒 gate 超时/取消/连接失败。

### 4.2 身份保持独立

- URL \`sessionId\)：稳定映射当前 HA ConfigEntry.entry_id，作为 Qwen 对话分区键。
- 当前活动 Gateway WebSocket：承载即时连续语境；续聊链路内保持不变。
- \`client.instance_id\`：稳定的 Tivoo 客户端/lease 身份，和 sessionId 不同。
- HA Context / turn generation：每一轮新的 HA turn 仍创建自己的 Context/generation。
- ESP32 MIC session_id：每一轮本地收音仍使用新 UUID；follow-up 设备入口不复用上一轮 MIC UUID。
- Qwen turnId / responseId / tool call callId：由 Gateway / model response 产生，不代替以上身份。
- ESP32 playback_id：仍由 HA 为具体物理播放分配并匹配终态。

不调用或虚构 HA ChatSession/conversation_id。新 turn 的 HA Context 和 MIC UUID 与保持活动的 Qwen WebSocket 并不冲突。

### 4.3 连接退出条件

- 普通回答物理播放完成且未 armed follow-up：关闭本轮 Gateway WebSocket。
- follow-up 输入到达：清除已消费的待续聊意图，原 socket 继续处理新 turn。
- follow-up gate 4 秒内无人说话：取消待续聊并按当前资源所有权规则关闭 socket / 收口 turn。
- 新真实唤醒、用户打断、Qwen 响应失败、ESP32 播放失败、HA unload、Gateway disconnect：先让现有 HA generation 失效并停止匹配播放，再按 B8.1 已核实的取消顺序取消/关闭 Gateway socket；旧事件不得影响新 turn。
- 以后一个独立的新唤醒如需重连同一 sessionId，必须以 B8.2 的 journal/context continuity 实测为依据；不把它与上述 immediate follow-up 混为一谈。

连接归属、旧轮 retire 与新轮移交，以及迟到事件过滤，统一遵循 [合同矩阵 §2.1](2026-11-22-p6-8-b8-1-qwen-realtime-contract-matrix.md#21-现有合同的最小实现补充2026-11-22)；复用现有 bridge/coordinator，不新增会话管理层。

## 5. HA 与 ESP32 的最小生命周期

复用当前 P6.8 的实现与合同，不发明新的设备消息：

- 使用当前有效 turn 的既有 \`continue_conversation\`/等价 per-turn 字段承载这一布尔结果；在 Qwen 路径中由助手最终文本问号规则赋值。若桥接结构不适合，最多新增一个属于当前 turn 的布尔值，不引入全局多阶段状态机。
- 必须同时满足：当前 turn/generation 有效、有效输入已结束并 drain、模型最终响应未失败/中断、对应 playback_id 的设备状态为 \`completed\`。
- 然后复用 \`AudioSessionManager.grant_followup(session_id)\` 和现有 \`TYPE_FOLLOWUP_OPEN (0x27)\`。
- 现有固件为 follow-up 创建新的 MIC UUID，设备按现有 \`followup=true\` 语义接受 speech_start；设备代码已把 follow-up speech_start 限制在 gate 时间窗口内（当前设计为 4 秒）。
- 沿用既有独立 follow-up beep 及声学安全 gate；4 秒从现有安全 gate 起算，不从模型 audio.done 或 beep 请求时刻起算。
- 用户开始 follow-up 后消费一次授权并清除待续聊标记；不允许同一授权重复打开 gate。
- 真正 wake 仍优先；旧 generation、取消、异常、超时必须清除标记。

现有源代码依据：\`assist_satellite.py\` 的 \`_Turn.continue_conversation\`、\`AudioSessionCoordinator._complete_response()\`；\`audio_session.py\` 的 \`grant_followup()\`、local follow-up session 验证；\`diagnostics.py\` 的 \`TYPE_FOLLOWUP_OPEN=0x27\`；ESP32 \`diagnostics.c\` 的 0x27 handler。实现阶段应以当时当前源码再次核对，不得照抄旧 Pipeline 的所有额外条件或计时。

## 6. 工具调用和音频终态边界

- 模型可能先发 Function Calling / MCP Tool Call，当前 response 可能没有语音。Agent 的工具调用状态是 \`tool.call.status=received\` 后到 \`completed\` 或 \`failed\`；工具状态不表达续聊意图。
- Gateway / Agent 会处理工具结果后的模型续接。HA 只判断工具执行结束后面向用户的最终 assistant \`transcript.final\`，不判断中间 response。
- \`audio.done\` 表示某个模型 response 的音频生成结束，不表示工具链结束，也不代表 ESP32 物理播放结束。
- \`AUDIO_STATE=completed\` 且 playback_id 匹配，才是本系统的设备播放完成条件。
- response 失败、中断、被旧 generation 抑制或没有有效最终文本，默认不续聊。锁定 Gateway 的 cancelled/incomplete 终态可能不向客户端公开，问号与 audio.done 不能证明正常成功；该可观测性缺口按合同矩阵 §2.1 保持门禁，不新增猜测字段，也不默许放宽条件。

## 7. B8 批次分工

| 批次 | 必须实现/验证的内容 |
|---|---|
| B8.2 | 实测助手 \`transcript.final\` 是否保留中文全角/英文问号和普通句号；验证 final 事件的 role/turnId/responseId；在同一活动 Gateway WebSocket 上完成两轮真实输入/响应，证明 immediate follow-up 的上下文续接；同时单独验证断线重连是否恢复 history，不将其作为 immediate follow-up 前提。 |
| B8.5 | Qwen Bridge 转发助手 \`transcript.final\` 及其 turn/response identity；支持续聊期间保留当前 WebSocket；生成/维护 P6.8 Prompt overlay 片段；不在 bridge 内另建状态机。 |
| B8.6 | HA 从当前 generation 的最终 assistant 文本计算一次布尔意图；重用 per-turn 续聊字段、已有 \`grant_followup()\`、0x27、4 秒 gate 和设备 beep；只在真实 playback completed 后授权；续聊输入走原 WebSocket 和新 MIC UUID/HA Context。 |
| B8.7 | 从锁定镜像提取完整 PROMPT.md、合并 overlay、设置 Prompt dir env 并做 NAS 验收；验证问号、句号、工具调用后最终问句、播放失败、打断、超时及同 socket 双轮。 |

## 8. 测试和验收矩阵

| 场景 | 预期 |
|---|---|
| 助手最终文本以 \`？\` 结尾 | 仅 arm，不立即开放麦克风 |
| 助手最终文本以 \`?\` 结尾 | 同上 |
| 助手以 \`。\` / \`!\` 结尾 | 不 arm |
| 助手文本末尾只有空白 | 裁剪空白后判断 |
| 用户 transcript 以问号结尾 | 忽略 |
| \`transcript.delta\` 中途出现问号，最终句号 | 不 arm |
| 最终助手文本缺失、空文本、响应 failed/cancelled/incomplete | 不 arm |
| 工具调用后最终回复问号 | 只在最终助手文本后 arm，不因工具调用本身 arm |
| 最终文本问号但 ESP32 playback failed/interrupted | 不打开 0x27 |
| 最终文本问号且匹配 playback completed | 只开一次 4 秒 gate |
| 4 秒内无用户 speech_start | 取消授权、收口资源 |
| 4 秒内用户 speech_start | 新 MIC UUID；复用原 Gateway WebSocket；新 turnId |
| 续聊后的第二轮再次问号 | 重新按同一规则 arm，不继承旧授权 |
| 新 wake / cancel / unload / reconnect | 旧 generation 和旧标记不影响新轮 |

### Gate

B8.2 已验证助手最终文本的标点/身份关联及同一活动 socket 多轮上下文，详见 [B8.2 报告](../reports/2026-11-22-p6-8-b8-2-qwen-gcp-pcm-preflight.md)。该结果不证明 cancelled/incomplete 可被客户端识别，也不代表 HA/设备续聊已验收。

B8.5 接入前须先核销合同矩阵 §2.1 的正常终态门禁；B8.5/B8.6 的反例测试须覆盖最终问句后取消/不完整、工具中间文本、文本晚于物理完成、旧轮清理后同 socket 接续。方案 A、0x27、4 秒 gate 与 B8.7 Prompt 部署范围均不变。
