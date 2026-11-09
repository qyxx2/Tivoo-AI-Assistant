# P4b2 实施报告：HA LLM Tools 平台与 StopCountdown Tool

- 日期：2026-11-09
- 分支：`feature/p4-ha-mcp-server`
- 批次基线：`f4a2fdf3f4fbc6f9a1649087195d55047efda33e`
- 执行环境：Remote Desktop Commander 连接的 Ubuntu 开发机
- 结果：P4b2 实现与本地自动化验收完成；未执行 push 或 merge

## 实现内容

### HA LLM Tools 平台

- 新增 `homeassistant/custom_components/tivoo/llm.py`，按 HA Core 2026.11.0 原生 `LazyIntegrationPlatforms` 约定导出同步 `async_get_tools(hass, llm_context, api_id)` callback。
- 仅当 `api_id == LLM_API_ASSIST` 且至少一个 Tivoo Config Entry 处于 loaded 状态时返回项目工具；其他 API 或集成未加载时返回 `None`。
- 不将该平台加入实体 `PLATFORMS`，不创建独立 MCP Server/Client。

### StopCountdown Tool

- 新增 `tivoo__StopCountdown`，继承 HA `Tool`，输入 Schema 为无参数 `probatio.Schema({})`，显式声明 `integration="tivoo"`。
- 显式设置 annotations：`read_only=False`、`destructive=False`、`idempotent=True`、`open_world=False`。
- 执行时只调用既有 `tivoo.stop_countdown` HA Service，传入空字典、`blocking=True` 和原始 `llm_context.context`；不访问命令适配器、不拼帧、不连接 ESP32。
- 成功返回 JSON object `{"status":"service_completed"}`。工具说明明确这只代表 HA Service 调用完成，不代表 Tivoo 设备已确认执行。
- 非空参数被明确拒绝；HA Service 缺失或适配器不可用时保留 HA 异常，不包装成成功 ToolResult。
- Assist API 中普通 HA 用户能够发现/使用该工具；HA 管理 API 不注册 Tivoo Tool，管理 API 自身仍遵循 HA 管理员权限要求。

## 测试与验证

先写测试并观察未实现平台时的预期失败，再新增最小实现。RED / GREEN 记录保存在本批 SDD 工作区：

| 阶段 | 命令 | 结果 |
|---|---|---|
| RED | `./scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_tivoo_llm.py` | **5 failed**；工具缺失导致 Assist API 未发现 Tivoo Tool |
| GREEN | 同一聚焦命令 | **5 passed** |
| Tivoo 聚焦回归 | `./scripts/test-ha.sh tests/homeassistant/custom_components/tivoo` | **28 passed** |
| 完整 HA / P3 回归 | `./scripts/test-ha.sh` | **120 passed**，包含原 P3 测试 |
| Ruff | `ruff check homeassistant tests` | passed |
| Ruff format | 本批两个新增 Python 文件的 `ruff format --check` | passed |
| Compile | `python -m compileall -q homeassistant tests` | passed |
| Dependencies | `python -m pip check` | No broken requirements found |
| Diff | `git diff --check` | passed |

完整测试的 63 条 warning 与 P4b1 基线相同，来自 HA/aiohttp/backoff 测试依赖的弃用和 AppKey 提示；无测试失败。

## 范围与限制

本批只新增 HA LLM Tools 平台、StopCountdown Tool 和对应测试。没有修改 P3 Conversation Agent、P4b1 服务实现、AstrBot 生产配置、README、NAS 文件、ESP32 固件或 TCP/SPP 通信代码。

尚未在本批连接生产 AstrBot/MCP 服务进行运行时配置验收；AstrBot MCP Server/Persona 配置属于 P4b5。默认生产设备适配器仍按 P4b1 约定报告 unavailable，真实 Tivoo 设备回执属于 P5/P6，本报告不声称已完成硬件控制。

## 收尾

- P4b2 的本地验收证据齐备，后续 P4b3/P4b4 可以在本分支继续。
- 仅本地提交到 `feature/p4-ha-mcp-server`；不 push、不 merge。
