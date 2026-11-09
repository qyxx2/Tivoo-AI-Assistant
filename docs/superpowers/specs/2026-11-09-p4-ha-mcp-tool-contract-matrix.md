# P4：Home Assistant MCP / Tivoo LLM Tools 合同矩阵

> 状态：P4 设计合同（待实现与集成验收）；本文只冻结已由现有规格、HA/AstrBot 源码或本机 Tivoo 协议实现证实的部分。凡现有代码没有定义的字段、资源引用格式和设备能力，明确标为待定，不以示例值冒充正式接口。
>
> 基线：Tivoo-AI-Assistant main 当前已实现 P3；Home Assistant Core 2026.11.0；AstrBot 4.29.4。P4 从 main 创建独立分支，本文不包含代码实现。

## 1. P4 目标与边界

P4 只负责建立 **AstrBot → Home Assistant 的 MCP 工具调用控制面**，并把项目需要的 Tivoo 操作注册为 HA LLM Tools，使其经 HA 原生 MCP Server 暴露给 AstrBot。

**第一版 MVP 必须完成以下明确列出的功能：表情预设、文字显示、屏幕亮度服务、图片显示、GIF 动画、倒计时启动、倒计时停止和扬声器音量调整。** 它们全部属于 P4b0–P4b6 的首版实现和验收范围，不是可选扩展。未在这份明确清单中列出的其他 Tivoo 服务，继续保留在完整能力矩阵中作为可选扩展，不要求首版实现。MVP 需打通 AstrBot → HA MCP → Tivoo LLM Tool → HA Service → 语义命令适配器链路；亮度按原计划提供 HA Service，不额外创建重复的自定义 MCP Tool。

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

第一版需要注册七项 Tivoo 自定义 Tool：`SetExpression`、`ShowText`、`StartCountdown`、`StopCountdown`、`SetVolume`、`ShowImage`、`PlayAnimation`。这些业务目前没有可直接替代的原生 HA 实体工具。

- `tivoo.set_brightness` 是第一版必须实现的 HA Service；按原计划暂不注册同义 `SetBrightness` MCP Tool。
- 表情、文字、图片/GIF、倒计时及音量的工具都必须向对应 HA Service 委派，不在 Tool 内实现设备或媒体逻辑。
- 屏幕开关、播放控制、时钟、天气、灯效、歌词、比分板、计时器、噪声计、闹钟、纪念提醒、音源切换、睡眠模式、设计等未明确列入 MVP 的能力，继续作为候选扩展；以后如已有原生 number/switch/media_player 实体并显式暴露给 Assist，应优先复用原生实体工具，避免重复注册项目 Tool。

注意：实体“已暴露给 Assist”与工具“已注册”是两个不同条件。必须同时确认实体已实现、功能状态语义可靠且已暴露，才能用原生实体工具替代项目自定义 Tool。

## 4. Tivoo 自定义工具矩阵

本节是 **经 Tivoo 型号专用上游核实的完整能力覆盖清单**。其中表情预设、文字滚动、图片显示、GIF 动画、屏幕亮度、扬声器音量、倒计时启动和停止属于第一版 MVP；其他行按“可选扩展”或“Excluded”处理。能力按 Tivoo 型号专用实现判定，不将泛 Divoom 清单套用于本机型。核对来源包括：

时钟样式说明：HA 通用服务 Schema 和设备父类接受 0–15，但 solar2ain/tivoo-control 的 Tivoo 专用 README 明确列出样式 0–6。项目只支持 Tivoo，因此服务/Tool 应限制为 0–6，不将通用父类字段范围当成当前型号能力。

Light 命令使用 0x45 0x01，是 16×16 像素屏上的纯色/灯效显示模式，不代表有独立灯条、背光或键盘灯。

- `solar2ain/tivoo-control`：本机图像/文字/动画/预设渲染的上游来源。
- `d03n3rfr1tz3/esp32-divoom`：Tivoo 原始协议帧的 ESP32 代理；支持的模式不等于每个型号都实现。
- `d03n3rfr1tz3/hass-divoom`：其 `devices/tivoo.py` 是型号专用覆写，优先级高于通用 `devices/divoom.py`；`services.py` / `services.yaml` 定义 HA 层服务与参数。
- 本机 `/home/Gold/WorkSpace/BluetoothBridgeTest/tivoo/`：当前项目的 Python payload builder、渲染器、离线测试和 `TivooDisplay` 业务方法。

