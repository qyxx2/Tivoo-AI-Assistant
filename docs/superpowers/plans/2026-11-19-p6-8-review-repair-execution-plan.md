# P6.8 B1–B8 审查修复分批执行计划（R01–R11）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended when available) or superpowers:executing-plans. 仅执行用户当次授权的一个批次；使用 test-driven-development、systematic-debugging（故障路径）与 verification-before-completion；逐任务 RED/GREEN，审查、报告、独立本地提交。无独立代理时明确说明，自审不冒充独立代理。

**Goal:** 在 B8 完成基线之上核销八份审查的全部软件问题、证据遗漏及产品合同冲突，保留硬件与生产 GAP，不提前进入 B9 清理。

**Architecture:** 沿现有 S3/Classic 双固件、UART/7777 与 7778 隔离、32k DMA/16k AFE、HA public Satellite Pipeline、唯一音频 owner 与 ExpressionCoordinator 修复，不创第二套链路。底层故障恢复、输入轮、输出轮及显示组合各有独立可测试交付。

**Tech Stack:** ESP-IDF v6.1、ESP-SR 2.6.1、codec 2.6.2、effects 1.4.5、HA 2026.11.0、Wyoming 1.10.2；沿现有 C host/Python 测试及两 target 构建。

**Spec:** [原 B1–B10 执行计划](2026-11-18-p6-8-b1-b10-execution-plan.md)、[路线](2026-11-18-p6-8-s3-local-wake-roadmap.md)、[硬件/UART](../specs/2026-11-18-p6-8-b0-2-hardware-uart-spp-design.md)、[AFE](../specs/2026-11-18-p6-8-b0-3-audio-afe-design.md)、[语音](../specs/2026-11-18-p6-8-b0-4-ha-stt-prompt-design.md)、[生命周期/显示](../specs/2026-11-18-p6-8-b0-5-lifecycle-display-design.md)、[ESM 矩阵](../specs/2026-11-14-tivoo-expression-state-machine-contract-matrix.md)、[迁移索引](../specs/2026-11-18-p6-8-legacy-contract-migration-index.md)、[cross-audit](../reports/2026-11-18-p6-8-b0-6-cross-audit.md)。

**Review input:** 本地忽略证据 `.superpowers/p68-review-summary/repair-recommendations.md`（F01–F18）及 `.superpowers/p68-b{1..8}/review.md`（34 个编号）。基线分支 feature/p6-8-s3-local-wake，HEAD 0b312dda75b3d3b392e5d953a7cd66e60b2ac44c。原审查基于历史完整 diff 与 HEAD 复核；本计划末尾存完整映射和可执行断言，即使其他 checkout 无 ignored 证据仍可确定范围；必要复现细节回查原报告。原 B1–B8 实现结束不等同软件及物理全部 PASS。

## Global Constraints

- 只修已审查的 F 项。已明确的规格、wire ID、方向、GPIO、采样格式、owner、UUID/epoch、FIFO 不变；不增加公开 HA/MCP 参数、不 patch HA Core，不重写架构。需改变合同或无法由锁定源码决定的事项先停止该子任务并确认，不能假设用户已批准。
- 32 kHz stereo 32-bit I2S，160 sample/5ms ×12 DMA；16 kHz MMNR 增强；320 sample/20ms PCM，500ms history，pending 上限1s；首次3s、续聊4s、命令15s，短 prompt drain 5s watchdog。合同外 STT finalize 等数值必须按现有数据及服务/调用链确认，再记录依据；不套用采集时限或截断正常 TTS。
- S3/第二颗 INMP441 实物未到位且禁止刷写旧 ESP32。全 R 批仅开发机软件验证：不连 NAS、不部署、不改生产配置、不擦 NVS/Bond、不启用未标定 production/TEST_GATE。重新实测需要另获硬件操作授权。T01–T08 物理 GAP、T09 条件清理、T10 全量核销照原计划。
- 保留 legacy 共存及 10400/10401、四 MP3、原有效测试、B6 prompt_rearm、B7 monotonic uptime 和原生命周期/停止所有权。拒绝为了绿测试删断言、虚构 ACK/终态、将 static inference 描述为实际硬件复现。
- 每批先检查 branch/HEAD/工作区及前置报告；按实际代码核对调用入口、参数、锁/owner、上游 API，不盲抄旧行号。计划新增测试名称是拟定名称，源文件/现有入口已核对；不预造未经核实的新 API 签名，涉及上游失败恢复的最小接口由本批第一步确认并在报告记录。先写断言再实现，旧证据缺口若新断言已通过，记录为补证，不制造 RED 或无意义生产变更。
- 每批报告 `docs/superpowers/reports/YYYY-MM-DD-p6-8-rNN-repair-acceptance.md`，日志 `.superpowers/p68-rNN/`（忽略）；列 F/R/T/合同编号、变更范围、RED/GREEN 证据（实际 test node、命令、exit、失败原因）、相关回归、构建/哈希、未核销项、下一批依赖。逐批检查完整 diff、记录当前软件核销状态，不改写历史验收结果。除本批相关文件、计划勾选和报告外不动其他文件；按授权独立本地提交，不切 main、不 push。
- 开发机使用已有环境与脚本；只对受影响固件构建，限并发（建议 -j 1 或按内存实测小并发）；不让宿主机 OOM。生成 sdkconfig、编译内部产物与临时凭据不提交。R11 再跑两 target clean build 和全量；原 test fixture 波动须查明、复跑并报告，不能仅删除失败。
- 运行命令约定（repo root）：下文 HA/ESP 用 `PYTHONDONTWRITEBYTECODE=1 bash scripts/test-ha.sh <列出的测试路径> -q -p no:cacheprovider`；Sherpa 用 `bash scripts/test-sherpa-wyoming.sh <路径> -q`；如真实 HA fixture 仍需历史 B5 pythonpath，先核对已存在的 `.superpowers/p68-b5/pythonpath` 与锁定依赖，按原 B5 环境设置，不能把缺依赖算产品故障。构建在 `esp32/firmware`、`esp32/bridge_firmware` 各自项目内使用现有 IDF v6.1 环境，沿 B1/B2 已验证方式使用 `CMAKE_BUILD_PARALLEL_LEVEL=1 idf.py reconfigure` 后 `nice -n 5 ninja -C build -j1`、`idf.py size`（独立目录时以实际 build 路径替换），两工程串行；生成配置与独立 build 目录须核对 target，不覆盖生产归档；初次配置才 set-target。报告以实际命令为准。

