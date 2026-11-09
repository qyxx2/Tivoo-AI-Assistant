# P4 Home Assistant MCP / Tivoo LLM Tools — Batch Execution Plan

> 状态：仅计划，尚未实现。
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
- 先核对 `BluetoothBridgeTest/tivoo/UPSTREAM.md` 声明的来源及许可证，并查看上游仓库当前许可证文件。纯 Python 模块在许可证和版权义务确认后才可 vendoring；不能从外部工作区绝对路径运行时导入，也不能把 BluetoothBridge Transport 带入 HA。
- 当前 `homeassistant/custom_components/tivoo/` 只有占位文件。不得假定有现成的 Tivoo HA 服务、实体、LLM Tools 或设备连接管理器。
- 不读取、复制或写入 NAS 上的 HA/AstrBot Token；任何需要真实凭据的 UI 配置由用户提供/录入或使用现有安全凭据存储。

## 3. 批次与依赖图

| Batch | 内容 | 依赖 | 独立交付 / 第一版要求 |
|---|---|---|---|
| P4b0 | 版本、源码、测试和协议复用前置核对 | 无 | 可执行的本地实施基线与阻塞项记录；必须 |
| P4b1 | Tivoo HA 集成骨架、服务注册与 StopCountdown、SetVolume 服务 | P4b0 | HA 可加载集成；两个服务有真实成功/失败语义；必须 |
| P4b2 | HA LLM Tools 平台与首个 StopCountdown Tool 垂直切片 | P4b1 | Assist API 正确发现 StopCountdown Tool；必须 |
| P4b3 | 表情、文字、倒计时工具与亮度服务 | P4b2 | StartCountdown Service/Tool、SetVolume Tool 是 MVP 必须部分；表情/文字/亮度为保留的可选扩展 |
| P4b4 | 图片/GIF 文件处理、服务与媒体 Tools | P4b2 | 完整保留为可选媒体扩展，不阻塞首版 |
| P4b5 | AstrBot MCP 配置、Persona 授权与运行时验证 | P4b3；若验证媒体扩展则另需 P4b4 | 验证 AstrBot 可调用三个首版必需 Tool；必须 |
| P4b6 | P4-C01–C15 合同验收、P3 回归与收尾 | P4b5 | MVP 证据齐全；可选扩展标为 DEFERRED；必须 |

第一版依赖路径：

```text
P4b0 → P4b1 → P4b2 → P4b3(MVP 子集) → P4b5 → P4b6
                         └──────── P4b4（可选媒体扩展，不阻塞 MVP）
```

P4b3 中表情/文字/亮度与 P4b4 媒体任务均保留原合同和实现设计，但第一版不执行这些可选子任务。若用户在首版验收后决定纳入扩展，再恢复相应子任务并追加独立提交/验收；不能把“暂缓”解释成“从 P4 计划删除”。

## 4. P4b0 — 版本、源码与本地验证前置

**Purpose:** 在编写 Tivoo 集成前确认当前可依赖的上游接口和本地验证条件。此批只做核查、计划必要修订和记录，不实现工具代码。

**Tasks:**

- [ ] 核对 HA Core 实际目标版本及本地 `homeassistant.helpers.llm`、`homeassistant.components.llm`、`mcp_server` 的真实接口。
- [ ] 核对 AstrBot 4.29.4 `mcp_client.py` 的 Streamable HTTP、headers、工具发现/调用和断线重试路径；不创建自己的 MCP Client。
- [ ] 确认 `/api/mcp/assist` 与 Assist API 的认证、权限和工具集合行为；区分 Assist API 与管理 API。
- [ ] 核对项目现有 HA 测试入口、P3 自动化回归、Ruff/compile 检查；记录完整测试命令。
- [ ] 核实 Tivoo Python 纯协议模块的上游许可证和本机来源声明。若证据不足，不复制源码；不得用运行时引用外部工作区的方式绕过部署边界。
- [ ] 记录本轮实际需要复用的纯函数范围，以及不复用的 BluetoothBridge/直接 SPP Transport。
- [ ] 将版本变化、接口差异、许可证不确定性或 AstrBot WebUI 无法访问等真实问题列为明确阻塞，不通过猜测参数继续。

**Exit gate:**

