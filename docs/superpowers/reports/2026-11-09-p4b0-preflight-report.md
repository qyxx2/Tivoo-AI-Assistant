# P4b0 前置核查报告

日期：2026-11-09  
分支：feature/p4-ha-mcp-server  
核查范围：仅 P4b0；未实现任何 Tivoo HA 服务或 LLM Tool。

## 结论

P4b0 的版本、接口、测试入口与协议边界核查已完成。可进入 P4b1。当前 MVP 以 P4 合同矩阵为准：七个 MCP Tool（SetExpression、ShowText、StartCountdown、StopCountdown、SetVolume、ShowImage、PlayAnimation）以及 SetBrightness HA Service，均为必需实现；不要沿用 SDD 账本早期的“三项 MVP”描述。

## 版本与源码证据

- Home Assistant Core：开发机 .venv 实际安装 2026.11.0。
- AstrBot：目标 v4.29.4；Git tag 指向 61335414433db721b3f7ecc93f90deafe0a59d78。本机没有 AstrBot 源码 checkout，使用该 tag 的 astrbot/core/agent/mcp_client.py 作为源码依据。
- HA LLM Tools：homeassistant.helpers.llm.Tool、LLMTools、ToolResult；平台同步回调 async_get_tools(hass, llm_context, api_id)；参数使用 probatio.Schema；工具执行 async_call(hass, tool_input, llm_context)。Tool 通过 hass.services.async_call 委派普通 HA 服务。
- Assist MCP：HA 原生 mcp_server 的专用路径为 /api/mcp/assist；由 Assist API 工具集合提供 tools/list 和 tools/call。有效 HA 用户认证仍然需要；assist 路由不要求管理员身份。它不是匿名接口，也不是只读接口。原生实体控制仍受 Assist 暴露配置约束；Tivoo Tools 应只对 api_id == "assist" 注册，不向管理 API 注册。
- AstrBot v4.29.4 已内置 Streamable HTTP MCP Client，支持 URL、Authorization headers、initialize、tools/list、tools/call 和断线重连/有限重试；本项目不开发自有 MCP Client。MCP SDK 2.3.0 的客户端函数导出名为 streamable_http_client，AstrBot 代码对新旧名称有兼容分支。
- P4 不接管 P3 对话链路，不实现 ESP32 TCP 7777/7778、SPP、音频资源、STT/TTS。

## 本地测试入口与环境

- 测试入口：./scripts/test-ha.sh，复用当前 .venv 和 pytest-homeassistant==2026.11.0。
- 原测试环境缺少 HA Core mcp_server manifest 的可选依赖。已在 requirements_test.txt 固定加入 mcp==2.3.0、aiohttp_sse==2.2.0、anyio==4.15.1，并安装到本机 .venv。HA MCP Server 模块可正常导入。
- P3 回归：./scripts/test-ha.sh → 92 passed。
- 静态检查：.venv/bin/ruff check homeassistant tests → passed；.venv/bin/python -m compileall -q homeassistant tests → passed；git diff --check → passed。
- 测试有 63 条依赖/HA 测试框架 deprecation/not-app-key warnings，无失败。

## Tivoo 协议与来源/许可证决策

- 本机 BluetoothBridgeTest/tivoo/UPSTREAM.md 声明协议渲染等内容源自 solar2ain/tivoo-control commit 6f24deaf631820089259177805d1a6a6615f6d7e，并说明上游 README 标注 MIT。
- 已克隆核对该固定提交：README 明确写明 MIT，但仓库根目录没有 LICENSE 文件；故许可证声明可查，标准 MIT 授权文本/版权声明文件并未随仓库提供。另两个参考仓库 d03n3rfr1tz3/esp32-divoom、d03n3rfr1tz3/hass-divoom 各自有 LICENSE 文件，但不因此推定 solar2ain/tivoo-control 源码继承它们的许可。
- P4b0 决策：本批不复制/vendoring 外部 Tivoo SDK 文件，也不从 BluetoothBridge 的外部绝对路径运行时导入。后续实现只在确认来源与许可义务后选择性复用；必要时由合同矩阵已确认的协议/参数自行实现最小业务适配。BluetoothBridge Transport、SPP 会话与设备连接代码绝不进入 HA 集成。若 P4b1–b4 确需逐字复制上游文件，应先补齐并核实该上游许可文本/版权声明，再进行复制。

## P4b1 输入与边界

- homeassistant/custom_components/tivoo/ 目前只有占位文件；没有可复用的 HA Tivoo 集成、服务、实体或 LLM Tools。
- 普通 HA 服务是自动化与 LLM Tool 共用的业务入口；Tool 只转发参数与适配结果。
- 媒体文件处理按合同矩阵约定的 HA 配置目录相对路径执行；AstrBot 不通过 MCP 传输图片帧/GIF 帧/二进制内容。
- 开发和测试继续在本 Ubuntu 开发机进行，不连接 NAS 跑重负载测试，不读取或复制生产 Token。
- P4b0 未修改 P3 代码、README、P4 合同矩阵、生产配置；未实现后续批次代码。

## 变更

- requirements_test.txt：加入 HA 原生 MCP Server 的测试依赖。
- 本报告：记录 P4b0 的版本、接口、测试、许可证决策和 P4b1 输入。
