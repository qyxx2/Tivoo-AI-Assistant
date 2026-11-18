# P6.8 b1–b10 分批实施与验收计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. 一次只执行用户授权批次，先红后绿，独立报告/本地提交；不得自行推进下一批。

**Goal:** 按冻结合同实现 S3 本地唤醒双麦语音终端与经典 ESP32 SPP 桥，并重新验收所有受影响的历史要求。
**Architecture:** S3 独占 Wi-Fi、音频和 AFE，经典板独占 Classic SPP；HA 保留公开 Satellite API、原对话/TTS、唯一显示仲裁。
**Tech Stack:** IDF v6.1、SR 2.6.1、codec 2.6.2、effects 1.4.5、HA 2026.11.0、Wyoming 1.10.2。
**Spec:** [总体路线](2026-11-18-p6-8-s3-local-wake-roadmap.md)、[硬件](../specs/2026-11-18-p6-8-b0-2-hardware-uart-spp-design.md)、[AFE](../specs/2026-11-18-p6-8-b0-3-audio-afe-design.md)、[语音](../specs/2026-11-18-p6-8-b0-4-ha-stt-prompt-design.md)、[生命周期](../specs/2026-11-18-p6-8-b0-5-lifecycle-display-design.md)、[历史逐 ID](../specs/2026-11-18-p6-8-legacy-contract-migration-index.md)、[交叉审计](../reports/2026-11-18-p6-8-b0-6-cross-audit.md)。

## Global Constraints

- 规格确定的 wire ID/方向、GPIO、采样格式、版本、所有权优先于旧实现；不另创公开 HA/MCP schema，不修改 HA Core。源代码路径为当前已有文件，新增文件仅计划归属，不假定已经存在。
- 32kHz I2S 双 32-bit slot；AFE MMNR 16k mono 增强；PCM 每20ms 640B，前导0.5s，待 ready 上限1s；首次 gate 后3s、续聊4s、命令15s，设备时钟权威。短 prompt gate 与普通 TTS 分离。
- 开发机先跑 host/HA/服务测试、分别构建；NAS 只按必要实机授权部署；新板未到货则物理 gate GAP，不得假装完成。不擦旧 NVS、不推动 main/远端、不提前切换生产。
- 每个测试组先添加明确断言并运行见 RED，最小实现后 GREEN；未变化的原测试直接回归，旧 topology 测试在 b9 前保留，不能为绿删掉有效断言。测试组是计划中的唯一证据 ID，可有多个测试；各批报告写具体 test node、命令、退出码、commit/hash、固件/HA 版本，实机记录原始数据、样本、缺测原因；T10 逐行关联 192+19 历史项及 49 个新合同。设计阶段无生产 PASS。
- 运行入口（真实已有脚本）：在 repo root 使用 `bash scripts/test-ha.sh tests/esp32 ...` 或 `bash scripts/test-ha.sh tests/homeassistant`；Sherpa 用 `bash scripts/test-sherpa-wyoming.sh`；禁止以一个混合 Python 环境掩盖依赖差异。各下列测试文件名为已有回归入口，新增断言放同域测试或专用文件。IDF 使用锁定 v6.1 环境，在各独立 project 内 `idf.py set-target esp32s3` / `idf.py set-target esp32`（仅初始化各自 build/config），`idf.py build`，核对生成 flash_args/model/size，再用实际识别串口独立烧录；不能手抄旧偏移。

## Review Focus

1. 新 START 抢旧 caller 的 finally/迟到 PCM/TTS — T05-C/T07-A/B/C。
2. speech_end 已到、消费者还未读尽，或同包新 start — T05-C/T06-B。
3. UART 两向都满且 ACK 丢、桥重启/切 MAC — T02-A/B/C。
4. 普通长 TTS 间隙、自身含唤醒词、听完提示立刻说 — T03-B/T04-B/T06-B/T07-A。
5. follow-up 真假授权、失败/迟到 beep、关屏重连与旧 mood — T07-D/T08-B/C。

## b1 — 独立构建与硬件