- [ ] HA/AstrBot 版本和关键方法签名有当前源码依据。
- [ ] 本地 P3 测试和静态检查能运行；测试命令与环境已明确。
- [ ] 已决定是否允许复用纯 Tivoo SDK 代码；未确认的代码不进入项目。
- [ ] 若任何接口与 P4 矩阵不符，先更新矩阵并单独提交，再开始 P4b1。

**Commit:** `docs(p4): record implementation preflight`（只有实际新增前置记录时提交；无内容变化则不创建空提交）

## 5. P4b1 — Tivoo HA 集成骨架、服务注册与 StopCountdown/SetVolume 服务切片

**Purpose:** 从当前空目录建立 HA `tivoo` 集成，先打通两个首版基础服务：无参数 StopCountdown 与 SetVolume。用它们验证 Service Schema、语义命令分派和失败传播；本批不引入 LLM Tool 或 MCP。

**Files (expected):**

- Create: `homeassistant/custom_components/tivoo/manifest.json`、`__init__.py`、`const.py`。
- Create: 如 HA Config Entry 加载路径确有需要，再新增最小 `config_flow.py` 与必要翻译。第一版不引入 `media_directory` 配置项；该选项仅在 P4b4 媒体扩展获准实施时增加。不保存设备 Token 或 AstrBot 凭据。
- Create: `services.py`、`services.yaml`；Python 服务 Schema 是执行时校验依据，YAML 只描述 UI 文案/字段，二者保持一致。
- Create: 最小的语义命令接口及适配器；按实际代码结构决定是否单独模块，不预先铺设多层抽象。
- Tests: `tests/homeassistant/custom_components/tivoo/` 下的加载、卸载、服务 Schema、服务调用和失败测试。

**Tasks:**

- [ ] 先写 RED：HA 能发现并加载集成、Config Entry setup/unload 与单实例约束；不为首版媒体扩展创建配置项。
- [ ] 先写 RED：注册 `tivoo.stop_countdown`，无必需参数；传入不允许的参数/缺失服务必须明确报错。
- [ ] 先写 RED：注册 `tivoo.set_volume`，必需字段 `volume: integer`，范围 0–100（含边界）；确认 0 不会被当成缺省值。
- [ ] 定义一个受限的语义命令接缝：当前 MVP 只传递 `stop_countdown`、`set_volume`，不接受任意 domain/service 或原始协议帧。
- [ ] 测试使用内存适配器捕获 StopCountdown 和 SetVolume 请求；未配置生产设备适配器时使用明确的 unavailable 实现并抛出 HA 可识别错误。
- [ ] StopCountdown 的服务调用不得要求启动时长，不读取或保存倒计时剩余时间。
- [ ] SetVolume 必须精确保留输入 0、100；拒绝小于 0、大于 100 和非整数。服务处理不得使用 `volume or default`。
- [ ] 服务注册与卸载跟随 Config Entry 生命周期，避免重复注册或卸载后残留 handler。
- [ ] 只使用 HA 原生集成/服务机制；不添加 TCP socket、SPP、ESP32 连接或命令帧编码。

**Exit gate:**

- [ ] Tivoo Config Entry 可 setup/unload，服务恰好注册一次并能正确卸载。
- [ ] 无参数 StopCountdown 与 SetVolume（0–100）两个服务均通过测试适配器生成明确的语义命令；生产适配器缺失时调用失败而非伪成功。
- [ ] 没有接入 P3 Conversation Agent、HA MCP 路由或任何 ESP32 传输代码。
- [ ] 聚焦测试、相关 P3 回归、Ruff、compileall（适用时）和 `git diff --check` 通过。

**Commit:** `feat(p4): add Tivoo HA integration with countdown stop and volume services`

## 6. P4b2 — HA LLM Tools 平台与 StopCountdown Tool

**Purpose:** 通过第一项工具验证 HA 的真实 LLM Tools 注册路径与服务复用关系。选择 StopCountdown，是因为其公开合同无参数，能同时验证空 Schema、错误传播和不依赖历史倒计时状态。

**Files (expected):**

- Create: `homeassistant/custom_components/tivoo/llm.py`。
- Modify: Tivoo 集成初始化/服务模块，仅为提供当前集成运行时和服务调用所需的最小引用。
- Tests: LLM platform 注册、API 过滤、工具调用及错误返回测试。

**Tasks:**

