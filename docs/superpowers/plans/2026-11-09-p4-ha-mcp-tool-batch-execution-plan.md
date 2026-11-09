# P4 Home Assistant MCP / Tivoo LLM Tools — Batch Execution Plan

> 状态：P4b0–P4b3 已完成；P4b4–P4b6 待执行。
> 工作分支：`feature/p4-ha-mcp-server`
> 计划权威来源：[P4 Implementation Plan](2026-11-09-p4-ha-mcp-tool-implementation-plan.md)
> 合同权威来源：[P4 Tool Contract Matrix](../specs/2026-11-09-p4-ha-mcp-tool-contract-matrix.md)
> 日期：2026-11-09

本文是 P4 的批次执行合同。每次只实现一个 Batch；不得将后续批次工作提前混入当前提交。

## 1. 分支与基线

- Base branch：`main`，基线提交 `c40c40046b257a37c632a9738bf04ec2abc0ef76`。
- 工作 branch：`feature/p4-ha-mcp-server`。
- 当前计划起点：`982966a`（P4 合同矩阵已修订媒体路径与倒计时停止语义）。
- 当前分支已包含 P3 实现；P3 现有测试是每批必要回归，不在 P4 修改 P3 代码。
- P4 所有批次在当前 P4 分支分别本地提交；不自动 push、merge 或修改 main。

## 2. 权威与前置条件

权威顺序：

1. `docs/superpowers/specs/2026-11-09-p4-ha-mcp-tool-contract-matrix.md`：P4 工具名称、参数、错误、媒体文件与验收合同的唯一权威来源。
2. `docs/superpowers/plans/2026-11-09-p4-ha-mcp-tool-implementation-plan.md`：P4 架构、模块职责和批次总顺序。
3. `README.md` §2–§4、§6–§8：项目层级职责、总体调用方向和上下游阶段。
4. `docs/superpowers/specs/2026-11-09-p3-astrbot-conversation-contract-matrix.md`：保护 P3 文本请求、SSE、session 与取消合同。
5. `docs/superpowers/specs/2026-11-09-esp32-ha-bidirectional-communication-design.md`：仅用于确认 TCP 7777/7778、HTTP 音频资源和 SPP 属于 P6 及以后。
6. `docs/superpowers/specs/2026-11-09-stt-tts-end-to-end-pipeline-spec.md`：仅用于确认 P4 不接管 STT/TTS。

进入 P4b0 时：

- 检查工作分支、HEAD、工作区和 main 基线；确保 P4 文档提交在当前分支。
- 重新核对运行目标 Home Assistant Core 与 AstrBot 版本；目标仍为 HA 2026.11.0、AstrBot 4.29.4。若有版本变化，先复核 HA LLM Tools、MCP Streamable HTTP 和 AstrBot MCP Client 源码，再更新矩阵。
- 本地 HA 测试环境沿用 `.venv`、`pytest-homeassistant==2026.11.0`、Ruff、`scripts/test-ha.sh`。若现有环境已失配，先修复/记录测试入口，不复制整套 HA 运行时。
- 核对 BluetoothBridgeTest/tivoo/UPSTREAM.md、固定上游 commit 和各参考仓库自己的许可证/来源。按模块优先复用现有纯协议、payload builder、图像/文字/GIF 渲染与 HA 服务实现；README 声明 MIT 但缺少独立 LICENSE 文件不构成一概拒绝个人研究复用的理由。保留来源、commit 和现有版权/许可声明；未来公开分发时再核查对应分发义务。不得从外部工作区绝对路径运行时导入，也不能把 BluetoothBridge Transport 带入 HA。
- 当前 `homeassistant/custom_components/tivoo/` 只有占位文件。不得假定有现成的 Tivoo HA 服务、实体、LLM Tools 或设备连接管理器。
- 不读取、复制或写入 NAS 上的 HA/AstrBot Token；任何需要真实凭据的 UI 配置由用户提供/录入或使用现有安全凭据存储。

## 3. 批次与依赖图

