# P4 目标 HA / AstrBot 运行时补充验收报告

日期：2026-11-10

分支：`feature/p4-ha-mcp-server`

部署代码提交：`128e47f487f8bd6d0acfbb5c5834bbc7a2713a7c`
关联报告：`2026-11-09-p4b6-acceptance-report.md`

## 1. 结论

本次在实际 NAS 部署环境补充完成了 P4 的关键运行时验收：Tivoo HA 集成部署并被 HA 启动加载；AstrBot 4.29.4 通过 Streamable HTTP 连接 HA `/api/mcp/assist`；AstrBot 工具列表显示七个必需的 Tivoo Tool；用户从当前 Persona 实际调用 `StopCountdown`，并收到 Tivoo 生产 Adapter 尚未配置设备传输通道的预期错误。

这证明了 MCP 连接、工具发现、至少一个 Persona 工具调用，以及 HA/Tivoo 错误返回链路。它**不代表设备动作执行成功**，也不代表七个工具均已逐项验证 Persona 授权。P4 整体继续保持 **PARTIAL**，原因是七个工具的 Persona 全量授权、`StartCountdown` / `SetVolume` 真实 Persona 调用，以及断线/响应丢失故障注入尚未完成。

## 2. 实际部署环境

| 项目 | 实测值 |
|---|---|
| NAS | Synology DS920，`192.168.3.94` |
| HA 容器 | `homeassistant` |
| HA 镜像 | `ghcr.io/home-assistant/home-assistant:2026.11.0` |
| HA Core | `2026.11.0` |
| 容器 Python | `3.14.10` |
| Pillow | `13.0.0` |
| AstrBot 容器 | `astrbot` |
| AstrBot 镜像 | `m.daocloud.io/docker.io/soulter/astrbot:latest` |
| AstrBot 实际版本 | `4.29.4` |
| HA 配置挂载 | `/volume1/docker/homeassistant/config` → `/config` |
| AstrBot 数据挂载 | `/volume1/docker/astrbot/data` → `/AstrBot/data` |

## 3. HA 集成部署与启动检查

- 从本地提交 `128e47f` 的 Git 跟踪内容打包部署 `homeassistant/custom_components/tivoo/` 到 `/volume1/docker/homeassistant/config/custom_components/tivoo/`。
- 部署包 SHA-256：`4c09c206f14dd59a081f838cf2f55c6db39de63c127c13212468c6daeb3737ba`；开发机和 NAS 计算结果一致。
- 部署前确认目标目录不存在，因此没有覆盖旧版集成；部署 16 个 Git 跟踪文件。HA 首次加载后产生的 `__pycache__` 不属于发布包。
- 创建默认媒体目录 `/volume1/docker/homeassistant/config/pixelart/`，对应 HA 配置目录内的 `/config/pixelart`。
- 仅重启 `homeassistant` 容器；AstrBot、MPD Server 和其他容器未重启。
- 重启后容器恢复 `running`，镜像仍为 HA Core 2026.11.0；HA 首页 HTTP 200。
- HA 启动日志出现 `custom integration tivoo has not been tested by Home Assistant` 的通用自定义集成提示；新启动日志样本未发现 Tivoo 初始化 Traceback 或 setup error。
- 在 HA 容器 Python 环境内导入 `tivoo.config_flow`、`tivoo.llm`、`tivoo.media`、`tivoo.rendering`、`tivoo.services` 均通过。
- 随后确认 HA 中已创建 `Tivoo` Config Entry，媒体目录配置为 `pixelart`。

本节只记录部署和运行时启动检查；没有在 NAS 上运行 pytest、Ruff 或其他完整代码级测试。

## 4. HA MCP Server 配置

实际 HA `mcp_server` Config Entry 配置摘要（不包含凭据）：

| 选项 | 实际值 |
|---|---|
| All LLM APIs / `all_llm_apis` | `false` |
| Selected LLM API / `llm_hass_api` | `assist` |
| Require admin / `require_admin` | `true` |
| Read-only / `read_only` | `true` |