- [ ] 先写 RED：HA LLM 平台能发现 Tivoo `llm.py`；只对 `api_id == LLM_API_ASSIST` 返回工具，其他 API 返回 `None`。
- [ ] 使用同步 callback `async_get_tools(hass, llm_context, api_id) -> LLMTools | None`；遵循 HA Core 2026.11.0 LazyIntegrationPlatforms 接口，不将其写成 async，也不加入实体 `PLATFORMS`。
- [ ] 注册 `tivoo__StopCountdown`；工具继承 HA `Tool`，参数采用 `probatio.Schema`，工具显式设置 `integration="tivoo"`。
- [ ] 工具调用只调用 `hass.services.async_call("tivoo", "stop_countdown", {}, blocking=True, context=llm_context.context)`；不在 Tool 内构造帧或直达设备。
- [ ] 显式设置 ToolAnnotations：`read_only=False`、`destructive=False`、`idempotent=True`、`open_world=False`，不依赖 HA 默认值。
- [ ] 返回 `ToolResult(data=<JSON object>)`。服务缺失、设备不可用和校验错误必须传播为工具失败。
- [ ] 只有 Tivoo Config Entry 正常加载时才暴露项目工具；集成未配置/卸载后不留下无效 Tool。
- [ ] 在测试中验证普通非管理员 HA 用户访问 Assist API 的范围；不把工具注册到 `homeassistant` 管理 API。

**Exit gate:**

- [ ] P4-C03、C06、C07、C08 的 StopCountdown 垂直切片通过。
- [ ] Assist API 工具清单包含 `tivoo__StopCountdown`，管理 API 不包含该工具。
- [ ] MCP Tool → HA Service 的调用参数无额外字段，且服务异常不被包装成成功结果。
- [ ] P3 Conversation Agent 与 HTTP/SSE 测试无变化、无回归。

**Commit:** `feat(p4): expose countdown stop as HA LLM tool`

## 7. P4b3 — 表情、文字、倒计时工具与亮度服务

**Purpose:** 延续原定 P4b3 范围。在这个批次中完成首版剩余必需能力（StartCountdown、SetVolume Tool），并保留表情、文字和亮度服务的可选扩展设计。首版执行时只做 MVP 必需子集；表情/文字/亮度子任务不提前混入首版。

### 7.1 第一版必须完成的 MVP 子集

**Expected files:**

- Modify: Tivoo `services.py`、`services.yaml`、`llm.py`、语义命令接口。
- Tests: StartCountdown Service/Tool、SetVolume Tool 参数、服务委派、注解与失败路径。

**Tasks:**

- [ ] 先写 RED：注册 `tivoo.start_countdown`，必需 `countdown: string`，严格格式 `MM:SS`；分钟 00–99、秒 00–59。
- [ ] `tivoo.start_countdown` 复用 b1 的语义命令接缝；映射上游 `show_countdown(value=True, countdown=...)`，不接受小时、宽松格式或静默截断。
- [ ] 在 `llm.py` 中注册 `tivoo__StartCountdown`，参数 Schema 与 HA Service 完全一致；Tool 只调用对应 Service。
- [ ] 在 `llm.py` 中注册 `tivoo__SetVolume`，必需整数 `volume` 0–100；该 Tool 只调用 P4b1 已实现的 `tivoo.set_volume`，不复制音量映射或 payload builder。
- [ ] StartCountdown 显式设置 `idempotent=False`；SetVolume 设置 `idempotent=True`；两者都设置 `read_only=False`、`destructive=False`、`open_world=False` 和 `integration="tivoo"`。
- [ ] StartCountdown / SetVolume 的 HA Service Schema 与 `probatio.Schema` 分别适配框架，并以合同测试验证字段、类型、必需性和范围一致。
- [ ] 所有 Tool 都通过 `hass.services.async_call(..., blocking=True, context=llm_context.context)` 调用服务，不得直达命令适配器。
- [ ] SetVolume 测试覆盖 0、100、越界和非整数；0 必须无损到达 b1 的服务/适配器。
- [ ] 若 b0 许可证/来源检查允许复用纯 payload builder，可在此添加 golden test；否则只验证语义命令，不复制或手写 wire encoder。

**MVP Exit gate:**

