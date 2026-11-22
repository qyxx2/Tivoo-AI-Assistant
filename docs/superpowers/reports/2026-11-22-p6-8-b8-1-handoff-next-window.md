# P6.8 B8.1 当前进度与下一窗口交接

- 更新日期：2026-11-22
- 项目：Tivoo-AI-Assistant
- 工作区：`/home/Gold/WorkSpace/Tivoo-AI-Assistant`
- 当前分支：`feature/p6-8-s3-local-wake`
原始交接时的任务范围：仅完成 P6.8 B8.1，尚未执行 B8.2；当前决策更新及下一步以本文第 8 节为准。

## 1. 当前结论

**历史记录：B8.1 原始审查完成时，因 follow-up 产品策略未确定而暂记 Gate = HOLD。** 2026-11-22 用户随后明确选择方案 A；当前产品决策已完成，B8.2 技术 Gate 仍待验证。请以本文最后的“决策更新”作为当前状态。

原始 HOLD 的直接原因是：Qwen GCP 7.0 没有原生 `continue_conversation=true` 字段、事件或等价结构化授权回执；P6.8 原合同又要求在真实播放 completed 后才打开一次 4 秒 local-followup 窗口。该接口事实仍然成立。随后用户已选择方案 A，用当前 generation 的助手 `transcript.final` 末尾 `？`/`?` 作为项目级应用策略，问号只 arm，并不替代真实播放完成、有效 turn、单次 0x27 和 4 秒 gate。

`audio.done`、`voice.state=idle` 仍不能作为续聊依据；`transcript.final` 也不是原生授权字段，只有按方案 A 限定为当前助手最终文本且末尾为问号时，才作为项目应用层意图标记。失败、缺失 final 文本或非问号默认不续聊。

**当前产品决策已完成。B8.2 允许开始协议/标点/同活动 WebSocket 双轮预检；B8.2 的标点保真和同 socket 上下文连续性通过前，不得在 B8.5/B8.6 实现问号续聊。** 旧 AstrBot/Pipeline 合同保持不变。

## 2. 本次已完成

### 文档产物

1. `docs/superpowers/specs/2026-11-22-p6-8-b8-1-qwen-realtime-contract-matrix.md`
   - 新增 B8.1 审查追踪合同 `B81-C01` 至 `B81-C15`。
   - 逐项说明现有接口、源码依据、事件时序、身份映射、边界及不支持的假设。
   - 对原 P6.8 合同矩阵进行了影响核对，没有伪造上游 API。
2. `docs/superpowers/reports/2026-11-22-p6-8-b8-1-qwen-realtime-contract-matrix-review.md`
   - 记录审查结果与 Gate HOLD 的原因。
3. `docs/superpowers/plans/2026-11-22-p6-8-qwen-realtime-migration-plan.md`
   - 修订了架构、事件名、session 映射、取消语义、raw PCM 资源边界和各批次任务说明。
   - B8.1 标记为审查完成但 HOLD；B8.2–B8.7 仍未执行。
4. `docs/superpowers/plans/2026-11-18-p6-8-b1-b10-execution-plan.md`
   - 更新 B8.1 状态、引用矩阵/报告，并加入后续批次约束。

### 审查和验证

- 对照 Qwen Audio Agent `v2.1.0` 上游 tag，固定源码 commit：`a9f4478da8df400d04facbb099ac2933ce8b11bc`。
- 对照 P6.8 当前 HA / ESP32 实现及其既有合同，不把实验 worktree 的试验端点当作生产接口。
- 原合同矩阵数量核对：`P68-HB01–15` 15 条、`AFE-C01–12` 12 条、`VOICE-C01–10` 10 条、`LIFE-C01–08` 8 条、`VIEW-C01–04` 4 条，共 49 条。
- B8.1 审查追踪项 `B81-C01–C15` 共 15 条。
- 本地 Markdown 引用目标存在；文档检查通过；`git diff --check` 通过。
- 本次只有文档修改，没有改生产代码、ESP32 固件，没有构建、刷机或部署；没有运行 HA/ESP32 运行时测试套件。

## 3. 关键协议结论（不要反向写错）

### 客户端事件和服务端事件

