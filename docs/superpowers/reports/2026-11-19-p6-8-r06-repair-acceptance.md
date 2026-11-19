# P6.8 R06 HA STT 输入终态与 Sherpa 并发验收

日期：2026-11-19；feature/p6-8-s3-local-wake；基线 35925c253235edc146b592f45b1ccd174c262d90（R05）。依据 [执行计划](../plans/2026-11-19-p6-8-review-repair-execution-plan.md) R06，F09/F10/F15、B5-R01/R02/R04、VOICE-C02/03/06/07、T05-A/B/C 本批软件子项。非整体硬件合同 PASS。

## R06.1/2 — 真实 HA 阻断点及正常输入 EOF

开发机实际安装 HA 2026.11.0：wyoming/stt.py 的上传任务正常遍历结束才发送 AudioStop；接收任务与上传任务 FIRST_COMPLETED，peer 提前回 Transcript 可先完成接收并取消上传。assist_pipeline/default_pipeline.py 在 STT_END 同步回调返回后才进入 Intent；assist_pipeline/run.py 的 process_event 同步调用 callback，execute 捕获 PipelineError 并经现有 ERROR/RUN_END 路径收尾。AssistSatelliteEntity 的 public async_accept_pipeline_from_satellite 是实际运行入口。原本只将 speech_end 视为 input_finished，且 _arm(0) 调度 stop，不能同步阻断 STT_END 后的 Intent。

保留 local_input_finished 的协议语义，新增 local_input_drained：匹配当前 local UUID、未 abort，且消费者自然读完所有 PCM、offset == tail、已合法 speech_end，才置位。接收 end、取走最后一个 yield、提前关闭或 abort 不等于成功 EOF。audio_subscription 提供可选 on_eof，仅当前轮次在真正 EOF 后切换计时阶段。STT_END 未满足条件，或本地模式意外 STT_VAD_START/END，直接抛 Core SpeechToTextError（stt-stream-failed），不再异步竞速；旧 local turn 的迟到 STT_END 同样拒绝。正常状态、回调、Intent 路由及原 10400 非本地识别逻辑保留；没有 patch Core、替换 provider 或使用私有运行入口。

实际 public fixture：HA Core + loopback fake Wyoming，正常分支保留完整 PCM、唯一 AudioStop、本地只读时间 Intent 和 fake AstrBot、wake interception、模拟已挂起的 ask_question future 验证。不操作真实设备。负例让 peer 在首块提前回 Transcript；另一个在 socket 写入首块后故意阻塞上传任务，设备送合法 tail/end，再让 peer 返回，证明 wire end 不等于 drain。VAD 负例仅在测试中注入 segmenter/metadata，使真实 Core 发 STT_VAD_START/END，不伪造 pipeline。

|场景|RED 或 GREEN 实际证据|
|---|---|
|提前 Transcript（无 end）|RED 出现 INTENT_START；GREEN STT_END → ERROR → RUN_END，0 AudioStop、0 Intent、0 chat|
|已收 end，未 drain|RED 出现 INTENT_END 且 fake chat +1；GREEN STT_END → ERROR → RUN_END，0 AudioStop、0 Intent、0 chat|
|unexpected VAD_START/END|RED VAD_END 发送 AudioStop；GREEN 两者 ERROR/RUN_END，0 AudioStop、0 Intent、0 chat|
|取消/断链|GREEN RUN_END，未送 AudioStop、未进入 Intent/外部请求|
|正常 endpoint|GREEN 全 PCM、一次 AudioStop、正常本地及 AstrBot Intent；不影响既有正常语义|

HA public hook 边界：Core 自身 _internal_on_pipeline_event 会在 public STT_END 转发前对已存在的 _ask_question_future set_result。当前 Tivoo 没有实现 async_start_conversation 主动提问入口（P9 未引入）；本批保证现有语音轮 Intent/设备动作不执行，保留正常的模拟 ask_question 回归，不把该 hook 宣称为未来主动问答结果的前置校验。P9 若新增此入口，须重新核对该上游边界；没有覆盖 Core 私有方法或提前实现 P9。

## R06.3 — 独立 finalize watchdog

原设备 speech 15s 合同不变；HA 既有 17s local_speech_timeout 保留至真实 drain，而不是收 end 即取消。自然 EOF 回调取消采集 watchdog、启动独立 stt_finalize_timeout 45s（包括正常 AudioStop 发出至 STT_END 的等待）。STT_END/ERROR 取消，stop/断线/换代经既有 _clear_timers 和 _retire_local 回收；_expire_timer 同时比较当前 _Turn 和 cancel handle，绑定已有 UUID/epoch，不污染新轮，不将此期限套到 Intent/TTS。

阈值决定依据：[P7A 实测](2026-11-10-p7a-acceptance-report.md) NAS 中文5.033s解码0.417–0.464s、中英8.100s解码0.788–0.802s，RTF 约0.083–0.099。共享 STT 单 worker 默认 MAX_PENDING_PER_MODEL=1，legacy 现有默认请求上限300s，设备15s，以一项在先长请求加当前命令保守线性估算 (300+15)*0.099≈31.2s，45s 留负载和传输余量。该估算不是300s长音频实测、不是正常响应 SLA，也非实机 P95；超时才取消，不人为等待45s 才产生结果。生产并发排队与实际延迟属 R09/R11/硬件门禁。

