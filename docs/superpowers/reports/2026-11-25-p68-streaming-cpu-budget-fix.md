# P6.8 持续播放卡顿：CPU 预算修复与部署

日期：2026-11-25，Asia/Shanghai。继续保留当前分支及未提交工作区。本报告接续当天流式改进与部署记录。

## 结果

正常修复固件已部署，独立 flash 校验通过。用户在部署后真人复测反馈“播放顺畅”；同轮 generation=2 日志为 underruns=0、missing_samples=0、rebuffers=0、missed_eofs=0、drained=1，验收脚本 passed=true。HA 两条设备连接均 ESTABLISHED。此结论覆盖本轮回答与数字对照，尚非长时间稳定性验收。

## 现场证据与根因

用户首次回复“已复现”的补采会话 944c4421-e2de-4bf4-8c27-3128f151b347：560 次欠载、89600 个缺失采样（32 kHz 下累计 2.8 秒）、27 次重新缓冲。AFE feed/fetch 错误、reset、capture_overrun、missed EOF 均为零。接收缓冲峰值仅 25600 B；Qwen 已结束生成时 S3 仍在慢慢收尾。未保存串口的原 10:25 会话没有被冒充成这轮现场证据；补采打开串口时出现过新的 USB reset。

只接收、不播放的隔离实验仍需 8.129 秒才能接收 6 秒的 chunked PCM。CPU0 idle=0，capture=32.15%、fetch=46.36%、HTTP=11.37%、TCP=4.85%、Wi-Fi=3.75%，并出现接收端 TCP 零窗口。供给慢在 S3 接收与计算预算，而不是必须等待 Qwen 生成完成。400 ms 初始预填只能暂时掩盖持续吞吐不足，符合“只有开头几个字流畅”的现象。

当前 SDK 原为默认 -Og。将整个应用与 SDK 切为 CONFIG_COMPILER_OPTIMIZATION_PERF=y（-O2），降低采集、HTTP 与网络处理开销，保留断言和调试符号。官方说明：[ESP-IDF 性能优化](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-guides/performance/speed.html)。安装的 ESP-IDF v6.1 Kconfig 及最终 compile_commands 均验证 -O2 已生效，覆盖 capture、AFE、HTTP client、lwIP sockets。

## 同设备数字对照

临时探针运行完整 AFE 与真实 HTTP/PCM/DMA 输出路径，但 DAC GPIO7 拉低且 I2S DOUT 取消映射，避免自动发声；下表是数字链路证据。6 秒输入为 384000 B 的 32 kHz 单声道 S16LE；paced 为每 8 ms 发送 1024 B，供给快于播放。

| 输入 | 原 -Og 耗时 / 欠载 | -O2 耗时 / 欠载 |
| --- | --- | --- |
| bulk 6 秒 | 7.510 秒 / 197 | 6.344 秒 / 0 |
| chunked 6 秒 | 10.434 秒 / 698 | 6.471 秒 / 0 |
| paced 6 秒 | 10.320 秒 / 668 | 6.528 秒 / 0 |
| paced 30 秒 | 未测原配置 | 30.530 秒 / 0 |

-O2 四轮 missing_samples、rebuffers、missed_eofs 均为零。短 chunked 播放时 CPU0/CPU1 仍有约 9.15%/10.23% idle。统计窗口与 receive-only 不同，不能把两组任务百分比当作严格相同负载。

还测试并撤回两项：本地原生 32 kHz 路径跳过转换工作区（chunked 仍 10.430 秒、713 次欠载）；HTTP 改到 core1（短句有改善，但 30 秒耗时 42.316 秒、2341 次欠载）。最终没有保留这些试验。

## 最终改动与真实复测

- sdkconfig.defaults 固化性能编译；当前有效 sdkconfig 同步为 -O2。
- PCM 断粮告警改为 TIVOO_LOGW，使现有诊断链路能保存告警。保留首次立即记录及后续每秒节流，日志队列不阻塞播放。
- 主机回归覆盖 -Og/-O2 的真实输出代码及诊断转发。

未改变 AFE 输入/输出采样率、任务核绑定/优先级或 DMA 时序。性能统计开关已关闭；临时静音、测试入口均已清除，正常 DOUT、唤醒与音频路径恢复。HA 本轮未改动，仍然增量流式转发，不等 Qwen 完成。

真人复测接收峰值 362494 B（原 25600 B），HTTP 接收 6676 ms、最长单次读 60 ms；随后缓冲继续供给完整播放。输出欠载、缺失采样、重新缓冲和 missed EOF 均为零。AFE 播放前后 feed/fetch errors、resets、capture_overruns 为零；启动阶段已有的 overruns=41 未在回答期间增长。

## 部署与回退

S3 只写应用偏移 0x10000；未擦除 NVS、模型或其他固件分区。正常固件 2501312 字节，SHA256 `da04bb22e36fdde204a9882e46eb467972648b9fdd3376b979b92f671c0b37d4`。写入后另行 verify_flash，digest matched，再复位启动。

回退文件 NAS `/volume1/docker/tivoo-esptool/artifacts/p68-streaming-normal-20261125.bin`，SHA256 `50ab2ab37119e8624d35ba0b8260ff810621a52f17f7872867e4ff693213ff02`。HA 保持上一部署版本。没有提交或合并。

## 验证与限制

正常固件编译、独立烧录校验和真人日志验收通过。全量 ESP32 主机测试 167 passed / 1 failed：既有诊断断线重连测试在握手时 ConnectionResetError；前一次运行另有 Wi-Fi 断线 EOF 断言遇到同类 reset。没有改动对应网络模拟器或用重试掩盖失败。最终相关用例与这两项单独重查共 42 passed（禁用无关 pytest 插件自动加载，避免环境内 httpx 别名插件冲突）。全量首次失败仍保留在 evidence 测试记录。临时夹具和串口采集已结束。

[evidence](evidence/2026-11-25-p68-cpu-budget/) 保存筛选后的前后指标、验收 JSON、编译参数与部署摘要；完整原始日志及临时探针留在 gitignored `.superpowers/p68-streaming-followup/`。

提交前再次验证：ESP32 全量 168 passed，HA Qwen 相关 53 passed。历史失败记录保留，未修改对应测试来规避异常。