- GCP 客户端线上音频输入事件是 `input_audio_buffer.append`，携带 base64 音频字段 `audio`。Gateway 内部归一化事件 `audio.append` 不是客户端线上事件名。
- GCP 客户端协议没有 `input_audio_buffer.commit`。不要让 HA 发送 Provider 端的 `input_audio_buffer.speech_stopped` 或 `input_audio_buffer.committed`。
- `audio.delta` 是输出音频分块，分块中包含 `sampleRate` 和 `responseId`。必须按实际分块采样率处理，不能无依据写死 24 kHz。
- `audio.done` 表示某个 response 的音频生成结束，不代表整轮业务完成，也不代表 Tivoo 硬件已经播放完成。
- 已核对的公开 GCP server events 中没有 `response.done`。不要依赖这个事件。
- 客户端取消事件是 `response.cancel`；Gateway 会归一化为内部 `interrupt`。不要把内部名称当成线上客户端事件。

### 取消与工具副作用

- `response.cancel` 会取消 provider response 并清理 Gateway playback。
- Qwen v2.1.0 的 MCP 请求使用连接级 `toolScope.signal`；单独发 `response.cancel` 不保证取消正在执行的 MCP 请求。该 signal 在 Gateway session close/disconnect 时 abort。
- HA 在切换/取消旧 turn 时，应先失效旧 generation、停止对应播放、发送 `response.cancel`，再关闭旧 socket 并完成清理；避免旧回调污染新 turn。
- 已执行的 HA Service 副作用通常没有通用回滚保证。非幂等工具不能因为取消/断连就盲目重试。

### 身份与会话

- `ownerId`：Gateway 根据 access credential 识别的认证主体。
- `sessionId`：WebSocket URL query 中的会话 ID，也是 session journal 历史键的一部分。
- `client.instance_id`：来自 `session.hello`，用于区分客户端实例/lease。
- 三者不是同一个概念。相同 owner 同时仅允许一个活动 Client；相同 `client.instance_id` 重连可替换旧 socket，不同实例可能触发 `client_occupied`。
- 当前迁移方案采用稳定的 `ConfigEntry.entry_id` 作为 Qwen URL 的 `sessionId`，并用独立稳定 ID（例如 `tivoo-<ConfigEntry.entry_id>`）作为 `client.instance_id`。这是项目映射决策，不是声称 HA 存在 ChatSession API。
- 当前 AssistSatellite 每轮新建 HA `Context()`；当前集成没有使用 HA `ChatSession` 或 `conversation_id`。不要在实现或合同中假定它们已存在。

### MCP / 内网 URL

- Qwen v2.1.0 Frontend MCP 支持 `streamable-http`、环境变量 header 引用、Bearer header 和显式工具 allowlist。
- 该版本 `normalizedUrl()` 对远程 MCP URL 只允许 HTTPS；HTTP 只允许不带 headers 的 loopback。局域网地址（如 NAS 的 `192.168.x.x`）使用 HTTP + Bearer 会被拒绝。
- `readOnly` / `approval` 不是该版本支持的有效策略字段，`normalizedPolicy()` 会拒绝它们。
- HA `/api/mcp/assist` 已在项目 P4 合同和 `test_tivoo_p4b5_mcp_http.py` 中验证 Streamable HTTP、Bearer、普通非管理员 HA 用户的 tools/list 与 tools/call。生产 allowlist 必须按 NAS 实际 tools/list 确认，不得照搬开发环境 fixture 数量。

### 音频播放实现边界

- ESP32 当前 `TIVOO_PCM_MIME` 是 `audio/x-tivoo-pcm-s16le-32000-mono`，已有 RAW PCM 32 kHz mono 播放路径。
- `TTS_PLAY` 使用命令 `0x30`，包含 playback_id、url、mime_type（可带当前 session_id）；设备通过 HTTP GET 拉取资源。
- 当前 HA `transport.py` 的 `async_send_tts_play()` 和 `audio_resource.py` 的 `build_internal_tts_url()` / `TtsResourceManager` 是现有 HA TTS Proxy / Pipeline TTS 流程，不是 Qwen raw PCM 音频分块 HTTP 资源。
- 试验 worktree 中的 `/api/tivoo/qwen/audio/...` 不是当前生产接口，不能在合同矩阵中列为已有接口。
- ESP Audio Effects SRC 虽已在 MP3 decoder 路径调用，不能据此推断 RAW PCM 24→32 kHz 已支持；相关转换必须在后续实现和实测中证明。

## 4. 原始审查时的待决事项（已由第 8 节更新覆盖）

**以下两条产品路线是 2026-11-22 原始审查时的讨论记录；用户随后已选择方案 A，不需要再次征求选择。当前执行入口是第 8 节规定的 B8.2 技术预检。**

