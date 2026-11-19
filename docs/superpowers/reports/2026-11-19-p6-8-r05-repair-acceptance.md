# P6.8 R05 有界校准 trace 与真实提示音数字链验收

日期：2026-11-19；feature/p6-8-s3-local-wake；基线 eefa2c79341d55c1805a8b4f09e3951c03f2f7a7（R04）。依据 [执行计划](../plans/2026-11-19-p6-8-review-repair-execution-plan.md) R05，F07/F13、B3-R03/R04(跨 reference)、B4-R04、B6-R03/R04；AFE-C01–05/10/12、VOICE-C04/05/07–10、T03-A/B/T04-A/B/T06-A/B 的本批软件子项。不是整体物理合同 PASS。

## R05.1 采集准备及可复现读取

保留 R03 可信 RX/TX 时间轴、reference ring 和 R04 VAD gate。capture_next 额外返回 DMA epoch 起始 raw sample；feed 在下次 capture_next 前复制 raw_slots/raw_tx（实际 EOF 提交的最终 TX 样本，含静音填充及 reference 校验），fetch 在下一次 vendor fetch 前复制 enhanced PCM 和独立 cache；不缓存借用指针。记录无效 reference、采集错误、索引断续、AFE reset/gap、实际 turn 的 gate/prompt 边界及是否成功开放；无已知索引时用 UINT64_MAX，不用上一 epoch 猜测。默认关闭时编译消去 trace 调用，无持续录音、无协议扩展、无新增网络服务、无 cache 拼接。

**本地调试入口**：独立 S3 校准构建中显式设 CONFIG_TIVOO_P68_CALIBRATION_TRACE=y（默认 n），CONFIG_TIVOO_P68_TRACE_DELAY_SECONDS=15（0–120 可调），AFE 初始化成功后延时一次，4s 采集截止。仅调试模式分配 PSRAM raw 1,400,000 B + afe 600,000 B；每条完整记录要么复制成功，要么增加 dropped，不覆盖旧数据、不写半条记录；发生分配/任务失败明确报告并停用 trace。两生产者只在短 mutex 内复制，结束先停收并同步最后写入，再由低优先级任务通过当前本地 serial console 输出，最后释放两缓冲；不在 feed/fetch 临界路径输出音频。实际 PSRAM 峰值、实时性、串口完整性待硬件验证；4s 为一次有界窗口，可多次独立采集，不等于长时漂移已测。

**格式 v1**（little endian，每条固定 40B header：index/epoch/aux 各 u64，kind/flags/count/extra 各 u32）：

| kind | index / epoch / aux | payload |
|---|---|---|
| 1 RAW | RX raw 32k 首样本 / DMA epoch 起点 32k / 实际所读 TX 32k 首样本 | count=160 双声道 slot（两有符号 32bit 原始 I2S slot），extra=160 TX mono s16；INMP441 有效高24位，分析时按实际格式算术右移8 |
| 2 FETCH | 16k 增强逻辑 cursor / 对应 AFE 首 feed 16k / 当前 gate 或未知 | count 个增强 s16，extra 个 vendor cache s16；cache 没有可信起始索引 |
| 3 CAPTURE_ERROR | 未知 / 未知 / 未知 | 无；采集失败 |
| 4 GATE | 16k 下一 cursor 或未知 / AFE 首 feed 或未知 / 请求 boundary 或未知 | 无；区分 prompt 开始、关闭/取消、请求打开和实际打开 |
| 5 AFE_GAP | 16k cursor 或未知 / AFE 首 feed 或未知 / 未知 | 无；AFE reset 断点 |

flags 位掩码：1=gap，2=reference_valid，4=speech，8=vad_valid，16=gate_open，32=prompt，64=open_requested。RAW 每条 1640B，4s 正常 800 条约 1.312MB；AFE cache 长度可变，超过预留容量丢整条并报 dropped。raw/afe 各自记录顺序，不以串口输出顺序替代采样时轴。AFE epoch 与 DMA epoch 是不同语义，按 32k/16k 坐标和 gap 正确关联，不能将 fetch 的逻辑 cursor 当作已经校准的物理声学位置。

**实物后**（需另获用户授权，不在此次刷写）：使用调试构建及开发机串口 monitor 保存完整文本日志，从两条 BEGIN 到 END 均完整保留；采集窗口按受控声源时点调整。导出一行 BEGIN 包含 stream/dropped/size，DATA 包含 stream/byte offset/hex（每块不超过256B），END 表示完整流。命令：
```bash
python3 scripts/read-p68-trace.py serial-capture.log trace-output
```
生成 raw.bin/afe.bin 及对应 JSONL（含原始采样及索引），缺失、乱序、截断拒绝解码，打印各自 dropped；有 gap/invalid/dropped 的区段不用于校准。trace 包含实际麦克风音频，仅本地保留并按需删除。此 debug 入口仅采集，不自动播放扫频/提示音，不放宽普通播放 UUID/epoch 绑定；真实标定阶段另行受控安排激励源/播放 owner，保持未标定 production gate 关闭。用同 epoch 的 TX/RX marker 互相关、多次采集比较延迟/漂移与左右残留，测量实际声学首尾；对增强 PCM 与 cache 波形核实重叠或遗漏后才决定是否有后续拼接需求。旧 47.5ms 与配置初始0均不是新硬件实测值。