按 HA Core 2026.11.0 的 MCP Server 实现，以上三个选项作用于主地址 `/api/mcp`。独立 API URL `/api/mcp/assist` 直接提供 Assist / Device control API，不受主地址选项中的 `require_admin` 和 `read_only` 限制。P4 的调用端点仍是 `/api/mcp/assist`；此处的 read-only 开关不能当作该端点的写操作限制。具体 HA API 工具暴露范围仍由 Assist API、实体暴露规则和 Tivoo 显式 Tool Schema 决定。该语义已在 P4 合同矩阵 §2.1 记录。

部署后未授权 GET 探测 `/api/mcp/assist` 返回 HTTP 405；Streamable HTTP 路由使用 MCP 请求方法。最终端点可用性由后续 AstrBot 实际连接、工具发现和 Persona 调用证据确认，而不是仅凭 GET 状态码判定。

## 5. AstrBot MCP 连接与工具发现

NAS 上实际 AstrBot 版本为 `4.29.4`。其数据目录 `mcp_server.json` 中确认存在一个启用的服务器配置：

| 字段 | 实际配置 |
|---|---|
| Server key | `tivoo_tools` |
| Active | `true` |
| Transport | `streamable_http` |
| URL | `http://192.168.3.94:8123/api/mcp/assist` |
| Authorization | 已配置 Bearer header（明文不读取、不记录） |
| Timeout | `30` 秒 |
| SSE read timeout | `300` 秒 |

用户提供的 AstrBot「可用工具」页面截图显示以下七个项目工具全部可发现：

- `tivoo__SetExpression`
- `tivoo__ShowText`
- `tivoo__StartCountdown`
- `tivoo__StopCountdown`
- `tivoo__SetVolume`
- `tivoo__ShowImage`
- `tivoo__PlayAnimation`

截图同时显示了 HA 原生 Assist 工具（例如 `homeassistant__GetLiveContext`）以及其他集成的工具。它们属于 Assist API 汇总的可用工具，不是 Tivoo 项目新增的 Tool；这与 P4 设计一致。

**判定：AstrBot 4.29.4 的 Streamable HTTP 连接、MCP 初始化及工具列表发现通过；七个 Tivoo Tool 均已出现在 AstrBot 可用工具列表。**

## 6. Persona 实际调用

用户随后从当前实际使用的 Persona 调用了 `StopCountdown`。AstrBot 返回的错误内容为（用户提供）：

> Tivoo 命令适配器尚未配置设备传输通道，因此该操作未能成功执行。

该响应与当前生产代码中的 `UnavailableCommandAdapter` 行为一致：P4 提供 HA Service 和 LLM Tool；设备传输通道尚未由后续 P6 实现接入时，Adapter 应明确返回不可用，而不能伪装动作成功。

**本次判定：**

- 当前 Persona 能够实际触发 `StopCountdown`：通过。
- 当前 Persona 对 `StopCountdown` 的工具调用触发了与 HA Tivoo `UnavailableCommandAdapter` 一致的不可用错误：按用户提供的真实调用结果判定该控制面调用/错误反馈路径通过；本次没有独立抓取 JSON-RPC 原始包或 HA Service 事件日志。
- 错误信息明确说明设备命令未执行，没有伪报硬件动作成功：通过。
- 没有证据证明其余六个 Tool 均已被该 Persona 单独授权并成功发起 `tools/call`；不扩大本次结论。
- 没有真实 Tivoo 设备动作或设备侧回执；硬件验收仍属于 P5/P6。

## 7. P4 合同验收状态更新

