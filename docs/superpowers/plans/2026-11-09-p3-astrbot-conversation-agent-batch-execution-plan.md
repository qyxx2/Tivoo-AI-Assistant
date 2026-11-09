# P3 AstrBot Conversation Agent — Task Batch Execution Plan

> 状态：P3b0 已完成；P3b1–P3b6 尚未开始。
> 本文件是 P3 的当前执行合同，细化主 Implementation Plan 的依赖、文件边界、测试顺序和退出门。
> 规划阶段未创建实现；各批次实际执行状态以本文件和 `.superpowers/sdd/2026-11-09-p3-astrbot-conversation-agent/progress.md` 为准。

## 1. Branch and baseline

- Branch：feature/p3-astrbot-conversation-agent
- Base：main，commit c754f5a22727fa0ded6a2fd0c309c967b162097d
- 当前工作树从该基线切出，计划文档提交保留在此分支。
- 每个后续实现 Batch 在此分支独立提交；不自动 push、merge 或修改 main。
- 规划阶段的提交只包含主 Implementation Plan、本文及 .gitignore 的 Superpowers 状态目录规则；后续每个实现 Batch 在此分支独立提交。

## 2. Authority and preconditions

权威顺序：

1. docs/superpowers/specs/2026-11-09-p3-astrbot-conversation-contract-matrix.md：唯一 P3 接口合同。
2. docs/superpowers/plans/2026-11-09-p3-astrbot-conversation-agent-implementation-plan.md：P3 架构、全局约束和主任务顺序。
3. README.md §2–§4、§10：项目总体职责、P3 所在阶段和上下游边界。
4. docs/superpowers/specs/2026-11-09-stt-tts-end-to-end-pipeline-spec.md：P3 文本流与 P5 TTS 流式输入边界。
5. docs/superpowers/specs/2026-11-09-esp32-ha-bidirectional-communication-design.md：仅用于禁止把设备通信工作混入 P3。

进入 B0 前置条件：

- 当前分支必须是 feature/p3-astrbot-conversation-agent，HEAD 必须包含已提交计划基线。
- 重新核对 HA Core 2026.11.0 和 AstrBot 4.29.4 实际运行版本。若版本不符，先核对源代码差异并更新 P3 合同，不得带着未经确认的接口假设开始实现。
- 明确可用的 HA Core 测试环境与兼容的 pytest 方案；不为本地测试直接复制一份完整 HA 运行时到项目中。
- 真实部署验收需要用户提供/录入专用 AstrBot OpenAPI Key、key_id 和 Base URL。密钥只能从 HA Config Flow 录入，不写入本仓库和测试日志。
- 本阶段不要求登录 Tivoo、ESP32、Wyoming 容器或 HA 设备实体。

## 3. Batch overview and dependencies

| Batch | 目标 | 依赖 | 主要交付 |
|---|---|---|---|
| B0 | HA 集成基线、测试环境和 Config Flow | 无 | 可加载的 astrbot 集成配置入口 |
| B1 | 单用户身份与 session Store | B0 | 稳定 username、UUIDv4、24h 滑动空闲期限 |
| B2 | AstrBot HTTP OpenAPI Client | B0、B1 | Chat/stop 请求合同与 HTTP 错误识别 |
| B3 | 增量 SSE Parser | B2 | 事件分类、可见文本增量和严格结束语义 |
| B4 | HA ConversationEntity 与 ChatLog | B1、B2、B3 | conversation.astrbot、真实 ChatLog 流式响应和标准结果 |
| B5 | 取消、串行化和协议异常收口 | B4 | session stop owner 匹配、无重复提交、并发隔离 |
| B6 | P3-T01 至 T16 集成验收 | B0–B5 | 完整合同覆盖和部署验收证据 |

顺序说明：

