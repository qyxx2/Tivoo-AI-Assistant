# P6.8 B8.7 实机自动化续验

> 同日后续：AFE 初始化内存错误已按 ESP-IDF v6.1 文档修复并重新刷写验证；软件回归 957 项通过。持续 RX gap/reset 仍未通过，B8.7/B9 HOLD。最新结果见 [AFE 内存修复与续验](2026-11-23-p6-8-afe-memory-fix.md)。下文保留修复前原始记录。

日期：2026-11-23（Asia/Shanghai）；代码基线 `a4469d7`，包含会话开始前已有的 6 个 tracked 文件修改。

**结论：本轮已执行可运行的自动化实机检查，B8.7 未通过，B9 继续 HOLD。** S3 已实际连接并完成刷写，不再是“没有 S3”的旧阻塞；当前阻塞是 AFE 初始化 `ESP_ERR_NO_MEM`、提示音声学校准未完成，以及 HA 仍指向旧板地址。没有真实有效的 local-wake turn，不能验收 Qwen → S3 播放、barge-in、播放完成后的问号续聊。

## 1. 执行范围与环境

- 使用 Superpowers using-superpowers、executing-plans、systematic-debugging、verification-before-completion 的流程原则，原地继续已有 B8.7 验收；本轮没有新增功能或修改固件源文件，没有进入 B9。
- 按用户限制仅执行自动化，不要求真人讲话、听音或确认画面。没有启用 test gate 或伪造声学校准/有效 MIC session 来绕过生产 gate。
- NAS：`root@192.168.3.94`；通过已有 `tivoo-esptool` 容器（镜像 `tivoo-esptool:4.8.1`）识别、刷写和采集串口。
- NAS 当前串口为 ACM1/ACM2；容器原来仍映射不存在的 ACM0。重建该工具容器，保留原镜像、`/work` bind mount 和 restart policy，改为映射这两个实际串口；未修改持久 recreate.sh。

| 串口 | esptool 实际识别 | MAC | 本轮写入 |
|---|---|---|---|
| `/dev/ttyACM1` | ESP32-S3 QFN56 rev v0.2，内置 8 MB PSRAM | `b8:1f:3f:aa:82:e0` | S3 app，偏移 `0x10000` |
| `/dev/ttyACM2` | ESP32-D0WD-V3 rev 3.1 | `58:2a:bd:d5:4c:90` | 无 |

## 2. 构建、刷写和启动

重新运行激活 ESP-IDF v6.1 后的 `ninja -C esp32/firmware/build -j2`：exit 0。使用现有私有 sdkconfig，app 为 2,528,752 bytes，SHA256：

```text
2b851f235eac297fda8b1cfb6003fde613e81bc05b1a72251c7b7985cd7fa939
```

仅写 app，保留 NVS、bootloader、partition table 和已有模型分区。首次刷写因本轮串口采集过早打开并复位芯片而中断，该次失败不计通过；等采集退出后重新完整刷写，esptool exit 0，输出 `Hash of data verified.`。随后才复位并采集启动日志，已确认成功启动上述 app，HELLO 版本为 `0.1.0+a4469d7`。

实机观测：

- Flash 16,777,216 bytes、PSRAM 8,388,608 bytes；启动 PSRAM 自检通过；GPIO38 RGB off 返回 ESP_OK。
- Wi-Fi 成功，S3 地址 `192.168.3.40`。状态查询 RSSI -11 至 -12 dBm。
- 双麦 capture 持续递增，L/R 均有非零样本；采集 monitor 接管后日志显示 `gaps=0`，启动累计 `lost_blocks=32`。仅证明数字采集活动，不能据此判断接线相位、声学质量或 AEC 效果。
- AFE 模型加载成功，配置为 MMNR / FD HIGH_PERF / AEC / BSS / vadnet1_medium / wn9_hilexin；打印 `feed=1024 x4 fetch=512 x1` 后报 `local AFE initialization failed (ESP_ERR_NO_MEM)`，随后 `Local wake unavailable: ESP_ERR_NO_MEM`。
- AFE 失败清理后 internal free=78,911 bytes，largest=31,744，PSRAM free=8,210,560；capture 日志 internal_min=316。**失败发生在 AFE 构造后的缓冲/队列/任务建立阶段；现有日志不能进一步区分具体哪一次分配失败，不能把释放后的空闲量当成失败瞬间的可用内存。**

刷写与启动原始证据：[flash](evidence/2026-11-23-p68-b87-hardware/s3-resume-flash-retry.txt)、[boot](evidence/2026-11-23-p68-b87-hardware/s3-resume-boot-retry.txt)。

## 3. S3 TCP 7778 自动化检查

