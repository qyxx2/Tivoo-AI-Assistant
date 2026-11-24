# P6.8 B8.7 持续 MIC 上送及 CPU0 看门狗实机修复

日期：2026-11-23；分支：`feature/p6-8-s3-local-wake`。本报告仅覆盖 B8.7 尚未通过的本地语音连续上送；保留工作区先前修复，不作为 B8.7 整体 / B9 验收。

## 故障原始证据

16:19:52 真实唤醒成功，“我在”播放完成，Qwen voice_ready，`input_bytes=44160`（69 个20ms帧），`output_bytes=0`，ESP32 `tx_timeout`。16:20:09 再次唤醒，`input_bytes=0`、`command_timeout`。先前 144/144 约3秒自动语音帧只证明有界 backlog 最终能排空，无法证明长时实时吞吐，也未完成真人问答。

代码确认每包 640B、50 包/秒；协议本身允许单 MIC_PCM 最多 4096B。HA local mode 曾限定 `len==640`；Qwen bridge 已负责将任意有效 chunk 切为 640B 转发。

## 最小生产改动及断言

1. `esp32/firmware/main/p68_local_turn.c`：在未结束时收集最多6个相邻320-sample帧合包，以1次事务发送至多3840B；结束时冲刷尾包。对跨环形缓冲末尾的包分段发送；每包发送成功后才推进计数器，不改既有的消息代际、FIFO、超时、任务优先级或64帧有界 backlog。
2. `homeassistant/custom_components/tivoo/audio_session.py`：本地 MIC_PCM 验证允许640B的正整数倍，公共合同仍明确拒绝空包、奇数字节及>4096B；Qwen代码无需改动。
3. `esp32/firmware/sdkconfig.defaults` + 真实 `sdkconfig`：保留 ESP-IDF task WDT 和 CPU1 Idle 检查，仅取消 CPU0 Idle task 默认订阅。CPU0 的连续高优先级 AFE 捕获/处理 + 实时上送工作在实测8秒窗口中会阻断低优先级 IDLE0 的5秒窗口；看门狗告警/回溯输出紧接着导致 DMA 错误。此选择减少了 CPU0 闲置任务饥饿监控范围，并非扩大任何任务或网络发送超时；不代表 CPU0 负载降低。

主回归：`tests/esp32/p68_uplink_batch_host.c` / `test_p68_uplink_batch.py`，测试6帧合包、序列完整、尾包和50帧环回绕。`tests/homeassistant/custom_components/tivoo/test_p68_local_session.py` 新增3840B透传断言。原 `p68_turn_host.c` 和 `p68_prompt_adapter_host.c` 更新为按样本数而不是网络包数核对。

## 真实 S3 自动 AFE 持续压力对照

所有临时试验都先自动触发 Wake + 真实提示音，再只临时强制 VAD 的8秒窗口；每字节 PCM 均来自硬件双麦与 ESP-SR AFE；并非伪造音频或真人问话。各临时 `AUTOTEST` 触发代码均只存在于压力固件，生产源码和最终固件不得保留。每次压力试验结束用 NAS `tivoo-esptool` 将已校验的生产应用恢复到 S3 的 `0x10000`，未擦NVS、模型或分区表。

| 版本 | 设备真实结果 | 裁定 |
|---|---|---|
| 6帧合包、原双核布局 + 原 WDT | 约7秒后 CPU0 `IDLE0` WDT；`send_attempts=59`、`send_failures=0`，随后 `audio_dma_fault`，AFE reset | 网络频率改善，但原 WDT 导致 DMA/会话中断 |
| capture 每200个5ms帧 sleep 1 tick | ~2.5秒后 `disconnected`、`rx_gaps` 增加、ISR overflow | **拒绝**，会破坏捕获实时性 |
| 网络 TX worker 改为 CPU1 绑定 | ~7秒 `IDLE0` WDT、AFE reset | **拒绝**，未解决 CPU0 Idle 饥饿 |
| 对称31tap FIR 合并运算 | 96,000个离线 PCM 逐值一致，实机~1.3秒仍出现 `capture_overruns=4` 和 reset | **拒绝**，源码已撤回 |
| capture/fetch 调整至CPU1，feed至CPU0 | 上电及会话期间重置、`capture_overruns=5`、feed最大104.5ms | **拒绝**，保留原采集/FEED亲和性 |
| 只取消 CPU0 Idle task WDT 订阅，其他保留 | **8秒完整输入**，`end valid=123097 padded=103 sent=123200`，`outcome=input_complete`，`send_attempts=73`、`send_failures=0`；43秒日志中无新增 AFE gap/reset/capture overrun/missed EOF | **保留该配置** |