RED：合法 AudioStop 后 silent peer，假钟推进46s仍占 owner。GREEN：正常 EOF 后20s仍等待，46s observe stt_finalize_timeout，peer close，0 Intent/chat，timer 清除，新轮正常。慢结果20s成功且一次 AudioStop；旧轮20s后 supersede，下一轮正常 EOF，仿真跨越旧 deadline 后仍保有新 owner 并成功一次 Intent/chat；provider Error 后取消 watchdog 和连接，轮次释放，新轮正常。设备协议、3s/4s gate 和 TTS terminal 逻辑未改。仿真时钟只推进 HA event loop；Core 2s duplicate wake 冷却使用真实 monotonic，恢复测试明确遵守冷却，不绕过生产逻辑。

## R06.4 — 双入口共享模型并发及 health

核对 services/sherpa_wyoming/run.py 的共享 provider、ModelExecutors 和 finally（两 listener stop、executors.shutdown），及 healthcheck.py 对配置的两个 endpoint gather。真实 loopback 双客户端同时发送 Transcribe/AudioStart/不同 PCM 后 AudioStop。fake recognizer 第一 decode 暂停，断言两个 session 各有640B，独立 stream，样本 8192/-16384 转为 0.25/-0.5；释放后各 decode 一次、各 socket 收 positive/negative，模型加载一次、同 provider/executor。10401 仍 ASR-only，拒绝其他 provider；10400 能力不变。分别真的 bind 占用 legacy/device 端口，run_server 启动失败后两个 stop、executor 一次 shutdown、另一端无法连接。实际 TCP health 描述 both 正常返回0；分别仅 legacy 或 device 可用返回1。首轮专项直接通过，只补测试证据，无人为制造 RED、无 Sherpa 生产代码修改、未重载或重复加载生产模型。

## RED/GREEN 与回归

日志：.superpowers/p68-r06/。
- red-core.log：第一轮 fixture 调用错误，不计产品 RED；修正 advance_clock pytest fixture 后 red-core2.log：4 failed/1 passed/4 deselected，exit1，失败为 early、queued_end、vad_end、silent，VAD_START 原先单独负例通过。
- green-core.log：9 passed/14 warnings，exit0。扩展轮次恢复测试初次 green-core-finalization.log 3 failed/22 passed，原因为测试未遵守 Core 实际2s冷却；显式等冷却后重新执行指定四文件。
- ha-focused.log：82 passed/16 warnings，32.88s，exit0；完整实际 Core 事件列表、Wyoming 消息序列与 fake chat 数已记录，R09 可复用。
- sherpa-focused.log：20 passed/1 warning，exit0；sherpa-full.log：140 passed/1 warning，3.36s，exit0。
- 额外 HA 全量 ha-full.log：556 passed/5 failed，118s，exit1。5例均为既有 test_p68_display.py 的 endpoint helper 在真实 async iterator drain 前人为触发 STT_END，调用序列不满足新增判据。仅修复该测试公共 helper 等待真实 local_input_drained（有界 event loop polling），保留全部状态断言与实际业务代码。ha-display-green.log：13 passed/7 warnings，exit0。
- 最终 HA 全量 ha-full-final.log：561 passed/260 warnings，117.13s，exit0；没有失败或 skip。包括 AstrBot、Tivoo、transport、legacy、TTS 取消与表情回归。原依赖弃用/HTTP AppKey/pytest socket 提示保留。

复验命令（开发机现有依赖，不访问生产）：
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath" bash scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/{test_p68_real_pipeline,test_p68_local_session,test_assist_satellite,test_audio_session}.py -q -s -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath" bash scripts/test-ha.sh tests/homeassistant -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 bash scripts/test-sherpa-wyoming.sh tests/services/sherpa_wyoming/test_server.py tests/services/sherpa_wyoming/test_healthcheck.py -q
PYTHONDONTWRITEBYTECODE=1 bash scripts/test-sherpa-wyoming.sh -q
```

## 审查与保留项

按 Superpowers executing-plans / receiving-code-review / systematic-debugging / test-driven-development / requesting-code-review / verification-before-completion 执行；无独立 reviewer/subagent 工具，按模板自审完整变更、真实 Core 同步 callback 与 public cancellation、PCM cursor/EOF、timer 生命周期、token identity、新旧轮清理、legacy 兼容及并发测试断言。自审发现原 display 模拟调用次序不合法，已仅修测试 helper 并重新全量验证。未发现本批范围内明确剩余 Critical/Important 软件问题。45s 选择为本批依据服务配置和历史实测作出的工程阈值，非生产延迟结论；未来主动问答入口的 Core 内置 future 边界已记录。R07–R11 未实施；R09 组合复验、R11 clean build/全量复验、生产 10401、真实模型排队/声学/播放/硬件仍 GAP。R06 未改固件，未重复构建或刷写，未访问 NAS、未部署、未推送远端。原 B1–B10 计划的既有链接改动不混入提交。