**Consumes:** HB01–04、AFE-C06/C08（smoke）。**Produces:** 两独立 target/flash manifest、GPIO/电源实物记录、S3 model partition。
**Files:** `esp32/firmware/{CMakeLists.txt,sdkconfig.defaults,partitions.csv,dependencies.lock,main/}`；新 `esp32/bridge_firmware/` 对应配置与 main；`tests/esp32/test_p5_hardware_memory.py`；复用 `esp32/tests/p5b0_compatibility/` 的编译验证逻辑。
- [x] T01-A（软件 PASS，见 [b1 报告](../reports/2026-11-18-p6-8-b1-build-acceptance.md)）：先断言独立 target、组件图不交叉、16MiB 区间无重叠/不越界、S3 8MiB app/4MiB model、classic NVS 不迁移/擦除、S3 无 Classic；运行 host test，随后分目标配置/构建并复验。S3 暂用 wn9_hilexin smoke，非用户最终词；实际 lock、map、size、生成 flash_args、srmodels.bin 均归档。S3 网络/诊断 scaffold 不声称 b2 SPP 已通。
- [ ] T01-B（GAP：S3/第二颗 INMP441 未到货，用户禁止刷写生产经典板）：对照 b0.2 丝印/通断/电源/USB/芯片 flash ID；在两个真实端口独立刷写并启动，记录完整/分段产物哈希、boot log、heap、NVS/Bond 保全、板载 RGB 关闭。无实物只能报告软件部分通过，不能过物理 gate。现经典板仍是生产单板，刷桥将使旧语音不可用；b1 真实刷写只在明确授权的隔离/维护窗口并备有旧完整 app/manifest 回退，完成测试后如尚未切换拓扑就恢复旧产物并核验，不把 b1 当正式接管生产。
- [ ] 验证：上述 host 文件、两个 build exit 0 及软件报告/本地提交已完成；T01-B 实物门禁未通过，物理接线安全/独立启动通过后才 b2 真机。

## b2 — 7777/UART/SPP 桥

**Consumes:** T01 两目标。**Produces:** HB05–15 的私有 UART frame、真实 status、原 7777 raw 双向、独立 7778；无 voice 业务。
**Files:** S3 `esp32/firmware/main/{control_bridge,network_listeners,device_status,diagnostics}.c`；桥复用 `tivoo_spp*,bt_security_policy,tivoo_frame_stream`；两目标各 UART transport adapter；HA `homeassistant/custom_components/tivoo/{protocol,transport,diagnostics}.py`。
- [x] T02-A（软件 PASS；双板实机 GAP）：C host golden（COBS、CRC32、字段 endian、4608 payload、任意切片、坏 CRC/长度/seq/旧 token）；双向 stop-and-wait 一未确认、control priority、ACK 仅入队。先失败后实现 UART1 见 HB05/06，1s heartbeat/3s invalidation/20s ACK 限，不重传非幂等。
- [x] T02-B（软件 PASS；双板实机 GAP）：测试 raw 7B、最大帧、拆/粘包、0x69 payload、reverse bytes 与 hint、32项队列满、8192B reverse 溢出、双向拥塞/ACK timeout、client epoch、切 MAC、旧 status、独立端口/重启；按 HB07/10–13 迁移 parser、状态和错误。命令级不发 ACK；真实 MAC 匹配才触发重连同步。
- [ ] T02-C（软件回归 PASS；实际 SPP/GIF/Bond 等硬件验收 GAP）：保留 Classic auth/Bond/SDP fallback、330B/15ms、WRITE_EVT、MCP 全部注册/权限/参数/错误和服务；正常/断线/显式 disconnect/改 MAC/最多256 GIF chunks/长滚动实机验证，后续音频并发留 b3/b10。禁止擅自清 Bond 或切别人设备。
- [x] 软件验证（416 passed；两 target build exit 0）：`bash scripts/test-ha.sh tests/esp32/test_p5b3_control_bridge.py tests/esp32/test_p5b3_security.py tests/esp32/test_p5b3_session.py tests/esp32/test_p6_reverse_channel.py tests/esp32/test_p6_device_status.py tests/homeassistant/custom_components/tivoo`，再两 target build；报告/提交。 见 [b2 报告](../reports/2026-11-18-p6-8-b2-uart-spp-acceptance.md)。实机 GAP 不核销。

## b3 — 音频物理通路与真实参考

