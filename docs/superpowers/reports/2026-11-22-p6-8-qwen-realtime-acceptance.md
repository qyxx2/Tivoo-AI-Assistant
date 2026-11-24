# P6.8 B8.7 — Qwen Realtime 迁移端到端验收与 NAS 部署

> 2026-11-24 最新：已定位严重回复卡顿为 core0 HTTP/SRC 与 AFE 调度竞争，播放任务移至 core1 / priority3，并关闭 Wi-Fi Modem-sleep。固定6秒对照零断粮，用户反馈日常回复已不卡顿；30秒连续压测仍有AFE过载，B8.7整体/B9继续HOLD。用户禁止后续发声，已刷回无探针正常固件并暂留下载模式。详见[卡顿定位与修复](2026-11-24-p68-playback-stutter.md)。

> 2026-11-23 声学校准续验：当前 S3/DAC/Tivoo/双麦装配的自动延迟校准 PASS，四组真实回采验证后已刷入正常固件，AEC 参考延迟 800、AFE 偏移 +519、安全尾音 1600（均为 16 kHz 样本）；90 秒启动复验 PASS。详见本文 §13。Step 8/9 的真人唤醒、真实 Qwen 播放/打断/续聊尚未核销，B9 继续 HOLD。

> 2026-11-23 最新：持续数字流故障已修复，最终无统计S3固件330秒日志中32份telemetry连续310.52秒严格PASS，无新增gap/drop/reset；ESP32回归145 passed。真实声学与物理播放/打断/follow-up尚未核销，Step 8/9及B9继续HOLD。见[持续数字流修复与实机长测](2026-11-23-p6-8-stream-throughput-fix.md)。

> 2026-11-23 最新：AFE 内存初始化故障已修复并通过最终固件刷写复验；持续 RX gap/reset 仍 FAIL，B8.7/B9 HOLD。见 [AFE 内存修复与自动化续验](2026-11-23-p6-8-afe-memory-fix.md)。

> 2026-11-23 自动化实机续验：S3 已连接并成功刷写；当前发现 AFE `ESP_ERR_NO_MEM`，提示音未校准，Step 8/9 仍阻塞，B9 HOLD。最新证据和限制见 [实机续验报告](2026-11-23-p6-8-b8-7-hardware-automation.md)。下文保留 11-22 原始验收记录。

日期：2026-11-22；基线：`b22e9e9`；分支：`feature/p6-8-s3-local-wake`。

**结论：B8.7 的软件、NAS 部署、真实 Qwen↔HA MCP、启动/回滚门已完成；真实 ESP32-S3 物理音频链路仍为明确 HARDWARE GAP，因此 B9 仍 HOLD。** 本报告严格区分软件证据、NAS 生产服务证据和物理硬件证据。缺失 S3 时不以旧 ESP32 classic 替代验收，不把 Gateway 音频生成完成视为设备播放完成。

## 1. 本地回归与构建

- HA/Qwen 定向门：207 passed。
- Qwen local-turn 禁旧 pipeline 专项：`test_qwen_satellite.py` 6 passed；Qwen 分支把旧 `async_accept_pipeline_from_satellite`、`validate_local_pipeline`、`PipelineTtsEvents` 设为调用即失败，实际未触发。
- B8.2 Gateway probe：12 passed。
- B8.3 Frontend MCP/private HTTP：198/198 passed。为避免 B8.5 的测试文件被 B8.3 `tests/*.test.mjs` 误纳入，本批将 `deploy/nas/qwen/patches/test.sh` 收窄到 B8.3 自有 `private-http.test.mjs` 与 `mcp-integration.test.mjs`；B8.5 门独立运行。
- B8.5 terminal-status patch：100/100 passed。
- B8.7 HA MCP 冷启动门专项：3/3 passed；覆盖 404、部分工具、完整工具与缺工具超时 fail-closed。
- ESP32 host SRC/resource：38 passed。
- 双 target clean build：ESP32-S3 与 ESP32 classic 均通过 build manifest/symbol/partition 核验。S3 clean build 使用 dummy Wi-Fi，只作为 clean-build 证据，不用于实机刷写。
- 另用现有生产 `sdkconfig` 构建当前 HEAD 的 S3 app：`tivoo_firmware.bin` 2,107,120 bytes，SHA256 `511841aa46a8cb3b6c26d4ac16f59e70c4eded5c4a12a0415d9399a049c3320e`；已暂存 NAS esptool artifacts，未刷写。

