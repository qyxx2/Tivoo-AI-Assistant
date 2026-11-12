# P6 ESP32 ↔ Home Assistant — Batch Execution Plan

> **状态：** P6b0、P6b1、P6b2 已完成。P6b1 真实 SPP DATA_IND 原始回传已通过亮度状态回显实机验证；P6b2 完成 7778 心跳/独立重连、状态快照与事件、P6 ERROR 解析、HA/ESP32 POSIX 回归及 ESP-IDF v6.1 构建。P6b3–P6b6 未开始。
> **工作分支：** `feature/p6-esp32-ha-bidirectional-communication`
> **基线：** `a2b0127`（创建 P6 分支时的 main）
> **合同矩阵：** [P6 Contract Matrix](../specs/2026-11-12-p6-esp32-ha-bidirectional-contract-matrix.md)
> **详细任务计划：** [P6 Implementation Plan](2026-11-12-p6-esp32-ha-bidirectional-implementation-plan.md)
> **日期：** 2026-11-12

本文件只规定执行顺序、批次边界、前置条件和阶段门。每批文件清单、稳定接口、测试步骤和具体验收要求以 P6 Implementation Plan §3–§5 为准；P6 Contract Matrix 是唯一技术合同。本文件不得重新定义协议或扩大阶段范围。

## 1. 分支和权威顺序

- P6 所有开发均在 `feature/p6-esp32-ha-bidirectional-communication`。
- 基线为 `a2b0127`；P5 已验收的源码和行为是 P6 兼容基线。
- 权威顺序：
  1. [P6 合同矩阵](../specs/2026-11-12-p6-esp32-ha-bidirectional-contract-matrix.md)：Message Type、Payload、端口、连接行为、状态和 P6-C01–C20 验收。
  2. [P6 实施计划](2026-11-12-p6-esp32-ha-bidirectional-implementation-plan.md)：文件职责、跨批接口和每批具体步骤。
  3. [上位双向通信规格](../specs/2026-11-09-esp32-ha-bidirectional-communication-design.md)：整体音频与设备架构；与 P6 矩阵不一致时以 P6 矩阵为准。
  4. [P5 合同矩阵](../specs/2026-11-11-p5-esp32-minimal-firmware-contract-matrix.md)和实际代码/报告：所有已有能力必须保留。
  5. P3/P7A 合同矩阵：只用于校验 AstrBot session 和 PCM 格式交接，不把它们的运行时职责搬进 P6。

## 2. 设备/网络/安全执行约束

- ESP32 只与 HA/NAS 配置的内网地址通信；两个 TCP 连接为 HA → ESP32，TTS HTTP GET 为 ESP32 → HA/NAS。
- 按可信局域网使用，不新增账号认证、mTLS、证书固定、密钥交换或专用代理；不做公网部署。
- TTS 首选 HA/NAS 内网 HTTP。若实际 HA internal_url 配置为 HTTPS，使用 ESP-IDF 自带标准 CA bundle；不要求自签证书或逐设备证书配置。
- 保留必要的协议检查、Payload 长度限制和资源请求状态检查。这些属于接口正确性，不扩展成通用安全框架。
- HTTP 只获取 HA 经 7778 明确下发的资源 URL；不新增目录浏览、任意资源发现或通用 HTTP Server。

## 3. 批次依赖和执行顺序

| 顺序 | Batch | 交付物 | 主合同 | 依赖 |
|---:|---|---|---|---|
| 1 | **P6b0** | TVIO v1 双向 codec、Message Type、Sequence、HELLO capabilities、双向 message API | C01、C05、C06、C10、C19 基础 | P5 |
| 2 | **P6b1** | TCP 7777 SPP DATA_IND 原始回传、上游 0x69/0x96 hint | C02–C04、C19 | P6b0 |
| 3 | **P6b2** | 7778 心跳、GET_STATUS、DEVICE_STATUS、DEVICE_EVENT、ERROR 和独立重连 | C07–C10、C17 | P6b0 |
| 4 | **P6b3** | MIC session/schema、binary PCM、HA 有界 async iterator、stop dispatch seam | C11、C18 | P6b0、P6b2 |
| 5 | **P6b4** | HA TTS Proxy 内网 URL、run-start/intent-progress/tts-end 事件时序和 TTS_PLAY | C12、C01 | P6b0、P6b2 |
| 6 | **P6b5** | ESP-IDF HTTP Client GET、流式 reader、AUDIO_STOP、AUDIO_STATE | C13–C16、C18 | P6b0、P6b4 |
| 7 | **P6b6** | P5/P6 regression、IDF build、7777/7778/HTTP 实机验收、P6 报告 | C01–C20 | P6b1–P6b5 |

依赖图：

```text
P5
 └─ P6b0
     ├─ P6b1
     └─ P6b2
         ├─ P6b3
         └─ P6b4
             └─ P6b5
                 └─ P6b6  (also depends on P6b1/P6b2/P6b3)
```

P6b1 与 P6b2 在技术上可独立，但为了减少跨批次接口变动和并行协调成本，按表串行执行。不创建额外分支，不把两批揉成一个大批次。

