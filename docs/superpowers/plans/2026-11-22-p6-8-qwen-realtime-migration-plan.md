# P6.8 B8.1–B8.7 Qwen Realtime 语音入口迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. 本计划只在独立的 B8.1 合同矩阵确认后执行；一次只执行一个批次，先 RED 后 GREEN，独立报告/本地提交。不得自行进入 B9。

**Goal:** 在不改变 HA 设备控制、会话仲裁、显示和 MCP 权威地位的前提下，将 P6.8 Tivoo 的 STT→HA Intent→AstrBot→HA TTS 语音链路替换为 Qwen Realtime + HA 现有 Assist MCP；不再依赖 AstrBot。

**Architecture:** S3 本地 WakeNet/VAD、HA PCM ingress、turn generation、播放所有权、设备服务和显示仲裁继续保留。HA 将当前 turn 的 16 kHz PCM 送入 Qwen Gateway GCP 7.0；Qwen Gateway 通过 Frontend MCP Client 直接调用 HA 现有 `/api/mcp/assist`。回答音频由 HA 经 B8.5 新增的有界 PCM HTTP 资源交给 ESP32；ESP32 已有 `TTS_PLAY`/HTTP GET 控制及 32 kHz mono raw-PCM 播放路径，24 kHz 输入重采样归 B8.4。Qwen `sessionId` 使用稳定的 `ConfigEntry.entry_id` 映射；HA 每一轮仍创建独立 `Context()`/generation，`client.instance_id` 是独立稳定的 Gateway 客户端/lease 身份。**若助手最终文本触发方案 A 的续聊，当前 Gateway WebSocket 必须跨越物理播放、4 秒 follow-up gate、下一轮输入及响应保持活动；只有本轮确定不续聊、gate 超时或错误收口时才关闭。** 独立新 wake 的断线重连/journal 恢复是单独场景，交 B8.2 验证；不能用相同 sessionId 字符串替代同 socket 连续上下文。

**Tech Stack:** HA Core 2026.11.0、Qwen Audio Agent 2.1.0（实际 NAS 版本实施前复核）、GCP 7.0、Qwen3.8 Omni Realtime、MCP Streamable HTTP、现有 Tivoo HA Integration、ESP-IDF v6.1 / ESP Audio Effects SRC。

**Spec:** [P6.8 总体设计](../specs/2026-11-18-p6-8-b0-1-overall-design-baseline.md)、[HA 语音接口设计](../specs/2026-11-18-p6-8-b0-4-ha-stt-prompt-design.md)、[生命周期设计](../specs/2026-11-18-p6-8-b0-5-lifecycle-display-design.md)、[旧合同迁移索引](../specs/2026-11-18-p6-8-legacy-contract-migration-index.md)、[Qwen Realtime 条件续聊设计](../specs/2026-11-22-p6-8-qwen-realtime-followup-design.md)、[NAS 实测报告](../reports/2026-11-22-p6-8-qwen-audio-agent-runtime-investigation.md)、[原 B1–B10 计划](2026-11-18-p6-8-b1-b10-execution-plan.md)、[Qwen 单轮音频桥接试验记录](../../../../Tivoo-AI-Assistant-main-gpio/docs/experiments/2026-11-21-qwen-realtime-audio-bridge.md)（仅作为独立 worktree 参考；实施者需在本分支重新核对来源代码）。

## Global Constraints

- **B8.1 产品决策不变，B8.2 标点与同 socket 多轮预检 PASS；B8.5/B8.6 仍须先核销合同矩阵 §2.1 的正常终态可观测性门禁。** 用户选择方案 A：模型最终助手文本用 `？`/`?` 表达确实需要用户下一步回答，HA 只解析当前 generation 的 assistant `transcript.final`。该约定是项目应用层策略，不是 Qwen 原生 `continue_conversation` 字段。设计：[Qwen Realtime 条件续聊设计](../specs/2026-11-22-p6-8-qwen-realtime-followup-design.md)；运行时证据：[Qwen Audio Agent 实测报告](../reports/2026-11-22-p6-8-qwen-audio-agent-runtime-investigation.md)。
- 仅替换语音/LLM 输入输出链路。保留本地唤醒、S3 AFE/VAD、7777/7778、UART/SPP、HA Services、HA MCP API、ExpressionCoordinator、ScreenPowerGate、音频输出唯一 owner、设备状态和其他 P6.8 工作。
- HA 继续是业务控制面和设备状态/服务权威。Qwen 负责实时语音理解、模型推理、工具选择和回答；Qwen 不直接连接 ESP32/SPP，不新增第二套设备控制、显示或播放仲裁。
- **复用现有 HA Assist MCP endpoint**：`/api/mcp/assist`，Streamable HTTP；不得另建第二套 HA MCP Server、GCP Client Action 映射或自制 28 个 Tivoo 工具。Qwen 使用标准 Frontend MCP Client。Qwen 的工具 allowlist 必须基于 NAS 实际 `tools/list`，不是把开发机测试列表直接当作生产配置。
- 用户只在内网使用 HA/Qwen。优先给 Qwen 2.1.0 Frontend MCP URL 校验增加一个显式 opt-in 的 RFC1918 内网 HTTP 例外，保留公网远程 HTTP 拒绝、远程 HTTPS 和原 loopback 规则；不先引入内网 TLS。HTTP 例外只服务明确配置的内网 HA 地址，认证仍使用 Bearer Token。
- 所有 HA MCP 凭据、Qwen Gateway token、DashScope API Key 只能保存在 NAS Secret/环境变量，不写 Git、日志或验收报告。HA MCP 使用专用非管理员用户 Token；不复用管理员 Token。
- 不搬迁、不解析、不导入 AstrBot 中的会话或记忆；Qwen 的 `ASSISTANT.md`、`USER.md`、`MEMORY.md` 及 Gateway journal 使用独立持久化目录。AstrBot 容器和代码在新链路验收后移除。
- Qwen GCP 7.0 客户端线上输入事件为 `input_audio_buffer.append`，Gateway 内部将其归一化为 `audio.append`；Qwen 2.1.0 没有公开输入音频 commit 客户端事件。DashScope Omni 的 VAD 模式依赖持续音频流触发自动端点。因此本项目优先验证“HA 本地 VAD 结束后追加静音 PCM 尾帧”能否稳定触发 Qwen VAD；尾帧长度以实际 A/B 数据决定，不能臆定。若失败，停止迁移，不得伪造不受支持的 GCP 事件；另行评估最小 Gateway 协议扩展。
- Qwen3.8 Omni 的已验证输入为 16 kHz mono PCM16，输出事件携带实际采样率，当前部署试验为 24 kHz。ESP32 播放总线仍为 32 kHz mono PCM；优先复用 ESP Audio Effects 的有状态 SRC。不得把试验分支的线性插值升采样作为最终音质实现。
- 同一个 Qwen owner 同一时刻只有一个活动 Client。Tivoo 使用稳定的 `client.instance_id`。**同一对话的 immediate follow-up 必须复用当前活动 WebSocket；不能在物理播放结束后为 follow-up 关闭并重建连接。** 普通回答无 follow-up 时才在匹配设备播放完成后关闭。新唤醒或故障重连可使用稳定 `ownerId + sessionId + client.instance_id`，但其上下文恢复由 B8.2 单独实测。不得让 Qwen WebUI 语音客户端与 Tivoo 同时抢占同一 owner。
- HA 的设备 `session_id`、HA `Context.id`、Qwen `sessionId`、Qwen `client.instance_id`、Gateway `ownerId`、ESP32 playback_id 是不同身份。当前项目以稳定 `ConfigEntry.entry_id` 映射 Qwen URL `sessionId`；`client.instance_id` 使用独立稳定值。不得虚构 HA ChatSession/conversation_id，也不得混用 UUID。
- 任何 interrupt/cancel 都必须以 HA 当前 turn 为 owner：先阻止旧回复继续交付，再定向停止匹配 playback_id、取消旧 Gateway response/连接并 join 清理。旧轮 MCP/模型结果、音频终态、timer 和回调不得覆盖新 generation。
- 不提前删除 Sherpa/Wyoming 全局服务。仅在 NAS 盘点实际 consumers 后，若确认无其他消费者，才随 B9 停止整个 STT/TTS/Wake 容器；若仍有其他用户，保留服务但 Tivoo 不再依赖它。
- NAS 部署前保存 Qwen/HA compose、环境变量键名、当前镜像 digest、当前 Gateway 配置、HA 自定义集成目录和可回滚镜像/tag。报告不得记录 Secret 明文。

