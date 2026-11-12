# P3 AstrBot Conversation 接口合同矩阵

> 状态：接口合同已冻结；P3 核心文字链路已实现并完成基础现场验收；HA 重启、24h 和取消/Stop owner 等验收仍待完成
> 日期：2026-11-09  
> 适用版本：NAS Home Assistant Core 2026.11.0；AstrBot 4.29.4（对应源码 tag：v4.29.4）  
> 范围：HA Assist Pipeline 与 AstrBot HTTP OpenAPI 之间的 Conversation Agent 适配层  
> 本文是 P3 的唯一接口合同依据。本文不实现代码，也不重新定义 STT/TTS、ESP32、MCP 或 Tivoo 设备协议。

## 1. 目标与设计结论

P3 交付一个独立的 HA 自定义集成 `astrbot`，将 HA Assist Pipeline 产出的最终 STT 文本交给 AstrBot，并将 AstrBot SSE 文本增量转换为 HA ChatLog 增量。

P3 的职责固定为：

1. 接收 HA `ConversationInput` 中的 STT 识别文本。
2. 调用 AstrBot 4.29.4 的 `POST /api/v1/chat`。
3. 为当前单一 HA 用户维护稳定的 AstrBot `username` 和活动 `session_id`。
4. 解析 AstrBot SSE，按顺序把用户可见的文本增量写入 HA `ChatLog`。
5. 实现 HA `ConversationEntity` 的真实流式响应能力，并返回标准 `ConversationResult`。
6. 处理认证失败、协议错误、连接中断、请求取消和上游停止。

**确定的单用户映射：**

- 本项目 P3 暂时只配置一个 HA 用户，不实现家庭成员区分或多 HA 用户映射。
- AstrBot `username` 固定映射为当前专用 OpenAPI Key 的鉴权主体：`api_key:<key_id>`。它不是 HA 用户名、显示名或 `context.user_id`。
- 所有来自当前 HA Conversation Agent 的请求使用同一个活动 AstrBot `session_id`；HA 的 `conversation_id` 不直接充当 AstrBot `session_id`。
- `session_id` 使用本集成生成的 UUIDv4，活动会话按 **最近一次被 AstrBot 接受的用户请求后 24 小时无活动** 过期。未超过 24 小时则复用；过期后创建新 UUIDv4。
- 正常的 AstrBot 上下文压缩不触发 session_id 轮换。

## 2. 当前版本和源码依据

### 2.1 运行版本

NAS 当前运行的 HA 容器镜像已通过容器清单确认：

`ghcr.io/home-assistant/home-assistant:2026.11.0`（容器名 `homeassistant`）。

AstrBot 当前运行版本按项目当前部署记录为 4.29.4。本合同只使用 AstrBot `v4.29.4` 的公开 OpenAPI、OpenAPI Schema 和对应实现；AstrBot Docker 镜像使用可变的 `latest` 标签，后续升级必须重新核对实际版本，不能只凭镜像标签认为接口不变。

### 2.2 HA 关键实现

- `homeassistant/components/conversation/models.py`：`ConversationInput` 的真实字段包括 `text`、`context`、`conversation_id`、`device_id`、`satellite_id`、`language`、`agent_id` 和 `extra_system_prompt`。
- `homeassistant/components/conversation/entity.py`：`ConversationEntity.async_process()` 负责建立/获取 HA ChatSession 和 ChatLog，集成实现 `_async_handle_message(user_input, chat_log)`；流式声明由 `_attr_supports_streaming` 提供。
- `homeassistant/components/conversation/chat_log.py`：`ChatLog.async_add_delta_content_stream(agent_id, stream)` 接收 HA 的 Assistant delta。
- `homeassistant/components/conversation/util.py`：`async_get_result_from_chat_log(user_input, chat_log)` 将最终 ChatLog 转换为标准 `ConversationResult`。
- `homeassistant/helpers/chat_session.py`：HA ChatSession 使用内存会话登记和清理；`CONVERSATION_TIMEOUT` 为 5 分钟。过期的 ULID conversation_id 再次进入时，HA 会创建新的 conversation_id。
- `homeassistant/components/assist_pipeline/default_pipeline.py`：Pipeline 将 ChatLog delta 传给 `INTENT_PROGRESS`；只有当前 TTS Stream 支持流式文本输入且 Conversation Agent 声明支持流式响应时，Pipeline 才具备流式 TTS 响应条件。

### 2.3 AstrBot 关键实现