- B1 可在 B0 后独立完成；B2 消费 B1 的稳定 username/session_id；B3 消费 B2 返回的流式响应。
- B4 只组合已测试的 Session/API/SSE 边界，不复制协议解析逻辑。
- B5 必须在 B4 的真实调用生命周期上验证，特别是 session 级 stop 与串行请求的交互。
- B6 只做集成、复核和验收，不借验收批次增加 P4/P5/P6 功能。

## 4. Batch 0 — HA integration baseline and Config Flow

**Purpose:** 确认实际 HA 2026.11.0 集成入口和测试方式，建立最小的独立 astrbot 集成与配置入口。此 Batch 不发送模型请求，不实现对话流。

**Files:**
- Create: homeassistant/custom_components/astrbot/manifest.json
- Create: homeassistant/custom_components/astrbot/__init__.py
- Create: homeassistant/custom_components/astrbot/const.py
- Create: homeassistant/custom_components/astrbot/config_flow.py
- Create: homeassistant/custom_components/astrbot/translations/en.json（HA 运行时实际读取的自定义集成本地化文件）
- Create: requirements_test.txt、pytest.ini、scripts/test-ha.sh（固定本地 HA 测试环境和入口）
- Tests: tests/homeassistant/custom_components/astrbot/test_config_flow.py

**Tasks:**
- [x] 核对实际 HA Core 版本与 2026.11.0 Config Entry/ConversationEntity 开发接口；确认 AstrBot 运行源码版本为 4.29.4。
- [x] 检查开发机 Python 3.14.4 和空白测试目录；固定 `pytest-homeassistant==2026.11.0`（其依赖 HA Core 同版）及 `ruff==0.17.4`，通过 `scripts/test-ha.sh` 在 Ubuntu 本地运行。
- [x] 先写 Config Flow / manifest / setup 失败测试；RED 阶段确认集成缺失导致测试失败，再实现使其通过。
- [x] 实现 domain=astrbot、Config Entry setup/unload 和最小 metadata。集成独立于 custom_components/tivoo。
- [x] Config Flow 保存 AstrBot Base URL、API Key secret 和 API Key key_id 三项；username 不提供输入项，由后续批次按合同自动派生。
- [x] 校验 HTTP(S) Base URL、端口、凭据、query/fragment 和 `/api/v1/chat` 后缀；不在 Config Flow 中触发真实模型请求。
- [x] 表单明确要求使用专用 `chat` scope API Key；B0 不在线检查 Key scope 或 owner 身份，实际鉴权/username 一致性留给 B2/B6；不申请 `chat:admin`。
- [x] 运行 B0 聚焦测试、HA 集成加载测试、Ruff lint/format 和 `git diff --check`。

**Exit gate:**
- HA 可创建并加载/卸载 astrbot Config Entry；配置由 HA Config Entry 机制持久化。
- 三项配置正确保存；secret 使用 PASSWORD selector 且不进入日志；username 不允许单独配置。
- 本地测试环境固定且与 HA 2026.11.0 兼容。
- 未创建 ConversationEntity stub、HTTP 客户端或任何 P4/P5/P6 功能。

**Commit:** chore(p3): add astrbot integration config flow

**B0 verification (2026-11-09):** Ubuntu 本地 `./scripts/test-ha.sh -q`：17 passed；Ruff check/format：passed。NAS 仅用于核对运行版本，没有在 NAS 上运行测试；未录入真实 OpenAPI Key，也未发起 AstrBot Chat 请求。

## 5. Batch 1 — Single-user session identity and Store

**Purpose:** 在任何 HTTP 实现前固定 session 生命周期，防止 HA 短期 conversation 与 AstrBot 长期 session 混用。

**Files:**
- Create: homeassistant/custom_components/astrbot/session.py
- Modify: const.py / __init__.py，仅接入 Store 初始化和配置身份变化。
- Tests: session manager 单元测试、HA Store 重启恢复测试。

