# P4 Home Assistant MCP / Tivoo LLM Tools 实施计划

> 状态：仅计划，尚未实现。
> 工作分支：`feature/p4-ha-mcp-server`
> 代码基线：`main` / `c40c40046b257a37c632a9738bf04ec2abc0ef76`
> 计划基线：P4 合同矩阵提交 `982966a`
> 版本基线：Home Assistant Core 2026.11.0；AstrBot 4.29.4
> 日期：2026-11-09

## 1. 目标

在不修改 P3 对话入口的前提下，建立 AstrBot → Home Assistant 的受限工具控制链路：

AstrBot 4.29.4 内置 MCP Client
→ Streamable HTTP
→ HA 原生 MCP Server 的 `/api/mcp/assist`
→ HA Assist API
→ Tivoo 集成 `llm.py` 暴露的 LLM Tools
→ 同一套 `tivoo.*` HA 服务
→ Tivoo 命令执行接口。

P4 交付的是 HA 工具接口、服务语义、AstrBot MCP 连接与 Persona 工具可用性，以及可复现的合同测试。它不交付 ESP32 设备传输或 Tivoo 实机命令成功。

## 2. 当前代码状态与实施前置

- P3 AstrBot Conversation Agent 已存在于 `homeassistant/custom_components/astrbot/`，并有配套 HA Core 测试。其 HTTP Chat、SSE、session 与 ChatLog 行为是回归基线。
- `homeassistant/custom_components/tivoo/` 当前只有占位文件，没有可复用的 HA Tivoo 集成、服务或实体。P4 必须从最小集成骨架开始，不能假定服务已经存在。
- 开发机已有 HA Core 2026.11.0 对应的 `.venv`、`pytest-homeassistant==2026.11.0`、Ruff 与 `scripts/test-ha.sh`。优先沿用，不另建测试框架。
- HA Tivoo 服务的真实设备执行依赖后续 P6 通信层。P4 使用测试适配器验证 Tool → HA Service → 命令请求；生产路径在设备传输尚未接入时必须明确报告不可用，不能返回伪成功。
- 本计划不要求连接 NAS 运行测试。开发与回归测试在 Remote Desktop Commander 连接的 Ubuntu 开发机完成；生产 HA/AstrBot 联调仅做必要的配置和受控冒烟验证。

## 3. 架构决策

### 3.1 控制面复用

- MCP Server 使用 HA Core 原生 `mcp_server`，路由固定为 `/api/mcp/assist`；不另建 MCP Server 容器或 HTTP 路由。
- MCP 传输使用 Streamable HTTP。AstrBot 端使用 4.29.4 已有的 MCP Client，不开发第二套 Client 或自定义传输。
- HA 鉴权使用专用普通 HA 用户的 Long-Lived Access Token，配置在 AstrBot MCP Server 的 Authorization header 中。Token 不进入仓库、测试日志或计划。
- HA Assist API 仅控制已暴露给 Assist 的实体；Tivoo 自定义工具只面向 `api_id == "assist"`。不向 HA 管理 API 注册 Tivoo 工具。
- 不创建任意 HA domain/service/service_data 调用器。工具列表只能包含显式定义的项目动作以及 HA 原生 Assist 实体工具。

### 3.2 HA Tivoo 集成与服务

- 新建独立 `tivoo` HA 集成。实体、服务和 LLM Tools 分别按 HA 对应平台机制加载；`llm.py` 通过 LazyIntegrationPlatforms 发现，不放进普通实体 `PLATFORMS`。
- 普通 HA 服务是自动化、脚本和 MCP Tool 共用的业务入口；LLM Tool 只做参数转发与结果适配，不复制协议或业务实现。
- Tool 调用服务时使用 `hass.services.async_call("tivoo", service, ..., blocking=True, context=llm_context.context)`，让服务执行错误可被观察。
- 服务调用成功只表示服务层已接受/完成其当前职责。无设备回执时不得声称屏幕已显示或动画已播放完成。
- 服务到设备之间保留一个最小的语义命令接口。测试使用内存适配器；P6 再接入 TCP 7777 生产适配器。P4 的默认不可用适配器必须返回明确错误，不尝试自行连接 ESP32。
- 不在 P4 实现 TCP 7777/7778、HTTP 音频获取、SPP、Tivoo 帧编码或固件逻辑。

