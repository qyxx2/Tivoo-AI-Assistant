# 首次唤醒提示音缺失与命令顺序修复

- 日期：2026-11-17；基线 `main@9908945`。
- 分支：`fix/ready-prompt-stale-tts-owner`。
- 用户要求：说唤醒词，听到“我在/在的/你说”，然后再说命令。

## 现场证据与原因

修复前 NAS 四个相关 HA 模块 SHA256 与 main 一致，三条静态 MP3 HTTP 均为 200/audio-mpeg。2026-11-16 23:42 的被动 TCP 记录显示：23:42:31 首次 KWS 成功但无提示音请求；后续真实 TTS 完成后提示音恢复，ready_03 和 ready_01 均 completed。另一次 ready_02 请求立即被 prompt_cancelled 停止，最终 stopped、bytes_received=0。因此不能归因为素材一直不可用或 DAC 永久损坏。

代码存在两个可复现的软件问题：

1. PromptSoundPlayer 的真实 TTS 占用只依赖 AUDIO_STATE 终态释放；断连和发送失败路径未释放，下一次唤醒直接被静默跳过。新增两条回归在旧代码下均以实际提示音发送次数为零失败。现场没有保留最早失败瞬间的全部日志，不能把最初那次断线的具体触发时间宣称为已证实。
2. HA 的 default_pipeline 会把 wake 期间的 queued_audio 继续送入 STT，早到的 STT_VAD_START 可以取消提示音。TCP 已观察到提示音尚未读入数据就被取消；新增回归模拟 HA 缓存尾音，旧代码不能保证提示音先完成。

## 实现边界

- 断连或 TTS 发送失败：按对应 playback_id 释放 HA TTS 占用；迟到旧 ID 不释放新占用。
- 首次唤醒且有可用提示音：结束原 WAKE_WORD Pipeline，通过既有取消/owner 清理路径收尾，等待提示音终态，然后以当前 ingress offset 启动新 STT。原 wake tail 不进入命令，新 STT_START 才起计 5 秒。
- 提示音最大等待 5 秒，之后定向停止并降级；failed/stopped、缺素材、发送失败不永久阻塞命令。
- side KWS 确认打断、免唤醒 follow-up 仍保留原有行为。本次不改固件、音频素材、设备音量或 LLM/TTS 引擎。
- 协议上旧 HA Pipeline 仍可能短暂发出 STT_START，然后被取消；它已不再是当前 turn，不能取消提示音或触发后续命令。

## 自动化验证

- 修改前基线：37 passed。
- 断连/发送失败两条新增回归：RED 2 failed → GREEN 2 passed。
- wake tail 顺序回归：RED → GREEN；额外覆盖提示音 failed 后继续进入 STT。
- 最终针对性：41 passed。
- HA 全套：483 passed（246 条既有依赖/测试警告）。
- ESP32 host 独立运行：56 passed（33 warnings）。
- Sherpa 专用环境：131 passed（1 warning）。
- Ruff check 和 git diff --check：PASS。

最初将所有测试交给 HA 环境运行时，8 个 Sherpa 模块因缺 wyoming/sherpa_onnx/numpy 收集失败；将 ESP32 与 HA 混跑时，test_controlled_http_fixture_covers_stream_and_failure_responses 被 HA socket guard 阻止并产生 teardown error，test_device_status_ping_events_and_p6_error_codes 出现 fetching/idle 时序失败。之后按仓库各自环境分离运行，以上三套全部通过；未修改这些无关测试。

## 部署与实机验证

仅部署 `/config/custom_components/tivoo/assist_satellite.py` 与 `prompt_audio.py`。备份：`/volume1/docker/tivoo-backups/ready-order-pre-20261117`。compileall 通过，重启 HA 后 API state=RUNNING、assist_satellite.tivoo=idle，生产两文件 SHA256 与工作区一致。

2026-11-17 00:23 的第一轮实机：

- 00:23:40.381：KWS 返回“大肥鱼”。
- 旧 Pipeline 00:23:40.394 结束。
- ready_03 经 buffering → playing → completed，接收 7532 bytes，没有 prompt_cancelled。
- 00:23:41.928：新的 STT Pipeline 开始；之后收到真人语音并得到 STT 结果。
- 随后正常回答 TTS 收到 buffering/playing，未因首次提示音破坏回答链。

这是协议/时序的实机证据，不冒充远程人工听音结论。连续多轮与用户主观听音结果以后续验收为准。

### 真实断连后的第二轮

00:23:59.141 TCP 抓包明确为 ESP32 `192.168.3.28:7778` 先发送 FIN，HA 00:24:00 自动重连。设备 uptime 连续，没有重启；正常回答未拿到 completed。因此本次不能宣称回答播放稳定性已修复。这个连接关闭原因尚未定位，是独立剩余问题。

重连后无需重载 HA 或复位设备，00:25:43.394 再次识别“大肥鱼”；ready_02 立即下发，buffering → playing → completed，6668 bytes；00:25:44.625 新 STT_START，随后正常得到命令识别结果。这直接验证了真实断连之后的提示音恢复和先提示音后命令的顺序，不再仅依赖模拟测试。

本次现场 HELLO 固件为 `0.1.0+4a14592`，与前一轮诊断时不同；本任务没有修改或刷写 ESP32。HA 修复与当前实际固件的协议兼容已经由上述两轮验证。