## Review Focus（本计划必须覆盖）

1. 已可见 FIN/RST 与延迟 ACK、旧 peer/error → R02：不得提交旧 staging、不得跨 peer 或错误关闭新连接。
2. 单漏 EOF、旧 PCM 与无法确认 drain → R03：不得假报安全 gate，恢复后有真实有效帧或显式不可用；R04/R05 使用该边界。
3. 提示音内 speech 延续、gate 后立即开口 → R04/R05：静音不自动开命令，真人首声不丢。
4. 提前 Transcript/未 drain 的 end 与正常 EOF 后 STT 无响应 → R06：前者绝不能发 Intent，后者及时释放；R09 真正组合验证。
5. 迟到 followup 拒绝失败、丢失 TTS terminal、无可见 mood 及慢 SPP → R07/R08/R10：旧轮不能杀新轮/RX，当前轮收敛，按明确合同输出真实赢家。

## 批次与依赖

R01 是构建证据；R02 控制链；R03 是独立且最重的音频底层；R04 AFE/VAD；R05 校准与提示音真实适配验证；R06 HA STT 与 Sherpa；R07 轮次入口；R08 资源终态；R09 真实全链路组合；R10 显示；R11 总复验。前置关系为语义依赖而非要求重复修改，推荐按编号执行；R06/R07 可在 R03–R05 硬件无关软件工作期间独立执行（同一工作区不得并行写重叠文件）。R10 的 Mood 产品裁决可提前取得，但未获批准不得改冻结合同。每批完成后停在该批，不自行推进。

| 批次 | 独占主责 | 必须前置 | 对应原测试组 |
|---|---|---|---|
| R01 | F01 | B8 基线 | T01-A |
| R02 | F02/F03/F04 | R01 的独立 target 构建 | T02-A/B/C、T08-C |
| R03 | F05 | R01 | T03-B、T06-B |
| R04 | F06/F08 | R03 | T04-A、T06-B、T05-C |
| R05 | F07/F13 | R03/R04 | T03-A/B、T04-A/B、T06-A/B |
| R06 | F09/F10/F15 | B8 基线 | T05-A/B/C |
| R07 | F11/F12 | R06 的输入收敛 | T05-C、T06-B、T07-A/D |
| R08 | F14 | R03/R05/R07 | T07-A/B/D |
| R09 | F16 | R05–R08 | T05-A/C、T07-A/C/D |
| R10 | F17/F18 | R02/R09；F17 产品裁决 | T08-A/B/C |
| R11 | 全量软件证据复核 | R01–R10 均完成或明确未通过 | T01–T08；不核销 T09/T10 |

## R01 — 双 target 构建与真实入口证据

**F01 / B1-R01–04；HB02–04/HB11、T01-A。**
**Files:** `esp32/firmware/main/{s3_main,wifi_station,board_boot}.c`，`esp32/bridge_firmware/main/main.c`，两 project CMake/sdkconfig.defaults 及归档机制；`tests/esp32/{test_p5_hardware_memory,test_p5b3_bootstrap}.py`。原则只补证，不先改生产 Wi-Fi 逻辑。
**Interfaces:** 两 active app_main → NVS/board_boot/diagnostics/listeners/Wi-Fi；独立 S3/Classic ELF 与 config/flash manifest。

- [x] R01.1 新增 test_active_targets_boot_and_memory：断言真实 S3/Classic CMake 图、NVS 不擦除、S3 NVS→诊断→监听→Wi-Fi、两入口 board_boot memory、Classic RGB；保留旧有仍有效断言。测试 clean checkout 不依赖未生成 sdkconfig，将有效生成配置断言明确置于 configure 后。
- [x] R01.2 使用非生产 dummy SSID 独立 S3 配置构建（不改默认空凭据机制），核验 ELF 中 esp_wifi_init/start/connect 与 SR 同在，map/size、PSRAM、partition/flash_args；Classic 独立构建，核验 SMP/BR_EDR/SPP、BANKSWITCH_RESERVE=8、NVS、RGB 及无 Wi-Fi/AFE/I2S runtime。
- [x] R01.3 保存本批实际脱敏 config snapshot、manifest/hash，配置顺序可在 clean checkout 重现；不重造 B1 历史 config。运行上述二测试（生成配置后）和两目标 build；确认 NVS/真实 AP/内存与回退仍 GAP。报告、审查、本地提交。