**暴露级别：**
- **Service + Tool**：有 Tivoo 专用上游方法/明确业务语义，P4 注册 HA 服务并提供受约束的 MCP Tool。
- **Service only**：保留 HA 自动化/脚本服务；由于有效索引、模式列表或运行状态尚未确认，不让 LLM 自由猜值。
- **Native entity later**：当前实体尚未实现时先用 Tool；实体真实可用且暴露给 Assist 后移除重复 Tool。
- **Excluded**：上游明确不支持、其他型号专属、裸协议/连接管理或不符合项目架构。

### 4.0 完整能力覆盖矩阵

| 能力 | HA 服务 / Tool | 上游与本机实现依据 | 参数合同 / 限制 | P4 决策 |
|---|---|---|---|---|
| 表情/预设 | `tivoo.set_expression` / `tivoo__SetExpression` | `TivooDisplay.preset(name)`；`tivoo.py` 的 preset/emotion registry；`solar2ain/tivoo-control` 有 33 个动画预设和 24 个表情预设 | `name` 只接受运行时 registry 中存在且非隐藏项；不把 AI 生成图片字节作为参数 | MVP 必须 |
| 文字滚动 | `tivoo.show_text` / `tivoo__ShowText` | `TivooDisplay.text()`、`_gen_text_frames()`、HA `show_text()` | `value`；可选颜色、背景、速度、步长、字号、已安装字体名称；`step=1–8`、`font_size=8–16`；不暴露 `font_file` | MVP 必须 |
| 图片显示 | `tivoo.show_image` / `tivoo__ShowImage` | 本机 `TivooDisplay.image()`；HA `show_image(file,time)` | `file` 相对 `media_directory`；PNG/JPG/GIF；可选 `time=0–65535 ms` | MVP 必须 |
| GIF 动画 | `tivoo.play_animation` / `tivoo__PlayAnimation` | `solar2ain/tivoo-control anim(path)`；HA `Image.open()` / `process_image()` GIF 多帧通路 | 只接受 GIF 文件及可选帧间隔；帧目录与 stage JSON 不属于 HA image service 的文件合同 | MVP 必须 |
| 屏幕亮度 | `tivoo.set_brightness`（HA Service；不注册重复 MCP Tool） | 本机 `TivooDisplay.brightness()`；HA `brightness`；协议 `0x74` | `value: integer 0–100` | MVP 必须（Service only） |
| 屏幕开关 | `tivoo.set_screen_power` / `tivoo__SetScreenPower` | HA 上游 `on`/`off` → `send_on()`/`send_off()`；本机 `screen_on()`/`screen_off()` | `value: boolean`；不提供原始电源/亮度字节 | 可选扩展（首版不实现） |
| 扬声器音量 | `tivoo.set_volume` / `tivoo__SetVolume` | HA `volume` 服务；本机 `TivooDisplay.volume()` / `commands.volume_payload()`；ESP32 `send_volume()`；协议 `0x08`，0–100 映射到设备 0–15 | `volume: integer 0–100`。0 是有效值；handler 必须显式判断 `None`，不能用 `or` 把 0 当缺省 | MVP 必须（P4 首版） |
| 音乐播放控制 | `tivoo.set_playstate` / `tivoo__SetPlayState` | HA `playstate`；`Divoom.send_playstate()` 支持 `previous/pause/play/next`；本机 SDK 已有 pause/play builder | `value` 仅为 `previous`、`pause`、`play`、`next`；前/下一曲需复用上游 `set playtrack 0x12` 语义，不传任意数字 | 可选扩展（首版不实现） |
| 时钟显示 | `tivoo.show_clock` / `tivoo__ShowClock` | HA Tivoo 继承 `show_clock()`；ESP32 `0x45 0x00`；本机 `TivooDisplay.clock()` | 必需 `clock: 0–6`（Tivoo 专用 CLI 已列出）；可选 `twentyfour`、`weather`、`temp`、`calendar`、RGB `color`、`hot`。不接受其他型号 `clock_id` | 可选扩展（首版不实现） |
| 日期/时间同步 | `tivoo.set_datetime` / `tivoo__SetDateTime` | HA `datetime`；本机 `datetime_payload()`；ESP32 `send_datetime()` | 可选 ISO datetime；省略时使用 HA 当前时间。帧字段按本机已测试 payload builder；不能把其他实现多出的 weekday 字段未经验证带入 | 可选扩展（首版不实现） |
| 天气 | `tivoo.set_weather` / `tivoo__SetWeather` | HA `weather`；本机 `weather_payloads()`；ESP32 `send_weather()` | 温度值、`C/F` 单位、条件代码 `1/3/5/6/8/9`（晴/多云/雷暴/雨/雪/雾）；温度范围按已验证 payload builder | 可选扩展（首版不实现） |
| 屏幕灯效显示模式 | `tivoo.set_light` / `tivoo__SetLight` | HA `light`；Tivoo 继承 `show_light()`；ESP32 `show_light()`，`0x45 0x01` | 必需 `brightness: 0–100`；可选 RGB 和 `effect: 0–4`。这是 16×16 像素屏上的纯色/灯效，不是额外背光或键盘灯 | 可选扩展（首版不实现） |
| 倒计时启动 | `tivoo.start_countdown` / `tivoo__StartCountdown` | 本机 `countdown_payload()`；HA `show_countdown(value=True,countdown="MM:SS")`；ESP32 `0x72 0x03` | `countdown: "MM:SS"`；分钟 00–99、秒 00–59 | MVP 必须（P4 首版） |
| 倒计时停止 | `tivoo.stop_countdown` / `tivoo__StopCountdown` | HA `show_countdown(value=False,countdown=None)`；ESP32 缺省时间编码 `00:00` | **无参数**；不需要保存或重传启动时长 | MVP 必须（P4 首版） |
| 歌词视图 | `tivoo.show_lyrics` / `tivoo__ShowLyrics` | **Tivoo 专用** `devices/tivoo.py` 覆写 `show_lyrics()`，发送 view `0x06`；通用 Divoom 对该命令有未实现差异 | 无参数；不把 MiniToo/Tiivoo2 专有 `effect/background` 参数暴露给 Tivoo | 可选扩展（首版不实现） |
| 比分板 | `tivoo.show_scoreboard` / `tivoo__ShowScoreboard` | **Tivoo 专用** `devices/tivoo.py` 覆写 `show_scoreboard()`，以 `0x72 0x01` scoreboard tool 发送两个分数 | `player1/player2: integer 0–65535`；不混用老设备的 view `0x06` scoreboard 表示 | 可选扩展（首版不实现） |
| 内置计时器 | `tivoo.set_timer` / `tivoo__SetTimer` | 本机 `timer_payload()`；HA `timer`；ESP32 `0x72 0x00` | `value: boolean`，true 启动、false 停止；与 MM:SS 倒计时是不同命令 | 可选扩展（首版不实现） |
| 噪声计 | `tivoo.set_noise_meter` / `tivoo__SetNoiseMeter` | 本机 `noise_payload()`；HA `noise`；ESP32 `0x72 0x02`，停止值 `0x02` | `value: boolean`，true 启动、false 停止 | 可选扩展（首版不实现） |
| 闹钟 | `tivoo.set_alarm` / `tivoo__SetAlarm` | HA `alarm`；本机 `alarm_payload()`；Tivoo 继承 `show_alarm()`；ESP32 `0x43` | HA Service 的 `slot` 可选、默认 0；可选 `time: HH:MM`（省略则清除此槽）、weekdays、frequency 64–108 MHz、volume 0–100（默认 100）。alarmmode/triggermode 默认 0，不向模型开放 | 可选扩展（首版不实现） |
| 纪念提醒 | `tivoo.set_memorial` / `tivoo__SetMemorial` | HA `memorial`；本机 `memorial_payload()`；Tivoo 继承 `show_memorial()`；ESP32 `0x54` | HA Service 的 `slot` 可选、默认 0；可选 ISO datetime（省略则清除）、`text`（默认 Home Assistant，最多 16 UTF-16 code units） | 可选扩展（首版不实现） |
| 音源切换/电台 | `tivoo.set_audio_source` / `tivoo__SetAudioSource` | HA `radio`；Tivoo 继承 `show_radio()`；本机 `radio_payloads()`；ESP32 `0x05` / `0x61` | `value` 仅限 `bluetooth/fm/linein/sdcard/usb`；可选 FM frequency 64–108 MHz，仅 `fm` 时使用。`linein` 是 AUX 音源 | 可选扩展（首版不实现） |
| 睡眠音效 | `tivoo.set_sleep_mode` / `tivoo__SetSleepMode` | HA `sleep`；Tivoo 继承 `show_sleep()`；本机 `sleep_payload()`；ESP32 `0x40` | 必需 `value: boolean`；time 0–255 分钟（默认 120）、sleepmode 默认 0、frequency 64–108 MHz 可选、volume 0–100（默认 100）、RGB（默认黑色）、brightness 0–100（默认 100）；不开放 `volume1..8` | 可选扩展（首版不实现） |
| 设计频道 | `tivoo.show_design` / `tivoo__ShowDesign` | 本机 `design_payloads()`；Tivoo 继承 `show_design()`；ESP32 `0x45 0x05` + `0xBD 0x17` | `number: 0–3`，已由本机 builder 限定 | 可选扩展（首版不实现） |
| 效果频道 | `tivoo.show_effects` | HA `effects`；Tivoo 继承 `show_effects()`；ESP32 `0x45 0x03` | 协议字段可编码 0–255，但 Tivoo App 可选索引清单未在仓库中定义 | 可选扩展（首版不实现） |
| 可视化频道 | `tivoo.show_visualization` | HA `visualization`；Tivoo 继承 `show_visualization()`；ESP32 `0x45 0x04` | 协议字段可编码 0–255，但有效可视化索引/音频输入能力未确认 | 可选扩展（首版不实现） |
| 游戏 | `tivoo.show_game` | HA `game`；Tivoo 继承 `show_game()`；ESP32 `0xA0` | 游戏索引因设备/App 版本而异，当前没有 Tivoo 有效游戏列表 | 可选扩展（首版不实现） |
| 游戏控制 | `tivoo.game_control` | HA `gamecontrol`；Tivoo 继承 `send_gamecontrol()`；ESP32 按键事件 | `value` 为 `go/left/right/up/down/ok`；仅在已打开且当前游戏可控时有意义 | 可选扩展（首版不实现） |
| 原始协议 | 不提供 `raw` LLM Tool 或服务 | HA 上游有 `raw`；ESP32 raw bridge 能转发完整帧 | 任意字节会绕过所有业务参数和操作限制 | Excluded；只允许后续受控底层调试，不作为 AI 工具 |
| 连接管理 | 不提供 `connect/disconnect` LLM Tool | HA 上游有连接动作；本项目由 HA 服务/网关维护到 ESP32 的 TCP 连接 | MCP 调用者不应决定 SPP/TCP 生命周期 | Excluded from LLM；由 P6 transport owner 管理 |
| 其他型号功能 | 不注册 `equalizer`、`keyboard`、独立 `temperature`、`signal`、`clock_id`、`volume1..8` | Tivoo 专用 `devices/tivoo.py` 明确对 equalizer/keyboard/temperature/signal 抛 unsupported；clock_id 和 volume1..8 只属于其他型号 | 时钟中的 `temp` 显示开关仍保留；这不等于支持独立 temperature channel | Excluded；不得把其他型号功能移植给 Tivoo |

