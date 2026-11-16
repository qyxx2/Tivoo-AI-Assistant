# P6.7b3 NAS 部署与真实设备声学验收

- 日期：2026-11-16
- 分支：`feature/p6-7-audio-prompts`
- 基线：`93f0fae`（P6.7b2）
- 范围：仅 P6.7b3；没有修改 ESP32 固件、AEC/VAD 参数、5/8 秒窗口或 P6.6/P3 行为。
- 结论：**b3 已执行，但 P6.7 整体验收不通过。PR-C18 FAIL，PR-C21 GAP。** 三条提示音均能真实走 ESP32 HTTP/MP3/输出链并到 `completed`，但三条都会稳定由自身声学回声触发 VAD `speech_start` 和 MIC session，不能宣称“播放提示音同时安全收命令”的声学闭环已成立。

## 1. 开发机回归

部署前在 Ubuntu 工作区执行：

```text
./scripts/test-ha.sh tests/homeassistant/custom_components/tivoo \
  tests/homeassistant/test_assist_pipeline_tts_cancellation.py -q
379 passed, 180 warnings
```

`git diff --check` 同时通过。该回归覆盖 b0–b2 的 PromptSoundPlayer、三个等待入口、真实 TTS 互斥、P6.5/P6.6/Tivoo 与 Pipeline cancellation。

## 2. NAS 部署

仅部署 P6.7 运行时需要的文件：

- `/config/custom_components/tivoo/assist_satellite.py`
- `/config/custom_components/tivoo/audio_resource.py`
- `/config/custom_components/tivoo/prompt_audio.py`
- `/config/www/tivoo/prompts/ready_01.mp3`
- `/config/www/tivoo/prompts/ready_02.mp3`
- `/config/www/tivoo/prompts/ready_03.mp3`

部署前备份：`/volume1/docker/tivoo-backups/p67b3-pre-20261116-153748`。

远端 SHA256 与工作区完全一致；HA 容器内 `compileall` PASS。重启 HA 后首页 HTTP 200，三条生产静态 URL 均实测 `HTTP 200 + audio/mpeg`，未见 Tivoo import/setup traceback。

## 3. ESP32 实机播放

ESP32 保持既有固件 `0.1.0+2ca4ed3`，未刷写。为释放设备唯一 7778 客户端，设备直连验收期间短暂停 HA；HTTP 测试服务绑定同一 NAS LAN 地址、端口和 `/local/tivoo/prompts/` 路径，并直接提供已经部署到 HA `www` 的同一文件。HA 恢复后又单独复核真实 HA `/local` 三条均为 200/audio/mpeg。

首次复用一个诊断连接连续播放时，第二条进入 `playing` 后出现一次 7778 EOF；设备没有重启，随后每条使用独立诊断会话均稳定完成，因此该次 EOF 不作为素材/解码失败证据，最终采用独立会话结果。

| 素材 | buffering | playing | completed | 播放期间 MIC 结果 |
| --- | ---: | ---: | ---: | --- |
| `ready_01.mp3` / “我在” | 95.3 ms | 245.1 ms | 1050.4 ms | 约 709.8 ms VAD speech_start；随后 MIC session |
| `ready_02.mp3` / “在的” | 92.0 ms | 284.6 ms | 1111.1 ms | 约 0.72–0.86 s MIC session / speech_start |
| `ready_03.mp3` / “你说” | 42.7 ms | 263.4 ms | 1186.1 ms | 约 0.77–0.83 s MIC session / speech_start |

`playing` 是 ESP32 数字播放路径的状态，不冒充外部同步录音测得的模拟首声。三条均返回独立 playback_id，最终 `audio_resource=idle`；测试期间 SPP 仍为 connected。

## 4. AFE/AEC 连续性与失败降级

对 `ready_01.mp3` 做额外前后计数：

```text
before: overruns=2 feed_errors=0 ref_underruns=0 ref_misaligned=1 vad=silence
after : overruns=2 feed_errors=0 ref_underruns=0 ref_misaligned=1 vad=silence
delta : overruns=0 feed_errors=0 ref_underruns=0 ref_misaligned=0
```

播放约 747 ms 后开启 MIC session，约 771 ms 记录 `VAD speech_start`，约 2.07 s 回到 `VAD speech_end`。因此 RX/AFE/VAD/MIC 上传确实在播放期间持续，最终 TX→AEC R 链没有出现新增 underrun/misalignment；问题是现有声学消除仍不足以让 VAD 忽略本机短提示音。

同一设备随后请求不存在的 `missing.mp3`，返回：

