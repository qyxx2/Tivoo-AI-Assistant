# P6.8 B8.7 持续数字流故障修复与实机复验

日期：2026-11-23，Asia/Shanghai。继续 `feature/p6-8-s3-local-wake`，基线 `a4469d7`，保留会话前已有的内存策略、启动顺序及配置修改。前序报告：[AFE 内存修复与失败试验](2026-11-23-p6-8-afe-memory-fix.md)。

**最终：持续数字流修复 PASS；最终无统计固件 330 秒实机日志、32 份连续 telemetry 覆盖310.52秒，严格检查 PASS。B8.7 Step 8/9 和 B9 仍 HOLD。** 本轮只处理真实 S3 的持续数字采集/AFE 链路；没有真人讲话、听音或画面确认，没有打开 test gate、声学校准 bypass 或伪造 MIC/播放完成事件。

## 1. 根因与最终保留的修复

原来的 sole capture consumer 同时调用阻塞式 `afe->feed()`；实测 feed 最长超过 60 ms 的原 ISR copy queue，甚至达到 123 ms。消费者无法及时取走原始采样，导致 overrun → RX gap → vendor reset，且重置进一步丢弃未完成块。将短队列扩容或简单把 feed/fetch 分核不能保证稳态吞吐。

另外，锁定 ESP-SR 在当前 data-cache line=32B 下的实际消费速率仍低于 16 kHz。解耦并分配双核后，约140 feed/10秒仍不足；只将 cache line 改为64B，保持容量32KB、80 MHz PSRAM、-Og及算法完全相同，55秒对照恢复约156 feed/312 fetch每10秒，gap/reset/drop不增长。两类限制分别有实际对照，不能把缓存容量、PSRAM总余量或初始化成功当作连续性证明。

最终保留：

- 新增唯一 capture owner，core0/priority8，持续排空原 ISR queue并完成双麦/TX reference抽取。原始瞬时指针当场复制进 trace，不跨任务传递。
- 有界32×5ms owned PCM queue（约17KB），通过显式 `MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT` backing storage、内部 `StaticQueue_t` 与 `xQueueCreateStatic` 建立。它是task-to-task队列，不是硬件DMA或ISR队列扩容。
- feed独占core1/priority7；fetch在core0/priority5，capture优先于fetch。队列满不阻塞采集，下一可交付包带gap；feed还独立检查样本索引，不拼接跨断流PCM。reset期间capture继续；fatal后的monitor由唯一capture owner接管。失败清理覆盖全部新增任务、queue和storage。
- defaults和实际配置均使用32KB data cache / 64-byte cache line；未切64KB cache，后者会额外消耗32KB内部heap。普通任务栈/DMA保持内部RAM，保留既有malloc阈值修复。
- MMNR、FD HIGH_PERF、AEC/BSS、VADNet/WakeNet模型、16kHz合同及所有gate保持不变。临时 `[DEBUG-stream]` / `[DEBUG-cpu]` 定位代码、FreeRTOS runtime stats全部撤回；未重新启用前轮已撤回的全局-O2或16-block ISR队列。

