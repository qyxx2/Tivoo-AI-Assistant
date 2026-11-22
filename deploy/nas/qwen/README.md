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