### 4.1 第一版 MVP 输入合同

第一版必须实现下列 HA Services；除屏幕亮度外，每项均提供同名语义的受约束 MCP Tool。HA Service 与 MCP Tool 使用相同业务语义；Tool 只调用对应服务，不复制 payload 或媒体处理逻辑。

| HA Service | MCP Tool | 必需输入 | 约束 |
|---|---|---|---|
| `tivoo.set_expression` | `tivoo__SetExpression` | `name: string` | 只接受运行时 preset registry 中真实存在且非隐藏的预设名称。 |
| `tivoo.show_text` | `tivoo__ShowText` | `value: string` | 可选 `color`、`background`、`speed`、`step`、`font_size`、`font`；`step=1–8`、`font_size=8–16`；font 必须是有效已安装字体；不暴露 `font_file`。 |
| `tivoo.start_countdown` | `tivoo__StartCountdown` | `countdown: string` | 严格 `MM:SS`；分钟 00–99，秒 00–59；映射上游 `show_countdown(value=True, countdown=...)`。 |
| `tivoo.stop_countdown` | `tivoo__StopCountdown` | 无 | 不接收任何参数；映射上游 `show_countdown(value=False, countdown=None)`，不读取或保存启动时长。 |
| `tivoo.set_volume` | `tivoo__SetVolume` | `volume: integer` | 0–100，包含 0；上游将 0–100 映射到设备音量 0–15。不得用 `value or default` 将 0 当作缺省值。 |
| `tivoo.set_brightness` | —（HA Service only） | `value: integer` | 0–100；供自动化、脚本和 HA Service 调用，不注册重复 `SetBrightness` Tool。 |
| `tivoo.show_image` | `tivoo__ShowImage` | `file: string` | 相对于 `media_directory`；支持静态 PNG/JPG 与 GIF；可选 `time: integer`，范围 0–65535 ms。 |
| `tivoo.play_animation` | `tivoo__PlayAnimation` | `file: string` | 相对于同一 `media_directory`；只接受 GIF；可选 `time: integer`，范围 0–65535 ms。 |