开发机样例（合成 host 数据，**非实测**）：.superpowers/p68-r05/trace-serial-host.log，trace-example/{raw,afe}.{bin,jsonl}。实际 debug task 的 host 执行产生 raw 1,398,920B / 48 dropped（故意超容量压力），afe 424B / 0 dropped；reader 完整按索引解码。test_enabled_trace_task_exports_once_and_stops 验证窗口前后、导出中不再采样、释放后 inert，以及饱和仅丢整条；test_trace_copies_bounded_indexed_records 验证覆盖输入指针后原数据仍一致、字节布局与截断拒绝。test_afe_runtime_availability 使用实际 feed/fetch callsite + vendor/RTOS fake 验证记录的真实 raw/cached pointer、长度、索引、gap 与 gate/VAD flags；实物 SDK 缓存物理映射仍未测。

## R05.2 真实适配层数字链

新增 test_prompt_real_adapter_dma_and_owner，编译实际 s3_local_turn、s3_afe、audio_resource、audio_capture、audio_output_manager、p68_prompt、p68_local_turn、p68_afe_flow（锁定 vendor 头、真实 cJSON，fake I2S/RTOS/clock/AFE fetch 边界）。真实12槽 output/EOF 驱动，按实际消费 slot 逐样本比对 signed 非零 marker；三种 ready 长度 23701/23892/26627 样本、followup 15360 样本，均远超5120 queue，多轮补写无乱序、漏/重样本；双槽一致、数字尾部为0。实际 adapter 生成 0x26 JSON，校验当前 UUID/epoch、completed、owner 已释放、gate index = 真实模拟 EOF+FIFO 余量 + 121 sample tail ±37 sample offset（仅测试值，非整80块）；不得产生普通 0x32。也验证跨 gate 即时命令443个合法样本 + 197补零，实际 0x21 走640 sample、0x24 speech_end 计数一致并通过真实 followup handler 开新轮。10 个测试场景：ready1/2/3、followup、negative、late、fault、timeout、stop、epoch。迟到时不开放；EOF 丢失、5s watchdog 以及 STOP/epoch 换代不得伪造 gate，回收后新 owner 输出完整新提示音。数字链未发现需改动的 adapter 缺陷，保留现有 owner、R03 fault 与 R04 gate；不提前做 R08 普通 worker/R09 真实 HA 组合。host linker GC 不执行未调用 HTTP worker；host 编译屏蔽该既有代码的 signed/unsigned warning，不屏蔽生产构建报错。

## R05.3 资产保护

原四 MP3 未改，SHA256 与 generate_prompts.py 冻结表完全一致。现资产测试两次确定性转换，四 PCM bytes 47402/47784/53254/30720；缺失资产置零长度。新增临时副本 ready_01.mp3 追加1字节，生成器非0退出并报 frozen contract mismatch，旧缓存内容未被当作新结果生成；CMake 已有 COMMAND_ERROR_IS_FATAL ANY，配置在使用旧 PCM 前失败。该负例直接 GREEN，不改 generator 或源文件。

## RED/GREEN 与回归