| Batch | 内容 | 依赖 | MVP 交付要求 |
|---|---|---|---|
| P4b0 | 版本、源码、测试和协议复用前置核对 | 无 | 确认所有 MVP 服务/Tool 的真实接口、可复用模块与来源、以及本地测试入口；必须 |
| P4b1 | Tivoo HA 集成骨架、服务注册与 StopCountdown/SetVolume 服务 | P4b0 | 集成可加载；StopCountdown、SetVolume Service 可用；media_directory 配置基础就位；必须 |
| P4b2 | HA LLM Tools 平台与首个 StopCountdown Tool 垂直切片 | P4b1 | Assist API 正确发现 StopCountdown Tool，服务委派和错误传播通过；必须 |
| P4b3 | 表情、文字、倒计时工具和亮度服务 | P4b2 | SetExpression、ShowText、StartCountdown、SetVolume Tools；SetBrightness Service；必须 |
| P4b4 | 图片/GIF 文件处理、服务与媒体 Tools | P4b2 | ShowImage、PlayAnimation 和媒体文件处理；必须 |
| P4b5 | AstrBot MCP 配置、Persona 授权与运行时验证 | P4b3、P4b4 | Persona 发现/授权七个必需 Tool，运行时调用通过；必须 |
| P4b6 | P4-C01–C15 合同验收、P3 回归与收尾 | P4b5 | 验收全部 MVP 实现，并完成倒计时启停/音量完整链路验证；必须 |

依赖顺序：

```text
P4b0 → P4b1 → P4b2 ─┬→ P4b3 ─┐
                    └→ P4b4 ─┴→ P4b5 → P4b6
```

P4b3 与 P4b4 可在 P4b2 后分别执行；两者都是 MVP 必需批次，P4b5 必须等待两者完成。只有未明确列入 MVP 清单的其他 Tivoo 服务才保留为可选扩展。

## 4. P4b0 — 版本、源码与本地验证前置

**Purpose:** 在编写 Tivoo 集成前确认当前可依赖的上游接口和本地验证条件。此批只做核查、计划必要修订和记录，不实现工具代码。

**Tasks:**

- [x] 核对 HA Core 实际目标版本及本地 `homeassistant.helpers.llm`、`homeassistant.components.llm`、`mcp_server` 的真实接口。
- [x] 核对 AstrBot 4.29.4 `mcp_client.py` 的 Streamable HTTP、headers、工具发现/调用和断线重试路径；不创建自己的 MCP Client。
- [x] 确认 `/api/mcp/assist` 与 Assist API 的认证、权限和工具集合行为；区分 Assist API 与管理 API。
- [x] 核对项目现有 HA 测试入口、P3 自动化回归、Ruff/compile 检查；记录完整测试命令。
- [x] 核实 Tivoo Python 纯协议模块的来源与许可信息：固定上游 README 声明 MIT，但仓库无独立 LICENSE 文件；将其作为需保留来源及声明的记录项，不将文件缺失等同于禁止个人研究复用。
- [x] 记录按模块复用边界：优先采用匹配合同的纯协议/payload/render builder、HA 服务/媒体处理实现；比对本地变更并保留上游来源。不得从外部工作区绝对路径导入；BluetoothBridge Transport/直接 SPP 不进入 HA 运行时。
- [x] 将许可证材料现状与技术复用决策分开记录；没有把独立 LICENSE 文件缺失设置为本地个人研究复用的统一阻塞项。HA/AstrBot 版本与接口无阻塞，不通过猜测参数继续。

**Exit gate:**

- [x] HA/AstrBot 版本和关键方法签名有当前源码依据。
- [x] 本地 P3 测试和静态检查能运行；测试命令与环境已明确。
- [x] 已决定纯 Tivoo SDK 的复用原则：按模块优先复用，不整体照搬；保留来源/commit/声明，部署包中不依赖开发机绝对路径。
- [x] HA/AstrBot 接口与 P4 矩阵一致，无需修改合同矩阵。

**Evidence:** [P4b0 前置核查报告](../reports/2026-11-09-p4b0-preflight-report.md)。

**Commit:** `docs(p4): record implementation preflight`（只有实际新增前置记录时提交；无内容变化则不创建空提交）

## 5. P4b1 — Tivoo HA 集成骨架、服务注册与 StopCountdown/SetVolume 服务切片

**Purpose:** 从当前空目录建立 HA `tivoo` 集成，先打通两个基础服务：无参数 StopCountdown 与 SetVolume。同步建立媒体目录配置基础，供 P4b4 媒体服务使用；本批不引入 LLM Tool 或 MCP。

**Files (expected):**