## 4. 每批范围、验收门和不做事项

### P6b0 — TVIO v1 双向协议底座

**状态：** 已完成。

**完成：** Python/C 两端拥有矩阵中 P6 消息类型、双向 framing/Sequence、二进制 MIC_PCM 上限、HELLO 新 capabilities、业务消息 send/dispatch API；P5 HELLO/ACK/日志/错误不回退。

**验收门：** Python/C golden bytes 一致；拆包/粘包、长度、Sequence、未知 type、握手拒绝测试通过；P5b2 diagnostics tests 通过；ESP-IDF v6.1 build 通过。

**禁止提前实现：** SPP reverse 业务、heartbeat/status 业务、MIC session manager、HTTP Client。

### P6b1 — TCP 7777 SPP 原始反向通道

**状态：** 代码实现、host/HA 验证、ESP-IDF v6.1 编译、NAS app-only flash、真实设备 HELLO/SPP Bond 认证、7777/7778 生命周期隔离及 HA 侧 P6b0/P6b1 transport 部署验证完成；真实 SPP DATA_IND 原始字节回传已通过实机亮度状态回显验证；上游参考源逐行对照仍未执行，详见 [P6b1 执行报告](../reports/2026-11-12-p6b1-tcp-control-spp-reverse-channel.md)。

**实现：** SPP DATA_IND 数据只复制到 8 KiB 固定容量 reverse queue，经 7777 当前 TCP client 原始返回；socket 发送由 listener writable path 承担；上游发送状态语义按单字节 0x69/0x96 hint 表示。HA 侧 7777 reader 独立消费 hint 或 opaque raw bytes。

**已验证：** POSIX simulator 覆盖有序数据、EAGAIN/待发数据保留、超容量拒绝、client disconnect、无 client 时不缓存给新 client；P5b1/P5b2/P5b3/P5b4 回归 31 passed；HA transport/services 29 passed；Ruff、format、diff check 通过。

**未完成的辅助对照：** 已使用本机既有 /home/Gold/.espressif/tools/activate_idf_v6.1.sh 完成 ESP-IDF v6.1 build，并通过 NAS 持久 esptool 容器仅刷写 app image 到 0x10000。真实设备 HELLO、SPP Bond 认证、7777 disconnect 隔离及通过 HA `Esp32ConnectionAdapter` 发送亮度 50/100 后回收 82 bytes SPP 原始数据均已验证通过。上游 BluetoothBridgeTest/esp32-divoom 三个参考源文件不在本工作区，因此逐行对照未执行。

**明确语义：** frame 提交时 connecting 返回 0x69、disconnected 返回 0x96；不将无连接时的 frame 排队到下一次连接后补发。hint 不是命令 ACK，也不是 authoritative SPP status；7778 状态快照才是权威来源。

**禁止提前实现：** TVIO 包装、command_id、per-command ACK、SPP 重连重写。

### P6b2 — TCP 7778 心跳、状态和事件

**状态：** 已完成；报告：[P6b2 执行报告](../reports/2026-11-12-p6b2-tcp-diagnostic-heartbeat-device-status.md)。

**实现：** HA 在 HELLO_ACK 后仅发送一次 GET_STATUS，按 15 秒节奏发送 PING，仅空 PONG 更新存活时间；连续 45 秒无有效 PONG 时关闭并复用原有 7778 独立重连循环，不触碰 7777 或 SPP。DEVICE_STATUS 回显 request_id，并通过现有 Wi-Fi/netif、listener client flags、SPP 原状态/peer getter 生成真实快照。HTTP resource 仅增加当前 idle/fetching 状态写入 seam，本批没有实现 HTTP GET。Wi-Fi 与 SPP 固定事件只在真实状态变化后发送；HA 校验并缓存状态/事件。P6 ERROR allow-list 扩展，标准日志 URL/token/凭据/PCM 字段脱敏。

**自动化验证：** HA transport/diagnostics、P6 device status simulator、P5b1 listener 和 P5b2 diagnostics 联合回归 73 passed；新增 ESP32 目标子集 22 passed。fake clock 覆盖 15s PING、有效/无效 PONG、45s 超时、7778 重连及 7777 连接保持；POSIX 模拟器覆盖 GET_STATUS、真实 getter 注入、idle/fetching 状态、Wi-Fi/SPP transition 去重和 P6 ERROR codes。

**构建：** ESP-IDF v6.1 / ESP32 target build 通过，生成 `esp32/firmware/build/tivoo_firmware.bin`。没有刷写 ESP32，也没有部署 NAS。

**范围：** 仅 P6b2；未实现 MIC session、TTS/HTTP GET、AUDIO_STOP、decoder/playback、设备重启或后续 P6b3–P6b6。未 push、未 merge。

### P6b3 — MIC session 传输接口

**完成：** HA 一个活动 session、16 条消息的有界 PCM 队列、session_id 匹配、async iterator、MIC_CAPTURE_STOP 接口；AUDIO_INTERRUPTED 只验证并分发给后续阶段注册的 handler。

