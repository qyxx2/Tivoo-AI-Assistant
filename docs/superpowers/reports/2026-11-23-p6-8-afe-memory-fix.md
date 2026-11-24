# P6.8 AFE 内存初始化修复与自动化续验

> 同日最新续验：持续数字流已通过最终固件330秒日志/310.52秒telemetry严格检查（145项ESP32回归通过）。采集与阻塞feed解耦、显式PSRAM PCM队列、capture0/feed1/fetch0及64B cache line为最终组合；B8.7声学/播放/打断/续聊与B9仍HOLD。见[持续数字流修复报告](2026-11-23-p6-8-stream-throughput-fix.md)。

日期：2026-11-23，Asia/Shanghai。基线 `a4469d7`，在原 feature checkout 上继续，保留会话前已有固件/测试修改。本轮无人参与讲话、听音或屏幕确认。

## 1. 已证实的内存根因与修复依据

实机自动复位复现 `Local wake unavailable: ESP_ERR_NO_MEM`。临时定位日志进一步分离了各分配阶段：

| 阶段 | 结果 |
|---|---|
| AFE 模型/实例 | 成功，MMNR、FD HIGH_PERF、AEC/BSS、vadnet1_medium、wn9_hilexin |
| input / flow 的 PSRAM 分配、control queue | 均成功 |
| 4096-byte feed task | 成功 |
| 4096-byte fetch task | 失败；此时 internal free=5063 bytes，largest block=1792 bytes |

问题是内部 RAM 连续块不足，不能以 PSRAM 尚余约 6.9 MB 或内部总空闲约 5 KB 推断任务栈可分配。将 `CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL` 从默认 16384 降为 1024，让普通大于 1 KB 的分配优先使用 PSRAM；保留普通任务的内部栈、32 KB 内部 reserve、DMA/ISR 内部存储。未改 AFE 算法组合，未降低模型或关闭断流门控。

只改阈值的第一次实机复验已不再出现初始化错误，两个任务启动后 internal free=37347、largest=24576。临时 `[DEBUG-afe]` 定位代码随后移除。

对应真实资料：