- Create: `homeassistant/custom_components/tivoo/manifest.json`、`__init__.py`、`const.py`。
- Create: 按 HA Config Entry 实际加载方式新增最小 `config_flow.py` 与必要翻译；提供 `media_directory` 配置，默认 `pixelart`，路径相对 HA 配置目录。不保存设备 Token 或 AstrBot 凭据。
- Create: `services.py`、`services.yaml`；Python 服务 Schema 是执行时校验依据，YAML 只描述 UI 文案/字段，二者保持一致。
- Create: 最小的语义命令接口及适配器；按实际代码结构决定是否单独模块，不预先铺设多层抽象。
- Tests: `tests/homeassistant/custom_components/tivoo/` 下的加载、卸载、服务 Schema、服务调用和失败测试。

**Tasks:**

- [x] 先写 RED：HA 能发现并加载集成、Config Entry setup/unload、单实例约束和 `media_directory` 默认配置行为。
- [x] 先写 RED：注册 `tivoo.stop_countdown`，无必需参数；传入不允许的参数/缺失服务必须明确报错。
- [x] 先写 RED：注册 `tivoo.set_volume`，必需字段 `volume: integer`，范围 0–100（含边界）；确认 0 不会被当成缺省值。
- [x] 定义一个受限的语义命令接缝：本批传递 `stop_countdown`、`set_volume`，后续按 MVP 批次增加已明确的表情、文字、亮度、倒计时和媒体动作；不接受任意 domain/service 或原始协议帧。
- [x] 测试使用内存适配器捕获 StopCountdown 和 SetVolume 请求；未配置生产设备适配器时使用明确的 unavailable 实现并抛出 HA 可识别错误。
- [x] StopCountdown 的服务调用不得要求启动时长，不读取或保存倒计时剩余时间。
- [x] SetVolume 必须精确保留输入 0、100；拒绝小于 0、大于 100 和非整数。服务处理不得使用 `volume or default`。
- [x] 服务注册与卸载跟随 Config Entry 生命周期，避免重复注册或卸载后残留 handler。
- [x] 只使用 HA 原生集成/服务机制；不添加 TCP socket、SPP、ESP32 连接或命令帧编码。

**Exit gate:**

- [x] Tivoo Config Entry 可 setup/unload，服务恰好注册一次并能正确卸载。
- [x] 无参数 StopCountdown 与 SetVolume（0–100）两个服务均通过测试适配器生成明确的语义命令；生产适配器缺失时调用失败而非伪成功。
- [x] 没有接入 P3 Conversation Agent、HA MCP 路由或任何 ESP32 传输代码。
- [x] 聚焦测试、相关 P3 回归、Ruff、compileall（适用时）和 `git diff --check` 通过。

**Evidence:** [P4b1 实施报告](../reports/2026-11-09-p4b1-implementation-report.md)。

**Commit:** `feat(p4): add Tivoo HA integration with countdown stop and volume services`

## 6. P4b2 — HA LLM Tools 平台与 StopCountdown Tool

**Purpose:** 通过首个 StopCountdown Tool 验证 HA 的真实 LLM Tools 注册路径与服务复用关系。其他 MVP Tools 在 P4b3/P4b4 按原批次完成，本批不提前实现。

**Files (expected):**

- Create: `homeassistant/custom_components/tivoo/llm.py`。
- Modify: Tivoo 集成初始化/服务模块，仅为提供当前集成运行时和服务调用所需的最小引用。
- Tests: LLM platform 注册、API 过滤、工具调用及错误返回测试。

**Tasks:**

- [x] 先写 RED：HA LLM 平台能发现 Tivoo `llm.py`；只对 `api_id == LLM_API_ASSIST` 返回工具，其他 API 返回 `None`。
- [x] 使用同步 callback `async_get_tools(hass, llm_context, api_id) -> LLMTools | None`；遵循 HA Core 2026.11.0 LazyIntegrationPlatforms 接口，不将其写成 async，也不加入实体 `PLATFORMS`。
- [x] 注册 `tivoo__StopCountdown`；工具继承 HA `Tool`，参数采用 `probatio.Schema`，工具显式设置 `integration="tivoo"`。
- [x] 工具调用只调用 `hass.services.async_call("tivoo", "stop_countdown", {}, blocking=True, context=llm_context.context)`；不在 Tool 内构造帧或直达设备。
- [x] 显式设置 ToolAnnotations：`read_only=False`、`destructive=False`、`idempotent=True`、`open_world=False`，不依赖 HA 默认值。
- [x] 返回 `ToolResult(data=<JSON object>)`。服务缺失、设备不可用和校验错误必须传播为工具失败。
- [x] 只有 Tivoo Config Entry 正常加载时才暴露项目工具；集成未配置/卸载后不留下无效 Tool。
- [x] 在测试中验证普通非管理员 HA 用户访问 Assist API 的范围；不把工具注册到 `homeassistant` 管理 API。