- `docs/zh/dev/openapi.md`、`openspec/openapi-v1.yaml`：HTTP OpenAPI 请求字段、认证和 SSE 端点合同。
- `astrbot/dashboard/api/open_api.py`、`astrbot/dashboard/services/open_api_service.py`：API Key scope、username/session_id 校验、WebChat Session 创建和 SSE 响应入口。
- `astrbot/dashboard/services/chat_service.py`：SSE 数据帧、run 生命周期、heartbeat、结束和错误事件。
- `astrbot/core/platform/sources/webchat/webchat_queue_mgr.py`：WebChat 按 session_id 建立输入队列，并按队列顺序交给 listener 处理。
- `astrbot/dashboard/api/chat.py`：公开的 session stop 路由。
- `astrbot/core/agent/context/manager.py`、`astrbot/core/agent/context/compressor.py`：内置 Agent 的上下文截断和压缩实现。

## 3. 职责边界

| 组件 | 本阶段职责 | 明确不负责 |
|---|---|---|
| HA Assist Pipeline | 唤醒词、STT、选择 Conversation Agent、消费 ChatLog 增量、调度 TTS | 不调用 AstrBot 模型，不管理 AstrBot 内部历史 |
| P3 AstrBot Conversation Agent | 接收识别文本、映射单用户会话、调用 HTTP OpenAPI、解析 SSE、写 ChatLog、停止上游任务 | 不接收音频、不做 STT/TTS、不调用 ESP32、不提供 HA 设备 MCP 工具 |
| AstrBot 4.29.4 | 人格、模型、Agent、对话历史、上下文压缩、已配置的插件和工具 | 不负责 HA 的 Assist Pipeline 生命周期 |
| HA ChatLog | 当前 HA conversation 的消息记录和流式增量载体 | 不作为 AstrBot 长期会话的权威存储 |
| HA MCP Server / AstrBot MCP Client | P4 反向工具调用：AstrBot 调用 HA 工具 | 不用于 HA 把 STT 文本发送给 AstrBot |
| Tivoo 自定义集成 | 后续阶段接管 Assist Satellite、ESP32 音频和设备控制 | 不承担 AstrBot HTTP Chat API 客户端职责 |

**集成隔离：** P3 放在 `homeassistant/custom_components/astrbot/`，独立于 `homeassistant/custom_components/tivoo/`。AstrBot Conversation Agent 可先通过 HA 网页 Assist 独立测试；Tivoo 设备和 ESP32 尚未接入时也必须可运行。

P3 不调用 HA 的 `async_provide_llm_data()` 来把 HA LLM Tools 注册给当前 Agent。P4 的工具方向是 AstrBot MCP Client → HA MCP Server，与 P3 的 HA → AstrBot HTTP Chat API 分开实现。

## 4. 合同矩阵

| ID | 提供方 → 消费方 | 接口/机制 | 输入合同 | 输出合同与完成条件 |
|---|---|---|---|---|
| P3-01 | HA Assist Pipeline → AstrBot Conversation Entity | HA `ConversationEntity` | `ConversationInput.text` 是最终 STT 文本；其余字段按第 5 节处理 | 进入 `_async_handle_message(user_input, chat_log)`；不接收原始音频 |
| P3-02 | HA Conversation Entity → HA ChatLog | `ChatLog.async_add_delta_content_stream()` | `AssistantContentDeltaDict` 异步增量流 | 每段用户可见文本按到达顺序进入 ChatLog；流结束后形成最终 AssistantContent |
| P3-03 | HA AstrBot 集成 → AstrBot | HTTP `POST /api/v1/chat` | Bearer API Key、JSON 请求体，必须含稳定 `username`、`session_id`、`message` | 成功时返回 `text/event-stream`；非流式 JSON 错误响应必须被识别为请求失败 |
| P3-04 | HA AstrBot 集成 → AstrBot 鉴权 | `Authorization: Bearer <API_KEY>` | AstrBot OpenAPI Key 至少包含 `chat` scope | 401/403 转换为可诊断错误；不要求 `chat:admin` |
| P3-05 | HA 单用户 → AstrBot 用户 | 固定 `username=api_key:<key_id>` | 使用专用 API Key 的 key_id 派生固定服务身份 | 与 AstrBot API Key 的 AuthContext.username 完全一致，使 Chat session owner 校验及 stop 路由使用同一身份 |
| P3-06 | HA 活动会话状态 → AstrBot | HA `Store` 持久化 `session_id` | UUIDv4、创建时间、最近活动时间、username/服务实例标识 | HA 重启后恢复未过期会话；24 小时无活动后改用新 ID |
| P3-07 | AstrBot SSE → HA SSE Parser | `text/event-stream`，`data: JSON\n\n` | 心跳注释、JSON 数据帧 | 解析出 `type` 和对应数据；保留帧顺序；不依赖非官方事件名 |
| P3-08 | SSE Parser → HA ChatLog Delta | `plain` 事件转 `AssistantContentDeltaDict` | 只接收用户可见纯文本，不转发 reasoning/tool 内部元数据 | 文本逐段写入 ChatLog；不等待整个回答聚合完成 |
| P3-09 | HA ChatLog → HA Assist Pipeline | ChatLog delta listener | Assistant role 和 content 增量 | Pipeline 收到 INTENT_PROGRESS；TTS 流式与否由 TTS Provider 后续能力共同决定 |
| P3-10 | HA Conversation Entity → Assist Pipeline | `conversation.async_get_result_from_chat_log()` | 已完成的 ChatLog | 返回标准 `ConversationResult`，包含 speech 和 HA conversation_id |
| P3-11 | HA 取消 → AstrBot | `POST /api/v1/chat/sessions/{session_id}/stop` | 同一个 API Key 和 username 所属的 session_id | 请求 AstrBot 停止该 session 正在执行的 Agent 工作；停止范围为整个 session，不是单独 run |
| P3-12 | HTTP/SSE 异常 → HA Conversation | HA Error/取消语义 | HTTP 状态、JSON error envelope、SSE error、非法帧、意外 EOF | 不把未完成响应当成正常回答；不自动重发可能已提交的用户请求 |

