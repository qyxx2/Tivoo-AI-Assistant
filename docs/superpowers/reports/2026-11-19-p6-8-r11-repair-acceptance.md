# P6.8 R11 软件总复验与审查核销

日期：2026-11-19。分支：feature/p6-8-s3-local-wake。被验收生产/测试代码提交：31eb764bfc385588a6fbfb345eb29ab0c4cfb60b（R10）。依据 [R01–R11 修复计划](../plans/2026-11-19-p6-8-review-repair-execution-plan.md) 及 [原 B1–B10 计划](../plans/2026-11-18-p6-8-b1-b10-execution-plan.md)。

**结论：R11 软件专项 PASS；18 个 F 软件修复/补证及 34 个来源审查编号完成追踪；完整独立套件 850 passed；两 target 独立 clean build 和产物复核 PASS。** 不等于 P6.8 总完成，不等于硬件/生产验收通过。只修改本批文档，生产源码、测试、依赖锁、工作区凭据与旧配置保持不变。

按 Superpowers executing-plans、receiving-code-review、verification-before-completion 执行；沿用户指定已有工作区及现分支，无新 worktree；本批无新产品缺陷需 TDD 修改。无独立 reviewer，由执行者对实际 diff/源码/断言进行总复核，不冒充独立复审。

历次原始修复证据（保留历史结果）：
[R01](2026-11-19-p6-8-r01-repair-acceptance.md)、[R02](2026-11-19-p6-8-r02-repair-acceptance.md)、[R03](2026-11-19-p6-8-r03-repair-acceptance.md)、[R04](2026-11-19-p6-8-r04-repair-acceptance.md)、[R05](2026-11-19-p6-8-r05-repair-acceptance.md)、[R06](2026-11-19-p6-8-r06-repair-acceptance.md)、[R07](2026-11-19-p6-8-r07-repair-acceptance.md)、[R08](2026-11-19-p6-8-r08-repair-acceptance.md)、[R09](2026-11-19-p6-8-r09-repair-acceptance.md)、[R10](2026-11-19-p6-8-r10-repair-acceptance.md)。

## R11.1 — 原审查核销矩阵

逐项对照八份 `.superpowers/p68-b*/review.md`、R01–R10 各提交的实际生产/测试 diff（完整累计 diff 保存为 `.superpowers/p68-r11/r01-r10.diff`）、当前源文件及断言与 [修复计划](../plans/2026-11-19-p6-8-review-repair-execution-plan.md) 的 F/R 映射。以下 PASS 仅指审查中的软件修复或软件证据子项，不是整个合同/实物 PASS。每行的提交是对应独立本地提交，详细 RED/GREEN 和原合同编号见同编号报告（链接见修复计划）。