**Exit gate:**

- [x] P4-C03、C06、C07、C08 的 StopCountdown 垂直切片通过。
- [x] Assist API 工具清单包含 `tivoo__StopCountdown`，管理 API 不包含该工具。
- [x] MCP Tool → HA Service 的调用参数无额外字段，且服务异常不被包装成成功结果。
- [x] P3 Conversation Agent 与 HTTP/SSE 测试无变化、无回归。

**Evidence:** [P4b2 实施报告](../reports/2026-11-09-p4b2-implementation-report.md)。

**Commit:** `feat(p4): expose countdown stop as HA LLM tool`

## 7. P4b3 — 表情、文字、倒计时工具与亮度服务

**Purpose:** 完成 MVP 的表情预设、文字显示、倒计时启动和亮度 HA Service，并提供 SetVolume MCP Tool（其 HA Service 已在 P4b1 完成）。本批以下项目全部是 MVP 必须。

**Expected files:**

- Modify: Tivoo `services.py`、`services.yaml`、`llm.py`、语义命令接口及允许复用的 preset/text render modules。
- Tests: preset registry、text rendering/service schema、countdown start、brightness service、volume MCP Tool、ToolAnnotations and service delegation.

**Tasks:**

- [x] 为 `tivoo.set_expression` 实现必需 `name`；只接受运行时 preset registry 中真实存在且非隐藏的预设名称，未知项拒绝。
- [x] 注册 `tivoo__SetExpression`，参数只包含 `name`；Tool 只调用 `tivoo.set_expression` HA Service。
- [x] 为 `tivoo.show_text` 实现必需 `value` 与可选 `color`、`background`、`speed`、`step`、`font_size`、`font`；`step=1–8`、`font_size=8–16`，`font` 必须来自有效字体列表。
- [x] 不在 Service 或 Tool schema 暴露 `font_file`；字体文件路径属于服务端资源，拒绝用户/LLM 传入本机路径。
- [x] 注册 `tivoo__ShowText`，参数与 HA Service 完全一致；Tool 只调用 `tivoo.show_text`。
- [x] 为 `tivoo.start_countdown` 增加必需 `countdown: string`；严格 `MM:SS`，分钟 00–99、秒 00–59；拒绝宽松格式、小时和静默截断。
- [x] `tivoo.start_countdown` 复用语义命令接缝，映射上游 `show_countdown(value=True, countdown=...)`；注册 `tivoo__StartCountdown`，Tool 只调用对应 Service。
- [x] 为 `tivoo.set_brightness` 注册 HA Service，`value: integer 0–100`；这是 MVP 必需服务，按原计划不注册重复 `SetBrightness` MCP Tool。
- [x] 在 `llm.py` 注册 `tivoo__SetVolume`，必需整数 `volume` 0–100；只调用 P4b1 已实现的 `tivoo.set_volume`，不复制音量映射/payload 逻辑。
- [x] ToolAnnotations：SetExpression、ShowText、StartCountdown 为 `idempotent=False`；SetVolume 为 `idempotent=True`；写操作统一 `read_only=False`、`destructive=False`、`open_world=False`、`integration="tivoo"`。
- [x] 所有 Tool 都使用 `hass.services.async_call(..., blocking=True, context=llm_context.context)` 调用服务，不得直达命令适配器。
- [x] 测试覆盖有效/无效 preset、文字样式上下界、禁止 `font_file`、倒计时格式边界、亮度 0/100 与越界、音量 0/100 与越界；音量 0 必须无损到达 b1 服务/适配器。
- [x] 优先复用与当前功能合同匹配的纯 payload/render builder，并添加或沿用 golden tests；先核对本机副本与固定上游 commit 的差异、保留来源声明。若某个具体模块确实不适合当前运行环境或边界，再仅为该模块做最小适配；不得因单独 LICENSE 文件缺失而重写整套 wire encoder。