真实 S3 三次 TCP 连接的 TVIO HELLO → HELLO_ACK → 空载 PING/PONG → GET_STATUS 全部成功，覆盖主动断开重连与协议拒绝后的重连。

| 检查 | 结果 | 可证明范围 |
|---|---|---|
| HELLO 能力 | PASS | 未宣告 `local_wake_stt_v1`，与 AFE 失败一致；仍有诊断、状态、audio resource/control 能力 |
| 心跳、状态、重连 | PASS | 三次连接成功；设备 uptime 连续增长，查询时 Wi-Fi connected |
| 随机 session 的 TTS_PLAY | PASS（拒绝子集） | 请求后 PONG 和状态仍正常，audio resource 保持 idle；没有证明任何 PCM 被播放 |
| 未协商 local-wake 时发送 FOLLOWUP_OPEN | PASS（拒绝子集） | 设备关闭诊断连接，随后可重新握手；没有打开有效 follow-up gate |
| 端到端设备连接 | GAP | S3 状态显示 7777 disconnected、SPP disconnected；HA 配置仍为 `esp32_host=192.168.3.28`，未改为 S3 `.40` |

探针首次错误地给 PING 带 JSON，设备明确返回 `PING payload must be empty`；修正为空 payload 后完整重跑 exit 0。首次探针不计通过。最终证据：[probe](evidence/2026-11-23-p68-b87-hardware/resume-device-probe.txt)。探针源码：[probe_device.py](evidence/2026-11-23-p68-b87-hardware/probe_device.py.txt)。

Classic 板另做自动复位及 18 秒串口观测：`Classic SPP startup: ESP_OK`、`UART bridge startup: ESP_OK`，两次计数快照 decode/overflow/ack/heartbeat/seq errors 均为 0。此结果仅证明桥接固件启动及短时空闲状态，未验证 SPP 实际连接或 UART 带载传输。[Classic boot](evidence/2026-11-23-p68-b87-hardware/classic-resume-boot.txt)

## 4. 定向软件回归与 NAS 服务

- HA/Qwen：通过 `scripts/test-ha.sh` 执行 `test_qwen_lifecycle.py`、`test_qwen_satellite.py`、`test_qwen_realtime.py`、`test_p68_lifecycle.py`，**102 passed**，exit 0。[日志](evidence/2026-11-23-p68-b87-hardware/resume-ha-tests.txt)
- ESP32：关闭 pytest 插件自动加载后运行 `test_p5_hardware_memory.py`、`test_p5b3_bootstrap.py`、`test_p68_afe.py`、`test_p68_pcm_src.py`、`test_p6_audio_resource.py`，**49 passed，1 failed**，exit 1。[日志](evidence/2026-11-23-p68-b87-hardware/resume-focused-tests.txt)
- 失败项 `test_effective_target_configs_after_configure`：当前私有 sdkconfig `CONFIG_ESP_WIFI_RX_BA_WIN=2`，测试要求 10。另实际 RX/TX buffer=10/10，而工作区 defaults=8/8，说明现有构建配置与待提交默认配置尚未统一。本轮保留现状和失败结果，没有仅为变绿修改断言。
- 最初直接启动 pytest 被环境已有 HTTPX 插件导入冲突阻断；关闭插件自动加载后得到上述实际测试结果。该环境启动失败不计为测试用例失败或通过。
- Qwen 真实 `/api/health`：`status=ready`，Frontend MCP initialized/ok，homeassistant ready，46 tools。未重复此前已经通过的真实模型读写、rollback/redeploy 流程。

## 5. 剩余 gate 与最终状态

| B8.7 项目 | 当前状态 |
|---|---|
| Step 8 local wake → prompt → 16 kHz → Qwen/MCP → 24 kHz → native SRC → AUX completed | **BLOCKED**：AFE 内存初始化失败，且未校准；没有可用 local-wake turn |
| Step 9 真实播放期间打断、匹配 completed 后单次 4 秒 gate、同 socket 跨物理播放接续 | **BLOCKED**：上游有效设备 turn/播放前置条件未成立 |
| Step 9 实机诊断断开与重连、无授权 follow-up 拒绝 | **PASS 子集**，不能替代整条会话生命周期 |
| SRC 输出音质、DAC→AUX 声学正确性 | **GAP**：本轮没有有效播放，也没有人工或自动回采质量测量 |
| B9 release gate | **HOLD** |

下一轮应先定位 AFE 失败的具体分配点，统一固件配置并恢复 Wi-Fi/AFE 同时可用，再自动完成提示音 TX/RX 关联与尾音校准。只有 local-wake 能力恢复后，才迁移 HA 目标到 S3 并执行真实语音/PCM/打断/续聊用例。上述工作不应通过打开测试 bypass 或伪造 completed 核销。本轮未声称完成 B8.7，未清理 AstrBot/Sherpa 等 B9 内容。
