# Tivoo AI Assistant 文档地图

本页是 2026-11-26 起的文档入口。仓库此前采用 P3/P4/P5/P6/P6.x/P7A/P6.8 分批计划推进；当前架构已经稳定进入正常迭代，因此旧计划统一归档。

## 阅读优先级

遇到实现、部署或历史文档相互冲突时，按以下顺序判断：

1. **当前源码和实际部署证据**。
2. 最近的当前架构验收/故障修复报告。
3. 当前仍适用的规格和合同。
4. 历史计划、旧规格和早期报告。

历史计划里的未勾选 checkbox 不再自动构成待办。

## 当前架构入口

- [项目 README](../README.md)：当前架构、组件、开发规则和非阻塞边界。
- [P6.8 本次构建摘要与 HA 决策](superpowers/reports/2026-11-25-p68-build-summary-and-ha-decisions.md)：当前流式播放/SRC/S3 CPU 决策。
- [P6.8 B8.8 验收记录](superpowers/reports/2026-11-25-p6-8-b8-8-acceptance.md)：Sherpa STT → HA local-first → Qwen text fallback 的最新验收边界。
- [Qwen Realtime 合同矩阵](superpowers/specs/2026-11-22-p6-8-b8-1-qwen-realtime-contract-matrix.md)：Qwen bridge、owner、终态与 follow-up 语义。
- [B8.8 local-first 合同矩阵](superpowers/specs/2026-11-25-p6-8-b8-8-stt-local-intent-qwen-text-contract-matrix.md)：当前 STT/local/Qwen 路由合同。
- [P6.8 音频/AFE 设计](superpowers/specs/2026-11-18-p6-8-b0-3-audio-afe-design.md)：S3 双麦、AEC/VAD/WakeNet 的设计来源。
- [P6.8 生命周期/显示设计](superpowers/specs/2026-11-18-p6-8-b0-5-lifecycle-display-design.md)：generation、播放 owner、表情与 follow-up 的设计来源。
- [Tivoo 可旋转底座 CAD](../tivoo-rotating-base/README.md)：当前 136 × 114 mm 级圆角底座、108 mm 旋转盘和内部器件布局的参数化建模入口；V1 仍是概念/布局模型，不是打印定稿。

### 当前运行时仍使用的历史组件

services/sherpa_wyoming/ 的 **device-endpoint STT** 仍是当前 B8.8 路径的一部分。因此 P7A 的“计划”是历史资料，但 Sherpa 服务本身不是废弃组件。

homeassistant/custom_components/astrbot/ 与相关 P3/P4 资料保留用于历史追溯；当前主要语音链不以 AstrBot 作为 AI 主体。

## 计划归档

[superpowers/plans/](superpowers/plans/) 下截至 2026-11-26 的所有计划统一归档。归档策略：

- [x]：后来能够由实现提交、测试、验收报告或生产证据确认完成。
- [ ]：历史上没有执行/没有完整验收，或已被后续架构替代。
- [ ] **不是当前 backlog**。
- 不再为了关闭历史计划而主动进行极端故障注入、长时间矩阵测试、旧架构人工验收。
- 实际使用出现故障时，以真实问题建立专用分支和新的针对性计划。

归档计划索引见 [plans/README.md](superpowers/plans/README.md)。

## 历史文档分区

### AstrBot / P3 / P4

以下内容描述早期 HA Conversation Agent、AstrBot SSE/Stop、Persona 和 AstrBot MCP 方案，已经退出当前主架构：

- superpowers/specs/2026-11-09-p3-astrbot-conversation-contract-matrix.md
- superpowers/specs/2026-11-09-p4-ha-mcp-tool-contract-matrix.md
- superpowers/specs/2026-11-13-astrbot-http-sse-inference-cancellation-spec.md
- 对应 2026-11-09 / 2026-11-10 AstrBot/P4 reports

这些文件不删除，也不再要求补做 HA 重启、24h session、API Key 轮换、Persona 完整授权和响应丢失故障注入。

### P5 / P6

P5/P6 记录 Classic ESP32 最小固件、7777/7778、SPP、HTTP 资源等基础能力。其中大量协议和工具能力被当前双板实现继承。

推荐历史证据：

- superpowers/reports/2026-11-12-p5-memory-bond-artifact-closeout.md
- superpowers/reports/2026-11-12-p6-acceptance-report.md

第二台 Tivoo、JTAG 软件重启、AP 人工断电等未执行项保留原记录，不再是当前门禁。

### P6.5 / P6.6 / P6.7

这些阶段建立了音频 owner、取消、表情状态、screen gate 和提示音等基础语义。旧 NAS KWS、AstrBot phase、HTTP ready prompt 等具体拓扑后来被 P6.8 替换。

实现逻辑仍可能被当前代码继承，计划本身不再继续执行。

### P7A Sherpa Wyoming

P7A C01–C39 已完成验收，历史计划中早期遗漏的已完成 checkbox 已回填。

当前架构仍使用 Sherpa device-endpoint STT；不要根据旧 Qwen migration 计划中“移除 Sherpa”的描述直接清理服务。是否保留其它 KWS/TTS Provider 由实际消费者决定。

### P6.8

P6.8 的路线、B1–B10、R01–R11、Qwen migration、onset/far-field/streaming、B8.8 等计划全部作为演进轨迹保存。

其中最重要的当前结果已经体现在源码和最新报告中。原 B9/B10 不再自动执行，也不要求逐条核销 49 + 192 + 19 条历史合同。

## Reports 与 evidence

superpowers/reports/ 不作为“待办列表”，而是事实证据库：

- acceptance：说明某批实际通过/未通过的边界。
- investigation / analysis：记录故障定位过程。
- fix / deployment：记录修复、构建、哈希和部署。
- reports/evidence/：原始日志、JSON、测量和可复核材料。

需要调查回归时优先从最近报告定位对应 evidence，而不是从旧计划重新执行整批任务。

## Specs

superpowers/specs/ 同时包含当前仍有价值的合同和历史架构合同。规格不会因为计划归档而删除。

当前开发若修改协议/owner/音频格式/生命周期，应先判断对应规格是否仍描述当前实现；若已被后续架构替代，则创建新的小型规格或直接在新功能文档中说明，不去改写历史事实。

## 后续新增文档约定

- 普通小修复：提交 + 测试 + 必要的简短 report 即可，不要求建立长期计划。
- 可复现 bug：建立专用修复分支，以故障证据和最小复现为入口。
- 大功能/跨模块迁移：需要时再创建新的活动 plan。
- 新 plan 必须明确基于哪个当前提交；完成后同样归档，不让历史计划长期充当 backlog。
