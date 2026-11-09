# P3 AstrBot Conversation Agent Implementation Plan

> 状态：P3b0 已完成（HA 集成基线与 Config Flow）；P3b1–P3b6 尚未开始。
> 工作分支：feature/p3-astrbot-conversation-agent
> 基线：main / c754f5a22727fa0ded6a2fd0c309c967b162097d
> 日期：2026-11-09

## Goal

在 Home Assistant Core 2026.11.0 中提供独立的 AstrBot Conversation Agent。HA Assist Pipeline 将最终 STT 文本交给 AstrBot 4.29.4 的 HTTP OpenAPI；集成将 AstrBot SSE 中的可见文本增量按顺序写入 HA ChatLog，最终通过 HA 原生 ConversationResult 返回。单一 HA 用户在 HA 重启、HA conversation_id 更新以及 AstrBot 上下文压缩后继续使用同一个活动 AstrBot 会话；最近一次被 AstrBot 接受的请求超过 24 小时未活动后才轮换 session_id。

本计划定义 P3 的完整实现批次；当前只完成 P3b0。后续批次仍按分批执行计划逐批实现，不提前创建 Session、HTTP Chat、SSE 或 Conversation 代码，也不扩大到 P4/P5/P6。

## Architecture

数据方向固定为：

HA Assist Pipeline
→ conversation.astrbot
→ 单活动 Session Manager
→ HA 共享 aiohttp ClientSession
→ AstrBot POST /api/v1/chat
→ 增量 SSE Parser
→ HA ChatLog Delta Stream
→ 标准 ConversationResult
→ HA Assist Pipeline

取消路径由同一集成调用 AstrBot session stop API。HA 是 HTTP/SSE 客户端，AstrBot 是对话主体。P3 不通过 MCP 发送 STT 文本，也不让 AstrBot 直接连接 ESP32。

集成独立放在 homeassistant/custom_components/astrbot/，不并入 homeassistant/custom_components/tivoo/。P3 可以先通过 HA 网页 Assist 独立验收，不要求 Tivoo、ESP32、Assist Satellite 或麦克风已接入。

## Authority

1. **唯一 P3 接口合同：** docs/superpowers/specs/2026-11-09-p3-astrbot-conversation-contract-matrix.md。HTTP 字段、API Key 身份、session_id 生命周期、SSE 事件、ChatLog、取消和 P3-T01 至 P3-T16 均以此为准。
2. **项目整体范围与阶段顺序：** README.md §2–§4、§10；P3 是独立阶段，位于 P2 与 P4 之间。
3. **语音链路边界：** docs/superpowers/specs/2026-11-09-stt-tts-end-to-end-pipeline-spec.md §2–§5、§7–§10。该文用于区分 P3 文本桥与 P5 TTS Provider，不重新定义 P3 API。
4. **更下游设备边界：** docs/superpowers/specs/2026-11-09-esp32-ha-bidirectional-communication-design.md。仅用于确认 P3 不依赖 Tivoo Satellite、TCP、HTTP 音频资源请求或 ESP32 固件。

发生冲突时，P3 合同矩阵对 P3 接口具有最高优先级；更上层文档不得被解释为允许扩大 P3 范围。

## Version and environment baseline

- Home Assistant Core：2026.11.0。
- AstrBot：4.29.4，源码 tag v4.29.4。
- AstrBot OpenAPI Key：专用于 HA P3，scope 只需 chat。
- 实施前在 B0 核对实际 HA Core 与 AstrBot 运行版本及其对应源码；若版本已改变，先复核 ConversationEntity、ChatLog、API Key username 和 stop owner 校验，不得直接假设旧合同仍适用。
- P3 使用 HA 已有的共享 aiohttp ClientSession、asyncio、Store 和原生 Conversation API。不新增 HTTP 客户端、SSE 第三方库或运行时依赖。
- 测试工具链由 B0 根据当前仓库和 HA 2026.11.0 兼容性确认；优先复用 Home Assistant 自身测试模式或兼容的 pytest-homeassistant-custom-component，不预先引入未验证的依赖版本。

## Global constraints