服务层需要保留语义命令接缝：测试环境可使用内存适配器验证调用参数；生产适配器在 P6 传输层接入前必须明确返回 unavailable，不得伪成功。屏幕亮度是必须注册的 HA Service，但不额外创建同义 MCP Tool。

### 4.2 MVP 媒体文件引用合同

复用 HA 上游 `d03n3rfr1tz3/hass-divoom` 已有的文件引用方式，不引入 asset ID、URI 或 HTTP URL：

- Tivoo 集成配置提供 `media_directory`，通过 `hass.config.path()` 相对 HA 配置目录解析；默认值沿用上游常量 `pixelart`。
- Tool 的 `file` 是相对于该目录的文件路径，例如 `generated/hello.gif`，不是 NAS 绝对路径。
- 解析后必须确认规范化路径仍位于 `media_directory` 内；复用上游 `_resolve_path()` 的 `realpath()` / `commonpath()` 边界检查模式。
- 静态图片沿用 Pillow `Image.open()` → `process_image()` → `send_frames()` 通路。GIF 自动读取多帧；未传 `time` 时沿用文件内 frame duration，传入时覆盖每帧时间。
- GIF 动画只接受 GIF 文件。帧目录和 `prepare` / `send` 的 JSON stage 是 CLI 本地工作流，不属于 HA image service 文件合同；不接受目录、JSON stage、原始帧数组或任意 URL。
- `show_image` 与 `play_animation` 共用文件根目录、GIF 解码和帧发送实现，不实现两套媒体协议。