**Tasks:**
- [ ] 先写 username 派生测试：唯一身份必须是 api_key:<key_id>；不得使用 HA context.user_id、HA conversation_id、显示名或设备 ID。
- [ ] 先写 UUIDv4、首次创建、未满 24 小时复用、达到/超过 24 小时轮换的测试。
- [ ] 先写 Store 数据结构测试：version、api_key_id、username、session_id、created_at、last_activity_at；不允许持久化用户消息或 Assistant 正文。
- [ ] 先写 HA 重启恢复和 HA conversation_id 变化测试；验证未过期时仍复用同一 AstrBot session_id。
- [ ] 先写身份变化测试：Base URL/key_id 改变时重新生成；仅替换同一 key_id 的 secret 不重置会话。
- [ ] 先写 agent_stats / token 统计 / 上下文压缩不触发轮换的回归测试。
- [ ] 实现最小 Store manager。候选 session 可先在内存生成；仅在符合合同的 AstrBot session_id 接受确认后写入/更新活动记录。
- [ ] 对旧版本、损坏、缺失字段或身份不匹配记录进行明确恢复；不尝试修补并复用来源不明的 session_id。
- [ ] 运行全部 session 聚焦测试和 B0 回归。

**Exit gate:**
- P3-T04 至 T07 的会话身份和生命周期行为由自动化测试覆盖。
- 连续多轮、HA conversation_id 换新和 HA 重启都不会在 24 小时窗口内误建新会话。
- 仅最近活动达到 24 小时、Base URL 变化或 key_id 变化触发轮换；上下文压缩不触发。
- 无聊天内容持久化。

**Commit:** feat(p3): persist single active AstrBot session

## 6. Batch 2 — AstrBot HTTP OpenAPI Client

**Purpose:** 完成固定请求和 HTTP 响应识别，仍不把 SSE 事件解析或 ChatLog 写入混在 HTTP 层。

**Files:**
- Create: homeassistant/custom_components/astrbot/api.py
- Modify: const.py / config_flow.py only if validated request settings require it.
- Tests: HTTP client tests with fake HA aiohttp session and streaming response fixtures.

**Tasks:**
- [ ] 先写 POST 路由、headers、body 的合同测试。
- [ ] 验证请求只有 username、session_id、message、enable_streaming=true；message 原样传入；不发送 locale、config_id、config_name、platform_id 或 HA conversation_id。
- [ ] 验证 Bearer API Key、Accept: text/event-stream、Content-Type: application/json；secret 不出现在 URL、query、日志或异常字符串。
- [ ] 通过 HA 共享 aiohttp ClientSession 发送请求；不在每次对话中创建 ClientSession，不添加 HTTP 依赖。
- [ ] HTTP 响应先检查状态和 Content-Type，再交给 SSE 层。正确区分 401、403、其他非 2xx、200 JSON error envelope 与 text/event-stream。
- [ ] JSON error envelope 即使在 HTTP 200 时也必须作为失败；不得把它交给 SSE parser。
- [ ] stop API path 固定为 POST /api/v1/chat/sessions/{session_id}/stop，认证使用同一 API Key；停止调用具体时机由 B5 负责。
- [ ] 测试 transport failure 不会触发 Chat POST 自动重试。
- [ ] 运行 API Client 聚焦测试及 B0/B1 回归。

**Exit gate:**
- P3-T03、T12 的 HTTP 合同和认证失败分支覆盖。
- 共享 HA aiohttp session 被复用；没有独立 HTTP owner 或新增运行时依赖。
- 网络失败、HTTP 错误和 JSON error envelope 具有不同诊断类型；不自动重发原始 Chat POST。

**Commit:** feat(p3): add AstrBot OpenAPI client

## 7. Batch 3 — Incremental AstrBot SSE Parser

**Purpose:** 把 AstrBot 4.29.4 实际 SSE 事件转换成有限、严格、有序的内部事件，不直接耦合 HA ConversationEntity。

**Files:**
- Create: homeassistant/custom_components/astrbot/sse.py
- Tests: SSE parser unit tests using fragmented byte streams and event fixtures.

