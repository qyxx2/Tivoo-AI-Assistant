# P4：Home Assistant MCP / Tivoo LLM Tools 合同矩阵

> 状态：P4 设计合同（待实现与集成验收）；本文只冻结已由现有规格、HA/AstrBot 源码或本机 Tivoo 协议实现证实的部分。凡现有代码没有定义的字段、资源引用格式和设备能力，明确标为待定，不以示例值冒充正式接口。
>
> 基线：Tivoo-AI-Assistant main 当前已实现 P3；Home Assistant Core 2026.11.0；AstrBot 4.29.4。P4 从 main 创建独立分支，本文不包含代码实现。

## 1. P4 目标与边界

P4 只负责建立 **AstrBot → Home Assistant 的 MCP 工具调用控制面**，并把项目需要的 Tivoo 操作注册为 HA LLM Tools，使其经 HA 原生 MCP Server 暴露给 AstrBot。

P4 不重新实现 MCP Server/Client，不改变 P3 的 Conversation Agent，不直接控制 ESP32、SPP 或音频通道。Tivoo 工具只调用 HA 的业务服务接口；后续阶段由 Tivoo 集成把服务请求接入已规划的设备通信层。

### 1.1 目标链路

```
AstrBot 4.29.4 内置 MCP Client
        │  Streamable HTTP / MCP JSON-RPC
        │  Authorization: Bearer <HA access token>
        ▼
Home Assistant Core 2026.11.0 原生 mcp_server
        │  /api/mcp/assist
        ▼
HA Device control API（Assist API，id=assist）
        ├── HA 原生实体工具（仅限暴露给 Assist 的实体）
        └── Tivoo LLM Tools（custom_components/tivoo/llm.py）
                    │
                    ▼
             HA 原生 tivoo.* 服务
                    │
                    ▼
          Tivoo 集成的业务/命令网关
                    │
                    ▼
       后续 P5/P6：P6 TCP 7777 → ESP32 → Classic SPP → Tivoo
```

AstrBot 不连接 ESP32，不拼接 Tivoo 二进制帧，也不访问 7777/7778。MCP 只传递工具名称、参数和 JSON 结果；图片帧、动画帧、PCM、TTS 音频均不走 MCP。

### 1.2 与已有阶段的边界

| 阶段 | 责任 | P4 的关系 |
|---|---|---|
| P3 | HA Conversation Agent 通过 AstrBot HTTP Chat API 发送文本，并把 SSE 文本增量写入 HA ChatLog | 保持不变；MCP 不是 STT/文本对话入口 |
| P4 | HA MCP Server 暴露设备/Tivoo 工具，AstrBot MCP Client 调用 | 本合同范围 |
| P5 | ESP32 最小固件与 Tivoo Classic SPP 控制 | P4 仅调用 HA 服务，不实现该传输 |
| P6 | HA↔ESP32 TCP 7777/7778 通信层与 HTTP 音频资源获取；7777 承载原始 Tivoo 控制桥，7778 承载设备状态/麦克风 PCM/TTS 通知 | P4 不实现、不使用 |
| P7/P8 | 麦克风唤醒/STT 与 TTS 音频输出 | 不属于 P4 |
| P9 | AstrBot 主动表达、表情/动画等主动交互 | 可复用 P4 工具，但不扩大 P4 范围 |
| P10 | Wi-Fi、I²S、SPP 并发及设备实测 | 后续硬件验收 |

## 2. 已由真实源码确认的协议与接口

### 2.1 Home Assistant MCP Server

本机 HA Core 2026.11.0 源码确认：

- 原生集成域名为 `mcp_server`，依赖 HA HTTP、Conversation 和 MCP Python SDK；无需另建 MCP Server 容器。
- Streamable HTTP 根路由为 `/api/mcp`；按 LLM API 指定的路由为 `/api/mcp/{api_id}`。
- 内置 Device control API 的 ID 是 `assist`，因此本项目使用的完整路径为 **`/api/mcp/assist`**。
- 该 API 由 HA 注册的 LLM API 提供工具，MCP 层的 `tools/list` 从 `llm_api.tools` 生成工具清单，`tools/call` 转交给 `llm_api.async_call_tool()`。
- HA MCP Server 当前 Streamable HTTP 实现是无状态请求/响应路径；无需在项目中另造 SSE 会话管理。
- HA API 专用路由对 `assist` 不要求管理员身份；其他 API ID 则要求管理员。默认的 `/api/mcp` 使用 MCP Server 集成选项选择 API 集合，并可能要求管理员。

主要源码：

- `.venv/lib/python3.14/site-packages/homeassistant/components/mcp_server/http.py`
- `.venv/lib/python3.14/site-packages/homeassistant/components/mcp_server/server.py`
- `.venv/lib/python3.14/site-packages/homeassistant/components/mcp_server/config_flow.py`
- `.venv/lib/python3.14/site-packages/homeassistant/components/llm/__init__.py`
- `.venv/lib/python3.14/site-packages/homeassistant/helpers/llm.py`

**P4 接口选择冻结：使用 `/api/mcp/assist`，不使用 `/api/mcp` 默认聚合入口，也不使用旧式 `/mcp_server/sse`。**

选择理由：

1. `assist` 是 HA 内置的 Device control API，面向设备控制，不是 HA 管理 API。
2. 原生 Device control 工具受 HA “暴露给语音助手”实体清单约束。
3. API 专用路由不要求管理员；可避免把 HA 管理权限授予 AstrBot。
4. Streamable HTTP 是 HA Core 2026.11.0 与 AstrBot 4.29.4 均有源码支持的共同传输。