| 合同 | 当前状态 | 目标环境证据 |
|---|---|---|
| P4-C01 MCP 路由 | PASS | AstrBot 实际连接 `/api/mcp/assist` 并成功发现工具。 |
| P4-C02 Streamable HTTP 初始化 | PASS | AstrBot 4.29.4 的 Streamable HTTP 客户端实际连接并展示工具列表。 |
| P4-C03 七个 Tool 发现 / Persona 授权 | PARTIAL | 七个 `tivoo__*` 均在 AstrBot 可用工具列表；当前 Persona 已调用 `StopCountdown`，其余六项尚未逐一确认 Persona 授权/调用。 |
| P4-C04 权限边界 | PASS（本地合同测试）/ 目标令牌角色未重新核验 | P4b5 本地自动化已验证普通 HA 用户 LLAT；目标运行时 Bearer Token 实际可用，但本次未重新检查 Token 所属 HA 用户角色。Assist 专用地址本身不要求管理员。 |
| P4-C05 实体暴露范围 | PASS（本地自动化） | 本次截图看到原生 Assist 工具；没有对实体暴露规则作额外改动。 |
| P4-C06 Tool 注册过滤 | PASS（本地自动化） | 七个项目 Tool 名称均以 `tivoo__` 出现在 Assist 工具集合中。 |
| P4-C07 服务复用 | PASS（本地自动化） | 本次 StopCountdown 运行时错误与服务/Adapter 不可用边界一致；服务委派各分支仍以 P4 自动化证据为主。 |
| P4-C08 失败传播 | PASS | 既有自动化错误测试通过；真实 Persona StopCountdown 收到预期 Adapter unavailable 错误。 |
| P4-C09 参数范围 | PASS（本地自动化） | 本次只实测无参数 StopCountdown；其他参数边界仍引用 P4b1–P4b6 自动化结果。 |
| P4-C10 媒体边界 | PASS（本地自动化） | 本次部署默认媒体目录；没有做跨容器媒体文件交接或硬件显示测试。 |
| P4-C11 P3 回归 | PASS（本地自动化） | P4b6 最终全量 205 passed，包含 P3 回归。部署阶段未重复运行。 |
| P4-C12 断线与响应丢失 | PARTIAL | 已确认实际连接和普通调用，但未做断线重连/响应丢失故障注入；非幂等动作重复执行风险仍需验证。 |
| P4-C13 设备传输隔离 | PASS（代码审查） | 目标部署未引入 TCP 7777/7778、RFCOMM/SPP 或 ESP32 直连路径。 |
| P4-C14 Tivoo 实机动作 | DEFERRED | 当前 Adapter 明确 unavailable；实际显示、倒计时、亮度、音量及媒体执行交 P5/P6。 |
| P4-C15 未声明功能边界 | PASS（本地合同验收） | 实际发现的七个 Tivoo Tool 与 MVP 合同一致。 |

## 8. 剩余验收项

1. 从当前 Persona 逐一确认 `SetExpression`、`ShowText`、`StartCountdown`、`SetVolume`、`ShowImage`、`PlayAnimation` 的授权和 `tools/call`；其中 `StopCountdown` 已完成一次调用。
2. 在 Persona 运行时验证 `StartCountdown` 的 `01:30` 参数和 `SetVolume` 的 0/100 参数是否按合同到达 HA Service。P6 设备传输接入之前，预期仍可能得到 Adapter unavailable 错误；这里只验收控制面参数和错误返回。
3. 对 AstrBot 4.29.4 实际连接执行受控断线恢复和响应丢失测试，确认其重试策略，并评估非幂等操作重复执行风险。不要对真实硬件做无保护的故障注入。
4. P5/P6 设备传输完成后，在 Tivoo 实机上验收表情、文字/滚动、亮度、PNG/JPG/GIF、倒计时启停和音量，并取得设备侧证据。

## 9. 安全与范围

- 没有将 HA Long-Lived Access Token 或 AstrBot 配置中的 Authorization 明文复制到报告、Git、命令输出或进度记录。
- 只部署 `custom_components/tivoo` 并重启 `homeassistant`；没有修改 AstrBot、MPD Server、其他容器或 NAS 生产网络配置。
- 没有连接 Tivoo 硬件，没有宣称任何硬件动作执行成功。
- 没有在 NAS 上重复运行代码级测试；P4b6 的 205 项全量测试与静态检查结果继续引用原验收报告。
- 本报告只记录运行时验收补充证据；不更新 README 为 P4 complete。P4 整体继续 PARTIAL，直到剩余 P4-C03 / P4-C12 运行时门完成。