依据：本机锁定ESP-SR `managed_components/espressif__esp-sr/src/esp_process_sdkconfig.c` 的64B cache-line建议；本机IDF v6.1 `components/esp_system/port/soc/esp32s3/Kconfig.cache` 的heap/cache容量关系；[IDF v6.1性能与任务统计](https://docs.espressif.com/projects/esp-idf/en/v6.1/esp32s3/api-guides/performance/speed.html)、[ESP-SR AFE独立feed/fetch接口示例](https://github.com/espressif/esp-sr/blob/master/docs/en/audio_front_end/README.rst)。最终亲和、160ms队列预算及cache组合是本板实测选择，不是官方通用保证。

## 2. 本轮对照与排除过程

证据目录：[2026-11-23-p68-stream-profile](evidence/2026-11-23-p68-stream-profile/)。前轮的队列扩容、fetch分核、全局-O2均失败并已撤回，本轮先重现，不叠加旧试验。

| 对照 | 实机结果及结论 | 证据 |
|---|---|---|
| 原最终内存修复固件，32秒 | rx_gaps 48→190、reset持续增加，无成功fetch telemetry，严格RED | [baseline](evidence/2026-11-23-p68-stream-profile/baseline-boot.txt) |
| 仅分段计时，35秒 | reference缺失=0、missed EOF=0；6000次三路抽取共7,311,154us，约1.219ms/5ms块；feed平均约52ms/64ms块，ISR overruns增长 | [profile](evidence/2026-11-23-p68-stream-profile/profile-boot.txt)、[定位patch](evidence/2026-11-23-p68-stream-profile/profile.patch) |
| 原任务仅feed移core0，40秒 | 最长feed122,938us，仍丢块并出现reference过期，RED | [feed-core0](evidence/2026-11-23-p68-stream-profile/feed-core0-boot.txt) |
| 独立capture1/feed0/fetch1，55秒 | ISR overruns固定启动累计43，missed=0，但PCM队列溢出44→217、feed约133/10秒，RED；只证明采集与feed的阻塞耦合已解除 | [worker](evidence/2026-11-23-p68-stream-profile/worker-boot.txt) |
| 上一布局，仅修正queue为显式PSRAM，28秒 | internal_min 11,844→29,256，largest 20,480；内存预算恢复，但feed约130/10秒、PCM队列仍溢出，RED | [PSRAM worker](evidence/2026-11-23-p68-stream-profile/psram-worker-boot.txt) |
| capture1/feed1/fetch0，40秒 | feed约109/10秒，仍RED；停止仅凭wall time推断CPU，启用临时任务统计 | [balanced-worker](evidence/2026-11-23-p68-stream-profile/balanced-worker-boot.txt) |
| 上一布局的任务统计 | 此2mic库没有独立SE task。不能从配置 `afe_perferred_core=0` 推断存在SE owner；先前以SE共核解释布局结果的假设被任务清单否定。约31秒快照feed62%、capture29%、fetch34%，core0 idle约59%、core1约8% | [CPU统计](evidence/2026-11-23-p68-stream-profile/cpu-profile-boot.txt) |
| 仅capture移core0，45秒，32B line | 约140 feed/10秒，仍PCM drop/reset，RED | [capture-core0](evidence/2026-11-23-p68-stream-profile/capture-core0-boot.txt) |
| 仅cache line32→64B，55秒 | 5份telemetry，feed157→783、fetch310→1562；rx_gap固定1、reset0、capture_overrun0、missed0，ISR overrun固定启动40；严格PASS | [64B启动](evidence/2026-11-23-p68-stream-profile/cache-line64-boot.txt)、[判据](evidence/2026-11-23-p68-stream-profile/cache-line64-result.json) |

分段计时是含抢占/等待的wall time，不等同CPU runtime。任务统计用于确认实际任务和负载位置；`TaskStatus_t`对正在运行任务的未结束时间片可能尚未计入，单个快照差分出现大于100%的派生值，不能当作精确单次CPU成本。原始快照保留，最终连续性以真实采样计数、drop、gap/reset和时长为准。

## 3. 最终固件与长测

最终构建成功，app=2,529,296 bytes。SHA256：`8c966afac31735037dbaf75befbbd8acc8aab31e094d26339acf8c03e63f8031`，本地与NAS上传文件一致。通过现有 `tivoo-esptool` 只刷ESP32-S3 `/dev/ttyACM1` 的 `0x10000` app，Hash verified，未擦除NVS、模型或分区表。

证据：[最终构建](evidence/2026-11-23-p68-stream-profile/final-build.txt)、[本地/NAS SHA](evidence/2026-11-23-p68-stream-profile/final-app-hash.txt)、[最终刷写](evidence/2026-11-23-p68-stream-profile/final-flash.txt)。

长测命令：

```bash
python docs/superpowers/reports/evidence/2026-11-23-p68-stream-profile/capture_stream.py.txt \
  docs/superpowers/reports/evidence/2026-11-23-p68-stream-profile/final-long-boot.txt 330
python scripts/verify-p68-afe-boot.py \
  docs/superpowers/reports/evidence/2026-11-23-p68-stream-profile/final-long-boot.txt \
  --min-runtime-seconds 300
```

**最终330秒实机复验 PASS，CLI exit0 / passed=true。** 32份telemetry从11.576秒至322.096秒，连续证据覆盖310.52秒，逐份进度和报告间隔/尾部新鲜度通过，满足最低300秒要求。

- feed最终5007、fetch10014，观测增量对应约15.63 feed/s、31.25 fetch/s，输入约16k samples/s。
- feed_error=0、fetch_error=0、resets=0、missed_eof=0、capture_overruns=0；rx_gaps固定1、ISR overruns固定40。这两个值在首份telemetry前已累计，32份报告之间没有增长；不宣称上电到模型初始化期间零丢块。
- feed_max=64,643us，仍超过原60ms ISR队列的名义预算；持续采集不能重新绑回vendor feed。fetch_wait_max=120,435us含等待，不当作纯计算耗时。
- internal_min=29,256、internal/dma largest=20,480，PSRAM free约6.86MB；capture/feed/fetch stack water=2780/2056/1788 bytes。Wi-Fi成功连接，无panic或初始化错误；task stats与临时debug代码已移除。
- 这是Wi-Fi在线、真实双麦/参考/AFE持续运行的数字检查，没有真实Qwen回复或AUX播放负载，不替代后续声学和打断验收。

证据：[完整长测](evidence/2026-11-23-p68-stream-profile/final-long-boot.txt)、[严格判定](evidence/2026-11-23-p68-stream-profile/final-long-result.json)、[速率与首尾计数](evidence/2026-11-23-p68-stream-profile/final-summary.json)。

## 4. 回归、审查与判据

- 实际C capture/feed/fetch owners的host用例验证：feed不运行时capture连续交付16块，随后逐样本检查三路owned PCM与MMNR的N=0；队列满后的gap与reset，reset期间继续capture，fatal后的唯一monitor接管。此脚本化RTOS测试不证明真实80ms ISR调度，后者仍以实机为准。
- reset-drain回归额外做mutation：临时让capture等待reset，断言 `captured->count==8` 确实RED，恢复代码GREEN；变异未保留。
- CLI新增drop计数增长但gap尚未被feed消费的反例，3 RED→6 GREEN。独立审查又复现“10/20秒健康、330秒只剩heartbeat”的静默卡死误报；补齐逐相邻报告进度、最大20秒报告间隔/尾部新鲜度、明确最低观测时长，5 RED→11 GREEN。最终长测强制 `--min-runtime-seconds 300`，不以两行早期日志代替长时间证据。
- 独立只读审查发现并核对了两个问题：FreeRTOS动态queue强制内部RAM（已改静态控制+显式PSRAM），旧CLI可误计静默停滞（已修正）。最终复审未发现新增actionable问题，审查不代替物理验收。
- 完整ESP32最终回归 **145 passed**（exit0；37项既有环境/弃用warning），`git diff --check`通过。见[最终测试记录](evidence/2026-11-23-p68-stream-profile/final-esp32-suite.txt)。未改HA/Sherpa代码，本轮不复用旧957项结果作为新验证数。

## 5. B8.7/B9范围

数字持续性仅是上游阻塞项。本轮长测PASS不代表真实wake→prompt→Qwen/MCP→SRC→AUX、播放期间barge-in、matching completed后的单次4秒续聊或声学质量通过。提示音声学校准和test gate没有打开；没有用模型audio.done或伪造MIC/completed核销物理项目。B8.7 Step 8/9继续未勾选，B9继续HOLD。
