# P6.8 流式播放卡顿调查

日期：2026-11-25，Asia/Shanghai。分支 `feature/p6-8-s3-local-wake`，HEAD `19f9114`，保留原有未提交修改。本次为诊断与方案研究，没有修改生产代码、重启服务、刷机或触发设备发声。

## 结论与证据边界

**应恢复 HA 真正的增量输出，并把 S3 播放视为有期限的连续供给系统。继续等待整段生成、只增加 PSRAM 容量或直接照搬任务优先级，都缺乏成功证据。**

目前能确认“回答数据未持续进入输出队列”，尚不能把今天凌晨真人轮次的全部阻塞唯一定位为 Wi-Fi、lwIP、HTTP 任务调度或 HA 写入节奏。`esp_http_client_read()` 的墙钟时间包含任务被抢占的时间，不能直接称为网络传输时间。现有日志缺少欠载发生瞬间的接收环水位、HTTP 到包时刻和 feeder 调度延迟。

## 最近几轮实测

旧报告 `2026-11-24-p68-playback-stutter.md` 的“移核改善”是历史结论。其后已出现 FD/SR 切换、双麦处理、接收环和优先级变更，不能把旧短测结论套在当前版本上。

| 证据 | 结果 | 意义 |
| --- | --- | --- |
| 保存的 `2026-11-24-p68-full-buffer-serial.log`，真人 generation 4/6 | 1171/4049 次 underrun；src_ms=0；missed_eofs=0；本地提示音为0 | 完整缓存与取消 S3 SRC 都不能保证连续播放 |
| `/tmp/p68-real-playback-acm1.log`，保存于11月25日00:42，真人 generation 3 | 512 KiB接收环，prefill=25600B，high_water=25600B；read累计37794ms，最大4160ms；1324次underrun；src_ms=0；missed_eofs=0 | 大环没有积累余量，主要证据指向上游供给/接收阶段；不能仅凭这个最大值断定每次欠载都发生于环空 |
| 同轮 AFE | feed/fetch errors、resets、capture_overruns均为0；启动累计rx_gaps=1、overruns=42未增长 | 该轮没有“播放改善却破坏采集”的证据；不能以此证明仍有充足CPU余量 |
| 400ms缓冲固定输入，6秒/30秒 | 133/407次underrun；30秒环峰值310272B | 单个全程峰值无法区分某一时刻环空还是feeder未调度 |
| split调度固定输入，6秒/30秒 | 播放零underrun，但AFE resets增长到40、capture_overruns至少990 | 拒绝此方案，播放零断粮不能抵消采集破坏 |
| 放大TCP窗口后的固定输入，6秒/30秒 | 6.344/30.529秒，输出零underrun；观测期AFE未增长故障 | 证明该配置在固定PCM负载有改善；不能替代真人、实际HA资源与流式抖动测试 |

今天凌晨真人轮次从 `buffering` 到 `playing` 为4680ms。`playing` 是当前网络侧按接收字节数发出的状态，不等于DAC首个非零样本；该时差不能直接当精确声学首音延迟。

安全摘录和源文件SHA保存在 [evidence/2026-11-25-p68-streaming-analysis](evidence/2026-11-25-p68-streaming-analysis/)。不保存用户问话、原始录音、SSID或凭据。

实际执行：

```bash
python scripts/verify-p68-playback.py /tmp/p68-real-playback-acm1.log
```

退出1：`passed=false`，generation 3为`drained=true, underruns=1324, missed_eofs=0`。这是离线重放真实失败轨迹，不是新实机实验。

## HA 确实失去了流式语义，而且部署版本与工作区不同

只读获取NAS实际HA文件后核对：

- NAS部署版：`QwenPcmStream.chunks()` 在 yield 第一个PCM块前等待 `finished`，HTTP可以先返回响应头，但音频要等 `audio.done`。
- 当前工作区：`_open_output()` 等待 `stream.finished` 才发播放命令；`get()` 又调用 `body()` 收齐整段、拼接、设置Content-Length后一次写出。新的整段写出尝试还没有与NAS文件一致。
- 两者都不是边生成边播放。诊断时必须记录部署版哈希，避免把未部署改动归为真人实测已验证。

对真实生产类做AST提取，使用实际aiohttp TestServer，推入1280B PCM而保持 `finished=False`：

```text
工作区：headers_before_done=False pcm_before_done=False
NAS文件：headers_before_done=True pcm_before_done=False
```

两个路径都没有在 `audio.done` 前交付首块PCM；本地探针退出1。没有用假音频通过设备播放。

恢复时应保留每个stream有状态的24k→32k转换器，移除所有整段完成门槛，首次合法 `audio.delta` 且本地输入已结束即可下发资源；HTTP逐块write且检查背压、超时、取消。`input_drained`、会话/generation校验、单次GET及物理drain必须保留。工具后续response与失败撤销仍按现有owner协议处理，不能把“恢复流式”等同于提前宣布最终回答成功。

## S3 当前代码做对了什么，还缺什么

已有 `HTTP producer → PSRAM环 → pcm_feed_task → 内部输出队列 → DMA`，方向正确，不需要再发明一层整段缓存。

按32kHz、16bit、mono计算：