## 5. HA 输入字段和用户映射

### 5.1 HA ConversationInput 字段处理

| HA 字段 | P3 处理 | 依据/原因 |
|---|---|---|
| `text` | 作为 AstrBot 请求的 `message` 原样发送 | 这是 STT 完成后的用户文本 |
| `context.user_id` | 不转换为 AstrBot username，不发送给 AstrBot | 当前只有一个 HA 用户；HA 自身负责 ChatSession 的用户归属校验 |
| `conversation_id` | 只用于 HA 自己的 ChatSession/ChatLog，不发送为 AstrBot session_id | HA 的 ChatSession 是短期内存对象，默认 5 分钟清理 |
| `device_id` | 不发送 | P3 使用单用户、单活动会话策略，不区分来源设备 |
| `satellite_id` | 不发送 | 同上；后续主动会话/多设备策略另行定义 |
| `language` | 不发送为 AstrBot `locale` | AstrBot `locale` 是内建错误消息/UI locale，不是模型对话语言字段 |
| `agent_id` | 不作为 AstrBot 用户或 session 标识 | HA 内部 Agent 标识 |
| `extra_system_prompt` | P3 不转发 | AstrBot 4.29.4 的 `OpenApiChatRequest` 没有等价字段；不能把它伪装成用户消息 |

### 5.2 HA 用户与 AstrBot username

本阶段只有一个 HA 用户，因此不需要维护 HA user_id 到 AstrBot 用户的多用户映射表。AstrBot `username` 固定使用专用 API Key 的鉴权主体：

| HA 来源 | AstrBot username | 说明 |
|---|---|---|
| 当前唯一 HA 用户的 Assist 请求 | `api_key:<key_id>` | 从专用 AstrBot OpenAPI Key 的 key_id 派生；该 Key 生命周期内保持不变 |

这是根据 AstrBot 4.29.4 实际鉴权代码确定的映射：

- `astrbot/core/workspace.py` 定义 `API_KEY_USERNAME_PREFIX = "api_key:"`。
- `astrbot/dashboard/api/auth.py` 的 `_require_api_key_scope()` 将 API Key 请求的 `AuthContext.username` 设置为 `api_key:<key_id>`。
- `POST /api/v1/chat` 使用请求体里的 `username` 作为 WebChat session creator；通用 Chat session stop 路由则使用 `AuthContext.username` 校验 creator。

因此，P3 必须在 Chat 请求体中显式发送同一个 `api_key:<key_id>`，让 Chat session creator 与 stop 路由鉴权主体一致。若使用 `ha_assist` 这样的自定义用户名，4.29.4 的 stop 路由会以 `api_key:<key_id>` 校验 owner，导致停止请求被拒绝。不能只因为 OpenAPI schema 中列出了 stop 接口就假设两种 username 身份会自动关联。

`key_id` 是 API Key 元数据，不是密钥；创建 Key 的响应和 API Key 列表均包含 `key_id`。P3 配置只需保存该 ID 和 API Key secret，不允许从 secret 前缀推导 key_id。不得使用显示名、邮箱、HA 内部 user_id 或每轮随机值生成 username。