**Exit gate:**

- [x] `SetExpression`、`ShowText`、`StartCountdown`、`SetVolume` 四个 Tool 均注册并映射到对应 HA Service。
- [x] `SetBrightness` HA Service 注册且范围为 0–100；没有创建同义 MCP Tool。
- [x] preset、文字、倒计时、亮度、音量的正常/异常参数测试通过；字体本地路径不从 Tool 输入到达。
- [x] 服务/适配器错误向上传播，没有成功字符串伪装。
- [x] 聚焦测试、P4b2 回归、P3 测试、Ruff 与 `git diff --check` 通过。

**Commit:** `feat(p4): implement Tivoo expression text countdown and brightness MVP`

## 8. P4b4 — 图片/GIF 文件处理与媒体 Tools

**Purpose:** 实现 MVP 必需的图片与 GIF 文件处理。P4 只接收 HA 配置目录下 `media_directory` 内的相对文件引用，不增加远程资源协议。

**Files (expected):**

- Modify: Tivoo `services.py`、`services.yaml`、`llm.py`、媒体路径/图像解码模块（只在形成清晰复用边界时拆分）。
- Tests: PNG/JPG/GIF fixtures、路径边界、GIF timing、Tool→Service delegation tests.

**Tasks:**

- [ ] 使用 P4b1 创建的 `media_directory` 配置；默认 `pixelart`，根目录通过 `hass.config.path()` 解析。
- [ ] 为 `tivoo.show_image` 增加必需 `file: string` 和可选 `time: integer`；支持静态 PNG/JPG 和 GIF。
- [ ] 为 `tivoo.play_animation` 增加必需 GIF `file: string` 和可选 `time: integer`；帧目录与 JSON stage 文件不在支持范围。
- [ ] 未提供 `time` 时保留 GIF 内嵌 frame duration；提供时校验 0–65535 毫秒并覆盖帧间隔。
- [ ] 使用 `realpath()` 与 `commonpath()` 验证解析后的文件仍处于 `media_directory` 内；拒绝绝对路径、路径穿越、逃逸 symlink 和目录。
- [ ] 拒绝不存在/不可读文件、非支持格式和无效 timing；错误在 HA Service 层明确出现并作为 MCP Tool error 传播。
- [ ] `ShowImage` 与 `PlayAnimation` 共用媒体路径解析和图像/GIF 读取实现，不实现两套文件协议。
- [ ] 注册 `tivoo__ShowImage`、`tivoo__PlayAnimation`；两者只调用对应 HA Service；ToolAnnotations 均为写操作且 `idempotent=False`。
- [ ] MCP 参数不接受 URL、asset ID、NAS 任意绝对路径、原始图片字节、palette、frame arrays 或 HTTP 资源地址。
- [ ] 测试使用 HA media directory 下的 PNG/JPG/GIF 测试夹具；至少验证一张静态图和一份多帧 GIF 被正确解析/转发，及文件不存在/路径逃逸的错误传播。
- [ ] 不实现 AstrBot 生成文件跨容器复制/上传协议。运行时使用者需将待显示文件放入 HA `media_directory`；P4 不发明 URL/asset ID。

**Exit gate:**

- [ ] `ShowImage` 支持静态 PNG/JPG/GIF，`PlayAnimation` 仅支持 GIF；参数符合合同矩阵。
- [ ] 有效相对路径通过；越界、symlink 逃逸、目录、URL、绝对路径、无效格式、缺失文件均明确拒绝。
- [ ] GIF 原始时长和显式 `time` 覆盖由测试证明。
- [ ] 两个 Tool 调用对应 HA Service，共用文件路径与帧处理逻辑，没有 MCP 二进制载荷。
- [ ] 聚焦测试、P4b2/P4b3 回归、P3 全套测试、Ruff 与 `git diff --check` 通过。

**Commit:** `feat(p4): implement Tivoo image and GIF MVP tools`

## 9. P4b5 — AstrBot MCP 配置、Persona 与运行时验证

**Purpose:** 使用 AstrBot 4.29.4 已有 MCP Client 连接 HA 原生 Assist MCP API，确认目标 Agent Persona 实际发现并获准使用全部七个 MVP Tivoo Tool；不写 AstrBot 插件或自定义 Client。

**Configuration contract:**

