# P6.5b11 自动化验收与现场补测

执行日期：2026-11-14。分支：`feature/p6-5-ha-cancellation-preflight`，基线 `5d35cb7`。

本批补测时序、打断、端点和 follow-up，并完成 P3/P6/P7A 与 b6 回归。计时采用现有合同值。现场不可操作，本批使用主机自动化和已归档的 NAS/板级证据。NAS 部署与 ESP32 刷写留到现场联调需要时进行。

## 复现命令

```bash
bash scripts/test-ha.sh -q --disable-warnings tests/homeassistant
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -c /dev/null -p no:cacheprovider -q tests/esp32
bash scripts/test-sherpa-wyoming.sh -q
```

HA 356 项、ESP32 host 55 项、Sherpa Wyoming 130 项。ESP32 host 独立运行可允许 HTTP fixture 监听 loopback。HA 插件混跑会拦截该 fixture 的 socket。

`test_stage_watchdogs` 在累进的单调时间轴上检查 3、15、5 秒截止点前后，也验证新的 speech_start 取消旧的静音计时。打断测试模拟旧轮清理 6 秒，核对新轮收到保留的 PCM，以及 5 秒窗口从新轮 STT_START 才开始。follow-up 测试在完成事件后 7.9 秒进 STT，在第二次完成后跨过 8 秒停止旧 ingress，并验证新的 session 从 WAKE_WORD 进入。HA 实际 Pipeline 与本地 Wyoming 连接以 20 ms 帧注入 PCM，用确定性的 MicroVAD 分数触发真实 VoiceCommandSegmenter，验证约 0.3 秒起始以及约 1.0、1.7、15.0 秒端点。1.7 秒由 1.0 秒语音接 0.7 秒静音构成。P7A 的 300 秒是独立请求限制。

## 合同证据

PASS 表示该行合同有足够的自动化或既有证据。GAP 表示软件、数字链路或真实服务的一部分已验证，尚缺现场闭环证据。BLOCKED 表示本批无法获取该项需要的声学数据。

| ID | 状态 | 可复现证据与待验收条件 |
|---|---|---|
| P65-A01 | PASS | `test_p65b8_audio.py` 验证空闲不发送 PCM；[b8 板级报告][b8]记录空闲 AFE 帧持续增加。 |
| P65-A02 | PASS | `test_p65b8_acceptance_tool.py` 覆盖 START→ACTIVITY→PCM，主机 C 用例覆盖预录；Satellite 回归验证同一 ingress 进入 WAKE_WORD 和 STT。11-15 真人触发、实际上传、KWS/STT 和 AUX 回复两轮通过。 |
| P65-A03 | GAP | `test_stage_watchdogs[wake_miss]`、`[wake_candidate_timeout]` 检查最近 speech_end 后 3 秒和首次 speech_start 后 15 秒，验证取消和 STOP；现场补测停止上传后 AFE 仍运行。 |
| P65-A04 | GAP | `test_stage_watchdogs[command_timeout]` 验证从 WAKE_WORD_END 命中起算；`test_confirmed_wake_replaces_active_turn` 验证连续 PCM、超过 5 秒的清理延迟、从新 STT_START 起算及空命令超时。现场补测连续说出唤醒词和命令。 |
| P65-A05 | PASS | `test_normal_pipeline_completion_closes_all_owned_streams` 的三个 endpoint 用例验证 Wyoming 的 `requires_external_vad`、起点和端点。P7A 的 `test_config.py`、`test_stt.py` 分别验证 300 秒默认值和按配置限制请求。 |
| P65-A06 | PASS | `test_upload_survives_run_end_and_starts_followup_after_playback` 覆盖同一 session 的两轮；`test_audio_session.py` 覆盖 PCM 顺序、旧 PCM 隔离、有界缓存和溢出。 |
| P65-A07 | PASS | `test_cancel_before_tts_closes_sse_and_stops_pipeline_once` 验证 reader 关闭、Stop 一次和迟到增量抑制；[b6 报告][b6]记录真实 AstrBot partial-output Stop。 |
| P65-A08 | PASS | `test_cancel_during_active_tts_proxy_tracks_all_owners` 覆盖真实 HA/FFmpeg/Wyoming 连接的活动流取消；`test_interruption_suppresses_late_tts_events` 验证迟到 TTS_PLAY 抑制。物理停音归 A11/A14。 |
| P65-A09 | PASS | `test_http_tts_proxy_disconnect_does_not_cancel_upstream` 与活动 TTS 取消对照，分别验证独立 consumer 断开和按 run 取消 producer。 |
| P65-A10 | GAP | `test_confirmed_wake_replaces_active_turn[playback-True]` 在模拟播放期间注入 speech_end/start 和 PCM，未返回 Detection 时保持同轮、无 AUDIO_STOP、无 MIC STOP。待采集普通讲话、电视和噪声。 |
| P65-A11 | GAP | 播放期模拟 Detection 触发匹配 ID 的 AUDIO_STOP，新轮从 STT 接收有序 PCM；[b9 NAS 记录][b9]有真实模型对直接注入音频的命中和未命中。待验证真人经 INMP441 唤醒、实际 DAC 停音和新命令识别。 |
| P65-A12 | GAP | 模拟 Detection 已覆盖首个 plain 前、plain 后、TTS 生成中和播放期；[b6 报告][b6]独立验证真实 AstrBot Stop。待验证真实音频触发与运行中四个阶段的组合。 |
| P65-A13 | BLOCKED | [b10 报告][b10]提供 TX 参考计数，实际 TX→扬声器→麦克风延迟、回声及含唤醒词 TTS 样本待采集。 |
| P65-A14 | GAP | [b10 报告][b10]记录数字 I²S TX/RX/AEC 与 SPP 对照、RX overrun 和参考错位；现场已确认 PCM5102 AUX 清晰出声、AFE 持续运行和播放中 SPP 回包。待验证同一场景中的真实 MIC 上传与 KWS。 |
| P65-A15 | GAP | follow-up 回归检查 RUN_END/resource_ready 不开窗口、completed 后 7.9 秒内进 STT、8 秒停止 ingress、忽略旧 PCM、新 session 重走 WAKE_WORD；待用真实播放末尾和网络帧复核。 |
| P65-A16 | PASS | `test_interruption_suppresses_late_tts_events`、follow-up 回归及 `test_p65b10_output.py` 覆盖旧 TTS_PLAY、AUDIO_STATE 和 AUDIO_STOP 对新代次的隔离。 |