**Tasks:**
- [ ] 先写分段网络数据测试：data 行被任意切开、CRLF、空行 frame separator、heartbeat comment 和最后一帧缓冲。
- [ ] 第一条数据事件必须为 session_id，且响应 session_id 必须与本次请求一致；run_id/message_id 不得作为会话 ID。
- [ ] 解析 plain：chain_type 为空或普通文本时产生可见 delta；reasoning、tool_call、tool_call_result 一律过滤。
- [ ] 忽略 user_message_saved、message_saved、agent_stats 和 heartbeat；这些元数据不得进入 ChatLog。
- [ ] end 是唯一正常结束标记；error 是失败终止；未收到 end/error 的 EOF 视为不完整响应。
- [ ] 未知事件、非法 JSON、字段类型错误作为协议异常；不静默跳过未知数据。
- [ ] 图片/文件/音频/actionrow 等非文本事件不进入 P3 文本流；正常 end 但无任何可见文本时返回无有效响应错误。
- [ ] 以异步增量形式产出事件；不把整段回答聚合到内存后再交给 ConversationEntity。
- [ ] 运行 SSE parser 聚焦测试及 B2 回归。

**Exit gate:**
- P3-T07 至 T10、T12 的 SSE 事件行为覆盖。
- 文本内容与顺序保持原样；内部 reasoning/tool 事件不会进入 HA ChatLog/TTS。
- 正常 end、error、未知事件和意外 EOF 有清晰区分。

**Commit:** feat(p3): parse AstrBot SSE stream

## 8. Batch 4 — HA ConversationEntity and ChatLog streaming

**Purpose:** 将已经独立测试的 Session/API/SSE 组件接到 HA 原生 ConversationEntity，交付 P3 的主要用户可见能力。

**Files:**
- Create: homeassistant/custom_components/astrbot/conversation.py
- Modify: __init__.py to register the conversation platform.
- Tests: ConversationEntity、ChatLog delta、ConversationResult 和 Assist pipeline integration tests.

**Tasks:**
- [ ] 先写 HA 侧加载测试：创建 conversation.astrbot，确认实体由 Config Entry 注册。
- [ ] 先写 supports_streaming=true 和 MATCH_ALL language contract 测试。
- [ ] 先写 ChatLog 流式断言：首个 chunk 为 assistant role，后续普通文本增量按到达顺序写入。
- [ ] 先写输入边界测试：只发送 ConversationInput.text；context.user_id、conversation_id、device_id、satellite_id、language、agent_id、extra_system_prompt 不转发。
- [ ] 在实体中实现 _async_handle_message(user_input, chat_log)，通过 Session Manager 取活动 session，调用 API Client，并消费 SSE Parser。
- [ ] 从可见文本开始逐段提交 ChatLog delta；不得等完整 SSE 结束后一次性添加全文。
- [ ] HA 已经写入用户消息；不重复写用户正文，也不把 AstrBot user_message_saved 再写回 HA。
- [ ] SSE 正常 end 后通过 HA async_get_result_from_chat_log() 返回标准 ConversationResult。
- [ ] 用真实 HA ConversationEntity/ChatLog 测试覆盖一轮和多轮，确认 pipeline 能消费增量。
- [ ] 运行 Conversation 聚焦测试及 B0–B3 回归。

**Exit gate:**
- P3-T01、T02、T08、T11 的实体与 ChatLog 合同覆盖。
- 可选择 conversation.astrbot；HA 对话输出使用标准 ConversationResult。
- supports_streaming 是真实逐段输出，不是仅声明属性。
- 不声称 TTS 已经流式播放。

**Commit:** feat(p3): stream AstrBot replies through HA ChatLog

## 9. Batch 5 — Cancellation, session serialization and failure closure

**Purpose:** 在单活动 session 与 session 级 stop 的限制下，保证多请求和取消不会互相误伤或伪报完成。

