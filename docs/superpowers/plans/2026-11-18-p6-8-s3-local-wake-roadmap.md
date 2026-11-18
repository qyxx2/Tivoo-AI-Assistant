# P6.8 — ESP32-S3 双板语音终端与原生 WakeNet 改造路线

> 状态：总体路线，尚未实施；B0 负责详细规格与合同矩阵。
> 基线：main @ d79775f（2026-11-18）；分支 feature/p6-8-s3-local-wake。
> 本文是 P6.8 的后续执行入口；旧规格保留已实现行为和证据，涉及旧硬件、远程 KWS、提示音和阶段归属的冲突按本文的目标方向在 B0 明确修订。不得把规划当成当前生产行为。

## 1. 目标与边界

- S3（拟 N16R8）作为主控制器：Wi-Fi、TCP 7777/7778、双 INMP441、AFE（AEC/BSS/VADNet/WakeNet）、本地提示音、PCM5102 DAC、TTS 拉流/解码/输出；待机常驻收音但不向 HA 上传环境 PCM。
- 经典 ESP32 只承担 Classic Bluetooth SPP（含配对、持久化、重连及双向状态），关闭其 Wi-Fi/音频运行时；与 S3 通过独立硬件 UART（TX/RX/GND）交换指令和状态。HA 仍只访问 S3；保持原 TVIO、SPP、MCP 及控制接口，必要的新事件由 B0 定义。UART 波特率、引脚和帧边界待确认，不透传无界数据阻塞音频任务。
- 使用 ESP-SR 原生 WakeNet9 系列及实际组件内自带官方唤醒词；不使用 microWakeWord，不训练任意文本唤醒词，不引入 MultiNet。具体官方模型与词语由 B0/B4 核验和用户选定。当前锁定 esp-sr 2.6.1，优先复用其 S3 实现。
- HA 保持 Assist Satellite / 本地 Intent 优先 / AstrBot fallback / TTS / 取消所有权以及唯一 ExpressionCoordinator 和 ScreenPowerGate。Sherpa Paraformer STT（整句解码）及 Matcha TTS 保留，不为缩短延迟盲目换模型。
- 目标链：待机 WakeNet → 本地确认唤醒 → 本地 ready 提示音 + 通知 HA 并行准备 STT → 提示音结束开放命令 → 增强 PCM 上行 → 本地断句 → HA 从 STT 到 Intent/TTS → S3 播放。用户明确要求听完提示音才发命令；无需支持旧计划的唤醒词与指令不间断连说。
- 任意正常处理/普通 TTS 阶段 WakeNet 确认可打断；VAD 单独不得取消普通 TTS/LLM。连续对话仅由当前 HA 对话结果 continue_conversation（保留既有问号规则）和真实回复完成共同授权，独立嘟声后免唤醒收音；取消、错误、普通回答不得误开 follow-up。

## 2. 分阶段路线

