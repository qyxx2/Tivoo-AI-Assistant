# AstrBot HTTP OpenAPI 推理取消与 SSE 终止规格

- 日期：2026-11-13
- 适用运行版本：AstrBot 4.29.4（对应源码 tag：`v4.29.4`）
- 项目分支：`feature/p6-5-ha-cancellation-preflight`
- 状态：**真实接口已验证：活动 run 在首个可见文本输出前后均可取消**
- 上位合同：[P3 AstrBot Conversation 接口合同矩阵](2026-11-09-p3-astrbot-conversation-contract-matrix.md)
- 适用范围：HA P3 Conversation Agent 使用 AstrBot 原生 HTTP OpenAPI 停止 WebChat Agent 推理，并结束相应 SSE 流。
- 本文只规定 AstrBot HTTP/SSE 的会话身份、停止调用、事件终止和 HA 适配流程；不重新定义 HA Pipeline、TTS Proxy/Cache、Wyoming 或 ESP32 的生命周期。

## 1. 目标与结论

AstrBot 4.29.4 的现有 HTTP OpenAPI 已提供停止 WebChat session 中活动 Agent 任务的接口：

```http
POST /api/v1/chat/sessions/{session_id}/stop
```

停止接口不是通过关闭 SSE TCP/HTTP 连接来替代的。关闭 SSE reader 只结束当前客户端的订阅/读取；需要同时调用 Stop，才能要求 AstrBot 终止 session 对应的 Agent run。

真实运行实例验证已证明：当 Chat SSE 已进入 `run_started`、Agent run 正在执行且尚未产生第一段可见 `plain` 文本时，使用正确的 API Key/session owner 调用 Stop，AstrBot 返回 `stopped_count: 1`，随后 SSE 发送 `complete` 和 `end`，没有产生新的 `plain` 文本，session 详情显示 `is_running=false`、`active_runs=[]`。

**关键约束：Stop 是 session 级，不是 run_id 级；Stop 的 API Key 身份必须与 Chat session creator 完全一致。**

## 2. 接口合同

### 2.1 认证

Chat 和 Stop 均使用 AstrBot OpenAPI Key，认证头为：

```http
Authorization: Bearer <ASTRBOT_API_KEY>
```

项目专用 API Key 至少需要 `chat` scope。不得把 API Key secret 放入 URL、query string、日志或规格文件。

对于 API Key 鉴权，AstrBot 4.29.4 的认证上下文用户名是：

```text
api_key:<key_id>
```

`key_id` 是 API Key 的非密钥标识，不能从 secret 猜测或截取生成。

### 2.2 Chat 请求

```http
POST /api/v1/chat
Accept: text/event-stream
Content-Type: application/json
Authorization: Bearer <ASTRBOT_API_KEY>
```

项目 P3 使用的请求体：

```json
{
  "username": "api_key:<key_id>",
  "session_id": "<UUIDv4>",
  "message": "<用户输入文本>",
  "enable_streaming": true
}
```

字段规则：

| 字段 | 规则 |
|---|---|
| `username` | 必须是 `api_key:<key_id>`，与 API Key 鉴权主体一致 |
| `session_id` | 使用 P3 SessionManager 持久化的活动 UUIDv4 |
| `message` | 当前用户输入文本 |
| `enable_streaming` | 固定为 `true` |

AstrBot 的 Chat 准备阶段也可能以 JSON error envelope 返回错误；不能只看 HTTP 状态码。只有响应 `Content-Type` 为 `text/event-stream` 才能交给 SSE parser。HTTP 200 + JSON 不是有效 SSE 响应。

P3 当前由 HA SessionManager 生成并持久化 UUIDv4，再将同一个 ID 放入 Chat body；不要为每一轮另行调用会话创建接口而绕过现有的 session 管理。

### 2.3 Stop 请求

```http
POST /api/v1/chat/sessions/<session_id>/stop
Authorization: Bearer <同一个 API Key>
```

Stop 路由从鉴权上下文取得调用方用户名，并要求数据库中目标 session 的 `creator` 与该用户名完全相同。成功响应示例：