- [ ] 首版三个工具 `StartCountdown`、`StopCountdown`、`SetVolume` 均已注册；StopCountdown 在 b2 已有测试，StartCountdown/SetVolume 在本批通过测试。
- [ ] 三个 Tool 均只调用对应的 HA Service；所有参数限制与合同矩阵一致。
- [ ] SetVolume 的 0、100 和范围拒绝行为通过测试；StartCountdown 的 MM:SS 边界通过测试。
- [ ] 服务/适配器错误向上传播，没有成功字符串伪装。
- [ ] 聚焦测试、P4b2 回归、P3 测试、Ruff 与 `git diff --check` 通过。

**MVP Commit:** `feat(p4): add countdown start and volume MCP tools`

### 7.2 保留的可选扩展子集（不属于第一版执行门）

首版验收前不执行以下任务。它们保留在 P4b3，只有在核心链路通过且明确决定扩展时才恢复执行：

- `tivoo.set_expression` / `tivoo__SetExpression`：`name` 只接受运行时 preset registry 中真实存在且非隐藏的预设；拒绝未知项。
- `tivoo.show_text` / `tivoo__ShowText`：`value` 加可选 `color`、`background`、`speed`、`step`、`font_size`、`font`；`step=1–8`、`font_size=8–16`，font 必须来自有效字体名称；不得暴露 `font_file`。
- `tivoo.set_brightness`：普通 HA Service，范围 0–100；AI 控制优先通过未来的 `number.tivoo_brightness` 原生实体，不注册重复的 `SetBrightness` Tool。
- 扩展工具仍须复用同一 HA Service/语义适配器边界；各自的 ToolAnnotations 和服务验证在扩展执行时按合同补齐。

**Optional extension exit gate（仅在明确排期扩展时适用）：**

- [ ] Expression、Text 和 Brightness 服务/Tool 参数符合完整合同矩阵与上游边界。
- [ ] 无效 preset/字体/显示参数拒绝；字体文件路径不会从 Tool 输入到达。
- [ ] 亮度服务 0–100；没有创建同义 `SetBrightness` Tool。
- [ ] 对应测试和必要回归通过；独立记录扩展提交。

首版报告将本小节标记为 `DEFERRED`，不把未执行当作 P4b3 MVP 缺陷。

**P4-C09 wire note:** StopCountdown 的无参数业务合同在 b1/b2 验证。若已合法复用纯 payload builder，则验证 `72 03 00 00 00`；若许可证/可部署来源未确认，字节级验证转交 P6 adapter 测试，不在 Tool 层重写协议。

## 8. P4b4 — 图片/GIF 文件合同与媒体 Tools

**Purpose:** 保留原定图片/GIF 文件处理与媒体 Tools 扩展。它不属于第一版倒计时/音量 MVP；只有在首版链路验收通过并明确决定加入媒体功能后才执行。P4 只接收 HA 配置目录内的文件引用，不增加远程资源协议。

**Files (expected):**

- Modify: Tivoo `services.py`、`services.yaml`、`llm.py`、媒体路径解析模块（仅当它能形成可复用的单一职责模块时）。
- Tests: 媒体文件夹具、路径边界、图片格式、GIF 帧时长和工具调用测试。

**Tasks:**

- [ ] 为集成配置 `media_directory` 使用 HA 配置目录相对路径，默认 `pixelart`；解析根目录时使用 `hass.config.path()`。
- [ ] 为 `tivoo.show_image` 增加必需 `file: string` 和可选 `time: integer`；静态 PNG/JPG 和 GIF 均可接受。
- [ ] 为 `tivoo.play_animation` 增加同样的 `file/time`；首期只接受 GIF，帧目录和 JSON stage 文件不属于 HA 上游服务合同。
- [ ] 未提供 `time` 时保留 GIF 内嵌 frame duration；提供时校验 0–65535 毫秒并覆盖原始帧时长。
- [ ] 用 `realpath()` 与 `commonpath()` 验证解析后的文件仍处于 media directory 内；拒绝绝对路径、路径穿越、逃逸 symlink 和目录。
- [ ] 拒绝不存在/不可读文件、非支持格式以及无效 timing；错误应在 HA Service 层清楚出现并作为 MCP Tool error 传播。
- [ ] `ShowImage` 与 `PlayAnimation` 共享媒体路径解析和 GIF/图像读取逻辑，不实现两套文件协议。
- [ ] MCP 参数不接受 URL、asset ID、NAS 任意绝对路径、原始图片字节、palette、frame arrays 或 HTTP 资源地址。
- [ ] 测试文件放在 HA media directory 测试夹具下；验证通过后只把经过验证的规范化文件引用交给语义命令接口。
- [ ] 不实现 AstrBot 生成文件跨容器复制/上传接口。该交接尚无上游合同，单独记录为后续部署问题，不发明 URL 或资源 ID。

