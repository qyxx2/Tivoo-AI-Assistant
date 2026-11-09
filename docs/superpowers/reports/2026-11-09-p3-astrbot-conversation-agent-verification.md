# P3 AstrBot Conversation Agent 验收报告

> 日期：2026-11-09
> 分支：`feature/p3-astrbot-conversation-agent`
> 本次批次：P3b6
> 状态：**本地自动化验收通过；已部署到 NAS HA；真实业务验收待用户手动完成**
> 报告范围：P3-T01 至 P3-T16，不包含 P4/P5/P6 实现。

## 1. 验收结论

P3b0–P3b5 已在本分支提交。本次 P3b6 在开发机完成了合同覆盖审计、自动化测试补齐、完整回归、静态检查和变更范围审查。

本地证据可以证明：
- HA Config Entry 能注册和卸载 `conversation.astrbot`。
- 文本输入、HTTP 请求体、username/session_id、SSE 解析、ChatLog 增量、标准 ConversationResult、会话过期策略、取消/Stop 编排及 owner mismatch 恢复均有自动化覆盖。
- HA Core 2026.11.0 的 Assist Pipeline 可以消费本集成产生的 ChatLog 增量，并在流式 TTS 输入能力开启时启动并持续读取文本流。

已将提交 `300e7aa` 中的 9 个受 Git 跟踪文件部署到 NAS 的 `/volume1/docker/homeassistant/config/custom_components/astrbot/`，逐文件 SHA-256 与提交内容一致，并重启 `homeassistant` 容器；重启后容器状态为 `running`，镜像仍为 `2026.11.0`。没有在 NAS 上运行 pytest、配置检查或 Assist 对话，也没有录入生产 API Key 或向真实 AstrBot 发送 Chat/Stop 请求。因此 HA UI 选择、真实 API Key 的 `AuthContext.username` owner 校验、HA Core 重启后的 session 恢复和真实模型多轮对话仍待用户手动验证。**P3 整体保持 BLOCKED，直至第 4 节人工验收完成。**

## 2. 本地验证环境与命令

- 开发机：Ubuntu ARM64，Python 3.14.4。
- 测试 HA Core：`homeassistant==2026.11.0`，`pytest-homeassistant==2026.11.0`。
- 项目目标 AstrBot 版本依据已冻结的 P3 合同矩阵为 4.29.4；本次只核对 HA 容器，未读取 NAS 上 AstrBot 容器的运行版本。
- HA Assist Pipeline 的导入依赖按 HA Core 对应组件 manifest 补入 `requirements_test.txt`：`mutagen==1.48.1`、`ha-ffmpeg==3.2.2`、`pymicro-vad==1.0.1`、`pyspeex-noise==1.0.2`。均为本地测试依赖，不是 AstrBot 集成运行时依赖。

最终验证命令与结果：

| 命令 | 结果 |
|---|---|
| `./scripts/test-ha.sh -q` | **91 passed, 63 warnings** |
| `.venv/bin/ruff check homeassistant/custom_components/astrbot tests/homeassistant/custom_components/astrbot` | Passed |
| `.venv/bin/ruff format --check homeassistant/custom_components/astrbot tests/homeassistant/custom_components/astrbot` | 13 files already formatted |
| `.venv/bin/python -m compileall -q homeassistant/custom_components/astrbot tests/homeassistant/custom_components/astrbot` | Passed |
| `.venv/bin/python -m pip check` | No broken requirements |
| `git diff --check` | Passed |

63 条 warning 来自 HA/aiohttp/backoff 的弃用提示和测试 HTTP server 的 `NotAppKeyWarning`，没有测试失败。仓库未配置 `mypy`、`pyright` 或 `basedpyright`，因此未声称通过类型检查。
## 3. P3-T01 至 P3-T16 自动化覆盖矩阵