## 2. NAS pre-state、备份与专用 HA 身份

pre-deploy 备份：`/volume1/docker/qwen-audio-agent/backups/p68-b87-predeploy-20261122T211413`。包含 active Compose、`config.env`、容器/image inspect、原 Gateway/Prompt 文件、HA Tivoo custom component tar、HA auth storage 及真实 MCP tools/list。凭据备份权限受限，报告不记录 token 值。

部署前 Qwen 没有 Frontend MCP 配置或 B8.7 runtime mount。HA 专用身份 `Tivoo Qwen MCP` 已按实际 HA 2026.11.0 auth store 创建并显式持久化：`system-users`、非管理员、`local_only=true`、active。专用 token 对 HA `/api/` 返回 200；无效 Bearer 的 MCP initialize POST 返回 401。

HA auth pre-state 与部署态逐对象比较：原 2 users / 3 groups / 1 credential / 8 refresh tokens 均逐字段未变；部署态只多出 `Tivoo Qwen MCP` 用户及其 1 个 refresh token。因此后续 rollback 可以精确恢复 auth pre-state，不覆盖其他同期账号变化。

## 3. 真实生产 MCP tools/list 与 allowlist

使用上述专用普通用户连接真实 `/api/mcp/assist`，完成 MCP initialize + tools/list，保存完整描述和 input schema。真实顶层工具共 54 个。

生产 allowlist 共 46 个：

- 28 个当前真实 `tivoo__*` Tool；
- 18 个已在真实列表出现的 HA 原生查询/家庭控制工具，包括 `homeassistant__GetLiveContext`、日期时间、标准 intent、media player、fan、todo 等现有合同内能力。

明确排除 8 个：`astrbot__NewConversation`、`assist_satellite__HassBroadcast` 和 6 个重复 Tivoo intent_script。没有通配、任意 HA service-call 或管理能力。

## 4. Qwen NAS 持久部署

持久部署已完成并核对 SHA：

- B8.3 `frontend-mcp-config.mjs` patch；
- B8.5 `realtime-presentation-runtime.mjs`、`gateway-events.mjs`、`gateway-client-protocol.mjs` terminal-status patch；
- `/root/.config/qwaudio/frontend-mcp.json`，只含 env 引用，不含 token；
- `QWEN_AUDIO_FRONTEND_MCP_CONFIG`、`HA_ASSIST_MCP_URL`、`HA_MCP_AUTHORIZATION`、`QWEN_AUDIO_FRONTEND_MCP_ALLOW_PRIVATE_HTTP=true`；
- 完整上游 Qwen 2.1.0 `PROMPT.md` + P6.8 follow-up overlay；
- `qwen-entrypoint.sh` + `wait-ha-mcp.mjs` 启动门：Qwen 冷启动前用真实 HA `tools/list` 等待生产 allowlist 的 46 个工具全部可见，再启动 Gateway。

第一次同时重启 HA 和 Qwen 时，Qwen 比 HA 更早初始化，日志出现一次 `frontend_mcp.connection_failed ... fetch failed`；回滚演练又复现了 endpoint 先 404、随后 tools/list 只出现部分工具的中间态。上游 2.1.0 `FrontendMcpClient` 初始化失败后不会后台重新发现，因此本批没有修改上游状态机，而是在部署层增加 fail-closed 启动门。真实冷启动验证中，HA 停止时 Qwen 容器仅等待并反复报告 `fetch failed`，Gateway 3101 未启动；HA 恢复后启动门实际经历 `HTTP 404 → missing 33/46 → missing 1/46 → 54 discovered / 46 required`，随后才 `exec qwenaudio gateway --lan`，无需人工重启 Qwen。最终生产日志：`frontend_mcp.connected {server:"homeassistant", transport:"streamable-http", tools:46}`。

