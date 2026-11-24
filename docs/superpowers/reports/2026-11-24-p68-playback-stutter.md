# P6.8 B8.7 回复播放卡顿：调度定位与修复

> 2317cd3 后续修订：用户确认恢复后的 FD 模式再次造成日常卡顿，并明确选择恢复此前流畅的 SR 模式。当前默认改为 SR HIGH_PERF，详见文末“基于 2317cd3 恢复 SR”。静默对照证明严重吞吐退化已解除，但仍存在少量断粮，不宣告零断粮或声学验收通过。

> 后续状态更新：用户明确要求“直接重启”后，已通过 RTS 重启 S3。串口确认正常 app 启动、AFE available、Wi-Fi 获得 192.168.3.40。设备已退出下载模式并恢复运行；没有触发播放或唤醒测试。下文“暂留下载模式”是重启前的收尾记录。

日期：2026-11-24（Asia/Shanghai）。分支 `feature/p6-8-s3-local-wake`，HEAD `a4469d7`；在原有 dirty 工作区上继续，保留此前所有改动。

**结论：已定位日常回复严重卡顿的主因，并保留最小调度修复。用户最新实测反馈“目前固件已经不再声音卡顿了”。30 秒连续负载仍暴露 AFE 过载，不能据此宣告 B8.7 整体、长回答、打断或 B9 通过。**

用户后续要求禁止设备再发声，且暂时不能进行唤醒测试。本轮已终止设备测试，清除自动探针，刷回正常固件且使用 `--after no_reset`，最后输出 `Hash of data verified` / `Staying in bootloader`。**设备当前暂留下载模式，不运行应用，也不会自动播放；后续恢复使用需重新启动。** 没有在该禁声指令后再执行播放或唤醒测试。

## 原始故障与可重复信号

用户现场复现，确认内置“我在”流畅，回答严重卡顿。真实 session `579c3a4c-f962-46ed-a639-8cb3225a87a2`、播放 `3d631994-91e1-4f20-a8f5-398ff7319613`：

- Qwen response.started 到 response.done 约 0.94 秒，已生成音频。
- HA 当时已经采用等待整段 audio.done 才下发的策略；本轮没有修改 HA 代码。即使整段已在 HA 准备好，仍会卡顿。
- S3 generation 4：HTTP read 累计 15,655ms、最大单次 395ms；`underruns=2667`、`missed_eofs=0`、物理 drained=1。`completed` 不能证明连续播放。
- 同轮本地提示音 underruns=0；AFE 采集 gap/reset/overrun 未增长。
- NAS 抓包观察到 S3 反复宣告 TCP 接收窗口为 0，常隔约 180–200ms 才重新更新窗口；数据未能及时进入播放队列。

实际执行的确定性判定：

```bash
python scripts/verify-p68-playback.py \
  docs/superpowers/reports/evidence/2026-11-24-p68-playback-stutter/live-baseline-serial.log
```

退出码 1，`passed=false`，明确报告 generation 4 的 2667 次断粮。它验证的是保存的真实故障轨迹；不会主动驱动物理播放。后续禁声期间可安全离线重跑。

## 固定输入对照：主因是 core0 调度竞争

临时测试固件直接调用生产 `stream_audio()` → `audio_playback` → `audio_output_manager`，NAS 独立临时 HTTP 服务提供完全相同的 288,000B、24kHz mono S16LE PCM，时长 6 秒。只比较任务调度/省电配置，AFE 与双麦采集持续运行。

这是下载/转换/物理 DMA 的性能探针，**没有用它代替真实 WakeNet/VAD、合法会话、barge-in 或 follow-up 验收**。探针不接管真实 MIC owner；播放状态无法发给 HA 的 warning 属于该独立探针的预期限制，不计作生产协议故障。所有临时启动代码均已撤回。

| 播放任务 | Wi-Fi 省电 | 固定 6 秒音频实际耗时 | 断粮 | AFE feed ring 溢出 |
|---|---|---:|---:|---:|
| core0 / priority3，轮一 | 关闭 | 15.311秒 | 1712 | 0 |
| core0 / priority3，轮二 | 关闭 | 15.105秒 | 1666 | 0 |
| core0 / priority6，两轮 | 关闭 | 各6.148秒 | 0 | 每轮1次，拒绝 |
| core0 / priority5，两轮 | 关闭 | 6.220 / 6.232秒 | 0 | 每轮1次，拒绝 |
| core1 / priority3，两轮 | 关闭 | 各6.220秒 | 0 | 0 |
| core0 / priority5 | 默认 MIN_MODEM | 6.256秒 | 0 | 1次，拒绝 |
| core1 / priority3 | 默认 MIN_MODEM | 6.287秒 | 11 | 0 |

