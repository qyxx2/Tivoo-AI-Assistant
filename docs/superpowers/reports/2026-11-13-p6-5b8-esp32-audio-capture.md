# P6.5b8 ESP32 常驻音频验收

- 实装 I2S0 Standard/Philips 全双工 32 kHz、双 32-bit slot、独立 RX/TX DMA。INMP441 接线为 BCLK GPIO26、WS GPIO25、SD GPIO34、L/R 接地，使用左槽。31 tap FIR 低通后 2:1 降采样，上传 16 kHz 单声道 S16LE。
- ESP-SR 2.6.1 使用 MR、SR High Performance AEC 与 WebRTC VAD，关闭播放 VAD 静音和本地 WakeNet。API 报告 feed/fetch 各 512 samples。静默 TX 参考输入为零，最终 TX PCM 参考接入及物理延迟对齐归 b10。
- 空闲 VAD 边沿触发 START、ACTIVITY、最多 500 ms AEC 预录，然后持续发送 20 ms PCM 帧。发送失败保留有界待发队列并重试。持续背压覆盖最旧待发帧，记录丢帧，覆盖范围内的活动边沿也可能丢失。诊断连接代次隔离重连，STOP 只匹配当前 UUID，物理运行时不随网络上传停止。

## 验证

| 项目 | 结果 |
|---|---|
| ESP-IDF 6.1 构建、分区大小、NAS 应用区刷写 | PASS。通过 `tivoo-esptool` 刷写 `0x10000` 并校验哈希，保留分区表和 NVS |
| 主机回归 | PASS。ESP32 53 项，HA 345 项。覆盖左槽/符号、抗混叠、S16LE、预录环、START 重试、PCM 背压、断线代次和匹配 STOP |
| 实机 I²S RX/AEC/VAD 常驻、Wi-Fi/SPP 并行 | PASS。经典 ESP32 160 MHz 首测出现 DMA 溢出和任务看门狗。240 MHz、两块 32 ms AEC 滤波、12 个 DMA 描述符下每 10 秒处理约 313 个 AFE 帧。实机复用原 SPP bond，观测到 AFE 计数持续增长，RX 溢出、feed/fetch 错误及网络 PCM drop 为 0。采集和 fetch 栈最低余量约 2 KiB |
| 真人语音触发、连续 PCM 及物理 STOP | GAP。7778 通过 HELLO/ACK 和 GET_STATUS，真人讲话时未观察到新的 VAD 边沿或 MIC_SESSION_START。VAD 开机后持续 speech，左槽滤波后峰值 21565–25236，未驱动的右槽读数达到满幅。当前证据不足以归因到硬件接线或麦克风。需核对 3.3 V、共地及 SD 的约 100 kΩ 下拉，再运行验收。尚无活动上传可用于实机 STOP 验证 |

## 复测

让 HA 释放唯一的 7778 客户端连接，再运行 `python3 -u tests/esp32/p65b8_device_acceptance.py <ESP32_IP> --spp-peer <已配对的 Tivoo MAC>`。等 READY 后在麦克风旁讲话 2–3 秒，然后保持安静。脚本验证事件顺序、二进制 PCM、静音后的持续上传、匹配 STOP 与后续 AFE 遥测。

NAS 原 Tivoo 集成使用固定 capability 列表，会拒绝 B8 HELLO。按确认部署分支已有的 B7 集成 `4ae2c8a` 并保留 B8 固件。HA 已重启，NAS 到 ESP32 的 7777/7778 两路连接均恢复。旧 Tivoo/AstrBot 集成备份位于 NAS 的 `/volume1/docker/tivoo-backups/p65b8-ha.w3W9KS/previous-integrations.tar.gz`。

## 分层复测

1. **先校验 7778 工具。** 运行 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/esp32/test_p65b8_acceptance_tool.py`。测试用分段 TVIO 字节流校验 HELLO/ACK、状态查询、START → ACTIVITY → PCM、静音后继续上传以及 STOP。真机脚本也会打印 START 前收到的 AFE 遥测。
2. **独立观察采集和 VAD。** 在 `Tivoo I2S audio` 菜单启用 `TIVOO_AUDIO_PROBE`，刷写诊断构建，使用 115200 UART 记录 `PROBE` 行。依次采集 5 秒安静、5 秒靠近麦克风播放固定 1 kHz 音调、5 秒安静。再用真人讲话观察 VAD；纯音只用于验证采集和滤波。每秒比较 `raw_left`、`raw_right`、`filtered_left`、`enhanced` 的 `ac_ms`（去直流均方值）、`dc`、`clipped`，以及 `vad speech_samples`。探针只记录统计值。
3. **必要时验证电气侧。** 在 ESP32 端用逻辑分析仪同时测 GPIO26/25/34。预期 WS 约 32 kHz、BCLK 约 2.048 MHz，WS 低电平槽在边沿后一个 BCLK 开始传输 24 位数据。确认供电、共地及 SD 的约 100 kΩ 下拉。若需确认槽位，可断电后把 INMP441 L/R 从 GND 改接 3.3 V 再重复纯音，确认原始双槽中音调能量随选槽转移，然后恢复 GND。

| 对照结果 | 下一层定位 |
|---|---|
| ESP32 引脚上时钟缺失或 SD 无有效响应 | 先测模块供电、共地、下拉和时钟到达情况。时钟在 ESP32 端也缺失时检查固件时钟与 GPIO 配置 |
| 引脚上能解出随音调变化的左槽，UART 原始左槽没有对应变化 | 检查 I²S GPIO 配置、DMA 字序、Slot 和位对齐 |
| 原始左槽有响应，滤波左槽缺失 1 kHz 响应 | 检查左槽提取与降采样 |
| 滤波左槽有响应，增强输出异常或干净真人语音缺少 VAD 切换 | 检查 AFE 输入格式、配置和 VAD |
| UART 有 VAD 边沿且 upload=1，7778 已完成握手却没有对应消息 | 检查 producer 和诊断队列，结合已知字节流测试区分接收工具 |
| UART 有 VAD 边沿但 upload=0 | 确认边沿是否出现在 HELLO_ACK 之后，并检查会话创建和入队 |

2026-11-14 使用探针完成「安静 → 真人说话 → 安静」对照。采到的 68 个一秒窗口中，原始左槽每秒有 62–157 个近满幅样本。滤波左槽和 AFE 输出的去直流均方值中位数分别约 139 万和 140 万，VAD 有 67 个窗口判为全程人声。右槽旧遥测的瞬时满幅无法代表整秒输入，探针的右槽每秒只有 0–3 个近满幅样本。本次确认异常已出现在 AFE 之前的 I²S/DMA 左槽。需要独立解码引脚波形或用已知正常的 I²S 信号源做对照，才能区分电气侧与 I²S 采集配置。
