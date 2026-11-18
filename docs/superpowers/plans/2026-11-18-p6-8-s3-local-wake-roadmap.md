# P6.8 — ESP32-S3 双板语音终端与原生 WakeNet 改造路线

> 状态：总体路线，尚未实施；设计阶段拆为 b0.1–b0.6，随后为 b1–b10 实施阶段，共 16 批；b0.1 总体设计与历史合同索引、b0.2 硬件与桥接设计、b0.3 音频/AFE、b0.4 HA STT/提示音合同、b0.5 生命周期与表情合同已完成，下一步 b0.6。
> 基线：main @ d79775f（2026-11-18）；分支 feature/p6-8-s3-local-wake。
> 本文是 P6.8 的后续执行入口；旧规格保留已实现行为和证据，涉及旧硬件、远程 KWS、提示音和阶段归属的冲突按本文的目标方向在 b0.1–b0.6 分域修订并统一交叉审查。不得把规划当成当前生产行为。

## 1. 目标与边界

- 微雪 ESP32-S3-DEV-KIT-N16R8-M（型号已由用户确定）作为主控制器：Wi-Fi、TCP 7777/7778、双 INMP441、AFE（AEC/BSS/VADNet/WakeNet）、本地提示音、PCM5102 DAC、TTS 拉流/解码/输出；待机常驻收音但不向 HA 上传环境 PCM。
- 经典 ESP32 只承担 Classic Bluetooth SPP（含配对、持久化、重连及双向状态），关闭其 Wi-Fi/音频运行时；与 S3 通过独立硬件 UART（TX/RX/GND）交换指令和状态。HA 仍只访问 S3；保持原 TVIO、SPP、MCP 及控制接口，必要的新事件由 b0.4/b0.5 定义。UART 波特率、引脚和帧边界见 b0.2 规格，不透传无界数据阻塞音频任务。
- 使用锁定 ESP-SR 原生 WakeNet9/9L，亦允许 b0.3 核实的 WakeNet10 官方模型，经 b4 实测与用户择定；不使用 microWakeWord，不训练任意文本唤醒词，不引入 MultiNet。具体官方模型与词语由 b0.3/b4 核验和用户选定。当前锁定 esp-sr 2.6.1，优先复用其 S3 实现。
- HA 保持 Assist Satellite / 本地 Intent 优先 / AstrBot fallback / TTS / 取消所有权以及唯一 ExpressionCoordinator 和 ScreenPowerGate。Sherpa Paraformer STT（整句解码）及 Matcha TTS 保留，不为缩短延迟盲目换模型。
- 目标链：待机 WakeNet → 本地确认唤醒 → 本地 ready 提示音 + 通知 HA 并行准备 STT → 提示音结束开放命令 → 增强 PCM 上行 → 本地断句 → HA 从 STT 到 Intent/TTS → S3 播放。用户明确要求听完提示音才发命令；无需支持旧计划的唤醒词与指令不间断连说。
- 任意正常处理/普通 TTS 阶段 WakeNet 确认可打断；VAD 单独不得取消普通 TTS/LLM。连续对话仅由当前 HA 对话结果 continue_conversation（保留既有问号规则）和真实回复完成共同授权，独立嘟声后免唤醒收音；取消、错误、普通回答不得误开 follow-up。

## 1.1 P6.8 已确定的目标硬件基线

型号由用户确认；以下规格为厂商资料值，不代表已经到货、完成接线或上板验收。硬件规格集中在本节，其他文档引用本节。

