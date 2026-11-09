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

### 3.3 第一版必需服务与工具集

第一版必须完成三项业务能力，先打通倒计时与音量的应用链路：

| MCP Tool | HA Service | 首版用途 / 参数 |
|---|---|---|
| `tivoo__StartCountdown` | `tivoo.start_countdown` | 启动 `MM:SS` 倒计时，分钟 00–99、秒 00–59 |
| `tivoo__StopCountdown` | `tivoo.stop_countdown` | 无参数停止倒计时 |
| `tivoo__SetVolume` | `tivoo.set_volume` | 设置扬声器音量 0–100，0 是有效静音值 |

服务和工具的批次位置：StopCountdown 与 SetVolume 服务在 P4b1；StopCountdown Tool 在 P4b2；StartCountdown 服务/Tool 与 SetVolume Tool 在 P4b3。第一版 `tools/list` 中只要求上述三个 Tivoo Tool。

原计划中的其它功能保留在七批路线图中，不作为首版必做：P4b3 保留表情预设、文字显示 Tool 和亮度 HA Service；P4b4 保留图片/GIF 文件处理及媒体 Tools。它们不进入首版代码实现和验收门；首版主链路通过后，再按实际需求决定是否执行这些扩展子任务。亮度 AI 控制仍优先采用未来的 `number.tivoo_brightness` 原生实体，不创建重复 `SetBrightness` Tool。完整能力和型号限制见合同矩阵第 4.0 节。

### 3.4 工具注解

三个首版必需写操作都显式设置 `ToolAnnotations`：`read_only=False`、`destructive=False`、`open_world=False`。SetVolume 是状态设置，`idempotent=True`；StopCountdown 是停止状态设置，`idempotent=True`；StartCountdown 会启动/重置时间，`idempotent=False`。后续表情、文字、媒体等扩展 Tool 在进入相应子任务时再按业务语义决定。

### 3.5 首版合同与可选扩展边界

- 首版启动倒计时只接受 `MM:SS`；分钟范围 00–99，秒范围 00–59。
- 首版停止倒计时不接收任何参数。业务层映射上游 `show_countdown(value=False, countdown=None)`，不读取或保存之前启动的时间。
- 首版音量使用整数 0–100，0 是有效静音值；上游设备层把 0–100 映射到设备 0–15 的音量范围。
- 原计划中的表情/文字/亮度服务继续保留在 P4b3 可选扩展子任务；图片/GIF、media_directory、`file/time` 参数和 AstrBot 跨容器文件落盘继续保留在 P4b4 媒体扩展，不属于首版必做。
- 未来媒体扩展继续遵循合同矩阵的相对 media_directory 文件引用方式，不增加 asset ID、URI 或 HTTP URL。

## 4. 关键实现边界

### 4.1 Tivoo 命令复用

首版只需要 StartCountdown、StopCountdown 和 SetVolume 三个设备语义动作。本机 `BluetoothBridgeTest/tivoo/commands.py` 已有对应倒计时/音量 payload builder，但复用前仍须通过 P4b0 许可证/来源检查；TivooDisplay 的 Transport 依赖 Android Bluetooth Bridge，不得直接搬入 HA 容器或从开发机绝对路径导入。若许可证证据不足，首版只保留语义命令接口，不 vendoring、不重写整套协议。表情、文字、亮度和媒体模块仍保留在原定扩展批次，届时再分别检查其复用条件。

### 4.2 命令接口的深度与测试

首版命令接口只表达 `start_countdown`、`stop_countdown` 和 `set_volume` 三个业务动作及合同参数，不暴露原始帧、TCP socket、蓝牙或 ESP32 细节。内存适配器验证 HA 服务的可观察请求；P6 的 TCP 适配器使用同一接口。后续扩展只在有明确需要时增加受限语义动作，不另建通用消息总线、任务队列或幂等数据库。

### 4.3 错误与重试

- 参数 Schema 不通过、服务不存在、文件不可读/越界、设备传输不可用，均明确失败。
- `ToolResult.data` 始终为 JSON object；只有服务层真实执行到的动作才可写入结果。
- `ToolAnnotations` 显式声明；写操作 `read_only=False`，本地 Tivoo 操作 `open_world=False`，幂等性按操作分别确定。
- 依据 AstrBot 4.29.4 已有 MCP Client 的实际断线恢复行为验收，不额外叠加通用重试框架。对动画、倒计时等非幂等动作，记录响应丢失时是否重复执行。

## 5. 实施批次与依赖

详细任务、文件范围、测试和退出门见 [P4 Batch Execution Plan](2026-11-09-p4-ha-mcp-tool-batch-execution-plan.md)。原定七批结构完整保留，第一版仅执行核心倒计时/音量所需子任务；其余显示和媒体任务在对应批次中作为可选扩展保留。

| 批次 | 目标 | 依赖 | 第一版范围 |
|---|---|---|---|
| P4b0 | 版本、源码、测试环境及协议复用前置核查 | 无 | 必须 |
| P4b1 | Tivoo HA 集成骨架、服务注册、StopCountdown 与 SetVolume 服务 | P4b0 | 必须 |
| P4b2 | HA LLM Tools 平台与首个 StopCountdown Tool | P4b1 | 必须 |
| P4b3 | 表情、文字、倒计时工具和亮度服务 | P4b2 | StartCountdown Service/Tool、SetVolume Tool 必须；表情/文字/亮度扩展可选 |
| P4b4 | 图片/GIF 文件处理、服务与媒体 Tools | P4b2 | 可选扩展，不阻塞首版 |
| P4b5 | AstrBot MCP 配置、Persona 授权与运行时验证 | P4b3；若纳入媒体扩展则另需 P4b4 | 必须，首版只验证三个必需 Tool |
| P4b6 | P4 合同矩阵验收、P3 回归与收尾 | P4b5 | 必须，扩展项可记录为 DEFERRED |

第一版依赖路径：`P4b0 → P4b1 → P4b2 → P4b3（MVP 子集）→ P4b5 → P4b6`。P4b4 保留为独立媒体扩展；只有决定把媒体功能纳入某次后续交付时，才要求 P4b4 在对应扩展验收前完成。

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

第一版要求 P4b0、P4b1、P4b2、P4b3 的 MVP 子任务、P4b5 和 P4b6 的首版退出门全部通过；AstrBot Persona 可通过 HA 原生 `/api/mcp/assist` 发现并调用三个必需 Tool（StartCountdown、StopCountdown、SetVolume）；每个 Tool 调用对应的 HA Service；服务参数、错误传播和返回对象符合合同；本地测试适配器证明 MCP → HA Tool → HA Service → 语义 Adapter 的完整应用链路；P3 全套测试无回归；凭据没有进入仓库或日志。

P4b3 中表情/文字/亮度扩展子任务与 P4b4 图片/GIF 媒体扩展保留在原计划，但不作为第一版完成条件；未实施时在验收矩阵标为 DEFERRED，不记为 MVP 缺陷。P4 完整扩展范围若后续被排期，再按对应子任务补充验证。

生产适配器在 P6 TCP 传输接入前必须明确报告 unavailable。第一版链路通过不等于 Tivoo 实机已经执行成功；真实音量和倒计时动作在 P5/P6 验收。