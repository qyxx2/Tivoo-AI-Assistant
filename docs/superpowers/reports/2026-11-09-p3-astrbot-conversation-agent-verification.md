# P3 AstrBot Conversation Agent 验收报告

> 日期：2026-11-09
> 分支：`feature/p3-astrbot-conversation-agent`
> 本次批次：P3b6
> 状态：**本地自动化验收通过；HA 网页文字对话与跨窗口上下文连续性现场通过；24h、HA 重启及取消/Stop 验收仍待完成**
> 报告范围：P3-T01 至 P3-T16，不包含 P4/P5/P6 实现。

## 1. 验收结论

P3b0–P3b5 已在本分支提交。本次 P3b6 在开发机完成了合同覆盖审计、自动化测试补齐、完整回归、静态检查和变更范围审查。

本地自动化证据可以证明 Config Entry/实体注册、请求合同、SSE 解析、ChatLog 增量、标准 ConversationResult、24h session 规则、取消/Stop 编排及 owner mismatch 恢复具备测试覆盖。HA Core 2026.11.0 的 Assist Pipeline 测试也验证了 ChatLog 增量能够被流式 TTS 输入消费端读取。

用户随后完成了真实现场验收：自定义集成可在 HA 中找到并添加，配置 Base URL/API Key/key_id 后能够连接 AstrBot；生成的 `conversation.astrbot` 实体可在 Voice assistants 中选择；HA Web 文字聊天可以正常往返并显示 AstrBot 回复；关闭聊天窗口后再次聊天仍保留此前上下文，且 AstrBot 日志确认继续使用相同用户对象和同一个 session 上下文。因此 P3 的核心文本桥接和跨窗口会话连续性已有真实环境证据。

现场尚未验证 24 小时空闲轮换、HA Core 进程重启后的 Store 恢复、HA 取消对话是否触发上游 Stop，以及真实 Stop API 的 owner 校验。用户当前使用的 HA Web 文字聊天界面没有可用的停止操作入口，因此后两项暂时无法从该界面实测。**P3 整体仍保持 BLOCKED，但不影响进入与这些未验收边界相互独立的 P4 开发；不得将剩余项目标记为通过。**

## 2. 本地验证环境与命令

- 开发机：Ubuntu ARM64，Python 3.14.4。
- 测试 HA Core：`homeassistant==2026.11.0`，`pytest-homeassistant==2026.11.0`。
- 项目目标 AstrBot 版本依据已冻结的 P3 合同矩阵为 4.29.4；本次只核对 HA 容器，未读取 NAS 上 AstrBot 容器的运行版本。
- HA Assist Pipeline 的导入依赖按 HA Core 对应组件 manifest 补入 `requirements_test.txt`：`mutagen==1.48.1`、`ha-ffmpeg==3.2.2`、`pymicro-vad==1.0.1`、`pyspeex-noise==1.0.2`。均为本地测试依赖，不是 AstrBot 集成运行时依赖。

最终验证命令与结果：

| 命令 | 结果 |
|---|---|
| `./scripts/test-ha.sh -q` | **92 passed, 63 warnings** |
| `.venv/bin/ruff check homeassistant/custom_components/astrbot tests/homeassistant/custom_components/astrbot` | Passed |
| `.venv/bin/ruff format --check homeassistant/custom_components/astrbot tests/homeassistant/custom_components/astrbot` | 13 files already formatted |
| `.venv/bin/python -m compileall -q homeassistant/custom_components/astrbot tests/homeassistant/custom_components/astrbot` | Passed |
| `.venv/bin/python -m pip check` | No broken requirements |
| `git diff --check` | Passed |

63 条 warning 来自 HA/aiohttp/backoff 的弃用提示和测试 HTTP server 的 `NotAppKeyWarning`，没有测试失败。仓库未配置 `mypy`、`pyright` 或 `basedpyright`，因此未声称通过类型检查。
## 3. P3-T01 至 P3-T16 自动化覆盖矩阵