下一窗口应先阅读：
- `docs/superpowers/specs/2026-11-18-p6-8-b0-5-lifecycle-display-design.md`
- `docs/superpowers/specs/2026-11-18-p6-8-b0-4-ha-stt-prompt-design.md`
- `docs/superpowers/specs/2026-11-22-p6-8-b8-1-qwen-realtime-contract-matrix.md`（重点 B81-C15）
- `docs/superpowers/reports/2026-11-22-p6-8-b8-1-qwen-realtime-contract-matrix-review.md`
- `docs/superpowers/plans/2026-11-22-p6-8-qwen-realtime-migration-plan.md`

以下两条路线仅保留原始 B8.1 讨论记录；方案 A 已由用户选定，不要按此处内容重新发起产品选择：

1. **保留 P6.8 的 follow-up 行为和显式授权要求。** 必须从真实存在且可观测的协议/应用接口中找到每轮授权来源，并保证它与当前 turn 绑定；只有真实设备播放完成后才消费一次授权并打开 4 秒窗口。若需要新增应用层机制，先定义它实际由谁触发、如何传递、如何验证及如何防止跨 turn/重复消费。不能虚构 Qwen 原生字段或事件。
2. **明确调整 Qwen 模式的产品合同。** 例如明确规定 Qwen 实时模式不启用该 local-followup 行为，或改为另一种经产品确认的交互方式。此路线必须显式评估对原 P6.8 用户体验/合同的影响，更新 spec、合同矩阵、迁移计划和测试断言；不得把缺少授权信号当作理由而静默删除旧逻辑。

（历史记录）原始 B8.1 审查时应保持 Gate HOLD；该产品决策现已由用户选择方案 A 解决。当前下一步按本交接文档第 8 节执行，仅开始 B8.2 技术预检，不再重复询问产品策略。

## 5. 当前可进行的工作与后续 Gate

产品策略已确定，下一步仅执行 B8.2：验证助手 `transcript.final` 标点保真、role/turnId/responseId 关联、同活动 WebSocket 双轮上下文、本地 VAD EOF/静音尾帧和 session 隔离。B8.2 通过后按迁移计划进入后续批次；B8.5/B8.6 续聊生产实现不得提前。每批仍应遵循：
- 先核对对应 spec、合同矩阵、执行计划与现有实现；
- 只定义会真实调用的接口；每个接口都要能追溯到项目源码或上游官方源码；
- 区分 Gateway 协议事件、HA 集成内部事件、ESP32 UART/SPP 命令、设备播放状态；
- 对取消、重连、generation、session、音频播放完成等边界做真实测试；
- 不把音频生成完成当成硬件播放完成；
- 不把实验 worktree 的代码或端点当成生产实现；
- 不跨批次提前实现 B8.2–B8.7，也不顺手修改无关 B9/B10 任务。

## 6. 工作区状态与交接注意事项

上次任务完成后，远端工作区 Git 状态为：

```text
## feature/p6-8-s3-local-wake
 M docs/superpowers/plans/2026-11-18-p6-8-b1-b10-execution-plan.md
?? docs/superpowers/plans/2026-11-22-p6-8-qwen-realtime-migration-plan.md
?? docs/superpowers/reports/2026-11-22-p6-8-b8-1-qwen-realtime-contract-matrix-review.md
?? docs/superpowers/specs/2026-11-22-p6-8-b8-1-qwen-realtime-contract-matrix.md
```

说明：
- 上述迁移计划文件在本次 B8.1 工作开始前已存在于工作区（未跟踪）；本次对它进行了修订。
- 父执行计划在本次开始前已有未提交修改；本次只在其基础上更新 B8.1 相关内容。不要把原有 B9/B10 修改误判成本次新增，也不要覆盖/丢弃它们。
- 本次新增了 B8.1 矩阵与审查报告。
- 所有改动仍未 stage、未 commit。没有执行 git reset、checkout 丢弃或其他清理操作。
- 开始下一窗口工作前，先查看 `git status --short` 和相关 diff，确认以上文件仍在；不要直接 reset、stash 或覆盖工作区。
- 当前起始 HEAD（本次开始 B8.1 前）：`9be427dcc85e3150ba16b65b6c44424cf2a968be`。

## 7. 建议交给下一窗口的启动指令

在 qqq 设备的 `/home/Gold/WorkSpace/Tivoo-AI-Assistant` 工作区继续，保持当前分支 `feature/p6-8-s3-local-wake`。先读取本交接文档第 8 节所列设计、运行时报告、B8.1 合同矩阵和 Qwen 迁移计划；再检查 git status 与现有 diff。**本轮仅按 B8.2 计划执行协议/标点/同活动 WebSocket 双轮预检，不开始 B8.3 以后生产实现，不修改无关 B9/B10。** 所有接口/事件必须从当前项目源码或固定版本 Qwen 上游源码中核实，不得推测或杜撰。