**Consumes:** T01 pin/target；T02 独立传输。**Produces:** AFE-C01–05/C12 的同步双麦 sample index、真实 TX/RX、32k mono output；原普通下行基础。
**Files:** `esp32/firmware/main/{audio_capture,audio_playback,audio_output_manager,audio_resource}.c`，现对应 headers；`tests/esp32/{test_audio_rx_timeline,test_p65b8_audio,test_p65b10_output,test_p6_audio_resource}.py`。
- [ ] T03-A：标记双声道 32-bit 高24位、有符号/饱和/滤波、相位、32→16k 31-tap、不同块长一致，RX/TX 共 BCLK/WS；独立敲击/示波验证 L/R、上电128ms 丢弃。先实现双通道采集和标记，不把单麦平均假称 BSS。
- [ ] T03-B：实际 TX（含零填/stop/音量）与 RX 样本轴同源，60ms DMA/160ms reference 初值；模拟 EOF gap、丢帧只计一次、长间隙继续、尾部 drain、取消、HTTPS/HTTP 格式/URL 无回归；真实 AUX 波形/双向并发，宽带脉冲相关重测参考位置/声学延迟，不照抄47.5ms。报告水位/内部 heap，b4 再测 AFE。
- [ ] 验证：上述4 test 文件及 IDF S3 build；实物无声学数据时保留 GAP；报告/提交。

## b4 — 双麦 AFE、本地 WakeNet

**Consumes:** T03 sample timeline；T01 model。**Produces:** AFE-C06–12，confirmed wake、VAD start/end 和按索引 cache。
**Files:** `esp32/firmware/main/audio_frontend.{c,h}`、audio_capture、sdkconfig/model build；新增 AFE host 流程测试并复用 T03 标记。
- [ ] T04-A：锁定实际模型/有效配置/动态 chunk，MMNR/FD HIGH_PERF、BSS 优先、无强开 NS、VADNet1 medium，真实 feed/fetch；测试重复 candidate/verified、丢帧、重触发、短 gate、VAD history/cache 重叠去重、500ms endpoint；输出单次确认及16k增强流，不接 NAS KWS。b4 前用户选最终官方词；未选时仅 smoke，不宣称最终声学通过。
- [ ] T04-B：5cm 初值，1m/3m/实际位置，多条件真人、电视普通/同词、正常TTS含/不含词、双讲及长播放，记录每组 count/误漏/延迟P50/P95/ERLE/负载和 drop；NSNet2/3 不自动叠加；若失败按 AFE 规格复测布局/阈值/模型。S3 网络/TTS/UART并发无新增欠载、AFE gap、watchdog。
- [ ] 验证：T04 host 与 T03 回归、build、实际模型 list/print_pipeline/内存/声学记录；报告/提交。

## b5 — HA STT 入口与有界会话

**Consumes:** 本地 confirmed wake/16k stream、TVIO v1；**Produces:** VOICE-C01–07 最小端到端、LIFE-C01/C04 的 UUID 字段与正常 owner 基础。
**Files:** `services/sherpa_wyoming/{run,config,healthcheck}.py` 及 compose 实际配置；HA `homeassistant/custom_components/tivoo/{assist_satellite,audio_session,diagnostics,transport,audio_resource}.py`、标准 pipeline select 平台接入；S3 diagnostics/audio capture；对应现 test_server/stt/runtime/config、test_assist_satellite/audio_session/diagnostics/transport/audio_resource。
- [ ] T05-A：实际 HA public Satellite API、专用 pipeline 和原 conversation/context，本地优先/模拟 AstrBot、手动新会话、P3 ChatLog/SSE 原断言、intercept/ask_question 例外；legacy 走旧 pipeline，local 模式错配拒绝，不能 preferred 回退。测试同名/失效 select、Provider 错配均 fail closed。
- [ ] T05-B：先使用真实 HA+fake Wyoming 整个 STT pipeline，确认 STT_START≠ready、pull 前已 Transcribe/AudioStart、尾 PCM 逐字节一致、自然 EOF/一次 AudioStop/一次 decode、无 HA VAD 截断；再用共享模型/executor 增 ASR-only listener requires_external_vad=false，原10400 true、旧三 Provider 继续；核验实际端口/健康/其他消费者/资源不重复加载、非法请求拒绝。若公开 API 可行性失败先回规格，不继续部署。
- [ ] T05-C：双端 0x20/21/22/23/24/25/26 codec/方向/能力（ACK 回显）、UUID/epoch、0x30/31/32 基础绑定；模拟 gate 先/ready 先、早 speech_end、tail+end+新start同包、错计数/overflow/timeout/取消 EOF；start gate 后且 ready 后、有界1s、3s假钟、15s命令，尾部完整才 EOF。正常 TTS 基础输出，使用测试 gate，不宣称 b6 提示音已交付；主动打断/续聊归 b7。
- [ ] 验证：`bash scripts/test-ha.sh tests/homeassistant` 及 `bash scripts/test-sherpa-wyoming.sh`，S3 build、真实 HA fake endpoint 证据与需要的只读本地 intent；报告/提交。