API Key 使用 `chat` scope，不授予 `chat:admin`。更换/重建 API Key 会产生新的 key_id，因此新 username 也变化；P3 将该情况视为服务身份变更并创建新的 AstrBot session_id。

## 6. AstrBot session_id 生命周期

### 6.1 为什么不能使用 HA conversation_id

HA Core 2026.11.0 的 `helpers/chat_session.py`：

- ChatSession 的内存超时为 5 分钟。
- 过期 session 会从 HA 内存登记表清除。
- 若后续请求传入的旧 conversation_id 是有效 ULID，但已不在登记表中，HA 会生成新的 ULID。

所以 HA conversation_id 不能作为跨 5 分钟、HA 重启及 24 小时窗口的持久 AstrBot session_id。

### 6.2 唯一活动会话记录

P3 只维护一个当前活动 session，存储在 HA `homeassistant.helpers.storage.Store` 中。数据结构：

```json
{
  "version": 1,
  "api_key_id": "<AstrBot API Key key_id>",
  "username": "api_key:<key_id>",
  "session_id": "<UUIDv4>",
  "created_at": "<UTC ISO-8601>",
  "last_activity_at": "<UTC ISO-8601>"
}
```

不保存聊天正文。聊天正文由 AstrBot 管理。

### 6.3 生成和复用规则

1. 首次调用且本地没有有效记录时，生成 UUIDv4。
2. 记录中的 username 与当前配置一致，且 `now - last_activity_at < 24h` 时，复用该 session_id。
3. 最近活动时间达到或超过 24 小时，创建新的 UUIDv4，并重置创建/活动时间。
4. 收到 AstrBot 接受请求的 SSE 起始帧（`type=session_id` 且 ID 与请求一致）后，持久化/更新时间；正常结束时更新最后活动时间。
5. HA 重启后读取 Store；未过期则继续使用原 session_id。
6. AstrBot URL 或 API Key 的 `key_id` 改变时，派生的 username 随之变化，旧映射不再复用并创建新 session_id。仅替换同一个 key_id 对应的 secret（例如重新录入同一 Key）且 URL/key_id 不变时，保留会话。
7. 旧 AstrBot session 不由 P3 删除；由 AstrBot 自身保留策略和 WebUI 管理。

### 6.4 上下文压缩不触发轮换

AstrBot 4.29.4 内置 Agent 在请求模型前运行 ContextManager：

- 根据模型窗口 Token 使用量检查是否达到压缩阈值；默认压缩阈值约 82%。
- 可选择按轮次截断，或用 LLM 将较早历史总结为摘要并保留最近的原始轮次。
- 若压缩后仍超过限制，会进一步丢弃最早的完整轮次。
- 这属于同一个 AstrBot 会话内部的历史整理，不是创建新 WebChat session。

AstrBot 4.29.4 的公开 Chat SSE 没有专门的 context-compression 事件。现有 `agent_stats` 中的 `current_context_tokens` 是模型请求的 token 使用数据，不是可靠的“本轮发生了压缩”标志。

因此 P3 **不根据压缩推断、token 数变化或 agent_stats 轮换 session_id**。若在压缩后立刻创建新 session_id，会切换到底层不同的 WebChat/UMO 对话上下文，丢弃原会话刚生成的摘要与保留的近期历史。这与 AstrBot 自带压缩机制的目的相反。

## 7. AstrBot HTTP OpenAPI 合同

### 7.1 Chat 请求

请求地址：

```text
POST {astrbot_base_url}/api/v1/chat
```

请求头：

```http
Authorization: Bearer <ASTRBOT_API_KEY>
Content-Type: application/json
Accept: text/event-stream
```

请求体：

```json
{
  "username": "api_key:<key_id>",
  "session_id": "<UUIDv4>",
  "message": "<ConversationInput.text>",
  "enable_streaming": true
}
```

字段要求：

| 字段 | 必需 | P3 规则 |
|---|---|---|
| `username` | 是 | 固定为当前 API Key 的 `api_key:<key_id>`，不得手工设置为其他身份 |
| `session_id` | P3 必须提供 | 使用第 6 节的 UUIDv4 活动会话 |
| `message` | 是 | 直接使用 STT 最终文本字符串 |
| `enable_streaming` | P3 必须为 true | 请求 AstrBot 流式输出 |
| `locale` | 否 | P3 不发送；不是模型语言控制字段 |
| `config_id` / `config_name` | 否 | P3 默认省略，使用 AstrBot 默认配置 |
| `platform_id`、`conversation_id` | 否 | P3 不发送 |

