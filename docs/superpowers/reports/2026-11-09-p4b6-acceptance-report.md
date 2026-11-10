# P4b6 合同矩阵验收与收尾报告

日期：2026-11-09
分支：`feature/p4-ha-mcp-server`
批次基线：`7f9f04ad8f880cd677599659fe6b79d7fc5bac86`

## 1. 结论

**P4b6 本地合同验收、P3 回归、静态检查和证据追踪已完成。2026-11-10 的目标环境补充验收已通过 HA 部署/加载、AstrBot 4.29.4 Streamable HTTP 连接、七个 Tivoo Tool 发现，以及 Persona 对 StopCountdown 的一次真实调用和预期 Adapter unavailable 错误返回。P4 整体仍为 PARTIAL：全部七个 Tool 的 Persona 授权、StartCountdown/SetVolume 的 Persona 调用及连接中断/响应丢失故障注入仍待验证。详见 `2026-11-10-p4-runtime-acceptance-report.md`。

2026-11-09 的 P4b6 本地批次没有把 MCP SDK 测试客户端当作 AstrBot 运行时证据，也没有把内存 Adapter 的成功当作 Tivoo 设备动作成功；当时开发机没有运行中的 HA/AstrBot 服务或 WebUI。2026-11-10 随后的独立目标环境验收连接了 NAS 并部署当前 P4 提交，过程及证据见补充运行时报告；没有读取或记录任何 Token 明文。

P4 当前生产 Adapter 仍按设计明确返回 unavailable，直到 P6 设备传输层接入。C14 的真实 Tivoo 硬件动作属于 P5/P6，不是 P4 的退出条件。

## 2. 本批范围与改动

仅完成 P4b6 验收与记录，没有新增生产功能、传输实现或 P3 业务逻辑。

- 新增 `tests/homeassistant/custom_components/tivoo/test_tivoo_p4b6_acceptance.py`：通过真实 HA Assist MCP Streamable HTTP 路由验证实体暴露隔离和 Tivoo 工具边界。
- 更新 P4 Batch Execution Plan 和 P4 Implementation Plan 的 P4b6 状态与实际阻塞说明。
- 新增本验收报告。
- 未修改 README：实施计划要求只有所有对应运行时验收门通过后才更新整体 P4 状态；Persona/真实 AstrBot 运行时证据尚未取得。

## 3. 自动化验证结果

最终代码树验证：

| 验证 | 结果 |
|---|---:|
| `./scripts/test-ha.sh -q` | **205 passed**, 74 warnings |
| Tivoo 集成聚焦测试 | **113 passed**, 16 warnings |
| P3 AstrBot 集成回归 | **92 passed**, 63 warnings |
| P4b6 新增实体暴露/工具边界测试 | **2 passed**（包含在上述 113/205 中） |
| Ruff check（排除两份未修改的上游 preset 文件） | PASS |
| Ruff format check（排除 4 个 HEAD 中未修改的历史格式文件） | PASS，剩余 31 个文件已格式化 |
| Python compileall | PASS |
| `pip check` | PASS，无 broken requirements |
| Tivoo manifest/translations JSON、services YAML 解析 | PASS |
| `git diff --check` | PASS |

warnings 主要来自 HA/aiohttp 的 NotAppKeyWarning、HA/backoff 的依赖弃用提示，以及测试专门尝试连接非 loopback 地址并确认被 pytest_socket 拒绝的预期警告。没有测试失败。

完整 Ruff format 检查曾报告 4 个文件未格式化：`homeassistant/custom_components/tivoo/__init__.py`、两份已有上游 preset 文件、`tests/homeassistant/custom_components/tivoo/test_services.py`。这些文件均与当前 HEAD 相同、未由 P4b6 修改；本批只对新测试文件执行格式化，并在排除这 4 个基线文件后复核其余代码。

## 4. P4-C01–C15 合同追踪

状态含义：PASS = 该合同已有足够的自动化或目标运行时证据；PARTIAL = 已验证部分关键路径，但仍有合同子项未验证；BLOCKED = 当前环境无法执行；DEFERRED = 合同明确归属后续阶段。