日志及产物：.superpowers/p68-r05/。
- red-capture.log：2 failed/4 passed，exit1；其中原采集 API 缺 epoch 字段导致 fixture 编译失败，另一个为新增测试自身 signed/unsigned 编译问题，不称产品 runtime RED。
- red-trace.log：trace 入口/格式文件未存在，1 failed/1 passed，exit1；跨 reference 原实现直接通过，新增逐样本验证跨两个80 sample@16k 块（实际 raw160 each，取160 raw，偏移39@16k/78 raw）、缺失半块、环覆盖、gap 与恢复 epoch。
- green-trace.log：10 passed；trace-callsite.log 3 passed；trace-runtime.log 2 passed。初次 adapter-first.log 为既有 unused/sign-compare host 编译问题；adapter-second.log 的 tail123+offset37 恰好整块导致测试设定错误，改为121；不把 fixture 问题报作产品缺陷。adapter-exact.log 1 passed；prompt-digital-host.log 十种真实调用场景分别 exit0。
- 最终计划指定 ESP 文件含普通 test_p6_audio_resource.py：17 passed/2 warnings，8.49s，exit0（green-esp-target.log）。HA test_prompt_assets.py/test_p68_local_session.py：26 passed/8 warnings，3.64s，exit0（green-ha.log）。
- 额外全 ESP 首次 107 passed/1 failed，69.48s，exit1（esp-full-first.log）；旧 test_queued_records_survive_disconnect_and_replay_after_new_handshake 的第二次握手收到 TCP RST，单项 retry 1 passed/exit0（diag-retry.log）。再次全量 105 passed/3 failed，67.96s，exit1（esp-full-second.log）：同一重连、test_wifi_ip_loss_closes_both_ports_and_new_sessions_recover 的 close RST、test_device_status_ping_events_and_p6_error_codes 在 simulator 的 stdin 状态命令与 socket 状态查询之间竞态（idle vs fetching）。三旧测试的编译单元及 fixture 与 R04 基线一致，不含 R05 更改的 capture/AFE/trace；无证据为 R05 回归。保留日志，不改旧网络/状态测试或生产模块，不声称额外全 ESP 全绿。三项合并独立复测 3 passed/exit0（diag-status-retry.log）。构建完全结束后最后一次串行全 ESP 107 passed/1 failed，70.66s，exit1（green-esp-full.log）；旧 test_unknown_message_reports_protocol_error_and_preserves_next_frame 第二个回复发生 socket closed after 0 of 16 bytes，单项复测 1 passed/exit0（diag-unknown-retry.log）。同一未修改诊断 host simulator，波动仍在，不能宣称全量稳定 PASS；R05 17 项指定测试均通过，旧连接/状态波动保留给 R11 全量复验证据处理，不进入其修复。

开发机复验命令：
```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32/test_p68_audio.py tests/esp32/test_p68_afe.py tests/esp32/test_p68_prompt.py tests/esp32/test_p68_turn.py tests/esp32/test_p68_trace.py tests/esp32/test_p6_audio_resource.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath" bash scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_prompt_assets.py tests/homeassistant/custom_components/tivoo/test_p68_local_session.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32 -q -p no:cacheprovider
```
既有 native pytest 配置/mark 与 HA 依赖弃用警告不改；无删测/绕开协议校验。

## S3 构建

开发机原 EIM ESP-IDF v6.1，未变更依赖/板型/生产参数。串行 reconfigure、nice -n 5 ninja -C build -j1、idf.py size，两次构建均 exit0；先显式 trace 调试构建，再还原原 sdkconfig 并重配恢复默认（新增 config 为 n）。两版本 TEST_GATE/PROMPT_CALIBRATED 都关闭。独立保存 ELF/BIN/flasher_args.json 与 SHA256SUMS，逐文件校验 OK。默认 ELF 不含 tivoo_trace_start/record/append 符号，调试 ELF 含三个符号；没有把校准采集带入默认发布路径。

| 版本 | app bin B | image B | DIRAM B | BIN SHA256 |
|---|---:|---:|---:|---|
| 默认 | 2105936 | 2105821 | 196503 / 341760 | 6d14c7e228cb9f7953241d1f7ea6ae401babc5aeaf7d6e4c3b3e6728865132f0 |
| trace 调试 | 2107888 | 2107773 | 196551 / 341760 | 5ccbc2eaea5f00669cd74571adf980857bd70b4b5512536bc02f0c181b2d23b8 |

目录 .superpowers/p68-r05/firmware/ 和 trace-firmware/；s3-build.log 与 s3-trace-build.log。DIRAM 为静态构建占用，不能代替运行峰值；2MB trace 缓冲需实机 PSRAM 验证。Classic 未改，双 target clean 总复验仍属 R11。

## 审查与保留项

按 Superpowers executing-plans / receiving-code-review / systematic-debugging / test-driven-development / requesting-code-review / verification-before-completion 执行。无独立 reviewer/subagent 工具，按模板逐项自审完整 diff、接口、传播时序、容量边界、指针寿命、默认关闭路径及实际断言。修正无有效 AFE epoch 时的 gate marker 读取为 unknown，避免误用旧 epoch；测试记录的完整性和真实 adapter gate 比较已验证。小型本地串口导出为本批决定，选择不扩展 HA/TVIO/MCP，不做波形自动拼接或新播放 owner；没有发现本批范围内明确剩余软件缺陷。未核销物理合同：真实 HTTP/HTTPS/MP3/SRC、AUX、两麦/TX 起始相位、物理 offset 与 tail、AFE cache overlap/真实声学首尾、长时漂移、实际资源峰值、串口带宽/实时性与现场标定激励仍 GAP；默认 gate 关闭，实际调试/播放需硬件和另获授权。R06–R11 未实施，R08/R09/R11 只保留后续关联复验。未访问 NAS、未部署、未刷写旧 ESP32 或 S3、未推送远端。原 B1–B10 计划的既有链接改动不混入此次提交。