| 设备 | 数量 / 来源 | P6.8 目标角色与规格 |
|---|---|---|
| 微雪 ESP32-S3-DEV-KIT-N16R8-M（SKU 28836） | 1 块新增；用户指定型号，预焊排针版 | 主控；ESP32-S3-WROOM-1-N16R8，Xtensa LX7 双核最高 240 MHz、512 KB SRAM、384 KB ROM；16 MB Quad SPI Flash（DIO/QIO），8 MB Octal SPI PSRAM（OPI）；2.4 GHz Wi-Fi、Bluetooth LE（不支持 Classic SPP）；单 USB-C，CH334 USB Hub + CH343 USB-UART，另一路为 S3 原生 USB |
| 微雪 ESP32-DEV-KIT-WROVER-E-M | 1 块现有；保留原硬件 | 经典 ESP32-WROVER-E-N16R8（16 MB Flash / 8 MB PSRAM），作为 Bluetooth Classic SPP 蓝牙桥；不再承担主控的 Wi-Fi 与音频任务 |
| INMP441 数字麦克风模块 | 共 2 颗＝现有 1 颗 + 新购 1 颗；用户确认相同品牌、型号及模块，具体品牌名未记录 | 同型号全向 MEMS 数字麦克风；3.3 V 供电，24-bit I²S，L/R 选择；目标为同步双麦输入，L/R 分开、可共享 SCK/WS/SD；按模块板实物核对 L/R 及 SD 三态/下拉，不能只根据芯片型号假设模块外围电路完全相同 |
| PCM5102 DAC 模块 | 1 块现有，复用 | S3 I²S TX → DAC 模拟音频 → Tivoo AUX |
| Divoom Tivoo | 1 台现有，复用 | AUX 扬声器输出、16×16 屏幕，经典 ESP32 SPP 控制 |

板型约束（具体设计接线见 b0.2 规格；音频采样规则由 b0.3 确定）：

- N16R8-M 的 M 后缀表示预焊排针，不是另一种 Flash/PSRAM 容量或外接天线版本；不要误选 N8R8、N32R16V 或 N16R8-U/UM。
- GPIO35/36/37 按微雪现行型号对照表为 NC；结合乐鑫 Octal PSRAM 资源约束，禁止分配给 UART/I²S 等外设。旧版微雪 Wiki 的 N16R8 引脚说明与现行资料有差异，按具体 R8 模组存储占用及实际板版次核对，不沿用旧版“可用”的说法。IO47/48 在该 N16R8 型号为 3.3 V 逻辑域；是否被板载功能占用仍需核对原理图。
- 一个 USB-C 连接电脑后，原生 USB 与 CH343 USB-UART 可分别枚举；刷写路径、板载 RGB、启动绑带脚、供电及 UART/I²S GPIO 设计分配见 b0.2，实际串口设备名与实物版次留 b1 验证。不得照搬 WROVER-E 当前 GPIO26/25/32/33 接线或 GPIO27 RGB 约束。
- 双 INMP441 默认设计方向为同一 I²S RX 的左右 Slot，同型号并不代表增益/相位已标定；b0.3 确定时钟、有效位、参考通道、麦距和标定方法，b3/b4 实测验收。保留原 PCM5102；不新增 DAC 或其他麦克风型号。

官方资料（b0.2/b0.3 以实际锁定版本核对）：