| ID | 自动化结果 | 测试证据与限制 |
|---|---|---|
| T01 | PASS | 自动化覆盖 Config Entry setup/unload；用户现场确认自定义集成可添加、`conversation.astrbot` 实体生成，并可在 Voice assistants 中选择。 |
| T02 | PASS | 自动化验证文本原样传入本地 HTTP 端点；用户现场通过 HA Web 文字聊天与真实 AstrBot 完成消息往返并收到回复。未单独抓取生产请求体做逐字段比对。 |
| T03 | PASS | 精确检查请求体只含 `username`、`session_id`、`message`、`enable_streaming`，username 派生规则、UUIDv4 和流式标志均被断言。 |
| T04 | PASS | 自动化测试覆盖不同 HA `conversation_id` 复用同一 session；用户另行关闭 HA 聊天窗口后重新聊天，AstrBot 日志确认仍为同一用户对象和同一 session 上下文。 |
| T05 | PASS（组合覆盖） | 新增超过 5 分钟后 Store/Config Entry reload 仍复用 session 的测试；Conversation 集成测试另行覆盖不同 HA conversation ID。未通过实际等待 HA 定时清理任务验证 UI 会话行为。 |
| T06 | PARTIAL | Store 在 Config Entry unload/setup reload 后恢复同一 session 的自动化测试通过；这不是 HA Core 进程终止后重启的完整现场验证。 |
| T07 | PASS | 覆盖 23:59:59 复用、恰好 24h 和 25h 轮换，以及接受请求后滑动刷新 24h 空闲期限。 |
| T08 | PASS（文本响应链路） | 自动化确认 plain 增量在上游 end 前进入 ChatLog；现场确认修复后的 HA Web 聊天可正常接收 AstrBot 输出。现场未单独记录 UI 是否逐段刷新，因此逐段呈现仍以自动化证据为准。 |
| T09 | PASS | Parser 测试覆盖 heartbeat、session_id、user_message_saved、message_saved、agent_stats、run_started 和 complete 等元数据/生命周期事件处理，不将其作为回答正文。 |
| T10 | PASS | Parser 测试覆盖 reasoning、tool_call、tool_call_result 过滤，内部链路不写入用户回答。 |
| T11 | PASS | 自动化确认 HA 原生 ConversationResult；用户现场确认 HA Web 聊天可正常显示并接收最终回答。 |
| T12 | PASS | 覆盖 HTTP 200 JSON error、401、403、其他 HTTP 错误、SSE error、非法/未知事件及无 end 的 EOF；不伪造成功结果，不重复提交 Chat POST。 |
| T13 | PASS（自动化）/ BLOCKED（现场） | 自动化覆盖关闭 SSE reader、同 session Stop、CancelledError 传播，以及 Stop 403/超时处理；HA Web 文字聊天当前无停止入口，真实用户取消链路未实测。 |
| T14 | PASS（HA Pipeline 集成） | 新增测试运行 HA Core 2026.11.0 的真实 `_DefaultPipelineProcessor.recognize_intent`，通过支持 `supports_streaming_input` 的测试 TTS 流消费 AstrBot ChatLog 增量，并验证生成期间后续文本仍能进入流。没有真实音频合成/播放；那属于 P5。 |
| T15 | PARTIAL / BLOCKED（现场） | 自动化断言 Chat 请求体 username 与 Stop 使用的 Bearer Key/相同 session 对应；真实 AstrBot `AuthContext.username` owner 校验未通过实际取消请求验证，且当前 HA Web 聊天没有可触发取消的停止入口。 |
| T16 | PASS（本地身份层）/ BLOCKED（现场） | key_id/Base URL 改变后生成新 session、username 跟随 key_id 变化；同 key_id 仅替换 secret 时保留 session；owner mismatch 只重试一次。生产 API Key 轮换尚未实测。 |

### 新增/明确的自动化覆盖

- `test_assist_pipeline_consumes_astrbot_chatlog_deltas_as_streaming_tts_input`：调用 HA Core 真实 Pipeline 意图处理器；模拟 TTS 消费者在流启动后并发读取后续文本增量。
- `test_astrbot_session_survives_over_five_minutes_and_entry_reload`：将时间推进 6 分钟后重载 Store，确认 AstrBot 活动 session 不因 HA 5 分钟 ChatSession 生命周期而轮换。
## 4. 人工验收与 BLOCKED 项

### 已通过的现场验收

