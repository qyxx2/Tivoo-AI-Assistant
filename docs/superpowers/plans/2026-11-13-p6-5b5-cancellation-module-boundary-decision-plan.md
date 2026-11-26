# P6.5b5 取消链路汇总与模块边界决策计划

> **ARCHIVED / 历史轨迹（2026-11-26）**：本计划已退出活动开发，不再是 backlog、发布门禁或后续执行入口。`[x]` 仅表示已有实现、测试、报告或部署证据；未勾选项表示当时未执行、被后续架构替代，或因复现成本/发生概率不值得主动验收。若实际使用暴露问题，再建立专用分支与针对性计划处理。当前文档入口见 [文档地图](../../README.md)。


> 权威要求：`docs/superpowers/patches/2026-11-11-p6-5-ha-cancellation-preflight.patch.md` §3–§6。
> 本批是既有实测证据的汇总与架构决策；只更新文档，不实现修复。

**Goal:** 汇总 b1–b4 的真实 HA/P7A 生命周期证据，准确标记 PASS/GAP/BLOCKED，明确 P7/P8 后续模块的取消责任和阻塞条件。

**Scope / constraints**
- 只修改 b5 计划、b5 最终报告、README P6.5 状态索引、P6.5 patch 的执行状态/汇总链接及本计划的 SDD ledger。
- 不修改 HA Core、Tivoo、AstrBot、Sherpa/Wyoming 或 ESP32 生产代码；不新增测试夹具。
- 不部署/重启 NAS 服务，不刷写或连接 ESP32/麦克风/DAC。
- 区分本机 HA Core 2026.11.0 测试版本、fake AstrBot/Sherpa 端点和未重新核实的外部服务版本。
- 不把删除 ResultStream token、关闭 HTTP GET 或已有断连清理代码描述成已完成端到端取消。

## Task 1 — 汇总证据并记录后续模块边界
**Inputs**
- P6.5 patch §3–§6。
- b0–b4 报告及 b1–b4 实施计划。
- P3 Conversation 合同、STT/TTS 端到端规格、P7A Wyoming TTS 合同。
- 当前 P6 `AudioSessionManager` / transport 职责与 P7A TTS 请求取消测试。

**Deliverables**
- Create `docs/superpowers/reports/2026-11-11-ha-cancellation-preflight-report.md`。
- Update README 的 P6.5 状态索引，链接 b5 报告并说明前置验证完成但活动 TTS 取消存在 GAP。
- Create `.superpowers/sdd/2026-11-13-p6-5b5-cancellation-module-boundary-decision-plan/progress.md`。

**Report acceptance**
- 记录环境版本、测试双环境边界、b1–b4 关键事件时间线和实际命令/结果。
- 按对象列出创建者/owner、取消或关闭入口、实测退出状态和证据。
- 分别标记正常完成、TTS 前取消、活动 TTS Pipeline 取消、HTTP GET 单独断开的 PASS/GAP；不得把“复现 GAP 的测试通过”写成取消链路通过。
- 明确 HA TTSCache producer/text generator 脱离 Pipeline owner、HTTP consumer queue 残留的不同责任边界。
- 明确 P3 Stop 唯一 owner、P7A 每连接请求 owner、ESP32 最终音频输出 owner 和 Tivoo transport / MIC session 的边界。
- 指明 P7 非打断路径可继续；依赖活动 TTS 取消的完整 barge-in 验收与 P8 全链路收尾保持 BLOCKED，直到独立设计并验证 producer 的定向关闭。
- 对尚未通过活动 TCP EOF 触发验证的 P7A handler 清理保持证据限定。
- 完成 `git diff --check`、Markdown 链接目标检查和工作区范围检查。

**Expected:** b5 文档完成；生产逻辑不变；P6.5 前置诊断的结论是“已定位并记录 GAP”，不是“端到端取消通过”。

**Commit:** `docs(p6.5b5): record cancellation boundary decisions`（仅本批文档文件；不合并、不推送）。