| F / 原审查编号（34 个唯一编号） | R 批 / 提交 | 复核的实现和有效断言 |
|---|---|---|
| F01 / B1-R01/R02/R03/R04 | R01 a5dd5c3 | 两 CMake target / active entry、真实 NVS/board_boot、Classic RGB；test_active_targets_boot_and_memory、test_effective_target_configs_after_configure 保留旧断言并分离生成配置；独立 ELF/config/manifest 的证据由 R11.3 重建。 |
| F02 / B2-R01 | R02 3b5893c | network_listeners 在 staging 前 MSG_PEEK，test_p68_closed_client_discards_uncommitted_staging(fin/rst) 校验首帧延迟 ACK 后无第二 FRAME、保持诊断连接；已提交帧不撤销。 |
| F03 / B2-R02、B8-R02 | R02 3b5893c、R10 31eb764 | SPP generation→request error epoch、code3 关闭对应 7777 由 HA 重发目标；test_real_uart_worker_request_error、test_p68_spp_status_reconnect_revokes_display_eligibility 校验旧 A 保持/不写错 peer、新 B 重选、连接资格及 ON/OFF；R10 真实慢 writer 组合再覆盖。 |
| F04 / B2-R03/R04 | R02 3b5893c | uart_transport、adapter_host 运行实际 FIFO/8192 ring、ACK、错误 code/epoch、generation invalidation、256 GIF chunk 和 reverse bytes；test_real_uart_adapter_worker 与旧 codec/session/security 保留。ACK 不等于物理 SPP 执行。 |
| F05 / B3-R01/R02/R04(12槽)、B6-R01/R02 | R03 504c056 | audio_capture/manager 共时轴故障失效/受控重建，真实 host 12 槽 PCM、旧 gen 不 drain/release、有效新帧、重复失败隔离；test_dma_runtime_recovery、test_local_lifecycle_adapter 的 watchdog、cancel/no gate、正常 STOP 不重建 RX。不可观测整圈丢失和硬件 IRQ 不声称检测/验证。 |
| F06 / B4-R03 | R04 eefa2c7 | s3_afe 实际 feed/fetch stub：无有效输入不报能力、reset fail/recover；test_afe_runtime_availability、test_p68_capability_rehandshake_preserves_nonvoice_channels 与 HA test_p68_afe_capability_reconnect_retires_old_turn_only 核对协商/旧轮隔离、7777 保持。 |
| F07 / B3-R03/R04(跨块)、B4-R04 | R05 35925c2 | p68_trace 默认关闭且有限 PSRAM 采集，test_trace_copies_bounded_indexed_records / test_enabled_trace_task_exports_once_and_stops 核对实际 L/R/TX/AFE/cache/索引、gap/溢出/导出；test_stereo_timeline_reference_and_output 查 160 非对齐读取/缺块。校准准备已交付，真实 cache 对齐/声学仍 GAP。 |
| F08 / B4-R01 | R04 eefa2c7 | p68_afe_flow / s3_afe gate 重置 VAD，test_local_afe_flow、test_afe_runtime_availability 校验 50 残留静音不产 START/END，即刻人声/跨块合法首声连续，reset 调用顺序；真实 vendor 声学留 GAP。 |
| F09 / B5-R01 | R06 70dd4dd | AudioSessionManager 自然 EOF/真实 tail 后 local_input_drained；public STT_END 同步抛 SpeechToTextError，test_public_satellite_stt_device_endpoint_preserves_tail early/queued_end/vad_start/vad_end/cancel/disconnect 不入 Intent、不发假 AudioStop；正常流逐字节保留。 |
| F10 / B5-R02 | R06 70dd4dd | 同一 public fixture silent/slow/superseded/provider_error：真正 EOF 后独立 45s finalize，超时退休，旧 timer 不影响新轮；正常有结果不截断；源 15s 采集合同不变。 |
| F11 / B5-R05(余项)、B7-R01 | R07 60a1736 | ingress 先 identity 后字段、当前冲突重复 fail closed；rejected followup best-effort 有界通知、旧 writer identity pin；test_stale_activity_ignored_before_payload_validation / test_conflicting_current_gate_stops_only_current / test_conflicting_current_activity_rejected / test_p68_rejected_followup_preserves_rx_and_reconnect。旧拒绝发送挂起期间新 START/gate 仍消费。 |
| F12 / B5-R06、B7-R05 | R07 60a1736 | p68_local_turn 未送出过期 START 作废、已送定向 ABORT、FIFO/发送 deadline；test_local_turn_host + test_local_lifecycle_adapter 实际断言事件顺序与每轮 metrics 分母、peak pending、ready latency；test_retirement_metrics_once_for_captured_turn 校验旧 owner 唯一计时。没有伪造 P95 或实物超时率。 |
| F13 / B6-R03/R04 | R05 35925c2 | test_prompt_real_adapter_dma_and_owner 编译运行真实适配器，实际 PCM marker、尾 padding、非对齐 gate、短 prompt 无 ordinary 0x32、cancel watchdog/no gate、首声/续聊；test_prompt_source_tamper_rejected 验证篡改退出且不覆盖已有产物，test_prompt_assets 保留固定四源及可重建。B6-R04 历史源保护原已存在、这里只补自动证据。 |
| F14 / B7-R02/R03 | R08 c94e47e | audio_resource worker terminal 入队失败使匹配 epoch 失效、旧 pending 不开 HTTP，test_local_resource_worker 九场景真实 owner/定向 stop/socket shutdown/drain quarantine/长流；test_terminal_loss_invalidates_only_own_diagnostic_epoch 和 test_local_grant_waits_for_both_playback_and_run(terminal_lost) 校验断链退休不发 grant、不关新连接。 |
| F15 / B5-R04 | R06 70dd4dd | test_device_endpoint_shares_models_and_rejects_other_providers 两 TCP 并发共享 executor、两份输入对应独立识别结果/各 decode 一次；test_dual_endpoint_start_failure_closes_listeners_and_executors / test_combined_health_uses_both_real_tcp_endpoints 实际启动异常清理和双端 health。保留 10400/10401；不是生产 listener 实测。 |
| F16 / B5-R03、B7-R04 | R09 356c2ce | 同一 public pipeline fixture full/no_tts/send_failure/lost_terminal/cancel_owner/stop_unconfirmed/unload/eof_unconfirmed，真实 HA/AstrBot/Wyoming/FFmpeg/MP3 GET、0x30 ID/URL/MIME、matching terminal 后一次 grant 且第二轮完成、旧 owner close 隔离、失败恢复；硬件播放边界仍模拟。 |
| F17 / B8-R01 | R10 31eb764 | 11-19 用户裁决已在计划 R10.1、B0.5、ESM-C11、迁移索引同步；local mood 仅为当前 generation 的 speaking payload，不是额外高优状态；test_local_mood_is_speaking_content_not_independent_intent / test_local_playing_mood_is_retired_by_new_wake 与 full/no_tts 真工具调用，长于原 5s、OFF、换轮、无 TTS 正常，legacy TTL 保留。 |
| F18 / B8-R03 | R10 31eb764 | public fixture display_wire_on/off，真实 7778/7777 loopback + SPP writer drain 故意阻塞，门控/PCM/终态仍被消费；错 UUID/ID/source 不改变赢家，重连资格、最新赢家/OFF、不补旧队列。非真实像素。 |
| 已历史修复 B4-R02 | B6 / R04–R05 回归 | p68_afe_flow.c prompt_rearm/neutral 保护仍存在，p68_afe_host.c 真 frame 顺序校验：持续 DETECTED/VERIFIED 不二次 wake，neutral 后才允许下一次。未重复实施。 |
| B5-R05 uptime 子项 | B7 / R07 回归 | audio_session.py 同连接 _local_uptime 单调和 disconnect reset 仍存在；本批忽略证据 monotonic-uptime.log 实际独立 UUID 99/100 拒绝、101 接受、断线后 1 接受，exit 0。 |

