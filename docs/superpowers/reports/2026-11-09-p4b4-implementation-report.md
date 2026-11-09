# P4b4 实施报告：图片/GIF 文件处理与媒体 Tools

日期：2026-11-09
分支：`feature/p4-ha-mcp-server`
批次基线：`5f02666738878b4698645334b3570fec6bfcaba3`

## 1. 范围与交付

本批次仅完成 P4b4。新增 HA Services：

- `tivoo.show_image`：读取 `media_directory` 内相对路径文件，支持 PNG、JPEG/JPG、GIF。
- `tivoo.play_animation`：读取同一目录内的 GIF 文件。

新增仅供 HA Assist API 使用的 Tools：

- `tivoo__ShowImage`
- `tivoo__PlayAnimation`

两个 Tool 都只接受必需的 `file: string` 和可选的 `time: integer`，并委派至同名 HA Service。它们均标记为写操作、`idempotent=False`。现有 P4b1 `media_directory` 配置（默认 `pixelart`，经 `hass.config.path()` 解析）作为唯一媒体根目录。

未实现 AstrBot 文件上传/复制协议、URL/asset ID、ESP32/TCP/SPP、设备传输、P4b5 Persona 配置或 P4b6 全链路验收。

## 2. 实现说明

- 新增 `media.py`，将路径解析与图像解码集中为共享实现。使用 `realpath()` 和 `commonpath()` 验证真实路径仍位于媒体根目录内；拒绝 URL（包括格式损坏的 URL）、绝对路径、Windows 驱动器路径、路径穿越、逃逸 symlink、目录、缺失文件和不可读文件。
- 依据项目现有 Tivoo SDK 的纯图像处理语义，使用 Pillow 将 RGBA 图像缩放到 16×16，Lanczos 重采样；alpha 小于 32 的像素变为黑色，其余保留 RGB。没有导入 SDK 的 Bluetooth Bridge、SPP 或 CLI 依赖。
- GIF 逐帧解码。未提供 `time` 时读取每帧内嵌毫秒时长；提供时严格限制为整数 0–65535，并覆盖每一帧。布尔值、浮点数、字符串不被当作整数接受。
- `PlayAnimation` 只接受 GIF；`ShowImage` 接受 PNG/JPEG/GIF。两个服务使用同一文件解析与帧处理函数，Pillow I/O 和解码在 HA executor 线程执行，避免同步解帧阻塞事件循环。
- HA Service 注册与卸载生命周期同步；Service 和 Tool 均不宣称硬件已显示或播放成功，成功仅代表 HA 服务层完成当前职责。
- 更新 `services.yaml`、上游复用说明及既有 Service/Tool 列表测试。

## 3. TDD 与测试结果

RED/GREEN 记录保存在本批次 SDD 目录：

- `p4b4-red-2.log`：新增媒体与 Tool 测试先于实现运行，相关用例因媒体 Service/Tool 尚未注册而失败。
- `p4b4-schema-red.log`：严格 MCP 参数合同测试先于 schema 修正运行，因浮点/布尔/额外帧载荷仍被接受而失败；修正后该测试通过。
- `p4b4-malformed-url-red.log`：损坏 URL 用例先于修正运行，复现 URL 解析异常未转成 HA 媒体路径错误；随后增加统一拒绝处理并通过该回归用例。
- `p4b4-windows-root-red.log`：带根分隔符但无盘符的 Windows 路径先于修正运行，复现文件名可能被解释为媒体目录内的相对文件；随后拒绝 `PureWindowsPath.root` 并通过回归用例。
- P4b4 媒体与 Tool 聚焦测试（executor 与 Windows rooted path 最终实现）：**29 passed**，5 warnings。
- 完整 Tivoo 集成测试：**105 passed**，5 warnings。
- 全仓 HA 测试：**197 passed**，63 warnings，exit 0。Warnings 属于现有 HA/aiohttp/backoff 测试依赖 deprecation/NotAppKey 类别；未出现失败项。

测试覆盖 PNG/JPEG/GIF 解码、16×16 RGB 帧、透明像素、GIF 多帧与内嵌时长、显式时长覆盖及边界、非法时长、路径穿越/绝对路径/Windows 盘符及 rooted 路径/URL/损坏 URL/symlink 逃逸/目录/缺失/损坏文件、GIF-only 限制、Assist Tool 注册与 Service 委派、Service 错误传播和禁止额外帧/palette 入参。

## 4. 静态验证

以下检查均通过：

- Ruff 全仓检查；排除两个未修改的上游预设工厂文件（`presets.py`、`emotion_presets.py`），与 P4b3 的上游源文件处理规则保持一致。
- 本批次修改的 Python 文件 Ruff format check。
- `python -m compileall -q homeassistant tests`。
- `python -m pip check`：No broken requirements found。
- `manifest.json` JSON 与 `services.yaml` YAML 解析；两项媒体 Service 的字段与时长边界检查。
- `git diff --check`。

## 5. 收尾审查

- 按 P4b4 §8 检查了路径边界、格式、GIF timing、Tool 参数和 Service 委派。未发现 Critical/Important 问题。
- 当前会话未提供独立 reviewer/subagent 派发能力，因此由作者按只读审查模板自审。
- P3 业务实现、P4b1–P4b3 服务逻辑未修改；仅更新因新 Tool/Service 注册而过时的测试清单断言。
- 没有连接 NAS 或 Tivoo 实机执行测试；本批只验收 HA 集成行为和语义 Adapter 交付。物理设备执行仍需后续传输批次完成。
- 本地提交按批次计划执行；不 push、不 merge。
