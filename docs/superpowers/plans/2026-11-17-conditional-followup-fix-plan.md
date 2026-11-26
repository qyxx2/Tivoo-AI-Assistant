# Tivoo Conditional Follow-up Fix Implementation Plan

> **ARCHIVED / 历史轨迹（2026-11-26）**：本计划已退出活动开发，不再是 backlog、发布门禁或后续执行入口。`[x]` 仅表示已有实现、测试、报告或部署证据；未勾选项表示当时未执行、被后续架构替代，或因复现成本/发生概率不值得主动验收。若实际使用暴露问题，再建立专用分支与针对性计划处理。当前文档入口见 [文档地图](../../README.md)。


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 让 Tivoo 只在 HA 明确返回 `continue_conversation=true` 时进入免唤醒连续对话。

**Architecture:** `AudioSessionCoordinator` 在当前 turn 上保存 `INTENT_END.intent_output.continue_conversation`。TTS 真实完成和无 TTS 的有效结束都调用同一条件式结束逻辑：true 打开现有 follow-up；false 停止当前 MIC session。

**Tech Stack:** Python 3.14, Home Assistant Core 2026.11.0, pytest.

**Spec:** `docs/superpowers/specs/2026-11-17-conditional-followup-design.md`

## Global Constraints
- 不修改 ESP32 VAD/AEC 参数。
- 不修改首次唤醒、确认打断和 side-KWS 逻辑。
- 不以缩短超时掩盖根因。
- 未知/缺失续聊字段按 false 处理。

## Review Focus
- 普通陈述回答完成后不得发送 follow-up prompt。
- 普通陈述回答完成后当前 MIC session 必须结束。
- 明确 `continue_conversation=true` 时仍进入 8 秒 follow-up。
- 无 TTS 的有效回答也必须遵循同一续聊判据。
- 旧/迟到 playback ID 不得改变当前 turn 的续聊状态。

### Task 1: 用失败测试固定根因并实现条件式 follow-up

**Files:**
- Modify: `homeassistant/custom_components/tivoo/assist_satellite.py`
- Modify: `tests/homeassistant/custom_components/tivoo/test_assist_satellite.py`

**Interfaces:**
- Consumes: `PipelineEventType.INTENT_END` 的 `event.data["intent_output"]["continue_conversation"]`
- Produces: 当前 `_Turn` 的续聊判据；TTS 完成后的条件式 follow-up/结束会话

- [x] 写测试：false 时 TTS completed 后不 follow-up、不发提示音、停止 session。
- [x] 运行该测试并确认 RED，失败原因是当前无条件 `_open_followup()`。
- [x] 写测试：true 时保持原 8 秒 follow-up。
- [x] 最小实现：记录布尔值并统一决定 follow-up 或 stop。
- [x] 跑上述测试转 GREEN。
- [x] 跑 Tivoo/AstrBot 聚焦回归和静态检查。

### Task 2: 生产部署与运行验证

**Files:** 无额外生产代码。

- [x] 备份生产 Tivoo/AstrBot 文件。
- [x] 同步修复后的相关自定义组件并在 HA 容器内 compileall。
- [x] 重启 Home Assistant。
- [x] 核对生产 SHA256、HA running 状态及启动错误。
- [x] 保留当前分支改动，不推送远端。