注意：HA 当前的 API 专用路由会忽略 MCP Server 配置页中的 API 集合/read-only 选项，且该路由不是只读模式。因此不能把 MCP 配置页的 read-only 开关当成 `/api/mcp/assist` 的权限边界。实际限制依赖 HA 用户身份、Assist 实体暴露配置以及 Tivoo LLM Tools 自身的最小工具集。

### 2.2 HA LLM Tools 注册合同

HA 2026.11.0 已提供 LLM Tools 平台机制。每个集成可以通过自己的 `llm.py` 向 HA 的 LLM API 提供工具；HA 原生 MCP Server 会自动把这些工具发布成 MCP tools。

Tivoo 集成应新增：

```
homeassistant/custom_components/tivoo/
├── __init__.py
├── manifest.json
├── ...
└── llm.py
```

平台接口：

- `llm.py` 作为 HA LLM Tools 平台由 `LazyIntegrationPlatforms` 发现；平台实现同步 callback `async_get_tools(hass, llm_context, api_id) -> LLMTools | None`（不要把它写成异步协程）。
- 返回值使用 HA 的 `LLMTools(tools=[...], prompt=...)`。
- 工具类继承 `homeassistant.helpers.llm.Tool`。
- 工具参数使用 HA 当前 `Tool.parameters` 所要求的 `probatio.Schema`，不要自行实现 JSON Schema 序列化器。
- 工具调用签名是 `async_call(hass, tool_input, llm_context) -> ToolResult`。
- 成功结果使用 `ToolResult(data=<JSON object>)`；失败通过 HA 的异常/ToolResult error 语义传播，不要把失败伪装成成功字符串。
- 工具名称采用集成域名加双下划线前缀，即 `tivoo__...`。HA Core 2026.11.0 会对缺少此前缀的工具报告问题，并计划在 2027.3 将该约定作为破坏性要求；P4 现在就遵循此前缀。工具显式设置 `integration="tivoo"`，避免未标记来源的工具告警。

注册和过滤规则：

1. 仅当 `api_id == LLM_API_ASSIST`（字符串值 `assist`）时返回 Tivoo 工具。
2. 其他 API（尤其是 HA 管理 API）返回 `None`，不向其额外注册 Tivoo 操作。
3. 不自行注册第二个 MCP Server，不在 Tivoo 集成中再创建 MCP HTTP 路由；也无需把 `llm` 塞入普通实体平台 `PLATFORMS` 列表，HA 的 LLM 平台加载器按需发现 `llm.py`。
4. 工具通过 HA LLM Tools 平台发现；不在 `astrbot` Conversation Agent 的 `conversation.py` 中注册 MCP 工具。
5. 可在 `LLMTools.prompt` 提供简短的 Tivoo 操作说明，但提示文本不是权限控制，真正的输入约束必须落在工具参数 Schema 与 HA 服务 Schema。

工具调用执行边界：

- 每个 LLM Tool 只做参数校验、业务服务调用和结果适配。
- 通过 HA 的 `hass.services.async_call("tivoo", service, ...)` 调用同一套 Tivoo 服务，供 MCP、自动化、脚本和 UI 共用；不得在 LLM Tool 内复制命令 payload 构造或设备连接逻辑。
- 服务调用使用当前 `llm_context.context` 作为 HA Context，以保留调用来源与关联上下文；工具授权边界仍由 MCP 接口认证、Assist 实体暴露配置和服务自身的访问规则决定。不要把 P3 的 AstrBot username/session_id 当作 HA 权限身份。
- LLM Tool 和自动化服务必须复用同一个业务处理函数，不能维护两套参数含义或校验规则。
- 工具执行结果必须是 JSON 可序列化对象。返回“HA 服务已接受/执行”的事实即可；没有设备回执时不得返回“屏幕已显示”“动画已完成”等无法证实的结论。

### 2.3 AstrBot 4.29.4 MCP Client

已核对 GitHub tag `v4.29.4` 下的真实文件：

`astrbot/core/agent/mcp_client.py`

源码实际支持：

- 远程 URL 连接。
- `transport` 或 `type` 配置字段；本项目统一使用 `transport`。
- `transport: streamable_http`。
- 自定义 `headers`，可用于 HA Bearer Token。
- MCP `initialize`、`tools/list`、`tools/call`。
- 断开后的连接重建与有限工具调用重试。

AstrBot 配置以其 WebUI 的 MCP 页面为入口。P4 不开发 AstrBot MCP Client，也不写入连接密钥到仓库。

项目连接配置合同：

| 字段 | 值/约束 |
|---|---|
| Server name | 稳定且易识别，例如 `home-assistant-tivoo`（显示名称，不是协议字段） |
| transport | `streamable_http` |
| url | `http(s)://<HA LAN 地址>:8123/api/mcp/assist` |
| headers.Authorization | `Bearer <HA Long-Lived Access Token>` |
| 其他传输字段 | 首期不增加；采用 AstrBot MCP Client 默认配置 |

请求行为依据 AstrBot 4.29.4 源码：

- 连接测试通过 Streamable HTTP POST 发送 MCP initialize。
- 请求头包含 `Content-Type: application/json` 和 `Accept: application/json, text/event-stream`。
- 初始化后建立 MCP ClientSession，再执行 `list_tools()`。
- 工具调用使用 MCP ClientSession 的 `call_tool(name, arguments)`。
- 配置保存后应在 AstrBot 中确认服务器已连接、工具列表已发现，并把此服务器/工具授权给实际使用的 Agent Persona。