| 合同 | 状态 | 本次证据与未完成项 |
|---|---|---|
| P4-C01 MCP 路由 | PASS | `test_tivoo_p4b5_mcp_http.py` 通过 HA Core 2026.11.0 实际 `/api/mcp/assist` 路由 initialize/list/call。 |
| P4-C02 Streamable HTTP | PASS | 开发机 MCP SDK 测试与 2026-11-10 目标运行时证据相互补充：AstrBot 4.29.4 已配置 `streamable_http`，实际连接 `/api/mcp/assist` 并显示工具列表；目标客户端 initialize/list 已通过。 |
| P4-C03 七个 Tool 发现 | PARTIAL | AstrBot 4.29.4 的可用工具列表已显示全部七个 `tivoo__*` Tool；用户随后从当前 Persona 实际调用 `StopCountdown` 并收到预期 Adapter 错误。截图证明 MCP 工具发现，单次调用证明至少该 Tool 对当前 Persona 可用；尚未逐项证明七个 Tool 全部获该 Persona 授权并可调用。 |
| P4-C04 权限边界 | PASS | 测试内普通 HA 用户有效 Bearer Token 可用，无效 Token 返回 HTTP 401；没有使用管理员 Token 调用 Assist endpoint。 |
| P4-C05 实体暴露范围 | PASS | P4b6 新增真实 MCP 调用测试：conversation 已暴露实体的名称/状态进入 GetLiveContext，隐藏实体不进入；Tivoo 工具只提供七项显式动作，不接受 entity_id 任意目标，Assist API 不暴露管理用 `homeassistant__call_action`。 |
| P4-C06 Tool 注册过滤 | PASS | 既有测试验证 Tivoo LLM 平台仅对 `LLM_API_ASSIST` 注册工具；七项 Tool 列表与集成标识均已检查。 |
| P4-C07 服务复用 | PASS | 七个 Tool 均经 MCP tools/call → HA LLM Tool → 对应 HA Service → 内存 Adapter；SetBrightness 通过独立 HA Service 验证，没有重复 Tool。 |
| P4-C08 失败传播 | PASS | 参数 Schema、服务缺失/不可用、Adapter 异常、媒体文件错误均有自动化错误测试；2026-11-10 的真实 Persona `StopCountdown` 调用也返回“命令适配器尚未配置设备传输通道”的预期错误，没有伪称硬件执行成功。 |
| P4-C09 参数范围 | PASS | 倒计时严格 MM:SS，StopCountdown 无参数；Volume/Brightness 整数 0–100，覆盖 0/100 和越界；preset、文字样式及字体参数有边界测试。 |
| P4-C10 媒体边界 | PASS | PNG/JPEG/GIF、多帧时长保留与覆盖、相对 media_directory、绝对路径/URL/路径穿越/symlink 逃逸/目录/缺失/损坏文件拒绝均有测试。 |
| P4-C11 P3 回归 | PASS | P3 AstrBot 集成 92 passed；最终 HA 全量测试 205 passed。Chat API、session、SSE、ChatLog 和取消相关原有 P3 测试均在全量回归中执行。 |
| P4-C12 断线与重试 | PARTIAL | 已按 P4b5 固定 AstrBot 4.29.4 源码提交 `61335414433db721b3f7ecc93f90deafe0a59d78` 核对重连路径：ClosedResourceError 后重建连接并刷新 tools/list，Tenacity `stop_after_attempt(2)` 为总计最多两次调用。尚未在真实 AstrBot 运行时注入响应丢失故障；非幂等动作可能在服务端已执行而响应丢失后再次执行。 |
| P4-C13 设备传输隔离 | PASS | Tivoo HA 运行时代码只包含语义命令与 Service/Adapter；代码扫描未发现 TCP 7777/7778、RFCOMM/SPP 或 Bluetooth transport 实现。 |
| P4-C14 Tivoo 实机动作 | DEFERRED | 按合同归属 P5/P6；P4 测试 Adapter 不代表真实屏幕、亮度、图像/GIF、倒计时或扬声器动作已成功。 |
| P4-C15 未声明功能边界 | PASS | 只保留七个 MVP Tool 和八个明确 Service（其中 SetBrightness 是 Service）；未将其他未声明 Tivoo 功能加入本批。 |

### 重点链路

以下三项已在本地完成 HA Assist MCP HTTP → Tivoo Tool → HA Service → 内存 Adapter 的端到端验证：

| 动作 | MCP 参数 | Adapter 观察值 |
|---|---|---|
| StartCountdown | `{"countdown":"01:30"}` | `start_countdown` / `countdown="01:30"` |
| StopCountdown | `{}` | `stop_countdown` / 空 data |
| SetVolume | `{"volume":0}`、`{"volume":100}` | `set_volume` / 分别保留 0 和 100 |