软件验收：[R01 修复验收](../reports/2026-11-19-p6-8-r01-repair-acceptance.md)，F01 软件证据核销，T01-B 实物 GAP 保留。两独立 target build、实际 ELF/配置/分区验证 exit 0，专项 19 passed。

## R02 — UART/SPP 连接与可信状态

**F02/F03/F04 / B2-R01–04、B8-R02；HB06/07/08/10/12/13/14、VIEW-C04、ESM-C19、T02-A/B/C、T08-C。**
**Files:** `esp32/firmware/main/{network_listeners,uart_transport,uart_link,uart_router,tivoo_spp,tivoo_spp_session}.c` 及必要 header；Classic CMake 复用同一组 shared 文件；`homeassistant/custom_components/tivoo/{transport,display_state}.py`；`esp32/tests/p5b3_control_simulator/control_host.c`、`esp32/tests/p68_uart/{link_host,router_host}.c`、`tests/esp32/{test_p68_uart,test_p5b3_control_bridge,test_p5b3_session,test_p5b3_security,test_p6_reverse_channel,test_p6_device_status}.py`、HA test_transport/test_display_state。
**Interfaces:** 7777 raw→staging→UART OPEN/CLOSE/FRAME/ACK + epoch→SPP generation/peer/WRITE；反向 ERROR 关联请求 epoch；7778 STATUS→现 coordinator 发送资格。

- [x] R02.1 RED：真实 listener 一次 sendall 两帧，首帧到桥后 FIN/close 或 RST，延迟 ACK，第二帧不能进入桥；7778 同时正常。用已有 control_host ACK seam；正常两帧与已开始 SPP write 不撤销亦有断言。修复可见 EOF/RST 检查、未提交 staging/token 作废，保留 ACK 仅入队与非幂等不重发；定向 GREEN。
- [x] R02.2 RED：实际 adapter/worker 最小 fake driver 执行 32 FIFO/8192 ring 双向饱和、CLOSE/OPEN 后旧 generation 跳过、reverse overflow 带当前 ERROR(epoch) 并关闭对应 7777、迟到旧 error 不闭新 7777、桥 invalidation 恢复通知、最长 256 GIF chunks；补原 link/router 计数测试没有跑到的边界。对 connect/disconnect/write/not_connected 关联 error 保留 epoch，真实全局错误才 epoch=0，核对现 wire schema。不为 RF 或通用 RPC 另造系统；GREEN。
- [x] R02.3 RED：真实或最小 driver 模拟 A→B、A disconnect API 暂时失败/CLOSE 超时，保留真实 A 状态且 B 帧不向 A，自动重新尝试最新 B。先核对 R02.2 关联错误能否准确定位 7777；优先使用关闭受影响连接及 HA 重新发送当前 MAC，若现有调用边界更适合，则仅使用桥保存最新目标的有限重试，报告为何；不能两套竞争或无限立即重连。执行 adapter 断言与 HA peer 过滤回归。
- [x] R02.4 RED：7777 未断、7778 独立重连后收到可信 connecting/非当前 peer，当前 display 不发送；随后 matched connected 只同步最新赢家/OFF。修改现 STATUS observer 资格规则，不将 7778 掉线等同 SPP 物理断开，不变动语音 UUID、gate/owner。旧/重复快照不影响新连接；GREEN。R10 复用此 fixture 加真实慢显示+语音，不重复创造桥。
- [x] R02.5 全部上述 ESP 测试 + `tests/homeassistant/custom_components/tivoo/{test_transport,test_display_state}.py`；两 target build；报告与提交。真实配对、射频、UART 水位与 Bond 保持 GAP。

软件验收：[R02 修复验收](../reports/2026-11-19-p6-8-r02-repair-acceptance.md)，F02/F03/F04 对应软件问题已核销；本批专项 102 passed，双 target reconfigure/build/size exit 0；T02/T08 物理 GAP 保留。

## R03 — DMA 时轴、旧 PCM、可信 drain 与恢复

**F05 / B3-R01/R02/R04(12 槽)、B6-R01/R02；AFE-C04/05/12、VOICE-C07/09、T03-B/T06-B。**
**Files:** `esp32/firmware/main/{audio_capture,audio_output_manager,p68_prompt,s3_local_turn,audio_resource}.c` 与相关 headers；`tests/esp32/{p68_audio_host,p68_prompt_host,p68_lifecycle_host}.c`、`test_p68_audio.py,test_p68_prompt.py,test_p68_turn.py,test_p65b10_output.py,test_audio_rx_timeline.py`。仅 owner/状态接缝需要动其他文件。
**Interfaces:** tivoo_dma_eof_tracker_reset/observe、tivoo_audio_capture_start/close/next、tivoo_audio_output_dma_sent/output_reference_raw/output_prompt_drain/output_drained、现 generation/owner 与 s3_local_turn prompt mask；由实际 IDF driver 生命周期决定恢复入口，不在计划中猜 ISR API。

