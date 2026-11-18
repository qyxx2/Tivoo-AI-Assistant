# P6.8 b2 UART/SPP 桥验收报告（软件通过，实机待验）

日期：2026-11-18。实现提交：`9ea452dca16e25f5bd299c9147f854bb57cc9827`。
范围：仅 b2，依据 b0.2 冻结合同 P68-HB05–HB15 及 b1–b10 计划。用户要求 S3 与第二颗 INMP441 到货前不进行双板实机测试，不刷旧 Classic。T01-B 仍为 GAP；本次未连接 NAS、未部署 HA、未改 NVS/Bond、未刷写任何固件、未开始 b3。

## 实现与证据

- T02-A：共用 C wire codec、CRC32/COBS、长度/类型/端序校验、流分隔恢复；真实 ESP-IDF UART1 921600 8N1、S3 TX17/RX18、Classic TX18/RX19、双 8192B driver ring；独立 reader/writer、优先小控制包、每向一个可靠在途包、1s/3s heartbeat、20s ACK、严格 token/seq/epoch；ACK 仅入队，失效不自动重播。
- T02-B：S3 真正接入 `control_bridge` 原 TCP parser、单段 staging 与 ACK 背压、独立 7778；Classic 复核完整 raw frame，使用原 32 项 FIFO、连接目标与 frame generation 检查，SPP 请求存 PSRAM。反向两端 8192B，桥溢出标记对应 7777 失效，保留物理 SPP；原 raw/hint 格式不变。监听端 socket 不随单个 client 关闭，避免重连竞态。桥真实状态/MAC 定期刷新，失效报 disconnected（不表示物理必然断开），旧状态不关闭新 writer，HA connected 同步仅限配置 MAC 一致。b2 HELLO 不宣告未实现音频能力，HA 接受控制/诊断能力并拒绝未宣告的音频请求。日志记录 wire decode/overflow、ACK/heartbeat timeout、seq 错误、ACK max、reverse/SPP 队列高水位（SPP 取采样值）。
- T02-C：复用原 Classic 安全、SPP session、SDP fallback、330B/15ms、WRITE_EVT、CONG_EVT 及 HA service/MCP/protocol；未修改配对密钥、NVS 布局或显示逻辑。原单目标 host 回归保留，不将模拟认作物理 SPP 证据。
- 依据：冻结 b0.2 已固定上游 esp32-divoom 提交/原 parser、项目现有 SPP 与 HA protocol；本机 v6.1 UART API、现有 PSRAM 配置、目标独立 CMake/锁/分区均核对。不另引入外部依赖或新语义命令。

## 软件验证

1. TDD 日志在 `.superpowers/p68-b2/`：wire、link/router、HA MAC 和 capability 测试先 RED 后 GREEN；补充旧 epoch 重新 OPEN 回归先失败后通过。C host golden 与 C link/router 用例覆盖坏 CRC、4608B、分段、旧 token、双向等待、ACK lost/timeout、重复 seq、旧 epoch、32 项和 reverse ring 8192B。
2. 增加真实 C TCP listener host 模拟：使用模拟 UART ACK/fault，验证 7B 拆分、最大帧、粘包且 payload 含 0x69/0x96、未 ACK 时暂停后续帧、7778 HELLO 仍可接收、7777 关闭/重连/故障隔离。曾复现旧 listener 关闭 client 同时关闭 listening socket 的重连竞态，分离 close_client/close_endpoint 后 6 项 listener 测试通过。该模拟不驱动真实 UART 或 Bluedroid。
3. 最终命令：
   `bash scripts/test-ha.sh tests/esp32/test_p68_uart.py tests/esp32/test_p5_hardware_memory.py tests/esp32/test_p5b3_control_bridge.py tests/esp32/test_p5b3_security.py tests/esp32/test_p5b3_session.py tests/esp32/test_p6_reverse_channel.py tests/esp32/test_p6_device_status.py tests/homeassistant/custom_components/tivoo -q`
   416 passed，170 warnings，68.25s，exit 0；完整日志 `.superpowers/p68-b2/final-regression.log`。未宣称全仓库测试。
4. 两个实际 ESP-IDF v6.1 target 均从实现提交重新 reconfigure、`nice -n 5 ninja -C build -j1`、`idf.py size`，串行，`CMAKE_BUILD_PARALLEL_LEVEL=1`，均 exit 0。观察 MemAvailable 约 4.3–4.5 GiB（抽样非峰值），没有宿主机卡死。未擦除或写 flash。代码自审及 git diff --check；无独立子代理审查。

## 产物与静态内存

| target | APP bytes | 8 MiB app 剩余 bytes | APP SHA-256 |
|---|---:|---:|---|
| esp32s3 | 1,664,032 | 6,724,576 | `dd182e3da0da9ccb0dbe7d12d636944ec541ef0925b93f6f421eeec7b6221178` |
| esp32 | 718,608 | 7,670,000 | `e31bf37e5458e90f29bd20509446a9312979686374dcdad11001d6cc49619954` |

S3 DIRAM 153639/341760，IRAM 独立保留区 16384/16384；Classic IRAM 104591/131072、DRAM 46483/124580。静态大小不是实际运行 heap、任务栈或实时负载证据。

归档：`.superpowers/p68-b2/artifacts/{esp32s3,esp32}/`，仅分段产物、flash_args/flasher_args.json、源提交及 SHA256SUMS；不提交二进制。Classic 禁止使用覆盖 NVS 的整片镜像，等授权维护窗口再按 b0.2/b1 分段刷写。构建日志 `.superpowers/p68-b2/*-final-*.log`。

## GAP（不核销硬件验收）

| 项目 | 软件 | 必须补验 |
|---|---|---|
| T01-B | 不在本批范围 | 实物版本、电源/接线/USB、两板启动、NVS 保全 |
| T02-A / HB05–06 | codec/link host 与两目标 build PASS | 两板真实 UART、误码/堵塞、双向 ACK 时序、内存/任务水位 |
| T02-B / HB07、10–13 | host parser、router、HA 与 build PASS | 真实 SPP reverse、双板任一重启/单 TX/RX 断线、MAC 切换、旧帧隔离、恢复状态 |
| T02-C / HB08–09 及控制兼容 | 原安全/session/HA 回归 PASS | 首配/旧 Bond/断电复用、真实 SPP 拥塞、显式 disconnect、真实最大 256 GIF chunks、长滚动、实际显示 |
| 音频并发 | 不属于 b2 | b3/b4/b10 真实音频与控制并发 |

受硬件缺席限制，b2 仅完成软件任务。T02-A/B/C 不作为全量实机 PASS；无必须在本批软件实现前另行人工确认而未确认的决定。S3 到货且 T01-B 通过后才做 b2 实机验证，期间现网 Classic 保持原固件；不提前执行 b3。