1. **集成安装与 HA UI（T01）：PASS。** 用户确认能在 HA 中找到并添加自定义集成；配置 Base URL、API Key、key_id 后连接 AstrBot 成功；HA 创建 `conversation.astrbot` 实体，并能在 Voice assistants 中新建助手、选择该实体。
2. **真实 HA Web 文字对话（T02、T11）：PASS。** 用户从 HA Web 自带文字聊天向所选对话代理发送消息，AstrBot 正常接收并生成回复，HA 页面正常显示最终输出。
3. **跨聊天窗口上下文连续性（T04）：PASS。** 用户关闭当前 HA 聊天窗口后重新聊天，仍能延续上次上下文；AstrBot 日志确认调用仍归属同一个用户对象和同一个 session 上下文。这是当前环境的真实连续性证据；现场没有单独记录两个 HA `conversation_id` 的值，跨 ID 的自动化覆盖仍作为第二层证据。

### 仍待验收 / BLOCKED

4. **生产请求身份字段（T03、T15 前置证据）：PARTIAL。** 真实聊天往返与 AstrBot 用户/session 连续性已验证；现场尚未逐字段记录生产请求的 username、key_id 派生值和 session_id，因此仍以自动化请求合同测试作为字段级证据。
5. **HA Core 重启恢复（T06）：BLOCKED。** 尚未进行真正的 HA Core 进程重启后继续会话测试；现有自动化仅覆盖 Config Entry reload。
6. **24 小时滑动期限（T07）：BLOCKED（现场）。** 自动化已覆盖 24h 边界和轮换策略，真实部署中尚未经过 24 小时窗口验证。
7. **取消与真实 Stop owner 校验（T13、T15）：BLOCKED（现场）。** 当前 HA Web 文字聊天没有可用的“停止”操作入口，无法从该界面触发取消链路。代码自动化已覆盖取消时关闭 SSE reader、调用同 session Stop、传播 CancelledError 和 Stop 失败处理；AstrBot 真实服务端的 owner 校验尚未实测。此项是长时间生成任务的取消/资源回收验收，不影响已经通过的正常完成对话。
8. **真实流式 TTS（T14）：不属于本轮现场验收。** 本地测试验证 HA Pipeline 可消费 ChatLog 增量；真实 TTS Provider 的流式输入、音频生成和播放属于后续 P5/P6，不把普通 Web 文字聊天等同于语音播放验收。
9. **API Key 轮换（T16）：BLOCKED（现场）。** 自动化覆盖新 key_id 与同 key_id secret 替换的身份规则；尚未在生产配置上轮换 API Key 实测。

**部署边界：** 首次部署复制 9 个 Git 跟踪集成文件；后续 SSE 生命周期兼容热修复只替换 `sse.py`，SHA-256 与本地提交一致，并重启 `homeassistant` 容器确认处于 running。NAS 上没有运行测试或配置检查。用户已在 HA UI 中完成集成配置和文字对话实测；本报告不记录或保存 API Key secret。未操作其他容器/服务，也未清理或删除 AstrBot 历史/session。
## 5. 范围复核

本批次代码改动只涉及：

- `tests/homeassistant/custom_components/astrbot/test_conversation.py`
- `tests/homeassistant/custom_components/astrbot/test_session.py`
- `requirements_test.txt`（为 HA Core Assist Pipeline 测试导入补充测试依赖）

验收报告、P3 计划与 P3b6 进度记录仅更新 P3 文档。未修改 `homeassistant/custom_components/tivoo`、ESP32 固件、AstrBot 插件、MCP、STT/TTS Provider 或 NAS 部署文件；未实现 P4/P5/P6 功能。

README 中的项目整体阶段状态保持不变：P3 的主文字交互已现场通过，但 HA 重启、24h、真实取消/Stop owner 和生产 API Key 轮换仍未验收，因此不把 P3 标记为全部完成。

## 6. P3b6 收尾状态

- 本地自动化验收、T01–T16 覆盖审计、P3b6 报告和范围复核完成；最新完整测试为 92 passed。
- HA 集成安装、实体选择、真实 Web 文字对话及关闭窗口后的 AstrBot session 连续性已由用户现场验收通过。
- HA Core 进程重启、24h 空闲轮换、真实取消/Stop owner 校验和生产 API Key 轮换仍未完成；P3 整体继续 BLOCKED，不更新 README 为 P3 complete。
- P4 与上述剩余项不存在实现依赖，可按总路线进入下一阶段开发；剩余 P3 验收继续列为未关闭项。
- 本批次只进行本地提交；不 push、不 merge。


