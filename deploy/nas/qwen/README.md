# Qwen Frontend MCP — P6.8 B8.3

本目录仅交付 Qwen Audio Agent **2.1.0** 的配置策略补丁、模板和本地测试。
B8.3 不部署：没有修改 NAS Qwen 安装包、config.env、frontend-mcp.json、HA 或 ESP32。
实际生产 URL、专用 HA 用户 Token 和完整工具白名单统一在 **B8.7** 核对并写入。

## 锁定来源和补丁

上游：<https://github.com/QwenAudio/qwen-audio-agent>，2.1.0 对应提交
`a9f4478da8df400d04facbb099ac2933ce8b11bc`。NAS 安装根目录为
`/usr/local/lib/node_modules/qwen-audio-agent`。本批只读核对安装版本为 2.1.0，
以下 config 原文件 SHA256 与 NAS 一致：

`361c6bd6afbd73aeb3519991227e7b2688b65004465788095545d3635d0965da`

补丁 `patches/0001-frontend-mcp-private-http.patch` 只修改
`server/src/frontend/tools/mcp/frontend-mcp-config.mjs`。
Qwen 原有 `FrontendMcpClient` 使用 MCP SDK `StreamableHTTPClientTransport`，
以 `requestInit.headers` 传入配置头；无需增加 HA MCP Server、代理或 GCP Client Action。

新增 `QWEN_AUDIO_FRONTEND_MCP_ALLOW_PRIVATE_HTTP=true`，默认关闭，精确匹配小写字符串 `true`。
例外只允许 URL 解析后落在 `10/8`、`172.16/12`、`192.168/16` 的 IPv4 字面地址，
且必须有合法 `Bearer <token>` 认证头。域名不做 DNS 推断，IPv6/ULA、link-local、CGNAT、
公网 HTTP 均不放行。URL 中的用户名/密码、fragment、非法协议仍拒绝。
远程 HTTPS 和原有 loopback 行为保持原样（原版 loopback HTTP 不允许头）。
这是配置 URL 策略，不提供 HA 服务端权限管理，也不改变 SDK 网络行为。

B8.7 应先保存原安装文件、config.env、镜像 digest 和持久配置，核对上述原文件 hash，
再在锁定构建/部署副本中以 `patch --batch --fuzz=0 -p1` 应用补丁，验证后部署。
hash 不符时停止应用并重新审查；不使用宽松 fuzz。回滚恢复原文件和环境设置并重启 Gateway。
保留已有 DashScope 设置和 `semantic_vad_ec` 补丁。**不要现在在运行容器中执行部署。**

## 模板和环境引用

`frontend-mcp.json.example` 是单一 `homeassistant` Streamable HTTP server 模板。
`HA_ASSIST_MCP_URL` 是完整 URL 占位环境变量；B8.7 核对实际内网地址/端口后设置，
路由固定使用现有 `/api/mcp/assist`。JSON 的 `authorization` 引用完整
`${HA_MCP_AUTHORIZATION}`，环境值为 `Bearer <专用非管理员用户 Token>`。
不要写成 `Bearer ${HA_TOKEN}`：Qwen 只展开整个字符串恰好为 `${NAME}` 的引用。

B8.7 需要的环境键（仅列键名/非秘密值）：

- `QWEN_AUDIO_FRONTEND_MCP_CONFIG=/root/.config/qwaudio/frontend-mcp.json`
- `QWEN_AUDIO_FRONTEND_MCP_ALLOW_PRIVATE_HTTP=true`
- `HA_ASSIST_MCP_URL`：部署时核对的完整 HA Assist MCP URL
- `HA_MCP_AUTHORIZATION`：完整 Bearer 值，仅存在 NAS 受限权限的 config.env/secret

模板中两个 `REPLACE_WITH_EXACT_*_TOOL_NAME` 都是待替换的白名单占位符；
不能直接作为生产配置启用。部署前用实际 NAS HA `tools/list` 中的完整名称替换并
逐项列出所有要启用的工具，不复制本地测试列表。发现缺失启用项时 Qwen 会将整个
server 标为 error，工具不进入模型目录。不得通过删掉 allowlist 或开启通配来绕过。

## 白名单与权限策略