1. **单用户范围：** 当前只有一个 HA 用户。不创建 user_id 映射表、不接入家庭成员区分，不按 device_id 或 satellite_id 分配 AstrBot 用户。
2. **唯一用户身份：** username 固定派生为 api_key:<key_id>。key_id 是创建/列出 API Key 时返回的元数据；不能从 secret 前缀推导。username 不可手工编辑，不得替换为 HA 用户名、显示名、邮箱或 context.user_id。
3. **单活动会话：** HA Store 只保存一个当前活动会话记录，不保存聊天正文。记录至少含版本、API Key key_id、派生 username、UUIDv4 session_id、created_at 和 last_activity_at。
4. **24 小时滑动空闲期限：** 距最近一次被 AstrBot 接受的用户请求达到或超过 24 小时才创建新 UUIDv4。HA conversation_id 变化、HA ChatSession 5 分钟清理、HA 重启以及 AstrBot 上下文压缩均不触发轮换。
5. **身份变化：** AstrBot Base URL 或 key_id 变化时不复用旧 session_id；同一 key_id 对应的 API Key secret 重新录入时保留会话。更换 key_id 后使用新 username 和新 session_id。
6. **上下文压缩：** 不解析 agent_stats 的 token 数、不推断压缩发生、不因压缩重置 session_id。AstrBot 自己负责上下文压缩和聊天历史。
7. **请求合同：** POST {base_url}/api/v1/chat；Authorization: Bearer；Accept: text/event-stream；Content-Type: application/json。请求体必须包含 username、session_id、原样 message 和 enable_streaming=true。省略 locale、config_id、config_name、platform_id、conversation_id。
8. **协议边界：** 不使用 /v1/chat/completions、AstrBot Dashboard WebSocket、MCP 或自行构造 Agent 内部事件。P3 不接收原始音频、不执行 STT/TTS、不注册 HA LLM Tools。
9. **SSE 到 ChatLog：** 只把普通可见 plain 文本增量交给 ChatLog；reasoning、tool_call、tool_call_result、agent_stats、保存元数据和 heartbeat 不进入回答。按到达顺序原样传递，不重写或重新分句。
10. **标准 HA 结果：** 通过 ChatLog 增量流和 HA 原生 async_get_result_from_chat_log() 形成 ConversationResult；不自行拼装历史对象，不重复写入 HA 已记录的用户消息。
11. **真实流式声明：** 只有真正逐段向 ChatLog 提交增量时才声明 supports_streaming。P3 完成不等于已经具备流式 TTS；P5 Wyoming TTS Provider 必须独立支持 streaming input。
12. **取消与并发：** AstrBot stop API 是 session 级而非 run 级。对唯一 session 的完整对话请求做串行化，避免并行请求被一次 stop 一并终止。取消时关闭 SSE reader、调用 stop，再继续传播 CancelledError。
13. **重试边界：** Chat POST 不自动重发。只有明确识别为 session owner 不匹配时，才可创建新 UUIDv4 并重试一次；不得把网络错误、超时或任意 4xx/5xx 当成 owner 冲突。
14. **失败不伪装成功：** HTTP JSON error、认证失败、SSE error、未知事件、非法 JSON、无 end 的 EOF 或只有元数据没有可见文本，都不能生成成功回答。意外 EOF / 协议异常在请求已发出后按合同尝试 stop。
15. **凭据保护：** API Key secret 只保存在 HA config entry；不得写入日志、测试 fixture、URL、query string、计划文档或 Git。错误日志只保留不含密钥的状态、事件类型和必要关联信息。
16. **范围隔离：** 不改 Tivoo 集成、不做 P4 MCP Tools、不做 P5 Wyoming STT/TTS、不做 P6 Assist Satellite、不做 P7 唤醒词、不改 AstrBot 插件和 ESP32 固件。
17. **批次规则：** 每个 Batch 先写并运行 RED 测试，再做最小实现并达到 GREEN；完成规定回归、diff 检查和边界审查后独立本地提交。未获另行授权不推送、不合并。

## Planned source layout

集成生产代码：

- homeassistant/custom_components/astrbot/manifest.json：HA 集成元数据。
- homeassistant/custom_components/astrbot/__init__.py：Config Entry setup/unload，注册 Conversation 平台。
- homeassistant/custom_components/astrbot/const.py：domain、配置键、username prefix、24 小时 TTL。
- homeassistant/custom_components/astrbot/config_flow.py：Base URL、API Key secret、API Key key_id 配置；username 不作为可编辑字段。
- homeassistant/custom_components/astrbot/session.py：单活动 session、Store、UUIDv4、身份变更和过期策略。
- homeassistant/custom_components/astrbot/api.py：复用 HA aiohttp session 的 Chat/stop HTTP 调用和响应状态检查。
- homeassistant/custom_components/astrbot/sse.py：增量解析 SSE 数据帧并分类事件。
- homeassistant/custom_components/astrbot/conversation.py：ConversationEntity、串行化、ChatLog delta stream、ConversationResult、取消编排。

新增 api.py 和 sse.py 是为了让 HTTP 与流协议可独立测试；不引入通用请求框架或复杂事件总线。若 B0 发现现有仓库模式要求不同布局，在对应 Batch 更新此计划后继续。

测试目录建议为 tests/homeassistant/custom_components/astrbot/，由 B0 确认与实际 test runner 的布局约定后冻结。至少覆盖 config flow、setup/unload、session、API client、SSE parser、ConversationEntity 和取消/并发行为。

## Stable internal boundaries

- Session Manager：读取或生成当前 UUIDv4；判断 24 小时过期；按 Base URL/key_id 身份变化轮换；收到 session_id 接受帧后持久化/更新时间；不保存对话正文。
- API Client：只负责按固定请求合同调用 AstrBot、校验 HTTP 状态/Content-Type、返回流式响应和调用 stop；不解释 ChatLog。
- SSE Parser：将线协议转成有序事件；不直接操作 HA Entity 或 Store。
- ConversationEntity：把输入文本交给 Session Manager/API Client，将可见文本交给 HA ChatLog，使用 HA 原生结果转换；不创建独立 HTTP session。
- Cancellation Coordinator：位于 Conversation 执行边界，停止当前 reader 并请求 session stop；不将 session stop 表述为 run_id 级操作。

这些边界是职责合同，不要求首版增加额外接口层、依赖注入容器或过度抽象。

## Batch sequence

完整任务、文件边界、测试和退出条件见同目录的 2026-11-09-p3-astrbot-conversation-agent-batch-execution-plan.md。

顺序固定为 B0 基线与集成配置、B1 会话持久化、B2 HTTP OpenAPI、B3 SSE Parser、B4 ConversationEntity/ChatLog、B5 取消/串行化/错误收口、B6 P3 全矩阵验收。除非合同审计发现明确依赖缺口，不跨批并行实现。

## Completion definition

P3 只有在 P3-T01 至 P3-T16 均有对应证据、HA 网页 Assist 的真实多轮文本对话通过、24 小时和重启会话策略通过、取消 owner 校验通过、ChatLog 增量和标准 ConversationResult 通过，且未把 P4/P5/P6 功能混入时才可声明完成。

自动化测试通过不能替代实际部署配置与 HA UI 验收；P3 完成也不能宣称端到端语音、流式音频或 Tivoo 播放已经完成。