### 4.3 第一版必需 Tool 与 Service 清单

第一版 MCP 工具清单固定为七项：

| Tool name | HA Service | 作用 |
|---|---|---|
| `tivoo__SetExpression` | `tivoo.set_expression` | 使用设备已有预设表情/动画 |
| `tivoo__ShowText` | `tivoo.show_text` | 显示/滚动文字 |
| `tivoo__StartCountdown` | `tivoo.start_countdown` | 启动 `MM:SS` 倒计时 |
| `tivoo__StopCountdown` | `tivoo.stop_countdown` | 无参数停止倒计时 |
| `tivoo__SetVolume` | `tivoo.set_volume` | 扬声器音量 0–100 |
| `tivoo__ShowImage` | `tivoo.show_image` | 显示 PNG/JPG/GIF 文件 |
| `tivoo__PlayAnimation` | `tivoo.play_animation` | 播放 GIF 动画 |

此外必须注册 `tivoo.set_brightness` HA Service（0–100），但不注册重复 `SetBrightness` MCP Tool。首版 `tools/list` 必须包含上述七个项目工具；HA Assist API 仍可能汇总其他集成注册的工具，验收时按 integration/source 区分。

未明确列入本次 MVP 的其余候选 Tool/Service 为：`SetScreenPower`、`SetPlayState`、`ShowClock`、`SetDateTime`、`SetWeather`、`SetLight`、`ShowLyrics`、`ShowScoreboard`、`SetTimer`、`SetNoiseMeter`、`SetAlarm`、`SetMemorial`、`SetAudioSource`、`SetSleepMode`、`ShowDesign`。`effects`、`visualization`、`game`、`game_control` 在缺乏有效 Tivoo 索引/状态证据时保持 Service only。它们均为可选扩展，不纳入首版实现和验收门。