### 3.3 首期工具集

首期只注册合同矩阵定义的六个 Tivoo Tool：

| MCP Tool | HA Service | 参数摘要 |
|---|---|---|
| `tivoo__SetExpression` | `tivoo.set_expression` | `name`，必须来自运行时有效 preset registry |
| `tivoo__ShowText` | `tivoo.show_text` | `value` 与已冻结的可选显示参数；不暴露本地字体文件路径 |
| `tivoo__StartCountdown` | `tivoo.start_countdown` | `countdown: "MM:SS"` |
| `tivoo__StopCountdown` | `tivoo.stop_countdown` | 无参数 |
| `tivoo__ShowImage` | `tivoo.show_image` | `file`，可选 `time` |
| `tivoo__PlayAnimation` | `tivoo.play_animation` | GIF `file`，可选 `time` |

亮度、显示模式和屏幕开关优先通过 HA 原生实体工具暴露；不额外注册重复的亮度 Tool。亮度服务可以保留给自动化调用，但实体尚未实现时不得宣称 MCP 已具备该实体能力。

### 3.4 工具注解

所有写操作显式设置 `ToolAnnotations`：`read_only=False`、`open_world=False`、`destructive=False`。只有 `StopCountdown` 是幂等停止动作，设置 `idempotent=True`；表情/文字动画、倒计时启动、图片/GIF 显示均按可能重新开始播放或重置状态处理，设置 `idempotent=False`。亮度通过原生实体工具控制，不新增同义 Tool。

### 3.5 媒体与倒计时合同

- 媒体文件使用相对 `media_directory` 的 `file` 路径；默认目录沿用上游 `pixelart`。静态图片支持 PNG/JPG，GIF 支持多帧；动画 Tool 首期只接受 GIF。
- 可选 `time` 为 0–65535 毫秒。省略时保留 GIF 文件内帧时长。
- 解析文件路径后必须验证其仍位于 `media_directory` 内。拒绝任意绝对路径、URL、资源 ID、原始二进制、帧目录和 JSON stage 文件。
- AstrBot 生成的媒体文件如何进入 HA `media_directory` 仍是文件交接问题。P4 不发明 URI/asset ID 协议；验证时使用已经放入 HA media directory 的文件夹/测试夹具，并把跨容器落盘方式保留为明确待办。
- 启动倒计时只接受 `MM:SS`；停止倒计时不接收任何参数。停止报文语义为 `72 03 00 00 00`，不得要求读取或重传之前启动的时长。

## 4. 关键实现边界

### 4.1 Tivoo 命令复用

本机 `BluetoothBridgeTest/tivoo/` 中的协议与渲染代码来自 `solar2ain/tivoo-control`，但 `TivooDisplay` 的 Transport 依赖 Android Bluetooth Bridge，不得直接搬入 HA 容器。只有确认上游许可证、版权和本地改动归属后，才可考虑复用纯协议/渲染模块；不允许从开发机绝对路径导入。若许可证证据不足，P4 保持语义命令接口，不擅自 vendoring 或重写整套协议。

### 4.2 命令接口的深度与测试

命令接口只表达业务动作及合同参数，不暴露原始帧、TCP socket、蓝牙或 ESP32 细节。内存适配器验证 HA 服务的可观察请求；P6 的 TCP 适配器使用同一接口。此接口是 P4 服务实现与后续设备传输之间唯一需要保持稳定的内部接缝，不另建通用消息总线、任务队列或幂等数据库。

### 4.3 错误与重试

- 参数 Schema 不通过、服务不存在、文件不可读/越界、设备传输不可用，均明确失败。
- `ToolResult.data` 始终为 JSON object；只有服务层真实执行到的动作才可写入结果。
- `ToolAnnotations` 显式声明；写操作 `read_only=False`，本地 Tivoo 操作 `open_world=False`，幂等性按操作分别确定。
- 依据 AstrBot 4.29.4 已有 MCP Client 的实际断线恢复行为验收，不额外叠加通用重试框架。对动画、倒计时等非幂等动作，记录响应丢失时是否重复执行。

## 5. 实施批次与依赖