## b6 — 本地提示音与 endpoint

**Consumes:** T03 physical output/T04 samples/T05 ingress；**Produces:** VOICE-C05–10，实际 gate/提示音资产、正常 STT end。
**Files:** `homeassistant/prompt_assets/`（保留源）、S3 app build 资产生成及 audio_output_manager/audio_frontend/audio_capture、HA 既有 prompt_audio/audio_session/assist_satellite 测试。
- [ ] T06-A：校验 b0.4 四源 SHA、确定性 FFmpeg 32k mono s16le、输出总179160B、app image 余量、ready 相邻不重复、beep 独立、缺失不跨池/不请求 HTTP；构建 Flash 只读短 PCM。记录实际 hash/版本。
- [ ] T06-B：先用 fake clock/sample marker 测 gate、尾帧 padding、短 prompt 不发 ordinary AUDIO_STATE、普通 TTS 不屏蔽 wake、缺资产确认无声、无法确认 drain 5s watchdog fail；真实测试提示音首声/尾巴、听完立刻说、短命令、500ms endpoint、尾部传输/AudioStop，3s 起始窗口（4s 由 b7 授权）。不把自播负样本数字日志当声学。
- [ ] 验证：HA prompt/audio_session/assist_satellite 测试、T03/T04/T05 回归和 S3 build；报告/提交。

## b7 — 打断、续聊、所有权

**Consumes:** T05 UUID/EOF/T06 gate/短 PCM；**Produces:** LIFE-C01–08 完整、0x27、真实普通播放终态。
**Files:** HA `assist_satellite.py,audio_session.py,audio_resource.py,tts_lifecycle.py,transport.py,diagnostics.py`，AstrBot `conversation.py,api.py`；S3 `audio_resource.c,audio_output_manager.c,diagnostics.c,audio_frontend.c`；对应 tests。
- [ ] T07-A：用 fake owner/clock 先测未ready/STT/intent/合成/播放/等待续聊重新 wake、连续3次、旧 caller finally、FIFO旧 PCM、断线/reload、慢 cleanup 超限；本地同步失效旧输出，旧清理只捕获其资源，HA reader 不阻塞，串行 public caller，最后一轮独占。普通 VAD 无权，短 gate 例外。
- [ ] T07-B：按 epoch+UUID+playback 验证迟到/重复0x30/31/32、无 ID stop、停止旧 DMA 后才能新 prompt、普通 TTS 持续长间隙/真实终态，正常回复无截断；实际 stop 延迟分离数字/物理。
- [ ] T07-C：P3 SSE accepted/not accepted/end/partial、session stop once、失败/timeout 不复用旧 session、保留新对话入口；真实 HA owner ResultStream/cache token、Wyoming FIN/EOF、FFmpeg/GET 取消与对照正常完成；5/15/5/10s 各 watchdog 无永久 barrier。先失败后最小扩展失败传播。
- [ ] T07-D：严格 true+有效 Intent+正常 run+真实 completed 双顺序或已证实无 TTS；false/缺失/error/stop/intercept/发送失败无授权；0x27 单次 parent→新 UUID，beep 后实际 gate 4s，5s grant handoff，重复/旧 grant/新 wake/无命令/早 ready，首次仍3s。不能以 playback_id None 推断无 TTS；正常无授权发匹配 0x23、设备匹配 0x22 后回 idle，迟到 END 不影响新轮。
- [ ] 验证：`bash scripts/test-ha.sh tests/homeassistant tests/esp32` 及 Sherpa suite，S3 build；真实服务/设备定向打断证据；报告/提交。

## b8 — 表情事件来源