最终 `/api/health`：`status=ready`，`frontendMcp.ok=true`，`initialized=true`，`homeassistant.status=ready`，`tools=46`；`voiceInput.inputActive=false`、`clients=[]`，没有 WebUI/第二 owner 占用。

## 5. Prompt / persona / memory 持久性

Qwen 运行时真实配置值：

- `frontendPromptDir=/root/.config/qwaudio/frontend-agent`
- `assistantProfilePath=/root/.config/qwaudio/ASSISTANT.md`
- `userModelPath=/root/.config/qwaudio/data/USER.md`
- `frontendMemoryPath=/root/.config/qwaudio/data/MEMORY.md`

Prompt 实际读取 2762 Unicode chars / 6640 bytes，低于 16,000 字符上限。`ASSISTANT.md`、`USER.md`、`MEMORY.md` 均位于 `/root/.config/qwaudio` 对应持久卷路径并为 mode 600。没有导入 AstrBot memory/persona。

## 6. 真实 Qwen → HA MCP 模型调用

只读生产探针使用真实 DashScope Realtime 模型、真实 Gateway 和真实 HA MCP，输入为语音 PCM；模型生成音频只计数丢弃，不向 ESP32/Tivoo 播放。

`GetLiveContext` 探针：

- user `transcript.final` 成功；
- Qwen tool event 明确出现 `mcp__homeassistant__homeassistant__GetLiveContext` received + completed；
- HA 返回实时暴露实体状态；
- 同一 turn 的后续 assistant final 正常生成；
- output audio delta 为真实模型音频但未播放。

日期时间探针也完成 Gateway/模型基线，但模型选择自身 `get_current_time`，故不作为 HA MCP read 证据。

受控 Tivoo `ShowText` 写调用：**PASS**。经客户端显式审批后，真实模型事件出现 `mcp__homeassistant__tivoo__ShowText` received + completed，后续 assistant final 返回“设备屏幕已显示‘测试’”。HA Tool 使用 `blocking=True` 调 Tivoo service；service 等待 `ExpressionCoordinator`，后者只有在当前 7777 control writer `write()` + `drain()` 成功后才返回，断线/写失败会抛错。因此这条证明 Qwen → HA MCP → Tivoo transport dispatch 成功；没有设备像素级回执，报告不把它写成物理屏幕确认。

## 7. 生产 Gateway 会话/lease 子集

在部署态使用全新的 B8.7 session IDs 重跑真实 same-socket probe：

- 不同 instance 的第二 owner 被 `client_occupied` 拒绝；
- 主 socket 三轮连续对话保持 open；
- journal 在 socket open 时为 6 条 user/assistant 消息；
- 同 session 断线重连恢复同一 6 条 history，并在新一轮后增长到 8；
- 独立 session 连接前 history=0，连接后仍为 0，自己的 turn 完成后仅有自己的 2 条消息；
- 模型音频始终只在探针内统计并丢弃。

这证明生产 Gateway 的 lease、同 socket、多轮、reconnect journal 与 session 隔离子集。另做真实 HA restart：Qwen 容器保持运行且不重启，待 HA tools/list 恢复后，同一个既有 MCP client 再次成功调用 `GetLiveContext` 并完成模型回答，说明运行中的 HA 重启可以恢复；需要启动门处理的是 Qwen 冷启动阶段的一次性发现 race。B8.6 单元/集成回归仍覆盖问号意图、失败默认关闭、工具中间 response、并行工具、generation/播放打断、handoff/gate 等软件状态机。

## 8. 回滚与启动时序演练

最终 Step 10 使用 pre-deploy 备份做真实 rollback → verify → redeploy：

