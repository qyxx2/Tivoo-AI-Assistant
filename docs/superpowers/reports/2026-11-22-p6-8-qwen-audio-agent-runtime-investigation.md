# Qwen Audio Agent 2.1.0 / Qwen3.8 Realtime NAS 运行时核查报告

> 日期：2026-11-22；目标：为 P6.8 B8.1 follow-up 合同决策提供真实部署证据。
> 性质：只读 NAS 检查 + 一次隔离的内置只读工具实时探测。未修改 NAS 配置、镜像、项目代码或部署状态。

## 1. 实际运行环境

| 项目 | NAS 实测 |
|---|---|
| NAS | Synology DS920；通过此前已信任 HostKeyAlias 的 IPv6 root SSH 只读连接 |
| 容器 | \`qwen-audio-agent\` |
| 镜像 | \`local/qwen-audio-agent:2.1.0\` |
| 镜像 ID | \`sha256:4a64b7fee162d368a65aba63af61e3d61c9ddb23c14a24a0cdd9a3954fcf5faf\` |
| 包版本 | \`qwen-audio-agent 2.1.0\` |
| HA | \`2026.11.0\` |
| Realtime 模型 | \`qwen3.8-omni-flash-realtime\` |
| Provider / API profile | DashScope / \`omni-v2\` |
| Turn detection | \`semantic_vad_ec\` |
| Voice | Tina |
| 模型输入/输出采样率 | 16 kHz / 24 kHz PCM |
| Gateway | \`http://192.168.3.94:3101\` |
| Realtime endpoint | 北京地域 DashScope WebSocket endpoint（不记录认证信息） |
| 部署适配器补丁 | \`shared/realtime-models/dashscope.mjs\`；SHA256 \`86e183bbd2c82ebc669d28410a9f695eab8af0525642209644fe79576d19af7c\` |

以上来自运行容器、实际环境配置、健康接口和安装包源码；密钥、Bearer token、DashScope API Key 均未读取或写入报告。

## 2. 当前 HA MCP 连接状态

实际健康接口中的结果：

\`\`\`json
{
  "frontendMcp": {
    "ok": true,
    "initialized": true,
    "tools": 0,
    "servers": []
  },
  "backend": {
    "enabled": false,
    "protocol": null,
    "kind": null,
    "label": "仅前台聊天",
    "status": "not_configured",
    "capabilities": { "backendUi": false },
    "ok": true,
    "code": "NOT_CONFIGURED"
  }
}
\`\`\`

进一步只读调用安装版本的 \`loadFrontendMcpConfiguration({filePath:''})\`，实际结果为：

\`\`\`json
{"version":1,"servers":[]}
\`\`\`

结论：

- 当前 NAS Gateway 没有配置任何 Frontend MCP Server。
- 当前 Gateway 的外部 MCP 工具数为 0。
- Qwen 模型官方具备 Function Calling 和 Remote MCP 能力，不代表当前 Qwen Agent 已经连接 HA MCP。
- Qwen Agent Frontend MCP 到 HA 的集成仍属于 B8.3，不得写成已经部署或验收。

## 3. Qwen Agent 自带 Markdown Prompt 的真实机制

锁定镜像中的源码：

- \`server/src/core/config.mjs\`：\`frontendPromptDir\` 由 \`QWEN_AUDIO_AGENT_FRONTEND_PROMPT_DIR\` 覆盖；没有设置时回退到包内 \`config/frontend-agent\`。
- \`server/src/conversation/frontend-agent-context.mjs\`：\`loadFrontendPrompt()\` 从 \`frontendPromptDir/PROMPT.md\` 读取核心 Prompt；最大 16,000 字符。
- 同一文件的 \`loadAssistantProfile()\` 单独读取 \`ASSISTANT.md\`，最大 4,000 字符。
- \`server/src/core/frontend-profile.mjs\`：\`QWEN_AUDIO_AGENT_ASSISTANT_PROFILE_PATH\` 用于 Assistant Profile 文件，不是核心 PROMPT.md 的路径。
- 当前容器没有设置 \`QWEN_AUDIO_AGENT_FRONTEND_PROMPT_DIR\`，当前配置卷有 \`ASSISTANT.md\`、\`data/USER.md\`、\`data/MEMORY.md\`，没有自定义 Prompt 目录。

实际包内 PROMPT.md 为 5,633 字符；当前是完整包内核心 Prompt。ASSISTANT.md 的代码注释和随包说明将其范围限制在默认身份、人格、关系和表达风格，不能可靠承担 P6.8 的行为协议。

**实施结论：** 将续聊约定作为 P6.8 Prompt overlay，合并到锁定版本完整 PROMPT.md 的自定义副本；用 \`QWEN_AUDIO_AGENT_FRONTEND_PROMPT_DIR\` 指向该目录。不要将规则只写入 ASSISTANT.md / USER.md / MEMORY.md，也不能用只有几行的 overlay 替换整个 PROMPT.md。实际 NAS 修改留 B8.7。

## 4. Gateway 协议与模型输出文本路径

锁定版本源码检查结果：

### 4.1 用户输入

- GCP v7 客户端音频输入事件：\`input_audio_buffer.append\`。
- GCP 客户端文本输入事件兼容名：\`conversation.item.create\`，协议映射到 Agent 内部的 \`input.message\`。
- 实际 \`RealtimeInputRuntime.submit()\` 会创建新的 Agent turn，记录当前 owner/session 的用户内容，再通过当前 frontend provider 提交输入。
- 不存在已验证的 GCP 客户端 \`input_audio_buffer.commit\`；Provider 的 speech_stopped/committed 不是客户端事件。

### 4.2 模型助手文本

\`server/src/voice/realtime-presentation-runtime.mjs\` 明确处理：

- \`response.audio_transcript.delta\`
- \`response.output_audio_transcript.delta\`
- \`response.audio_transcript.done\`
- \`response.output_audio_transcript.done\`
- \`response.text.delta\`
- \`response.text.done\`

其中 transcript done / text done 进入 \`#emitTranscript(final=true)\`，被映射为 Gateway 的 \`transcript.final\`，带有：

- \`role: "assistant"\`
- \`content\`
- \`responseId\`
- \`turnId\`（从响应上下文映射）
- 当前响应上下文中的 generation 等必要字段

增量文本映射为 \`transcript.delta\`。工具调用的中间 response 和未完成文本不能作为最终续聊判据。

这是锁定源码明确支持的路径，但本报告的实时探测没有成功取得一条普通助手自然语言最终回复，因此中文问号是否在当前模型的最终文本中稳定保留仍待 B8.2 实测。

### 4.3 不存在原生续聊授权字段

对锁定版 GCP client/server event schema、Gateway server event、DashScope provider profile 和实际模型配置检查：

- 没有 \`continue_conversation\`。
- 没有 \`should_followup\`。
- 没有 \`need_user_reply\`。
- 没有等价的结构化续聊授权回执。

\`semantic_vad_ec\` 负责语音活动/端点检测，不是助手回答完成后是否期待用户继续发言的授权。

## 5. 一次真实隔离探测

用户通过 Desktop Commander 的审核面板批准了一次只读探测。探测创建独立的 Gateway 会话，不复用 WebUI 会话；使用内置只读工具 \`get_current_time\`，不调用 HA/设备服务。

探测会话 ID：\`nas-observe-3e40b705b73d\`

实际收到的关键序列（时间为探测进程相对起始时间）：

| t_ms | 事件 | 实际结果 |
|---:|---|---|
| 16 | \`session.ready\` | GCP \`7.0.0\`，获得 session_id |
| 17 | \`voice.state\` | idle |
| 17 | \`voice.ownership\` | active |
| 38 / 487 | \`voice.connection\` | connecting → connected，provider=dashscope |
| 487 | \`voice.ready\` | DashScope Realtime |
| 491 | \`turn.started\` | 新 turn |
| 492 | \`transcript.final\` | role=user，文本输入完成 |
| 1304 | \`response.started\` | 模型 response 开始 |
| 1342 | \`tool.call\` | get_current_time，surface=frontend，status=received |
| 1344 | \`tool.call\` | 同一 callId，status=completed，durationMs=3 |
| 1346 | \`audio.done\` | 该 response 音频生成终态 |

实际 tool call 事件状态为：

\`\`\`text
received -> completed
\`\`\`

这验证了当前运行时的前台 Function Calling 入口、工具状态更新和音频生成终态事件。该工具是 Agent 内置工具，不是 HA MCP。

**未验证的项目：** 本次没有得到 assistant 自然语言 \`transcript.final\`，没有完成第二轮输入，也没有在同一个 WebSocket 上证明 turn 间上下文保留；因此不能声称上述三项已经实测通过。

## 6. Tool Call、MCP 与 response/audio 状态边界

- Qwen Audio Agent 的 \`tool.call\` 公共状态实际观察到 \`received\` 和 \`completed\`；安装版执行器也会在失败时发 \`failed\`。
- Agent 内部 Frontend MCP 工具源把 MCP 工具包装成前台 Function Calling。它与 Qwen 模型底层协议中的原生 Remote MCP 事件不是同一事件流。
- 模型官方支持 Remote MCP，不代表当前 NAS 已配置 MCP；当前 health 是 0 server / 0 tool。
- \`audio.done\` 只表示当前模型 response 的生成端音频结束，不是 Agent 全部工具流程结束，也不是 Tivoo 设备播放结束。
- 当前 P6.8 设备真实播放完成仍以匹配 playback_id 的 ESP32 \`AUDIO_STATE=completed\` 为准。
- \`response.done\` 是 Provider 内部事件；锁定的 GCP 公共 server event 不提供它，HA 不应订阅虚构的公开 \`response.done\`。

## 7. 会话身份与连接生命周期

项目计划中身份映射为：

| 身份 | 用途 |
|---|---|
| ConfigEntry.entry_id → Qwen URL sessionId | 稳定 Qwen 历史/会话分区键 |
| Gateway ownerId | 由 Gateway access credential 决定的认证主体 |
| client.instance_id | GCP 客户端实例/lease ID，Tivoo 稳定使用独立值 |
| HA Context / generation | 每个 HA turn 的新上下文和 generation |
| ESP32 MIC session_id | 每次 wake/follow-up 收音用新 UUID |
| Qwen turnId / responseId / tool call callId | 分别标识模型输入轮次、响应和工具调用 |
| ESP32 playback_id | 匹配设备物理音频播放 owner 和终态 |

Agent 源码中，文本输入 \`conversation.item.create\` 被映射至当前连接对应的 \`RealtimeInputRuntime.submit()\`，该 runtime 使用创建它时绑定的 ownerId/sessionId。会话关闭会调用 \`realtimeSession.close()\`，并中止连接级工具 scope。

因此 P6.8 immediate follow-up 的架构要求应为：模型问号响应播放完毕后，保持原 Gateway WebSocket 不关闭；用户 follow-up PCM 到达时继续走该 socket。只保留 sessionId 字符串、关闭 socket 后再新建连接，不能替代同一活动连接的上下文保证。

同一活动 socket 两轮输入尚未被本次探测实测，必须列入 B8.2。独立新 wake 或连接中断后的 history journal 恢复是另一个场景，需单独验证，不与 immediate follow-up 混为一谈。

## 8. 对 P6.8 架构决策的结论

1. 已存在可供 HA 消费的助手文本最终事件路径，不需要 HA 从音频二次 ASR。
2. 没有 Qwen 原生的续聊授权布尔值；续聊策略应由项目定义。
3. 用户已选择“最终助手文本问号约定 + HA 判断”的方案 A。
4. HA 只判断 assistant \`transcript.final\` 的最后有效字符为 \`？\` / \`?\`，不处理 delta 或用户文本。
5. 标记只 arm，不立即开麦；等待真实匹配 playback completed 后复用既有 \`grant_followup()\`、0x27 和 4 秒本地 gate。
6. immediate follow-up 必须使用原活动 Gateway WebSocket；新一轮仍拥有新 HA Context、MIC UUID 和 Qwen turnId。
7. Prompt overlay 使用锁定 v2.1.0 的完整 PROMPT.md 副本 + P6.8 规则，并由现有 \`QWEN_AUDIO_AGENT_FRONTEND_PROMPT_DIR\` 覆盖机制加载。
8. B8.2 先实测 assistant final transcript 标点和同 socket 多轮连续性；未通过前不写生产 parser 或部署 Prompt。

## 9. 源码证据定位

NAS 安装包根目录：\`/usr/local/lib/node_modules/qwen-audio-agent\`

| 文件 | 核对内容 |
|---|---|
| \`shared/protocol/gateway-client-protocol.mjs\` | GCP 7.0 客户端事件、conversation.item.create 映射 |
| \`shared/protocol/gateway-events.mjs\` | 输入/输出事件 schema |
| \`server/src/voice/realtime-input-runtime.mjs\` | \`submit()\` 处理和用户输入记录 |
| \`server/src/voice/realtime-session-runtime.mjs\` | 连接事件分派、turn/runtime/socket close |
| \`server/src/voice/realtime-presentation-runtime.mjs\` | 上游 transcript done → Gateway transcript.final、audio.done、response/context 关联 |
| \`server/src/frontend/tools/tool-call-handler.mjs\` | 工具调用 received/completed/failed |
| \`server/src/frontend/tools/mcp/frontend-mcp-config.mjs\` | Frontend MCP 配置和 URL 策略 |
| \`server/src/conversation/frontend-agent-context.mjs\` | PROMPT.md / ASSISTANT.md 分离加载 |
| \`server/src/core/config.mjs\` | \`QWEN_AUDIO_AGENT_FRONTEND_PROMPT_DIR\` |
| \`config/frontend-agent/PROMPT.md\` | 包内完整核心 Prompt |
| \`config/frontend-agent/ASSISTANT.md\` | 默认助手画像，不是续聊协议配置 |

上游文档/版本：
- Qwen Audio Agent v2.1.0：\`https://github.com/QwenAudio/qwen-audio-agent/tree/v2.1.0\`
- Qwen Realtime 模型官方事件文档：阿里云 Model Studio Realtime API 的 Client Events / Server Events / Function Calling / Remote MCP 文档。
- Qwen Assistant Profile / Preferences：\`https://qwenaudio.github.io/qwen-audio-agent/zh/reference/personalization\`
- Qwen Memory Provider / Context Boundaries：\`https://qwenaudio.github.io/qwen-audio-agent/zh/reference/memory-provider\`

## 10. 本次范围与未完成事项

- 完成 NAS 只读配置、健康接口、锁定 v2.1.0 源码和一次隔离 live probe。
- 没有修改 NAS 文件、环境变量、容器、镜像、HA 配置或设备状态。
- 没有修改工作区生产代码；本次新增/更新仅为 P6.8 设计、审查与计划文档。
- 未执行 B8.2 的中文助手文本双标点测试、同 WebSocket 双轮测试和真实 4 秒 follow-up gate 测试。
- 未执行 B8.3 MCP 接入、B8.4 SRC、B8.5/B8.6 生产实现、B8.7 部署。



---

## 11. Gateway 公共事件全集、状态枚举与任务生命周期

以下是锁定 Qwen Audio Agent v2.1.0 / GCP 7.0.0 安装包中定义或实现的 Gateway 公共协议，不等同于 DashScope 原生模型 WebSocket 事件。

### 11.1 Gateway server event 家族

安装包 `shared/protocol/gateway-events.mjs` 与相邻协议定义中的公共事件家族：

| 类别 | Gateway 事件 |
|---|---|
| 连接 | `gateway.connected`、`gateway.disconnected` |
| 语音连接与状态 | `voice.connection`、`voice.ready`、`voice.state`、`voice.ownership`、`voice.deactivated`、`voice.sleep` |
| turn / 播放控制 | `turn.started`、`playback.clear` |
| 输入控制 | `input.suspend`、`input.resume` |
| 音频输出 | `audio.delta`、`audio.done` |
| response 生命周期 | `response.started`、`response.interrupted` |
| transcript | `transcript.delta`、`transcript.final`、`transcript.discard` |
| 工具 / Agent | `tool.call`、`agent.activity` |
| 状态 / 错误 | `memory.changed`、`client.state`、`error` |

事件字段以锁定版本 schema 为准。对于续聊实现，直接相关字段为：

- `transcript.delta/final`：`role`、`content`，并带当前上下文映射出的 `turnId`；助手最终文本还带 `responseId`。
- `audio.delta`：Base64 PCM、实际 `sampleRate`、`responseId`，用于设备音频传输关联。
- `audio.done`：`responseId`（以及当前上下文的 turn 标识）；仅是模型 response 音频生成终态。
- `response.started/interrupted`：`responseId` 和可关联的 turn 上下文。
- `tool.call`：`callId`、`name`、`surface`（frontend/backend）、`status`、args/result、`durationMs`、`responseId`、`turnId`、可选 `taskId`。

### 11.2 Gateway 状态值

| 字段 | 锁定版已定义值 | 含义/边界 |
|---|---|---|
| `voice.state` | `idle`、`listening`、`processing`、`speaking` | Gateway 当前语音阶段；不替代 ESP32 物理播放状态 |
| `voice.ownership` | `active`、`busy`、`available` | Gateway owner / voice lease 状态 |
| `voice.sleep` | `preparing`、`enabled`、`sleeping`、`detected`、`awake`、`disabled` | Gateway 睡眠/唤醒子状态 |
| `voice.connection.state` | 非空字符串 | schema 不把它限制成固定枚举，不应自行补造完整值表 |
| `client.state.state` | 非空字符串 | 由客户端状态上报，schema 不定义固定枚举 |

`voice.ready` 主要携带输入采样率和 provider/providerLabel。不要将 `voice.state=idle` 当作响应最终文本已完成或设备播放完成信号。

### 11.3 Tool Call 状态

Gateway 对一个 Agent 工具调用公开的状态生命周期：

```text
tool.call(status=received)
    -> tool.call(status=completed | failed)