## 2026-11-14 现场补测

- NAS 上 HA、AstrBot 与 Sherpa 容器运行，HA 使用配置了 `tivoo-wake` 的 AstrBot Pipeline。ESP32 的 HELLO 报告固件 `0.1.0+e7ca515`。本轮沿用现有部署。
- 独立下发 NAS 已归档的 32 kHz 单声道 TTS MP3。现场确认 Tivoo AUX 出声清晰。ESP32 首次 `completed` 用时 5,018.0 ms，播放中收到 SPP 状态回包。另一次匹配 STOP 在 67.4 ms 内收到 `stopped`，该值为协议时延，实际停音尚未确认。
- 测试时 AFE 帧持续增加。两轮完整播放 TX underruns 为 0，PCM 输出队列高水位 5,120 样本，参考峰值 19,326。测试期间 RX overrun、参考 underrun/错位和 PCM drops 保持为 0。累计 DMA missed EOF 保持 313。全双工合同仍缺同一场景下的真实 MIC 上传与 KWS。
- 现场说出「大肥鱼，告诉我今天是星期几」后未听到回复。串口复现 B8 的持续 `vad=speech`，AFE 帧仍正常增长，7778 未见持续 PCM 上传。现场暂无法断电核对 INMP441，待核对接线或测量 GPIO26/25/34 波形后复测。唤醒超时、打断、回声负样本和 follow-up 的声学闭环仍待验收。
- 独立播放期间短停 HA 以释放 7777/7778，随后已重启并确认两路恢复连接。

## 2026-11-15 真人唤醒与 TTS 延迟复测

现场两次连续说「大肥鱼，告诉我今天是星期几」，两次都听到 Tivoo AUX 回复。ESP32 探针记录安静时 VAD 为静音、说话时产生 speech_start 并开启上传。两轮均由 Sherpa KWS 命中，STT 返回转写，TTS 生成 PCM，ESP32 播放至 completed。两轮 TX underruns 均为 0。P65-A02 的真人首轮正向链路通过。

| 测量区间 | 第 1 轮 | 第 2 轮 |
|---|---:|---:|
| VAD speech_start → KWS 命中 | 1.21 s | 1.30 s |
| KWS 命中 → STT 返回 | 2.99 s | 3.28 s |
| STT 返回 → HA 发出 TTS_PLAY | 6.41 s | 9.37 s |
| TTS_PLAY → ESP32 AUDIO_STATE playing | 2.73 s | 1.15 s |
| KWS 命中 → AUDIO_STATE playing | 12.13 s | 13.80 s |
| VAD speech_start → AUDIO_STATE playing（ESP32 单调时钟） | 13.32 s | 15.10 s |

KWS 和 STT 使用 NAS 的 Sherpa 请求完成日志，TTS_PLAY 和 playing 使用同一 NAS 的 7778 抓包时间。playing 表示进入数字播放路径，实际 AUX 首声未采集同步录音，现场听测确认两轮确实出声。VAD speech_start 是设备检测到语音的时刻。两条 KWS 日志请求 ID 为 `03f8a462da39` 和 `5de95107887c`，对应 playback ID 为 `5831175a-39c4-42bd-9296-203718d3c712` 和 `34a4e919-ca31-4eb5-a3d1-fd03f62b39e9`。Sherpa 两轮首 PCM 均为 0.988 s（从 TTS 请求起算）。STT 返回到 TTS_PLAY 是两轮最大的等待区间，本轮未获取 AstrBot 首个 plain 的单独时间。打断与 follow-up 单独验收。