上表三项仍是本地 MCP SDK 客户端发起的 Adapter 路径自动化证据，不是 AstrBot Persona 发起。另有一项独立运行时证据：2026-11-10 当前 AstrBot Persona 发起 `StopCountdown`，HA 返回 Adapter 未配置设备传输通道的预期错误；这证明调用和错误返回链路，不证明硬件动作成功。

## 5. 必须人工验收的项目

### 5.1 目标 HA / AstrBot 运行时（P4 尚未通过的部分）

2026-11-10 已完成的目标运行时步骤见 `2026-11-10-p4-runtime-acceptance-report.md`。剩余人工验收：

1. 在当前目标 Persona 中逐项确认七个 Tivoo Tool 的授权状态；目前已确认列表包含全部七项，且至少 `StopCountdown` 可由该 Persona 实际调用。
2. 从同一 Persona 验证 StartCountdown `01:30`、SetVolume 0/100 的参数与 HA Service 入参一致；当前生产 Adapter 在 P6 前会明确返回 unavailable，因此本项只验证调用到 HA Service 的错误/可用性行为，不要求设备执行成功。StopCountdown 无参数调用已完成一次。
3. 对 AstrBot MCP 连接执行受控断开/恢复与响应丢失测试，重点观察 StartCountdown、SetExpression、PlayAnimation 等非幂等动作是否可能重复执行。不要在真实设备上用会造成风险的动作做无保护故障注入。

### 5.2 媒体文件交接

图片/GIF 服务只接受 HA 配置目录下 `media_directory` 的相对文件引用。部署时需先把待显示 PNG/JPG/GIF 文件放入 HA 该目录，再由 AstrBot 传入相对文件名。AstrBot 生成文件跨容器复制/上传协议不属于 P4，本批没有新增远程 URL 或 asset ID 机制。

### 5.3 Tivoo 真机动作（P5/P6）

设备传输 Adapter 接入后，再由人工确认：

- 表情预设实际显示；
- 中文/英文文字及滚动效果；
- 亮度 0、边界值与中间值；
- PNG/JPG 图片与多帧 GIF 显示、帧时长；
- 倒计时启动、停止；
- 扬声器音量 0、100 及中间值。

这些是真实设备侧验收，不应在当前阶段用内存 Adapter 代替。

## 6. 代码审查与范围

- 仅新增 P4b6 验收测试及更新 P4 计划/验收文档；无生产业务代码变更。
- 未修改 P3 实现、AstrBot 插件、ESP32、NAS 部署、Token 或生产配置。
- P4b6 本地批次本身没有连接 NAS 或 Tivoo 实机；2026-11-10 的后续 HA/AstrBot 运行时部署和受控调用记录见补充报告。没有连接 Tivoo 实机或验证真实屏幕/音频动作。
- 按 SuperPower 流程完成作者自审；当前工具环境没有独立 reviewer/subagent 调度能力，因此本报告不声称独立审查通过。
- P4b6 本地验收与后续目标运行时补充验收均有报告。HA/AstrBot 连接、七个 Tool 发现和一次 StopCountdown Persona 调用已通过；七个 Tool 的完整 Persona 授权、StartCountdown/SetVolume Persona 调用及重连/响应丢失注入仍待人工验收。整体 P4 保持 PARTIAL。
- 本批只本地提交，不 push、不 merge。

## 7. 本批证据文件

- `docs/superpowers/reports/2026-11-10-p4-runtime-acceptance-report.md`（目标 HA/AstrBot 运行时补充验收）
- `tests/homeassistant/custom_components/tivoo/test_tivoo_p4b6_acceptance.py`
- `.superpowers/sdd/2026-11-09-p4-ha-mcp-tool/p4b6-full-suite-final.log`
- `.superpowers/sdd/2026-11-09-p4-ha-mcp-tool/p4b6-tivoo-focused-final.log`
- `.superpowers/sdd/2026-11-09-p4-ha-mcp-tool/p4b6-p3-regression-final.log`
- `.superpowers/sdd/2026-11-09-p4-ha-mcp-tool/p4b6-entity-exposure-red.log`
- `.superpowers/sdd/2026-11-09-p4-ha-mcp-tool/p4b6-entity-exposure-final.log`