**Optional extension exit gate（不属于 MVP 退出条件）:**

- [ ] `ShowImage` 支持静态图片/GIF，`PlayAnimation` 只支持 GIF；参数符合 P4 矩阵。
- [ ] 有效相对文件路径可通过；路径越界、symlink 逃逸、目录、URL、绝对路径和无效格式均被拒绝。
- [ ] GIF 自带时长与显式 `time` 覆盖行为由测试证明。
- [ ] 两个 Tool 调用同一 HA Service 参数合同与同一媒体处理路径，没有 MCP 二进制载荷。
- [ ] 聚焦测试、P4b2 回归、P3 全套测试、Ruff 与 diff 检查通过。

**Optional extension commit:** `feat(p4): expose Tivoo image and animation tools`

## 9. P4b5 — AstrBot MCP 配置、Persona 与运行时验证

**Purpose:** 使用 AstrBot 4.29.4 已有 MCP Client 连接 HA 原生 Assist MCP API，并确认目标 Agent Persona 实际可发现、调用项目工具。此批不写 AstrBot 插件或自定义 Client。

**Configuration contract:**

- Server name：稳定名称，例如 `home-assistant-tivoo`。
- Transport：`streamable_http`。
- URL：`http(s)://<HA LAN 地址>:8123/api/mcp/assist`。
- Header：`Authorization: Bearer <HA Long-Lived Access Token>`。
- 使用专用普通 HA 用户 Token；不得改用需要管理员权限的聚合/管理 API。

**Tasks:**

- [ ] 在 AstrBot WebUI 使用上述配置添加 HA MCP Server；凭据由用户/现有安全配置入口录入，不写入 Git、计划、截图、日志或测试 fixture。
- [ ] 确认 MCP initialize 成功，AstrBot 显示 server connected，`tools/list` 能发现三个首版必需 Tivoo Tool：StartCountdown、StopCountdown、SetVolume。
- [ ] 将该 MCP Server 的三个必需 Tool 授权给实际 Tivoo 助手使用的 Agent Persona；确认工具不只是出现在服务器列表而是进入对应 Persona 的可调用工具集。
- [ ] 检查完整 `tools/list`：HA Assist API 可能聚合其他已安装集成的 LLM Tools；按来源识别 Tivoo 工具，不假设清单只含 Tivoo，也不把第三方工具误记为项目交付。若可选扩展尚未执行，不要求这些扩展 Tool 出现。
- [ ] 在独立开发 HA（启用内存测试适配器）环境分别调用 StartCountdown、StopCountdown、SetVolume，验证 `tools/call` 经过 MCP → HA Tool → HA Service → 命令适配器；SetVolume 测试 0 和 100；验证 service error 会返回 MCP tool error。生产 HA 不安装/启用内存适配器。
- [ ] 若 P4b3 可选表情/文字子任务或 P4b4 媒体扩展已获准实施，再附加验证这些扩展 Tool；否则不要求它们存在。
- [ ] 验证有效普通用户 Token 可访问 Assist API，错误 Token 被拒绝；确认不会因为 `/api/mcp/assist` 路由把管理员权限交给 AstrBot。
- [ ] 验证 AstrBot MCP 断开重连和 4.29.4 实际重试行为；对非幂等动作使用测试适配器模拟响应丢失，不在真实 Tivoo 上重复触发动画或倒计时。
- [ ] 记录其他集成的工具是否出现在 Assist API 中，以及是否影响目标 Persona 工具选择；不为过滤第三方工具添加未经需求确认的自定义 MCP Server。
- [ ] 若目标 HA/AstrBot 环境不可访问或没有可用凭据，完成本地协议/接口验证后将运行时项标为 BLOCKED；不读取 NAS 配置文件来寻找 Token，也不以静态配置猜测连接成功。

**Exit gate:**

