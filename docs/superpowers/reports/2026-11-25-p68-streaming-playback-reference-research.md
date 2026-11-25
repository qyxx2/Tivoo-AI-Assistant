# P6.8：同类 ESP32-S3 流式播放实现核查

日期：2026-11-25（Asia/Shanghai）。本报告为源码/官方文档研究，不代表本机硬件验收，也不修改生产实现。

## 结论

三类参考实现的共同思路是把接收、转换和实际输出以有界队列隔开，让 I²S 的供给不直接跟随网络分片节奏；没有依据要求 HA 等完整 Qwen 回答才传输。对 Tivoo 的建议是恢复 HA 增量发送，同时在 S3 保留“网络抖动容量”和“可及时执行的输出工作”两层缓冲。仅扩大 PSRAM 缓冲并不能解决写 DMA 的任务本身长期无法调度；下面给出的容量、门限及调度建议均为工程推断，须用本项目实测决定。

## 版本边界

- 小智主线固定到 `9101335f121cb7fa4c38a3fe24101ee340d6730a`（提交时间 2026-11-24T00:10:27Z）。[固定版本](https://github.com/78/xiaozhi-esp32/tree/9101335f121cb7fa4c38a3fe24101ee340d6730a)。
- ESPHome 开发主线固定到 `b16e064f33981281daec174b1ba526fed8ea78d2`（提交时间 2026-11-24T16:46:23Z），并非声称这些细节都已进入稳定发行版。[固定版本](https://github.com/esphome/esphome/tree/b16e064f33981281daec174b1ba526fed8ea78d2)。官方网页当前标识为 2026.11.0，源码中的后续细节以固定提交为准。[I²S speaker 文档](https://esphome.io/components/speaker/i2s_audio/)。
- Espressif ADF/GMF 文档读取 `latest`（2026-11-25 检查），其内容可能随后变化；内存约束另查 ESP-IDF v5.5 固定版本。

## 小智：压缩包队列、PCM 队列、输出任务分开

网络数据交给 `PushPacketToDecodeQueue()`；`OpusCodecTask()` 解码/重采样后进入 PCM 播放队列，`AudioOutputTask()` 单独调用 codec 输出，操作输出时已释放队列互斥锁。任务配置为 input priority 8/core0、output priority 4（不固定核）、codec priority 2（不固定核）。满队列等待带 service-stop 与 playback-generation 检查，取消后旧数据不能继续入新代队列。[固定 audio_service.cc](https://github.com/78/xiaozhi-esp32/blob/9101335f121cb7fa4c38a3fe24101ee340d6730a/main/audio/audio_service.cc#L120)。

配置的 Opus 帧长是 60ms；decode queue 容量为 `1200/60=20` 包，PCM queue 容量为 2 帧。这是**容量上限，不是必须先攒 1.2 秒才播放**。在解码前即可接收后续包；不依赖整段音频结束。[固定 audio_service.h](https://github.com/78/xiaozhi-esp32/blob/9101335f121cb7fa4c38a3fe24101ee340d6730a/main/audio/audio_service.h#L40)。

AFE 和 codec I/O 分工明确；本版本默认输入为单麦 M/MR，多麦为显式实验配置，不能拿它的任务优先级直接推断 Tivoo 双麦 MMR 的 CPU 余量。文档明确 AEC 在可唤醒/处理语音时保持活动；不能借“别人这样做”而关闭本项目 AEC、第二麦或打断能力。[固定架构说明](https://github.com/78/xiaozhi-esp32/blob/9101335f121cb7fa4c38a3fe24101ee340d6730a/main/audio/README.md)。

## ESPHome：软件 ring buffer 与 DMA 独立

官方 I²S speaker 的 `buffer_duration` 默认 500ms，并说明增大可减少卡顿、增加内存；这同样是 ring buffer 的容量说明，不是 500ms 首音预填承诺。[官方配置](https://esphome.io/components/speaker/i2s_audio/#configuration-variables)。

`play()` 仅向软件 ring 写入，不能全写时返回实际写入字节；Voice Assistant 每次最多递交 4KiB，保留未写尾部，下个 loop 重试。这样高层不必阻塞等待物理播放。[固定 speaker 实现](https://github.com/esphome/esphome/blob/b16e064f33981281daec174b1ba526fed8ea78d2/esphome/components/i2s_audio/speaker/i2s_audio_speaker.cpp#L230)、[固定 VA 实现](https://github.com/esphome/esphome/blob/b16e064f33981281daec174b1ba526fed8ea78d2/esphome/components/voice_assistant/voice_assistant.cpp#L701)。

标准 speaker 在本开发快照配置 5 个约 10ms DMA 块，独立任务持续写；初始化预装静音，之后每块写真实音频并补零到块边界，以阻塞 I²S 写自然节拍运行。还维护 write-record 与 DMA EOF 对应关系，丢事件时重同步。此处补零维持数字链路和计数一致性，并不代表缺失的语音已修复；不能将其当成“零卡顿”。[固定 standard speaker](https://github.com/esphome/esphome/blob/b16e064f33981281daec174b1ba526fed8ea78d2/esphome/components/i2s_audio/speaker/i2s_audio_speaker_standard.cpp#L23)。

speaker priority 在该版本为 19；resampler 是另一任务。可借鉴“轻量输出优先于重转换”的职责分离，不能直接复制数值到 Tivoo，否则可能挤占现有 AFE feed/fetch。[固定 speaker header](https://github.com/esphome/esphome/blob/b16e064f33981281daec174b1ba526fed8ea78d2/esphome/components/i2s_audio/speaker/i2s_audio_speaker.h#L23)、[固定 resampler](https://github.com/esphome/esphome/blob/b16e064f33981281daec174b1ba526fed8ea78d2/esphome/components/resampler/speaker/resampler_speaker.cpp#L263)。

## Espressif：不同速率阶段通过 ring buffer 隔离

ADF 传统架构以 ring buffer 连接 HTTP reader、decoder、I²S writer。GMF 官方进一步明确：上游与下游速率差异大时拆成两条 pipeline，以 ring buffer 桥接，每段有独立任务和栈/优先级；单条本地文件 pipeline 也可以由同一任务驱动。因此“必须一元素一任务”并非通则，网络阻塞隔离才是本场景要点。[ADF pipeline](https://docs.espressif.com/projects/esp-adf/en/v2.0/api-reference/framework/audio_pipeline.html)、[GMF topology](https://docs.espressif.com/projects/esp-gmf/en/latest/gmf-framework/gmf-core/gmf-core-overview.html#bridging-two-pipelines-with-a-ringbuffer)。

官方开发说明建议大缓存/codec 工作集放 PSRAM，实时 DMA/中断路径按需要显式选 internal RAM；同页建议通过任务 runtime stats 测量忙核，缓冲抗抖动需付出延迟，不能通过提高 WDT 超时掩盖忙核。文档同时讨论 AFE feed/fetch 的核布局，具体选择仍需看本机实际任务图。[官方开发说明](https://docs.espressif.com/projects/esp-adf/en/latest/knowledge-center/design-considerations.html)。

ESP-IDF v5.5 说明 `MALLOC_CAP_DMA` 选择 DMA 合适内存，通常排除外部 PSRAM，同时也明确 S3 EDMA 的外部内存支持存在组合能力/对齐要求；因此不能泛称“S3 的任何 DMA 都绝不支持 PSRAM”。对现有 Tivoo 驱动，先保留内部 DMA 缓冲，仅把大抖动缓存放 PSRAM更便于控制变量。[固定 IDF 内存文档](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32s3/api-reference/system/mem_alloc.html#dma-capable-memory)。

## 对 Tivoo 的实施建议（推断，未硬件验证）

1. HA 的 stream 在首批输出满足现有输入排空约束后即可通知 S3；HTTP 使用增量 body，不以 `audio.done`/`finished` 作为首包门槛。允许在 HA 增量 24→32kHz SRC，从 S3 移出重采样计算，但转换器状态必须跨 delta 保留。
2. S3 接收者只读网络并入有界 ring，不直接等待播放完成；消费者只做固定小块搬运/输出，网络读超时不得占住输出任务。若已有类似双任务实现，下一步应测 ring 水位和调度等待，不再重复堆相同层。
3. 32kHz mono S16LE 每秒 64,000B：500ms 软件缓存约32KB；容量与启动门限必须分开配置。主线程最新真人日志已观察到512KiB ring、400ms预填仍失败，HTTP最长4.16秒；这说明不能从ESPHome默认500ms容量推断“再预填500ms就会好”，更不能把8秒容量当作实际拥有8秒存量。门限须有上下限并按已观测到的到达抖动适配，先解释长阻塞期间的实际水位与调度原因。输出 DMA 窗口则覆盖实际 writer 最坏调度延迟；单个 descriptor 大小、总个数不能仅随意翻倍。
4. 欠载时保持 I²S 时钟/真实参考连续，输出短静音，进入有限再预填后继续；如实现淡出/淡入，应以最终实际输出样本供给 AEC reference。不要把合成静音算作已成功播放真实语音，也不要丢未输出的 PCM 来美化延迟。
5. 每代记录 ring min/high-water、空缓冲持续时间、最长 producer/write 调度空洞、实际 DMA EOF、真实/补零样本数。仅 `completed` 或网络吞吐充足不构成连续播放证据。
6. Opus 可减少链路带宽，却增加编码/解码、分帧及 CPU 工作；现有局域网 PCM 只有约384kbps（24k）/512kbps（32k），在已知任务竞争时先换 Opus 没有充分依据。优先修复 PCM 的实时供给，随后再以 CPU/profile 和网络实测决定是否引入压缩协议。

验收至少包括短答/长答、突发网络间隔、边播放边真实唤醒、取消清空与重连。要求 HA 首字节早于 provider audio.done，S3 零非预期输出断粮/EOF丢失，AFE 错误计数不增加；同类项目源码只能提供设计证据，不能替代 Tivoo 真人声学测试。

本地交叉核对边界：主线程另发现早期 split 方案虽输出零断粮，却有 AFE reset/capture 丢失；因此上面的任务分离是职责模型，不意味着重新照搬已被本机 AFE 数据否决的优先级方案。最新真人失败及历史数字的原始日志归主线程主报告展开，本研究未独立重跑物理测试。