### 4.4 MVP ToolAnnotations

七个首版 Tool 均为写操作，显式设置 `read_only=False`、`destructive=False`、`open_world=False`，并显式设置 `integration="tivoo"`：

- `SetVolume` 是目标音量状态设置，`idempotent=True`。
- `StopCountdown` 是停止状态设置，`idempotent=True`。
- `StartCountdown` 会启动或重置时间，`idempotent=False`。
- `SetExpression`、`ShowText`、`ShowImage`、`PlayAnimation` 都可能重播或重新开始显示过程，设置 `idempotent=False`。

屏幕亮度仅作为 HA Service 提供，不适用 MCP ToolAnnotations。Annotations 是模型提示元数据，不是授权机制；实际访问限制仍由 HA 用户权限、Assist 工具过滤和服务参数校验决定。

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
| commands.py | volume、pause/play、datetime、weather、countdown、timer、noise、alarm、memorial、radio、sleep、effects、visualization、design、game/gamecontrol payload builders | 优先复用已有 builder；previous/next track、Tivoo scoreboard/lyrics、clock hot、light effect 等只在需要时补最小 builder 和 golden tests |
| tivoo.py | 外层 packet、图像缩放/调色板编码、build_image_frame、文字帧生成、动画块构建、preset registry | 复用纯协议/渲染函数；避免复制实现并分叉 |
| client.py | TivooDisplay 高层方法覆盖 brightness、clock、light、image、animation、text、preset、volume、playstate、datetime、weather、countdown、timer、noise、alarm、memorial、radio、sleep、effects、visualization、design、game、game_control、status | 复用高层方法签名作为业务映射依据；Transport 不直接用于 HA/NAS |
| test_commands.py | 既有 payload 与外层帧的离线单元测试 | 保留为 golden/regression 验证依据 |
| protocol-reference.md | 命令表、帧结构、兼容性说明 | 供实现者查阅；如与可执行代码冲突，以代码和测试为准并修订说明 |

上游 hass-divoom 的 Tivoo 型号专用驱动还实现 lyrics 与 scoreboard，并明确拒绝 equalizer、keyboard；这些型号专用证据优先于通用父类或较早的本机协议笔记。当前 MVP 复用表情、文字、图片/GIF、亮度、倒计时和音量所需的纯协议/渲染能力；不复制 BluetoothBridge 客户端，也不扩展到未声明的其他服务。
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

## 7. P4 批次边界与第一版范围

P4 保留原定七个批次 P4b0–P4b6。用户明确列出的七类功能均为 MVP 必须完成项：表情预设、文字显示、亮度 HA Service、图片显示、GIF 动画、倒计时启停、扬声器音量。未在此清单中的其他 Tivoo 服务仍为可选扩展。

| 批次 | 原定目标 | MVP 必须完成部分 | 依赖 |
|---|---|---|---|
| P4b0 | 版本、源码、测试环境及协议复用前置核查 | 所有 MVP 接口、测试环境和协议复用前置核查 | 无 |
| P4b1 | 建立 Tivoo HA 集成、服务注册和 StopCountdown 服务 | 集成骨架；StopCountdown、SetVolume Service；media_directory 配置基础 | P4b0 |
| P4b2 | 实现 HA LLM Tools 平台及首个 Tool | LLM Tools 平台、StopCountdown Tool | P4b1 |
| P4b3 | 表情、文字、倒计时工具和亮度服务 | SetExpression、ShowText、StartCountdown、SetVolume Tools；SetBrightness Service | P4b2 |
| P4b4 | 图片/GIF 文件处理及媒体工具 | ShowImage、PlayAnimation Tools 与媒体文件处理 | P4b2；与 P4b3 完成后共同进入 P4b5 |
| P4b5 | AstrBot MCP 配置、Persona 授权和运行时验证 | 发现并授权全部七个必需 Tool，运行时验证 | P4b3、P4b4 |
| P4b6 | P4 合同矩阵验收、P3 回归和收尾 | 验收全部 MVP 实现，并验证倒计时启停与音量的完整 MCP→HA→Service→Adapter 链路 | P4b5 |

