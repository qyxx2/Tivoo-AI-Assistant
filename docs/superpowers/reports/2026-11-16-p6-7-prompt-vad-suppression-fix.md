# P6.7 提示音专用人声检测 Gate 修复验收

- 日期：2026-11-16
- 分支：`feature/p6-7-audio-prompts`
- 实现提交：`9a73d03`（`fix(p6.7): gate mic detection during ready prompts`）
- 基线：`68c0891`（AEC reference delay 已标定为 760 samples / 47.5 ms）
- 产品取舍：仅三条 ready prompt 的声学播放窗口暂停人声检测与 MIC 上送；提示音结束并覆盖已标定声学尾部后立即恢复。普通 TTS 的 VAD/KWS 打断能力保持原行为。

## 1. 为什么不采用单纯降音量

先在不改生产素材的条件下做了临时衰减实测。原始 0 dB 与 -3 dB 三条均可复现自触发；更低电平虽然降低概率，但没有形成稳定阈值。加入 1.5 秒播放前静默门禁后，`ready_03 -12 dB` 仍有 2/3 自触发；`ready_01 -15 dB` 仍有 1/3 自触发。继续压低电平会明显损失提示音可听性，却仍不能证明可靠消除误触发，因此不采用“只调素材音量”作为修复。

## 2. 实现

HA 沿用 `TTS_PLAY=0x30`，只增加向后兼容的可选布尔 `suppress_vad`。默认/省略为 false，只有 `PromptSoundPlayer` 对三条 ready prompt 置 true；普通 TTS payload 不带该字段。

ESP32 保持全局 `vad_mute_playback=false`。只有当前 request 明确带 `suppress_vad=true` 时：

- 取得唯一 audio output owner 后，在首批正长度音频数据进入播放路径时 runtime `disable_vad + reset_vad`；
- RX、AFE、AEC 和最终 TX→AEC reference 继续运行；
- gate 期间暂停 `MIC_ACTIVITY` / `MIC_PCM` 向 HA 上送；若进入 gate 前已有 speech，只归零并至多发送一次 `speech_end`；
- 数字输出 drain/end 后继续保持 gate 到实测 TX→mic 延迟 760 samples / 47.5 ms 结束，实现向上取整 48 ms；
- 随后 `enable_vad + reset_vad`，恢复正常 MIC/VAD 路径。

因此语音若完整落在约 0.7–0.9 秒提示音窗口内可能被忽略，这是此 workaround 的明确取舍；不再声称提示音期间具备双讲识别。普通 TTS 不进入该 gate。

## 3. TDD 与自动化证据

RED 使用独立 HEAD worktree（旧生产实现）加载同一新增测试：Prompt owner 测试因没有发送 `suppress_vad=true` 失败，transport 测试因旧 `async_send_tts_play()` 不接受该参数失败，证明测试确实能捕获缺失行为。

GREEN / 回归：

- 针对性 ESP32 host：`3 passed`，覆盖 gate 归零已有 speech、不上传 gate 内 PCM、恢复后再次产生 speech/PCM，以及 `suppress_vad` 的可选 bool 解析与非法类型拒绝。
- 针对性 HA：`35 passed, 7 warnings`。
- ESP32 host 全套：`56 passed, 33 warnings`。
- HA Tivoo + Pipeline cancellation 全相关回归：`379 passed, 180 warnings`。
- `git diff --check`：PASS。
- 固件完整 `ninja -C build`：PASS；`tivoo_firmware.bin` 大小 `0x1a4ce0`，app 分区余量 79%。

## 4. 固件部署

生成的 app-only 镜像 SHA256：

`6ba474f4ed6dba80d3bf4bb6d28122d558c8d09d0f19c10d3096735924e0c403`

开发机与 NAS 落盘 SHA256 一致。通过 NAS `tivoo-esptool` 容器仅写入 app 分区 `0x10000`，未擦除或写入 NVS；esptool 写入 1,723,616 bytes 后执行 data hash verify 并硬复位。实机 HELLO 显示固件 `0.1.0+9a73d03`。

## 5. 最终实机对照

每一轮连接后先观察 1.2 秒，若出现 MIC session/activity/PCM 则该轮不进入样本。最终三条提示音都走相同 NAS HTTP MP3 路径：

| 样本 | `suppress_vad` | AUDIO_STATE | MIC_SESSION_START | MIC_PCM | `speech_start` | VAD gate 日志 |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `ready_01.mp3` | true | buffering → playing → completed | 0 | 0 | 0 | on: `disable=0 reset=1`; off: `enable=1 reset=1` |
| `ready_02.mp3` | true | buffering → playing → completed | 0 | 0 | 0 | on: `disable=0 reset=1`; off: `enable=1 reset=1` |
| `ready_03.mp3` | true | buffering → playing → completed | 0 | 0 | 0 | on: `disable=0 reset=1`; off: `enable=1 reset=1` |
| `ready_01.mp3` 正对照 | false | buffering → playing → completed | 1 | 1* | 1 | 无 suppression on；出现 `VAD speech_start transitions=13 upload=1` |

`*` 正对照在检测到首个 MIC session 后立即发送了测试用 `MIC_CAPTURE_STOP`，因此这里只保留到 1 个 PCM 帧；目的不是测上传总量，而是证明 gate 结束后 VAD/MIC 已恢复、普通 TTS 仍可进入既有打断入口。

这组对照排除了“修复实际上把 VAD 全局关掉”的可能：三条提示音均不再自触发，而同一音频不带 `suppress_vad` 时仍能立即触发 VAD/MIC。

## 6. HA 生产部署

仅更新生产集成中本次需要的：

- `/config/custom_components/tivoo/prompt_audio.py`
- `/config/custom_components/tivoo/transport.py`

部署前备份在 `/volume1/docker/tivoo-backups/p67-vad-pre-20261116-1845`。两文件开发机/NAS SHA256 完全一致。HA 恢复后容器为 running，首页 HTTP 200，未见 Tivoo traceback/error；三条生产 `/local/tivoo/prompts/ready_0{1,2,3}.mp3` 均为 HTTP 200 + `audio/mpeg`，HA 已重新建立到 ESP32 `192.168.3.28:7778` 的连接。

## 7. 结论

P6.7 的“提示音自身唤起 VAD”故障已按当前产品取舍关闭：**仅 ready prompt 播放窗口暂停 VAD/MIC 上送，声学尾部结束后恢复；普通 TTS 不进入 gate，原有 VAD/KWS 打断入口保留。**

这不等于 P6.5 的通用 AEC 双讲能力已通过；P65-A13 的 AEC 声学能力继续按其自身证据独立记录。