唯一源编号计数：B1=4、B2=4、B3=4、B4=4、B5=6、B6=4、B7=5、B8=3，共34。B3-R04 分 12槽/跨块两个子项；B5-R05 分剩余/历史 uptime；不重复计数。原软件已复现 B2-R01、B4-R01、B5-R01、B8-R01，B4-R02 历史复现已修；其余按原审查的软件静态路径或测试缺口分类，R 批 host/fixture RED 不升级为真正物理失败。无独立 reviewer 可用；作者以实际 diff/当前源码和断言进行总复核，而不是重新宣称独立复审。

## R11.2 — 全量测试与环境冲突复验

使用开发机已有 .venv（HA 2026.11.0）及 .venv-sherpa（Python 3.11），沿 R06/R09/R10 的 Wyoming 1.10.2 本地 fixture 路径；不安装依赖，不改 pytest/生产配置。repo root 执行如下命令；全部日志在 .superpowers/p68-r11/。

```bash
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath"
bash scripts/test-ha.sh tests/esp32 tests/homeassistant -q -p no:cacheprovider
bash scripts/test-sherpa-wyoming.sh -q
# 混合环境的 HA socket plugin 不适用于 ESP 主机 HTTP fixture，按原 R03/R08 拆分
(unset PYTHONPATH; PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32 -q -p no:cacheprovider)
bash scripts/test-ha.sh tests/homeassistant -q -p no:cacheprovider
# 两独立 sdkconfig 都完成生成后验证实际新配置
TIVOO_P68_CONFIG_ROOT="$PWD/.superpowers/p68-r11" bash scripts/test-ha.sh tests/esp32/test_p5_hardware_memory.py tests/esp32/test_p5b3_bootstrap.py -q -p no:cacheprovider
```