依赖顺序：`P4b0 → P4b1 → P4b2 → {P4b3, P4b4} → P4b5 → P4b6`。P4b3 与 P4b4 可在 P4b2 后分别执行；两者都是 MVP 必需批次，P4b5 必须等待两者完成。

详细任务、文件范围、测试与提交门见 [P4 Batch Execution Plan](../plans/2026-11-09-p4-ha-mcp-tool-batch-execution-plan.md)。

## 8. P4 第一版验收矩阵

| ID | 验收项 | 第一版通过标准 | 阶段 |
|---|---|---|---|
| P4-C01 | HA MCP Server 路由 | HA Core 2026.11.0 原生 `/api/mcp/assist` 可达 | MVP |
| P4-C02 | Streamable HTTP 初始化 | AstrBot 4.29.4 使用 `transport=streamable_http` 与 Bearer header 完成 initialize | MVP |
| P4-C03 | MCP 工具发现 | 七个必需 Tivoo Tool：SetExpression、ShowText、StartCountdown、StopCountdown、SetVolume、ShowImage、PlayAnimation 出现在目标 Persona 工具集 | MVP |
| P4-C04 | 权限边界 | 普通 HA 用户有效 Token 可用；无效 Token 拒绝；不需要管理员权限 | MVP |
| P4-C05 | 实体暴露范围 | 未暴露实体不成为可调用对象；七项显式 Tivoo Tool 和亮度 HA Service 不依赖任意服务调用 | MVP |
| P4-C06 | 工具注册过滤 | Tivoo `llm.py` 仅向 `assist` API 提供上述七个 MVP Tool | MVP |
| P4-C07 | 服务复用 | 七个 Tool 分别调用对应 HA Service；亮度由 `tivoo.set_brightness` Service 提供；服务逻辑可由自动化共用 | MVP |
| P4-C08 | 失败传播 | 参数错误、服务不存在、媒体文件不合法、适配器不可用等情况明确失败，不返回伪成功 | MVP |
| P4-C09 | 基础参数范围 | 倒计时严格 `MM:SS`；Stop 无参数；Volume/Brightness 整数 0–100 且音量 0 有效；表情与文字输入按运行时 registry/Schema 校验 | MVP |
| P4-C10 | 媒体参数边界 | `media_directory` 相对路径、静态 PNG/JPG、GIF、多帧时长、路径越界拒绝；不接受 URL/绝对路径/原始帧数组 | MVP |
| P4-C11 | P3 回归 | P3 HTTP Chat、session_id、SSE → ChatLog 不受影响；MCP 不作为文本 STT 入口 | MVP |
| P4-C12 | 断线与重试 | 按 AstrBot 4.29.4 实际行为验证连接恢复；记录 StartCountdown/显示类非幂等动作的响应丢失风险 | MVP |
| P4-C13 | 设备传输隔离 | AstrBot 不直接连接 TCP 7777/7778、SPP 或 ESP32；动作经 HA Service 和语义适配器 | MVP |
| P4-C14 | Tivoo 实机动作 | 真实屏幕、表情、文字、图片/GIF、亮度、音量和倒计时动作在 Tivoo 上生效并有设备侧证据 | P5/P6 |
| P4-C15 | 未声明功能边界 | 未明确列入 MVP 的其他 Tivoo 服务不被误纳入首版；保持可选扩展或按证据 Excluded | MVP |

P4 第一版完成要求 P4-C01–C13、C15 的 MVP 适用项全部有证据。P4-C14 的实际设备回执仍交由 P5/P6，不以测试适配器结果冒充真机验收。