- Server name：稳定名称，例如 `home-assistant-tivoo`。
- Transport：`streamable_http`。
- URL：`http(s)://<HA LAN 地址>:8123/api/mcp/assist`。
- Header：`Authorization: Bearer <HA Long-Lived Access Token>`。
- 使用专用普通 HA 用户 Token；不得改用需要管理员权限的聚合/管理 API。

**Tasks:**

- [ ] 在 AstrBot WebUI 添加 HA MCP Server；凭据由用户/现有安全配置入口录入，不写入 Git、计划、截图、日志或测试 fixture。
- [ ] 确认 MCP initialize 成功，`tools/list` 发现七个 MVP Tool：SetExpression、ShowText、StartCountdown、StopCountdown、SetVolume、ShowImage、PlayAnimation。
- [ ] 将七个 MVP Tool 授权给实际 Tivoo 助手使用的 Agent Persona；确认它们进入 Persona 的可调用工具集。
- [ ] 检查完整 `tools/list`：HA Assist API 可能聚合其他集成工具；按 integration/source 区分，只要求本项目七个 MVP Tool 完整出现。
- [ ] 在独立开发 HA（启用内存测试适配器）环境通过 MCP 调用七个工具，验证每个 `tools/call` 经过 HA LLM Tool → 对应 HA Service → 语义 Adapter；图片/GIF 使用 HA media directory 中的测试文件。
- [ ] 通过 HA Service 直接调用 `tivoo.set_brightness`，验证 0、100、越界输入；此服务不要求存在同义 MCP Tool。
- [ ] 对 StartCountdown、StopCountdown、SetVolume 分别验证参数到达适配器；SetVolume 测试 0 和 100；验证服务错误作为 MCP tool error 返回。
- [ ] 验证有效普通用户 Token 可访问 Assist API，错误 Token 被拒绝；确认不会授予 AstrBot HA 管理权限。
- [ ] 验证 AstrBot MCP 断开重连和 4.29.4 实际重试行为；对非幂等动作使用测试适配器模拟响应丢失，不在真实 Tivoo 上重复触发动画或倒计时。
- [ ] 若目标 HA/AstrBot 环境不可访问或没有可用凭据，完成本地协议/接口验证后将对应运行时项标为 BLOCKED；不读取 NAS 配置文件寻找 Token，也不以静态配置猜测连接成功。

**Exit gate:**

- [ ] AstrBot 4.29.4 完成 HA Streamable HTTP initialize 和七个 MVP Tool 的发现。
- [ ] 目标 Persona 已获准使用全部七个 MVP Tool；独立开发 HA 与内存适配器可用时，七个工具均完成一次端到端工具调用。
- [ ] 亮度 HA Service 的成功/参数错误路径有运行时或自动化测试证据。
- [ ] 普通 HA 用户认证、无效 Token 拒绝、服务异常映射均有证据。
- [ ] 非幂等 Tool 的重连/重试风险有可复现测试记录；没有叠加自定义通用重试层。
- [ ] Token 没有进入仓库、测试输出或验收报告。

**Commit:** `test(p4): verify AstrBot access to all Tivoo MVP tools`

## 10. P4b6 — 合同矩阵验收与收尾

**Purpose:** 验收全部明确列入 MVP 的功能实现，并重点证明倒计时启动、倒计时停止和音量调整的完整 AstrBot→MCP→HA→Service→Adapter 调用链。其他未声明 Tivoo 服务仍作为可选扩展，不纳入本次验收范围。

**Tasks:**