| ID | 自动化结果 | 测试证据与限制 |
|---|---|---|
| T01 | PASS | Config Flow/Config Entry setup、平台注册和 unload 测试确认可创建 `conversation.astrbot`。尚未验证真实 HA Settings/Assist UI。 |
| T02 | PASS | Conversation 集成测试把包含前后空格和换行的中文输入原样送到本地 HTTP 测试端点；真实 AstrBot 接收结果待人工验证。 |
| T03 | PASS | 精确检查请求体只含 `username`、`session_id`、`message`、`enable_streaming`，username 派生规则、UUIDv4 和流式标志均被断言。 |
| T04 | PASS | 两轮对话使用不同 HA `conversation_id`，请求复用同一 AstrBot `session_id`。测试端点为本地模拟服务。 |
| T05 | PASS（组合覆盖） | 新增超过 5 分钟后 Store/Config Entry reload 仍复用 session 的测试；Conversation 集成测试另行覆盖不同 HA conversation ID。未通过实际等待 HA 定时清理任务验证 UI 会话行为。 |
| T06 | PARTIAL | Store 在 Config Entry unload/setup reload 后恢复同一 session 的自动化测试通过；这不是 HA Core 进程终止后重启的完整现场验证。 |
| T07 | PASS | 覆盖 23:59:59 复用、恰好 24h 和 25h 轮换，以及接受请求后滑动刷新 24h 空闲期限。 |
| T08 | PASS | 增量 SSE plain 文本按原顺序进入 ChatLog；测试确认上游 SSE end 前已收到首段 ChatLog delta。 |
| T09 | PASS | Parser 测试覆盖 heartbeat、session_id、user_message_saved、agent_stats 等元数据处理，不将其作为回答正文。 |
| T10 | PASS | Parser 测试覆盖 reasoning、tool_call、tool_call_result 过滤，内部链路不写入用户回答。 |
| T11 | PASS | HA 原生 ChatLog 生成 AssistantContent，并通过 `async_get_result_from_chat_log` 路径返回标准 ConversationResult。 |
| T12 | PASS | 覆盖 HTTP 200 JSON error、401、403、其他 HTTP 错误、SSE error、非法/未知事件及无 end 的 EOF；不伪造成功结果，不重复提交 Chat POST。 |
| T13 | PASS（模拟服务） | 取消测试覆盖关闭 SSE reader、同 session Stop、CancelledError 传播，以及 Stop 403/超时仍传播取消。Stop 端点是本地模拟服务。 |
| T14 | PASS（HA Pipeline 集成） | 新增测试运行 HA Core 2026.11.0 的真实 `_DefaultPipelineProcessor.recognize_intent`，通过支持 `supports_streaming_input` 的测试 TTS 流消费 AstrBot ChatLog 增量，并验证生成期间后续文本仍能进入流。没有真实音频合成/播放；那属于 P5。 |
| T15 | PARTIAL | 自动化断言 Chat 请求体 username 与 Stop 使用的 Bearer Key/相同 session 对应；不能在本地模拟服务中证明真实 AstrBot 的 `AuthContext.username` owner 校验通过。 |
| T16 | PASS（本地身份层） | key_id/Base URL 改变后生成新 session、username 跟随 key_id 变化；同 key_id 仅替换 secret 时保留 session；owner mismatch 只重试一次。真实新 API Key 的在线轮换仍需人工验收。 |

### 新增/明确的自动化覆盖

- `test_assist_pipeline_consumes_astrbot_chatlog_deltas_as_streaming_tts_input`：调用 HA Core 真实 Pipeline 意图处理器；模拟 TTS 消费者在流启动后并发读取后续文本增量。
- `test_astrbot_session_survives_over_five_minutes_and_entry_reload`：将时间推进 6 分钟后重载 Store，确认 AstrBot 活动 session 不因 HA 5 分钟 ChatSession 生命周期而轮换。
## 4. 人工验收与 BLOCKED 项