| 执行 | 实际结果 | 日志 |
|---|---|---|
| HA+ESP 混合 | 709 passed, 1 failed, 1 teardown error, 271 warnings, 216.11s, exit 1 | full-ha-esp.log |
| Sherpa 全量 | 140 passed, 1 warning, 3.31s, exit 0 | sherpa.log |
| ESP native 初次显式指定独立配置 | 117 passed, 1 failed, 37 warnings, 74.88s, exit 1 | esp-native-first.log |
| ESP native 完整复跑（当前已有配置） | 118 passed, 37 warnings, 77.73s, exit 0 | esp-native-retest.log |
| HA 独立完整复跑 | 592 passed, 270 warnings, 145.13s, exit 0 | ha-full.log |
| 两新独立 config 定向验证 | 19 passed, 5 warnings, 0.44s, exit 0 | configured-target-tests.log |

最终三个完整独立套件共 850 passed、0 failures/errors/skips；19 项是重复定向新配置验证，不另计入全量数字。R05 记录的旧诊断 TCP/状态时序波动本批完整复验未出现，不删除历史证据、也不保证永不波动。

根因分类：
- 混合 suite 唯一失败 tests/esp32/test_p6_audio_resource.py::test_controlled_http_fixture_covers_stream_and_failure_responses；pytest_homeassistant.plugins.HASocketBlockedError: A test tried to use socket.socket，teardown 同一 fixture 的 HASocketBlockedError.instances 断言。与 R03/R08 已记载的混合插件冲突一致。未改产品或 fixture，原生完整 ESP suite 与独立 HA suite 均通过（不是只重跑失败节点）。
- ESP 初次显式 TIVOO_P68_CONFIG_ROOT 早于 Classic configure，test_effective_target_configs_after_configure FileNotFoundError: esp32/sdkconfig；属于本批执行顺序失误，明确配置缺失必 FAIL 正是 R01 契约。完整 ESP native 重测及两个独立 config 都生成后的 19 项实测通过。无产品缺陷；不绕过配置断言。
- 警告保留在日志中，非零 warnings 不冒充无警告。未出现未解释的失败；运行使用 loopback/fake hardware 或 host C，而非 NAS/设备。

## R11.3 — 两 target clean build 与产物验证

使用已安装 ESP-IDF v6.1.0，IDF commit fff9895c82d744c7237be8847347bdd1b07c6643；S3 锁定 ESP-SR 2.6.1、codec 2.6.2、effects 1.4.5。新建本批独立输出/生成配置目录，不清理旧工作区或覆盖原 sdkconfig，不改任何凭据；S3 独立 dummy.defaults 仅设非生产 SSID TIVOO_R11_DUMMY_ONLY、空密码，绝不是实测 AP。串行构建，CMAKE_BUILD_PARALLEL_LEVEL=1、ninja -j1，未发生内存耗尽。实际执行（repo root，p 为独立路径）：

```bash
p="$PWD/.superpowers/p68-r11"
source ~/.espressif/tools/activate_idf_v6.1.sh
export CMAKE_BUILD_PARALLEL_LEVEL=1
cd esp32/firmware
idf.py -B "$p/esp32s3/build" -D "SDKCONFIG=$p/esp32s3/sdkconfig" -D "SDKCONFIG_DEFAULTS=$PWD/sdkconfig.defaults;$p/esp32s3/dummy.defaults" reconfigure
nice -n 5 ninja -C "$p/esp32s3/build" -j1
idf.py -B "$p/esp32s3/build" size
idf.py -B "$p/esp32s3/build" size-components
cd ../bridge_firmware
idf.py -B "$p/esp32/build" -D "SDKCONFIG=$p/esp32/sdkconfig" -D "SDKCONFIG_DEFAULTS=$PWD/sdkconfig.defaults" reconfigure
nice -n 5 ninja -C "$p/esp32/build" -j1
idf.py -B "$p/esp32/build" size
idf.py -B "$p/esp32/build" size-components
cd ../..
python "$p/verify-builds.py" "$p" esp32s3
python "$p/verify-builds.py" "$p" esp32
```