- [ ] AstrBot 4.29.4 完成 HA Streamable HTTP initialize 和工具发现。
- [ ] 目标 Persona 已获准使用 StartCountdown、StopCountdown、SetVolume 三个首版必需 Tool；独立开发 HA 与内存适配器可用时，三项调用均通过完整链路。若没有独立测试实例，则把完整成功调用标为 BLOCKED，只验收工具发现与不可用错误传播，不把生产环境切换为 fake adapter。
- [ ] 普通 HA 用户认证、无效 Token 拒绝、服务异常映射均有证据。
- [ ] 非幂等工具的重连/重试风险有可复现测试记录；没有叠加自定义通用重试层。
- [ ] Token 没有进入仓库、测试输出或验收报告。

**Commit:** `test(p4): verify AstrBot countdown and volume MCP integration`

## 10. P4b6 — 合同矩阵验收与收尾

**Purpose:** 逐项审计 P4-C01 至 P4-C15，以自动化结果和真实运行证据区分 PASS、PARTIAL、BLOCKED、DEFERRED；首版只要求倒计时/音量核心合同通过，P4-C14 仍属于 P5/P6。

**Tasks:**

- [ ] 对照 P4-C01 至 P4-C15 建立合同追踪表；首版适用项链接到具体测试、命令输出或现场验证；可选扩展未执行时标记 DEFERRED，不从“服务已注册”推断“设备动作已成功”。
- [ ] 验证 MCP 路由、Streamable HTTP、工具发现、普通用户认证与 Assist API 权限。
- [ ] 验证首版三个 Tool 的注册过滤、实体暴露边界、服务复用、参数合同、失败传播和 JSON ToolResult。
- [ ] 媒体文件相对路径、根目录包含关系、静态图片/GIF、GIF timing 和越界拒绝只在 P4b4 已执行时验收；否则标记 DEFERRED。
- [ ] P4b3 表情/文字/亮度可选子任务如未执行，标记 DEFERRED，不阻塞首版。
- [ ] 验证无参 StopCountdown 及 `72 03 00 00 00` wire 语义。若 P4b0 未能确认纯 payload builder 的合规复用方式，则把字节级检查标为 P6 adapter 待办；不得在 Tool 层另写协议编码器。
- [ ] 验证 AstrBot 4.29.4 断线恢复/重试，不引入自定义协议或额外重试框架。
- [ ] 运行 P3 全套 HA 测试，确认 Chat API、session、SSE、ChatLog、取消与 P4 完全隔离。
- [ ] 运行开发机完整测试与静态检查：`./scripts/test-ha.sh -q`、Ruff check、Ruff format check、Python compileall、`pip check`、`git diff --check`。
- [ ] 检查变更范围只涉及 Tivoo HA 集成、对应测试、必要依赖与 P4 文档；没有改动 P3 实现、AstrBot 插件、ESP32、TCP 7777/7778 或 NAS 部署文件。
- [ ] 创建 P4 验收报告，区分自动化 PASS、AstrBot 运行时 PASS、生产文件交接 BLOCKED、设备实测 DEFERRED。
- [ ] 仅在全部对应门通过后更新 README 的 P4 状态；未通过项保留明确状态和后续归属。

**Exit gate:**

- [ ] P4-C01–C09、P4-C11–C13 的首版适用项均有 PASS/PARTIAL/BLOCKED 结论及证据；P4-C10 媒体和 P4-C15 显示扩展如未实施，明确标记 DEFERRED；字节级报文若因许可证/代码复用条件未能在 P4 验证，必须记入 P6 adapter 待办而不标 PASS。
- [ ] 本地 HA 自动化和 P3 回归通过；静态检查与 diff 检查通过。
- [ ] AstrBot 实际 Persona 能发现并调用 StartCountdown、StopCountdown、SetVolume 三个首版必需 Tool；所有失败路径都没有伪成功。
- [ ] C14 实机动作不作为 P4 关闭前提；报告明确转交 P5/P6。
- [ ] 最终变更审查完成并本地提交；不 push、不 merge。

**Commit:** `test(p4): verify HA MCP Tivoo tool contracts`

## 11. 合同到批次追踪