**Files:**
- Modify: conversation.py / api.py / session.py only where needed.
- Tests: cancellation, lock ordering, owner mismatch, EOF and stop API integration tests.

**Tasks:**
- [ ] 先写并发测试：同一个活动 session 的两个 Chat 请求不得并行进入 AstrBot；第二个请求等待第一个结束/取消。
- [ ] 先写取消测试：关闭当前 SSE reader 后使用同一个 API Key 和 session_id 调用 stop，随后继续传播 CancelledError。
- [ ] 先写 stop owner 测试：请求体 username 与 API Key AuthContext username 必须都是 api_key:<key_id>；不同自定义 username 必须被测试拒绝。
- [ ] 先写 stop 失败/超时测试：记录不含密钥的警告，仍传播取消，不宣称上游已停止。
- [ ] 对已发出的请求发生协议错误或意外 EOF 时，在需要时调用 stop；不能生成成功结果。
- [ ] 精确识别 session owner mismatch；只有这一确定错误可以丢弃映射、创建新 UUIDv4 并重试一次。其他 4xx、5xx、timeout、connection reset 不得触发新 POST。
- [ ] SSE error 事件作为本轮失败终止；不把错误内容当成正常 Assistant 回答。
- [ ] 验证正常结束后锁释放、取消后锁释放、失败后下一轮可用；不允许遗留后台 reader 或 task。
- [ ] 运行全部 cancellation/serialization/error 测试及 B0–B4 回归。

**Exit gate:**
- P3-T12、T13、T15、T16 覆盖。
- 同一 session 的 stop 不会误杀并行 Chat，因为并行请求已串行化。
- 取消与 stop 失败都不吞掉 CancelledError，不伪造成功响应。
- 除明确 owner mismatch 外没有 Chat POST 自动重试。

**Commit:** fix(p3): close cancellation and session ownership edge cases

## 10. Batch 6 — P3 contract matrix acceptance

**Purpose:** 完成 P3 全部机器测试、真实 HA 文本对话验收和范围审查；不实现下游阶段。

**Files:**
- Modify only tests/docs required by actual findings.
- Create: docs/superpowers/reports/2026-11-09-p3-astrbot-conversation-agent-verification.md after evidence exists.
- Update README.md P3 status only after the corresponding acceptance gates have passed.

**Tasks:**
- [ ] 对照 P3-T01 至 P3-T16 逐项检查自动化覆盖和人工验收证据；未运行项目标记 NOT COVERED / BLOCKED，不得推断通过。
- [ ] 运行全部 HA 集成测试、目标 unit tests、lint/type checks available in the selected test environment 和 git diff --check。
- [ ] 将代码加载到 HA 2026.11.0，确认 Settings/Assist 可选择 conversation.astrbot。
- [ ] 在用户配置专用 chat-scope API Key 后，通过 HA 网页 Assist 发起真实文本对话；核对 AstrBot 收到的原始文本、username、session_id 和 SSE 增量。
- [ ] 连续多轮、HA conversation_id 换新、等待超过 HA 5 分钟 ChatSession 生命周期、HA 重启恢复、24 小时边界和 key_id 轮换均按各自测试/证据验证。
- [ ] 通过真实取消验证 AstrBot stop owner 校验；不因测试需要清除 AstrBot 历史或删除 session。
- [ ] 证明 SSE 增量进入 HA ChatLog，并返回标准 ConversationResult。
- [ ] P3-T14 仅验证 Conversation Agent 的 ChatLog 增量满足 Pipeline 的流式输入条件；真实 Wyoming TTS 分句、PCM callback、TTS Proxy 和 ESP32 播放明确留给 P5/P6。
- [ ] 最终审查变更只涉及 astrbot 集成、对应测试与 P3 文档；无 Tivoo 集成、MCP、STT/TTS Provider、Satellite 或固件代码。
- [ ] 建立 P3 验收报告；只有 T01–T16 达到各自定义标准才更新 README P3 状态。
- [ ] 独立本地提交最终验收材料；未经用户指示不推送、不合并。

