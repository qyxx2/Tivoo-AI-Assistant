# Tivoo 条件式连续对话修复设计

## 目的
修复普通语音命令回答完成后无条件播放“我在/在的/你说”并开启 8 秒免唤醒监听，导致环境人声再次触发 STT/LLM 的问题。

## 根因
HA Core 2026.11 在 `INTENT_END.intent_output.continue_conversation` 已提供本轮是否需要续聊的权威布尔值；当前 Tivoo `AudioSessionCoordinator` 不读取该字段，而是在任何正常 TTS `completed` 后无条件 `_open_followup()`。P6.7 又在 `_open_followup()` 中无条件请求 follow-up 提示音，因此普通陈述也会再次播“我在”并监听环境人声。

## 方案比较
1. 调低 ESP32 全局 VAD：会同时降低首次唤醒和正常命令灵敏度，不能区分电视对白与用户语音，不采用。
2. 缩短 8 秒窗口：只能降低误触概率，普通回答后仍错误进入 follow-up，不采用。
3. 使用 HA `continue_conversation`：在 `INTENT_END` 记录本轮权威续聊结果；真实 TTS 完成或无 TTS 的有效轮次结束时，仅当该值为 true 才打开 follow-up。普通回答直接结束 MIC session。采用。

## 行为
- `continue_conversation=false`：正常回答播放完后不播放 follow-up 提示音，不进入 8 秒窗口，结束当前 MIC session；下一轮必须重新说唤醒词。
- `continue_conversation=true`：保留现有 8 秒 follow-up 及现有提示音/监听行为。
- 首次唤醒提示音、确认打断提示音、side-KWS、TTS 播放中打断、AEC/VAD 参数均不改。
- 未收到合法 `INTENT_END` 续聊字段时默认 false，避免异常路径误进入连续对话。

## 验证
先增加失败测试复现普通回答 `continue_conversation=false` 仍进入 follow-up；再实现最小修复。另保留正向测试证明 `true` 时仍能续聊。最后跑 Tivoo/AstrBot 聚焦回归、完整 HA 测试、静态检查并部署生产。