沿用 [P4 合同](../../../docs/superpowers/specs/2026-11-09-p4-ha-mcp-tool-contract-matrix.md)：

| 能力 | 选择规则 |
|---|---|
| HA 实体查询/读状态 | 仅选实际 tools/list 中面向 Assist 已暴露实体的查询工具 |
| HA 实体控制 | 仅选家庭语音所需的已暴露实体控制工具；不授予任意服务调用或管理能力 |
| Tivoo 显示/表达 | 保留当前 P4/P6.8 合同内的表情、心情、文字、时钟、图像/动画等已注册能力 |
| Tivoo 设备控制 | 保留当前 P4/P6.8 合同内的音量、亮度、屏幕、倒计时、游戏及其余已授权设备服务工具，参数/权限继续由 HA 校验 |
| 其他能力 | 不属于现有合同的新工具默认不启用；部署时有明确需求再独立审查 |

Qwen 不支持配置级 `readOnly`/`approval` 策略，不能添加这些字段假装限制写操作。
实际边界是 HA 专用用户、Assist 实体暴露清单、Tivoo Tool/Service schema 和权限。
`SetMood` 等工具不扩大公开 schema，不从 Qwen call_id 伪造 HA Context；关联限制仍按 P6.8 合同。

配置 `tools` 的键为 HA 返回的原始名称，模型看到的名称为 `mcp__homeassistant__<原始工具名>`。
上游会把非字母数字下划线字符替换成 `_` 并限制总长度 128，部署时须检查名称碰撞。
白名单覆盖当前已授权合同能力；既不把开发测试的工具数量当作上限，也不自动启用 NAS 新出现的非合同能力。
未列出或 `enabled=false` 的工具不暴露。

### B8.7 冷启动门

生产部署同时安装 `wait-ha-mcp.mjs` 与 `qwen-entrypoint.sh`。Compose 将二者只读挂载到容器，
并用 `qwen-entrypoint.sh` 替换镜像默认 entrypoint；脚本先调用真实 HA `/api/mcp/assist`
`tools/list`，从持久 `frontend-mcp.json` 读取 `homeassistant` server 中所有 `enabled=true`
的工具名。只有这些工具全部出现在实时目录后，才执行原始 `qwenaudio gateway --lan`。

这不是第二套 MCP client，也不缓存 tools/list；它只解决 HA 与 Qwen 同时冷启动时 `/api/mcp/assist`
可能先 404、再返回部分工具，而 Qwen 2.1.0 Frontend MCP 只做一次启动发现的问题。等待上限
120 秒；超时进程退出，由 Compose `restart: unless-stopped` 重新尝试。日志只记录 HTTP 状态、
缺失工具数量和最终发现/要求数量，不输出 Authorization。运行中的 HA 重启不依赖此门：B8.7
真实验证中，既有 Qwen MCP client 在 HA 恢复后可继续调用工具。

NAS Compose 保留原 `init`、端口、env_file 和其他 mounts，只增加：

```yaml
services:
  qwen-audio-agent:
    restart: unless-stopped
    entrypoint: ["/bin/sh", "/usr/local/lib/tivoo/qwen-entrypoint.sh"]
    volumes:
      - ./startup/qwen-entrypoint.sh:/usr/local/lib/tivoo/qwen-entrypoint.sh:ro
      - ./startup/wait-ha-mcp.mjs:/usr/local/lib/tivoo/wait-ha-mcp.mjs:ro
```

宿主将仓库这两个文件复制到 Qwen Compose 目录的 `startup/`；不要把 token 写入脚本或 Compose。

本地定向测试：

```bash
node --test deploy/nas/qwen/tests/wait-ha-mcp.test.mjs
```

覆盖 endpoint 404、部分工具、完整工具与始终缺工具 fail-closed。

上游上限：8 server、每 server 64 tool policy；连接超时 100–30000 ms，
单次调用超时 100–30000 ms，结果 1024–65536 bytes，每工具每 turn 1–4 次。
模板选用 1 server、8 s 连接、10 s 调用、32 KiB 结果、每工具每 turn 2 次。
MCP 结果作为不可信事实材料送回模型，不能覆盖系统/用户指令。

## 本地验证