HA 认证使用归属当前单一 HA 用户的 Long-Lived Access Token，放入 AstrBot MCP 配置的 Authorization header。Token 只保存在 AstrBot/NAS 的配置与凭据存储中，不提交到 Git、不写入项目文档、不进入日志。首期使用局域网 HA 地址，不要求把 HA MCP 端口暴露到公网。

AstrBot 4.29.4 的 MCP Client 对连接关闭错误有自动重连和一次重试路径。对于不具备幂等性的动画/定时器命令，网络在服务端执行完成但返回丢失时存在重复执行风险。P4 需通过断线注入测试记录实际行为；不在本阶段再叠加一套通用重试框架或自造 MCP 请求协议。

## 3. 工具分类与暴露策略

### 3.1 两类工具来源

| 来源 | 工具内容 | 访问约束 |
|---|---|---|
| HA Device control 原生工具 | 对 HA 实体的查询与控制 | 只允许控制已暴露给 Assist 的实体；不另写一套通用 HA 服务调用工具 |
| Tivoo 自定义 LLM Tools | 无法通过标准实体操作表达的 Tivoo 业务动作 | 通过 `tivoo/llm.py` 注册，只调用 `tivoo.*` 服务 |

不增加“任意 HA 服务调用”工具，不允许模型自行拼装任意 domain/service/service_data。HA 原生 MCP Device control API 不是通用管理员服务终端。

### 3.2 实体与自定义工具去重

项目已有实体规划包括：

- `number.tivoo_brightness`
- `select.tivoo_display_mode`
- `switch.tivoo_screen`
- `media_player.tivoo`
- `assist_satellite.tivoo`
- 麦克风/SPP 等只读诊断实体

这些实体在实际实现后，按需要显式暴露给 Assist。可以通过 HA 原生 Device control 工具完成的能力，不再创建同义的 Tivoo LLM Tool。

具体决策：

- 亮度：保留 `tivoo.set_brightness` 作为 HA 服务，供自动化/脚本调用；AI 默认通过已暴露的 `number.tivoo_brightness` 控制，不再额外暴露同义 `tivoo__SetBrightness`。
- 显示模式/屏幕开关：优先使用 `select.tivoo_display_mode`、`switch.tivoo_screen` 的原生实体能力，不另建重复工具。
- 表情预设、播放动画、显示文字、显示图片、倒计时：属于业务操作，不适合简单实体状态控制，使用 Tivoo 自定义服务/LLM Tools。
- 诊断状态：优先通过实体状态让 HA/Assist 读取；只有当原生实体上下文不能满足明确用例时才增加只读工具。

注意：实体“已暴露给 Assist”与工具“已注册”是两个不同条件。未暴露的实体不能假定会出现在原生工具列表里；尚未实现的实体也不能作为 P4 已有能力宣传。

## 4. Tivoo 自定义工具矩阵

下表中的服务名称来自项目 README 的既有规划；底层方法名/参数来自本机 Tivoo Python 代码，并补充核对了 `solar2ain/tivoo-control`、`d03n3rfr1tz3/esp32-divoom` 和其 HA 集成 `d03n3rfr1tz3/hass-divoom` 的实际实现。媒体文件引用与倒计时停止语义已有上游依据，不再列为未知接口。