- 消耗64000B/s。512KiB是8.192秒**容量**，不代表已缓冲8秒。
- 接收预填25600B是400ms；内部5120 samples队列是160ms，预填3840 samples是120ms。
- DMA为12×160 samples，即60ms物理尾部。加大DMA会影响停音上限与AEC参考时序，不应作为首选。
- 最新真人接收环峰值只有400ms；不能期待它抵御数秒读取停顿。即便缓存3秒，持续供给低于实时消耗时仍然会耗尽。
- `vTaskDelay(1)` 在当前100Hz配置是一个10ms tick，明显粗于5ms输出块。它不是已证实根因，但实时补给应由水位/空间事件唤醒，减少轮询和任意延时。
- 当前仅初次播放有预填，启动后 `in_dma` 使队列只要有一点数据就继续输出；没有欠载后恢复高水位的状态。供给抖动时可能反复“少量PCM—静音”。
- `playing` 在producer端按累计接收量触发，不应被当作物理开始；`completed`只说明结束与drain，现有代码允许中间严重卡顿后仍报告completed。
- underrun目前仅统计空块，部分块不足160 samples的补零没有计入；应增加缺失样本数、最长连续空窗以及时间分布，避免改变统计方式后误以为性能变好。

## 同类方案与推荐取舍

一手源码和固定提交详见 [同类项目研究](2026-11-25-p68-streaming-playback-reference-research.md)。共同点是网络/解码/硬件输出有界解耦，输出任务独立运行；容量、预填、播放结束是不同概念。

推荐分两步推进，首先保持HTTP与PCM32k协议：

1. **恢复流式并建立可定位的数字链路。** 保留现有接收环，HA逐块SRC/写出，S3 producer只读网并入环。播放writer仅负责固定小块搬运；用任务通知或信号量在数据到达和输出队列释放空间时唤醒，ISR只做有界操作并发通知。不在ISR访问PSRAM、重采样或打印日志。重采样仍放HA，不把Opus引入当前紧张的AFE预算。
2. **测出供给缺口后做有限预填和恢复。** 400ms先作为对照值，初始可比较200/400/800ms；这是待验证参数，不是已确定最优值。短句EOF必须立即排空，欠载后进入单次rebuffer，攒到恢复水位再继续，避免碎片化恢复。保持I2S时钟运行、输出明确零样本，AEC参考记录实际发出的PCM/静音；所有等待能被STOP立即打断。不能仅清零underrun计数掩盖rebuffer，必须单独记录暂停次数与总时长。

最有价值的下一次测量是在**每次缺粮的首次边沿**记录：generation、累计接收/消费字节、接收环当前水位与短窗最低值、内部队列水位、最近数据到达距今、feeder上次运行距今、连续缺失样本数；每秒汇总，避免串口日志本身干扰调度。另记录HA各chunk生成/写出间隔和write等待，用同一会话关联；跨主机用各自单调时间与事件相对顺序，不直接相减不同主机时钟。

判别规则：

| 欠载时观测 | 下一步 |
| --- | --- |
| PSRAM环仍有足量数据、内部队列空 | 查feeder调度延迟、临界区与拷贝，调整writer期限/亲和性；加大接收环没有帮助 |
| PSRAM环空、HA已连续写出 | 对齐TCP窗口/重传抓包和HTTP任务运行时间，定位Wi-Fi/lwIP/应用读调度 |
| PSRAM环空、HA写出也有空窗 | 区分provider生成间隙、转换耗时、HTTP背压；背压也可能由S3停止读引起，不能直接归因Qwen |
| 输出missed_eofs增长 | 单独处理ISR/临界区时限，普通jitter buffer无法修复漏EOF |

其他选择：Opus可减少链路字节数，但增加编码/解码、协议与CPU负担；本机已有AFE算力竞争，只有证实网络带宽是瓶颈再考虑。整体改为ADF/GMF pipeline可获得成熟分阶段框架，但当前有真实TX参考、owner和drain合同，迁移成本高，应先修现有阶段边界。小智的任务优先级及AFE成本不能直接照搬到本机双麦MMNR/BSS图。

## 验收应同时覆盖什么

1. 软件流式回归：不发送 `audio.done`，先推一个PCM块，必须已经得到播放命令和HTTP音频；第二个块稍后到达仍保持转换状态与样本连续；STOP能取消等待与HTTP处理器。
2. 数字对照：相同24k输入/32k输出，6秒和30秒，分别从本地内存源、NAS固定HTTP源、HA分块资源播放；再注入50/150/300ms到包抖动。每轮都核对缺失样本、rebuffer、missed EOF以及AFE计数增量。可静默验证数字DMA，但不能替代声学/真人验收。
3. 真人短答、长答、追问和播放中打断；首块真正进入DMA应早于最终audio.done（对确实逐段生成的长答）；输出连续、AFE不丢帧、不reset，且停音尾部符合既有合同。不能以固定正弦零underrun替代实际HA流式资源通过。

原工作区缓冲/worker定向测试实际重跑22 passed。默认pytest启动受全局HA插件的 `httpx2.alias_httpx()` 导入冲突阻断；禁用自动加载插件后运行ESP32纯host测试通过，出现两项HA配置未加载warning。未声称HA全量回归或新固件实机验收通过。