两个 configure/build/size/size-components 与产物验证均 exit 0（build-status.log、verify-s3.log、verify-classic.log）。复用 R01 的实际产物验证脚本，仅替换 dummy SSID；保存本批脚本、有效配置、manifest、ELF/map、flash_args、flasher_args.json、解码 CSV、依赖锁、size 与全日志于上述目录。再独立计算全部 manifest artifact 与 segment SHA256，S3 18+4、Classic 17+3 条均一致，两个依赖锁逐字节匹配 HEAD，完整镜像 SHA 一致（verify-manifests.log）。

| Target | 实际构建及有效配置 | app / model 大小、分区余量 | 静态链接内存 |
|---|---|---|---|
| esp32s3 | PASS；Wi-Fi init/start/connect、SR/AFE/I2S 等真实 ELF 符号存在，Classic SPP 不进入；PSRAM/OCT，wn9_hilexin smoke + VADNet1 medium；production calibrated、测试 gate、trace 均关闭 | 2,508,240 B / 579,214 B；8 MiB app 分区余约 70%，4 MiB model 分区 | DIRAM 232,547/341,760 B (68.04%)，独立 IRAM 区 16,384/16,384 B，external RAM 静态 31,180 B |
| esp32 | PASS；BT classic/BR_EDR/SPP、bank reserve 8、双核；真实 SPP/board RGB/NVS 符号存在，无 Wi-Fi/AFE/I2S 等 S3 路径 | 718,768 B；无 model；8 MiB app 分区余约 91% | IRAM 104,591/131,072 B (79.8%)，DRAM 46,483/124,580 B (37.31%) |

静态链接区占用不等于现场 heap/最大连续 DMA 分配，S3 独立 IRAM 区满不代表整个片内 RAM 耗尽；真实启动、PSRAM、长时 AFE 等仍待验。flash_args 实际偏移均核对；两分区表无重叠/越界，S3 model = 0x810000，Classic 不含 model。完整镜像为 16MiB 非生产归档，含空白 NVS 区，不得刷写。

| Target / 归档段 | offset | size B | SHA256 |
|---|---|---:|---|
| esp32s3 / bootloader.bin | 0x0 | 21120 | `b21f674b68ad5ccaf46bc60dbc11a8709f185596ce62d507269a71b4e66a352c` |
| esp32s3 / partition-table.bin | 0x8000 | 3072 | `3474e872c7915f718ccbbd3319c9164ac4d55b6be8570796d151796c7facbeb0` |
| esp32s3 / tivoo_firmware.bin | 0x10000 | 2508240 | `08f1eb45a717c97780a6f98fcf9f805420f688ac6fdaf5fe77a00ee6c46b3a19` |
| esp32s3 / srmodels.bin | 0x810000 | 579214 | `f1a1a39defc1d1c52d112b45629fb221adad4dfda85785ed9f527cb53a145e19` |
| esp32s3 / full-16MB.bin（禁止刷写） | 0x0 | 16777216 | `ede993e0b408ce66b1845fb56a25f0f050e8a47a6e953cfcb18082a4190044bf` |
| esp32 / bootloader.bin | 0x1000 | 26176 | `04ba908c2f8cd897c2b30235003217eacc5773c73aecd72db88b6bddb86ab463` |
| esp32 / partition-table.bin | 0x8000 | 3072 | `fc0cac519e0c7119f7ed0fa70326b9516f35a4c98ca3cd1ad50262b415f6dc90` |
| esp32 / tivoo_bridge_firmware.bin | 0x10000 | 718768 | `80b9fcad9de45506fb3c89daa9430804b77ad0c3ba3b713855763536dbb84ab9` |
| esp32 / full-16MB.bin（禁止刷写） | 0x0 | 16777216 | `33a6f99bea0e1f42e81f61bab5aee5d4098b76ef8269aead7edbfaf22af64e4b` |

## R11.4 — T01–T08 当前状态、下一步门禁