- [ ] 对照 P4-C01 至 P4-C15 建立合同追踪表；每项链接到具体测试、命令输出或受控运行证据。
- [ ] 验证 MCP 路由、Streamable HTTP、七个必需 Tool 的发现和 Persona 授权、普通用户认证与 Assist API 权限。
- [ ] 验证 SetExpression、ShowText、ShowImage、PlayAnimation 四个显示/媒体 Tool 的参数 Schema、服务委派、正常执行路径和失败传播。
- [ ] 验证 SetBrightness Service 的 0–100 参数边界和调用路径；它是 HA Service，不要求另建 SetBrightness MCP Tool。
- [ ] 验证 StartCountdown、StopCountdown、SetVolume 三项完整链路：通过 AstrBot Persona 分别执行 `MM:SS` 启动、无参停止、音量 0/100 设置；逐层确认 MCP `tools/call`、HA LLM Tool、HA Service 和内存语义 Adapter 收到的动作/参数一致。
- [ ] 通过错误输入测试确认倒计时格式、音量边界、媒体路径越界和文字/preset 非法输入会明确失败，不产生伪成功。
- [ ] 媒体验收覆盖相对 media_directory、PNG/JPG/GIF、GIF timing、路径穿越/逃逸 symlink/缺失文件拒绝。
- [ ] 验证 StopCountdown 无参数语义及对应 wire payload。若 P4 当前范围只覆盖 HA Service/语义 Adapter，字节级验证由复用的 payload builder 测试或 P6 传输 Adapter 验证；不在 LLM Tool 层另写编码器。
- [ ] 验证 AstrBot 4.29.4 断线恢复/重试，不引入自定义协议或额外重试框架。
- [ ] 运行 P3 全套 HA 测试，确认 Chat API、session、SSE、ChatLog、取消与 P4 完全隔离。
- [ ] 运行开发机完整测试与静态检查：`./scripts/test-ha.sh -q`、Ruff check、Ruff format check、Python compileall、`pip check`、`git diff --check`。
- [ ] 检查变更范围只涉及 Tivoo HA 集成、对应测试、必要依赖与 P4 文档；没有改动 P3 实现、AstrBot 插件、ESP32、TCP 7777/7778 或 NAS 部署文件。
- [ ] 创建 P4 验收报告，区分自动化 PASS、AstrBot 运行时 PASS、媒体文件交接限制和设备实测 DEFERRED。
- [ ] 仅在全部对应门通过后更新 README 的 P4 状态；未通过项保留明确状态和后续归属。

**Exit gate:**

- [ ] P4-C01–C13、C15 的 MVP 适用项均有 PASS/PARTIAL/BLOCKED 结论及证据；没有把未声明服务列成遗漏。
- [ ] 表情、文字、亮度 Service、图片/GIF、倒计时启停和音量调整的所有实现与参数合同均有测试/运行时证据。
- [ ] AstrBot 实际 Persona 能发现并调用七个 MVP Tool。
- [ ] StartCountdown、StopCountdown、SetVolume 的 MCP → HA LLM Tool → HA Service → 语义 Adapter 完整链路全部通过；所有失败路径都没有伪成功。
- [ ] P3 回归、类型/静态检查与 diff 检查通过。
- [ ] C14 实机动作不作为 P4 关闭前提；真实硬件回执转交 P5/P6。
- [ ] 最终变更审查完成并本地提交；不 push、不 merge。

**Commit:** `test(p4): accept all Tivoo MVP features and core MCP flow`

## 11. 合同到批次追踪

| 合同 ID | 主要 Batch | MVP 验证重点 |
|---|---|---|
| P4-C01 MCP 路由 | P4b0、P4b5 | HA 原生 `/api/mcp/assist` 可达 |
| P4-C02 Streamable HTTP | P4b0、P4b5 | AstrBot 4.29.4 initialize 与 Bearer header |
| P4-C03 工具发现 | P4b2–P4b5 | 七个 MVP Tool 出现在指定 Persona |
| P4-C04 权限边界 | P4b0、P4b5 | 普通 HA 用户 Token 可用；错误 Token 拒绝；不使用管理 API |
| P4-C05 实体暴露 | P4b5、P4b6 | 原生工具只作用于暴露给 Assist 的实体；项目自定义 Tool 是明确动作 |
| P4-C06 Tool 注册过滤 | P4b2–P4b4 | 仅 `api_id=assist` 返回七个 MVP Tool |
| P4-C07 服务复用 | P4b1–P4b4 | 七个 Tool 调用对应 HA Service；Brightness Service 独立可调用 |
| P4-C08 失败传播 | P4b1–P4b6 | 参数错误、媒体文件错误、服务缺失、适配器不可用均不伪成功 |
| P4-C09 MVP 参数范围 | P4b1–P4b3、P4b6 | 倒计时 MM:SS/Stop 无参；Volume/Brightness 0–100；preset/text schema |
| P4-C10 媒体边界 | P4b1、P4b4–P4b6 | media_directory、PNG/JPG/GIF、GIF timing、路径越界拒绝 |
| P4-C11 P3 回归 | P4b2–P4b6 | P3 Chat/SSE/session/ChatLog 不变 |
| P4-C12 断线与重试 | P4b5、P4b6 | 使用 AstrBot 4.29.4 实际重连行为；记录非幂等动作返回丢失风险 |
| P4-C13 设备传输隔离 | P4b1–P4b6 | AstrBot 不连接 TCP 7777/7778、ESP32/SPP |
| P4-C14 Tivoo 实机动作 | P5/P6 | 不作为 P4 退出条件；交由设备通信和硬件验收 |
| P4-C15 未声明功能边界 | P4b6 | 其他未声明服务不混入 MVP；按完整矩阵保留为可选扩展或 Excluded |