- rollback：恢复 HA auth pre-state、旧 Tivoo integration、Qwen Compose/config.env/原 Prompt，移除 Frontend MCP config、B8.7 runtime mounts 与启动门；专用 `Tivoo Qwen MCP` 用户不存在，旧 token 返回 401，Qwen health 回到 `frontendMcp tools=0 / servers=0`；
- redeploy：恢复专用用户/token、当前 Tivoo integration、Frontend MCP config、B8.3/B8.5 runtime patches、Prompt overlay 与启动门；专用 token 返回 200，最终 `frontendMcp.ok=true / tools=46 / homeassistant=ready`，Prompt 2762 chars；
- 最终演练输出：`ROLLBACK_PRESTATE_PASS`、`REDEPLOY_FRONTEND_MCP_READY tools=46 promptChars=2762`、`ROLLBACK_REDEPLOY_PASS`，exit 0。

第一次 rollback 演练暴露了部署 readiness 过早的问题：只等 `/api/` 返回 401 不足以证明 `/api/mcp/assist` 和完整工具目录已稳定。该失败没有被当作 PASS，并由上述启动门修正后重新完整演练通过。

## 9. 硬件 GAP

NAS 当前只枚举 `/dev/ttyACM0`。在任何写入前用 esptool 自动识别得到：`ESP32-D0WD-V3 rev 3.1`，MAC `58:2a:bd:d5:4c:90`，即旧 ESP32 classic，不是 ESP32-S3。HA 7777/7778 也实际连接 `192.168.3.28`，HELLO 为 `0.1.0+e306476`。

尝试以 `--chip esp32s3` 执行 read_flash 时，esptool 在芯片类型检查阶段报 `This chip is ESP32 not ESP32-S3`，在任何 flash read/write 前退出；没有修改 Flash。没有 S3 serial port 可用，因此当前 HEAD S3 app 未刷写，不能验证：

- 真实 S3 24 kHz → 32 kHz native SRC；
- Qwen PCM HTTP → S3 → DAC → Tivoo AUX 的物理播放 completed；
- 真实播放期间 barge-in、物理 completed 后问号 4 秒 follow-up；
- S3 disconnect/restart、双麦/AFE 与本迁移路径的整机时序。

这些全部保持 **HARDWARE GAP**，不能由 classic 板、host SRC 测试或 Gateway `audio.done` 代替。

## 10. B8.7 计划核销状态

| Step | 状态 | 证据/说明 |
|---|---|---|
| 1 focused regressions | PASS | HA/Qwen、B8.2、B8.3、B8.5、ESP32 host、双 target clean build 均通过 |
| 2 no-legacy-call assertions | PASS（软件） | Qwen local branch 直接走 Qwen Bridge；6 个专项测试调用旧 pipeline/STT/TTS 即失败且全部通过；旧实现保留到 B9 |
| 3 NAS pre-deploy backup | PASS | 完整备份与 active mounts/config 检查完成 |
| 4 production tools/list | PASS | 专用非 admin 用户；54 real tools；完整 schema 已保存 |
| 5 install Frontend MCP config | PASS | persistent config/env/patch 安装，token 不入 JSON |
| 6 running Gateway config | PASS | health ready，homeassistant ready，46 tools；冷启动启动门等待真实 tools/list 46/46 后才启动 Gateway |
| 7 live MCP calls | PASS | GetLiveContext 真模型读调用 PASS；ShowText 真模型写调用及 transport dispatch PASS；invalid auth 401；owner 空闲 |
| 8 actual device E2E | GAP | ESP32-S3 未连接/未枚举，禁止拿 classic 替代 |
| 9 lifecycle scenarios | PARTIAL/GAP | 生产 same-socket/reconnect/lease/session 隔离、HA restart 后既有 MCP client 继续调用、Qwen 冷启动 race 自动恢复均 PASS；依赖物理 playback/follow-up/barge-in/S3 disconnect 的场景 GAP |
| 10 rollback | PASS | 真 rollback 回到 0 tools/旧 token 401，再 redeploy 到 46 tools/token 200/Prompt 2762 chars，最终 exit 0 |
| 11 Prompt/persona/memory persistence | PASS | active runtime paths、2762-char Prompt、persistent ASSISTANT/USER/MEMORY 已核对 |
| 12 honest report | PASS | 本报告明确拆分软件/NAS PASS 与 S3 HARDWARE GAP，不放行 B9 |

