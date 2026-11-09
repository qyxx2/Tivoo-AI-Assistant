# P4b5 实施报告：HA Assist MCP 协议验证与 AstrBot 运行时边界

日期：2026-11-09
分支：feature/p4-ha-mcp-server
批次基线：92182ea406103bfa1f7d63c899616c555ac91135

## 1. 范围与结论

本批次仅处理 P4b5：核对并复用 AstrBot 4.29.4 内置 MCP Client 的接入方式，验证 HA Core 2026.11.0 原生 Assist MCP endpoint 与七个 Tivoo MVP Tool 的协议和服务调用链，并记录实际 Persona/重连验证状态。

没有新增 AstrBot 插件、第二套 MCP Client、HA MCP Server、任意 HA Service 调用器或生产部署配置。没有修改 P3 对话集成、ESP32 固件、TCP 7777/7778、SPP 或 NAS。

**本地协议与服务链路 PASS；AstrBot WebUI、真实 Persona 授权和 AstrBot 重连故障注入 BLOCKED。** 当前开发机没有可运行的 AstrBot 4.29.4 实例/WebUI，也没有目标 HA/AstrBot 凭据。P4b5 批次计划明确允许这种情况下完成本地接口验证并将目标运行时项标为 BLOCKED。本报告不把 MCP SDK 测试等同于 AstrBot 实际运行时测试。

## 2. 接入合同与 AstrBot 源码核对

保持既有计划中的配置合同，不在仓库创建真实凭据：

- Server name：home-assistant-tivoo
- Transport：streamable_http
- URL：http(s)://<HA LAN host>:8123/api/mcp/assist
- Header：Authorization: Bearer <HA Long-Lived Access Token>
- Token 所属账号：专用普通 HA 用户，不使用 HA 管理 API，不授予管理权限。

按计划固定的 AstrBot 4.29.4 提交检查其内置 MCP Client：
- 源文件：astrbot/core/agent/mcp_client.py
- 固定提交：61335414433db721b3f7ecc93f90deafe0a59d78
- 源码链接：https://github.com/AstrBotDevs/AstrBot/blob/61335414433db721b3f7ecc93f90deafe0a59d78/astrbot/core/agent/mcp_client.py
- Streamable HTTP 分支读取 url 与 headers，构造 MCP HTTP client，建立 ClientSession 并执行 initialize；随后 list_tools_and_save 调用 tools/list。
- 因此不需要自制 MCP Client 或 AstrBot 扩展。WebUI 的实际字段录入和 Persona 工具授权仍需要目标实例，未作静态猜测。

### 重连与非幂等风险

该固定版本的 call_tool_with_reconnect 捕获 anyio.ClosedResourceError 后执行 _reconnect（新建连接并刷新 tools/list），然后重抛异常交给 Tenacity 重试。装饰器 stop_after_attempt(2) 是最多两次总尝试，即首次调用加一次重试；源码 docstring 中的“max 2 retries”文字与实际 attempts 语义不一致。

若 HA 已执行 StartCountdown、SetExpression 或 PlayAnimation，但 HTTP 响应丢失导致客户端收到 ClosedResourceError，重连后再次调用可能重复执行。该风险来自固定版本源码控制流分析；AstrBot 运行时当前不可用，未能进行响应丢失故障注入，故不宣称已复现。没有增加自定义重试层，也没有对真实 Tivoo 执行重复动作。

## 3. 自动化实现与测试

新增 tests/homeassistant/custom_components/tivoo/test_tivoo_p4b5_mcp_http.py，直接使用已安装的 MCP SDK 2.3.0 Streamable HTTP 客户端连接本地 HA 测试应用的真实 /api/mcp/assist 路由。临时普通 HA 用户及 Long-Lived Access Token 仅在测试进程创建并使用，不输出、不写文件。

测试覆盖：
1. 使用普通用户完成 MCP initialize，并按 tivoo__ 前缀过滤完整工具列表，发现且仅断言项目的七个 MVP Tool：SetExpression、ShowText、StartCountdown、StopCountdown、SetVolume、ShowImage、PlayAnimation。不会错误假设 Assist API 总工具数只有七个。
2. 通过 tools/call 逐个调用七个工具，验证参数从 HA LLM Tool 传入对应 HA Service，再到内存语义 Adapter。覆盖 StartCountdown 的 MM:SS 字符串、StopCountdown 空参数、SetVolume 0/100、图片 PNG 和 GIF 动画测试文件。
3. 使用失败 Adapter 验证服务异常被返回为 MCP Tool error。
4. 使用无效 Bearer Token 初始化时，HA 返回 HTTP 401。
5. 直接调用 tivoo.set_brightness 服务，确认 0 和 100 接受、101 由 HA Service Schema 拒绝。Brightness 是 HA Service，不新增同义 MCP Tool。
6. 验证 MCP 测试 socket 仅允许 127.0.0.1，连接保留测试地址 192.0.2.1 被拒绝。

