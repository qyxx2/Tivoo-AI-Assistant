# P6.8 流式播放改进实施记录

> 后续更新：已进一步修复持续吞吐不足并重新部署，真人复测顺畅。当前固件与证据见 [CPU 预算修复报告](2026-11-25-p68-streaming-cpu-budget-fix.md)。以下保留首次改动/部署记录。

> 后续部署更新：配套HA与S3固件已部署，HA双通道恢复、S3正常启动及70.12秒AFE静默稳定性核验通过。见 [部署记录](2026-11-25-p68-streaming-deployment.md)。下文保留部署前的实施与验证状态，未宣告真人听感验收。

日期：2026-11-25，Asia/Shanghai。分支 `feature/p6-8-s3-local-wake`，HEAD `19f9114`。本次在已有 dirty 工作区继续，原修改备份于 `.superpowers/p68-streaming-improvement/before/`，没有自动提交、部署HA、刷机、复位或触发设备发声。

## 实际改进

### HA 恢复增量 PCM

删除工作区新增的 `stream.finished` 播放派发门槛和整段 `body()` 拼接。收到合法音频 delta 且本地 MIC 输入已排空后，即可派发资源；HTTP 使用 chunked 增量写出，不等待最终 `audio.done`。保留此前工作区已有的、有状态的24→32kHz转换，避免重新把SRC负担放到S3。

恢复流式后，原有的10秒数据等待超时会使“先说一段工具确认语、工具运行较久、再说结果”的合法回答中断。本次把该超时限制保留在HTTP prepare/write/write_eof，对等待下一段provider PCM则使用现有owner的45秒事件进度和120秒整轮期限。HA 2026.11.0和aiohttp TestServer均开启handler_cancellation，客户端断开会取消等待中的处理器；原有取消/连接撤销清理仍保留。

新增结束摘要 `qwen_pcm_metrics`：按session记录收到delta的最大间隔、HTTP逐块写入的最大间隔和最长写等待；失败/取消的写也在finally记录时长。不记录音频、问话、URL能力凭据。

### S3 不再靠10ms tick轮询补给

保留已有512KiB PSRAM接收环、400ms接收预填、任务优先级和核布局、AFE运行图。将接收数据、接收环空间和feeder完成的等待改为静态二值事件；输出队列写满时等待独立DMA空间事件。DMA回调将“应唤醒高优先级任务”的结果传回I2S驱动，允许及时调度。

所有事件操作都在应用portMUX临界区之外。事件存储位于内部静态RAM，生命周期不依赖可删除的任务句柄；临界区只保护队列和等待标志。feeder最后一次访问父任务栈上下文是发布原子的done状态，之后仅访问静态完成事件，再自行退出。唤醒只作提示，每次都会重查数据量、generation、STOP或完成状态，迟到信号不会变成EOF。

STOP和本地owner退休会显式唤醒接收环的数据/空间等待；匹配的输出STOP也唤醒writer。保留20ms有界等待作为故障/取消兜底，不以它作为正常补给节拍。正常EOF由消费端在最终PCM入队后立即发布，不再等待HTTP父任务重新调度后才finish_input；物理drain仍由真实DMA完成边界决定。

### 及时交付短 HTTP 片段

核对本机ESP-IDF 6.1 `esp_http_client.c:1416–1493` 后确认：`read(buffer,1024)`会跨transport read凑请求长度，只有超时/EOF等条件才把不足1024B的内容交给应用。原8秒body超时不适合连续PCM。

仅对32kHz PCM body设置40ms的transport空闲读取超时，保留原连接/响应头设置。收到部分内容照常入环，`-ESP_ERR_HTTP_EAGAIN`只表示暂时无数据、继续读；异常断开和非法EOF仍失败。**40ms不是整个HTTP read调用墙钟耗时的上界**：任务抢占以及40ms内持续到达的小片段都可能延长一次调用。该改动不能证明最近4.16秒墙钟阻塞已全部消除，仍须实机验证。

### 欠载后完整恢复，并如实计数

普通回答一旦缺少一个完整160-sample输出块，进入再预填，使用已有内部队列门槛3840 samples（120ms）后恢复；不再每来一点PCM就立即夹着静音播放。所有PCM按原顺序保留，不通过丢样本追赶时间。短句/尾包遇到EOF立即绕过门槛排空；本地提示音维持eager行为。

I2S时钟保持运行，真实TX reference仍在实际描述符EOF后记录，静音也进入真实参考。没有增加DMA长度、改采样率、关闭AEC或抬高播放任务优先级。

保留原underrun计数，另记录缺失样本数、最长连续静音补齐长度、再预填次数；第一块部分输出也计入，真实PCM隔开的多个短静音尾巴不合并成一个长间断。流中补零和恢复等待不会被写成“音频连续通过”。

### 诊断的用途与限制

feeder在观察到缺失样本增长后，最多每秒输出一次 `PCM supply` 摘要：session/generation、PSRAM环字节量、内部输出队列样本量、距最近接收的时间、feeder循环最大间隔、缺失样本和再预填计数。接收时间戳先加载、再取当前时钟，避免跨核更新产生unsigned年龄下溢。