| 业务能力 | HA 服务/候选 MCP Tool | 现有实现依据 | 参数合同与边界 | P4 暴露决策 |
|---|---|---|---|---|
| 表情预设 | 服务 `tivoo.set_expression`；工具名建议 `tivoo__SetExpression` | `TivooDisplay.preset(name)`；`tivoo.py` 的 `_load_all_presets()`、`presets/` 工厂函数 | 唯一输入沿用现有预设名称 `name`；必须按现有注册表过滤隐藏项/未知项，不由模型自由生成图片字节。枚举值由运行时实际 preset registry 产生，不在本合同抄写一份会过期的列表 | 作为 P4 首批自定义工具 |
| 动画播放 | 服务 `tivoo.play_animation`；工具名建议 `tivoo__PlayAnimation` | `solar2ain/tivoo-control` 的 `anim(path)` 支持 GIF；HA 上游 `hass-divoom` 的 `image(file, time)` 通过 `Image.open()` 读取 GIF 多帧，再按 0x49 分块发送 | `file: string`，相对于集成配置的 `media_directory`；首期只接受 GIF 文件作为动画资源，可选 `time` 覆盖每帧毫秒数。MCP 不承载原始帧数组；目录动画和 JSON stage 文件不是 HA `image` 服务已支持的资源类型 | 作为 P4 自定义工具；复用 `hass-divoom` 文件引用与 GIF 解码模式，不创建 asset ID/URI |
| 文字显示 | 服务 `tivoo.show_text`；工具名建议 `tivoo__ShowText` | `TivooDisplay.text(value, color, background, speed, step, font_size, font, font_file)`；`tivoo.py` 的 `_gen_text_frames()` | 文本主参数沿用现有方法的 `value`；可选样式只能映射到现有方法支持的 color/background/speed/step/font_size/font。不得把本机文件路径 `font_file` 暴露给 LLM。step 与 font_size 的已知 CLI 范围分别是 1–8、8–16；服务层最终 Schema 应与实际渲染函数校验一致 | 作为 P4 首批自定义工具；不暴露文件路径 |
| 图片显示 | 服务 `tivoo.show_image`；工具名建议 `tivoo__ShowImage` | `TivooDisplay.image(path, timecode, resample)`；HA 上游 `hass-divoom` 的 `divoom.image(file, time)` 同时支持静态图片和 GIF；`process_image()` 处理 PNG/JPG/GIF 帧并复用原有帧编码 | `file: string`，相对于配置的 `media_directory`；支持 Pillow 可读取的静态图片文件，GIF 也会被识别为多帧。可选 `time: integer`（0–65535 ms）覆盖 GIF 帧间隔；未提供则沿用 GIF 自带帧时长。禁止传 NAS 任意绝对路径、URL、原始图片字节或调色板数据 | 作为 P4 首批自定义工具；与动画工具共用同一文件引用根目录和图像编码通路 |
| 亮度 | HA 服务 `tivoo.set_brightness`；默认不创建重复 MCP Tool | `TivooDisplay.brightness(value)`；payload 0x74，范围 0–100；HA 实体规划 `number.tivoo_brightness` | MCP 控制优先走 number 实体的原生控制工具；服务和 number 实体必须使用相同 0–100 语义 | 服务保留；通过原生实体暴露 AI 控制 |
| 倒计时启动 | 服务 `tivoo.start_countdown`；工具名建议 `tivoo__StartCountdown` | `TivooDisplay.countdown(minutes, seconds, start=True)`；`commands.countdown_payload()`；上游 `show_countdown(value=True, countdown="MM:SS")`；payload 0x72 0x03 | `countdown: string`，格式 `MM:SS`；分钟 00–99、秒 00–59。上游 HA 集成也接受 `HH:MM:SS`，但会忽略小时，只取末尾 `MM:SS`；本项目首期统一使用 `MM:SS` | 可注册；将硬件能力状态标为待 P5/P6 实测 |
| 倒计时停止 | 服务 `tivoo.stop_countdown`；工具名建议 `tivoo__StopCountdown` | 上游 `show_countdown(value=False, countdown=None)`；ESP32 `Divoom::show_countdown()` 在 countdown 缺省时发送 `0x72 0x03 0x00 0x00 0x00` | **无必需参数**。停止时不需要重传启动时长、不需要 HA 保存当前倒计时；缺省时长按上游实现编码为 `00:00`。本机 `commands.countdown_payload()` 的 minutes 参数是必填的内部函数参数，适配时传 `minutes=0, seconds=0, start=False` 即可，不应暴露给 LLM | 可注册为无参数停止工具；实机支持仍需 P5/P6 验收 |
| 内置 Timer | 不在当前 README 的 P4 工具列表中 | `TivooDisplay.timer(start=True)`；payload 0x72 0x00 | 与 MM:SS 倒计时 0x72 0x03 是两个不同命令。不能把 stop_countdown 偷换成 timer(False) | 不自动加入 P4；另有明确需求再纳入 |
| 其他 Divoom 命令 | 不作为 P4 默认工具 | `commands.py` 还有 volume/playstate/date/weather/alarm/memorial/radio/sleep/effects/visualization/design/game 等构建器 | 上游通用 Divoom 实现及离线 payload 测试，不等于当前 Tivoo 固件已支持；项目目标也未要求全部暴露 | 不加入首期 Tool list；逐项实测和需求确认后再评估 |

### 4.1 首期可冻结的输入字段

服务字段以已核对的 HA 上游 Divoom 服务合同为主，本机 Python API 作为 payload 构建层；MCP Tool Schema 与 HA 服务 Schema 必须保持一致，不得在 Tool 层再次改名。媒体路径使用集成配置的 `media_directory` 相对路径，不是 asset ID/URL。

| 服务 | 必需字段 | 可选字段 | 类型/约束来源 |
|---|---|---|---|
| `tivoo.set_expression` | `name: string` | 无 | `TivooDisplay.preset(name)`；有效值由运行时 preset registry 决定，隐藏项/未知项拒绝 |
| `tivoo.show_text` | `value: string` | `color: string`、`background: string`、`speed: integer`、`step: integer`、`font_size: integer`、`font: string` | 对齐 `TivooDisplay.text()`；`step` 沿用 CLI 1–8，`font_size` 沿用 CLI 8–16，`font` 必须来自 `FONT_NAMES`；不暴露 `font_file` |
| `tivoo.start_countdown` | `countdown: string`（`MM:SS`） | 无 | 对齐上游 `countdown` 字符串语义；分钟 00–99、秒 00–59 |
| `tivoo.stop_countdown` | 无 | 无 | 对齐上游 `value=false` 且 `countdown` 缺省时发送 `00:00`；无需保留上次时长 |
| `tivoo.set_brightness`（服务，不单独注册 Tool） | `value: integer` | 无 | 对齐 `TivooDisplay.brightness()` 与 `number.tivoo_brightness`：0–100 |
| `tivoo.show_image` | `file: string` | `time: integer`（0–65535 ms） | `file` 相对于配置的 `media_directory`；静态 PNG/JPG 或 GIF；GIF 默认使用文件内帧时长 |
| `tivoo.play_animation` | `file: string` | `time: integer`（0–65535 ms） | `file` 相对于同一 `media_directory`；首期限定 GIF，`time` 可覆盖 GIF 帧间隔；目录动画/JSON stage 暂不暴露 |

`show_text` 的 `font_file` 是服务端本地文件路径参数，不属于 LLM 可输入面；字体只允许通过已安装的字体名称选择。

### 4.2 媒体文件引用合同

复用 HA 上游 `d03n3rfr1tz3/hass-divoom` 已有的文件引用方式，不再引入 asset ID、URI 或 HTTP URL：

