# P6.8 本地语音上送背压定位与修复

日期：2026-11-23。分支 `feature/p6-8-s3-local-wake`，在既有脏工作区原地继续；未重置或提交用户先前改动。

## 1. 结论

本轮自动实机复现确认，“唤醒成功后语音上送期间像 AFE 断流、最终无回答”的第一故障不在双麦 I2S 或 ESP-SR AFE，而在 S3 的 7778 realtime 上送边界。

原实现 `MESSAGE_QUEUE_DEPTH=4`，只覆盖 80 ms 的 20 ms MIC 帧；realtime MIC 与普通 diagnostic log/HELLO 共用 priority 1 的 `tivoo_diag` worker。原故障复现中 AFE `feed_errors=0 / fetch_errors=0 / resets=0 / capture_overruns=0`，但 MIC_PCM 91 次 enqueue 只有 2 次成功、89 次失败；HA/Qwen 仅收到 1280 B，恰为 2×640 B。

真正执行到 socket 的 MIC 帧均发送成功，mutex/queue lock 等待为微秒级。时序证明主要问题是发送 worker 得不到足够服务窗口，而不是 HA/TCP 首先阻塞。

证据：`evidence/2026-11-23-p68-uplink-backpressure/original-p1-repro-serial.txt`。

## 2. 排除过程

所有试验均使用同一个一次性自动 turn：软件只替代 wake/VAD 触发条件以避免真人讲话；提示音、双麦 I2S、TX reference、ESP-SR enhanced PCM、7778、HA 与 Qwen 都是真实链路，上传内容始终来自真实 AFE 输出，没有制造 PCM。试验代码最终全部移除，因此这不算“真实唤醒词识别”物理验收。

| 试验 | realtime 结果 | AFE 结果 | 判定 |
|---|---|---|---|
| 原 whole worker priority 1 | 89/91 MIC enqueue 失败，`tx_timeout` | 连续健康 | 网络 worker 饿死 |
| whole worker priority 4 | 仍大量失败，`pcm_overflow` | 连续健康 | 单纯小幅提优先级无效 |
| whole worker priority 5/6 | enqueue 可推进 | capture overrun / RX gap / reset | 会反向破坏实时采集 |
| 独立 realtime worker priority 5 | 可推进 | 仍触发 AFE reset | 太高 |
| 独立 realtime worker priority 4、4帧 | 大量 enqueue fail | AFE 完全健康 | 结构正确，但 80 ms 缓冲不足 |
| 独立 realtime worker priority 4、64帧 | 输入可完成 | timing export 后有扰动 | 临时探针污染结果 |
| 关闭 timing probe，且满队列检查移到 malloc/copy 前 | 144/144 帧完整到 HA/Qwen | 全程无新增 gap/reset/overrun | **PASS** |

代表性证据：`whole-worker-p4-serial.txt`、`whole-worker-p6-serial.txt`、`split-worker-p4-serial.txt`。

## 3. 最终保留修复

`esp32/firmware/main/diagnostics.c`：

1. 普通 `tivoo_diag` 保持 priority 1，只处理 HELLO/诊断日志等非实时工作。
2. 新增 `tivoo_rt_tx`，priority 4；空闲时阻塞在 task notification，只消费 bounded realtime message queue。
3. `MESSAGE_QUEUE_DEPTH` 从 4 调整为 64：64×20 ms = 1.28 s。按实测约 0.95 s 最坏服务空窗加约 30% 余量选取，不是无限缓冲。
4. MIC PCM payload 显式使用 `MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT`；满队列约 40 KiB 音频不占内部 RAM。
5. producer 先无阻塞检查 queue/generation/capacity，只有确定能入队后才 malloc+memcpy。队列满重试不再反复做 PSRAM 分配/复制/释放。
6. 保留 control slot 预留与原 generation/epoch/FIFO/single-socket sequence 语义；没有改变 TVIO wire 格式。