P3 不使用 OpenAI 兼容接口 `/v1/chat/completions`，不使用 AstrBot Dashboard 内部 WebSocket，不自行构造 AstrBot Agent 事件。

### 7.2 API Key scope 和 username 一致性

- 为 HA P3 创建专用 AstrBot OpenAPI Key，启用 `chat` scope。
- 创建时记录 API Key 返回的 `key_id`，HA 配置保存 `key_id` 与 `api_key` secret 两项。
- P3 计算 `username = "api_key:" + key_id`；这一值与 4.29.4 `AuthContext.username` 的生成规则一致。
- 不需要 `config`、`im`、`file` 或 `chat:admin` scope。
- 认证方式按官方文档使用 `Authorization: Bearer ...`。
- API Key secret 保存在 HA config entry，不写入日志，不放进 URL/query string。

### 7.3 响应头与非流式错误

成功响应为 `text/event-stream`，AstrBot 使用 chunked StreamingResponse 和 no-cache 响应头。

必须先检查 HTTP 状态与 Content-Type：

- 有效 SSE：进入 SSE parser。
- 401/403：认证或 scope 错误。
- 其他非 2xx：HTTP 请求失败。
- AstrBot 的准备阶段也可能返回 JSON error envelope；不能只依赖状态码，必须识别 `application/json` 和 `{ "status": "error", "message": ... }`。即使状态码为 200，也不能把该 JSON 当成 SSE。

## 8. AstrBot SSE 合同

### 8.1 线格式

AstrBot 4.29.4 的 `/api/v1/chat` 实际使用：

```text
data: {"type":"session_id","data":null,"session_id":"<UUIDv4>"}

data: {"type":"user_message_saved","data":{...}}

data: {"type":"run_started","data":{"run_id":"<run_id>"}}

data: {"type":"plain","data":"你好","streaming":true}

data: {"type":"complete","data":"你好","streaming":true}

: heartbeat

data: {"type":"end","data":""}
```

以上是实际代码中的事件结构示意，不是额外定义的自有协议：

- SSE frame 使用 `data: JSON\n\n`。
- 等待期间会发送 `: heartbeat\n\n` 注释帧。
- P3 不依赖 `event:` 名称、event ID 或 retry 字段。
- POST Chat 的第一条数据事件为 `session_id`，之后可有 `user_message_saved`、`run_started`、流式内容和 `complete`。
- `run_started` 是 Agent 运行开始的非文本生命周期事件；`complete` 是一条流式消息的完成事件。两者均忽略并继续消费后续事件，不进入 ChatLog。
- `session_id` 事件必须与请求的 ID 一致；不一致视为协议错误。
- `run_id/message_id` 是单轮执行标识，不是会话 ID，不得保存成 session_id。

### 8.2 事件处理矩阵

| SSE JSON `type` / 字段 | P3 处理 |
|---|---|
| `session_id` | 校验响应 ID 与请求 ID 一致；用于确认 AstrBot 接受了该 session |
| `user_message_saved` | 忽略正文之外的保存元数据 |
| `plain` 且 `chain_type` 为空/普通文本 | 将 `data` 字符串作为可见回答增量 |
| `plain` 且 `chain_type=reasoning` | 不加入 ChatLog、不交给 TTS |
| `plain` 且 `chain_type=tool_call` 或 `tool_call_result` | 内部工具调用记录，不加入 ChatLog、不交给 TTS |
| `agent_stats` | 只作为诊断元数据；不当作压缩事件，不送入 ChatLog |
| `message_saved` | 忽略保存元数据 |
| `run_started` | 忽略 Agent 运行开始状态；不得写入 ChatLog |
| `complete` | 忽略当前 WebChat 消息完成状态；不得将其当成整个 Chat run 的终止标志，继续等待 `end` |
| `end` | 整个 Chat run 正常完成标志；结束 delta stream 并生成 ConversationResult |
| `error` | 本轮失败；不得把它当成正常回答 |
| heartbeat 注释帧 | 忽略并继续等待 |
| 图片、文件、音频、actionrow 等非文本事件 | P3 文本范围不处理；若无可见文本，按无有效文本响应失败 |
| 未知类型 / 非法 JSON | 视为协议异常；记录不含密钥的诊断信息并终止本轮 |

所有普通可见 `plain.data` 按 SSE 到达顺序原样追加。P3 不自行做 Markdown 清洗、重新分句或文本重写；分句属于后续 TTS Provider 的职责。