## 11. 最终审查

B8.7 最终 diff 按设备上的 `review-agent` 只读规则人工复核：检查完整 tracked/untracked 变更、启动门与 Compose 调用关系、B8.3 runner 批次边界、计划核销和本报告的 PASS/GAP 表述；未发现可执行的 correctness/security/maintainability finding。最终本地门在审查前重新执行：启动门 3/3、B8.3 198/198、B8.5 100/100、shell/node syntax 与 `git diff --check` 全部通过。

另一次最终 `codex review --uncommitted` 已发起，但设备侧 Codex 额度在审查过程中耗尽并以 exit 1 中断，未产生 finding 结论，**不计为独立审查 PASS**。更早、尚未加入冷启动门之前的 uncommitted diff 曾独立审查无 finding；本报告不把该旧结果替代最终 diff 的独立审查。

## 12. Release gate

**B9 仍 HOLD。** Step 7 controlled write 与 Step 10 rollback 已通过；剩余阻塞仅是 Step 8/9 所需真实 ESP32-S3 物理音频/打断/续聊证据缺口。B9 必须保持独立用户授权批次，且只有真实 S3 hardware acceptance 补齐后才能放行。

## 13. 2026-11-23 自动声学延迟校准

**本轮校准 PASS，已刷入真实 S3；不据此核销整项 B8.7。** 用户确认 DAC 已可出声后，在当前音量、麦克风位置及 AUX 布置下，通过已有的一次性 P68TRACE 接口和临时本地播放刺激测量。没有制造 MIC session、唤醒事件或播放完成事件；没有开启 `TIVOO_P68_TEST_GATE`。

### 实测方法与结果

临时测量固件在四个独立 4 秒窗口内，分别播放 100 ms、400–3600 Hz 扫频标记及 `ready_01/02/03/followup_01` 原始嵌入资产。同步记录最终 TX reference、双麦原始 RX 和 AFE enhanced PCM，保留各自绝对样本索引。标记和资产均真实写入输出队列并 drain，播放日志没有 underrun、missed EOF 或失败。

- 四组原始采集各 800 块，AFE 各 125/125/125/124 块；全部样本索引连续、reference valid、trace dropped=0。AFE 为独立异步 32 ms fetch，4 秒窗口可排除一个边界块；末组 124 块覆盖 3.968 秒，不是中间丢帧。
- 四次扫频的 TX→RX 相关峰完全一致：左路 1603、右路 1602 个 32 kHz 样本，即 50.09375/50.0625 ms；相关系数绝对值 0.749–0.845，均反相。共同参考取 800 个 16 kHz 样本（50 ms），没有分别移动两路麦克风或修改极性来抹除空间信息。
- 四组双麦原始时钟→AFE 输出索引的互相关偏移均为 **+519** 个 16 kHz 样本（32.4375 ms），相关系数 0.222–0.550。TX→enhanced 的直接相关在 AEC 适应后很弱，不以其低置信峰值代替索引映射；使用保留绝对索引的 raw→enhanced 关联，避免把声学传播延迟重复加进 AFE 偏移。
- 独立扫频标记在数字 drain 后的可检测尾音上界为 **672 个 16 kHz 样本（42 ms）**。实际四个提示音资产在其保守数字 drain 后未检出超过阈值的额外残留。选择 **1600 样本（100 ms）** 安全尾音，较本轮最大可检测标记尾音多 58 ms。
- 尾音不是“绝对无声”证明：原始提示音使用 10 ms RMS、阈值为前置背景 RMS 的 99 分位数三倍与峰值 RMS 的 1% 两者较大值；扫频尾音使用 5 ms RMS、前置背景 95 分位数三倍。背景变化及低于噪声阈值的残响不计作精确零。该校准对应当前实际装配和音量，未验证不同音量、双讲或真人近端保留质量。