```json
{
  "status": "ok",
  "message": null,
  "data": {
    "stopped_count": 1
  }
}
```

`stopped_count` 是本次请求实际要求停止的活动 Agent run 数量。实测活动 run 返回 `1`。若为 `0`，只说明本次没有命中活动 run，不能据此宣称刚才某个仍在运行的推理已经被停止；应结合 session 的 `is_running` / `active_runs` 和 SSE 状态判断。

### 2.4 身份一致性是硬条件

以下三个身份必须匹配：

1. Chat 请求鉴权产生的 API Key `AuthContext.username`；
2. Chat body 的 `username`，它用于创建/归属 WebChat session；
3. Stop 请求鉴权产生的 API Key `AuthContext.username`。

本项目固定使用 `username = "api_key:" + key_id`。不能用 `ha_assist`、`diagnostic-owner` 或每次随机生成的其他用户名替代。

错误用户名会导致 Stop 返回业务错误 `Permission denied`，即使 HTTP 状态为 200，且 Chat SSE 本身正在正常产生内容。此前使用自定义 username 的测试失败是 owner 不匹配，不是 Stop API 不具备停止能力。正确处理方式是从实际 API Key 元数据取得 key_id，并让 Chat body 使用对应的 API Key owner；不得为了绕过检查而放宽服务端 owner 校验。

## 3. SSE 事件与停止语义

### 3.1 事件边界

AstrBot 4.29.4 Chat SSE 的主要数据事件：

| 事件 | 含义 | P3 行为 |
|---|---|---|
| `session_id` | 确认本次 WebChat session | 校验与请求 ID 完全一致，并持久化/确认会话 |
| `user_message_saved` | 用户消息已保存 | 忽略元数据 |
| `run_started` | Agent run 已启动 | 忽略状态帧，继续读取 |
| `plain` | 输出内容片段 | 仅普通可见文本按顺序进入 HA ChatLog |
| `complete` | 当前消息/响应内容完成帧 | 不是整个 Chat run 的终止标志；继续等待 |
| `end` | Chat run 的正常终止帧 | 结束本轮 SSE 消费 |
| `error` | Chat run 错误 | 作为失败处理，不伪装为正常回答 |
| SSE 注释 heartbeat | 保活帧 | 忽略并继续读取 |

`complete` 和 `end` 不可混用。P3 parser 必须继续等待 `end`；若连接在收到 `end` 前 EOF，应视为不完整响应，而不是正常结束。

### 3.2 真实 Stop 后的事件顺序

真实 AstrBot 4.29.4 实测（2026-11-13）：

```text
session_id
user_message_saved
run_started
  -- POST /api/v1/chat/sessions/{session_id}/stop -->
complete
end
```

Stop 后没有新增 `plain` 事件。这里的顺序是**Stop 请求在 SSE reader 仍保持打开时发出**的协议验证方式；与 HA P3 生产取消流程的调用顺序不同，见 §4。

## 4. HA P3 生产取消流程

### 4.1 生命周期顺序

P3 Conversation Agent 是 AstrBot SSE reader 和 AstrBot session Stop 的唯一 owner。HA/Tivoo Satellite 层只取消自己的 Pipeline 调用 task，不直接请求 AstrBot Stop，也不复制 P3 会话身份逻辑。

当 HA 取消当前 Conversation 时，`homeassistant/custom_components/astrbot/conversation.py` 按以下顺序执行：

1. **接收取消：** ChatLog delta 消费循环收到 `asyncio.CancelledError`。
2. **关闭 SSE reader：** 显式调用 `deltas.aclose()`。关闭异步生成器会退出 `async with api_client.async_chat(...)`，由 aiohttp response context manager 关闭当前 HTTP SSE response。
3. **判断是否需要 Stop：** 只有 Chat response 已被接受、且尚未收到正常 SSE `end` 时才发送 Stop。未启动/未接受的请求，以及已经正常结束的 run，不需要 Stop。
4. **调用 Stop：** 使用原 session_id 和同一 AstrBot API Key 调用 `POST /api/v1/chat/sessions/{session_id}/stop`。每次取消路径只调用一次。
5. **等待与传播：** 当前实现最多等待 10 秒。Stop 请求失败或超时时记录不含密钥的 warning；随后继续抛出原始 `CancelledError`，不得返回伪造的完整回答。
6. **释放本地资源：** `finally` 再次执行幂等的 `deltas.aclose()`，退出当前 Conversation 锁，允许下一轮处理。