最终结构把 AFE 实时域与网络短时背压解耦：短时 worker 调度抖动由有界 PSRAM backlog 吸收；容量耗尽时 producer 仍非阻塞，turn 自身 pending PCM 后续重试。

## 4. 自动主动链路验收

无 timing-probe 的最终候选自动 turn：

```text
end valid=46057 padded=23 sent=46080
turn_metrics ... outcome=input_complete
```

`46080 samples × 2 B = 92160 B`。HA/Qwen 对同一会话记录：

```text
input_bytes=92160
input_eof=5268 ms
```

即 144 个 640 B / 20 ms MIC PCM 帧全部到达，没有丢帧。

同一实机日志约 31.6 s 内：
- `feed 155 -> 312 -> 468`
- `fetch 301 -> 623 -> 936`
- `feed_errors=0`
- `fetch_errors=0`
- `rx_gaps=1`（启动期固定，不增长）
- `resets=0`
- `capture_overruns=0`

证据：`q64-checkfirst-active-serial.txt`、`q64-checkfirst-ha-qwen.txt`。

自动输入没有语义真人语音，因此 Qwen `output_bytes=0 / stt_finalize_timeout` 不能作为回复能力失败证据；本试验只核销“AFE 连续性 + 完整上送”。

代价：该压力样本的 `input_eof≈5.27s`，相对约 3 秒强制 speech 存在约 1 秒 backlog 排空延迟。这是当前 priority 4 保护 AFE 的显式折中。

## 5. 临时探针清理

`p68_timing_probe.h`、`read-p68-timing.py`、timing 专用测试及生产热路径 instrumentation 均已移除。实测表明大量 `P68TIME` 串口导出本身可制造 RX EOF 丢失/AFE reset，因此不得保留为正常 wake 后自动导出功能。

最终源码与最终 app 都检查不到 `AUTOTEST`、`P68TIME`、`p68_timing_probe`。

## 6. 正常固件最终验收

最终正常 app SHA256：

```text
df7f15e4e3fd6026706d2b4675ed138cd4b42b0644a28bc886f12ef1c214e0ae
```

通过 NAS `tivoo-esptool` 仅刷 S3 `/dev/ttyACM1` 的 `0x10000` app，Hash verified；未擦 NVS、模型或分区表。

90 秒串口采集，严格验收脚本要求至少 60 秒，结果：

```json
{"passed":true,"observed_runtime_seconds":70.11,"reports":8}
```

最后一份 telemetry：

```text
feed=1251 fetch=2501 feed_errors=0 fetch_errors=0
rx_gaps=1 resets=0 overruns=40 missed_eof=0 capture_overruns=0
```

启动期 `rx_gaps=1 / overruns=40` 在全部 8 份报告间均未增长。

证据：`final-normal-flash.txt`、`final-normal-90s.txt`、`final-normal-verify.txt`、`final-firmware-sha256.txt`。

## 7. 回归

- 定向 diagnostics / local turn / AFE / hardware-memory：**40 passed**。
- 全部 `tests/esp32` 第一次经 HA runner 时，唯一失败/错误来自 HA 全局 socket guard 拦截本地 HTTP fixture，不是生产代码失败。
- 按 ESP32 suite 的独立环境 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 重跑：**146 passed**，exit 0。
- `git diff --check` PASS。

证据：`final-esp32-suite.txt`。

## 8. 当前边界

本轮已经解决并验证的是：**本地 wake 后 AFE 输出进入 Wi-Fi 上送时，不再因为 7778 realtime worker/4帧队列背压造成会话失败或让重试负担拖垮 AFE。**

尚未用真人语音重新核销：
- 真实 WakeNet “嗨，乐鑫” → 正常问句 → Qwen 语义回答；
- 回复播放中的真实 barge-in；
- 问号续聊后的整条物理会话。

这些不影响本轮背压根因与修复成立，但不能用自动 synthetic-trigger 结果冒充上述物理验收。