- [ESP-IDF v6.1 外部 RAM：malloc 阈值、显式 capability 与 internal reserve](https://docs.espressif.com/projects/esp-idf/en/v6.1/esp32s3/api-guides/external-ram.html)。本机 v6.1 的 `components/esp_psram/Kconfig.spiram.common` 同时核对了配置定义；数值 1024 是本项目通过实机选择的预算，不是文档承诺的通用推荐值。
- [ESP-IDF v6.1 FreeRTOS：task stack 以字节计、core affinity](https://docs.espressif.com/projects/esp-idf/en/v6.1/esp32s3/api-reference/system/freertos_idf.html)。没有把 `ALLOW_EXT_MEM` 误当作普通任务栈自动迁移开关。
- [ESP-SR AFE 输入/Feed/Fetch 接口](https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/audio_front_end/README.html)，并核对本项目锁定的 ESP-SR 2.6.1 头文件与 `AFE_MEMORY_ALLOC_MORE_PSRAM`。MMNR/16 kHz 合同保持原样。

## 2. 继续测试揭示的吞吐问题

内存初始化修复后，持续性检查仍为 RED：RX gap/reset 持续增加。下一次定位显示 reference_valid=1、missed EOF=0，但软件队列 overruns 增加；AFE feed 最长 65733 us，原 ISR copy queue 为 12×5 ms=60 ms。

新增真实 capture/ISR host 用例：消费者暂停 70 ms，期间产生 14 个 DMA 回调，然后读取并验证精确连续样本索引，重复 10 次并跨 DMA ring wraparound。原代码失败；软件队列增加为 16×5 ms=80 ms 后通过。硬件 DMA 仍为 12 blocks；队列仍位于内部 BSS，增加 5152 bytes；TX reference history 仍为 160 ms。依据：[I2S 防丢数据：根据最大消费间隔确定缓存](https://docs.espressif.com/projects/esp-idf/en/v6.1/esp32s3/api-reference/peripherals/i2s.html#how-to-prevent-data-lost)。该原则用于应用层 ISR copy queue，不能把它描述为更改了硬件 DMA 参数。

但队列扩容单独的 65 秒实机复验仍 RED，不能据 host 用例声称持续吞吐修复。随后将 fetch 移至 core0、feed 保留 core1，45 秒观测可产生有效 fetch，但仍有 gap 增长：首个 10 秒报告 feed=113/fetch=179，之后约每 10 秒只增加 114 次 feed，低于 16 kHz/1024 samples 应有的约 156 次。该中间结果也没有计作 PASS。

第三组单变量试验从 `-Og` 切到 `CONFIG_COMPILER_OPTIMIZATION_PERF=y`，保留断言开启，依据 [ESP-IDF v6.1 性能指南的 -O2 建议](https://docs.espressif.com/projects/esp-idf/en/v6.1/esp32s3/api-guides/performance/speed.html)。构建、刷写哈希校验成功，但 45 秒实机检查仍 RED：首个报告 feed=132/fetch=234、gap=30/reset=29；30 秒后 feed=526/fetch=906、gap=137/reset=136，overruns=228、missed EOF=0。没有 panic 或新的初始化内存错误，但持续吞吐仍不足。

三组试验均未恢复连续流，因此**队列扩容、fetch 分核、-O2 配置及其专用 burst 测试不纳入最终修复**，已从工作树撤回；试验源码与 RED/GREEN 记录存入证据目录。最终保留 malloc 阈值修复、实际 Wi-Fi 配置一致性检查与不会误报的真实启动日志验收工具。后续需对采集/抽取与阻塞 feed 的耦合路径做时序/CPU profiling 和模块划分评估；本轮没有继续尝试第四组参数。

## 3. 最终实机结果

**最终内存初始化：PASS；持续数字流：FAIL；B8.7/B9：仍 HOLD。** 最终工作树与实机已撤回上述三组未通过试验，保持原队列和任务调度，仅保留已验证的内存策略与配置一致性修复。

最终固件重新构建 exit 0，使用 NAS `tivoo-esptool`、`--chip esp32s3 --port /dev/ttyACM1 --baud 460800` 只写 `0x10000` app，`Hash of data verified.`，exit 0；未擦除 NVS/模型/分区表。设备为 ESP32-S3 rev v0.2，MAC `b8:1f:3f:aa:82:e0`，16 MB flash / 8 MB PSRAM。

- app：2,528,752 bytes；SHA256 `8a94e5a2fe91b49f5e61ffeb8c2a99f6733c8f6b9cd4b0ccfe2981f44bb49d82`；NAS 上传文件 SHA 与本机构建一致。
- 刷写完成后再次自动复位，采集 25 秒完整启动日志。PSRAM memory test OK；两个 AFE 任务成功建立，没有 `ESP_ERR_NO_MEM`、`Local wake unavailable` 或 panic；internal free=37363、largest=24576，PSRAM free=6878708，Wi-Fi `.40` 连接成功。
- 同一新日志执行 `verify-p68-afe-boot.py --initialization-only`：exit 0，passed=true；默认严格模式：exit 1，passed=false。约 11.8 秒时 gap=53/reset=41，约 21.9 秒时 gap=123/reset=89；不能把初始化 PASS 扩大为音频连续性 PASS。
- Qwen 最终 health 仍为 ready，Frontend MCP initialized/ok、homeassistant ready、46 tools；本轮未重复模型 MCP 调用或回滚演练。

最终证据：[刷写](evidence/2026-11-23-p68-afe-memory/retained-flash.txt)、[启动](evidence/2026-11-23-p68-afe-memory/retained-boot.txt)、[初始化检查 PASS](evidence/2026-11-23-p68-afe-memory/retained-init-result.txt)、[持续性检查 FAIL](evidence/2026-11-23-p68-afe-memory/retained-runtime-result.txt)。

## 4. 软件回归、配置一致性与审查

- ESP32 最终撤回试验后全部 Python/host 测试：137 passed；包括 3 个新增日志验收 CLI 用例。[结果](evidence/2026-11-23-p68-afe-memory/esp32-final-suite.txt)
- HA 与 integration：680 passed。[结果](evidence/2026-11-23-p68-afe-memory/ha-suite.txt)
- Sherpa/Wyoming：使用独立 Python 3.11 runner，140 passed。[结果](evidence/2026-11-23-p68-afe-memory/sherpa-suite.txt)
- 原有私有 sdkconfig 与 tracked defaults 的 Wi-Fi 8/10 buffer、2/10 BA window 漂移已统一为实际使用的 RX=10、TX=10、BA=2，并由 configure 测试比较持久 defaults 与实际配置。
- 新增 `scripts/verify-p68-afe-boot.py`：默认要求至少两次增长的 feed/fetch telemetry、无 feed/fetch error、无 gap/reset 增长、无 unavailable/fatal tail；`--initialization-only` 明确只验启动，不宣称持续性/声学通过。
- 独立只读审查发现初版日志检查会把“早期正常、随后失败”的日志误计 PASS。两个反例先 RED 后 GREEN，已修正；队列新改动审查未发现 actionable defect。审查明确指出 host burst 用例不能证明持续吞吐或实机内存余量。
- 测试环境准备：HA suite 最初因 `.venv` 缺少已在 `requirements_test.txt` 声明的 `wyoming==1.10.2` 而 collection 失败，安装该固定版本后重跑通过。将 ESP32 socket fixture 与 HA runner 混跑时被 HA 全局 socket guard 拒绝，改用各组件正式环境分组执行；没有修改生产代码规避失败。

## 5. B8.7 范围

本轮检查时 HA 已连接 S3 `.40` 并占用单客户端 7777/7778；独立探针作为第二个客户端被 EOF 拒绝，不能将其解释为固件握手失败，也不计为本轮独立 owner 验收通过。本轮没有修改 HA 目标地址。

证据目录：[2026-11-23-p68-afe-memory](evidence/2026-11-23-p68-afe-memory/)。重点原始记录：[分配点定位](evidence/2026-11-23-p68-afe-memory/instrumented-boot.txt)、[仅阈值修复启动](evidence/2026-11-23-p68-afe-memory/threshold-boot.txt)、[分核试验](evidence/2026-11-23-p68-afe-memory/split-boot.txt)、[-O2 试验](evidence/2026-11-23-p68-afe-memory/perf-boot.txt)、[严格检查仍失败](evidence/2026-11-23-p68-afe-memory/perf-runtime-result.txt)。

提示音声学校准仍关闭，test gate 仍关闭。即便数字 AFE 稳定，也不能据此自动关闭真实 wake→prompt→Qwen→SRC→AUX、播放期间 barge-in、completed 后问号 4 秒续聊与声学质量 GAP。B8.7 Step 8/9 和 B9 release gate 继续按实际证据核销，不以模型 `audio.done` 或伪造 MIC session 代替物理播放。