自动压力证据目录：`evidence/2026-11-23-p68-batch-uplink/`。文件分别为 `autotest-70s.txt`、`yield-autotest-58s.txt`、`pin1-autotest-42s.txt`、`fir-autotest-42s.txt`、`balanced-autotest-34s.txt`、`wdt-autotest-43s.txt`，附各次刷写日志及恢复日志。

自动 PASS 具体样本指标：完成时间 `17836 ms`（自动命令音频开始 `9826 ms`），`end valid=123097` +尾部pad `103` = `123200` samples / `246400 B`。peak pending=6873 samples，send_attempts=73，失败=0。AFE 首至末可比较的10秒进度 `feed 154→312→468→625`、`fetch 307→622→936→1249`；rx_gaps恒为1、resets恒0、ISR overruns恒40、missed EOF恒0、capture_overruns恒0。约43秒试验中没有WDT告警或DMA重置。

**边界**：自动唤醒/VAD测试只证明 S3 真实音频流持续送达会话提交边界，不能用环境声被强制判语音的测试证明 Qwen 回答质量。尤其原第二次真实 `command_timeout input_bytes=0` 仍需实人触发后的 VAD 起始复验。用户尚未提供新固件上的真实人声完整回答、回复播放、打断与续聊，B8.7余下声学/交互门禁和B9继续HOLD。

## 生产部署及最终无探针复验

正式生产固件包含“PCM 合包 + local mode 长度合同 + CPU0 Idle WDT 单项订阅配置”三处改动，**没有**自动 Wake/强制VAD、临时任务亲和性、采集sleep或FIR优化代码。

- 正常 ESP32-S3 app：`2529792 bytes`；SHA256 `c9276f0c2e4717e9b0de5280a71346d498ce41b7c8860b1dcbef361f3c2691e4`；`strings build/tivoo_firmware.bin | grep AUTOTEST` 无命中。NAS 文件：`/volume1/docker/tivoo-esptool/artifacts/p68-b87-batch-wdt-normal-20261123.bin`。两端SHA一致。
- `tivoo-esptool` 通过 `/dev/ttyACM1` 对S3 `0x10000` 应用分区写入，日志明确 `Hash of data verified` 和 `Hard resetting via RTS pin`，未刷写ESP32经典板，未修改模型分区或NVS。刷写证据 `evidence/2026-11-23-p68-batch-uplink/final-normal-flash.txt`。
- 无自动触发的正常固件串口采集90秒，连续8份AFE telemetry覆盖70.11秒；严格验收脚本 `--min-runtime-seconds 60` **PASS**。feed 155→1251；fetch 310→2501；`feed_errors=0`、`fetch_errors=0`、`rx_gaps=1`恒定、`resets=0`、`overruns=40`恒定、`missed_eof=0`、`capture_overruns=0`，无WDT报错。证据 `final-normal-90s.txt`、`final-normal-verification.json`。
- 8秒自动真实AFE上送日志另经相同严格判据验证 **PASS**：4份 telemetry、观测30.08秒，见 `wdt-autotest-verification.json`。
- HA文件：`/volume1/docker/homeassistant/config/custom_components/tivoo/audio_session.py`，SHA256 `07ffbede7473de8a63e497bca8463ceb6f98c396506790a37f0319923f1cc6af`，变更前文件备份为同目录下 `audio_session.py.before-p68-b87-batch`。最终检查 HA、Qwen 容器均为`running`。
- 实际压力会话的Qwen gateway日志证明 `voice_client.connected`、`realtime.connected`、之后 `voice_client.disconnected`，见 `wdt-autotest-qwen.log`。由于 HA 当前INFO日志未开放，此次没有从HA侧取得同一会话的 `input_bytes` 精确独立统计；不得声称“Qwen收到了246400B”或“Qwen给出了回答”。
- 完整 ESP32 Python/host suite **147 passed**（exit0；37 warnings）；定向 HA local-session/lifecycle **49 passed**（exit0；5 warnings）；`git diff --check` exit0。证据：`final-esp32-suite.txt`、`final-HA-local-suite.txt`。

**最终结论**：连续双麦AFE采集与本地TCP MIC PCM持续8秒上送、正常input_end已由真机可重复使用的配置修复并通过自动压力验收，正式正常固件部署且空闲连测稳定；真人WakeNet→真正说出问题→Qwen音频回复→Tivoo播放，以及`input_bytes=0`型原始个案尚无真人新证据，B8.7余项仍HOLD。保留所有未提交的先前工作区改动；此报告未声称已合并或提交整个分支。