- Tivoo 集成配置使用 `media_directory`，按上游实现通过 `hass.config.path()` 相对 HA 配置目录解析；首期默认值沿用上游常量 `pixelart`。
- 工具的 `file` 是相对于该目录的文件路径，例如 `generated/hello.gif`，不是 NAS 绝对路径。
- 解析后必须确认规范化路径仍位于 `media_directory` 内；上游 `_resolve_path()` 使用 `realpath()` 和 `commonpath()` 拒绝越界文件。
- 静态图片沿用现有 Pillow `Image.open()` → `process_image()` → `send_frames()` 编码通路。GIF 的所有帧会自动读取；未传 `time` 时沿用 GIF 自带的 frame duration，传入时覆盖每帧时间。
- `solar2ain/tivoo-control` 的 `anim(path)` 还支持帧目录；其 `prepare` / `send` 使用本地 JSON stage 文件，结构是 `frames` 与 `delays`。这些是 CLI 本地文件工作流，不是 HA 上游 `image` 服务支持的格式。P4 首期只暴露静态图片文件和 GIF，不暴露目录、JSON stage、原始帧数组或任意 URL。

`show_image` 与 `play_animation` 是项目对模型暴露的语义化工具；底层共享同一文件根目录、GIF 解码和 Tivoo 帧发送通路，不应再实现两套媒体协议。若后续不需要区分静态/动画两个工具，也可只保留上游风格的统一 `show_image(file, time)` 动作，但不影响本合同的 `file` 语义。

### 4.3 工具命名建议

P4 新增的项目自有 Tool 使用 HA 域名前缀：

| Tool name | 对应服务 |
|---|---|
| `tivoo__SetExpression` | `tivoo.set_expression` |
| `tivoo__ShowText` | `tivoo.show_text` |
| `tivoo__StartCountdown` | `tivoo.start_countdown` |
| `tivoo__StopCountdown` | `tivoo.stop_countdown` |
| `tivoo__ShowImage` | `tivoo.show_image` |
| `tivoo__PlayAnimation` | `tivoo.play_animation` |

`ShowImage` 与 `PlayAnimation` 使用上节已经冻结的 `file` / `time` 输入，不另建资源 ID 或帧数组参数。若实现者需要调整工具显示名，应保持稳定、唯一、以 `tivoo__` 开头，并同步更新测试矩阵。

不为 `number.tivoo_brightness` 再注册同义 Tool。不要用原始协议命令号作为 LLM 工具名或参数。

### 4.4 ToolAnnotations

HA 的 ToolAnnotations 默认值偏保守（默认不是只读、destructive、非幂等、open-world）。每个 Tivoo Tool 应显式声明，不依赖默认值：

- 写操作：`read_only=False`。
- 本地 Tivoo 显示控制不访问开放网络：`open_world=False`。
- 是否 `idempotent` 必须按操作语义设置；设置亮度/显示固定预设与播放一次动画不能一概而论。
- `destructive` 按服务是否会覆盖重要设备状态评定。不能仅为了让 Agent 更容易调用而把写操作标成 read-only。

Annotations 是模型提示元数据，不是授权机制；真正的访问限制仍由 HA 用户权限、Assist 实体暴露、服务参数校验与工具清单控制。

## 5. Tivoo 服务与既有设备协议的复用边界

### 5.1 服务层不能直接复制协议实现

P4 的 LLM Tool 只转发到 HA 服务，不负责：

- 生成 Tivoo 外层二进制帧、长度或 checksum。
- 编码 16×16 palette/RGB 图像。
- 拆分动画块。
- 打开 TCP socket、连接 ESP32 或处理 SPP。
- 连接 BluetoothBridge 或直接连接 Tivoo Classic Bluetooth。

业务服务将来由 HA Tivoo 集成实现；命令和媒体处理复用既有来源。

### 5.2 本机 Tivoo Python 实现可复用内容

已检查本机目录：

`/home/Gold/WorkSpace/BluetoothBridgeTest/tivoo/`

关键文件与能力：

| 文件 | 已有能力 | 复用要求 |
|---|---|---|
| `commands.py` | 亮度以外的音量、播放状态、日期、天气、倒计时、timer、alarm、memorial 等 payload builder 和输入校验 | 优先复用已有 builder；不重新手写 payload |
| `tivoo.py` | `_build_packet()`、图片缩放/调色板编码、`build_image_frame()`、文字帧生成、动画块构建、预设加载 | 复用协议/渲染函数；避免复制实现并分叉 |
| `client.py` | `TivooDisplay` 高层方法：brightness/image/animation/text/preset/countdown 等 | 复用高层方法签名作为业务映射依据；其 Transport 不直接用于 NAS 端 |
| `test_commands.py` | 既有 payload 与外层帧的离线单元测试 | 后续移植/打包时保留为 golden/regression 验证依据 |
| `protocol-reference.md` | 命令表、帧结构、兼容性说明 | 供实现者查阅；如与可执行代码冲突，以代码和测试为准并修订说明 |

重要区别：当前 `TivooDisplay` 通过 Android Bluetooth Bridge 直接打开 Classic SPP；这不是本项目最终 NAS → ESP32 → Tivoo 的传输。应复用其协议 payload、图像/文字渲染及编码逻辑，不把该 BluetoothBridge 连接实现照搬进 HA 容器。

这些源文件目前在 Tivoo-AI-Assistant 仓库之外，不能在部署时依赖开发机绝对路径。实现阶段需要把真正需要的纯 Python 协议/渲染模块整理为项目内可部署包，或以带来源和许可证声明的受控 vendoring 方式纳入；不得从 NAS 运行时 import `/home/Gold/WorkSpace/BluetoothBridgeTest`。

