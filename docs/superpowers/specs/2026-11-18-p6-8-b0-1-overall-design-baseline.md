# P6.8b0.1 总体设计与迁移前基线

> 2026-11-18；main d79775f，当前设计分支起点 be73329。仅架构、历史合同索引和基线证据；不代表新固件、GPIO/协议细节或声学验收完成。后续以[总体路线](../plans/2026-11-18-p6-8-s3-local-wake-roadmap.md)和[逐 ID 迁移索引](2026-11-18-p6-8-legacy-contract-migration-index.md)为入口。

## 1. 迁移前真实实现与证据等级

- 单 ESP32 WROVER-E-N16R8，当前固件源码 Kconfig 默认 BCLK26/WS25/MIC SD32/DAC DIN33、GPIO27 RGB 灭灯（4a14592）；非新 S3 接线。IDF v6.1（P5 环境报告），`esp32/firmware/main/idf_component.yml` 锁 esp-sr 2.6.1、esp_audio_codec 2.6.2、esp_audio_effects 1.4.5；sdkconfig.defaults 为 16MB flash、Quad PSRAM 40MHz/himem、Wi-Fi/lwIP 优先可用 PSRAM。实际芯片目前运行的固件版本本次未取得 HELLO 证据，不把工作区源码版本当作当前固件。
- `main.c`、`wifi_station.c`、`network_listeners.c` 启动单板 Wi-Fi/7777/7778；`control_bridge.c`、`tivoo_frame_stream.c`、`tivoo_spp.c`、`tivoo_spp_session.c` 承担 raw Tivoo 帧、Bond、连接及 reverse queue；`diagnostics.c`、`device_status.c` 承担 TVIO 和设备状态。
- `audio_capture.c` 使用共享 I2S RX/TX 双向时钟，一颗左 slot INMP441，32 kHz 采集、降至16 kHz；`audio_frontend.c` 初始化 MR、AFE_TYPE_SR/HIGH_PERF、vad_mute_playback=false；旧声学标定760 samples/47.5ms。固件 VAD 候选触发 MIC 上传，15s 超时后重臂由 4a7c2b9 修复；此行为不是本地 WakeNet。
- `assist_satellite.py:AudioSessionCoordinator` 当前 on_activity 首次 speech_start 进入 WAKE_WORD；miss 3s、候选 15s；WAKE_WORD_END 命中、有 ready 素材时终止旧轮、等待远程提示音、重新在 STT stage 从新鲜 ingress_offset 读取。STT_START 起命令5s、STT_VAD_START 解除；STT_VAD_END/STT_END 释放订阅。side watcher 调用远端 KWS；普通 VAD 无打断权。旧实际延迟包含候选、网络、远程判断、旧 Pipeline cleanup、HTTP 提示音、再启动 STT、HA endpoint；不能将这些时段简单相加或预估为实测。
- `audio_session.py` 管有界 PCM/订阅，`tts_lifecycle.py` 管 run owner/cache producer/consumer，`audio_resource.py` 与 `transport.py` 负责 TTS URL/设备通知、ID/终态。设备 `audio_resource.c` → `audio_playback.c` → `audio_output_manager.c` → PCM5102，正常 HA proxy 32kHz mono MP3。59e1bac 跨段间隙静音，b278dc3 内存/诊断非阻塞及 cache 等待 producer、断开和终态修复，全部保留语义。playing 是已有 PCM 进入路径，不代表模拟首声。
- `prompt_audio.py:PromptSoundPlayer` 独立 owner，ready_01..03 随机无相邻重复、followup_01 独立单嘟，真实提示音/尾部 gate 抑制 MIC/VAD；当前是 HA 静态 HTTP MP3，不是新目标本地 PCM。不得把 gate 扩大到正常 TTS。
- `astrbot/conversation.py,api.py,sse.py,session.py` 仍为 HA Agent、流式 ChatLog、会话与显式 Stop；735ca78 的问号规则及 INTENT_END 严格 true 与匹配回复 completed（无 TTS 有效响应走 _complete_response）共同决定续聊，当前 _open_followup 先启动8s timer 再发嘟声；新计时从哪个有效边界起由 b0.4/5 固定。普通回答不得自动续轮。
- `display_state.py:ExpressionCoordinator/ScreenPowerGate` 为 HA 唯一显示决策；`assist_satellite.py` 是生命周期适配；`services.py/llm.py/device_commands.py` 保持语义工具/显式内容；mood、TTL、gate inhibit、C19 stale control recovery 保留。禁止在 S3 或桥重复创建协调器。
- `services/sherpa_wyoming/providers/{wake,stt,tts}.py` 是三个独立请求路径；维持同一 Wyoming 服务，STT 整句 Paraformer、TTS Matcha 分段，不用替换模型解决编排延迟。

