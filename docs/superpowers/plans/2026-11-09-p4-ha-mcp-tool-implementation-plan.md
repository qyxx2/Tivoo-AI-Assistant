# P4 Home Assistant MCP / Tivoo LLM Tools 实施计划

> 状态：P4b0–P4b6 的本地实现、自动化验证和合同追踪已执行。2026-11-10 目标运行时补充验收已通过 HA/Tivoo 部署、AstrBot 4.29.4 MCP 连接/工具发现，以及一次 Persona `StopCountdown` 调用和预期 Adapter unavailable 错误返回；七个 Tool 的全量 Persona 授权、StartCountdown/SetVolume Persona 调用和实际断线/响应丢失故障注入仍待验证。P4 整体保持 PARTIAL，详见 `2026-11-10-p4-runtime-acceptance-report.md`。
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
- HA Tivoo 服务的真实设备执行依赖后续 P5/P6 通信层：P5 提供 Wi-Fi、最小单向 TCP 7777 SPP 控制和 7778 诊断日志，P6 再补齐完整双向通信及音频资源通路。P4 使用测试适配器验证 Tool → HA Service → 命令请求；传输尚未接入时必须明确报告不可用，不能返回伪成功。
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
- 服务到设备之间保留一个最小的语义命令接口。测试使用内存适配器；P5 接入单向 TCP 7777 SPP 控制及 7778 诊断日志适配器，P6 在此基础上扩展完整双向通信。P4 的默认不可用适配器必须返回明确错误，不尝试自行连接 ESP32。
- 不在 P4 实现 TCP 7777/7778、HTTP 音频获取、SPP、Tivoo 帧编码或固件逻辑。

### 3.3 第一版 MVP 服务与工具集

第一版必须完成下列功能和 HA Services：表情预设、文字显示、亮度服务、图片显示、GIF 动画、倒计时启动/停止、扬声器音量调整。

| MCP Tool | HA Service | 必需参数 |
|---|---|---|
| `tivoo__SetExpression` | `tivoo.set_expression` | `name`，只接受运行时有效 preset registry 项 |
| `tivoo__ShowText` | `tivoo.show_text` | `value`，可选已冻结的显示样式参数，不暴露本地字体路径 |
| `tivoo__StartCountdown` | `tivoo.start_countdown` | `countdown: MM:SS` |
| `tivoo__StopCountdown` | `tivoo.stop_countdown` | 无参数 |
| `tivoo__SetVolume` | `tivoo.set_volume` | `volume: integer 0–100` |
| `tivoo__ShowImage` | `tivoo.show_image` | `file`，可选 `time` |
| `tivoo__PlayAnimation` | `tivoo.play_animation` | GIF `file`，可选 `time` |

另外必须实现 `tivoo.set_brightness` HA Service，`value` 范围 0–100；按原计划不注册重复 `SetBrightness` MCP Tool。上述七个工具全部由 `llm.py` 提供并调用对应 HA Service。

未明确列入上述清单的其他 Tivoo 服务和 Tool 均作为可选扩展保留，不作为本版实现或验收门。完整能力和型号限制见合同矩阵第 4.0 节。

### 3.4 工具注解

七个首版写操作 Tool 均显式设置 `read_only=False`、`destructive=False`、`open_world=False` 和 `integration="tivoo"`。`SetVolume`、`StopCountdown` 设 `idempotent=True`；`StartCountdown`、`SetExpression`、`ShowText`、`ShowImage`、`PlayAnimation` 设 `idempotent=False`，因为这些动作可能重播或重新开始显示过程。亮度只作为 HA Service，不适用 MCP ToolAnnotations。

### 3.5 MVP 参数与媒体合同

- 倒计时启动只接受严格 `MM:SS`；分钟范围 00–99，秒范围 00–59。停止不接收任何参数。
- 音量和亮度均为整数 0–100；音量 0 是有效静音值，处理时不能被当作缺省值。
- 表情使用运行时有效 preset registry；文字只接受冻结的显示字段，不暴露本地 `font_file`。
- 静态图片支持 PNG/JPG，GIF 动画只接受 GIF 文件；使用相对 `media_directory` 的 `file` 路径，可选 `time=0–65535 ms`。
- `media_directory` 默认沿用 `pixelart`，在 HA 配置目录内解析。路径解析拒绝绝对路径、URL、路径穿越及逃逸 symlink；媒体文件测试使用 HA 配置目录中的测试夹具。
- 不接受帧目录、JSON stage、asset ID、URL 或 MCP 原始二进制载荷；AstrBot 生成媒体文件如何进入 HA 配置目录不通过发明 MCP 资源协议解决。

## 4. 关键实现边界

### 4.1 Tivoo 命令复用