- [ ] R03.1 首先核对锁定 IDF i2s_common.c 的循环描述符、disable/enable/delete/reset 与回调可调用上下文；确认 RX/TX 共享时钟、DMA 槽安全写入及重建 epoch 时谁停/启、如何禁止旧 callback；记录最小方案及父子 owner 顺序。只处理已检测到的单漏/uncertain，不声称识别不可观测整圈丢失。
- [ ] R03.2 RED：模拟真实 12 槽非零 PCM，startup 学序单漏→发 gap/invalid→受控恢复后重新给出有效同轴 frame；正常 STOP 不重置 RX。运行时 TX 单跳槽→旧 PCM 不得跨 generation、reference/drain 不可被信任；不得只凭 s_completed/last_due 算安全结束。使用现 host tracker/queue，必要时引入小型 DMA seam 运行实际调度路由。
- [ ] R03.3 最小实现：检测 fault 后失效当前 reference、generation 及 drain，取消相关 turn；受控清理安全槽并重同步 RX/TX 共 epoch。禁止写 DMA 正在读的槽；正常 stop 保持常驻 RX；不能以重置计数或仅清 prompt_generation 伪报完成。恢复有界、失败保留明确安全隔离/不可用及原因；若只能人工重启且与规格恢复要求冲突，先确认合同变更。GREEN R03.2。
- [ ] R03.4 RED/GREEN：5s 后当前轮取消且不能 drain 时不得开 gate、不得无限静默占 owner；受控恢复后仅新轮能开始，无 canceled turn completed gate，真实故障保留显式 fault（F06 对外能力由 R04）；正常短提示音、普通 TTS 无间隙截断、stop/drain/下一 owner 回归。检查所有依赖 drain 的 owner release，不允许 prompt 与普通路径各有一套恢复。
- [ ] R03.5 运行上述 ESP 测试 + test_p6_audio_resource.py；S3 build，核对 12 槽/gap/fault 状态的实际测试，不将模拟当声学。报告 R04 所需真实时间轴/故障接口及未证实物理恢复，审查、提交。

## R04 — AFE 状态真实性与 VAD 跨 gate 隔离

**F06/F08 / B4-R03/R01；AFE-C06/10/12、VOICE-C04/05/09、T04-A/T06-B/T05-C。**
**Files:** `esp32/firmware/main/{s3_afe,p68_afe_flow,s3_main,diagnostics,s3_local_turn}.c` 与必要 headers；`tests/esp32/{p68_afe_host,p68_lifecycle_host}.c`、test_p68_afe.py/test_p68_turn.py/test_p68_prompt.py；HA test_diagnostics/test_transport（若现能力协商需改）。
**Interfaces:** tivoo_s3_afe_start/control/finish_prompt、feed/fetch vendor reset、flow 当前 gate/cursor、诊断 HELLO capabilities/ACK；R03 有效 epoch/fault。保留 B6 prompt_rearm/neutral。

- [ ] R04.1 RED：首次持续 capture invalid 无有效 feed、vendor reset_buffer/reset_vad 失败、正常恢复三类；断言可观察原因/计数、能力声明不假报、普通控制/下行独立。复用现任务/状态测试，以最小 vendor/capture stub 执行实际 runtime；不能只搜字符串。
- [ ] R04.2 实现 AFE 可用性区别任务创建/首有效 feed/运行 fatal/恢复；利用现诊断状态和协商边界，确需断线重握手须先核对协议约束，不发假 wake 或新增无限 supervisor。与 R03 分工：R04 不另造 DMA 恢复。GREEN R04.1。
- [ ] R04.3 RED：实际 flow 中 gate 内 speech、开放后 50×160 静音 PCM 仍 vendor speech 后 silence，START=0/END=0；gate 后真实即时开口必须 START、PCM 首样本与合法历史连续，迟到/跨块 gate fail-closed；独立 WakeNet 连续 DETECTED/VERIFIED 无 neutral 仍不二次 wake。先核对锁定 esp_afe_sr_iface/reset_vad 语义、cache 与样本边界，再选最小隔离/reset；常驻 AFE/WakeNet 不关闭，不硬等额外500ms。GREEN。
- [ ] R04.4 运行 test_p68_afe.py/test_p68_turn.py/test_p68_prompt.py/test_p68_audio.py、HA test_diagnostics.py/test_transport.py；S3 build；记录新 gate 状态语义供 R05/R09，真实三种 ready/followup/声学保持 GAP。报告、审查、提交。

## R05 — 有界校准 trace、真实提示音数字链

**F07/F13 / B3-R03/R04(跨 reference)、B4-R04、B6-R03/R04；AFE-C01–05/10/12、VOICE-C04/05/07–10、T03-A/B/T04-A/B/T06-A/B。**
**Files:** `esp32/firmware/main/{audio_capture,audio_output_manager,s3_afe,p68_afe_flow,s3_local_turn,p68_prompt,audio_resource}.c`，`generate_prompts.py`；既有 `tests/esp32/{p68_audio_host,p68_prompt_host,p68_lifecycle_host}.c`、test_p68_audio.py/test_p68_afe.py/test_p68_prompt.py/test_p68_turn.py；HA test_prompt_assets.py/test_p68_local_session.py；新增 trace 文件仅按已确认的有界格式归属命名。
**Interfaces:** capture frame raw_slots/raw_tx/tx_first_sample（生命周期至下次 capture_next）；reference_read，AFE enhanced/cache/VAD/索引；R03 可信时轴、R04 gate 语义、0x26 真实 adapter 发送。