## 2026-11-15 首声延迟分段复测

在生产 HA 2026.11.0 的 AstrBot Pipeline 以 WebSocket 注入同一段现场录音，并用 NAS 抓包核对 AstrBot 可朗读的 SSE `plain`（排除 `chain_type=reasoning`）和 HA Pipeline 事件。单独的文本输入测得，星期短问句从 intent-start 到首个可朗读 plain 为 5.75 秒，到 tts-end 为 7.11 秒，期间未触发流式门槛。三句介绍黄山从 intent-start 到首个可朗读 plain 为 13.40 秒，HA 在 13.66 秒发出 `tts_start_streaming`。HA 2026.11.0 以超过 60 字符或已有正文后触发工具调用来启动流式 TTS。后续一句介绍黄山校验得 3.95 秒到首正文、4.13 秒到流式启动，开放问答仍走 AstrBot。

生产 AstrBot 统计显示原链路使用 `agnes/agnes-2.5-flash`。同一短问句单独对照了 Gemini 2.5、3.1、3.5 Flash Lite 和精简 WebChat 默认提示的方案，首正文时间波动且分布重叠，因此保留生产模型和提示配置。

生产 HA 通过原生会话句子触发部署 `tivoo_local_weekday`、`tivoo_local_date`、`tivoo_local_time`。使用 HA 的 Asia/Shanghai 时区，精确匹配中文问法，并覆盖录音中实测到的唤醒词残留「大飞鱼」。文字复测确认三组查询本地命中。现场录音重放经生产 Pipeline 的 KWS、STT、TTS Proxy，匹配星期问句前两轮耗时 11.80、11.67 秒至首个 HTTP 音频响应，部署后三轮耗时 4.64、4.57、4.71 秒至收到 2048 字节音频，三轮均为热缓存。时间查询新文本一次生成约 1.22 秒。重放未经过物理 Tivoo，现场 7778 抓包窗口内观察到 wake_miss，未得到新配置的 AUX 首声和 completed。

## 现场补测步骤

1. 记录 HA、AstrBot、Sherpa 和 ESP32 版本，核对 INMP441、PCM5102 与 Tivoo AUX 接线。优先按 [b8 报告][b8] 复核已观察到的 I²S 原始左槽异常和 VAD 持续判人声。保持生产 HA 连接 7777/7778。同步记录 TVIO、HA Pipeline、Wyoming、AstrBot、串口和外部录音时间点。独立的 b8/b10 诊断脚本只在需要隔离板级问题时运行，它们各自需要独占对应端口。
2. 从空闲开始，依次播放无唤醒词短句、跨越 15 秒的连续讲话、只说唤醒词、唤醒词后不间断说命令。记录 MIC_ACTIVITY、首轮 Detection、STT_START/VAD_START/VAD_END、STOP 与最后一个 MIC_PCM。对照 3/15/5 秒和分段阈值，检查 STOP 后 AFE 帧仍递增。
3. 让一轮回复在 AstrBot 等待首个 plain、已有 plain、TTS 生成中、PCM5102 正在发声四个阶段分别接受真人唤醒和新命令。记录原 run、playback_id、旧轮取消、AUDIO_STOP/终态、实际停音和新 STT。播放时在 7777 发送一次可观察的屏幕操作并记录 SPP 响应，同时确认上传连续且 RX 无重启。
4. 分别测试普通 TTS、自含唤醒词的 TTS、环境讲话和电视人声。在不同音量与麦克风距离下逐条登记样本、VAD、KWS hit/miss 和是否取消。用同步的参考和麦克风录音测量声学延迟。参考错位计数记录为独立指标。
5. 以 AUX 实际末声及同 ID 的 completed 为观测点，对比 8 秒内说话、8 秒无输入、到期后无唤醒词讲话与重新说唤醒词。记录停止上传及下一轮起始阶段。
6. 每轮记录空闲/播放/打断时的 heap、内部 RAM、PSRAM 和 CPU；记录 Wi-Fi RSSI、断连及 SPP 往返。取固件日志中 TX underruns、RX overruns、ref_underruns、ref_misaligned、PCM drops、pending、stack_min、queue_high_water 的前后差值或峰值。CPU 利用率和实际声学 lag 若当前诊断未提供，现场另采样并登记来源。

现场记录字段：样本/场景、音量、距离、run/session/playback ID、各事件时间、模拟首声/末声、KWS 结果、计数器和 PASS/GAP/BLOCKED。现场结果到齐后更新对应行。本批收尾保留 P7/P8 历史合同，是否标记 superseded 由用户决定。

[b6]: 2026-11-13-p6-5b6-cancellation-owner-closeout.md
[b8]: 2026-11-13-p6-5b8-esp32-audio-capture.md
[b9]: ../plans/2026-11-13-p6-5-batch-execution-plan-from-b6.md#p65b9--nas-kws-watcher确认打断与-pcm-handoff
[b10]: 2026-11-14-p6-5b10-esp32-playback.md