| 批次 | 主要工作 | 阶段出口 |
|---|---|---|
| P6.8b0 | 核对当前代码/生产 HA 版本和官方接口；记录现有端到端延迟基线（KWS、提示音、实际命令末尾、VAD/AudioStop、STT_END、设备执行、首声）；明确 GPIO、I2S 时钟与参考、模型分区、UART、TVIO 事件、轮次归属和兼容边界；形成详细规格、合同及分批计划。 | 确认路线与真实接口，旧验收项完成归属，不虚构接口。 |
| P6.8b1 | 建立 S3 主固件与经典 ESP32 蓝牙桥两个独立构建/刷写目标；复用 firmware 主模块，配置 S3 Flash/PSRAM/模型分区及完整烧录，核对 USB/串口和 GPIO 安全。 | 两个目标分别构建及刷写，型号/内存/模型分区正确。 |
| P6.8b2 | 拆分 SPP/Bond/重连，复用 tivoo_spp、tivoo_spp_session、control_bridge；S3 TCP ↔ UART ↔ 经典 ESP32 ↔ Tivoo，恢复真实 SPP 状态及 reverse channel。 | 既有 HA/MCP/亮度/屏幕/倒计时/GIF、独立重启恢复全部可用；大 GIF 不阻塞语音。 |
| P6.8b3 | S3 双 INMP441 同步采集（L/R）、PCM5102 输出及 AEC 数字参考和采样对齐；迁移 audio_capture、audio_playback、audio_output_manager、audio_resource、网络与既有 TTS 欠载修复。暂分离新算法变量，保留原始采集和诊断能力。 | 双声道数据正确、AUX 清晰、长音频不中断、收音和 UART 并行；重新标定声学延迟，不照搬旧 47.5 ms。 |
| P6.8b4 | 启用 S3 官方 AFE 双麦/参考布局（如 MMNR，实际按锁定版本验证），BSS/AEC/VADNet、WakeNet；模型加载、wake state/重触发、VAD 缓存及时间轴；以官方示例为参考。 | 独立于 HA 的官方词唤醒、误/漏唤醒、电视及自身播放干扰下的声学测试；记录负载与内存。 |
| P6.8b5 | HA 本地唤醒入口：新增设备确认事件与必要 session/代次关联（具体字段在 b0），修改 protocol、diagnostics、audio_session、assist_satellite；直接从 STT 启动 HA Pipeline，网络保持连接，命令 PCM 与 STT 准备协调；B5 可用测试/过渡提示音验证入口，量产本地提示音在 b6 完成；处理准备竞态和失败回退。 | 无 NAS WAKE_WORD run 的本地唤醒→STT→本地控制和 AstrBot/TTS；待机无 PCM，命令首尾不丢。 |
| P6.8b6 | 本地提示音与断句：复用生产音色现成 ready 素材/独立 follow-up beep 转 PCM 存 Flash，统一音频出口并与 AEC 实际 TX 参考一致；短提示音时隔离命令采集，结束后开放。S3 VADNet speech_end 驱动 STT 输入结束，按序消费尾部 PCM，再发 AudioStop；核对已部署 HA 公开接口和 VAD 行为，不改 HA Core 或盲目关闭 VAD。 | 无远程 MP3 提示音依赖；无自触发/旧播音抢占；约 400–600ms 初始静音参数实测调优，HA 不额外等待无意义断句。 |
| P6.8b7 | 本地 WakeNet 打断与连续对话：保持 AFE 常驻；确认后 S3 立即停止旧输出、通知 HA 按旧 generation/playback ID 取消 Pipeline/TTS/AstrBot SSE，旧轮清理与新轮准备协调；复用现有 owner 机制，避免旧 TTS 抢占；follow-up 只在真实回复完成且获授权时开放，保留 5/8 秒窗口意图并在 b0 明确计时起点。 | 普通人声不打断，真实唤醒在识别/思考/合成/播放均有效，连续多次打断无旧音频或错误自动续轮。 |
| P6.8b8 | **表情状态机事件来源迁移**：修改 HA Satellite 到 display_state.py 的生命周期适配，保留 Coordinator 和 ScreenPowerGate、原优先级、TTL、显式显示、mood、中央息屏门控；用 S3 wake、命令及实际播放事件代替远程 KWS/候选事件，恢复桥接 SPP 状态；详见下节。 | 正常、打断、follow-up、取消、错误、重启重连和息屏/亮屏全覆盖；没有旧 generation 表情或提示音误触发 speaking。 |
| P6.8b9 | 本地 WakeNet 验收后删除 Tivoo 旧远程唤醒路径：候选上传、WAKE_WORD Pipeline、side KWS watcher、旧 3/15 秒候选计时/重建、远程提示音路径；保留 STT/TTS、必要诊断/会话取消。若无其他依赖才停止 NAS KWS 模型加载，不破坏其他消费者。 | Tivoo 单一唤醒路径，无长期双 KWS；更新 README、规格、配置、部署说明与旧测试归属。 |
| P6.8b10 | 双板综合实机验收、性能测量、稳定性回归；核销旧阶段转入的合同/GAP，必要时修复再验收。 | 记录真实声学、两类延迟、长 TTS、电视、连续打断、表情/屏幕/工具、重启/断网、UART 压力和 CPU/IRAM/DRAM/PSRAM；完整部署和证据。 |

## 3. 表情事件迁移方向（b8）

| 现有状态 | P6.8 目标事件来源 |
|---|---|
| wake_confirmed | S3 本地真实 WakeNet 确认，包括打断；按当前/新 generation 立即提交，高于旧 speaking，不等待 NAS WAKE_WORD_END。 |
| active_listening | 仅本轮命令或获授权 follow-up 的真实 speech_start/end；取消待机候选人声的 700ms/35%/10s 随机监听规则（待机不传环境音）。保持 idle 轮换。 |
| thinking / tooluse | 保持 STT_END 非空有效命令及 AstrBot tool_call/tool_call_result 的现有语义，不用 STT_START 代替。 |
| speaking | 仅当前回复 playback ID 的真实 AUDIO_STATE playing/终态；本地 ready/beep 单独归类，不触发回复 speaking 或 follow-up。 |
| followup_wait | HA 当前结果授权 + 真正回复 completed + 本地 beep 就绪，用匹配轮次的新 speech 或超时退出；不得被旧终态重开。 |
| idle / explicit_content / ai_mood / screen gate | 保留原逻辑、优先级、TTL、owner inhibit、重连重放规则；任何旧轮或失效连接事件不得覆盖当前 desired，HA 为唯一显示仲裁者。 |