- [ ] R05.1 定义并记录一次短时、有界、显式启用的 trace 格式/大小/导出途径（沿现有诊断或本地窄入口，正常模式无持续录音、无额外网络服务），同轴原始 L/R 与实际最终 TX、索引/epoch/gap，关联增强 PCM、cache 数据/长度、VAD 与 gate marker；先验证 pointer 生命周期/复制位置及开发机读取。RED 跨 80 sample reference 块的160样本、非整块偏移、缺半块/环覆盖、gap、索引连续；GREEN 真实 reference 与采集格式。实物后用互相关/marker 决定 delay/漂移/cache 重叠，不能提前拼 cache、不能采用旧47.5ms/0当实测。
- [ ] R05.2 RED：通过现 s3_local_turn/s3_afe/audio_resource 真实适配层小型 stub，驱动 15360–26627 非零 PCM、5120 queue 多次补写逐样本一致，signed offset/非整块 gate、poll 已晚、可信 drain 失败及回收后的新 owner、epoch/STOP，prompt 不发 ordinary AUDIO_STATE；从 adapter 获得正确 0x26，不手写事件代替。复用 R03/R04 fault/gate 实现，修测试揭示的必要 adapter 缺口，不做新 owner。GREEN；R09 再组合真实 HA。
- [ ] R05.3 现有 generate_prompts 源保护负例：临时副本追加1字节，生成拒绝且不使用过期 PCM；保持四 MP3 原 hash、确定性转换、缺失策略。该断言可能直接 GREEN，已有 probe 证明保护有效；不改源资产。
- [ ] R05.4 运行上述 ESP/HA 测试与 test_p6_audio_resource.py；S3 build，归档 trace 样例/读取说明及数字 PCM 证据。实际 HTTP/HTTPS/MP3/SRC、AUX、物理 offset 与校准、声学首尾仍 GAP，production gate 保持关闭；报告、审查、提交。

## R06 — HA STT 输入终态与 Sherpa 并发

**F09/F10/F15 / B5-R01/R02/R04；VOICE-C02/03/06/07、T05-A/B/C。**
**Files:** `homeassistant/custom_components/tivoo/{audio_session,assist_satellite}.py`；`tests/homeassistant/custom_components/tivoo/{test_p68_real_pipeline,test_p68_local_session,test_assist_satellite,test_audio_session}.py`；`services/sherpa_wyoming/{run,healthcheck}.py`（仅暴露失败才最小改）、`tests/services/sherpa_wyoming/{test_server,test_healthcheck}.py`。
**Interfaces:** AudioSessionManager.local_input_finished(session_id)、实际 audio iterator 正常 EOF/drain、AssistSatellite on_pipeline_event(STT_END/ERROR)、原 public run/cleanup；10400 原 Provider、10401 ASR-only 共享 provider/executor。

- [ ] R06.1 RED 真实 HA fixture：fake Wyoming 第一 audio-chunk 后直接 Transcript，无 speech_end；合法 speech_end 已入队但迭代器未 drain；unexpected VAD/取消/断连。断言不出现 INTENT_START、不执行本地命令/不增加 fake AstrBot 请求；正常 endpoint 全 PCM、一次 AudioStop 与合法 Intent 仍成立。用真实 public API，不造成真实设备动作。
- [ ] R06.2 核对当前安装 HA 2026.11.0 wyoming/stt.py、assist_pipeline/default_pipeline.py STT_END 回调和 public cancellation 边界；确认何处可同步阻断后续 Intent。仅收到 end 不是 drain，增加可校验正常 EOF 判据，禁止仅缩短 _arm(0) 或异步竞速。不 patch Core；若 public API 无合法实现路径，记录证据停本子任务、提交合同裁决，不臆造接口。GREEN R06.1。
- [ ] R06.3 RED：正常 EOF/AudioStop 后 peer 不回 Transcript，轮次自动释放；新轮不受旧 timer，正常慢结果不被误杀。根据现有合同/实际服务数据确认独立 STT finalize timeout、起点（正常 EOF 后等待结果）、取消条件（STT_END/ERROR/stop/换代/断线）；按 UUID/epoch 进入现 cleanup。不得用采集15s/播放固定短限替代。GREEN；记录阈值依据。
- [ ] R06.4 Sherpa test_server 双客户端并发 Transcribe、各自输入/输出匹配且各 decode 一次、任一 listener 启动失败时另一端清理、组合 health 一端失败即不通过。先核对实际 run finally/healthcheck，测试若已通过仅补证；不重复加载模型或改 10400 原用途。
- [ ] R06.5 运行上述 HA 四文件、Sherpa test_server/test_healthcheck 及服务全套；保存真实 Core 事件/帧日志供 R09 复用。无生产服务/设备部署，报告、审查、提交。

## R07 — 轮次身份、拒绝发送、超时与诊断