### 8.3 SSE 结束条件

- 收到 `type=end`：正常结束。
- 收到 `type=error`：失败结束。
- 未收到 end/error 而连接 EOF：视为不完整响应，不得返回成功。
- 收到 end 但没有任何可见 Assistant 文本：视为无有效回答。
- 不在 SSE 断线后自动重发原 POST，避免 AstrBot 已接收请求但 HA 未收到响应时产生重复对话。

## 9. ChatLog delta 与 ConversationResult 合同

### 9.1 流式写入

使用 HA 2026.11.0 已有的 `ChatLog.async_add_delta_content_stream(agent_id, stream)`，不另造 ChatLog 写入器。

从第一个可见文本增量开始：

1. 先 yield 一次 `{"role":"assistant"}`。
2. 每收到一个可见 AstrBot 文本片段，yield `{"content":"<chunk>"}`。
3. 所有片段严格按顺序输出，不等待整个 AstrBot SSE 结束。
4. SSE 的 end 到达后，正常结束异步生成器，让 HA ChatLog 提交最终 AssistantContent。

HA 已经在 `ConversationEntity.async_process()` 中写入用户消息；P3 不重复添加用户消息，不把 AstrBot 的用户消息保存事件写回 HA。

### 9.2 最终结果

在 ChatLog delta stream 正常结束后，使用：

```python
conversation.async_get_result_from_chat_log(user_input, chat_log)
```

返回标准 HA ConversationResult。不要自己拼装一个新的历史对象，也不要绕过 ChatLog 只返回临时字符串。

### 9.3 流式能力声明

实体设置：

- `_attr_supports_streaming = True`
- `supported_languages = MATCH_ALL`（由 AstrBot 处理语言，HA Agent 不自行限制 STT 语言）

Agent 必须真的逐段调用 ChatLog delta stream；只设置 `supports_streaming=True` 而最后一次性写入全文不符合合同。

**P3 和 P5 的流式边界：**

HA 2026.11.0 的 Pipeline 可持续接收 ChatLog 增量。是否进入流式 TTS 还要求当前 TTS Stream 的 `supports_streaming_input` 为 true。P3 只负责满足 Conversation Agent 一侧；P5 的 Wyoming TTS 分句输入与 PCM 分块输出是另一份合同。不能把 P3 ChatLog 流式通过等同于已经实现首段音频播放。

## 10. 取消、错误和重试合同

### 10.1 取消

AstrBot 4.29.4 的 SSE subscriber 在 HTTP 连接关闭时会移除 subscriber，但其上游 run task 与 SSE subscriber 生命周期解耦。因此仅关闭 HA 的 HTTP response reader 不保证停止 AstrBot Agent。

4.29.4 确实提供 `POST /api/v1/chat/sessions/{session_id}/stop`，scope 为 `chat`。但必须同时满足 owner 校验：

- 通用 Chat API 的 API Key 鉴权主体由 `_require_api_key_scope()` 设为 `api_key:<key_id>`。
- `POST /api/v1/chat` 的 WebChat session creator 来自请求体 `username`。
- stop 路由将 `AuthContext.username` 传入 `ChatService.stop_session()`；该方法要求它与 session creator 完全相同。

因此，P3 统一使用 `username=api_key:<key_id>`，之后可以使用同一个 API Key 调用 stop 接口。不得用 `ha_assist` 等不同的自定义 username，否则 stop 会因 owner 不匹配而失败。

取消当前 HA Conversation 时：

1. 立即停止向 HA ChatLog 写入新的增量，并关闭当前 SSE reader。
2. 使用相同 API Key 调用 `POST /api/v1/chat/sessions/{session_id}/stop`。
3. 等待 stop 请求完成或超时后，将 HA 的 CancelledError 继续向上抛出，不返回伪造的完整回答。
4. 若 stop 请求本身失败或超时，记录不含密钥的告警并继续传播取消；不得宣称 AstrBot 上游任务已停止。

该 stop API 内部按 session 的 UMO 调用 `active_event_registry.request_agent_stop_all()`。它是 **session 级停止**，不是 run_id 级停止。由于 P3 单用户所有请求共用一个活动 session，Conversation Entity 应对该 session 的请求做串行化，使用一个轻量 asyncio.Lock，避免同一 session 的并行请求被 session 级 stop 一并终止。

### 10.2 错误处理矩阵