**Exit gate:**
- P3-T01 至 P3-T16 均有明确 PASS 证据，或明确记录未完成项并保持 P3 BLOCKED。
- HA 网页 Assist 的实际文本对话可用；多轮 session 身份稳定；ChatLog 增量/最终结果和取消行为符合合同。
- 不将 TTS 流式播放或 Tivoo 实机语音当作 P3 完成条件。

**Commit:** test(p3): verify AstrBot conversation agent contract

## 11. Contract-to-batch traceability

| 合同 | 主要责任 Batch | 自动/人工验证重点 |
|---|---|---|
| P3-01 HA 输入 | B4 | 最终 STT 文本进入 ConversationEntity，不接收音频 |
| P3-02 ChatLog delta | B3、B4 | Assistant role、可见 delta 顺序、无重复用户消息 |
| P3-03 Chat HTTP | B2 | 路由、headers、body、200 SSE 与 JSON error |
| P3-04 API Key scope | B0、B2、B6 | chat scope、401/403、secret 保护 |
| P3-05 username 映射 | B1、B2、B5 | api_key:<key_id> 与 stop owner 一致 |
| P3-06 Store/session | B1 | UUIDv4、持久化、24h TTL、重启和身份变化 |
| P3-07 SSE framing | B3 | data frame、heartbeat、边界和顺序 |
| P3-08 可见文本 | B3、B4 | plain 过滤、内部链路不进 ChatLog |
| P3-09 Pipeline delta | B4、B6 | HA 消费增量；TTS 能力另归 P5 |
| P3-10 ConversationResult | B4 | 原生 ChatLog 到标准结果转换 |
| P3-11 stop API | B2、B5 | stop path、相同 API Key、session 级语义 |
| P3-12 异常/取消 | B2、B3、B5 | HTTP/SSE/EOF/取消失败不伪装成功、不重复提交 |
| P3-T01–T03 | B0、B2、B4 | 集成加载、真实文本入口、请求体 |
| P3-T04–T07 | B1、B6 | 多轮、HA 5 分钟、重启、24h 边界 |
| P3-T08–T11 | B3、B4 | SSE 到 ChatLog、正常 end、标准结果 |
| P3-T12–T13 | B2、B3、B5 | 错误、EOF、取消和 stop |
| P3-T14 | B4、B6 | 仅 Conversation delta 与 Pipeline 条件；TTS 实播归 P5 |
| P3-T15–T16 | B1、B5、B6 | stop owner 一致、API Key 更换后新 session |

## 12. Global execution and verification rules

- 每个 Batch 开始先核对当前 branch、HEAD、working tree、主计划、本文和 P3 合同矩阵；只执行当前 Batch。
- 每个 Batch 必须先增加能暴露缺失行为的 RED 测试，再做最小实现并 GREEN。禁止先写完整实现再补测试。
- 优先复用 HA 原生 ConversationEntity、ChatLog、Store、aiohttp session 和现有集成加载/测试模式；不建立自有 Conversation 历史存储。
- 每个 Batch 结束运行其聚焦测试、必要回归、静态检查、git diff --check 和 changed-file scope review；单独本地提交。
- 每个批次在进度账本记录基线、修改范围、RED/GREEN 证据、验证命令、提交 SHA、尚未覆盖项和下一 Batch 的接口输入。
- 遇到合同与运行版本不一致、stop owner 规则不一致、SSE 真实事件结构变化或测试框架无法复现 HA 2026.11.0 行为时，停止该 Batch 并先更新合同/计划，不在代码里临时绕过。
- 任何真实 HA/AstrBot 验收必须使用用户配置的专用 API Key；不得复制密钥到计划、报告、日志或 Git。
- 未经用户另行指示，不部署到 NAS、不修改生产 HA Config Entry、不创建/删除 AstrBot session、不推送、不合并。