**F11/F12 / B5-R05/R06、B7-R01/R05；VOICE-C01/04/05/07、LIFE-C01/03/07/08、B0.5 §3.1、T05-C/T06-B/T07-A/C/D。**
**Files:** HA `audio_session.py,assist_satellite.py,transport.py,diagnostics.py`；S3 `p68_local_turn.c,s3_local_turn.c`；`tests/esp32/p68_turn_host.c,p68_lifecycle_host.c,test_p68_turn.py`；HA test_p68_local_session.py/test_p68_lifecycle.py/test_transport.py/test_diagnostics.py。
**Interfaces:** 0x26 ACTIVITY/gate、0x20 START、0x23 定向 stop、0x27 parent grant（原 UUID/epoch）；现 turn tick/send_event、on_local_start/_retire_local，R06 输入终态。

- [ ] R07.1 RED：非当前 UUID 非法 ACTIVITY、合法新帧、同轮冲突/完全相同重复 gate、旧 uptime/new UUID 边界；旧异常 inert、当前 payload 严格校验、完全相同重复 inert，不重复 START。按合同定义当前冲突重复处理；保持 B7 monotonic uptime，不改 wire schema。
- [ ] R07.2 RED：过期/无 grant 的 followup START，定向 _stop_sender 产生 HomeAssistantError 或 write/drain 挂起；后续合法诊断帧和 reconnect 正常、新 UUID 不受影响。复用有界 best-effort stop 与正常诊断 teardown；不 await 无界通知阻断 reader，不增加 ACK。明确 stop 失败与本地清理关系，GREEN R07.1/2。
- [ ] R07.3 RED：actual p68_local_turn host blocked=true、短阻塞后 START/PCM/end FIFO 恢复；过期且 START 从未发出则作废且无迟到开轮，已发 START 走匹配 ABORT；fake clock 使用原1s/3s/15s合同。最小修改 pump/event 发送边界，GREEN。
- [ ] R07.4 利用现日志/诊断增加 per-turn ready latency、peak pending、失败次数及分母、retirement duration、ready timeout 次数/比例；假钟断言一次轮次一次指标，迟到 timer/旧轮不重复计。不是新监控服务，不标实机 P95。
- [ ] R07.5 运行上述 ESP/HA 测试并 S3 build；更新 R09 fixture 所需 cleanup 及 UUID 断言，报告/审查/提交。

## R08 — 普通 TTS terminal 和真实资源 worker

**F14 / B7-R02/R03；LIFE-C02/04/06/07/08、VOICE-C07、T07-A/B/D。**
**Files:** `esp32/firmware/main/{audio_resource,audio_output_manager,diagnostics,s3_local_turn}.c`、必要 header；`tests/esp32/{test_p68_turn,test_p65b10_output,test_p6_audio_resource}.py`、p68_lifecycle_host.c 及最小新 worker harness（必要时）；HA test_p68_lifecycle.py/test_audio_resource.py/test_transport.py。
**Interfaces:** send_audio_state→diagnostics enqueue、matching session/playback/epoch terminal→on_playback；active/pending owner、retire_local/socket shutdown/drain/quarantine；R03 安全 drain、R05 prompt、R07 轮次取消。

- [ ] R08.1 RED：实际 audio_resource worker 的终态消息入队暂满+永久失败（原尝试250ms），模拟原7778仍健康；HA 不得永久等 terminal，失败不得发 grant 或伪报 completed。先评估现诊断连接失效/epoch teardown 是否可在发送失败处安全触发，能则优先使用；否则同连接保留 terminal 有界重送。二选一且关联当前连接，不能旧 epoch 关闭新连接、无限重发或用固定短播放时限截断正常长 TTS。GREEN。
- [ ] R08.2 最小 socket/output fake seam 执行真实 audio_resource.c 的 active/pending、旧 UUID retire、HTTP shutdown、drain 超时隔离、旧 stop/new play、matching terminal 一次及 late terminal inert；普通 0x23→实际 tivoo_s3_local_turn_stop→0x22 正常结束。旧测试的 bool prompt_ready/记录 retire stub 继续作为 turn 层断言，不能代替 worker 证据。
- [ ] R08.3 运行上述 ESP、HA 三文件、test_p68_prompt.py/test_p68_audio.py 回归；S3 build；确认 R05 prompt 与普通 TTS 的 AUDIO_STATE/owner 仍隔离。报告 terminal policy 与真实 fixture，为 R09 提供组合边界，审查、提交。

## R09 — 真实 HA 完整 Pipeline 与 owner 生命周期组合

**F16 / B5-R03、B7-R04；VOICE-C02、LIFE-C03/04/05/06/08、T05-A/C、T07-A/C/D。**
**Files:** `tests/homeassistant/custom_components/tivoo/{test_p68_real_pipeline,test_p68_lifecycle,test_p68_local_session,test_audio_resource}.py`、`tests/homeassistant/test_assist_pipeline_tts_cancellation.py`、`tests/homeassistant/custom_components/astrbot/{test_session,test_conversation}.py`；若测试暴露确凿组合缺陷仅改现 `assist_satellite/audio_session/audio_resource/tts_lifecycle/transport` 或 AstrBot 真实 owner 调用边界，不扩大范围。
**Interfaces:** 复用 R06 真实 HA public API + fake Wyoming STT；现 PipelineTtsOwner 与 fake TTS/真实取消 API、AstrBot fake SSE server、R05/07/08 的 gate/设备终态契约。避免 R05/R08 各造另一套 HA 测试环境。