注意：生产流程先关闭 SSE response，再发 Stop，所以生产调用方不依赖自己还能读到 Stop 后的 `complete/end` 帧。Stop 的作用是让服务端 run 停止；客户端 SSE reader 的释放由本地 response close 完成。

### 4.2 为什么需要显式 Stop

AstrBot 4.29.4 的 SSE subscriber 与上游 Agent run 生命周期解耦。关闭 HA 侧 SSE response 可以终止当前连接读取，但不能作为上游推理已终止的充分证据。因此 P3 在取消和已接受流的协议/传输异常路径显式请求 Stop。

### 4.3 Stop 是 session 级操作

Stop service 根据 session 构造 WebChat 的 unified message origin，然后调用该 origin 下的活动 Agent stop registry。其作用范围是该 session 的活动 run，不是单个 `run_id`。

项目 P3 当前一个单用户只维护一个活动 AstrBot session，并用 `asyncio.Lock` 序列化 Chat 请求。不要允许同一个 session 上两个 Chat 请求并发执行，否则一个请求调用 session Stop 可能同时停止同 session 的其他活动 run。

## 5. 错误与边界处理

| 情况 | 要求 |
|---|---|
| Chat 401 | API Key 无效/缺失；作为认证失败处理，不重试原消息 |
| Chat 403 | API Key 缺少 `chat` scope 或权限不足；作为授权错误处理 |
| Chat HTTP 200 + JSON error | 不是 SSE；按 JSON error envelope 处理，不能交给 SSE parser |
| Chat HTTP 200 + 非 SSE Content-Type | 响应协议错误 |
| Stop 返回 owner `Permission denied` | 先检查 `username` / session creator / API Key principal；不要当作模型停止失败后盲目重试 |
| Stop HTTP 401/403/其他非 2xx | 记录失败；仍传播原始 HA cancellation/error，不伪报远端停止成功 |
| Stop 超时 | 当前 P3 超时值 10 秒；记录 warning，保留原始取消语义 |
| Stop 返回 `stopped_count=0` | 不声称本次停止了活动 run；结合 session 状态判断本来已结束、未命中活动 run，或调用时序不符 |
| SSE 收到 `complete` | 继续等待 `end` |
| SSE 收到 `end` | 正常结束当前 run |
| SSE 在 `end` 前 EOF | 不完整流；若请求已接受且未完成，则按 P3 合同请求 Stop |
| 已收到正常 `end` 后取消上层消费 | 不再 Stop 已完成的 run；继续按 HA 的取消语义退出 |

Stop 请求失败时，不能吞掉最初的 `CancelledError`，也不能声称 AstrBot 端已经停止。不要通过全局 task 扫描、猜测 task name、关闭 AstrBot 容器或删除 session 的方式代替公开 Stop API。

## 6. 已验证行为与未覆盖范围

### 6.1 真实 AstrBot 4.29.4 HTTP/OpenAPI 实测

- 日期：2026-11-13
- 方式：Ubuntu 开发机通过 SSH 对用户现有 NAS 上的 AstrBot 实例执行一次性 HTTP API 验收；API Key 只在 NAS 本地受限文件读取，secret 没有输出、复制到项目或写入 Git。
- 真实运行版本：AstrBot 4.29.4。
- Chat：HTTP 200，Content-Type 为 `text/event-stream; charset=utf-8`。
- Stop 触发前收到：`session_id`、`user_message_saved`、`run_started`。
- Stop：HTTP 200，`stopped_count=1`。
- Stop 后 SSE：`complete`、`end`；新增 `plain` 事件数为 0。
- session detail：creator 与本次 API Key owner 匹配；`is_running=false`；`active_runs` 数量为 0。
- Cleanup：测试 session 删除接口 HTTP 200，专用测试会话已清理。

### 6.2 证据范围限制