### 5.3 ESP32 侧既有实现复用

已检查本机参考代码：

`/home/Gold/WorkSpace/BluetoothBridgeTest/esp32-divoom/components/divoom/`

- `input_tcp.cpp`：TCP 原始桥接协议，0x69 建立连接、0x96 断开、原始 Tivoo 帧转发。
- `util.cpp`：`getFrameSize()`、`isFramePending()`、`appendFrames()` 处理 TCP 拆包/粘包与完整帧边界。
- `bluetooth_spp.cpp`：Classic Bluetooth SPP、SDP 通道发现、发送队列与拥塞处理。
- `output_bluetooth.cpp`：将已有 Tivoo 原始帧转发到 SPP，并把返回数据交回输入通道。

该参考实现使用其自身的 Arduino/平台抽象；项目后续 ESP-IDF 固件需要按规格适配，而不是把它当成已可直接编译的 ESP-IDF 模块。P4 不复制或修改这套固件源码。

### 5.4 P5/P6 通道引用

与后续 ESP32–HA 规格保持一致：

| 通道 | 既有合同 | P4 是否直接使用 |
|---|---|---|
| TCP 7777 | HA 主动连接 ESP32 TCP Server；raw Tivoo bridge control/connect/disconnect/data；完整 Tivoo 帧保持原始字节格式 | 否。由后续 Tivoo 服务/网关使用 |
| TCP 7778 | 16-byte TVIO header、version/message type/sequence；设备状态、麦克风 PCM、TTS 控制/状态 | 否 |
| HTTP | ESP32 按 HA 下发 URL GET TTS 音频资源 | 否 |
| Classic SPP | ESP32 将完整 Tivoo raw frame 转发到 Tivoo-audio RFCOMM | 否，由 ESP32 负责 |

禁止新增 MQTT/HTTP JSON/自定义 WebSocket 作为 P4 的 Tivoo 命令通道；也禁止把 7778 的音频事件协议复用为屏幕命令协议。

## 6. 错误、返回与幂等语义

### 6.1 MCP Tool 结果

- 工具参数 Schema 校验失败时，调用必须失败，不能默默纠正成另一条命令。
- HA 服务不可用、Tivoo 尚未连接、业务校验失败等情况应返回 MCP tool error/HA 错误，不要返回“成功”文本。
- ToolResult 的 data 必须是 JSON object。
- 若底层服务没有设备确认回执，成功结果只能描述 HA 服务层实际完成的动作（例如服务请求已接收/入队）；不得将 TCP 写入成功、SPP 发送成功等同于屏幕确认显示。
- P4 不新造设备 ack 消息。设备状态及命令发送/确认的区分沿用 ESP32–HA 通信规格。

### 6.2 重试边界

AstrBot 4.29.4 内置 MCP Client 在特定连接资源关闭异常时会重连并再次调用工具。对幂等和非幂等操作要分开看待：

- 亮度、固定显示模式、屏幕开关等状态设置优先通过 HA 实体状态工具操作。
- 表情/动画/倒计时等动作可能产生重复可见效果或重复计时；P4 测试需要覆盖返回丢失、连接重建条件下的实际行为。
- P4 不额外建立通用任务队列、请求去重数据库或自定义幂等协议。若真实测试发现重复执行对实际使用造成明显影响，再以该阶段的测试结果决定是否增加最小必要机制。
- 不在 HA 或 AstrBot 两侧叠加多层盲目重试。

## 7. P4 批次边界

本节给出 P4 批次索引。每批的具体文件范围、任务顺序、测试、退出门和提交约定，以 [P4 Batch Execution Plan](../plans/2026-11-09-p4-ha-mcp-tool-batch-execution-plan.md) 为准；总体架构与批次目标见 [P4 Implementation Plan](../plans/2026-11-09-p4-ha-mcp-tool-implementation-plan.md)。

| 批次 | 内容 | 完成条件 | 明确不做 |
|---|---|---|---|
| P4b0 | 版本、源码、测试环境和协议复用前置核对 | HA/AstrBot 接口、测试入口及 SDK 复用条件有当前证据；差异和阻塞项已记录 | 不实现工具代码、不猜接口 |
| P4b1 | Tivoo HA 集成骨架、语义命令接缝和 StopCountdown 服务切片 | 集成可加载；无参数服务能通过测试适配器产生语义命令，生产适配器缺失时明确失败 | 不写 LLM Tool、不连接 TCP/ESP32/SPP |
| P4b2 | HA LLM Tools 注册和 StopCountdown Tool | 仅 Assist API 发现工具；Tool 复用 HA 服务，参数/错误/结果符合合同 | 不自建 MCP Server/Client，不提供任意服务调用 |
| P4b3 | 表情、文字、倒计时 Tools 与亮度服务 | SetExpression、ShowText、StartCountdown、StopCountdown 的映射与校验通过；亮度不重复注册 Tool | 不实现 Tivoo 实体或硬件传输 |
| P4b4 | 图片/GIF 文件服务与媒体 Tools | 相对 media_directory 的文件合同、格式、时长和路径边界测试通过 | 不新增 asset ID/URI、帧目录、JSON stage 或 MCP 二进制载荷 |
| P4b5 | AstrBot MCP 配置、Persona 授权和运行时验证 | AstrBot 4.29.4 连接 HA Assist MCP，目标 Persona 可发现工具；鉴权/错误/重试行为有证据 | 不写自定义 MCP Client、不将 Token 写入仓库 |
| P4b6 | P4-C01–C13 合同验收、P3 回归和收尾 | 每项有 PASS/PARTIAL/BLOCKED 结论及证据；C14 转交 P5/P6 | 不把测试适配器结果当作 Tivoo 实机验收 |