结果与重放工具：[校准汇总](evidence/2026-11-23-p68-calibration/measurement-result.json)、[严格检查](evidence/2026-11-23-p68-calibration/verify_measurements.py)、[原始完整采集 gzip](evidence/2026-11-23-p68-calibration/round2.log.gz)、[采集工具](evidence/2026-11-23-p68-calibration/capture.py)、[窗口拆分](evidence/2026-11-23-p68-calibration/split.py)、[索引/相关分析](evidence/2026-11-23-p68-calibration/analyze.py)、[尾音分析](evidence/2026-11-23-p68-calibration/metrics.py)。每组 `round2-assetN.analysis.json` / `.metrics.json` 保存实际数值。原始采集压缩前后逐字节核对，派生大文件已删除，可从 gzip 解压后重建；分析依赖 NumPy/SciPy。合成索引数据已验证相关符号和已知延迟恢复，见 [分析验证](evidence/2026-11-23-p68-calibration/analysis-validation.txt)。首轮串口波特率未同步的无效采集不计入以上四组。

### 已安装配置与正常固件复验

当前私有 `esp32/firmware/sdkconfig` 已设置，板级测量值另存 [非秘密配置快照](evidence/2026-11-23-p68-calibration/measured-settings.txt)，没有覆盖通用未校准 defaults：

| 配置 | 当前值 | 单位/作用 |
|---|---:|---|
| `TIVOO_AEC_REFERENCE_DELAY_SAMPLES` | 800 | 16 kHz 样本，50 ms |
| `TIVOO_P68_PROMPT_AFE_OFFSET_SAMPLES` | +519 | 物理采样时钟→AFE 索引，32.4375 ms |
| `TIVOO_P68_PROMPT_TAIL_SAMPLES` | 1600 | 数字 drain 后安全余量，100 ms |
| `TIVOO_P68_PROMPT_CALIBRATED` | y | 真实测量前置条件已满足 |
| `TIVOO_P68_TEST_GATE` / `TIVOO_P68_CALIBRATION_TRACE` | n / n | 正常固件无测试 bypass 或音频追踪 |

临时刺激、任务栈和串口提速修改均已撤回；`p68_trace.c` 与本轮开始前逐字节一致。[临时测量 patch](evidence/2026-11-23-p68-calibration/temporary-stimulus.patch) 仅作证据。正常 app 构建成功，SHA256 为 `00359440fa199e9a9e172162c2baeae8f335743bbfdef2f8b2e20c15677288af`；只刷 S3 `/dev/ttyACM1` 的 `0x10000` app，esptool 确认 Hash verified，未擦除 NVS 或改动模型/分区。

最终正常固件 **90 秒启动日志，8 份 telemetry 覆盖 70.12 秒，严格检查 PASS**（显式要求 `--min-runtime-seconds 60`）。feed/fetch 持续增长，feed/fetch errors=0、reset=0、capture overrun=0、missed EOF=0；rx_gaps=1、ISR overruns=40 为启动期累计值，观测期间没有增长。internal_min=29256、largest=20480 bytes。真实 TCP HELLO 宣告 `local_wake_stt_v1`，PING/PONG、GET_STATUS 成功，Wi-Fi `.40` connected，SPP connected、audio resource idle。定向 trace/prompt/AFE/turn 软件回归 **11 passed**；`git diff --check` 通过。

证据：[正常构建](evidence/2026-11-23-p68-calibration/candidate-normal-build.txt)、[刷写](evidence/2026-11-23-p68-calibration/normal-flash.txt)、[正常启动](evidence/2026-11-23-p68-calibration/normal-boot.txt)、[严格启动判定](evidence/2026-11-23-p68-calibration/normal-boot-result.json)、[真实状态](evidence/2026-11-23-p68-calibration/normal-status.txt)、[定向回归](evidence/2026-11-23-p68-calibration/focused-tests.txt)。本轮没有迁移 HA 目标地址或执行真人 turn；Step 8/9 和 B9 保持未通过，接下来仍须真实 wake→prompt→Qwen→AUX、播放中打断及 matching completed 后的问号续聊实测。