Stop 在收到 `run_started` 后立即触发，Stop 前尚未收到第一段可见 `plain` 文本。B6 另在首条非空 `plain` 后发起 Stop，得到 `stopped_count=1`，Stop 成功响应后无新增 `plain`，SSE 收到 `complete` 和 `end`。详见 [B6 真实 AstrBot 验收](../reports/2026-11-13-p6-5b6-cancellation-owner-closeout.md#真实-astrbot-验收)。

P3 本地自动化测试已覆盖取消时先关闭 SSE reader、同一 session Stop 只调用一次、Stop 403/超时不吞掉 `CancelledError`、锁释放后后续请求可继续；这些用例使用本地 fake HTTP/SSE 端点，不等同于真实 AstrBot 模型推理验收。

本规格只证明 AstrBot 端 HTTP/SSE 的停止机制。它不证明 HA TTSCache producer、HTTP TTS consumer queue、Wyoming writer 或 P7A TTS request 会随 Pipeline 取消而终止。P6.5b3/b4 已将这些下游活动 TTS owner 缺口独立标记为 GAP；不得将 AstrBot Stop 通过扩展解释成整条语音输出链已取消。

## 7. 项目实现映射

| 责任 | 项目位置 | 现有行为 |
|---|---|---|
| HTTP Chat / Stop client | `homeassistant/custom_components/astrbot/api.py` | Bearer auth；Chat 设定 SSE Accept 与 JSON body；Stop 使用同一认证头 |
| 会话 owner / session_id | `homeassistant/custom_components/astrbot/session.py` | `api_key:<key_id>`；UUIDv4 + HA Store；24 小时空闲 TTL |
| SSE reader 与取消编排 | `homeassistant/custom_components/astrbot/conversation.py` | 关闭 delta generator / response 后，对同一 session 调用 Stop；10 秒超时；保留取消传播 |
| SSE parser | `homeassistant/custom_components/astrbot/sse.py` | 忽略 `run_started`/`complete`；必须等待 `end`；EOF-before-end 为不完整流 |
| 自动化合同 | `tests/homeassistant/custom_components/astrbot/test_conversation.py` | fake endpoint 覆盖 stop 顺序、owner username、调用次数、Stop 失败/超时及锁释放 |

## 8. 验收要求

后续升级 AstrBot 或修改 P3 取消实现时，至少重新确认：

- [ ] AstrBot 实际版本与 `v4.29.4` 的接口差异已核实。
- [ ] Chat 返回有效 `text/event-stream`，并收到与请求一致的 `session_id`。
- [ ] Chat body 的 `username` 与 API Key principal 完全一致。
- [ ] 活动 run 上调用 Stop 返回成功，且 `stopped_count` 与观测到的活动 run 相符。
- [ ] Stop 后没有继续产生新的 `plain` 内容；session 详情不再报告活动 run。
- [ ] SSE 终止事件语义仍为 `end`；不能把 `complete` 单独视为 run 结束。
- [ ] 真实测试覆盖至少一个已产生部分可见文本后的中途取消场景。
- [ ] P3 自动化回归通过：`./scripts/test-ha.sh tests/homeassistant/custom_components/astrbot/test_conversation.py -q`。
- [ ] Stop 失败或超时时原始 HA cancellation 仍传播，且不会泄漏 API Key。

## 9. 官方接口与源码依据

- [AstrBot HTTP OpenAPI 官方文档](https://docs.astrbot.app/dev/openapi.html)
- [AstrBot 4.29.4 OpenAPI Chat route](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/dashboard/api/open_api.py)
- [AstrBot 4.29.4 API Key authentication](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/dashboard/api/auth.py)
- [AstrBot 4.29.4 API Key username prefix](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/core/workspace.py)
- [AstrBot 4.29.4 session Stop route](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/dashboard/api/chat.py)
- [AstrBot 4.29.4 Stop service and owner check](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/dashboard/services/chat_service.py)
- [Project P3 contract matrix](2026-11-09-p3-astrbot-conversation-contract-matrix.md)
- [P6.5 cancellation preflight report](../reports/2026-11-11-ha-cancellation-preflight-report.md)