依赖顺序：

```text
P4b0 → P4b1 → P4b2 ─┬→ P4b3 ─┐
                    └→ P4b4 ─┴→ P4b5 → P4b6
```

P4b3 与 P4b4 可在 P4b2 后分别执行；AstrBot 运行时验收必须等待两个批次完成。P4b0 是前置审查批，不要求为了形式创建空提交。StopCountdown 的无参服务合同在 P4 验收；字节级 `72 03 00 00 00` 只在纯 payload builder 的合法复用条件确认后纳入 P4 测试，否则明确作为 P6 adapter 验收项，不得由 P4 Tool 层重写协议编码。

## 8. P4 验收矩阵

| ID | 验收项 | 通过标准 | 阶段 |
|---|---|---|---|
| P4-C01 | HA MCP Server 路由 | HA Core 2026.11.0 原生集成启用后，`/api/mcp/assist` 可达 | P4 |
| P4-C02 | Streamable HTTP 初始化 | AstrBot 4.29.4 使用 `transport=streamable_http` 与 Bearer header 完成 initialize | P4 |
| P4-C03 | MCP 工具发现 | AstrBot 的工具列表包含预期 HA Assist 工具和已启用的 Tivoo LLM Tools；不出现未注册/重复工具 | P4 |
| P4-C04 | 权限边界 | 正常 HA 用户的有效 token 可使用 Assist API；无效 token 拒绝；不需要 HA 管理员权限 | P4 |
| P4-C05 | 实体暴露范围 | 原生设备工具仅操作显式暴露给 Assist 的实体；未暴露实体不应成为可调用对象 | P4 |
| P4-C06 | 工具注册过滤 | Tivoo `llm.py` 只向 `assist` API 提供项目工具；不注册进 HA 管理 API | P4 |
| P4-C07 | 服务复用 | Tool 调用对应的 `tivoo.*` HA 服务，参数校验和业务逻辑与自动化/脚本共用 | P4 |
| P4-C08 | 失败传播 | 不合法参数、服务不存在、设备不可用等情况不会返回伪成功；MCP 返回 error | P4 |
| P4-C09 | 参数范围 | 亮度 0–100、倒计时 `MM:SS`（分钟 00–99/秒 00–59）；停止工具无必需参数并编码为 `72 03 00 00 00` | P4 |
| P4-C10 | 媒体参数边界 | `file` 相对于 `media_directory`；静态图片/GIF 可读，路径越界被拒绝；不接受任意绝对路径、URL、原始图片字节或帧数组 | P4 |
| P4-C11 | P3 回归 | P3 HTTP Chat、session_id、SSE → ChatLog 行为不因 MCP 改动发生变化；MCP 不作为文本 STT 入口 | P4 |
| P4-C12 | 断线与重试 | 按 AstrBot 4.29.4 MCP Client 实际行为验证重连；记录非幂等动作在响应丢失时是否重复 | P4 |
| P4-C13 | 设备传输隔离 | AstrBot 没有 TCP 7777/7778、SPP、ESP32 连接；所有操作经过 HA 服务层 | P4 |
| P4-C14 | Tivoo 实机动作 | 亮度、图像、动画、倒计时等在实际 Tivoo 上产生预期结果，且状态反馈准确 | P5/P6；不作为 P4 单独完成依据 |

## 9. 未冻结项与实现前必须解决的问题

这些问题是当前代码/规格尚未给出答案的真实缺口，不得在实现时猜测：

1. **动画资源类型边界**：`solar2ain/tivoo-control` 的 `anim(path)` 支持 GIF 或帧目录，`prepare` / `send` 支持本地 JSON stage（`frames` / `delays`）；HA 上游 `hass-divoom` 的 `image(file,time)` 通过 Pillow `Image.open()` 读取文件，已有静态图/GIF 能力，但没有帧目录或 JSON stage 输入。P4 首期按 HA 可复用接口只接受静态图片/GIF；目录和 stage JSON 暂不支持，不为此新增自定义资源格式。
2. **AstrBot 生成文件落盘位置**：上游服务的 `file` 必须位于 HA 配置的 `media_directory` 之下。AstrBot 生成图片/动画后如何将文件安全放入该目录，属于部署/集成文件交接问题，不是 MCP 媒体 URI 协议；P4 实现时必须验证这条文件交接链，不应因此放开任意绝对路径或公网 URL。
3. **Tivoo 固件功能兼容性**：payload builder 和离线测试只证明字节构建，不证明当前 Tivoo 固件支持所有 Divoom 扩展命令。倒计时停止报文有上游实现，但当前 Tivoo 固件是否实际响应仍需实机验收；weather、alarm 等也需逐项验证。P4 工具清单只放有明确需求且测试通过的能力。
4. **协议代码可部署形式与许可证**：本机 Tivoo SDK 位于另一个工作区；需要检查其上游许可证、确认允许的复用方式，并保留版权声明。esp32-divoom、hass-divoom 与 Tivoo Python 源码的许可证分别核实，不可把一个仓库的许可证推定到另一个仓库。
5. **MCP 其他集成工具的集合影响**：`/api/mcp/assist` 使用 HA Assist API 汇总的 LLM Tools。后续若 HA 安装更多第三方 LLM Tool 平台，它们也可能进入同一 Assist API 工具集合；P4 应在实际环境中检查最终清单，不应假定它只包含 Tivoo 工具。
6. **主动播报/会话启动**：README 中 `assist_satellite.announce` 与 `assist_satellite.start_conversation` 是主动交互链路需要的 HA 操作；当前 HA Assist API 的原生工具并不等于任意 HA Service 调用器。若后续需要让 AstrBot 通过 MCP 执行这两个动作，必须为明确的业务操作注册受限 Tool，并依据 HA Core 对应服务 Schema，不允许增加通用 service-call Tool。本项归属主动交互接入阶段，P4 不擅自扩大范围。