这些是**任务恢复运行后的水位快照，不是ISR缺粮瞬间的双级水位**；feeder间隔也包含正常阻塞等待，不等于纯调度延迟。HA到包间隔同样可能受Gateway/网络/HA事件循环影响。日志可帮助缩小供给或搬运边界，不能单独把卡顿归因给Qwen或某个核。跨主机按session及事件相对关系对照，不直接相减两台机器的单调时钟。

## 验证

新增/修改的实际行为测试覆盖：

- 24k/32k流在audio.done前连续交付首块和下一块PCM；首个delta后即派发播放。
- 两个response之间的工具等待超过缩放后的HTTP写超时，HTTP与owner仍可正常结束；实际客户端断开、处理器取消及异常终态继续走清理。
- 欠载后少量PCM保持排队，达到恢复门槛再按顺序输出；EOF短尾和STOP正确处理。
- 输出队列满时DMA事件唤醒writer，STOP也唤醒；退出后不再给旧等待者发信号。
- 强制阻塞fake playback，确定512KiB接收环填满且producer已经阻塞后才释放，验证真实空间唤醒；环满时STOP同样验证唤醒而非靠兜底超时通过。
- 在应用临界区调用FreeRTOS信号API会触发测试断言；初版先RED，改为锁外静态事件后GREEN。
- 模拟短transport分片，PCM读取空闲期限小于160ms输出队列；旧8秒设置先RED，40ms设置GREEN。
- 第一块partial PCM的缺失计数、连续partial尾巴的最长单段静音长度，以及原有字节顺序、单次EOF、owner/重复STOP/故障隔离测试。

独立审查发现的两项Important（临界区内通知、工具等待误超时）均补回归后修正；partial计数、水位年龄和失败写等待统计问题也已修正。没有把软件测试通过解释为真人听感或AFE算力验收通过。

最终命令与结果、产物哈希见本报告后续“最终核验”记录。

## 最终核验

| 命令 | 结果 |
| --- | --- |
| `bash scripts/test-ha.sh tests/homeassistant tests/integration -q --tb=short` | 694 passed，271项既有库/HA warning |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32 -q --tb=short`，最终独立负载复验 | 166 passed，37项既有配置/标记/库warning |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv-sherpa/bin/python -m pytest tests/services -q --tb=short` | 140 passed，3项warning |
| Ruff：`qwen_realtime.py` 和 `test_qwen_realtime.py` | All checks passed |
| `git diff --check` | exit 0 |
| ESP-IDF 6.1 `idf.py -C esp32/firmware build` | 正常S3 app构建成功，占用约30%的8MiB app分区 |

此前并行负载下的一轮ESP32回归为165 passed / 1 failed：`test_p5b2_diagnostics.py::test_queued_records_survive_disconnect_and_replay_after_new_handshake`，第二次HELLO握手出现ConnectionResetError。该模拟器只编译本次未改动的network_listeners/control_bridge/frame_stream/diagnostics代码；未通过修改无关控制链路或放宽断言让它变绿。该文件单独重跑28 passed，随后完整ESP32复验166 passed。原失败日志仍保留，不能据复测排除其既有重连时序风险。

统一用HA Python3.14环境执行 `bash scripts/test-ha.sh -q --tb=short` 时，Sherpa七个测试文件因缺少numpy/sherpa_onnx在collection阶段失败；不是本次音频断言失败。随后使用仓库已有Python3.11 `.venv-sherpa` 独立运行全部services测试，140 passed；未安装新依赖、改锁文件或跳过这七个文件。HA/ESP32/Sherpa按匹配环境分别核验，不宣称单一环境的默认全仓命令已通过。

正常固件：

- 文件：`.superpowers/p68-streaming-improvement/tivoo_firmware-normal.bin`（同时保留标准build目录产物）。
- 大小：2,533,936B。
- SHA256：`50ab2ab37119e8624d35ba0b8260ff810621a52f17f7872867e4ff693213ff02`。
- 配套HA为当前工作区代码；没有将该产物写入任何设备。`artifact.json`记录对应源文件哈希，包含 `deployed=false, hardware_tested=false`。
- 链接图确认DMA回调、`xQueueGiveFromISR`、`xTaskRemoveFromEventList`位于内部IRAM区域。

关键验证日志与产物清单见 [evidence/2026-11-25-p68-streaming-improvement](evidence/2026-11-25-p68-streaming-improvement/)。原始完整执行日志、改前文件备份和正常bin保留于git忽略的 `.superpowers/p68-streaming-improvement/`。

## 尚需实机复核

本轮没有修改远端运行版本。需要把配套HA与S3产物部署后，在同一版本组合下复核真人短答/长答/工具等待/播放中打断，并核对输出缺失样本、再预填次数及AFE错误增量。主机C测试和编译无法证明双核CPU预算、实际Wi-Fi调度或扬声器声学连续性；本轮不宣告实际卡顿已经消除。