SPP 连接状态来源为蓝牙桥的真实状态，经 S3 转发；UART 重连/经典 ESP32 重启、S3 重启及 HA 重载都要回归，不能将 UART/Wi-Fi 连通等同于 SPP 已连。

## 4. 旧阶段归属及执行顺序

旧文档/日志是历史合同及证据，不删除旧 PASS，不把旧 GAP 自动视为完成；仅停止按旧拓扑重复开发，B0 对合同 ID 做正式追踪，B10 依据新证据核销。

| 旧阶段 / 遗留项 | 处理方式 |
|---|---|
| P3/P4、P5/P6 | 已实现接口与已验收证据保留；P3 与新拓扑无关的 HA 重启、24h/API Key 轮换等独立 GAP 保留后续；P5/P6 SPP、AP/网络/恢复、生产 HTTPS 等仍适用项归 b2/b3/b10。第二台 Tivoo、JTAG 专项等非本次必需硬件留原记录，不当作新阶段强制前置。 |
| P6.5 b6–b11 / P7 旧阶段 / P8 旧阶段 | 已有音频/取消能力复用；旧远程 KWS 候选、watcher、连续连说路线由本地唤醒取代；真实麦克风、AEC、DAC、回声负样本、各阶段取消和 follow-up 等现场 GAP 归 b3–b7/b10（P65-A03/A04/A10–A15 等逐项核对）。P7/P8 不再独立重复实施。 |
| P6.6 | 已完成的 C19 与显示逻辑保留，真人语音/工具/mood/打断等现场 GAP 归 b8/b10。 |
| P6.7 | 已完成 b0–b3 及后续修复保留记录；旧 HA 远程提示音/HTTP 门控合同不再单独实施，本地 ready/beep 及提示音负样本/播放边界归 b6/b7/b10。 |
| P7A-C40–C43 | C40 实际声学 KWS 目标改由本地 WakeNet 重新验收，不宣称原 NAS KWS 声学项 PASS；C41 音频上行、C42 TTS/DAC、C43 SPP/并发归 b3/b5/b10；C01–C39 既有服务验收与 STT/TTS 继续有效。 |
| P9 | 现有 mood/MCP 表情部分不重做；未实现的主动播报/主动对话/自动化入口在 P6.8 完成后继续，复用同一播放和显示所有权。 |
| P10 | 旧单芯片 Wi-Fi/SPP/I2S 并发专项被双板并发/稳定性验收替代，归 b10；A2DP 保留备选但本次不实施、不作为 P6.8 前置。 |

## 5. 初步验收目标（非实测保证）

- 分开测量唤醒词结束→实际提示音首声、命令结束→STT 返回、命令结束→HA 实际执行、命令结束→实际回答首声；日志结合真实录音和设备状态，不以数字 playing 代替首声。
- 正常短指令本地命中：尝试唤醒提示音首声 ≤300ms、STT 返回 ≤1.2s、HA 执行 ≤1.5s；本地 WakeNet 确认到停止旧音频 ≤100ms。按 b0 基线和实测校准目标，LLM/TTS 单独计时。
- 待机无 PCM 上传，双麦环境下误/漏唤醒和电视干扰较基线有可测改善；验证提示音隔离、普通播放全双工、无空轮/旧音频/多余表情、长 TTS 与 GIF 并发、断电重启和长期运行。
- 开发机优先构建和自动化，NAS/两板仅进行必要部署和实机验收。每批按实际证据 PASS/GAP/FAIL，不将自动化等同于声学验收。

## 6. 上游参考（B0 核对实际锁定版本）

- [ESP-SR S3 AFE](https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/audio_front_end/README.html)
- [ESP-SR WakeNet](https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/wake_word_engine/README.html)
- [ESP-SR 上游及模型选择](https://github.com/espressif/esp-sr)；[ESP-SKAINET 官方示例](https://github.com/espressif/esp-skainet)
- [ESP-IDF S3 UART](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/uart.html)
- [HA Assist Satellite](https://developers.home-assistant.io/docs/core/entity/assist-satellite/)；[HA Assist Pipeline](https://developers.home-assistant.io/docs/voice/pipelines)

本路线只设定总体步骤，不是详细规格、合同矩阵或可直接执行的实现清单；下一步仅展开 P6.8b0。