### 1.1 2026-11-18 NAS 只读核对

通过新 IPv6 使用已有 NAS 可信 HostKeyAlias（已记录的 192.168.3.94），StrictHostKeyChecking=yes 成功；不新增信任记录。通过 DSM Docker 绝对路径查询。

| 组件 | 实际可核对证据 |
|---|---|
| HA | 容器 homeassistant image 2026.11.0，运行中；下列核心代码与工作区 SHA256 逐文件一致：tivoo/assist_satellite.py、audio_session.py、prompt_audio.py、display_state.py、transport.py、diagnostics.py、tts_lifecycle.py；astrbot/conversation.py、api.py、sse.py、session.py（共11）；不能从抽样 hash 推定全量一致或当次内存已加载。 |
| AstrBot | image tag latest，Python importlib.metadata 实测 astrbot 4.29.4 |
| Wyoming | ghcr.io/qyxx2/tivoo-sherpa-wyoming:sha-d320db56187431b46720b3117e791f42c3733e34，healthy；printenv WAKE_WORD_PHRASE 实际为“大肥鱼”，与历史 Pinkman 提交不等价；镜像标识不证明运行时配置。未修改词、HA pipeline 或服务。 |
| 提示音 | NAS /config/www/tivoo/prompts 四个 MP3 与工作区 homeassistant/prompt_assets 全部 SHA256 相同（包含 d79775f 嘟声）。 |
| ESP32 | esptool 4.8.1 容器在线；本次现有 HA 日志中未取得 firmware_version，不抢占7777/7778、不读串口或重启来强制取值；运行固件 commit、实际 GPIO、内存峰值留 GAP；可在 b1 前利用正常 HELLO/必要只读设备观测确认。 |
| HA 本地意图生产配置 | 用户既有文字本地响应和本地控制要求保留；本次不读取完整 HA 配置或触发实体，精确 pipeline/local-preference/口语文件实际状态留 b0.4 核对。 |

证据等级：源码是当前 checkout 行为；容器镜像/文件哈希是本次现场证据；下节既有测试为历史实测；新板尚未上板、未测不能标 PASS。没有人为触发语音、控制灯/屏幕、播放或取消实机。额外尝试通过 AstrBot 模块导入取版本时 ImportError，日志提示 config key order fixed；版本以先前成功的 importlib.metadata 为准。未主动编辑配置，但该导入可能触发应用自身配置顺序整理，本次未验证是否写盘。

## 2. 目标总体设计（以责任边界为合同，不预造接口）

```text
INMP441 L/R → S3 I2S RX → AFE (M/M/R，具体布局待 b0.3)
                           ├ WakeNet 确认 / VADNet 断句
                           └ 当前有效命令 PCM → S3 7778 → HA Satellite → STT
                                                               → HA 本地 intent 优先
                                                               → AstrBot fallback
                                                               → HA Matcha / TTS Proxy
S3 本地提示音 ──────────────────┐                            ↓ HTTP MP3
                                └→ 唯一输出 owner ← S3 TTS reader
                                    → 最终 TX → PCM5102/AUX → Tivoo
                                    ↘ 实际 TX PCM 参考 R → AFE
HA MCP / 服务 / ExpressionCoordinator / ScreenPowerGate
         ↕ 7777/7778 (兼容原 TVIO / 原始 Tivoo frame)
       S3 ↔ 独立硬件 UART（TX/RX/GND）↔ WROVER-E Classic SPP ↔ Tivoo
```

| 所有者 | 必须负责 / 不负责 |
|---|---|
| S3 | Wi-Fi、两 TCP、真实双麦前端、本地 WakeNet/断句、提示音及唯一 DAC 输出、正常 TTS HTTP、诊断；待机常驻收音但无环境 PCM 上行；只给 HA 发事实事件，绝不自行决定 HA 表情或继续对话。 |
| 经典 ESP32 | UART↔Classic SPP，Bond/NVS/MAC、真实连接状态与反向原始数据；不承担 Wi-Fi、I²S、AFE 或会话。UART 带宽、队列/背压与分帧由 b0.2 确定，避免 GIF 阻塞语音。 |
| HA | Satellite/Pipeline 轮次/取消、先本地 Intent 后 AstrBot；TTS provider/cache、唯一显示与 screen gate、MCP/服务；只接受当前轮/播放真实事件；不创建第二套显示或播放逻辑，不改 HA Core 来绕过未核实接口。 |
| NAS Wyoming/AstrBot | 保留当前 STT/TTS、SSE Stop 和服务隔离；原远程 Wake Provider 只在确认没有其他消费者后才停止加载，b9 后 Tivoo 单一路径；禁止未验收先删。 |

