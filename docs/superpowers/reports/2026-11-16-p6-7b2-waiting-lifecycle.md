# P6.7b2 三个等待入口与无阻塞收音

- 日期：2026-11-16
- 分支：`feature/p6-7-audio-prompts`
- 基线：`2f076d0`（P6.7b1）
- 范围：仅 P6.7b2。未部署 NAS，未刷写 ESP32，未进行真实 Tivoo 出声/AEC 声学验收；P6.7b3 与 P65-A13 仍待现场证据。

## 实现

`assist_satellite.py` 将 b1 的 `PromptSoundPlayer` 接入实际语音生命周期：

- Satellite 加载时创建唯一 `PromptSoundPlayer`；真实 TTS 的 `PipelineTtsEvents` 复用 b1 `async_yield_to_tts()` seam，仍由正常 TTS 优先占用物理播放槽。
- 首次有效 `WAKE_WORD_END` 在原 5 秒 `command_timeout` 已启动后异步请求一次提示音；重复 WAKE_WORD_END、普通 STT_START 与候选 VAD 不会重复触发。
- `_open_followup()` 在原 8 秒 `followup_timeout` 已启动后异步请求一次提示音；prompt 自身 completed/stopped/failed 先由 prompt owner 按 playback_id 消费，不会进入正常 TTS、P6.6 speaking 或再次打开 follow-up。
- side-KWS confirmed replacement turn 仍先完成旧 turn 的定向 TTS stop / caller / TTS owner 清理；新 turn 真正进入 STT_START 后才请求提示音。MIC handoff subscription 在等待旧轮清理期间已建立，因此不丢已进入 ingress 的 PCM。
- `STT_VAD_START` 和 follow-up `speech_start` 优先用户输入：先使待发 prompt generation 失效，再仅对该 prompt generation 执行定向取消；不对正常 TTS 发 VAD-only stop。
- prompt 请求使用 turn context + phase 作为 generation；异步 task 下发前再次核对当前 generation 与 turn。命令若先开始或 turn 已替换，则旧请求直接丢弃；旧 generation 迟到不会补播。
- session end / unload 同样只取消当前 prompt owner，并在 unload 时等待本组件创建的 prompt tasks 收口。
- 未修改 ESP32 协议、MIC/AEC 路径、5 秒/8 秒计时起点、AstrBot/ChatLog、P6.6 screen power/priority，也未再修改 b1 已完成的 `audio_resource.py` seam。

## RED → GREEN

先新增四个行为测试并在未接线代码上运行；四项均失败，首次唤醒用例明确表现为 `async_send_tts_play.await_count == 0`，证明测试覆盖的是缺失的 b2 行为而非既有行为。

GREEN 聚焦验证：

```text
./scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_assist_satellite.py -q \
  -k 'wake_prompt or prompted_followup or confirmed_turn_waits'
4 passed, 23 deselected
```

覆盖：
1. 首次 KWS 命中只提示一次；命令开始只定向停止 prompt；prompt 终态不产生 follow-up。
2. prompt 播放/完成不移动首次命令 5 秒 watchdog。
3. 真实 TTS completed 打开一次带 prompt 的 8 秒 follow-up；follow-up speech_start 立即进入免 KWS STT，不卡在提示音结束。
4. confirmed interruption 中旧真实 TTS 先定向停止；模拟旧轮清理延迟 6 秒期间不抢占 DAC；清理后新 STT 收到预先进入 ingress 的 handoff PCM，再请求 prompt。

## 回归与异常复核

第一次完整交叉回归结果为 `378 passed, 1 failed`，唯一失败是既有
`test_normal_pipeline_completion_closes_all_owned_streams[minimum-command]`
中的 P7A trace `task_cancelled` 时序断言。按 systematic-debugging 流程单独原样重跑该用例得到 `1 passed`；本次修改前的基线也包含该文件且通过。没有据此修改生产代码。

随后重新执行完整门禁：

```text
./scripts/test-ha.sh tests/homeassistant/custom_components/tivoo \
  tests/homeassistant/test_assist_pipeline_tts_cancellation.py -q
379 passed, 180 warnings
```

因此未观察到可稳定复现的 P6.7b2 回归。

静态检查：
- `ruff check`：PASS
- `ruff format --check`：PASS
- `git diff --check`：PASS

## b2 合同结果

| 合同 | b2 结果 | 证据 |
| --- | --- | --- |
| PR-C01 | PASS | 首次 wake、confirmed、新 follow-up 三个显式入口；重复 wake/普通 STT 不重复发声 |
| PR-C02 | PASS | WAKE_WORD_END 后原 5 秒 watchdog 不因 prompt 完成而移动 |
| PR-C03 | PASS（HA 软件时序） | 旧 TTS/turn 清理优先；延迟 6 秒测试；新 STT 后 prompt；handoff PCM 保留 |
| PR-C04 | PASS | 只有真实 TTS completed / 无 TTS 正常路径打开 follow-up；prompt terminal state 被 owner 截获 |
| PR-C05 | PASS | follow-up speech_start 立即启动 STT；prompt 与 STT 互不等待 |
| PR-C06 | PASS（HA 软件边界） | 未增加 MIC ingress 屏蔽/暂停/等待 prompt；真实 RX/AFE/AEC 声学部分仍属于 b3 |
| PR-C13 | PASS | prompt playback_id 不进入正常 TTS/P6.6 speaking/follow-up dispatcher |
| PR-C14 | PASS | 当前 generation + turn 身份使重复/过期待发请求失效；旧 playback state 按 ID 隔离 |
| PR-C15 | PASS（HA 软件） | b1 TTS yield seam 已接入真实 Satellite；confirmed 路径先清旧 TTS，再允许 prompt |
| PR-C16 | PASS | STT_VAD_START/follow-up speech_start 取消待发或定向停止 prompt 自身，不停正常回答 |
| PR-C19 | PASS（HA 软件） | prompt owner 的发送/stop/释放失败继续静默降级；生命周期不等待 prompt |
| PR-C20 | PASS | P6.5/P6.6/Tivoo 全目录与 Pipeline cancellation 回归通过；未接 AstrBot/ChatLog/新对话入口 |

## 边界

P6.7b2 至此只具备端到端软件生命周期。没有把自动化测试冒充真实声学证据：NAS 静态文件生产部署、ESP32 HTTP 解码/Tivoo 实际出声、提示音期间真人讲话首字/AEC/VAD/STT、不同距离与音量、RX/reference 指标以及 P65-A13 均留给 P6.7b3。P6.7 整体尚不能标记完成。