| 合同 ID | 主要 Batch | 第一版验证重点 |
|---|---|---|
| P4-C01 MCP 路由 | P4b0、P4b5 | HA 原生 `/api/mcp/assist` 可达 |
| P4-C02 Streamable HTTP | P4b0、P4b5 | AstrBot 4.29.4 initialize 与 Bearer header |
| P4-C03 工具发现 | P4b2、P4b3、P4b5 | 三个首版必需 Tool 出现在指定 Persona；扩展工具按是否排期决定 |
| P4-C04 权限边界 | P4b0、P4b5 | 普通 HA 用户 Token 可用；错误 Token 拒绝；不使用管理 API |
| P4-C05 实体暴露 | P4b5、P4b6 | 原生工具只作用于暴露给 Assist 的实体；不以未实现实体替代必需 Tool |
| P4-C06 Tool 注册过滤 | P4b2、P4b3 | 仅 `api_id=assist` 返回 Tivoo Tools |
| P4-C07 服务复用 | P4b1–P4b3 | 三个必需 Tool 调用对应 `tivoo.*` Service；服务处理逻辑可由自动化共用 |
| P4-C08 失败传播 | P4b1–P4b6 | 参数错误、服务缺失、适配器不可用均不伪成功 |
| P4-C09 MVP 参数范围 | P4b1–P4b3、P4b6 | Stop 无参数；Start 严格 MM:SS；Volume 整数 0–100 且保留 0 |
| P4-C10 媒体边界 | P4b4、P4b6 | media_directory 相对路径、PNG/JPG/GIF、GIF timing、路径越界拒绝；未排期则 DEFERRED |
| P4-C11 P3 回归 | P4b2–P4b6 | P3 Chat/SSE/session/ChatLog 不变 |
| P4-C12 断线与重试 | P4b5、P4b6 | 使用 AstrBot 4.29.4 实际重连行为；记录非幂等动作返回丢失风险 |
| P4-C13 设备传输隔离 | P4b1–P4b6 | AstrBot 不连接 TCP 7777/7778、ESP32/SPP |
| P4-C14 Tivoo 实机动作 | P5/P6 | 不作为 P4 退出条件；交由设备通信和硬件验收 |
| P4-C15 显示扩展边界 | P4b3、P4b6 | 表情/文字/亮度仅在可选子任务排期后验收；首版不要求 |

## 12. 全局实施与测试规则

- 一个 Batch 一个执行任务、一个独立提交；执行提示必须引用本批次编号、本文和 P4 合同矩阵，并明确“仅做当前批次”。第一版只执行 P4b3 的 MVP 子集；可选扩展子任务应在单独明确排期后再执行。
- 每个新增服务/Tool 行为先写能观察公开行为的 RED 测试，再实现最小逻辑并 GREEN。测试通过服务与 HA Assist/MCP 接缝，不绑定内部类结构。
- 优先复用 HA Core 的 Config Entry、Service Registry、LLM Tools、Assist API、MCP Server 和现有 P3 测试脚手架。AstrBot MCP Client 复用 4.29.4 原生实现。
- HA 服务 Schema 与 LLM Tool 的 `probatio.Schema` 可能属于不同验证框架；共享一份参数合同，分别适配框架并通过合同测试检查字段、类型、默认值和范围，不强行共享不兼容的 Schema 对象。
- Tool 调用服务必须等待服务执行结果，以便传播 ServiceNotFound/ServiceValidationError/设备不可用错误；不把异步事件已排队当作设备动作完成。
- 测试适配器只用于开发机合同测试。生产默认适配器在 P6 传输接入前应清楚报告 unavailable；不可在生产中自动切换为“成功的内存适配器”。
- 文件测试只读取 HA 配置 media directory 内的测试文件；不通过任意 HTTP URL、共享外部绝对路径或原始二进制简化文件交接。
- 每批结束运行本批聚焦测试和必要回归；P4b2 之后至少运行 P3 现有测试。最终运行 `./scripts/test-ha.sh -q`、Ruff check/format、compileall、pip check 和 `git diff --check`。
- 不在 NAS 上运行耗时测试或负载测试。开发机 Ubuntu 测试通过后，只进行必要的远程 MCP 连通/配置验证；不扫描、清理或修改无关 NAS 文件、容器和会话。
- 每批结束记录：基线 SHA、实际修改文件、RED/GREEN 命令与结果、静态检查、人工验收状态、提交 SHA、剩余 BLOCKED/DEFERRED 项。不要因 MVP 通过而虚报可选扩展已完成，也不要因可选扩展未实施而阻塞 MVP。
- 遇到合同缺失、上游版本变化、许可证不明、HA 实际服务语义不同或 AstrBot 工具发现与预期不一致，先停止对应批次并更新合同/计划；不在实现中私自扩展协议。
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
