# Tivoo Phase-Specific Prompt Assets Design

## Intent

让首次唤醒/确认打断继续使用现有三条 ready 提示音，而只有真正进入免唤醒连续对话时播放独立的 follow-up 提示音。连续对话判据继续完全沿用 HA 当前 `continue_conversation` 结果；AstrBot/HA 以回答末尾问号决定该值，本次不改变。

## Current facts

- `AudioSessionCoordinator._request_prompt(turn, phase)` 已真实区分 `ready`、`wake`、`confirmed`、`followup`。
- `_open_followup()` 现在只在当前 turn 的 `INTENT_END.intent_output.continue_conversation is True` 时进入，并调用 `_request_prompt(..., "followup")`。
- `PromptSoundPlayer` 当前忽略 phase，所有入口都从 `ready_01.mp3..ready_03.mp3` 选择。
- 提示音使用现有唯一播放 owner、独立 playback_id、`suppress_vad=true`、定向 AUDIO_STOP 和真实 TTS 互斥；这些都不改变。
- ready 素材由生产 Sherpa Wyoming Matcha Baker + Vocos、voice/sid 0、speed 1.0 生成；再加约 120 ms 前静音、180 ms 后静音并转 32 kHz mono MP3。
- 当前相邻不重复是全局单文件名状态。若 follow-up 只有一个素材而原样复用该规则，第二次 follow-up 会被静默跳过。

## Chosen approach

方案 A：保留一个 `PromptSoundPlayer`，让 `phase` 参与素材选择。

- `ready` / `wake` / `confirmed` -> `READY_PROMPT_FILENAMES = ready_01..03`
- `followup` -> `FOLLOWUP_PROMPT_FILENAMES = followup_01.mp3`
- ready 池保持现有“相邻同文件不重复”；即使只剩一个 ready 文件，也继续按旧合同不重复。
- follow-up 池首期固定一个文件，允许跨 generation 重复播放。
- `build_internal_prompt_url` 只接受上述固定文件并继续走 HA `/local/tivoo/prompts/`。
- `async_request(generation, phase)` 和 `has_available_assets(phase)` 要求显式 phase；未知 phase 视为编程错误，不回退到 ready。
- `AudioSessionCoordinator` 只负责传递已有 phase，不新增任何文本/语义判断。

## Follow-up asset

首期文件固定为 `followup_01.mp3`。内容采用短促、与 ready 三句可听区分的“嗯？”，由当前生产 Sherpa Wyoming 的同一 Matcha Baker/Vocos 模型一次性生成。只做与 ready 素材相同的前后静音和 32 kHz mono MP3 适配，不改变音色、速度或响度处理。文件可日后直接替换，不需要改代码。

## Non-goals

- 不改变 HA 末尾问号 -> `continue_conversation` 的现行规则。
- 不新增 LLM 语义分类。
- 不改变 8 秒 follow-up 计时起点。
- 不改变 ESP32、AEC/VAD、`suppress_vad` 或音频协议。
- 不新增第二个 prompt player、混音或第二播放 owner。
- 不新增配置 UI/动态素材管理。

## Required behavior

1. 普通回答 `continue_conversation=false`：不进入 follow-up，永远不会请求 `followup_01.mp3`。
2. `continue_conversation=true`：真实回答完成后进入现有 follow-up，并只请求 `followup_01.mp3`。
3. 连续两次真实 follow-up：两次都必须播放 `followup_01.mp3`。
4. ready/confirmed/wake 仍只能使用 `ready_01..03`，并保持相邻不重复。
5. follow-up 素材缺失或发送失败仍沿用现有静默降级：连续对话窗口本身继续存在，不因提示音失败而失败。