**验收门：** 格式/长度/session 隔离/队列满/迟到消息测试通过；PCM bytes 不做 Base64、不丢序、不跨 session；HA unload 清理活动 iterator 与队列。

**禁止提前实现：** I²S RX、INMP441 采集、AEC/VAD、真实 MIC_PCM producer、Assist Satellite、Pipeline cancel、AstrBot Stop。

### P6b4 — HA TTS Proxy URL 与事件触发

**完成：** 用 HA Core 2026.11.0 URL helper 生成内网 URL；run-start 保存资源信息；流式回答在 tts_start_streaming 时提前通知；非流式短回答在 tts-end 通知；每个 playback_id 只发送一次 TTS_PLAY。

**验收门：** internal_url 优先、LAN IP fallback、无内网地址时报错；流式触发先于 tts-end；URL path token 保持原样；logger 不输出完整 URL/token。

**禁止提前实现：** Satellite entity、音频播放完成语义、TTS Proxy 后台取消、Pipeline/SSE/AstrBot 取消。

### P6b5 — ESP32 HTTP 资源获取和停止

**完成：** ESP-IDF HTTP Client 独立 task；2xx/MIME 校验；chunked/未知长度流式 reader；单活动 GET；AUDIO_STOP 按 playback_id 匹配/幂等；状态 buffering/resource_ready/stopped/failed。

**验收门：** 受控 HTTP server 覆盖状态码、MIME、分块、未知长度、大响应、断开和 stop；真实板卡从 HA/NAS 内网 HTTP 获取资源，reader 持续接收；IDF v6.1 build 通过。

**禁止提前实现：** MP3/WAV decoder、SRC、PCM queue、I²S TX、DAC/AUX、playing/completed 状态。resource_ready 只表示 HTTP 字节完整交给 reader。

### P6b6 — 最终集成与阶段验收

**完成：** P5 全回归、P6 自动化测试、跨语言 golden tests、ESP-IDF clean build、必要真实设备链路、逐合同验收报告、README 阶段状态。

**验收门：** C01–C20 全部有证据；自动化、IDF build、真实设备观察分类清晰；任何未运行项目标记 BLOCKED/NOT RUN，不以编译/模拟代替实机验收。

**禁止提前实现：** P6.5 取消前置验证、P7/P8 runtime、无关重构或阶段状态提前标 PASS。

## 5. 执行环境和测试约定

- HA 测试：现有 `./scripts/test-ha.sh`，使用项目 Python 3.14 环境。
- ESP32 host tests：现有 `.venv/bin/python -m pytest tests/esp32 -q`；C 使用项目已有 POSIX simulator 和系统 gcc。
- 固件构建：ARM64 Ubuntu 上 ESP-IDF v6.1、target esp32；复用 P5 dependency lock 和配置。改动固件的批次必须 IDF build。
- 实机测试：NAS 只用于运行 HA、提供 TTS Proxy 和连接真实 ESP32/Tivoo；不在 NAS 编译、跑大型测试或构建容器。
- 固件升级：已配对设备只刷 app-only image `0x10000`，保留 NVS/Wi-Fi/SPP Bond；不 erase flash，不用覆盖 NVS 的 merged image 做常规升级。
- 每批最小验证：聚焦测试 + 相关 P5 regression + `git diff --check`；改 Python 执行 Ruff/compile；改 C 执行 POSIX simulator + IDF build。
- 每批一份简短 implementation report，记录基线 SHA、文件列表、RED/GREEN、命令/退出码、合同 ID、设备测试状态和 commit SHA。

## 6. 单批执行和变更管理

1. 每批只执行当前 Batch；开始前确认分支、HEAD 和 worktree。
2. 本次计划阶段在工作区形成的文档变更须先作为 planning-only 变更单独收尾，不得混入 P6b0 代码提交。
3. 使用 TDD：先写行为测试并看到 RED，再做最小实现和 GREEN；每批通过退出门后再开始下一批。
4. 每批单独本地 commit，只提交该批实现、测试、文档和报告。
5. 未经用户明确要求，不自动 push、merge main、刷写 ESP32 或部署 NAS 配置。
6. 若发现矩阵与固定 HA Core/ESP-IDF 实际 API 冲突，先停下受影响批次，基于实际源码更新矩阵/计划，再继续。
7. 没有独立 reviewer 时做自审并如实记录，不伪称外部审查。
8. 任何真实设备测试未执行都保留 NOT RUN/BLOCKED，不降低合同退出门。

## 7. P6.5 与 P7/P8 阶段衔接

- P6.5 依据 [P6.5 cancellation preflight patch](../patches/2026-11-11-p6-5-ha-cancellation-preflight.patch.md)，安排在 P6b6 后、P7/P8 依赖取消行为的完整验收前。
- 当前没有 P6.5 报告 `docs/superpowers/reports/2026-11-11-ha-cancellation-preflight-report.md`，因此状态为 NOT RUN。P6 不执行 P6.5 的任务追踪测试，不得将其记为 PASS。
- P7 消费 P6 的 MIC session iterator 和 16 kHz S16LE 协议；P8 消费 P6 的 HTTP resource reader。P6 仅提供稳定接口，不把下游实现提前合并。