测试脚本 scripts/test-ha.sh 显式加载 pytest_socket 插件。对标记为 enable_socket 的 MCP 测试，autouse fixture 在启用 socket 后调用 socket_allow_hosts(["127.0.0.1"])；独立回归用例确认连接 192.0.2.1 会被拒绝。其他测试继续使用原有 socket 限制，没有启用外网访问。

## 4. 验证结果

最终代码树上的验证结果：

| 检查 | 结果 |
|---|---|
| P4b5 聚焦 HTTP/MCP 测试 | 6 passed |
| 完整 HA 测试套件 | 203 passed |
| Ruff 新增测试检查 | PASS |
| 新增测试 Ruff format check | PASS |
| scripts/test-ha.sh shell 语法 | PASS |
| 完整 Python compileall | PASS |
| pip check | PASS（No broken requirements found）|
| git diff --check | PASS（提交前变更检查）|

测试输出包含 HA/aiohttp 的 NotAppKeyWarning、pytest_socket 的预期外部地址拒绝警告与依赖 deprecation warnings；聚焦测试 6 passed，完整测试套件 203 passed / 72 warnings，没有测试失败。最终完整测试日志与静态检查日志保存在本机忽略目录 .superpowers/sdd/2026-11-09-p4-ha-mcp-tool/。

## 5. 验收状态

| 验收项 | 状态 | 依据 |
|---|---|---|
| HA Assist MCP Streamable HTTP initialize/list | PASS | 本地 HTTP 测试应用，MCP SDK 2.3.0 |
| 七个 Tivoo MVP Tool 发现 | PASS | 普通用户 tools/list，按 tivoo__ 过滤 |
| 七个 Tool → HA Service → 内存 Adapter | PASS | 本地 HTTP tools/call 测试 |
| SetVolume 0/100、倒计时与 Stop 空参数 | PASS | Adapter 收到准确参数 |
| Brightness Service 0/100/越界 | PASS | HA Service 自动化测试 |
| 无效 Token 拒绝、普通用户调用 | PASS | 普通用户 LLAT 与 401 测试 |
| Service/Adapter 错误映射 MCP tool error | PASS | MCP 错误返回测试 |
| AstrBot WebUI 保存 MCP Server | BLOCKED | 当前开发机无 AstrBot 实例/WebUI |
| AstrBot 4.29.4 内 initialize/tools/list | BLOCKED | 没有可运行目标实例；源码仅做静态核对 |
| 目标 Tivoo Persona 七项工具授权 | BLOCKED | 目标 Persona/配置界面不可访问 |
| AstrBot 重连响应丢失故障注入 | BLOCKED | 没有 AstrBot 运行时；已完成源码级风险审查 |
| Token 未进入仓库、日志和报告 | PASS | 测试内临时生成；无凭据文件或输出 |

## 6. 自审与变更边界

- 新测试走 HA 原生 Assist MCP HTTP endpoint，不是仅调用 Python 方法或 mock MCP server；普通用户权限、HTTP Bearer 认证和服务调用都经过实际 HA HTTP 处理路径。
- 测试临时媒体文件落在 HA test config 下随机目录；测试使用内存 Adapter，不触及设备。
- 脚本改动只为显式加载 pytest_socket，使已有的局部 loopback 测试标记生效；白名单限定为 127.0.0.1。
- 未修改 Tivoo 生产实现、AstrBot 插件或 P3 代码。新增测试及脚本改动仅用于 P4b5。
- 本会话没有可派发的独立代码审查 Agent 工具；按 P4 SuperPower 工作流完成作者自审，未把自审标记为独立 Reviewer 通过。
- 未连接 NAS、未读取 NAS 配置或寻找 Token、未连接 Tivoo 实机。

## 7. 收尾

P4b5 在当前可用开发环境中的协议与 HA 服务链路验证已完成；需要目标 AstrBot 实例的 WebUI 配置、Persona 授权和运行时重连注入明确保留为 BLOCKED，不能据此宣称 AstrBot 端整体验收通过。目标环境具备后，后续只需按 §9 对照表补测这些 BLOCKED 项，不需要新增 MCP Client 或修改 HA 接口合同。

本批次仅本地提交；不 push、不 merge。P4b6 未开始。