仅关闭 Wi-Fi 省电的真人复测仍记录 1312 / 647 次断粮；用户反馈“仍然卡顿，几乎没什么改善”。因此不能把省电模式当作主因，也不能声称仅关省电已解决。

以上对照将主因定位到 core0 上的实时采集/fetch 与低优先级 HTTP/SRC 播放任务竞争：播放任务得不到足够运行机会，TCP 接收窗口耗尽，PCM 补给速度低于输出消耗速度。把播放优先级提升到 fetch 之上（甚至与 fetch 同级）虽然消除了输出断粮，却导致 AFE 输入溢出，不能保留。移到 core1、仍低于 feed 优先级，短时对照能兼顾两条链路。

[官方 Wi-Fi 文档](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-guides/wifi-driver/wifi-performance-and-power-save.html)说明默认 Modem-sleep 会延迟接收，`WIFI_PS_NONE` 可降低实时接收延迟、代价是更高功耗。本板关闭省电后 ping 延迟有所下降，但实际播放仍失败；最终保留它作为辅助措施，以避免移核后对照中出现的短暂断粮，不将其描述为独立根因。

## 长负载的实际限制

在用户禁声指令到来前，另一次真实 30 秒固定 PCM（1,440,000B）测试已执行，core1 / priority3、关闭省电：

- 30.775秒完整消费；输出 83 次断粮，missed_eofs=0，drained=1。
- 约播放第14秒出现 AFE feed ring 满，`feed_errors=1`、`resets=1`；结束后恢复。
- 说明短回复改善不等于长负载具备充足算力余量。该结果保持失败，不以用户日常听感反馈覆盖或删除。
- 长测启动前还观察到自然 wake/prompt；独立探针并非完全隔离的整机测试。因此它证明该现场并发条件下长负载仍可能过载，尚不能把所有过载严格归因于单独一个任务。

后续应在允许测试时，先增加无原始录音的任务运行时间/AFE ring 水位统计，针对 capture/fetch 与 feed 的持续算力及内存带宽预算优化。保持 AEC、真实 TX reference 和有效输入隔离，不通过提高播放优先级、忽略 AFE reset 或放宽验收掩盖过载。本轮不再继续实机实验。

## 最终保留内容与部署

本轮生产实现只增加两处修改：

1. `esp32/firmware/main/audio_resource.c`：HTTP/SRC 播放任务 pin 从 core0 改为 core1，保持 priority3；不提高到 AFE feed/fetch 之上。
2. `esp32/firmware/main/wifi_station.c`：初始化后、启动前调用 `esp_wifi_set_ps(WIFI_PS_NONE)`，检查并返回失败。

新增离线 CLI `scripts/verify-p68-playback.py` 和 9 个 verifier 回归用例。其判据要求真实 HTTP generation 的物理 drain、零断粮/丢 EOF、每个观测到的请求终止为 completed、足够的播放数量；缺失终态或 generation 重复会失败。独立审查发现的“后一个播放未结束被前一次成功掩盖”和“重启后相同 generation 覆盖旧失败”均先复现 RED，再修复 GREEN。

不含任何自动发声/自动 wake/强制 VAD/测试 gate；未改 HA/Qwen、本地缓冲大小、DMA 队列、模型、分区、NVS、Classic 固件。HA 本轮开始时已有的整段缓冲尝试继续保留，不冒充本轮修复。

- 原芯片 app 回读与原本地 bin SHA256 一致：`fa734a78ca1dcdc50eda0a25e79aed5e69ef36aa23d9f73f3e81a068345de22e`。
- 回滚文件：NAS `/volume1/docker/tivoo-esptool/artifacts/p68-stutter-before-20261124.bin`。
- 最终正常 app：2,530,160B；SHA256 `f8484663e80758f7d3ec5de966deb80aa8b04721602123671ff3b459fa3f24cc`。
- 最终 NAS 文件：`/volume1/docker/tivoo-esptool/artifacts/p68-stutter-final-silent-20261124.bin`。
- S3 `/dev/ttyACM1`，仅写 `0x10000` app；刷写校验通过，**未复位，保持 ROM 下载模式**。没有声称该最终无探针产物在禁声指令后又完成了自然会话验收。
- 临时 NAS fixture 服务已结束/清理；生产源码及最终 bin 检索不到 `STUTTER-BENCH` 或临时 benchmark 启动函数。

## 验证与证据

最终构建成功，ruff 与 `git diff --check` 通过。ESP32 全量首次回归 153 passed（当时 verifier 6 用例）；补齐 verifier 后一次 156 passed。最后生产源码回归发生一个既有 control-bridge 连接时序用例超时（155 passed / 1 failed）；针对该文件与 verifier 重跑 17 passed，保留失败日志，不改无关控制链路来让它变绿。干净负载下完整复验 **156 passed**（exit 0，37 warnings），见 `esp32-tests-clean-recheck.txt`。该时序超时仍保留原始失败记录。