**Consumes:** T02 可信 SPP status、T07 generation/Context/gate。**Produces:** VIEW-C01–04，不另起仲裁。
**Files:** HA `display_state.py,assist_satellite.py,transport.py,services.py,llm.py`，对应 display/assist/transport/services/llm 测试。
- [ ] T08-A：idle 30–90s、wake100%、真实 start/end、有效 STT_END 才 thinking、空/失败/旧轮退出；优先级/显式恢复、无待机候选显示；原 fake-clock 断言先加 RED 再迁移。
- [ ] T08-B：同 Context/satellite/UUID/playback 绑定 tooluse/speaking/followup gate，迟到 terminal/TTL/旧 cancellation、prompt 不 speaking、atomic transition，旧 generation 不回写。
- [ ] T08-C：原 schema、mood 白名单/5s/known context/无 context 边界，显式内容、多 inhibit/temporary wake、OFF 唤醒/打断/重连、stale 7777、HA reload 初始同步（不声称 RAM gate 持久）。慢 SPP 不阻塞 RX；真实画面 OFF/ON/赢家。
- [ ] 验证：`bash scripts/test-ha.sh tests/homeassistant/custom_components/tivoo`，T02/T07 回归；报告/提交。

## b9 — 条件清理和部署说明

**Consumes:** b4–b8 真实本地模式已通过必要 gate（特别确认正/负样本、语音链、打断与显示）；**Produces:** Tivoo 单一本地唤醒，非 Tivoo 服务兼容。
**Files:** 原 legacy candidate/watch_wake_word/remote prompt 路径和对应旧固件配置/测试、HA/Sherpa 配置及 README/部署说明。
- [ ] T09：先测试 local 模式无旧候选上传/WAKE_WORD run/side watcher/3或15s rearm/远程 prompt URL、旧固件明确不兼容、STT/TTS/普通 URL/音频取消仍正常；按 b0.4 能力隔离切换，删除确认无消费者的 Tivoo 专属代码/资产路径；保留四源 MP3 构建输入。盘点实际 HA pipelines、Wyoming entries、其它客户端配置与消费证据；未证实无依赖则保留10400/KWS模型/健康契约并记录，不删全局服务。若有依赖不改消费者；旧 tests 中仍有通用语义的移植，新无用路径断言替换为负样本，历史报告不删。
- [ ] 验证：HA 与 Sherpa suite、两 build、目标模式抓包/配置核对，README/回退路径和证据；报告/提交。不得为清理提前变更在线服务。

## b10 — 实机综合与全量核销

**Consumes:** b1–b9 所有软件与实际依赖 gate。**Produces:** T10 每合同 PASS/GAP/FAIL + 证据定位；不自动关闭历史 GAP。
- [ ] 自动化：`bash scripts/test-ha.sh tests/esp32 tests/homeassistant`，`bash scripts/test-sherpa-wyoming.sh`，两个 target clean build（只清各 build 产物、非工作区/NVS）；记录测试数量/失败、flash manifest/版本/部署目标。
- [ ] 综合实机：对照 T01–T09 各行，复查双麦接线/独立 USB、电源、真实 SPP/断电 Bond/切换重连/长 GIF、HA 本地/LLM、TTS长段/间隙、端点、真实人声、电视、自播负样本、三次打断、3s/4s、屏幕/mood、AP/7777/7778各失联、任一板重启/HA reload、生产 HTTPS；保留原适用断言。各阶段原报告未运行项按 H01–H19 处理，不自动执行第二台/JTAG/key 轮换等延后专项。
- [ ] 延迟：固定说话距离、词、声源音量和命令；记录外部录音与独立设备/HA 单调时间轴，不减异机 uptime。报告词尾→WakeNet确认、词尾→真实提示首声、实际命令人声尾→STT_END（另记 VAD speech_end→STT_END）、实际命令结束→HA实际执行/回答首声、wake确认→旧声停止（目标见路线：300ms/1.2s/1.5s/100ms；非保证）；LLM、TTS 独立分解。每组记录 count/P50/P95、失败样本、旧基线缺测；未达目标列 GAP/FAIL 并定位，不能以日志代替物理结果。
- [ ] 压力：长回复/连续电视与常驻监听/控制 GIF 同时，记录时长/次数、两核 CPU、IRAM/DRAM/PSRAM 最低和 contiguous/DMA、stack、AFE feed/fetch、UART/队列水位、CRC/drop/underrun、watchdog、长期资源变化；统计正负样本，不承诺电视同词可区分。
- [ ] 逐项填写新合同49行和迁移索引192+19行：适用原断言+新证据+对应 test node/report path；未测/失败不标 PASS；独立延后明确理由。只有实际合格才宣布 P6.8 完成。报告、本地提交；用户另授权才集成/推送。
