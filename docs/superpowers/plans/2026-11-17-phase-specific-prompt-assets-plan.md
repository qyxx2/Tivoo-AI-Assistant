# Tivoo Phase-Specific Prompt Assets Implementation Plan

> **ARCHIVED / 历史轨迹（2026-11-26）**：本计划已退出活动开发，不再是 backlog、发布门禁或后续执行入口。`[x]` 仅表示已有实现、测试、报告或部署证据；未勾选项表示当时未执行、被后续架构替代，或因复现成本/发生概率不值得主动验收。若实际使用暴露问题，再建立专用分支与针对性计划处理。当前文档入口见 [文档地图](../../README.md)。


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Tivoo 的连续对话只播放独立 `followup_01.mp3`，首次/确认提示音继续使用现有 ready 素材池。

**Architecture:** 继续由单个 `PromptSoundPlayer` 拥有提示音播放槽，只把已有 phase 传入播放器用于固定素材池选择。ready 池保留相邻不重复；单文件 follow-up 池明确允许重复。Conversation 续聊判据、ESP32 和音频协议均不修改。

**Tech Stack:** Python 3.14, Home Assistant 2026.11, pytest, FFmpeg, production Sherpa Wyoming Matcha Baker/Vocos.

**Spec:** `docs/superpowers/specs/2026-11-17-phase-specific-prompt-assets-design.md`

## Global Constraints

- 不改变 `continue_conversation` 的末尾问号规则。
- 不改变 8 秒 follow-up 时序。
- 不修改 ESP32/AEC/VAD/音频协议。
- 只保留一个 `PromptSoundPlayer` 作为提示音 owner。
- follow-up 素材必须由当前生产 Sherpa Wyoming 同一 TTS 模型生成。

## Review Focus

- 第二次连续 follow-up 不能因单素材相邻去重而静默不播。
- ready/confirmed/wake 不能误用 follow-up 素材。
- follow-up 不能回退到 ready 素材。
- 缺失 follow-up 素材不能破坏 8 秒连续对话状态。
- 真实 TTS 与提示音的 playback owner/ID 路由不能变化。

---

### Task 1: Phase-aware prompt selection

**Files:**
- Modify: `homeassistant/custom_components/tivoo/prompt_audio.py`
- Modify: `homeassistant/custom_components/tivoo/assist_satellite.py`
- Modify: `tests/homeassistant/custom_components/tivoo/test_prompt_audio.py`
- Modify: `tests/homeassistant/custom_components/tivoo/test_assist_satellite.py`

**Interfaces:**
- Consumes: coordinator phase strings `ready|wake|confirmed|followup`
- Produces: `PromptSoundPlayer.async_request(generation, phase)`, `has_available_assets(phase)`

- [x] 写 RED：followup 只能选择 `followup_01.mp3`，且连续两个 generation 都能播放同一单素材。
- [x] 写 RED：ready 池仍保持相邻不重复；未知 phase 不回退。
- [x] 写 RED：Satellite 真实 `continue_conversation=true` 路径最终下发 follow-up 专属 URL。
- [x] 运行聚焦测试，确认失败原因是当前播放器忽略 phase。
- [x] 最小修改播放器和 coordinator 传参。
- [x] 运行聚焦测试转 GREEN。

### Task 2: Production-matched follow-up asset

**Files:**
- Create: `homeassistant/prompt_assets/followup_01.mp3`
- Modify: `tests/homeassistant/custom_components/tivoo/test_prompt_assets.py`
- Modify: P6.7 prompt spec/contract documentation as required

**Interfaces:**
- Produces: `/local/tivoo/prompts/followup_01.mp3`, audio/mpeg, 32 kHz mono

- [x] 先扩展资产测试要求 `followup_01.mp3`，运行并看到缺文件 RED。
- [x] 通过 NAS 正在运行的生产 Sherpa Wyoming 合成“嗯？”原始 22.05 kHz mono PCM。
- [x] 仅加入约 120 ms 前静音和 180 ms 后静音，转为 32 kHz mono MP3。
- [x] 跑资产元数据、头尾静音、真实 HA /local 测试转 GREEN。

### Task 3: Verification and production deployment

**Files:** no additional product code.

- [x] 跑完整 `tests/homeassistant`、独立 Sherpa suite、Ruff/format/diff 检查。
- [x] 自审完整 diff，重点核对 single-owner、迟到 playback ID 和 phase 生命周期。
- [x] 本地提交，不推远端。
- [x] 备份生产 HA prompt code/assets，同步代码和 `followup_01.mp3`。
- [x] 容器内 compileall、重启 HA、核对哈希和启动日志。
- [x] 不主动发声做声学验收；只做无声 HTTP/文件可访问验证。