```text
AUDIO_STATE failed
error_code=audio_http_status
bytes_received=0
```

设备音频 owner 随后可继续处于 idle，没有因 HTTP 错误卡死。

## 5. 关键声学结论

PR-C18 明确要求提示音自身不得诱发 follow-up 假启动或错误命令。当前三条提示音在每次播放前 AFE 均处于 `vad=silence`，随后都在提示音语音主体期间稳定触发 `speech_start` 并开启 MIC session。这已经是合同禁止的真实声学负样本。

因此没有继续把“真人同时讲话、不同音量/不同距离”的剩余矩阵当作可能改变最终结论的门禁：在没有外部用户讲话时提示音自身已经失败，继续做更多正向样本也不能把 PR-C18 改为 PASS。当前也不为验收测试改变 Tivoo 音量，因为生产状态没有可靠的可读/可恢复音量值。

这不是 RX/AEC 停止或参考队列崩溃：计数器证明采集与参考持续；需要后续独立任务重新处理 AEC 延迟/增益/声学耦合或提示音播放条件，再重新做声学验收。P6.7b3 按计划不在发现失败后直接扩展实现范围。

## 6. PR-C01–C21 最终状态

| 合同 | 状态 | b3 结论 |
| --- | --- | --- |
| PR-C01 | PASS | b2 三入口自动化仍通过；b3 未改变触发逻辑 |
| PR-C02 | PASS | 5 秒窗口回归通过 |
| PR-C03 | PASS | confirmed interruption 清理/handoff 回归通过 |
| PR-C04 | PASS | prompt terminal state 与真实 TTS follow-up 隔离回归通过 |
| PR-C05 | PASS | follow-up speech_start 不等待 prompt 的回归通过 |
| PR-C06 | PASS | 实机播放期间 RX/AFE/VAD/MIC 持续；无采集屏蔽 |
| PR-C07 | PASS | 三个生产同音色、32 kHz mono MP3 已部署 |
| PR-C08 | PASS | b1 随机不连播/缺失静默跳过回归通过 |
| PR-C09 | PASS | 真实 HA 三 URL 200/audio/mpeg；设备可从同一 LAN host/port/path 获取相同部署字节 |
| PR-C10 | PASS | 未放宽 TTS Proxy URL 白名单 |
| PR-C11 | PASS | 实机复用 0x30/现有 decoder/output manager；三条均 playing→completed，无新协议/混音 |
| PR-C12 | PASS | prompt 独立 playback_id；source 仍为 tts_http，按 ID 路由 |
| PR-C13 | PASS | b2 隔离回归通过；prompt 终态不进入真实 TTS dispatcher |
| PR-C14 | PASS | generation/旧状态隔离回归通过 |
| PR-C15 | PASS | TTS 优先/提示音让出物理槽回归通过；本轮未见正常路径 audio_busy |
| PR-C16 | PASS | 命令开始仅定向取消 prompt 的回归通过 |
| PR-C17 | PASS | 实机 RX 持续、AEC R 计数无新增 underrun/misalignment；`vad_mute_playback=false` 既有实现未改 |
| PR-C18 | **FAIL** | 三条提示音均在无外部命令输入的验收条件下触发 VAD speech_start + MIC session |
| PR-C19 | PASS | 缺失 HTTP 资源实机 failed/audio_http_status 后 owner 回 idle；软件错误路径回归通过 |
| PR-C20 | PASS | 未修改 P6.6/AstrBot/ChatLog/LLM；完整相关 HA 回归通过 |
| PR-C21 | **GAP** | NAS 部署、HA HTTP、ESP32 解码/数字输出与真实回声证据均已取得；因 C18 失败，真人并行讲话/多音量距离闭环不能标 PASS |

## 7. P65-A13

P65-A13 不能标 PASS。此前缺少的“实际 TX→扬声器→麦克风存在声学回授”现在已有直接证据：提示音播放与 VAD/MIC session 高度同步，且三条均可复现；但没有完成同步声学延迟标定、含唤醒词 TTS 的 KWS 负样本以及真人并行讲话识别，因此最多从“无现场数据”推进到 **GAP**，不能视为 AEC 验收完成。

## 8. b3 收尾判定

**P6.7b3 的部署与验收工作已完成，验收结果为 FAIL/GAP，而不是 PASS。** 当前生产文件已部署，开发分支不应标记 P6.7 整体完成。根据本批边界，本次不修改 ESP32 AEC/VAD 实现、不刷固件、不 push、不 merge main。