补充：上面的 Git 状态清单是 B8.1 完成时、创建本交接文档之前的状态。本交接文档是随后新增的文件，因此当前工作区还会多出：

```text
?? docs/superpowers/reports/2026-11-22-p6-8-b8-1-handoff-next-window.md
```

---

## 8. 2026-11-22 决策更新：方案 A 已确定，下一批先做 B8.2

本交接文档前文 §1–§5 记录的是 B8.1 审查刚结束时的历史状态。随后用户明确选择方案 A，产品策略已完成决策；不要再要求用户重新选择，也不要再把“是否保留 follow-up”作为待决问题。

### 已选架构

Qwen Realtime 最终助手回复通过末尾标点表达是否真正需要用户下一步回答。Qwen Agent 核心 `PROMPT.md` 增加 P6.8 overlay：只有确实需要补充信息/选择/确认时，完整最终回复才以“？”或“?”结尾；已完成的回答使用普通结束标点，不做礼貌性反问。

HA 只处理当前 generation 的 assistant `transcript.final`，执行 `content.rstrip().endswith(("？", "?"))`。不处理用户 transcript、`transcript.delta`、工具调用中间响应，也不从 `audio.done`/`voice.state=idle` 推断续聊。问号只 arm 当前 turn，不立即开麦克风。匹配 ESP32 playback_id 的真实 `AUDIO_STATE=completed` 后，复用现有 `AudioSessionManager.grant_followup()`、0x27 和 4 秒 local_followup gate。失败/中断/文本缺失/普通标点 fail closed。

immediate follow-up 必须保留原活动 Gateway WebSocket，第二轮输入通过原 socket 发送。HA 第二轮创建新 Context/generation，ESP32 第二轮使用新 MIC UUID，Gateway 生成新 turnId/responseId。不能关闭 socket 后只凭相同 sessionId 重连来代替上下文连续性。普通应答没有续聊时，才在匹配物理播放完成后关闭连接。旧 AstrBot/Pipeline 仍沿用 `INTENT_END.continue_conversation`，不受此改动影响。

### Prompt 的真实注入方式

Qwen Audio Agent 2.1.0 源码确认核心指令通过 `<frontendPromptDir>/PROMPT.md` 加载；`ASSISTANT.md` 是单独的人设文件，不能作为核心行为规则覆盖位置。NAS 当前没有设置 `QWEN_AUDIO_AGENT_FRONTEND_PROMPT_DIR`，正在使用包内 Prompt。

B8.7 应从锁定镜像复制完整 `config/frontend-agent/PROMPT.md` 到持久目录，追加 P6.8 overlay，设置 `QWEN_AUDIO_AGENT_FRONTEND_PROMPT_DIR` 并重启验证；不要用几行 overlay 替换整个 PROMPT.md，也不要只修改 ASSISTANT.md。详情见 [Qwen Realtime 条件续聊设计](../specs/2026-11-22-p6-8-qwen-realtime-followup-design.md) 和 [运行时核查报告](2026-11-22-p6-8-qwen-audio-agent-runtime-investigation.md)。

### 下一窗口只做什么

**下一步允许启动 B8.2，且仅执行 B8.2 预检/协议验证；不要开始 B8.3 以后的生产实现，更不要开始 B8.5/B8.6。**

B8.2 必须先验证：
1. 助手最终自然语言文本是否真实通过 `transcript.final` 到达 HA，保留“？”、“?”和普通句号，role/turnId/responseId 对应正确。
2. 在同一活动 Gateway WebSocket 中连续执行两轮语音输入/模型响应，第一轮后不关闭 socket，第二轮经原 socket 上传，确认第二轮确实能使用第一轮上下文。
3. 独立测试关闭后以相同 sessionId/client.instance_id 重连的 journal 恢复；它不能替代同 socket 测试。
4. 工具调用中间 response、不完整/失败/中断响应不触发续聊；只有最终助手文本参与标点判断。

B8.2 通过后，才在 B8.5 接入 assistant final 文本/保持 socket 生命周期，在 B8.6 实现 HA 标点判断、播放完成后的 0x27/4 秒 gate；B8.7 安装持久 PROMPT overlay 并部署验收。具体步骤已写入 [Qwen Realtime 迁移计划](../plans/2026-11-22-p6-8-qwen-realtime-migration-plan.md)。

当前未实现代码、未改 NAS、未部署 Prompt、未开始 B8.2；本次任务只更新了架构/批次文档。开始下一窗口前仍须检查 Git 状态和未提交 diff，不 reset/stash/覆盖原来的 B8.1 文件。