硬件高层判断依据：微雪[型号表](https://docs.waveshare.com/ESP32-S3-DEV-KIT-N8R8) 确认 N16R8-M SKU28836、CH343/CH334、GPIO35/36/37 NC；乐鑫[IDF v6.1 蓝牙类型表](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-guides/bt-architecture/overview.html) 表明 S3 无 Bluetooth Classic、支持 LE，因此不能用 S3 直接代替 SPP。乐鑫[AFE](https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/audio_front_end/README.html) 与[WakeNet](https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/wake_word_engine/README.html) 验证 S3 支持 WakeNet9 系列及双麦 AFE 方向；latest 文档只验证架构可行方向，非 esp-sr 2.6.1 具体字段/模型证明。板型/麦克风/PCM5102 权威规格仍为路线 §1.1；禁止在本批指定引脚、AFE 模型/通道顺序、UART baud 或最终声学参数。

### 2.1 正常、打断与失败

1. S3 待机始终 AFE/WakeNet，本地确认后，通知 HA 准备仅从 STT 开始的轮次，同时本地提示音开始。命令门在提示音真实完成/声学尾部及 HA 可接收协调后开放；用户明确听完再说，不携带旧 wake tail；缓冲与准备竞态由 b0.4 验证。准备失败可恢复待机，不遗留任何等待。
2. VADNet 输出命令开始/结束，尾部有效 PCM 先于结束事件交给 STT。HA 如何消费结束并生成 Wyoming AudioStop，必须 b0.4 查生产源码和做最小验证，未验证不假设关闭 HA VAD 可行。
3. 正常 TTS 播放中持续真实 TX AEC 参考与 WakeNet；普通人声不得抢占。确认新 wake 由 S3 先停止旧音频、HA 对旧代次定向停止 Pipeline/TTS/AstrBot session，不能以旧终态覆盖新轮；本地物理 stop 与 HA owner cleanup 并行协调，禁止旧 producer 继续下发到新音频 owner；详细事件见 [b0.5 生命周期与表情合同](2026-11-18-p6-8-b0-5-lifecycle-display-design.md)。
4. 仅当前 HA 结果授权且回复正常完成才进入 follow-up，独立嘟声而非 ready 人声；保留明确无 TTS 有效回答的旧语义，判据见 [b0.5 生命周期与表情合同](2026-11-18-p6-8-b0-5-lifecycle-display-design.md) §4。5/8s 等待窗口在真实可收音边界计时；取消、错误、普通回答不打开续轮。提示音 gate 内有意不接收命令，普通 TTS 不扩大 gate。
5. 显示事件迁移：S3 wake→wake_confirmed（立即高于旧 speaking）；有效命令 speech→active_listening；非空有效 STT_END→thinking；实际 AstrBot 工具事件→tooluse；匹配真实回复播放→speaking；授权并真实回复/嘟声完成→followup_wait。idle 随机轮换保持，但去掉旧候选人声显示。显式内容、mood、screen inhibit、TTL 和重连重发保留。桥报告真实 SPP，UART 连通不代表 SPP 已连。
6. 任一板/HA 网络失联、设备重启：当前旧代次失效、定向资源清理，新握手恢复真实状态、不重播过时提示/回复；具体恢复时序分别 b0.2/4/5 审核。UART 帧错误不得阻塞音频，不提前引入通用消息总线。

## 3. 迁移前性能基线与缺测

既有数字实测与本次容器核对的日期不同，不能合成一条虚拟端到端计时。用户观察语音控制约5–6s仅作症状，不算同步计时。以下均引用仓库原报告，不重跑会播放声音或改变实体的场景。

| 测量点 | 历史数据/来源 | 对新链比较的含义 |
|---|---|---|
| NAS 远程 KWS | [P7A acceptance §3/4](../reports/2026-11-10-p7a-acceptance-report.md)：官方 1.43–1.54s 音频命中 wall 1.45–1.80s，计算0.12–0.18s；负样本8.03s处理8.1–10.1s；不是词结束→命中 | 真实麦克风当前词结束到 Detection 未测；本地确认需 b4/b10 录音对齐 |
| 旧 ready 提示音 | [P6.7b3](../reports/2026-11-16-p6-7b3-device-acceptance.md)：三条 TTS_PLAY 到 playing 216.5/264.3/226.2ms；VAD speech_start 688.9/826.4/718.2ms（不是 completed）；当时均触发 VAD，后续 gate 修复 | 仅协议计时，非 KWS→实际首声；本地资产减少 HTTP/解码/预缓冲的可能时间，数值待测 |
| 参考尾部 | [P6.7 fix](../reports/2026-11-16-p6-7-prompt-vad-suppression-fix.md)：760 samples/47.5ms，此板 gate 向上取整48ms | 新声学布局必须重新标定，不直接继承 |
| 命令末尾→端点 | P65-A05 旧 HA VoiceCommandSegmenter 初始合同 0.3s speech/1.0s 最小 command/0.7s silence/15s timeout；实际源码当前切换需 b0.4 核对 | 当次真实语音末尾、STT_VAD_END、Wyoming AudioStop 时间均缺测；旧理论阈值≠实际等待 |
| STT 解码 | [P7A acceptance](../reports/2026-11-10-p7a-acceptance-report.md)：5.033s 中文样本0.417–0.464s；8.100s 中英0.788–0.802s，RTF 0.083–0.099 | 不是用户命令末尾到 STT_END；保留模型、优化送入/断句 |
| HA STT_END / 实际执行 | 当前代码通过有效 STT_END 发 thinking，未取得一轮对齐日志/真实执行时戳 | GAP；b5/b6/b10 从命令末尾、STT_END、真实只读查询或受控动作验证，不以 INTENT_START 等同执行 |
| TTS provider/HTTP 首块 | 同 P7A：provider 直测首块0.643s、服务分段0.566s，HTTP proxy 两次2.215/0.200s | 区分冷/热和不同测试，无完整回答首声实测 |
| 数字播放延迟 | [P6.5b10](../reports/2026-11-14-p6-5b10-esp32-playback.md)：22.05k mono 原始 MP3 buffering→playing 390–420ms（均402.5），32k mono 90ms；两种均无此次欠载、SRC 平均1.2175s→0，120ms 输出预缓冲在 playing 后 | 首块数字≠AUX 首声；保留现有32k mono proxy 及后续间隙修复，b3 重新对照 |
| 旧 stop / 资源 | 同 b10 32k mono STOP→stopped 102ms（另一次 NAS 转码样本66.6ms）；P7A 峰值进程 RSS 374276KiB、首次模型加载13.609s | stop 为协议终态非物理停音；现有固件内存实际峰值与当前版本未测；b10 分域采集 |

缺测原因：当前连接允许 NAS 只读证据核对；没有可控真人唤醒、同步记录真实声学起止的装置及安全的实际实体命令场景。本批不使用合成日志、抢占生产 socket、操作 GPIO/刷机/播放或变更配置来冒充真实测量。后续 b10 使用同一单调时钟与录音对齐，多轮分别记录 t0 唤醒词尾、t1 确认、t2 真实提示首声、t3 提示末尾/命令门、t4 命令人声尾、t5 VAD_END、t6 AudioStop、t7 STT_END、t8 实际执行或状态结果、t9 TTS provider 首块、t10 首次数字 TX、t11 真实回答首声；本地命中与 LLM 分开，冷/热分开，失败也记录；不要以任何两种时间基准直接相减。暂保留路线的300ms/1.2s/1.5s/100ms尝试目标，不宣布改善幅度或保证。

## 4. 分域移交与未决事项

| 下一领域 | 本批不替它猜测的事项 / 出口 |
|---|---|
| b0.2 | 实物板版次、引脚/串口/供电、两 target 完整编译/flash、实际 UART 分帧/容量、SPP 状态与 bonding；查锁定版本及原理图。 |
| b0.3 | ESP-SR 2.6.1 真实 S3 model/API、官方词供用户择定、双麦 slot/BSS/参考布局/VADNet 端点、采样/时钟及麦距；先核实再选型号，后续实测校准。 |
| b0.4 | 生产 HA API/配置与 STT endpoint 可行性、PCM/结束事件、准备竞态、音色素材与提示音/时序；不给假字段。 |
| b0.5 | 轮次/owner/取消时序、follow-up 授权与计时、显示适配、断开重连；原表达式优先级不变。 |
| b0.6 | 逐项正式新合同/原 ID、测试、验收映射；解决跨域冲突后方可 b1。 |
| b10 | 新板真实声学/首声/端点、负样本、误漏率、长回复/滚动 GIF、断开重连、资源、完整回归；旧 PASS 仅作历史证据，不自动继承。 |

## 5. b0.1 出口自审

- 合同矩阵八份逐行索引共192个原 ID（P3 28/P4 15/P5 25/P6 20/P65 16/ESM 23/PR 21/P7A 44），另外19个历史/用户需求追踪项；原 ID 一一覆盖由脚本严格集合核对，未创建虚构的新合同 ID。历史 GAP 未核销。
- 架构、边界、实际源码、NAS 只读证据和历史性能数据已记录；固件运行版本、生产 HA 本地配置精确值和完整声学延迟缺测已显式登记。
- 本批不实现/编译/烧录、不重启任何服务、不触发语音或设备控制。只自审文档，无独立 reviewer；b0.6 全量交叉审查仍必需。