## 7. 部署后 SSE 生命周期事件兼容热修复

- **现场根因：** 用户提供的 HA traceback 指向 sse.py 对 run_started 的未知事件异常。核对 AstrBot 4.29.4 源码后确认，WebChatMessageEvent.send_typing() 会发送 run_started；同一 SSE 响应还会在 visible plain chunks 之后发送 complete。这两个事件是生命周期/完成状态，不是新文本；如果只忽略 run_started，流还会在 complete 处再次失败。
- **代码改动：** 只在 _IGNORED_TYPES 中增加 run_started 和 complete。session_id、plain 文本增量、SSE error、正常 end、EOF 与未知事件校验逻辑不变。
- **回归测试：** test_parser_ignores_run_lifecycle_events_and_continues_visible_text 覆盖 session_id → user_message_saved → run_started → plain → complete → message_saved → end，断言解析器仅产出 session_id、plain 和 end。TDD RED 分别暴露 run_started 与 complete 两个未兼容事件，GREEN 后通过。
- **提交：** a020a52 — fix(p3): ignore AstrBot run lifecycle SSE events。
- **本地验证：** ./scripts/test-ha.sh -q → **92 passed, 63 warnings**；Ruff check、Ruff format check（13 files）、Python compileall、pip check、git diff --check 均通过。
- **部署：** 仅更新 /volume1/docker/homeassistant/config/custom_components/astrbot/sse.py。远端 SHA-256 与本地一致：8c97e19805e92da233379457dc4223b62df54ce6827bc34eb0d009b0c1875505。仅重启 homeassistant 容器；只读状态检查确认 running=true，镜像仍为 HA Core 2026.11.0。
- **NAS 测试边界：** 助手未在 NAS 上运行任何测试、配置检查、Assist 对话、AstrBot API 请求或日志扫描；用户的现场操作由用户本人在 HA UI 完成。未修改其他 Config Entry/session 或其他服务。当前现场已确认正常 Web 文字对话；24h、HA Core 重启、取消/Stop owner 和生产 API Key 轮换仍保持 BLOCKED，README 的 P3 完成状态不变。
## 8. 2026-11-10 生产 HA Assist Pipeline 真实 STT/AstrBot/TTS 补充验证

P3b6 报告完成后，P7A 分支补做了生产 HA Core 2026.11.0 的真实语音管线联调，结果见 [HA Assist / AstrBot / Sherpa STT-TTS 端到端补充验收报告](2026-11-10-ha-assist-astrbot-stt-tts-e2e-report.md)。

- 通过 HA WebSocket 的 `assist_pipeline/run` 从 STT 阶段送入两段仓库 16 kHz/mono/PCM16 测试 WAV；实际调用生产 `stt.sherpa_onnx_paraformer`，两轮均返回有效最终 Transcript。
- 两轮文本均经生产 `conversation.astrbot` 进入真实 AstrBot HTTP/SSE；没有使用 Mock。第二轮回答引用第一轮讨论的全球金融动荡主题，确认上下文连续。
- HA Pipeline 实际调用 Sherpa Matcha TTS；TTS Proxy 返回两份 `audio/mpeg` MP3，22.05 kHz mono，FFmpeg 全量解码均通过。
- 两轮共用 HA `conversation_id`；AstrBot 持久化 session 记录保留原创建时间并刷新 `last_activity_at`。
- 为保护用户原有设置，测试使用临时 Pipeline，完成后删除；生产 preferred Pipeline 和 Config Entry 未更改。

**边界：** 本次从 STT 阶段开始，不覆盖本轮 KWS；此前 P7A 报告已单独验证 KWS hit/miss。没有测试 INMP441、ESP32 Assist Satellite、Tivoo AUX/DAC 或扬声器实际播放。另发现生产 preferred `Astrbot` Pipeline 当前的 STT/TTS/KWS 选择仍为空；临时测试 Pipeline 的成功不等于该 preferred Pipeline 已完成语音配置。

本次补充验证提高了 P3 正常语音输入/输出集成的运行时证据，但 **P3 整体仍保持 BLOCKED**：HA Core 重启恢复、24 小时会话轮换、真实取消/Stop owner 校验及生产 API Key 轮换仍未验收。