| 场景 | 行为 |
|---|---|
| API Key 缺失/401 | 当前请求失败，提示检查 API Key；不打印密钥 |
| scope 不足/403 | 明确提示 API Key 需要 `chat` scope |
| 派生的 `api_key:<key_id>` 被识别为 AstrBot 管理员 ID | 创建新的专用 API Key（新 key_id）并更新配置；不自动申请 `chat:admin` |
| session_id 已归属其他 username | 丢弃该映射并创建新 UUIDv4 后仅允许重试一次；仅在确定是 owner 冲突时执行 |
| 400/JSON error envelope | 读取 `message` 并转换为 HA 可读错误 |
| 网络连接失败 | 当前轮失败；不自动重发 POST |
| SSE JSON/协议错误 | 结束当前流；若请求已接受则调用 session stop（使用与 session creator 一致的 API Key 身份） |
| SSE 意外 EOF | 视为本轮未完成；调用 session stop，不生成成功结果 |
| AstrBot error 事件 | 当前轮失败；不将错误文本伪装成正常回答 |
| HA 取消当前对话 | 关闭 SSE reader，调用 owner 匹配的 session stop，再传播取消 |
| 只有元数据、无可见文本 | 以无有效响应处理 |
| HA 重启 | 下次加载 Store 后按 24 小时规则恢复或新建 session |

### 10.3 重试边界

`POST /api/v1/chat` 会创建一次真实 WebChat run。若网络在服务端接收请求后断开，HA 不能从客户端侧判断模型是否已经开始执行。因此：

- 不对同一轮 Chat POST 做自动重试。
- 认证、scope、JSON 输入等确定性错误修复后，由下一次新的用户请求触发。
- 若要在未来支持断线续流，需另行评估 AstrBot `GET /api/v1/chat/runs/{run_id}/stream` 和 run_id 持久化；P3 首版不实现自动恢复。

## 11. 配置和代码责任边界

建议代码目录：

```text
homeassistant/custom_components/astrbot/
├── __init__.py       # config entry setup/unload
├── manifest.json     # HA integration metadata
├── config_flow.py    # AstrBot URL、API Key secret、API Key key_id 配置
├── const.py          # domain、API_KEY_USERNAME_PREFIX、24h TTL
├── conversation.py   # ConversationEntity + HTTP/SSE -> ChatLog bridge
└── session.py        # 单活动 session 的 Store、UUIDv4、24h 过期判断
```

最小配置项：

| 配置 | 默认/要求 |
|---|---|
| AstrBot Base URL | 必填；NAS 上 AstrBot 的 HTTP 地址，默认端口 6185；不包含 `/api/v1/chat` 后缀 |
| AstrBot API Key | 必填；只保存在 HA config entry |
| AstrBot API Key key_id | 必填；从创建 Key 的响应或 Key 列表取得，属于非密钥元数据 |
| AstrBot username | 自动派生为 `api_key:<key_id>`；不提供独立编辑项 |
| Session inactivity TTL | 固定 24 小时；首期不增加复杂选项 |

HTTP 客户端复用 HA 的共享 aiohttp ClientSession。不要为每轮对话创建新的 ClientSession，不新增 HTTP/SSE 第三方依赖。SSE parser 只需按行增量解析 `data:` 帧、处理空行和心跳注释。

## 12. P3 验收矩阵

| 测试 ID | 测试条件 | 通过标准 |
|---|---|---|
| P3-T01 | HA 2026.11.0 加载自定义集成 | 生成可选的 `conversation.astrbot` Agent |
| P3-T02 | HA Assist 输入一条中文文本 | AstrBot 收到完全一致的 STT 文本 |
| P3-T03 | 检查请求体 | `username=api_key:<key_id>`、持久 UUIDv4 session_id、`enable_streaming=true` |
| P3-T04 | 连续多轮，HA conversation_id 不同 | 24h 窗口内 AstrBot session_id 不变 |
| P3-T05 | 模拟 HA ChatSession 超过 5 分钟后重新生成 conversation_id | AstrBot session_id 仍然复用 |
| P3-T06 | HA Core 重启，Store 记录未过期 | 重启后继续使用相同 AstrBot session_id |
| P3-T07 | 距最近活动不足 24h / 达到 24h | 前者复用，后者创建新 UUIDv4 |
| P3-T08 | AstrBot 正常 SSE | plain 文本逐段写入 ChatLog，顺序与内容完全一致 |
| P3-T09 | SSE 带 heartbeat、session_id、user_message_saved、agent_stats | 忽略元数据；不把 heartbeat/统计写入回答 |
| P3-T10 | SSE reasoning/tool_call/tool_call_result | 不写入用户回答，不进入 TTS 文本 |
| P3-T11 | SSE 正常 end | ChatLog 有 AssistantContent，返回标准 ConversationResult |
| P3-T12 | JSON error、401、403、SSE error、意外 EOF | 显示明确失败，不伪装成功，不重复提交消息 |
| P3-T13 | HA 取消对话 | 用相同 API Key 调用 session stop API 并传播取消；stop 失败时不伪称上游已停止 |
| P3-T14 | 开启后续支持流式输入的 TTS Provider | Pipeline 可接收本集成产生的 Assistant 增量；实际流式 TTS 由 P5 验收 |
| P3-T15 | 使用专用 API Key 发送 Chat 后立即取消 | Chat 请求体 `username` 与 stop 路由的 `AuthContext.username` 均为 `api_key:<key_id>`，owner 校验通过 |
| P3-T16 | 轮换为新建的专用 API Key | key_id/username 变化后创建新 session_id；旧 session 不被误用 |