## 12. 全局实施与测试规则

- 一个 Batch 一个执行任务、一个独立提交；执行提示必须引用本批次编号、本文和 P4 合同矩阵，并明确“仅做当前批次”。表情、文字、亮度 Service、图片/GIF、倒计时启停和音量均属本版必做；只有未明确列入清单的其他 Tivoo 服务才是可选扩展。
- 每个新增服务/Tool 行为先写能观察公开行为的 RED 测试，再实现最小逻辑并 GREEN。测试通过服务与 HA Assist/MCP 接缝，不绑定内部类结构。
- 优先复用 HA Core 的 Config Entry、Service Registry、LLM Tools、Assist API、MCP Server 和现有 P3 测试脚手架。AstrBot MCP Client 复用 4.29.4 原生实现。
- HA 服务 Schema 与 LLM Tool 的 `probatio.Schema` 可能属于不同验证框架；共享一份参数合同，分别适配框架并通过合同测试检查字段、类型、默认值和范围，不强行共享不兼容的 Schema 对象。
- Tool 调用服务必须等待服务执行结果，以便传播 ServiceNotFound/ServiceValidationError/设备不可用错误；不把异步事件已排队当作设备动作完成。
- 测试适配器只用于开发机合同测试。生产默认适配器在 P6 传输接入前应清楚报告 unavailable；不可在生产中自动切换为“成功的内存适配器”。
- 文件测试只读取 HA 配置 media directory 内的测试文件；不通过任意 HTTP URL、共享外部绝对路径或原始二进制简化文件交接。
- 每批结束运行本批聚焦测试和必要回归；P4b2 之后至少运行 P3 现有测试。最终运行 `./scripts/test-ha.sh -q`、Ruff check/format、compileall、pip check 和 `git diff --check`。
- 不在 NAS 上运行耗时测试或负载测试。开发机 Ubuntu 测试通过后，只进行必要的远程 MCP 连通/配置验证；不扫描、清理或修改无关 NAS 文件、容器和会话。
- 每批结束记录：基线 SHA、实际修改文件、RED/GREEN 命令与结果、静态检查、人工验收状态、提交 SHA、剩余 BLOCKED/DEFERRED 项。所有明确列入 MVP 的功能都必须有验收证据；仅未声明的其他服务允许保持 DEFERRED。
- 遇到合同缺失、上游版本变化、HA 实际服务语义不同或 AstrBot 工具发现与预期不一致，先停止受影响批次并更新合同/计划。若来源或具体模块的许可/声明存在疑点，只暂停该模块的引入，核实或换用其他已有实现；不得把局部问题扩大为整个 SDK 禁用，也不得因此自动重写已有协议/编码器。
- 用户未另行授权时不部署生产改动、不更改生产 HA Config Entry、不触发真实 Tivoo 非幂等动作、不 push、不 merge。

## 13. P4 范围外项目

以下工作明确不属于 P4：

- TCP 7777 原始 Tivoo frame bridge、TCP 7778 音频/状态协议、ESP32 固件和 Classic SPP。
- Tivoo 实际屏幕、表情、GIF、倒计时硬件动作的确认回执；这些属于 P5/P6 实机测试。
- Assist Satellite 音频会话、麦克风 PCM、STT、TTS、HTTP 音频 URL 获取及主动播报生命周期。
- AstrBot 主动任务插件、主动对话和情绪决策（P9）。
- 自定义 MCP Server、额外 MCP Client、任意 HA Service Call Tool、通用任务队列、请求去重数据库或额外传输协议。
- 自动将 AstrBot 生成的媒体文件跨容器复制到 HA media directory。上游合同目前没有对应 URL/asset ID 协议；待确认可用共享目录或由后续网关提供明确文件交接方案。

---