## 10. 参考实现与文档

### 项目内规格与实现

- `README.md`：P4 阶段目标、Tivoo HA 集成职责、服务/实体规划、P1–P10 阶段关系。
- `docs/superpowers/specs/2026-11-09-p3-astrbot-conversation-contract-matrix.md`：P3 已冻结合同，以及 P3/P4 反向工具链边界。
- `docs/superpowers/specs/2026-11-09-esp32-ha-bidirectional-communication-design.md`：TCP 7777/7778、HTTP 音频资源、HA 与 ESP32 职责边界、Tivoo 协议复用清单。
- `/home/Gold/WorkSpace/BluetoothBridgeTest/tivoo/client.py`
- `/home/Gold/WorkSpace/BluetoothBridgeTest/tivoo/commands.py`
- `/home/Gold/WorkSpace/BluetoothBridgeTest/tivoo/tivoo.py`
- `/home/Gold/WorkSpace/BluetoothBridgeTest/tivoo/test_commands.py`
- `/home/Gold/WorkSpace/BluetoothBridgeTest/tivoo/protocol-reference.md`
- `/home/Gold/WorkSpace/BluetoothBridgeTest/esp32-divoom/components/divoom/input_tcp.cpp`
- `/home/Gold/WorkSpace/BluetoothBridgeTest/esp32-divoom/components/divoom/util.cpp`
- `/home/Gold/WorkSpace/BluetoothBridgeTest/esp32-divoom/components/divoom/bluetooth_spp.cpp`
- `/home/Gold/WorkSpace/BluetoothBridgeTest/esp32-divoom/components/divoom/output_bluetooth.cpp`

### 已核对的上游资源与命令合同

- [solar2ain/tivoo-control README](https://github.com/solar2ain/tivoo-control/blob/main/README.md)：`image <path>`、`anim <path>`（GIF/帧目录）、`prepare` / `send` stage 工作流。
- [solar2ain/tivoo-control `tivoo_macos.py`](https://github.com/solar2ain/tivoo-control/blob/main/tivoo_macos.py)：`anim(path)` 的 GIF/目录读取，以及 stage JSON 的 `frames` / `delays` 结构。
- [d03n3rfr1tz3/esp32-divoom README](https://github.com/d03n3rfr1tz3/esp32-divoom/blob/main/README.md)：`MODE countdown [value] [countdown]`，value=0 停止、value=1 启动，时间为 `mm:ss`。
- [esp32-divoom `components/divoom/divoom.cpp`](https://github.com/d03n3rfr1tz3/esp32-divoom/blob/main/components/divoom/divoom.cpp)：缺省 countdown 字符串时将时间字节置为 0、0；停止不要求上次时长。
- [d03n3rfr1tz3/hass-divoom README](https://github.com/d03n3rfr1tz3/hass-divoom/blob/main/README.md)：`divoom.image` 的 `file` 相对 `media_directory`、静态/动画文件与可选帧间隔；`divoom.countdown` 的 value 必填、countdown 可选。
- [hass-divoom `custom_components/divoom/services.py`](https://github.com/d03n3rfr1tz3/hass-divoom/blob/main/custom_components/divoom/services.py)、[`notify.py`](https://github.com/d03n3rfr1tz3/hass-divoom/blob/main/custom_components/divoom/notify.py)、[`devices/divoom.py`](https://github.com/d03n3rfr1tz3/hass-divoom/blob/main/custom_components/divoom/devices/divoom.py)：媒体根目录校验、GIF 多帧解码及倒计时缺省字段的实际实现。

### 上游与官方源码

- Home Assistant Core 2026.11.0 MCP Server：`homeassistant/components/mcp_server/http.py`、`server.py`、`config_flow.py`。
- Home Assistant Core 2026.11.0 LLM Tools：`homeassistant/components/llm/__init__.py`、`llm.py`、`homeassistant/helpers/llm.py`。
- AstrBot v4.29.4 MCP Client：[astrbot/core/agent/mcp_client.py](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/core/agent/mcp_client.py)。
- [Home Assistant MCP Server 官方说明](https://www.home-assistant.io/integrations/mcp_server/)。
- [Home Assistant LLM API 开发说明](https://contributors.home-assistant.io/core/internals/llm-api/)（以当前 HA Core 2026.11.0 实际源码接口为准）。
- [d03n3rfr1tz3/esp32-divoom](https://github.com/d03n3rfr1tz3/esp32-divoom)。
- [solar2ain/tivoo-control](https://github.com/solar2ain/tivoo-control)（本机 Tivoo Python 端的上游项目；复用前单独核实许可证及本机分支变更）。

---

**本合同矩阵创建范围（2026-11-09）：** 创建合同矩阵时不新增代码、不修改 P3 文档或 README、不连接 NAS 做设备测试、不部署 MCP 服务、不填写或提交任何 HA/AstrBot Token。P4 批次执行计划随后单独建立，见本节链接。