## Review Focus

1. S3 `speech_end` 后本地 PCM iterator 会 EOF；需验证追加静音尾帧能否让 Qwen Provider VAD 结束输入，并由 Gateway 公开 transcript/response 事件。Provider 内部 `speech_stopped` 只能作为 Gateway/Provider 侧证据，不是 HA 客户端事件。
2. Qwen `audio.delta.sampleRate` 发生变化或不是 24 kHz 时，HA/ESP32 必须按实际采样率拒绝或正确配置 SRC，不能错速播放。
3. 含 MCP Tool Call 的上游 response 的 `audio.done` 只是中间 response；必须继续等待工具结果和最终语音 response，不能提前关闭 PCM/WS。
4. 本地唤醒在 Qwen 生成或 ESP32 播放期间发生；旧 response、进行中的 MCP 调用、旧音频 stream 和旧 display generation 必须按当前所有权规则收口。
5. HA reload、Qwen Gateway 重启、WebSocket 重连、ConfigEntry 更换或 Gateway session journal 恢复；不得串用旧 Qwen session 或让单 owner lease 被其他客户端意外占用。**另需验证 assistant `transcript.final` 的中文问号/句号保真及同一活动 WebSocket 两轮输入，不以断线重连的 journal 恢复代替 immediate follow-up 连续性。**

---

## B8.1 — 独立合同矩阵审查与放行门禁

**结果：B8.1 审查与产品策略设计完成；B8.2 预检 PASS。后续最小实现补充及门禁以合同矩阵 §2.1 为准。** GCP 7.0 没有原生 `continue_conversation` 字段或授权事件，因此问号只作为项目应用层约定，不标记为 Qwen 原生授权。详细合同见 [Qwen Realtime 条件续聊设计](../specs/2026-11-22-p6-8-qwen-realtime-followup-design.md)。这两项预检已通过；正常终态可观测性与生产生命周期验收仍按合同矩阵 §2.1 执行。

- [x] 审阅 P6.8 49 条合同矩阵与旧迁移索引受影响条目。审查矩阵：[B8.1 Qwen Realtime 合同矩阵](../specs/2026-11-22-p6-8-b8-1-qwen-realtime-contract-matrix.md)。
- [x] 核对本地 VAD EOF 与 Qwen Provider VAD 的边界、ConfigEntry.entry_id 到 Qwen URL sessionId 的项目映射、MCP 权限边界、response/tool/audio/playback 生命周期、取消和 owner 冲突语义。原生续聊授权字段缺失已确认；用户随后选择以 assistant `transcript.final` 问号约定作为项目策略，详见 B81-C15 与条件续聊设计。
- [x] 形成独立审查报告：[B8.1 合同矩阵审查报告](../reports/2026-11-22-p6-8-b8-1-qwen-realtime-contract-matrix-review.md)。报告保留原审查与用户决策历史；最新预检及实现门禁以 B8.2 报告和合同矩阵 §2.1 为准。