- [ ] R09.1 真 HA local STT→Intent→TTS→资源 URL→匹配设备 terminal→正常完成；strict True 时一次0x27及新 followup UUID 消费；有效 no-TTS 与 TTS send failure 区别，不凭 playback_id=None 推断。测试实际 session/playback/epoch/Context/URL 及定向 stop，不把 end_stage=INTENT 当完整。
- [ ] R09.2 真实旧 PipelineTtsOwner 停止：fake Wyoming peer FIN/EOF、ResultStream/GET/取消等待与真实 AstrBot SSE stop_unconfirmed 路径；新轮不得越过 old public caller/retiring owner，未确认旧 session 不复用且显式新会话可恢复；disconnect/unload 等待 close 能收敛。保留 B7 模拟六阶段和连续3轮测试；只增加最小真实组合，不重写全部 mock。
- [ ] R09.3 复跑 R06 提前 Transcript/EOF、R07 旧 UUID/拒绝、R08 terminal failure；对应 fake peer 共享基础 fixture，保证异常不发外部 Intent、不错误 grant、不错误结束新轮。已有行为若直接 GREEN 记录，若实际失败先 RED 后最小修复并说明归属。
- [ ] R09.4 运行上述 HA 测试 + test_transport.py；检查完整事件、URL/播放终态绑定。物理 DAC/真实生产 TTS/AstrBot Stop 保留 GAP；报告所需 display 事件序列供 R10，审查、提交。

## R10 — 显示合同裁决与真实传输组合

**F17/F18 / B8-R01/R03；VIEW-C01–04、ESM-C09/C11/C19、T08-A/B/C。**
**Files:** 裁决后仅必要规格条款 `docs/superpowers/specs/2026-11-18-p6-8-b0-5-lifecycle-display-design.md` 与 ESM 矩阵/迁移索引，必要引用；HA `assist_satellite.py,display_state.py,transport.py,services.py,llm.py`；HA test_p68_display.py/test_display_state.py/test_transport.py/test_p68_real_pipeline.py/test_services.py（必要时既有 LLM 测试）。
**Interfaces:** coordinator 的当前 generation/5s TTL/known voice Context、thinking/speaking/tooluse 正常终态，R02 可信 SPP eligibility，R09 的真实 Pipeline/0x32。继续唯一 coordinator，不增公共 schema。

- [ ] R10.1 **产品决策门禁（未批准不得编写 F17 实现）：** 原 ESM-C09 优先级不动，B0.5 thinking 从 STT_END 到完成，mood active reply/5s/结束清除，两者使 SetMood 接受却始终不显示。优先建议真实 Intent 结束（不再思考）时退出 thinking，保持 tooluse/speaking 覆盖与 TTL，允许未过期 mood 在无高优状态的当前 generation 窗口可见；复核真事件及 no-TTS 窗口。若用户要求长 TTS 后也必须显示，则另明确 response-tail 所有权、TTL 起点、新 wake/followup/OFF/显式内容抢占，修合同后才实施，不用延长轮次/阻塞新轮，不能自行提高 mood priority。若明确取消显示承诺亦须合同裁决。记录用户批准方案并最小更新冲突条款与测试期望；未确认时该子任务 GAP，可按独立授权做 R10.3，但不能宣称 R10/F17 完成。
- [ ] R10.2 RED 真生命周期 SetMood 被接受后 winner/adapter 输出按获批时机实际可见；普通 TTS、无TTS、续聊授权、取消/新 Context、TTL、OFF、显式内容；已知旧 Context 拒绝、无 context 只按现 active reply，不猜 AstrBot 关联字段。最小实现获批状态变化；不改屏幕 power gate 或优先级；GREEN。不能以人工 begin_generation(no thinking) 单元测试替代完整事件。
- [ ] R10.3 复用 R02 fake TCP socket＋R09 当前语音轮：真实 DEVICE_STATUS/DEVICE_EVENT→7777 writer→coordinator；人为阻塞 SPP 写时 gate/start/PCM/end/0x32 仍消费，旧 UUID/非 tts_http/错 playback ID 不改赢家；7778 连接恢复及 connecting/non-target→matched connected 期间不发、恢复重申 OFF/最新赢家，慢写解除后不回放过期队列。保护当前 I/O 不可撤销的原边界，last_sent 不是实际像素；不重做 RF/peer recovery。
- [ ] R10.4 运行上述 HA 测试 + test_p68_lifecycle.py/test_p68_local_session.py；核对 T08 原优先级/idle/多 owner/临时唤醒/OFF/reload 不退化，真实物理显示仍 GAP；报告/审查/提交。

## R11 — 全量软件复验与闭环核查（不替代 B9/B10）

**Consumes:** R01–R10 报告；**Produces:** 修复核销矩阵、完整软件回归证据、两 target 可复现产物、实际剩余 GAP 清单。仅文档/证据核销，不借机实现别的功能或顺手改代码。
**Files:** 本计划勾选、`docs/superpowers/reports/YYYY-MM-DD-p6-8-r11-repair-acceptance.md`；原计划追加状态引用而不覆盖历史 PASS；必要修复应回对应 R 批重新红绿与提交。