## 13. P3 冻结项与后续阶段依赖

P3 冻结：

- 自定义集成域名：`astrbot`；目标实体：`conversation.astrbot`。
- AstrBot 调用接口：HTTP `POST /api/v1/chat`，不使用 MCP 传输 STT 文本。
- API Key scope：`chat`。
- 用户身份：固定派生 username `api_key:<key_id>`，与当前专用 API Key 的通用 Chat API 鉴权主体一致；这是 AstrBot 4.29.4 实现约定，升级 AstrBot 时必须复核 `API_KEY_USERNAME_PREFIX` 和 stop owner 校验。
- session_id：独立 UUIDv4，HA Store 持久化，24 小时滑动空闲期限。
- SSE → ChatLog：`async_add_delta_content_stream()`。
- HA 结果：`async_get_result_from_chat_log()`。
- 取消：HTTP `POST /api/v1/chat/sessions/{session_id}/stop`。

留给后续阶段：

- P4：HA MCP Server 和 Tivoo LLM Tools；本阶段不依赖它们，也不把它们混入 Conversation Agent。
- P5：Wyoming TTS 逐句输入与 PCM 分块输出；只有 P3 Agent 与 P5 Provider 均支持流式时，HA 才能流式 TTS。
- P6：ESP32 ↔ HA 双向通信传输层（TCP 7777/7778、MIC 消息分发接口、TTS HTTP 资源获取）；不创建 Assist Satellite。P3 的 Conversation Entity 不依赖 ESP32 存在。
- P6.5：HA Assist Pipeline/TTS Proxy/Wyoming/AstrBot 取消传播前置验证。
- P7：Tivoo Assist Satellite、ESP32 麦克风/AEC/VAD 上行及中文 Wake Word/STT 与真实语音端到端联调。
- 后续多用户：重新设计 HA user_id → AstrBot username/session_id 的映射表；不得通过把当前固定 username 临时替换成 context.user_id 来“顺便支持”。

## 14. 官方文档和源码

### Home Assistant Core 2026.11.0

- [Conversation Entity 开发文档](https://developers.home-assistant.io/docs/core/entity/conversation/)
- [ConversationInput / AbstractConversationAgent](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/conversation/models.py)
- [ConversationEntity](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/conversation/entity.py)
- [ChatLog delta stream](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/conversation/chat_log.py)
- [Conversation result conversion](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/conversation/util.py)
- [HA conversation session cleanup](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/helpers/chat_session.py)
- [Assist Pipeline delta listener and TTS stream gate](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/assist_pipeline/default_pipeline.py)

### AstrBot 4.29.4

- [HTTP OpenAPI 文档](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/docs/zh/dev/openapi.md)
- [OpenAPI Chat request schema](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/dashboard/schemas.py)
- [OpenAPI Chat route](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/dashboard/api/open_api.py)
- [OpenAPI session owner / ID validation](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/dashboard/services/open_api_service.py)
- [WebChat SSE run and event payload](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/dashboard/services/chat_service.py)
- [API Key AuthContext username](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/dashboard/api/auth.py)
- [API_KEY_USERNAME_PREFIX](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/core/workspace.py)
- [API Key creation/list metadata](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/dashboard/services/api_key_service.py)
- [WebChat session stop route](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/dashboard/api/chat.py)
- [WebChat stop owner validation](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/dashboard/services/chat_service.py)
- [WebChat per-session queue](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/core/platform/sources/webchat/webchat_queue_mgr.py)
- [Context compression documentation](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/docs/zh/use/context-compress.md)
- [Context manager implementation](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/core/agent/context/manager.py)
- [Context compressor implementation](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/core/agent/context/compressor.py)