需要 Node 22+、Git、patch、npm 和一个本机 RFC1918 IPv4 网卡（测试 HTTP server 绑定本机私网地址，
不访问 NAS/HA）。准备包含锁定提交的上游 Git checkout，然后运行：

```bash
bash deploy/nas/qwen/patches/test.sh /path/to/qwen-audio-agent-v2.1.0
```

脚本从锁定提交创建临时源码副本，通过 hash 校验后先跑原版 RED，再应用补丁跑 GREEN。
仅在临时目录以锁定依赖安装测试运行时，`--ignore-scripts`；不修改传入 checkout。
可设置 `QWEN_B83_NODE_MODULES=/absolute/path/to/node_modules` 复用已安装测试依赖。
脚本退出时删除临时副本。测试中的 Bearer 值只是假凭据。

覆盖：RFC1918 边界与默认关闭、HTTPS/loopback 回归、环境引用/认证/URL 拒绝；
真实 Qwen Client + MCP SDK 对本机无状态 JSON-RPC mock server 的 initialize、
initialized、tools/list、tools/call；白名单、UTF-8 结果上界、超时/取消、HTTP 401、
JSON-RPC/工具错误；真实 ToolCallHandler + RealtimePresentationRuntime + AnnouncementWindow
在中间 audio.done/response.done 后保留同一 turn，待工具结果回传再请求后续模型响应。
模型网络接口是内存测试边界，没有实时模型生成、物理输出或真实设备命令。

另跑 HA endpoint 回归：

```bash
PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath" bash scripts/test-ha.sh \
  tests/homeassistant/custom_components/tivoo/test_tivoo_p4b5_mcp_http.py -q -p no:cacheprovider
```

真实 HA Token 拒绝、NAS tools/list、HA 实际工具调用以及 NAS MCP 配置部署归 B8.7。

## B8.5 最小终态兼容补丁（仅打包）

用户已批准 B8.5 的最小兼容补丁。`patches/0002-response-terminal-status.patch`
保留 GCP 7.0 的现有事件及 `audio.done.responseId`、`turnId`，增加：

| 字段 | 值与含义 |
|---|---|
| `responseStatus` | `completed` / `failed` / `cancelled` / `incomplete` / `unknown`；未提供或未知 provider 状态归为 `unknown` |
| `awaitsToolFollowUp` | boolean；上游本次响应是否等待工具后续响应 |
| `hasFunctionCall` | boolean；本次响应是否包含函数调用；即使上游抑制后续总结，也不能据此响应开启续聊 |

客户端在 `session.hello.capabilities` 请求 `response.terminal-status`，并检查
`session.ready.capabilities` 的交集回显。旧版相同版本号不能证明支持该补丁；未回显时终态门禁失败。
补丁在 WebSocket `/api/realtime` 的原有事件路径发布字段，无新增 GCP event 或版本变更。
只有三个字段全部存在且类型正确、`responseStatus === "completed"`、
`awaitsToolFollowUp === false`、`hasFunctionCall === false` 时，才具备可用于续聊判断的模型成功终态条件。
物理播放完成、文本最终完成及其他会话条件仍由 HA 独立检查。
`audio.done` 是一次模型响应的结束，工具中间响应也会发送它；不能把它独自当作整轮完成。
`hasFunctionCall=true` 且 `awaitsToolFollowUp=false` 的正常工具受理语音允许结束 PCM，
但必须等待本轮全部已观察工具成功结束再完成交付；结果 `followup_eligible=false`，
关闭 socket，不能由工具中间文字开启续聊。`awaitsToolFollowUp=true` 继续等待后续响应，
缺失应到的工具/文本/物理回执仍有界超时清理。

补丁只增加可观测性，不改变工具执行/后续响应策略。旧 producer 的 schema 字段仍为 optional，
保留旧消息解析；补丁 producer 在两个 `audio.done` 发送点均附加全部字段，provider error
路径标记 `failed`。原有 schema passthrough、session encode 与 JSON 序列化保留新字段。
取消/不完整响应之后迟到的文字不会把其终态升级为 completed；正常响应允许终态先于最终文字。
被 upstream 抑制而无 `audio.done` 的响应不生成成功证据，由 HA 的取消/超时路径收敛。

