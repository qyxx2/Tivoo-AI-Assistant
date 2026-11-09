# P4b0 前置核查报告

日期：2026-11-09（复用策略修订）
分支：feature/p4-ha-mcp-server
核查范围：仅 P4b0；未实现任何 Tivoo HA 服务或 LLM Tool。

## 结论

P4b0 的版本、接口、测试入口与协议边界核查已完成。可进入 P4b1。当前 MVP 以 P4 合同矩阵为准：七个 MCP Tool（SetExpression、ShowText、StartCountdown、StopCountdown、SetVolume、ShowImage、PlayAnimation）以及 SetBrightness HA Service，均为必需实现；不要沿用 SDD 账本早期的“三项 MVP”描述。

**复用原则修订：优先复用已有实现，不因仓库缺少独立 LICENSE 文件而一概放弃复用。** solar2ain/tivoo-control 固定提交的 README 声明 MIT，但仓库根目录没有单独的 LICENSE 文件。这是许可证材料/版权声明完整性需要记录的情况，不等同于“禁止个人研究使用”，也不构成拒绝引入纯协议模块的技术理由。用户当前明确的用途是个人研究和自有设备使用；本项目按模块评估并优先复用，保留来源、固定版本和上游声明。若未来公开发布或向他人分发，再单独核对各来源仓库的许可证文本和分发义务；不得将一个仓库的许可证套用到另一个仓库。

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

## Tivoo 协议与既有实现复用

### 来源与许可证记录

- 本机 BluetoothBridgeTest/tivoo/UPSTREAM.md 声明协议渲染等内容源自 solar2ain/tivoo-control commit 6f24deaf631820089259177805d1a6a6615f6d7e。
- 已核对该固定提交：README 明确声明 MIT，但仓库根目录没有独立 LICENSE 文件。记录这一事实并保留上游 README、仓库地址和 commit SHA；不从其他仓库借用许可证文本，也不把 esp32-divoom、hass-divoom 的许可证推定给 tivoo-control。
- 本项目当前是用户个人研究及自有设备用途。复用策略不以“先取得额外书面许可/补齐独立 LICENSE 文件”作为所有本地复用的统一前置门槛；按模块保留来源和声明。若将来改变为公开发布或分发，再评估对应来源的许可证和通知义务。

### 按模块复用，不整体照搬

- **优先复用 Python 纯协议与渲染代码**：commands.py 中已有 payload builders；tivoo.py 中外层 packet、图像缩放/调色板编码、文字帧、动画块和 preset registry。与当前合同相符的函数应优先采用，并用现有测试/Golden tests 验证；不要仅因需要整理目录就重新实现整套 wire encoder。
- **复用高层语义作为映射依据**：client.py 中的 brightness、image、animation、text、preset、volume、countdown 等方法签名可用于确认 HA Service 应表达的能力和默认值。设备连接方式不决定 HA 服务接口。
- **复用 HA 上游集成中合适的部分**：hass-divoom 的服务 Schema、媒体文件解析、GIF 解码、路径处理和 Tivoo 型号专用能力可作为现成实现或直接移植候选；仅对照后选取本项目需要的模块，不要求整体复制其集成。
- **复用 ESP32 侧既有协议实现**：esp32-divoom 可用于核对设备侧命令处理和字段含义；后续固件阶段优先复用可移植逻辑，再按 ESP-IDF 环境适配，不因平台不同就重新发明协议。
- **明确排除的是错误的运行时传输边界**：BluetoothBridge 的 RFCOMM/SPP 连接、会话和设备发现实现不得放进 HA 容器，也不能让 HA 绕过 ESP32，自己连接 Tivoo。这不代表禁止参考或复用同一仓库中的纯协议、编码和渲染代码。

### 引入方式

- 对需要进入部署产物的模块，优先选择简单、可维护的方式：将必要纯 Python 文件/模块整理进本项目的可部署包；当上游目录边界和更新需求更合适时，可使用固定 commit 的子模块或依赖。
- 复用前比对本机 BluetoothBridgeTest/tivoo 与声明的上游 commit 的差异，区分上游原始代码和本地修改；保留相关版权声明、README 来源及版本记录。
- 不从开发机外部工作区绝对路径运行时导入。部署到 NAS 的代码必须在项目包、明确安装的依赖或固定子模块中可获得。
- 不把整个 BluetoothBridge 客户端或传输栈带入 HA；HA Service 仍通过语义适配接缝执行。P4 的 HA/MCP 层不接管 ESP32 TCP/SPP，设备传输仍由后续 P5/P6 范围负责。

## P4b1 输入与边界

- homeassistant/custom_components/tivoo/ 目前只有占位文件；没有可复用的本项目 HA Tivoo 集成、服务、实体或 LLM Tools。
- 普通 HA 服务是自动化与 LLM Tool 共用的业务入口；Tool 只转发参数与适配结果。
- 媒体文件处理按合同矩阵约定的 HA 配置目录相对路径执行；AstrBot 不通过 MCP 传输图片帧/GIF 帧/二进制内容。
- 开发和测试继续在本 Ubuntu 开发机进行，不连接 NAS 跑重负载测试，不读取或复制生产 Token。
- P4b0 未修改 P3 代码、README、P4 合同矩阵、生产配置；未实现后续批次代码。

## 变更

- requirements_test.txt：加入 HA 原生 MCP Server 的测试依赖。
- 本报告：记录 P4b0 的版本、接口、测试和按模块复用决策；本次修订纠正此前对 vendoring 的过度限制。
