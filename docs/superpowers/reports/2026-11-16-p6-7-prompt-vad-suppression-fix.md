# P6.7 提示音专用人声检测 Gate 修复验收

- 日期：2026-11-16
- 分支：`feature/p6-7-audio-prompts`
- 基线：`68c0891`（AEC reference delay 已标定为 760 samples / 47.5 ms）
- 产品决策：仅提示音期间暂停人声检测；提示音声学结束后立即恢复。正常 TTS 播放中的 VAD/KWS 打断能力不得受影响。

## 实现

HA 沿用 `TTS_PLAY=0x30`，只增加向后兼容的可选布尔 `suppress_vad`。默认/省略为 false，只有 `PromptSoundPlayer` 对三条 ready prompt 置 true；普通 TTS payload 不带该字段。

ESP32 保持全局 `vad_mute_playback=false`。仅当前 request 的 `suppress_vad=true` 且取得真实 output owner 后：

- RX、AFE、AEC 和最终 TX→AEC reference 继续工作；
- runtime `disable_vad + reset_vad`；
- gate 期间暂停 `MIC_ACTIVITY` / `MIC_PCM` 向 HA 上送；若进入 gate 前已有 speech，只归零并至多发送一次 `speech_end`；
- 数字输出结束后继续保持 gate 到实测 TX→mic 声学延迟 760 samples / 47.5 ms 结束，实现向上取整 48 ms；
- 随后 `enable_vad + reset_vad`，恢复正常 MIC/VAD 路径。

因此语音若完全落在约 0.7–0.9 秒提示音窗口内可能被忽略，这是明确的 workaround 取舍，不再声称提示音期间具备双讲识别。

## 自动化证据

- ESP32 audio producer / protocol host：`3 passed`。覆盖已有 MIC session 被 gate 归零且不发 PCM、gate 后下一次 `speech_start`/PCM 恢复，以及 `suppress_vad` 可选 bool 的解析与非法类型拒绝。
- HA 完整相关回归：`379 passed, 180 warnings`。
- 固件完整构建 PASS；AEC delay 保持 760 samples。

## 实机证据

最终实现的 `ready_01.mp3` 对照：

- 提示音请求 `suppress_vad=true`：gate 内 `0 VAD speech_start / 0 MIC_ACTIVITY / 0 MIC_PCM`；RX/AFE/AEC 计数正常。
- gate 结束后，同一音频立即作为普通 TTS（无 `suppress_vad`）播放：再次出现 `VAD speech_start`、`MIC_ACTIVITY speech_start` 和 103 个 MIC PCM 帧。
- 因此 suppression 没有全局作用于普通 TTS，原正常 TTS 播放期间的 VAD/KWS 打断入口仍存在。

同一 prompt gate + 48 ms 声学尾部的前序设备复测中，`ready_02.mp3`、`ready_03.mp3` 均为 0 自触发。最终版本只进一步将 gate 内 MIC_PCM 从继续上传改为暂停上传，不改变 VAD disable/enable 与 48 ms 恢复时序。后续重复直连测试受 ESP32 唯一 7778 客户端及 HA 自动重连的测试环境时序干扰；HELLO 前 EOF/connect timeout 不作为功能失败。

## 结论

P6.7 提示音自触发按新的产品取舍关闭：**提示音期间故意不做人声检测，提示音声学结束后恢复；正常 TTS 不进入该 gate，原有打断能力保留。**

这不把 P6.5 的 AEC 双讲能力标为 PASS；P65-A13 的 AEC 声学能力继续按其自身证据独立记录。