```

同一个 `callId` 关联开始和终态事件。schema 的 `status` 是普通 string，并非对外固定 enum；以上三个值来自锁定版执行路径。工具执行失败的状态与模型 response 的音频终态、整轮对话意图互相独立。

此前 NAS live probe 实际验证了内置只读 `get_current_time` 的 `received -> completed`，耗时 3 ms。历史 NAS 日志也记录过内置 `web_search` 实际调用和 Agent-origin 后续模型响应。两者都不证明当前 NAS 已配置 HA MCP。

### 11.4 Background Task 状态（与语音 turn / follow-up 分开）

锁定版 Task 公共事件家族包括：

- `task.snapshot`、`task.accepted`、`task.scheduled`、`task.scheduled.fired`
- `task.running`、`task.delegated`、`task.finalizing`、`task.cancelling`
- `task.updated`、`task.progress`、`task.completed`、`task.failed`、`task.cancelled`
- `task.permission.requested`、`task.permission.resolved`
- `task.input.requested`、`task.input.resolved`
- `task.notification.pending`、`task.notification.delivered`、`task.notification.offline`

`GatewayTaskSchema.workState` 值：`submitted`、`working`、`auth_required`、`input_required`、`completed`、`failed`、`cancelled`。

内部 TaskStatus 另有：`scheduled`、`queued`、`running`、`delegated`、`finalizing`、`cancelling`、`completed`、`failed`、`cancelled`。

这些状态用于后台 Agent Task，不是语音 response 的“等待用户回答”状态，不可映射到 Qwen 问号续聊。

## 12. 模型原生 Function Calling 与 Remote MCP：与 Agent 工具桥接分层

### 12.1 原生 Function Calling

Qwen3.8 Omni Realtime 原生 Function Calling 工作流包含：

1. 模型产生 `function_call` 输出项。
2. 服务端发出 `response.output_item.added`、`response.function_call_arguments.delta/done`、`response.output_item.done` 等事件。
3. 原生 function_call item 的状态可为 `in_progress` 后完成；客户端执行本地工具。
4. 客户端用 `conversation.item.create` 回传 `function_call_output`，随后发送 `response.create` 让模型基于结果继续回答。

Qwen Audio Agent 2.1.0 在 GCP 外层将其包装成 Gateway `tool.call`，在服务端执行 Agent built-in 或外部 frontend source 工具，再由 Agent 管理工具结果后的模型续接。HA 不应再自己模拟一次 Function Calling 的 `response.create`，否则会与 Agent 自身的响应调度重叠。

### 12.2 模型原生 Remote MCP 事件

Qwen3.8 Omni Realtime 原生 Remote MCP 协议有独立的事件家族：

- 工具发现：`mcp_list_tools.in_progress`、`mcp_list_tools.completed`、`mcp_list_tools.failed`。
- MCP 调用：`response.mcp_call.in_progress`、`response.mcp_call.completed`、`response.mcp_call.failed`。
- 需要人工审批时出现 `mcp_approval_request` 对话项；客户端通过 `conversation.item.create` 回传 `mcp_approval_response`，内容包含 `approval_request_id` 与 `approve` 布尔值。
- 拒绝/超时会使对应 MCP 调用失败；调用完成后模型可以继续生成最终回复。具体事件顺序按当前 Qwen3.8 原生 MCP 交互文档。

这套原生 Remote MCP 是模型/Realtime 服务端直接管理 MCP Server 的路径。当前阿里云 Qwen3.8 Realtime 文档要求在 `session.tools` 配置公网 HTTPS MCP Streamable HTTP 服务，默认要求审批；Function Calling 与 MCP 可以同时配置在 `session.tools`，但不能同时启用联网搜索 `enable_search`。因此 NAS 内网 HTTP 的 HA MCP 不能仅靠模型原生 MCP 配置直接接入，除非另外提供满足要求的 HTTPS 端点。它不是 Qwen Agent 的 Frontend MCP Client，也不是 Agent 对 HA 暴露的 Gateway `tool.call` 事件。

### 12.3 Agent Frontend MCP 与 GCP client.tools 不是原生 Remote MCP

当前 Agent 2.1.0 内部 Frontend MCP Client 负责连接已配置 MCP Server，把发现到的外部工具纳入 Agent 的前台工具来源；模型侧仍经 Agent 的 frontend Function Calling / ToolCallHandler 进入执行流程，再通过 Gateway `tool.call` 对客户端呈现。

另一个不同机制是 GCP `session.hello` 中的 `client.tools`。安装包文档明确说明：这是客户端声明可供 Agent 调用的 Client Tools，**不是 MCP Server**；通过 `client.action.request` / `client.action.result` 执行，也不能称作 HA MCP。

NAS 当前：
- Frontend MCP servers = 0、tools = 0。
- 没有配置模型原生 Remote MCP Server。
- 真实 live probe 仅调用 Agent 内置只读工具。
- 模型官方支持 Remote MCP，不代表这两个实际运行配置已经启用它。

### 12.4 与续聊方案的关系

上述工具发现、工具调用、审批和工具结果续接都属于工具执行生命周期。HA 问号策略只能处理所有工具步骤完成后，最终面向用户的 assistant `transcript.final`。中间 `tool.call` / MCP 状态和工具 response 的 `audio.done` 均不触发续聊。

## 13. 当前模型文档中容易混淆的边界

- Qwen3.8-Omni-Flash-Realtime 官方模型文档说明：模型支持文本/流式音频/视频输入、文本/音频输出、自定义 Function Calling 和 Remote MCP；这不等于 Agent 当前启用了 Remote MCP。
- 阿里云原生 Realtime API 文档定义 `input_audio_buffer.append` 和 `input_audio_buffer.commit`。但 Qwen Audio Agent v2.1.0 的 GCP Client Protocol 7.0 schema/alias 表没有把客户端 `input_audio_buffer.commit` 映射到 Agent 输入事件；本项目 HA 只能发送 Agent 已实现的 GCP 事件，不能把模型原生 Client Event 直接当作 Gateway Client Event。
- 原生模型 VAD 会产生 `input_audio_buffer.speech_started`、`input_audio_buffer.speech_stopped`、`input_audio_buffer.committed` 等 Provider/模型侧事件；它们不是 HA 在 GCP 客户端 socket 上可以发送的控制消息。
- 原生 Realtime `response.audio.done` 也可能在 interrupted、incomplete、cancelled response 情况出现，不能单凭它判断成功；Agent 映射后的 `audio.done` 仍不是设备播放完成。
- `idle_timeout_ms` 用来在静默超时后主动触发对话的能力，官方约束只适用于 Qwen3.5 Omni Realtime 的 `server_vad` 场景，不属于本部署 Qwen3.8 Omni + `semantic_vad_ec` 可以依赖的续聊授权机制。
- 原生 Realtime Function Calling 与原生 Remote MCP 的结果续接，都是工具流程续接；与等待用户下一轮语音不是同一状态。

### 上游官方文档入口（协议层参考）

- [Qwen3.8 Omni Realtime 模型信息](https://help.aliyun.com/zh/model-studio/qwen3-8-omni-flash-realtime)
- [Realtime API 概览](https://help.aliyun.com/zh/model-studio/realtime)
- [Realtime Client Events](https://help.aliyun.com/zh/model-studio/client-events)
- [Realtime Server Events](https://help.aliyun.com/zh/model-studio/server-events)
- [Realtime Function Calling](https://help.aliyun.com/zh/model-studio/qwen-function-calling)

以上链接描述模型原生协议；Agent 的可用 Gateway 客户端协议仍以 NAS 锁定的 Qwen Audio Agent 2.1.0 安装包源码为准。