原有未提交修改未清理、未提交。本轮 review 对 verifier 的两个问题已修复并复审；最终移核代码的后续 reviewer 调用因工具额度失败，没有把它计为已通过的独立代码审查。实际硬件对照与明确未通过的长负载结果如上。

全部原始日志与临时探针源码保留在 [evidence/2026-11-24-p68-playback-stutter](evidence/2026-11-24-p68-playback-stutter/)，关键文件：

- `live-baseline-serial.log`、`baseline-tcp.txt`、`baseline-verdict.json`
- `ps-none-live-serial.log`、`ps-none-tcp.txt`
- `benchmark-comparison.json`、`benchmark-serial.log`、`scheduling-benchmark-serial.log`
- `long-benchmark-serial.log`、`long-fixture-server.log`
- `final-build.txt`、`final-silent-flash.txt`、`read-before.txt`
- `esp32-tests-final.txt`、`control-and-verifier-recheck.txt`、`esp32-tests-clean-recheck.txt`


## 基于 2317cd3 恢复 SR（2026-11-24）

用户反馈最新提交上的日常回答重新卡顿，并明确选择“恢复此前流畅的 SR 模式并提交”。此前流畅产物实际运行 `AFE_TYPE_SR / AEC_MODE_SR_HIGH_PERF`，2317cd3 中运行图与配置校验恢复为 `AFE_TYPE_FD / AEC_MODE_FD_HIGH_PERF`；旧移核结论不能直接覆盖不同 AFE 算法的实时预算。

本次只恢复 SR HIGH_PERF 的运行图、严格配置校验、日志及编译探针，并补充实际 `config_valid()` 回归：接受正确 SR 配置，拒绝混入 FD mode、FD type 或开启 playback VAD mute。测试先在旧实现上 RED，再在 SR 实现上 GREEN。双麦 MMNR、AEC、BSS、VAD/WakeNet、采样率、缓存、任务布局与优先级均保持不变。试验中的文件级编译优化、SRC 内部 RAM 缓冲与 CPU 采样探针没有保留。

所有本轮负载试验均把物理 DAC DIN（GPIO7）固定为低电平、I²S DOUT 设为 UNUSED，并禁用 wake 事件回调；GPIO dump 确认 SigOut=256（普通 GPIO 输出）。仅数字 DMA/reference 非零，没有播放测试音，也没有进行实际唤醒测试。该静默探针不代表声学 AEC 效果、打断或完整会话验收。

相同 288000B / 24kHz mono S16LE / 6秒 PCM，播放任务均为 core1 / priority3：

| 运行图 | 实际耗时 | 输出断粮 | 观测期 AFE 错误/丢帧增长 |
|---|---:|---:|---|
| FD HIGH_PERF | 93.064秒 | 17173 | 无 |
| SR HIGH_PERF 第一轮 | 6.412秒 | 41 | 无 |
| SR HIGH_PERF 第二轮 | 6.349秒 | 17 | 无 |

SR 两轮期间 feed_errors/fetch_errors/resets/capture_overruns/missed_eof 均保持0；rx_gaps固定启动累计1，ISR overruns固定39。**本次恢复解决的是 FD 引入的严重吞吐退化；41/17 次短暂断粮仍保留为未通过的零断粮指标，不能写成完全消除卡顿。** FD 的额外非线性回声抑制不再作为当前默认路径能力声明；B8.7 声学/打断/长负载及 B9 仍 HOLD。

定向回归10 passed，完整 ESP32 回归156 passed（37项既有warning）；正常 SR 固件构建成功，最终源代码不包含临时发声、静默探针或强制 wake/VAD 代码。五个代码/测试文件的独立审查未发现可操作问题。本次未修改 NAS HA/Qwen 配置。

提交内保留的可审查证据：

- [配置与时序的 RED](evidence/2026-11-24-p68-2317-stutter/sr-config-red.txt)、[定向 GREEN](evidence/2026-11-24-p68-2317-stutter/sr-config-green.txt)、[完整回归](evidence/2026-11-24-p68-2317-stutter/esp32-tests.txt)。
- [FD 基线元数据](evidence/2026-11-24-p68-2317-stutter/fd-baseline.txt)、[SR 复验元数据](evidence/2026-11-24-p68-2317-stutter/sr-validation.txt)、[对照汇总](evidence/2026-11-24-p68-2317-stutter/sr-comparison.json)。原始未提交日志继续保留在该证据目录，未将其他历史音频/构建产物纳入本次提交。