- [ ] R11.1 检查每个 F 项的实际 diff/测试断言/验收报告；34/34 原 R 编号追踪，包括 B4-R02 和 B5-R05 uptime 已修部分（复查保留保护）、B6-R04 已证实的源保护、静态 vs 实际复现区分。核验 F17 批准裁决存在；未决不算通过。
- [ ] R11.2 运行 `bash scripts/test-ha.sh tests/esp32 tests/homeassistant -q -p no:cacheprovider`（若 HA 与 ESP 需按原环境分开，报告两完整命令与结果）；`bash scripts/test-sherpa-wyoming.sh -q`；失败/teardown/波动如实分类，定位后重测，不只报告独立成功用例。
- [ ] R11.3 两 target clean build（只清独立生成 build 目录，绝不清工作区/凭据/NVS），限并发，核对依赖锁、实际有效配置、Wi-Fi+SR、flash_args/partition/model/manifest 与 SHA/size。R01 的非生产测试配置不冒充实际生产配置；软件产物不刷写。
- [ ] R11.4 按原 T01–T08 各受影响测试组记录当前软件 PASS/GAP/FAIL、对应 F/R evidence 及保留 physical/deploy GAP；另写修复报告并引用原报告，不改写原报告历史事实。确认工作区仅授权变更、每批提交完成，无 NAS/部署/刷写。若尚有缺口，列出对应批次与原因、回相应批次；不能因为全量通过就自动核销无证据合同。
- [ ] R11.5 总报告并本地提交。R11 不标 P6.8 总完成，不执行 B9/T09 或 B10/T10；硬件到齐且用户授权后按原计划必要 gate 及实际配置/服务/声学验收，之后才允许 B9 条件清理，最后 B10 逐行核销49新合同、192历史ID、19遗留项。

## F 项与源审查完整追踪（主责唯一）

| F | 原审查编号 | 主责批次 | 关联复验 |
|---|---|---|---|
| F01 | B1-R01/R02/R03/R04 | R01 | R11 |
| F02 | B2-R01 | R02 | R11 |
| F03 | B2-R02、B8-R02 | R02 | R10 |
| F04 | B2-R03/R04 | R02 | R10/R11 |
| F05 | B3-R01/R02/R04(12槽)、B6-R01/R02 | R03 | R04/R05/R08 |
| F06 | B4-R03 | R04 | R09 |
| F07 | B3-R03/R04(跨块)、B4-R04 | R05 | R11、实物校准 |
| F08 | B4-R01 | R04 | R05/R09 |
| F09 | B5-R01 | R06 | R09 |
| F10 | B5-R02 | R06 | R09 |
| F11 | B5-R05(余项)、B7-R01 | R07 | R09 |
| F12 | B5-R06、B7-R05 | R07 | R09 |
| F13 | B6-R03/R04 | R05 | R08/R09 |
| F14 | B7-R02/R03 | R08 | R09 |
| F15 | B5-R04 | R06 | R11 |
| F16 | B5-R03、B7-R04 | R09 | R10 |
| F17 | B8-R01 | R10 | R11 |
| F18 | B8-R03 | R10 | R11 |
| 已关闭 | B4-R02（B6 prompt_rearm + neutral）；B5-R05 的 uptime 子项（B7） | 不再实施 | R04/R07/R11 保留回归 |

覆盖：B1 4、B2 4、B3 4、B4 4、B5 6、B6 4、B7 5、B8 3，共34个唯一源编号；F05/F07 共用 B3-R04 的两个子项，不重复执行。所有 F01–F18 仅一个主责 R 批，关联复验不是再次实现。B2-R01、B4-R01、B5-R01、B8-R01 是已有软件复现；B4-R02 为历史复现且已修；其他静态故障和证据缺口不提升为真实硬件失败。

## 保留的门禁

T01–T08 原物理与部署缺口：实物板/接线/电源/USB/PSRAM/NVS/Bond、AP/HELLO、921600 UART/SPP 实际吞吐、双麦/DAC/AUX/HTTP/HTTPS/MP3/SRC、同步校准/声学模型与最终词/误漏/电视与双讲、生产 HA pipeline/10401、真正 TTS/AstrBot Stop、3s/4s/端点/连续打断、实际像素/OFF/ON、两板独立 reset/HA reload 及全量性能稳定性。F07 是软件采集准备而非已校准；不承诺电视同词必可区分，不强叠 NSNet/BSS。不能因为 R 批全绿就标硬件 PASS。

原 B9 明确要求 B4–B8 真正必要 gate 达成才能对 legacy 路径实施清理；仅可另获授权先做只读消费者盘点/部署说明准备，保留 10400/KWS/四 MP3/旧客户端兼容直到证实无依赖。P9 主动任务/公开 owner 扩展不引入。原 B10 综合现场验收、历史 GAP 保留，另获授权执行。

## 本文状态

R01–R02 已完成软件修复验收；R03–R11 未实施/未勾选；18项归并、11个批次拆分、命名和建议顺序为计划者决定，不代表 F17 已获合同裁决。计划编制不需要再次复现原全部审查，也不改变已有软件 PASS 的历史事实；当前软件仍待修复复验。