- [用户指定微雪 N16R8-M 官方文档](https://docs.waveshare.net/ESP32-S3-DEV-KIT-N8R8/?variant=ESP32-S3-DEV-KIT-N16R8-M)；[同产品官方英文概览及型号对照](https://docs.waveshare.com/ESP32-S3-DEV-KIT-N8R8)；[官方资源/原理图入口](https://docs.waveshare.com/ESP32-S3-DEV-KIT-N8R8/Resources-And-Documents)；[USB 串口 FAQ](https://docs.waveshare.com/ESP32-S3-DEV-KIT-N8R8/FAQ)；[官方商品版本说明（预焊排针）](https://www.waveshare.com/catalog/product/view/id/5541/s/esp32-s3-dev-kit-n8r8/category/628/)
- [乐鑫 WROOM-1 N16R8 Flash/PSRAM 模式对照](https://docs.espressif.com/projects/arduino-esp32/en/latest/troubleshooting.html)；[乐鑫 ESP32-S3 硬件设计指南](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32s3/schematic-checklist.html)
- [原经典 ESP32 微雪硬件文档](https://docs.waveshare.net/ESP32-DEV-KIT-XX/?variant=ESP32-DEV-KIT-WROVER-E-M)
- [INMP441 芯片数据手册（沿用原项目引用）](https://invensense.tdk.com/wp-content/uploads/2015/02/INMP441.pdf)

## 2. 分阶段路线

| 批次 | 主要工作 | 阶段出口 |
|---|---|---|
| P6.8b0.1 | 总体架构、现有实现及旧合同全量清点、现有性能基线 | 总体设计、合同迁移索引初版、实测基线或缺测记录 |
| P6.8b0.2 | 双板硬件、构建/刷写、GPIO、模型分区及 UART/SPP 桥接合同 | 硬件与通信分域规格/矩阵；供 b1–b2 |
| P6.8b0.3 | 双麦/I2S/DAC、AFE、AEC/BSS/VADNet/WakeNet、采样与缓冲合同 | 音频与语音前端分域规格/矩阵；供 b3–b4 |
| P6.8b0.4 | S3↔HA 事件、STT 启动与断句、本地提示音合同 | 语音会话及提示音分域规格/矩阵；供 b5–b6 |
| P6.8b0.5 | 打断、连续对话、音频所有权及表情事件协调合同 | 跨模块生命周期/显示分域规格/矩阵；供 b7–b8 |
| P6.8b0.6 | 全部合同交叉审计、历史合同归属复核、实施任务与验收追踪 | 修订跨域冲突，完整分批实施计划及测试映射；供 b1–b10，尤其 b9–b10 的清理/验收 |
| P6.8b1 | 建立 S3 主固件与经典 ESP32 蓝牙桥两个独立构建/刷写目标；复用 firmware 主模块，配置 S3 Flash/PSRAM/模型分区及完整烧录，核对 USB/串口和 GPIO 安全。 | 两个目标分别构建及刷写，型号/内存/模型分区正确。 |
| P6.8b2 | 拆分 SPP/Bond/重连，复用 tivoo_spp、tivoo_spp_session、control_bridge；S3 TCP ↔ UART ↔ 经典 ESP32 ↔ Tivoo，恢复真实 SPP 状态及 reverse channel。 | 既有 HA/MCP/亮度/屏幕/倒计时/GIF、独立重启恢复全部可用；大 GIF 不阻塞语音。 |
| P6.8b3 | S3 双 INMP441 同步采集（L/R）、PCM5102 输出及 AEC 数字参考和采样对齐；迁移 audio_capture、audio_playback、audio_output_manager、audio_resource、网络与既有 TTS 欠载修复。暂分离新算法变量，保留原始采集和诊断能力。 | 双声道数据正确、AUX 清晰、长音频不中断、收音和 UART 并行；重新标定声学延迟，不照搬旧 47.5 ms。 |
| P6.8b4 | 启用 S3 官方 AFE 双麦/参考布局（b0.3 确定 MMNR/FD HIGH_PERF 初始图，实际 pipeline 与声学由 b4 验证），BSS/AEC/VADNet、WakeNet；模型加载、wake state/重触发、VAD 缓存及时间轴；以官方示例为参考。 | 独立于 HA 的官方词唤醒、误/漏唤醒、电视及自身播放干扰下的声学测试；记录负载与内存。 |
| P6.8b5 | HA 本地唤醒入口：新增设备确认事件与必要 session/代次关联（具体字段在 b0.4/b0.5），修改 protocol、diagnostics、audio_session、assist_satellite；直接从 STT 启动 HA Pipeline，网络保持连接，命令 PCM 与 STT 准备协调；B5 可用测试/过渡提示音验证入口，量产本地提示音在 b6 完成；处理准备竞态和失败回退。 | 无 NAS WAKE_WORD run 的本地唤醒→STT→本地控制和 AstrBot/TTS；待机无 PCM，命令首尾不丢。 |
| P6.8b6 | 本地提示音与断句：复用生产音色现成 ready 素材/独立 follow-up beep 转 PCM 存 Flash，统一音频出口并与 AEC 实际 TX 参考一致；短提示音时隔离命令采集，结束后开放。S3 VADNet speech_end 驱动 STT 输入结束，按序消费尾部 PCM，再发 AudioStop；核对已部署 HA 公开接口和 VAD 行为，不改 HA Core 或盲目关闭 VAD。 | 无远程 MP3 提示音依赖；无自触发/旧播音抢占；约 400–600ms 初始静音参数实测调优，HA 不额外等待无意义断句。 |
| P6.8b7 | 本地 WakeNet 打断与连续对话：保持 AFE 常驻；确认后 S3 立即停止旧输出、通知 HA 按旧 generation/playback ID 取消 Pipeline/TTS/AstrBot SSE，旧轮清理与新轮准备协调；复用现有 owner 机制，避免旧 TTS 抢占；follow-up 只在真实回复完成且获授权时开放，首次（含再次唤醒打断）3 秒、续聊 4 秒从物理 gate 开始；按 b0.5 单次 FOLLOWUP_OPEN 授权与新 UUID，保留有效无 TTS 答复例外。 | 普通人声不打断，真实唤醒在识别/思考/合成/播放均有效，连续多次打断无旧音频或错误自动续轮。 |
| P6.8b8 | **表情状态机事件来源迁移**：修改 HA Satellite 到 display_state.py 的生命周期适配，保留 Coordinator 和 ScreenPowerGate、原优先级、TTL、显式显示、mood、中央息屏门控；用 S3 wake、命令及实际播放事件代替远程 KWS/候选事件，恢复桥接 SPP 状态；详见下节。 | 正常、打断、follow-up、取消、错误、重启重连和息屏/亮屏全覆盖；没有旧 generation 表情或提示音误触发 speaking。 |
| P6.8b9 | 本地 WakeNet 验收后删除 Tivoo 旧远程唤醒路径：候选上传、WAKE_WORD Pipeline、side KWS watcher、旧 3/15 秒候选计时/重建、远程提示音路径；保留 STT/TTS、必要诊断/会话取消。若无其他依赖才停止 NAS KWS 模型加载，不破坏其他消费者。 | Tivoo 单一唤醒路径，无长期双 KWS；更新 README、规格、配置、部署说明与旧测试归属。 |
| P6.8b10 | 双板综合实机验收、性能测量、稳定性回归；核销旧阶段转入的合同/GAP，必要时修复再验收。 | 记录真实声学、两类延迟、长 TTS、电视、连续打断、表情/屏幕/工具、重启/断网、UART 压力和 CPU/IRAM/DRAM/PSRAM；完整部署和证据。 |

## 2.1 设计批次细化（b0.1–b0.6）

**b0.1 交付：** [总体设计与迁移前基线](../specs/2026-11-18-p6-8-b0-1-overall-design-baseline.md)、[历史合同迁移索引初版](../specs/2026-11-18-p6-8-legacy-contract-migration-index.md)。完整声学/固件版本缺测及分域待核实事项见设计文档。

**b0.2 交付：** [双板硬件、构建/烧录与 UART/SPP 桥接规格及合同矩阵](../specs/2026-11-18-p6-8-b0-2-hardware-uart-spp-design.md)。GPIO、双 target、model 分区、UART 私有协议、真实 SPP 回报与恢复边界均在此定义；实物及构建验收留实施批。

**b0.3 交付：** [双麦 I2S、DAC、AFE 与本地唤醒规格及合同矩阵](../specs/2026-11-18-p6-8-b0-3-audio-afe-design.md)。含 ESP-IDF v6.1/ESP-SR 2.6.1 兼容核对、81 个原厂模型打包清单、双麦/真实 TX 参考/端点和声学验收约束。最终唤醒词未代选；b1 构建及 b4 实机 gate 保留。

**b0.4 交付：** [本地唤醒、HA STT 会话与短提示音规格及合同矩阵](../specs/2026-11-18-p6-8-b0-4-ha-stt-prompt-design.md)。核对生产 HA 2026.11.0、Wyoming 1.10.2、现有 pipeline/素材；设备端点通过有限 PCM iterator EOF 触发正常 AudioStop，专用 ASR 入口隔离原 provider，完整 Pipeline 验证归 b5；b0.5 补跨轮所有权。

**b0.5 交付：** [打断、连续对话、音频所有权与表情协调规格及合同矩阵](../specs/2026-11-18-p6-8-b0-5-lifecycle-display-design.md)。每轮 UUID 绑定普通 TTS playback ID，S3 先本地定向停止、HA 序列化取消旧 caller，独立授权 0x27 与真实 gate 计时；保持唯一显示仲裁，b7–b8 实施及 b10 实机。

**执行顺序：** b0.1 → b0.2 → b0.3 → b0.4 → b0.5 → b0.6 → b1–b10。每一批仅完成其设计范围，产出可独立审阅的文档或报告，不提前修改生产实现。跨域发现应回写所属规格，避免同一规则在多个规格中重复定义。设计阶段不等于声学/生产验收。

| 设计批次 | 核对与确定的内容 | 交付物及退出条件 |
|---|---|---|
| b0.1 | 核对当前真实代码、部署版本和已有验收报告；明确保留/迁移/替代/删除/延后边界；逐条清点 P3/P4/P5/P6/P6.5/P6.6/P6.7/P7A 合同、P7/P8/P9/P10 遗留项和后续修复要求；尽可能记录旧链路 KWS、提示音、命令末尾、VAD/AudioStop、STT_END、实际执行及回答首声 | 总体设计与统一历史合同迁移索引初版；基线证据及缺测原因；所有旧合同和明确用户需求均有归属，不因旧 PASS 就跳过受迁移影响的回归 |
| b0.2 | 以 §1.1 已确定的微雪 N16R8-M 和现有 WROVER-E-M 为基线，核对实际板型原理图、供电、引脚限制、USB/串口、独立构建及完整烧录、Flash/PSRAM/模型分区；UART 帧边界/必要流量控制、TVIO 兼容、SPP/Bond、双向返回和真实状态、任一板重启/断开后的恢复；大 GIF 对音频的影响 | 硬件/构建/UART/SPP 规格与矩阵；核对锁定 ESP-IDF 和真实上游协议；明确引脚、资源边界以及待实测项，供 b1–b2 |
| b0.3 | 以 §1.1 两颗同品牌同型号 INMP441 为基线，两麦 L/R 布局与采样、DAC 时钟及 SRC、AFE 实际通道布局、最终 TX 参考对齐、AEC/BSS/VADNet/WakeNet 模型与资源、音频缓冲和欠载、重触发与负样本；官方词和可用模型以实际版本为准 | 音频/AFE 规格与矩阵，供 b3–b4；接口与格式核实，麦距、AEC 延迟、VAD 阈值等仅规定初始候选与实测方法，不照搬旧值 |
| b0.4 | 核对实际 HA Core、Assist Satellite/Pipeline 和 Wyoming 源码；本地唤醒事件、session/轮次关联、STT 提前准备、命令 PCM 边界、speech_end→尾帧→AudioStop、失败/超时；现有 ready 素材与独立 follow-up beep、本地提示音出口和输入 gate | HA 语音会话/提示音规格与矩阵，供 b5–b6；确认设备断句所需 HA 接口或记录最小验证/可行替代，禁止凭猜测锁定接口 |
| b0.5 | 跨阶段 WakeNet 打断、旧 owner 释放、迟到 TTS/AUDIO_STATE、连续对话授权/窗口、提示音误触发、generation 对齐；表情 wake_confirmed/active_listening/thinking/tooluse/speaking/followup_wait、mood、息屏门控、SPP 状态及重连 | 生命周期/表情事件规格与矩阵，供 b7–b8；以正常与异常时序逐项核对，不创建第二套显示仲裁或播放所有权 |
| b0.6 | 交叉审查前五批规格、接口双方、需求/历史合同覆盖、测试责任、清理条件及最终声学/性能回归 | 正式迁移追踪索引、分批执行计划及测试/验收映射；修订发现的冲突，不新增无来源功能；通过设计出口后才开始 b1 |

b0.5 必须跨模块至少审查：唤醒后 HA 未就绪、识别/思考/合成/播放时重新唤醒、旧 TTS 在本地停止后继续到达、follow-up beep 或自身回复误触发、旧播放终态覆盖新表情、息屏期间打断和 SPP 重连、任一 ESP32 独立重启、HA 断线/重载。对应测试分别归入实际拥有行为的实现批次，b10 再做端到端闭环。

## 2.2 合同追踪与设计出口

- **统一追踪链：** 原合同 ID/用户需求 → 归属（保留、迁移、替代、删除、延后）及理由 → 新合同 ID 或仍生效的原合同 ID → 实施批次 → 测试/实机验收 → 验收证据。旧合同未覆盖或新合同无需求来源、无实施/验收归属均须修正；延后和明确废弃项保留记录，不虚标 PASS。
- **合同确定方式：** 已经由真实源码/锁定版本上游确认的接口直接锁定；硬件相关不确定值在设计阶段确定约束、测量方法和验收阈值的决策条件，由 b2–b4/b6 等责任批次依据实测锁定；无法确认的上游接口安排最小可行性验证，记录结果及可行替代，不使用猜测的字段/方法。
- **待定项边界：** 记录具体问题、验证方式、责任批次和阻塞的依赖；影响核心架构可行性或下一批接口的项须在进入依赖实现前解决。仅待硬件实测的非阻塞参数可保留为受控待定，不以占位符代替核心合同，不提前标注硬件验收通过。
- **b0.6 审查出口：** 逐条覆盖现有需求与历史合同；核对跨域事件字段、方向、数据格式、时钟、所有权、取消顺序和恢复语义；每个可实施合同有明确批次、用例和验收依据；高风险正常/异常时序有对应测试；清理条件、回归范围、未决事项及后续处理均明确。发现遗漏或冲突时回到所属规格修订，不把未解决的跨域错误带入实现。可用独立审查能力时做规格评审，否则逐域自审并如实记录限制。

## 3. 表情事件迁移方向（b8）

| 现有状态 | P6.8 目标事件来源 |
|---|---|
| wake_confirmed | S3 本地真实 WakeNet 确认，包括打断；按当前/新 generation 立即提交，高于旧 speaking，不等待 NAS WAKE_WORD_END。 |
| active_listening | 仅本轮命令或获授权 follow-up 的真实 speech_start/end；取消待机候选人声的 700ms/35%/10s 随机监听规则（待机不传环境音）。保持 idle 轮换。 |
| thinking / tooluse | 保持 STT_END 非空有效命令及 AstrBot tool_call/tool_call_result 的现有语义，不用 STT_START 代替。 |
| speaking | 仅当前回复 playback ID 的真实 AUDIO_STATE playing/终态；本地 ready/beep 单独归类，不触发回复 speaking 或 follow-up。 |
| followup_wait | HA 当前结果严格授权 + 正常 run 与真实回复 completed（有效无 TTS 例外）+ 新 local_followup 的安全 COMMAND_GATE，用匹配轮次的新 speech 或超时退出；不得被旧终态重开。 |
| idle / explicit_content / ai_mood / screen gate | 保留原逻辑、优先级、TTL、owner inhibit、重连重放规则；任何旧轮或失效连接事件不得覆盖当前 desired，HA 为唯一显示仲裁者。 |

SPP 连接状态来源为蓝牙桥的真实状态，经 S3 转发；UART 重连/经典 ESP32 重启、S3 重启及 HA 重载都要回归，不能将 UART/Wi-Fi 连通等同于 SPP 已连。

## 4. 旧阶段归属及执行顺序

旧文档/日志是历史合同及证据，不删除旧 PASS，不把旧 GAP 自动视为完成；仅停止按旧拓扑重复开发，b0.1 建立合同 ID 迁移索引，b0.2–b0.5 分域补充，b0.6 统一核查，B10 依据新证据核销。

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
- 正常短指令本地命中：尝试唤醒提示音首声 ≤300ms、STT 返回 ≤1.2s、HA 执行 ≤1.5s；本地 WakeNet 确认到停止旧音频 ≤100ms。按 b0.1 基线和实测校准目标，LLM/TTS 单独计时。
- 待机无 PCM 上传，双麦环境下误/漏唤醒和电视干扰较基线有可测改善；验证提示音隔离、普通播放全双工、无空轮/旧音频/多余表情、长 TTS 与 GIF 并发、断电重启和长期运行。
- 开发机优先构建和自动化，NAS/两板仅进行必要部署和实机验收。每批按实际证据 PASS/GAP/FAIL，不将自动化等同于声学验收。

## 6. 上游参考（b0.2–b0.5 按领域核对实际锁定版本）

- [ESP-SR S3 AFE](https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/audio_front_end/README.html)
- [ESP-SR WakeNet](https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/wake_word_engine/README.html)
- [ESP-SR 上游及模型选择](https://github.com/espressif/esp-sr)；[ESP-SKAINET 官方示例](https://github.com/espressif/esp-skainet)
- [ESP-IDF S3 UART](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/uart.html)
- [HA Assist Satellite](https://developers.home-assistant.io/docs/core/entity/assist-satellite/)；[HA Assist Pipeline](https://developers.home-assistant.io/docs/voice/pipelines)

本路线只设定总体步骤，不是详细规格、合同矩阵或可直接执行的实现清单；b0.1–b0.5 文档设计出口已记录，下一步仅展开 P6.8b0.6；b0.6 审查通过后进入 b1。