**放行条件更新：** 方案 A、B8.2 预检 PASS 保留。B8.3/B8.4 按原范围推进；B8.5 接入前先证明正常最终响应与 cancelled/incomplete 的客户端可区分性，未核销不得以无 error、audio.done 或 idle 视为成功。其余连接移交、早端点/清播放及 PCM 清理条目随 B8.5/B8.6 验收，统一见 [合同矩阵 §2.1](../specs/2026-11-22-p6-8-b8-1-qwen-realtime-contract-matrix.md#21-现有合同的最小实现补充2026-11-22)。本次不新增上游协议改造批次。

## B8.2 — Qwen GCP、HA PCM 边界与本地 HTTP 预检

**Files:**
- Inspect only: test worktree `homeassistant/custom_components/tivoo/qwen_realtime.py`、`tests/homeassistant/custom_components/tivoo/test_qwen_realtime.py`、试验记录。
- Inspect only: P6.8 `assist_satellite.py`、`audio_session.py`、`transport.py`、ESP32 `audio_frontend.c`。
- Add: `tests/integration/qwen_realtime` 或现有项目已使用的 Qwen 探针目录（先复用已有测试目录结构，不引入新的长期服务）。

**Interfaces:**
- Input: 当前 P6.8 在本地唤醒及 ready prompt 完成后提供的有序 16 kHz mono S16LE PCM；本地 `speech_end` 后 iterator 正常 EOF。
- Output: 已验证的 Qwen3.8 Omni GCP 7.0 用户轮次端点行为、实际转写和响应事件；不修改生产桥接代码。

- [x] **Step 1: 核对锁定的 Qwen 部署版本和协议来源。** 在 NAS 只读采集 Gateway 镜像版本/digest、模型 profile、`semantic_vad_ec` 补丁是否仍在、GCP handshake/capabilities 和当前真实客户端事件列表。以 NAS 运行版本为准，不把 GitHub 当前 main 文档替代 2.1.0 源码。
- [x] **Step 2: 核对实际 DashScope Omni 文档和 Gateway 适配器。** 记录 Qwen3.8 16 kHz 输入、输出采样率、当前 turn_detection profile、VAD 与 Manual 模式差别；确认 Gateway 2.1.0 的客户端线上输入事件是 `input_audio_buffer.append`（内部归一化为 `audio.append`），不得向客户端宣称 `input_audio_buffer.commit` 已受支持。
- [x] **Step 3: 建立本地 VAD 真实结束边界样本。** 从既有测试音频/录音中取语音 PCM，按当前 ESP32 20 ms、640-byte 数据格式发送；分别测试本地 VAD speech_end 后追加不同长度的零值 PCM 尾帧。采样时长从短到长扫描，记录发出的 PCM byte 数/持续时间、Gateway `voice.state`、转写、`response.started`、`audio.delta`、`audio.done`。
- [x] **Step 4: 选定最短可靠静音尾帧。** 至少使用中文短句、长句、轻声、正常间隔、背景噪声样本进行重复测试；记录每组成功率、P50/P95 端点时间和失败日志。只有在尾帧能稳定触发服务端端点且没有把下轮/播放回声并入当前 turn 时才 PASS。
- [x] **Step 5: 验证助手最终文本和同一活动 socket 的即时续聊。** 在同一 GCP 7.0 WebSocket 上完成真实双轮语音输入/响应：第一轮测试要求模型确实向用户提出一个需要回答的问题，捕获 Gateway `transcript.final`，核对 `role=assistant`、匹配 turnId/responseId、`content` 保留中文全角 `？` 和英文 ASCII `?`；另测试普通陈述回复保留句号/其他非问号标点。第二轮在第一轮响应后不关闭 socket，继续经同一 socket 发送语音 PCM；确认 `session_id`/活动连接不变、turnId/responseId 更新，且模型能利用第一轮上下文回答。用户侧 transcript 的问号不得误判为助手意图。然后单独验证普通回答结束后关闭 socket，再用同一个 Qwen URL `sessionId` 和 `client.instance_id` 重连时 Gateway journal 是否恢复历史；另换 sessionId 验证会话隔离。只有第一种同 socket 路径作为 immediate follow-up 的强制实现路径；重连恢复是独立新 wake 的能力，不得替代前者。
- [x] **Step 6: 记录停止条件。** 若只能通过 Gateway 不支持的 commit 事件才能完成本地 turn，或静音尾帧方案在真实 Qwen3.8 上不可靠，停止后续代码迁移，提交最小失败证据和另行设计建议；不得先写入猜测的事件名。
- [x] **Step 7: RED/GREEN。** 把已验证的 VAD-tail、跨 WS session continuity、session isolation 和 lease 冲突场景固化为可重复探针/自动化测试，并重新运行探针验证。

**Acceptance:** 本地 VAD EOF 能触发 Qwen 服务端端点并得到非空用户 transcript/模型音频；同一活动 WebSocket 上可连续完成至少两轮语音 turn 并保留上下文；Gateway 输出的 assistant `transcript.final` 保留模型实际使用的中文 `？`、英文 `?` 和普通结束标点，事件带正确的 turnId/responseId；独立重连时的 journal 恢复结果有单独证据；新 session 不串话；没有发送未实现协议事件。未通过文本标点或同 socket 双轮验证时，B8.5/B8.6 不得启用问号续聊实现。

**B8.2 实测结果（2026-11-22）：PASS。** NAS 锁定镜像为 Qwen Audio Agent 2.1.0 / GCP 7.0.0，输入 16 kHz mono PCM16，实际输出 24 kHz。通过 20 ms / 640-byte 帧验证本地 VAD EOF 后静音尾帧；跨中文、英文、现有 STT WAV、50% 音量、500 ms 句中停顿和 18 dB SNR 背景噪声测试，统一候选尾帧取 1000 ms。25% 音量测试未形成 Provider speech turn，已列入报告限制。assistant transcript.final 的全角问号、ASCII 问号、普通句末标点均有真实事件证据。最终加强断言复跑通过：同一活动 WebSocket 三轮连续对话（含中间 tool response）、client_occupied lease 冲突、journal 断开重连恢复、新 session 隔离均得到自动化断言。HA 测试 592 passed，Sherpa Wyoming 140 passed，ESP32 host 117 passed / 1 个既有 device-status 模拟断言失败（单独复跑仍失败，未修改无关实现）；B8.2 自身 12 项单测和静态检查通过。HTTP PCM 预检发现试验桥接未传当前 MIC session_id、finish 队列 sentinel 有潜在阻塞、试验线性 SRC 不应复制，分别交 B8.5/B8.4 处理。详见 [B8.2 Qwen GCP 与 PCM 预检报告](../reports/2026-11-22-p6-8-b8-2-qwen-gcp-pcm-preflight.md) 和 [B8.2 Probe 代码审查](../reports/2026-11-22-p6-8-b8-2-probe-code-review.md)。本批没有修改 HA / ESP32 生产代码、NAS 持久配置或播放路径。

## B8.3 — Qwen Frontend MCP 直连 HA 与内网 HTTP 例外

**Files:**
- Qwen 2.1.0 source: `server/src/frontend/tools/mcp/frontend-mcp-config.mjs`（精确路径以 NAS 安装包为准）。
- Add to this repo: `deploy/nas/qwen/patches/` 中的可审查补丁/测试与部署说明（目录当前不存在时再创建）。
- Add: `deploy/nas/qwen/frontend-mcp.json.example` 和部署说明；只含 HA URL 占位值、环境变量引用和工具白名单样例，不含真实 Token。
- Tests: Qwen 2.1.0 MCP config policy tests；当前 HA `tests/homeassistant/custom_components/tivoo/test_tivoo_p4b5_mcp_http.py` 继续作为 HA endpoint regression。
- **本批只完成代码、配置模板和自动化测试；不把真实 MCP 配置写入 NAS 正在运行的 Qwen 容器。生产配置部署统一在 B8.7。**

**Interfaces:**
- Qwen Frontend MCP Client consumes the existing HA Assist MCP Streamable HTTP endpoint `/api/mcp/assist` (current candidate `http://192.168.3.94:8123/api/mcp/assist`; verify actual HA LAN URL/port at deployment).
- Authorization header uses `${HA_MCP_AUTHORIZATION}` sourced from Qwen container `config.env` (value is `Bearer <dedicated non-admin HA token>`).
- This deploys/configures the **Qwen-side MCP Client** against the existing HA MCP Server. Do not install a second HA MCP Server, proxy, service or Client Action.

- [ ] **Step 1: Define the non-secret Qwen MCP config template.** Use one named `homeassistant` server, Streamable HTTP transport, `${HA_MCP_AUTHORIZATION}` header reference, and placeholder-only URL/tool names. Document that the production URL and complete tool allowlist are filled from the NAS HA `tools/list` during B8.7; do not copy a development fixture as production truth.
- [ ] **Step 2: Verify Qwen 2.1.0 transport implementation.** Confirm its Frontend MCP client uses Streamable HTTP and supports Authorization headers. Locate the exact remote HTTP restriction in `frontend-mcp-config.mjs`; do not patch another file or globally disable URL validation.
- [ ] **Step 3: Add narrow private-LAN HTTP opt-in.** Add the explicit environment switch `QWEN_AUDIO_FRONTEND_MCP_ALLOW_PRIVATE_HTTP=true` (default disabled). Permit the configured RFC1918 LAN endpoint with Authorization header only when enabled; continue rejecting public/non-private HTTP and malformed URLs, preserve remote HTTPS and existing loopback behavior. Keep implementation small and use Node built-in address validation/range checks; do not add a new proxy or certificate system.
- [ ] **Step 4: Add config-policy RED tests.** Assert private LAN HTTP with Bearer header is accepted only with opt-in; remote public HTTP remains rejected; remote HTTPS remains accepted; invalid credentials/URL syntax still rejected.
- [ ] **Step 5: Finalize the reusable Frontend MCP config template.** Use `transport.type=streamable-http`, an HA Assist URL placeholder, `authorization: "${HA_MCP_AUTHORIZATION}"`, and explicit per-tool allowlist entries. Qwen's model-visible names use `mcp__<server>__<tool>`; underlying names must exactly match the real production `tools/list` captured later in B8.7. Keep token material outside JSON.
- [ ] **Step 6: Define the intended tool allowlist policy.** Use the HA P4 exposure/permission contract to identify which read and write capabilities the voice agent should receive; the example file stays placeholder-only, and the exact production tool names are filled only from the real NAS `tools/list` in B8.7. Respect Qwen's configured server/tool limits. Do not add duplicate GCP Client Actions or copy the LLM tool definitions into Qwen.
- [ ] **Step 7: Add local MCP integration tests.** Use a local/mock Streamable HTTP MCP server to verify `initialize`, `tools/list`, `tools/call`, exact environment reference expansion, allowlist filtering, result bounds, timeout and failure propagation. This tests the Qwen Frontend MCP path without changing NAS deployment or real Tivoo state.
- [ ] **Step 8: Verify Agent tool-result continuation in tests.** Exercise a frontend MCP tool call through the Agent ToolCallHandler test path; verify the tool result returns to the same model response flow and that intermediate tool-response audio completion does not close the user turn/output.
- [ ] **Step 9: Verify the security boundary in tests.** Private LAN HTTP with Bearer is accepted only with the opt-in; public HTTP remains rejected; HTTPS remains accepted; secrets are environment references only. Actual HA token rejection and live Qwen tool discovery/calls are B8.7 deployment acceptance, not B8.3.

**Acceptance:** Qwen v2.1.0 has a tested Frontend MCP Streamable HTTP path, private-LAN HTTP is opt-in, config template and exact tool allowlist structure are documented, mock MCP discovery/call/continuation tests pass; no HA MCP implementation changes and no production NAS MCP configuration is applied in this batch.

## B8.4 — ESP32 对 24 kHz Qwen PCM 的本地 SRC

**Files:**
- Modify: `esp32/firmware/main/audio_playback.c`, `audio_playback.h`, `audio_resource.c` only where necessary.
- Tests: existing `tests/esp32` host tests and firmware target build fixtures; add focused raw-PCM SRC tests.
- Reuse: existing `esp_ae_rate_cvt_open/process/get_max_out_sample_num/close` path and the existing 32 kHz output queue.

**Interfaces:**
- Input: raw signed 16-bit little-endian mono PCM at the sample rate declared in the HTTP MIME / TTS_PLAY request; Qwen 3.8 current expected output is 24 kHz, verified from actual `audio.delta.sampleRate`.
- Output: existing 32 kHz mono output queue / I2S bus; preserve existing playback_id, session_id, stop and completion receipts.

- [ ] **Step 1: Add RED format tests.** Validate that existing 32 kHz MIME remains byte-for-byte passthrough; add a 24 kHz raw PCM format case; reject unsupported rates, misaligned sample bytes and MIME/rate mismatches.
- [ ] **Step 2: Implement stateful raw PCM SRC.** Reuse the existing ESP Audio Effects SRC state for the raw PCM path; do not add a new resampler library. Carry SRC state across arbitrary HTTP chunk boundaries and flush/close only at the matching stream EOF.
- [ ] **Step 3: Verify exact output duration and continuity.** Feed silence, constant level, impulse and swept/representative speech fixtures in irregular chunk sizes; assert the 24 kHz input yields the expected 32 kHz output duration and no discontinuity caused by resetting SRC per HTTP chunk.
- [ ] **Step 4: Verify cancellation and generation fencing.** Stop a 24 kHz playback while streaming; ensure old SRC state/buffer cannot enqueue samples into the next playback generation.
- [ ] **Step 5: Run ESP32 host tests and clean builds.** Build the current S3/Classic targets with locked ESP-IDF v6.1; capture flash manifest and test output. Do not flash hardware in this batch.

**Acceptance:** 24 kHz PCM is converted to 32 kHz by existing ESP Audio Effects SRC, 32 kHz compatibility is unchanged, chunk boundaries do not reset the converter, and old generations cannot leak PCM.

## B8.5 — HA Qwen Realtime Bridge（替换 STT/LLM/TTS 入口）

**接入前门禁及验收补充：** 先核销合同矩阵 §2.1 的正常终态可观测性；未通过保持 HOLD，不臆造 GCP 字段。Step 2/3/7/8 同时覆盖早端点与同 MIC 多 turnId、playback.clear、满队列/无 GET/断连清理、工具中间响应和晚到最终文本。只补既有 bridge 的边界测试，不新增服务或状态机。

**Files:**
- Create: `homeassistant/custom_components/tivoo/qwen_realtime.py` by adapting the verified test-branch bridge, not blind cherry-picking.
- Modify: `homeassistant/custom_components/tivoo/__init__.py`, `assist_satellite.py`, and only the existing transport/resource code needed for Qwen raw PCM delivery.
- Tests: add `tests/homeassistant/custom_components/tivoo/test_qwen_realtime.py`; extend current audio session and satellite lifecycle tests.

**Interfaces:**
- Consumes: current HA `AudioSessionManager.audio_subscription()`, local wake turn, prompt completion boundary, 16 kHz mono S16LE PCM and the B8.2-verified VAD end tail.
- Produces: Qwen GCP 7.0 input audio stream and final transcript/tool/audio lifecycle events. Existing ESP32 `TTS_PLAY` control channel remains the handoff; HA production code currently has no generic Qwen raw PCM HTTP resource, so B8.5 must implement and test the bounded resource before specifying its actual route.
- Qwen HTTP output format is selected from the actual Gateway `audio.delta.sampleRate`; the ESP32 already accepts the existing 32 kHz raw-PCM MIME, while non-32 kHz input requires the B8.4 SRC extension. HA still needs the new B8.5 bounded PCM HTTP resource for Qwen output at either rate.

- [ ] **Step 1: Add RED tests for the GCP handshake.** Assert `session.hello` uses protocol 7.0.0, stable client type/version/instance_id, `input.audio` and `session.heartbeat` capabilities, and locale; verify `session.ready` then `voice.ready` ordering, sample-rate validation, auth header, correlated `session.ping`→`session.pong` handling and Gateway error handling.
- [ ] **Step 2: Add RED tests for input PCM.** Verify exactly the current local turn's PCM is sent using GCP client event `input_audio_buffer.append` (Gateway internal alias: `audio.append`), in 16 kHz S16LE, with the B8.2-verified silence tail after local speech EOF. Never send pre-wake audio, prompt playback echo or the next turn's PCM.
- [ ] **Step 3: Add RED tests for output PCM.** Verify Gateway `audio.delta` chunks are base64 decoded, sample rate validated, and queued unchanged for the corresponding raw-PCM HTTP stream; no linear-interpolation resampler in HA. Bound the queue and surface producer/consumer backpressure failures.
- [ ] **Step 4: Preserve current ESP32 handoff.** Reuse existing random playback UUID, HTTP stream, `TTS_PLAY`, `AUDIO_STOP`, `playing/completed/failed` events and output-owner fencing. Include the current P6.8 device `session_id` in playback and stop operations wherever the current transport contract requires it.
- [ ] **Step 5: Adapt the test-branch bridge.** Carry forward only GCP handshake, PCM bridge, bounded HTTP PCM stream, diagnostic timing and the already-fixed tool-response continuation. Rework all lifecycle assumptions to match the active P6.8 local-wake session API.
- [ ] **Step 6: Integrate the bridge into the HA Satellite runner.** After the existing local wake and ready prompt gate, call the Qwen bridge instead of `async_accept_pipeline_from_satellite()`. The P6.8 Assist Satellite remains the owner of current turn, Context/generation, audio ingress, cancellation and public entity state; do not run the old STT/Intent/TTS pipeline in parallel or silently fall back to it.
- [ ] **Step 7: Validate Qwen response sequencing.** Test assistant `transcript.delta`/`transcript.final` including role, turnId, responseId and exact final punctuation preservation; user transcript must remain role=user. Test response.started, audio.delta, tool.call, intermediate audio.done, final audio.done and errors. A tool-bearing response's audio.done must not finish the user turn or close the HTTP PCM output; only the final user-facing assistant transcript is eligible for Qwen follow-up intent, and matching physical ESP32 completion remains required.
- [ ] **Step 8: Verify resource cleanup and conditional socket retention.** On output failure, WebSocket error, input timeout, cancellation, unload and HTTP consumer disconnect, close streams/remove registry entries/release socket exactly once. On a successful final response without follow-up, close the Gateway socket after matching physical playback completion. When the final transcript arms follow-up, keep the current socket alive through playback completion, the 4-second device gate and the next user input/response; close it only when that follow-up chain ends or times out. Do not close at `audio.done`.

**Acceptance:** one local-wake turn reaches Qwen without calling Sherpa STT/AstrBot/HA TTS; Qwen's final voice output reaches the existing ESP32 playback owner; errors and cancellations release all resources.

## B8.6 — HA 会话身份、打断、显示事件与 follow-up 生命周期

**验收补充：** Step 4/5/8 按合同矩阵 §2.1 测试已授权 follow-up 的旧轮 retire 与原 socket 移交、迟到事件隔离、移交失败收口，以及 suspend/deactivated 不自行重新开麦；不增加设备控制消息或会话管理层。

**Files:**
- Modify: `homeassistant/custom_components/tivoo/assist_satellite.py`, `qwen_realtime.py`, and the smallest required display/playback callback surface.
- Tests: extend `test_assist_satellite.py`, `test_p68_lifecycle.py`, `test_p68_display.py`; add Qwen lifecycle-focused tests.

**Interfaces:**
- Qwen URL 的 `sessionId` 使用当前 `ConfigEntry.entry_id` 的稳定映射；HA `Context.id` 仍是每轮新建的 turn/generation；ESP32 `session_id` 和 playback UUID 保持独立。当前 Tivoo AssistSatellite 不调用 HA ChatSession。
- Qwen `client.instance_id` 固定为 `tivoo-<ConfigEntry.entry_id>`，跨 turn / reconnect 不变；Gateway owner 由现有 Gateway access-token 决定。**immediate follow-up 必须在原活动 WebSocket 上继续；仅普通回复结束、follow-up gate 超时或错误收口时才关闭连接。** 独立 wake 的重连恢复已由 B8.2 预检验证，生产接入仍须回归。

- [ ] **Step 1: Add RED session mapping tests.** Two independent local-wake conversations under the same ConfigEntry reconnect with the same Qwen sessionId and stable client.instance_id; verify journal/history recovery separately from same-socket follow-up; a different ConfigEntry must use a different sessionId. Do not invent HA ChatSession or conversation ULID behavior.
- [ ] **Step 2: Add RED owner/connection tests.** Same instance reconnect replaces its stale Gateway socket; different same-owner client gets the expected occupied result. Handle Gateway heartbeat ping/pong and negotiated capabilities; never start a second active Client intentionally.
- [ ] **Step 3: Map Gateway events to existing HA lifecycle.** Qwen user transcript-final marks the current turn as accepted/thinking; Qwen tool.call received/running/completed/failed maps to current generation's tool-use state; assistant response starts speaking only when the matching ESP32 playback is actually playing; physical completed remains the authoritative playback terminal.
- [ ] **Step 4: Add RED interruption tests.** During Qwen response generation, during MCP execution, and during ESP32 playback, a new valid local wake must stop/retire only the old response/playback, send the supported GCP 7.0 `response.cancel` event when the old socket is still usable, then close/join the old Gateway session connection (closing the connection is required to abort the connection-scoped MCP tool signal) and start the newest turn only after the existing P6.8 cleanup barrier. Late transcript/audio/tool/display events from the old generation must be ignored.
- [ ] **Step 5: Implement the Qwen follow-up contract.** Use the selected project policy in [Qwen Realtime 条件续聊设计](../specs/2026-11-22-p6-8-qwen-realtime-followup-design.md)：只处理当前 generation 的 assistant `transcript.final`；对 `content.rstrip()` 判断是否以 `？`/`?` 结尾，赋值到现有 per-turn follow-up 布尔字段（优先复用 `_Turn.continue_conversation`，不新增第二套状态机）。`transcript.delta`、用户转写、`tool.call`、`audio.done`、`voice.state=idle` 均不作为授权。问号只 arm；必须等待匹配 playback_id 的 ESP32 `AUDIO_STATE=completed`，并满足现有输入 drain、正常响应和无错误条件后，复用 `AudioSessionManager.grant_followup()` 与 `TYPE_FOLLOWUP_OPEN (0x27)`，只打开一次现有 4 秒 local_followup gate。设备创建新 MIC UUID，HA 创建新 Context/generation；但 Qwen 输入必须继续使用原活动 Gateway WebSocket，不要按 follow-up 重连。普通标点、缺失文本、失败、取消或超时默认不续聊。旧 AstrBot/Pipeline 路径的 `INTENT_END.continue_conversation` 逻辑保持不变。
- [ ] **Step 6: Preserve HA as state and service authority.** Qwen MCP tools call HA only; HA validates/service-routes each call and retains the current display/screen/playback owners. The model cannot emit raw SPP, raw wire frames or a new parallel display state.
- [ ] **Step 7: Resolve mood/tool correlation.** Retain the B8 `SetMood` validation and unassociated-MCP-call limitation. Do not invent a Context ID from Qwen call_id or modify the public SetMood schema unless B8.1 explicitly changes the contract.
- [ ] **Step 8: Verify restart and disconnect.** HA integration unload/reload, Gateway restart, device diagnostic disconnect, Gateway lease replacement and a network outage must return the satellite to the existing idle/ready state without stale playback, leaked streams or stale Qwen session binding.

**Acceptance:** HA remains the single turn/display/physical-output owner; turns under the same ConfigEntry retain Qwen context; immediate follow-up uses the same active Gateway WebSocket, while new HA Context/MIC UUID/turnId identities remain separate; distinct ConfigEntries isolate context; question-mark policy only arms once and requires matching physical playback completion before the existing 0x27/4-second gate; failures/interruption/timeout fail closed; legacy AstrBot continuation behavior is unchanged.

## B8.7 — 迁移端到端验收、NAS 部署与 B9 放行

> **HA MCP 部署范围：** HA 侧 `/api/mcp/assist` 服务在 P4 已实现，本批不重复部署或修改 HA MCP Server。B8.7 负责把 Qwen Audio Agent 2.1.0 的 Frontend MCP Client 配置持久化部署到 NAS，并使用专用 HA 用户 Token 连接现有服务。当前 NAS health 仍是 `servers=[]`、`tools=0`；只有本批完成实际配置、Gateway 重启、工具发现及调用验证后，才算 Qwen↔HA MCP 部署完成。

**Files:**
- Add/update: `docs/superpowers/reports/2026-11-22-p6-8-qwen-realtime-acceptance.md`.
- Update NAS deployment files only after a pre-deployment backup and review of the actual running Compose mounts.
- Update tests and Qwen deployment patch/config references in this repo; do not store runtime secrets.

- [ ] **Step 1: Run focused local regressions.** HA Tivoo unit/integration tests; Qwen bridge/HTTP PCM tests; Qwen 2.1.0 MCP configuration policy tests; ESP32 host SRC/resource tests; both target clean builds.
- [ ] **Step 2: Run no-legacy-call assertions.** A local-wake voice turn must not open Wyoming Transcribe, use the old Sherpa STT entity, call AstrBot SSE, invoke AstrBot Stop, or request Matcha/HA TTS. Keep wake and PCM transport tests active.
- [ ] **Step 3: Back up and inspect the real NAS deployment before MCP installation.** Back up the active Qwen Compose/deployment definition, `/root/.config/qwaudio/config.env`, any existing Frontend MCP JSON, current image digest and container mount mapping. Preserve secrets in a permission-restricted backup; do not print or copy their values into logs/Git. Confirm the persistent config volume currently mounted at `/root/.config/qwaudio` and re-confirm the HA LAN URL/port at deployment time.
- [ ] **Step 4: Capture the actual HA production tools/list.** Use a dedicated non-admin HA account/token against the actual `/api/mcp/assist`; record exact tool names, descriptions, input schemas and read/write capabilities. Check which Tivoo tools are exposed to that user. Build the production allowlist from this result only; never guess names or assume the development fixture's 34 items are the production list.
- [ ] **Step 5: Install the real Qwen Frontend MCP config into the persistent Qwen config volume.** Create `/root/.config/qwaudio/frontend-mcp.json` with version 1 and one enabled `homeassistant` Streamable HTTP server. Set its URL to the verified HA `/api/mcp/assist` LAN URL; use `headers.authorization` as `${HA_MCP_AUTHORIZATION}`; enable only exact tool names from Step 4. Do not put the Bearer token into JSON. In the persistent `/root/.config/qwaudio/config.env`, set `QWEN_AUDIO_FRONTEND_MCP_CONFIG=/root/.config/qwaudio/frontend-mcp.json`, `HA_MCP_AUTHORIZATION=Bearer <dedicated HA user token>`, and `QWEN_AUDIO_FRONTEND_MCP_ALLOW_PRIVATE_HTTP=true` (the opt-in introduced and tested in B8.3). Preserve existing DashScope settings and `semantic_vad_ec` patch. Restrict permissions on the credential-bearing `config.env`; JSON contains no secrets.
- [ ] **Step 6: Apply and verify the running Gateway configuration.** Restart the Qwen Gateway using the NAS deployment's existing restart mechanism. Confirm the effective Frontend MCP config path, health status reports the `homeassistant` server initialized and nonzero discovered tools, and startup logs report no URL/auth/discovery errors. Verify the exposed model tool names correspond to the production allowlist. Do not treat `servers=[]` / `tools=0` as success.
- [ ] **Step 7: Verify live Qwen↔HA MCP calls.** Through a real Qwen model response, call an exact read-only tool discovered in Step 4 (for example GetLiveContext only if that exact name is present); inspect the structured result and confirm Agent tool-result continuation produces a final spoken answer. Then call one controlled non-destructive Tivoo tool. Separately verify an unauthenticated/invalid HA request is rejected without replacing the valid production token. Confirm WebUI voice does not occupy the same Gateway owner.
- [ ] **Step 8: Verify actual device end-to-end.** Local wake → ready prompt completion → 16 kHz input → Qwen transcript → Qwen direct HA MCP tool call → tool result continuation → 24 kHz PCM output → ESP32 native 24→32 kHz SRC → actual Tivoo AUX playback completed. Record Qwen/HA/ESP32 timing with the same monotonic clock domains or an explicit synchronization method.
- [ ] **Step 9: Verify conversation/lifecycle scenarios.** Multi-turn same conversation; final assistant transcript ending in `？`/`?` opens only one follow-up after matching physical playback completion; ordinary punctuation does not; question mark in user transcript or transcript.delta does not; tool-call intermediate response does not but final post-tool assistant question does; missing/failed/interrupted assistant final text defaults closed; no-response timeout; response containing multiple tool calls; response tool failure; long TTS; barge-in during generation and playback; same active WebSocket survives through playback/gate/next input; Gateway restart/reconnect; HA reload; ESP32 disconnect.
- [ ] **Step 10: Verify rollback.** Restore the backed-up Qwen `config.env`, Frontend MCP JSON, private-HTTP patch/config, HA integration and Qwen image as appropriate. Verify `frontendMcp` returns to the pre-deployment state when the config path/env entries are reverted, no unintended credentials remain active, and the old stack can be re-enabled until B9 retires it. Ensure no ESP32 firmware rollback is required unless B8.4 is separately hardware-accepted.
- [ ] **Step 11: Install and verify the P6.8 Prompt overlay and persona/memory persistence.** From the exact deployed Qwen 2.1.0 image, copy its complete `config/frontend-agent/PROMPT.md` into a persistent custom prompt directory, append the P6.8 follow-up policy fragment from [Qwen Realtime 条件续聊设计](../specs/2026-11-22-p6-8-qwen-realtime-followup-design.md), set `QWEN_AUDIO_AGENT_FRONTEND_PROMPT_DIR` to that directory and restart Gateway. Verify the active Prompt path, overlay text/hash and <=16,000-character limit. Do not replace the full Prompt with the fragment and do not put this runtime rule only into `ASSISTANT.md`. Also verify `ASSISTANT.md`, `USER.md` and `MEMORY.md` remain persistent; do not import AstrBot records or memory.
- [ ] **Step 12: Report each result honestly.** Separate software PASS, NAS service PASS and actual hardware PASS/GAP; keep missing hardware or production tests as GAP. Do not mark B9 ready if any required response, audio, MCP, owner, cancellation or follow-up contract is unverified.

**B9 release gate:** B8.1–B8.7 accepted; Qwen tool calls through HA work; real device Qwen audio playback and interruption are verified; rollback is tested. B9 remains a separate user-authorized batch.

---

## B9 overlay — 原条件清理批次的增补范围（保留原有其他任务）

原 `2026-11-18-p6-8-b1-b10-execution-plan.md` 的 B9 T09 所有条件清理任务仍保留，另增加以下迁移清理；不可把本节当作 B9 已完成：

- [ ] **AstrBot：** B8.7 通过后，移除 HA 的 AstrBot Conversation Agent/自定义集成、phase event 监听、SSE/Stop 专用调用和对应运行时配置；停止/移除 AstrBot 容器与专用网络/挂载。用户已明确不需要其会话、记忆或人格，因此不迁移这些数据。保留历史设计/验收报告作为历史记录，不将它们当作仍需运行的依赖。
- [ ] **Sherpa/Wyoming：** Tivoo 不再使用 Sherpa 的 STT/TTS/Wake Provider；继续执行原 T09 的实际 HA Pipeline、Wyoming entry、其他客户端和容器 consumer 盘点。若无其他消费者，停用/删除该容器、模型和 10400 配置；若存在其他消费者，仅解除 Tivoo 的绑定并保留共享服务，不破坏其他客户端。
- [ ] **HA 配置：** 删除/停用仅为旧 STT/LLM/TTS 链路创建的 Tivoo 专用 Pipeline/Provider 选择和旧 provider 环境变量；保留未迁移的全局 HA Voice Pipeline、实体与其他客户端兼容性。
- [ ] **回归：** 移除旧架构专属测试前，将仍有通用价值的 wake、音频资源、取消、设备服务和播放所有权断言迁移到 Qwen 测试；不得为通过测试而删除仍适用的 P6.8 断言。

## B10 overlay — 综合验收变化（保留原有其他任务）

- 原 B10 的两块固件、双麦/AFE、UART/SPP、设备断线/重启、显示/息屏/mood、压力、延迟和历史合同逐行核销全部保留。
- 语音综合路径改为本地 WakeNet/VAD → HA turn/PCM ingress → Qwen GCP → Qwen Frontend MCP → HA Services/Tivoo → Qwen Realtime output → HA PCM stream → ESP32 SRC/播放。原来专属于 AstrBot 的 SSE/Stop 与 Sherpa STT/TTS Provider 检查，替换为 Qwen Gateway response/tool/session/lease/cancel 及 HA MCP 验收。
- 若 Sherpa 被保留给其他消费者，仍运行其适用的独立服务测试；若容器被 B9 移除，不再把它列为 Tivoo 生产依赖或部署验收项。
- P6.8 除语音出入口迁移外的全部历史要求、新合同和物理 GAP 继续按原 B10 计划核销，不因 Qwen 迁移而自动 PASS。

## 官方协议和锁定版本源码依据

以下链接用于执行时重新核验接口，不以本文摘要替代原始规范：

- [Alibaba Cloud Qwen-Omni-Realtime WebSocket 文档](https://help.aliyun.com/en/model-studio/realtime)：16 kHz PCM 输入、24 kHz PCM 输出；VAD 模式由服务端端点触发响应，Manual 模式需要 commit/committed/response.create。
- [Qwen Audio Agent v2.1.0 Gateway Protocol](https://github.com/QwenAudio/qwen-audio-agent/blob/v2.1.0/docs/gateway-protocol.md)：GCP 7.0 握手、owner 单活动 Client、stable instance reconnect、heartbeat、客户端音频输入事件。
- [Qwen v2.1.0 Gateway client event names](https://github.com/QwenAudio/qwen-audio-agent/blob/v2.1.0/shared/protocol/realtime-events.mjs)：核对 GCP 客户端事件集合；不可把 DashScope provider event 当作 GCP client event。
- [Qwen v2.1.0 Gateway transport](https://github.com/QwenAudio/qwen-audio-agent/blob/v2.1.0/server/src/transport/gateway-client-transport.mjs)：确认 query `sessionId`、owner/session scope、replay buffer 与 Gateway session runtime 的构造。
- [Qwen v2.1.0 Frontend MCP 配置规范](https://github.com/QwenAudio/qwen-audio-agent/blob/v2.1.0/docs/reference/frontend-mcp.md) 与 [配置实现](https://github.com/QwenAudio/qwen-audio-agent/blob/v2.1.0/server/src/frontend/tools/mcp/frontend-mcp-config.mjs)：Streamable HTTP、header environment reference、explicit tool allowlist 和 remote HTTP policy。
- [Qwen v2.1.0 Frontend MCP client](https://github.com/QwenAudio/qwen-audio-agent/blob/v2.1.0/server/src/frontend/tools/mcp/frontend-mcp-client.mjs)：核对真实 transport 与 Authorization header 传递。
- [Qwen v2.1.0 ConversationSync](https://github.com/QwenAudio/qwen-audio-agent/blob/v2.1.0/server/src/conversation/conversation-sync.mjs)、[Session conversation history](https://github.com/QwenAudio/qwen-audio-agent/blob/v2.1.0/server/src/app/session-conversation-history.mjs) 和 [Session journal](https://github.com/QwenAudio/qwen-audio-agent/blob/v2.1.0/server/src/session/session-journal.mjs)：验证同 owner/session 跨 socket 的会话恢复依据。
- [Qwen v2.1.0 Memory Provider 文档](https://github.com/QwenAudio/qwen-audio-agent/blob/v2.1.0/docs/reference/memory-provider.md)：`ASSISTANT.md`、`USER.md`、`MEMORY.md` 和可替换存储接口。
- 本项目 HA 侧 MCP HTTP 回归：[test_tivoo_p4b5_mcp_http.py](../../../tests/homeassistant/custom_components/tivoo/test_tivoo_p4b5_mcp_http.py)；AssistSatellite 的当前 Context/turn 语义以现有 `assist_satellite.py` 和 HA Core 2026.11.0 源码为准。当前集成未使用 HA ChatSession。

**版本边界：** 上述 Qwen GitHub 文件固定到 v2.1.0 tag；官方 Alibaba 文档是当前在线文档，实施时仍需对照 NAS 当前模型、Workspace endpoint 和实际返回的 Gateway events。若 NAS 不是 v2.1.0 或模型 profile 不一致，先更新技术预检，不得直接照搬配置。