| 原执行组 | 软件状态（仅已设计的软件边界） | 实物 / 部署 GAP（待另获授权） |
|---|---|---|
| T01-A/B / F01 | A PASS，R01+R11 真实 target/config/ELF/manifest；B 不核销物理部分 | 两板供电、接线、独立 USB、板载 RGB、NVS/Bond、PSRAM 实际 malloc/连续 heap、AP/HELLO；非生产 dummy SSID 不是 AP 实测 |
| T02-A/B/C / F02/F03/F04/F18 | A/B 软件 PASS（实际 host UART codec/link/FIFO/error/peer）；C 原协议/服务/MCP、真实 loopback SPP eligibility/256 chunks 软件回归 PASS | 实际 921600 UART、classic SPP/RF/配对/加密/Bond、长 GIF 与写入时延、两板独立重启和断线 |
| T03-A/B / F05/F07 | 数字样本/12 槽故障恢复、reference/drain/跨块、普通音频回归 PASS；采集 trace 准备 PASS | 两颗麦克风独立相位与 TX/RX 时钟、DAC/AUX/实际 HTTP/HTTPS/MP3/SRC、声学互相关/延迟与真实 GDMA 恢复、压力 |
| T04-A/B / F06/F07/F08 | A 模型构建、runtime fake vendor/gap/门控、neutral 与 gate/cache trace 主机证据 PASS；B 软件采集准备 PASS，真实声学无证据 | 最终官方词、真实 AFE feed/fetch/reset/可用性、cache 对应关系、1m/3m/实际距离、电视/自播/双讲误漏、负载、P50/P95、标定。当前仅保留 smoke 模型，不宣称已确定最终词 |
| T05-A/B/C / F09/F10/F11/F12/F15/F16 | public HA 真实 pipeline+fake TCP provider、ASR-only 并发/健康、EOF 真尾帧与有界 finalize、旧 UUID/epoch/FIFO/诊断 PASS | 生产专用 pipeline/实体、10401 注册与实际识别服务/模型语义、真实设备上传时序、多消费者/实际资源及延迟 |
| T06-A/B / F05/F07/F08/F13 | 四源 hash/确定性 PCM/篡改拒绝、真实 C adapter/DMA marker/尾部/fault/watchdog/gate、正常音频数字证据 PASS | 真实提示音首声尾声、标定参数、听完立即说、500ms 端点、语音自播负样本；production gate 不解除，调试 trace 不默认开启 |
| T07-A/B/C/D / F11/F12/F14/F16 | 轮次 owner 抢占/取消/终态丢失/定向 stop、正常长流、真实 loopback SSE/MP3/EOF、3s/4s/15s 与 grant/Handoff 验证 PASS | 真正 HTTP TTS/AstrBot Stop/播放中打断、设备旧声停止/短 prompt/drain、真实续聊/连续三次打断/延迟、HA reload/断网物理组合 |
| T08-A/B/C / F03/F17/F18 | 单 coordinator、真实 local speaking mood（获批 R10）/legacy TTL、旧事件隔离/OFF/慢写/重连同步软件 PASS | 实际 Tivoo 像素与 OFF/ON/最新赢家、真实 SPP 慢链、两板独立 reset/HA reload 组合、实际画面与吞吐 |

无本批新增已证实生产代码缺陷；所有 18 F 的软件主责已完成或补证，34 源编号已追踪，并保留各原报告的实物/生产 GAP。R11 并非 B10 的49新合同、192历史ID、19遗留项逐行最终核销；不改写原 B1–B8 报告。P9 主动问答的 HA Core ask_question future 回调边界（R06 报告）属未引入功能，不算本次缺陷也不替未来验收。T09/B9 仍须 b4–b8 必要硬件/生产 gate 达成和另获授权；不删 legacy、10400/KWS/四 MP3，不改原消费者。T10/B10 必须现场全量验收；本批不推进。禁止刷写旧 ESP32/S3、擦 NVS、连接 NAS、部署或 push。

## R11.5 — 范围与交付

本批没有生产代码或测试变更。只提交本报告、R11 五项验收/状态及原计划追加的软件状态引用；开始前原 B1–B10 计划已有未提交的审查修复插入链接，保持原始工作区 hunk，不将其纳入本批提交。R01–R10 各独立提交均在当前分支历史中；本批不合并、不推送、不连接 NAS、不部署、不刷写、不擦 NVS。没有新增需返工的软件 FAIL，实物/生产 GAP 如上保留。后续必须另获授权，硬件到齐先按原计划实物 gate，达成 B9 前置再条件清理，最后 B10 综合核销。