详细范围、测试和退出门见 [P4 Batch Execution Plan](2026-11-09-p4-ha-mcp-tool-batch-execution-plan.md)。

| 批次 | 目标 | 依赖 |
|---|---|---|
| P4b0 | 版本、源码、测试环境与上游复用前置核对 | 无 |
| P4b1 | Tivoo HA 集成骨架、服务注册与语义命令接缝 | P4b0 |
| P4b2 | LLM Tools 注册与首个无参 StopCountdown 垂直切片 | P4b1 |
| P4b3 | 表情、文字和倒计时工具完整落地 | P4b2 |
| P4b4 | 图片/GIF 文件服务和媒体工具落地 | P4b2 |
| P4b5 | AstrBot MCP 配置、Persona 授权与实际工具调用 | P4b3、P4b4 |
| P4b6 | P4 合同矩阵回归、权限/错误/断线验收和收尾 | P4b5 |

依赖图：`P4b0 → P4b1 → P4b2 → {P4b3, P4b4} → P4b5 → P4b6`。P4b3 与 P4b4 在 P4b2 完成后可独立进行。

## 6. 权威文档

1. [P4 HA MCP Tool 合同矩阵](../specs/2026-11-09-p4-ha-mcp-tool-contract-matrix.md)：P4 所有工具、参数、错误和验收合同的唯一权威来源。
2. [README.md](../../../README.md) §2–§4、§6–§8：项目目标、HA/AstrBot/ESP32 责任及阶段关系。
3. [P3 Conversation 合同矩阵](../specs/2026-11-09-p3-astrbot-conversation-contract-matrix.md)：保护 P3 HTTP/SSE 文本链路及其身份/session 约定。
4. [ESP32–HA 双向通信规格](../specs/2026-11-09-esp32-ha-bidirectional-communication-design.md)：只用于保持 P4 与 TCP 7777/7778、SPP、音频资源通道隔离。
5. [STT/TTS 端到端规格](../specs/2026-11-09-stt-tts-end-to-end-pipeline-spec.md)：只用于确认 P4 不接管语音输入/输出流水线。

发生冲突时，P4 合同矩阵决定 P4 工具合同；本计划决定实施顺序。更下游设备规格不得被解释为允许扩大 P4 范围。

## 7. 全局执行规则

- 每次开始一个 Batch，先检查分支、HEAD、工作区和本计划/批次计划；只执行当前批次。
- 每个新行为先写可从外部接口观察的 RED 测试，再做最小实现并 GREEN。优先复用 HA Core 机制和 P3 测试脚手架，不自行搭建重复基础设施。
- 每批结束运行聚焦测试、必要 P3 回归、Ruff、格式检查、compileall、pip check（适用时）和 `git diff --check`；检查改动文件范围后单独本地提交。
- 每批记录修改范围、RED/GREEN 证据、验证命令、提交 SHA、尚未解决事项和下一批输入。
- 版本或源代码不再符合矩阵、HA LLM Tool 平台实际加载行为与计划不符、服务参数无法映射上游语义时，先停止并更新合同，不在实现中猜字段。
- 普通 HA 服务与 LLM Tool 必须共享同一个服务 Schema 和业务 handler；不实现第二套 AI 专用服务逻辑。
- 不连接 NAS 做重负载测试。生产验证仅在开发机验证通过后做必要的 HA/AstrBot 连接冒烟；不部署或修改生产配置，除非另有明确指示。
- 不 push、不 merge，不修改 main；P4b0–P4b6 每批独立提交到当前 P4 分支。

## 8. P4 完成定义

P4b0–P4b6 的退出门全部通过；合同矩阵 P4-C01 至 P4-C13 有自动化或受控现场证据；AstrBot Persona 可通过 HA 原生 MCP Assist API 发现并调用六个合同工具；服务参数、错误和文件边界符合矩阵；P3 全套测试无回归；凭据没有进入仓库或日志。

P4-C14 的 Tivoo 实机动作验证属于 P5/P6。P4-C09 的无参停止服务语义在 P4 验收；字节级报文只有在纯 payload builder 的合法复用方式确认后才可在 P4 直接验证，否则明确转交 P6 adapter 测试。P4 不能以测试适配器通过为由宣称真实屏幕、动画或倒计时已在设备执行。