## 9. 未冻结项与实现前必须解决的问题

以下问题是媒体部署或后续硬件阶段需要解决的真实缺口。它们不得被理解为可以跳过本版图片/GIF 文件解析、路径约束和服务测试；涉及所有 MVP 服务/Tool 的参数与接口问题都必须在对应批次解决：

1. **MVP 媒体输入范围**：`solar2ain/tivoo-control` 的 `anim(path)` 支持 GIF 或帧目录，`prepare` / `send` 支持本地 JSON stage（`frames` / `delays`）；HA 上游 `hass-divoom` 的 `image(file,time)` 通过 Pillow `Image.open()` 读取文件，已有静态图/GIF 能力，但没有帧目录或 JSON stage 输入。MVP 按 HA 可复用接口只接受静态图片/GIF；目录和 stage JSON 不属于本版支持范围，不为此新增自定义资源格式。
2. **媒体文件在 HA 侧的可见性**：上游服务的 `file` 必须位于 HA 配置的 `media_directory` 之下。AstrBot 生成图片/动画后如何将文件安全放入该目录，属于运行环境的文件交接问题，不是 MCP 媒体 URI 协议；MVP 必须验证 HA 配置目录中的媒体文件能被服务读取，不应因此放开任意绝对路径或公网 URL。
3. **后续可选设备功能的固件兼容性**：上游 Tivoo 驱动有代码实现不等于用户手上固件版本已经现场通过。P4 验收表情、文字、亮度、图片/GIF、倒计时和音量的 HA 服务与 MCP 应用行为；真实设备动作及设备侧回执仍需 P5/P6 实机验收。
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
- [hass-divoom Tivoo 专用驱动](https://github.com/d03n3rfr1tz3/hass-divoom/blob/main/custom_components/divoom/devices/tivoo.py)：证实 Tivoo 型号专门实现 lyrics 与 scoreboard；并明确拒绝 equalizer 与 keyboard。该文件优先于通用 Divoom 父类判断具体型号能力。
- [hass-divoom 通用设备驱动](https://github.com/d03n3rfr1tz3/hass-divoom/blob/main/custom_components/divoom/devices/divoom.py)：Tivoo 继承的 volume、playstate、clock、light、countdown、timer、noise、alarm、memorial、radio、sleep、weather、text、design、effects、visualization、game 等具体实现；standalone temperature 与 signal 显式 unsupported。
- [hass-divoom 服务 Schema](https://github.com/d03n3rfr1tz3/hass-divoom/blob/main/custom_components/divoom/services.py) 与 [services.yaml](https://github.com/d03n3rfr1tz3/hass-divoom/blob/main/custom_components/divoom/services.yaml)：HA 服务字段、0–100 音量/亮度、source enum、radio frequency、设备类型差异和其它参数边界。

- Home Assistant Core 2026.11.0 MCP Server：`homeassistant/components/mcp_server/http.py`、`server.py`、`config_flow.py`。
- Home Assistant Core 2026.11.0 LLM Tools：`homeassistant/components/llm/__init__.py`、`llm.py`、`homeassistant/helpers/llm.py`。
- AstrBot v4.29.4 MCP Client：[astrbot/core/agent/mcp_client.py](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/core/agent/mcp_client.py)。
- [Home Assistant MCP Server 官方说明](https://www.home-assistant.io/integrations/mcp_server/)。
- [Home Assistant LLM API 开发说明](https://contributors.home-assistant.io/core/internals/llm-api/)（以当前 HA Core 2026.11.0 实际源码接口为准）。
- [d03n3rfr1tz3/esp32-divoom](https://github.com/d03n3rfr1tz3/esp32-divoom)。
- [solar2ain/tivoo-control](https://github.com/solar2ain/tivoo-control)（本机 Tivoo Python 端的上游项目；复用前单独核实许可证及本机分支变更）。

---

**本合同矩阵创建范围（2026-11-09）：** 创建合同矩阵时不新增代码、不修改 P3 文档或 README、不连接 NAS 做设备测试、不部署 MCP 服务、不填写或提交任何 HA/AstrBot Token。P4 批次执行计划随后单独建立，见本节链接。