首版需要表情、文字、亮度、图片/GIF、倒计时和音量对应的纯业务/协议能力。本机 BluetoothBridgeTest/tivoo 中的纯 payload builder、图像/文字/GIF 渲染和 preset registry 应按模块优先复用；先比对本机副本与固定上游 commit 的差异，保留来源、commit 和原有声明。solar2ain/tivoo-control README 声明 MIT 但仓库没有独立 LICENSE 文件，这一材料情况需要记录，不作为个人研究场景下拒绝所有模块复用的统一门槛。TivooDisplay 的 Transport 依赖 Android Bluetooth Bridge，不得直接搬入 HA 容器或从开发机绝对路径导入；仅排除这部分不符合架构的运行时传输代码。对某个具体模块若来源或适用边界确实不清楚，只暂停该模块并核实/替换来源，不重写整套协议。未声明的其他服务不随 MVP 扩大。

### 4.2 命令接口的深度与测试

首版命令接口只表达 `set_expression`、`show_text`、`set_brightness`、`show_image`、`play_animation`、`start_countdown`、`stop_countdown`、`set_volume` 这些明确业务动作及合同参数，不暴露原始帧、TCP socket、蓝牙或 ESP32 细节。内存适配器验证 HA Service 的可观察请求；P5 最小 TCP 适配器沿用同一接口，P6 再扩展完整双向通信。未声明的其他服务不加入这批语义动作；不另建通用消息总线、任务队列或幂等数据库。

### 4.3 错误与重试

- 参数 Schema 不通过、服务不存在、文件不可读/越界、设备传输不可用，均明确失败。
- `ToolResult.data` 始终为 JSON object；只有服务层真实执行到的动作才可写入结果。
- `ToolAnnotations` 显式声明；写操作 `read_only=False`，本地 Tivoo 操作 `open_world=False`，幂等性按操作分别确定。
- 依据 AstrBot 4.29.4 已有 MCP Client 的实际断线恢复行为验收，不额外叠加通用重试框架。对动画、倒计时等非幂等动作，记录响应丢失时是否重复执行。

## 5. 实施批次与依赖

详细任务、文件范围、测试和退出门见 [P4 Batch Execution Plan](2026-11-09-p4-ha-mcp-tool-batch-execution-plan.md)。原定七批结构完整保留；表情、文字、亮度 Service、图片/GIF、倒计时启停和音量控制均为 MVP 必须项，其他未声明服务仅作为可选扩展。

| 批次 | 目标 | 依赖 | MVP 范围 |
|---|---|---|---|
| P4b0 | 版本、源码、测试环境及协议复用前置核查 | 无 | 全部前置核查，必须 |
| P4b1 | Tivoo HA 集成骨架、StopCountdown/SetVolume 服务及媒体目录配置 | P4b0 | 两个服务与集成基础，必须 |
| P4b2 | HA LLM Tools 平台与首个 StopCountdown Tool | P4b1 | 首个 Tool 垂直切片，必须 |
| P4b3 | 表情、文字、倒计时工具和亮度服务 | P4b2 | SetExpression、ShowText、StartCountdown、SetVolume Tools 与 SetBrightness Service，必须 |
| P4b4 | 图片/GIF 文件处理及媒体 Tools | P4b2 | ShowImage、PlayAnimation Tools 与媒体文件处理，必须 |
| P4b5 | AstrBot MCP 配置、Persona 授权和运行时验证 | P4b3、P4b4 | 七个必需 Tool 的发现、授权和调用，必须 |
| P4b6 | P4 合同矩阵验收、P3 回归与收尾 | P4b5 | 全部 MVP 功能验收及倒计时/音量完整链路验收，必须 |

第一版依赖路径：`P4b0 → P4b1 → P4b2 → {P4b3, P4b4} → P4b5 → P4b6`。P4b3 与 P4b4 都是首版必需批次，P4b5 必须等待两者完成。

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
- 不 push、不 merge，不修改 main；P4b0–P4b6 按批次分别本地提交到当前 P4 分支。

## 8. P4 第一版完成定义

P4b0–P4b6 全部必需批次通过；表情、文字、亮度 HA Service、图片/GIF 文件处理、倒计时启停和音量调整均有自动化测试或受控运行证据。AstrBot Persona 通过 `/api/mcp/assist` 发现并授权七个必需 Tool；各 Tool 正确调用对应 HA Service。P4b6 必须额外证明 StartCountdown、StopCountdown、SetVolume 三项经 AstrBot MCP → HA LLM Tool → HA Service → 语义 Adapter 的完整调用链；P3 全套测试无回归；凭据没有进入仓库或日志。

亮度以 HA Service 验收，不要求新增同义 MCP Tool。未明确列入 MVP 的其他 Tivoo 服务标记为可选扩展，不阻塞本版。P4 默认生产适配器在 P5 最小 TCP 传输接入前必须明确报告 unavailable；P5 仅启用单向 SPP 控制和诊断日志，P6 再扩展完整双向通信。测试适配器通过不代表 Tivoo 实机动作已经成功，实机回执仍属 P5/P6。