以下项目需要用户在已部署的 NAS HA/AstrBot 环境中手动验证；本次未代替用户执行这些测试。

1. **HA 部署及 UI（T01）**：部署已完成：9 个集成源文件位于 `/config/custom_components/astrbot/`，宿主机目录为 `/volume1/docker/homeassistant/config/custom_components/astrbot/`；SHA-256 与提交 `300e7aa` 一致，HA 容器已重启并确认运行。**没有做 UI 验证**；请手动在 Settings → Voice assistants / Assist Pipeline 确认可选择 AstrBot Conversation Agent。
2. **真实文本请求（T02–T04、T08、T11）**：由用户在 HA 网页 Assist 中配置专用 AstrBot OpenAPI Key（scope 仅需 `chat`，同时记录 `key_id`），发送中文文本并核对 AstrBot 收到的 message 原文、username、session_id、SSE 增量及最终回答。连续多轮需跨不同 HA conversation ID 复用活动 AstrBot session。
3. **HA 重启恢复（T06）**：真实 HA Core 重启后发起下一轮，确认未过期 Store 中的 session_id 被恢复。当前自动化只模拟 Config Entry reload。
4. **24h 与身份轮换（T07、T16）**：24h 边界已有虚拟时钟单测；现场重点确认 HA 配置使用新的 `key_id` 后 username 变更且不再使用旧 session。只替换同一 key_id 对应 secret 不应重置 session。
5. **真实取消与 owner 校验（T13、T15）**：模型生成过程中取消 HA 对话，观察 Stop 请求成功；在 AstrBot 4.29.4 真实端确认 Chat 请求 username 与 API Key 的 `AuthContext.username=api_key:<key_id>` 完全一致，Stop owner 校验通过。当前本地测试只证明客户端发出了同 key 的 Stop 请求。
6. **真实 TTS Provider（T14）**：选择后续实现中确实支持流式文本输入的 TTS Provider，验证 Pipeline 触发流式输入条件。当前假 TTS 流只验证 HA Pipeline 的消费接口，不验证 Provider 音频能力。真实 TTS 分句、PCM callback、TTS Proxy 和 Tivoo 播放仍属 P5/P6，不作为 P3 已完成证据。

**部署边界：** 本次仅连接指定 NAS，将 Git 提交中的 AstrBot 自定义集成 9 个文件复制到 HA 的 `/config/custom_components/astrbot/`，核对 SHA-256，并重启 `homeassistant` 容器确认其处于 running。未在 NAS 执行任何测试；未修改 HA 其他集成/配置，未修改生产 Config Entry，未创建/删除 AstrBot session，未使用真实 API Key。后续 UI、Assist、真实 AstrBot 与会话验收由用户手动执行。
## 5. 范围复核

本批次代码改动只涉及：

- `tests/homeassistant/custom_components/astrbot/test_conversation.py`
- `tests/homeassistant/custom_components/astrbot/test_session.py`
- `requirements_test.txt`（为 HA Core Assist Pipeline 测试导入补充测试依赖）

验收报告、P3 计划与 P3b6 进度记录仅更新 P3 文档。未修改 `homeassistant/custom_components/tivoo`、ESP32 固件、AstrBot 插件、MCP、STT/TTS Provider 或 NAS 部署文件；未实现 P4/P5/P6 功能。

README 中的 P3 项目状态本次保持不变：由于真实 HA/AstrBot 验收仍 BLOCKED，不把本地模拟测试通过表述为 P3 全部完成。

## 6. P3b6 收尾状态

- 本地自动化验收、T01–T16 覆盖审计、P3b6 报告和范围复核完成。
- AstrBot 自定义集成已部署并重启 HA 容器；真实 HA UI / AstrBot 业务验收仍由用户手动进行并保持 BLOCKED。
- P3 整体状态维持 BLOCKED，直至第 4 节人工验收证据补齐。
- 本批次只进行本地提交；不 push、不 merge。