修改上游三个文件：`server/src/voice/realtime-presentation-runtime.mjs`、
`shared/protocol/gateway-events.mjs`、`shared/protocol/gateway-client-protocol.mjs`。
锁定提交同上，原文件 SHA256 记录在 `patches/terminal-source.sha256`。
安装前须逐项核对目标文件 hash，使用 `patch --batch --fuzz=0 -p1`；
hash 不符必须重新审查。0001 与 0002 修改不同文件，可顺序应用。
B8.5 没有安装此补丁、修改运行中的 NAS 或进入 B8.6/B8.7。
B8.7 部署前仍需备份并验证，回滚恢复这三个原文件；保留既有 provider/VAD 配置。

独立验证入口（不改变 B8.3 的 `test.sh`）：

```bash
bash deploy/nas/qwen/patches/test-terminal.sh /path/to/qwen-audio-agent-v2.1.0
```

需要 Node 22+、Git、patch、npm、ripgrep。可设置
`QWEN_B85_NODE_MODULES=/absolute/path/to/node_modules` 复用锁定依赖。
脚本从锁定提交创建临时 archive，校验原 hash，先确认原版断言 RED，再应用 0002 并跑
终态、协议、presentation 和 session 定向测试；不运行全量 suite，不修改传入 checkout。
本地结果为原版 20 个预期断言失败（1 个兼容性用例通过），补丁后 100/100 通过。
覆盖状态枚举、缺失/未知状态、最终问句后的取消/不完整、工具中间响应及抑制总结、
迟到文本、provider failure、capability 正向协商/未协商、schema 类型拒绝和真实 encode/JSON
字段保留，以及旧客户端消息兼容。没有调用模型网络、HA、NAS 或物理设备。

## P6.8 Prompt overlay（B8.5 交付，B8.7 合并）

`prompt-overlay.md` 是需追加到完整 Prompt 的最小片段，遵循
[续聊设计 §2](../../../docs/superpowers/specs/2026-11-22-p6-8-qwen-realtime-followup-design.md)。
B8.7 从实际部署的锁定镜像提取完整 `config/frontend-agent/PROMPT.md`，
保留原有工具、路由、权限及核心规则，再将该片段追加到副本末尾。
不得用此片段替换整个 `PROMPT.md`，也不能仅放入 `ASSISTANT.md`。
合并后校验完整内容/hash 及总长度不超过 16,000 字符，放入持久配置目录，
再设置 `QWEN_AUDIO_AGENT_FRONTEND_PROMPT_DIR` 并按 B8.7 流程重启验证。
升级时从新锁定版本完整 Prompt 重新合并。
本批只维护片段，没有安装 Prompt、设置环境变量或重启 NAS。

## HA Bridge 接入（B8.5）

HA 进程读取 `TIVOO_QWEN_GATEWAY_URL`（默认 `ws://127.0.0.1:3101/api/realtime`）
和 `TIVOO_QWEN_GATEWAY_TOKEN`（仅环境 Secret）。URL 的 `sessionId` 固定为 ConfigEntry
entry_id，客户端实例为 `tivoo-<entry_id>`。B8.7 需配置实际可达地址和 Token，并先安装
0002；原版 2.1.0 会在 capability 协商时被明确拒绝，没有旧 Pipeline fallback。

每轮 HTTP PCM 缓存上限 512 KiB，只接受 24/32 kHz mono S16LE；
`/api/tivoo/qwen/audio/{stream_id}` 是随机 UUID 单次 GET capability，不持久化或记入本模块日志。
GET 等待上限 10 秒，每次读/写停滞 10 秒；Gateway 事件/物理完成等待上限 45 秒，
整轮上限 120 秒，取消的设备 stop、socket/HTTP join 各 5 秒；静音尾帧 50 × 20 ms。
日志仅含 generation、输入/输出字节数和阶段耗时。

Bridge 返回 `QwenResult`，保留精确最终文本和 turn/response identity，另有
`followup_eligible`。显式 `owner.keep_socket=true` 可将已成功且具备续聊资格的原 socket
保留最多 5 秒；接收者必须传匹配 `parent_session_id`，禁止连接缺失时重连冒充续聊。
只有未来 B8.6 的授权调用者可以设置该标志；当前 Satellite 不解析问号，不发 0x27。
旧 owner 的重复 close 不关闭已保留的连接；超时、异常及 unload 均关闭。
