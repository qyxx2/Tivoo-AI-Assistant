# P6.8 B8.7：未提交修复后仍无回答的诊断与解决方案

日期：2026-11-23，Asia/Shanghai。检查窗口：初查 21:17–21:25；真人复现及事件回放 21:32 起。分支 `feature/p6-8-s3-local-wake`，HEAD `a4469d7`，以现有 dirty 工作区为基线。

## 1. 最终结论：真人复现已定位 HA 对正常 playback.clear 的误处理

**21:32:55–21:32:59 已完成真实唤醒复现，用户确认“已说完，无回答”。直接根因是 HA `qwen_realtime.py:471–479` 将首次语音起始时的正常 `playback.clear(reason=user_interruption)` 无条件当作致命撤销。** Qwen 已识别语音起始，HA 随即抛错、关闭连接并让 S3 停止，模型没有机会完成这轮回答。

此前 21:25 的“优先检查输入是否有效”只是针对旧日志的初步方向；这次新证据推翻了把它当作本轮主因的判断。旧会话缺少完整日志，不能反推所有历史失败都由同一原因造成。下面第 3–6 节保留早期分析与声学验证备选；**本次应优先采用第 8 节协议修复方案，不先调整音量、VAD、队列或任务布局。**

证据闭环：

1. 真人 S3 session `4c59f184-4a0d-4f50-8efb-c40b158e3ea2`：WakeNet 命中、提示音 drained、gate completed；无新增 AFE gap/reset/overrun；最后 outcome=`ha_stop`，send_failures=0。
2. HA generation `01M849R4JFWPRC8BPBX5FF47E9`：`input_bytes=55040`、`output_bytes=0`、voice_ready=376 ms；21:32:59.442 抛 `RuntimeError: Qwen response delivery was revoked`，堆栈指向 `_handle()` 第 479 行；retire reason=`pipeline_failed`。未记录 input_eof，说明这次在输入尚未完成时被终止。
3. Qwen：21:32:59.437 记录 `realtime.provider.speech_started`，21:32:59.444 客户端断开。不是云端完全没检测到讲话。
4. 现场安装的 `realtime-input-runtime.mjs` 中 `#startSpeech()` 在 accepted 的首次起音也依次发送 `playback.clear(reason=user_interruption)` → `turn.started` → listening，没有“必须已有回复”的条件。
5. 对当前真实 Gateway 再跑清晰语音探针并只记录事件元数据，直接观察到同样的 clear → turn.started 顺序，随后可完整回答。
6. 将该真实 clear 事件直接传给工作区真实 `QwenRealtimeBridge._handle()`，在尚无 turn/stream/playback、output_bytes=0 的 owner 上，稳定复现相同异常，进程 exit=1。

**最新未提交改动没有修改 `_handle()` 的无条件撤销分支。** 它们修通了音频到达云端的前置条件，而正常语音一旦触发云端 speech_started，就暴露这个既有协议适配错误。强制 VAD 上送的环境声没有触发云端 speech_started 时，恰好无法覆盖此缺陷。

## 2. 实际部署核对

| 层 | 本轮现场结果 | 限制 |
|---|---|---|
| NAS | `root@192.168.3.94` SSH 成功 | 未重启 NAS |
| HA | `ghcr.io/home-assistant/home-assistant:2026.11.0`，running；Tivoo host=`192.168.3.40` | 不是旧报告中的 `.28` |
| HA audio_session.py | 本地/部署 SHA256 均 `07ffbede7473de8a63e497bca8463ceb6f98c396506790a37f0319923f1cc6af` | 3840 B 合包支持已部署 |
| HA qwen_realtime.py | 本地/部署均 `af557a2404a810032533f93cbbf2863bf4583d088284deff89b31049ec1e9e35` | 本轮无代码替换 |
| HA transport.py | 本地/部署均 `40d8e90c6f4a6808a72d810236b8e577db67dc768f9814146194581f9ade4646` | 同上 |
| S3 app 产物 | 本地 build 与 NAS `p68-b87-batch-wdt-normal-20261123.bin` 均为 `c9276f0c2e4717e9b0de5280a71346d498ce41b7c8860b1dcbef361f3c2691e4` | 结合既有刷写记录判断部署；本轮没有重新读 Flash，不能将文件 hash 冒充芯片回读 hash |
| S3 运行 | 串口 uptime 约 3.2 小时；feed/fetch 递增，`rx_gaps=1`、`resets=0`、`overruns=40`、`capture_overruns=0`、`missed_eof=0` 保持稳定 | 证明观测期间采集连续，不证明语音内容有效 |
| Qwen | `local/qwen-audio-agent:2.1.0`，running；当前 provider=`dashscope`，model=`qwen3.8-omni-flash-realtime`，模型默认 turn detection=`semantic_vad_ec`；health ready | 模型默认值来自实际 health，不据此推断所有运行时参数 |
| Qwen MCP | health 46 tools；现场 MCP initialize HTTP 200、有 result、无 error | 本轮没有触发家居写操作 |

Qwen 运行文件 hash：

- `shared/protocol/gateway-events.mjs`：`c6ecf314700b474abcaf2e78d235f618e99b3493fc729e4e92671f23985650f7`
- `server/src/voice/realtime-presentation-runtime.mjs`：`1f7e8ec9d253ceaacc81b73b8becfbc06685e5dcc9e5418787b5ee6c7fe7b28b`
- `shared/protocol/gateway-client-protocol.mjs`：`fba6286d46ba3201d6516002a3d54c81043779e9196549ed3c42d1f54cb7a828`

旧报告里的 AFE 初始化 OOM、HA 指向旧板、压力固件 WDT/DMA 错误，不能直接拿来解释当前正常固件的最新失败。

## 3. 最新故障证据与未提交修改的覆盖范围

### 3.1 初查时的历史生产会话（21:13；后续真人复现见第 1、8 节）

从持久 `gateway.log` 和容器日志核对，生产 session `01M70NVPJ77QKP212ZMMTZHRSV`：

- 21:13:06.654：voice_client.connected。
- 21:13:07.188：realtime.connected，连接耗时 483 ms。
- 21:13:55.630：voice_client.disconnected，closeCode 1000。
- 其间没有 `realtime.provider.speech_started`、`speech_stopped`、`realtime.response_started` 或 `realtime.response.done`。
- 19:15:59 起的另外三次生产连接也只有连接/关闭事件。该 session 的消息历史为空。

同一运行实例会为本轮清晰语音对照记录 speech_started/stopped、response_started/done，因此不是这些事件在该运行版本中完全不记录。

49 秒连接寿命与 HA `EVENT_TIMEOUT=45` 加输入处理时间相容，但**没有当轮异常栈，不能断言就是这个超时**。closeCode 1000 只说明 WebSocket 正常关闭，不说明回答成功。

### 3.2 修改为何不足

| 未提交改动 | 实际解决边界 | 未解决/未证明 |
|---|---|---|
| s3_afe.c PSRAM 分配、独立 capture 队列、任务布局 | 初始化内存和持续采集 | 麦克风 PCM 幅度、SNR、双麦相位、AFE 增强后是否仍保有人声 |
| diagnostics.c 独立实时 TX、64 帧有界队列、入队前检查 | 发送积压与诊断线程干扰 | VAD 没有 START 时，队列根本没有命令 PCM 可发 |
| p68_local_turn.c 六帧合包 | 从 50 个小包/秒降低事务频率，尾包冲刷 | 合法包长/样本数量不等于有效人声 |
| HA audio_session.py 接受 640 B 整数倍 | 接受至多 3840 B 的当前合包 | 没有分析音频内容，也不会替代云端 VAD |
| 取消 CPU0 Idle WDT 默认订阅 | 避免已测压力情境下 Idle 饥饿触发回溯及后续故障 | 不降低 CPU 实际负载，更不能改善语音信噪比 |
| s3_local_turn.c 包装函数等 | 保留既有调用路径 | 没有新增真实 VAD 或声学诊断能力 |

此前 8 秒自动压力固件明确强制 Wake/VAD。它绕过了现在必须验证的识别条件；`input_complete` 只证明本地提交边界，不证明云端识别人声。既有报告已经把这一项保留为 HOLD，不应升级成“问题已修复”。

## 4. 本轮执行的复现和对照

### 4.1 真实 Qwen 清晰语音对照：PASS

复用仓库 `tests/integration/qwen_realtime/gateway_probe.mjs`，在现有 Qwen 容器内运行。凭据仅在 NAS 进程内使用，不写入本地报告。输入取仓库 `happy_today_sid41.wav`，转换为 16 kHz mono S16LE、20 ms 帧，尾部静音 1000 ms；独立诊断 session，不接管生产会话，不发送 TTS_PLAY。

结果：用户转写“今天我挺开心的。”；助手完整转写；20 次 audio.delta，共 299520 B；audio.done；无工具调用。第一帧输入到 response.started 4295 ms。日志同时出现 provider speech_started、speech_stopped、response_started 和 completed。

这排除了“当前 Qwen 完全不能识别中文/不能输出音频”的解释。它未经过 S3、HA bridge、HTTP PCM、DAC，不能证明这些环节正常。

### 4.2 真实 Qwen 静音输入：预期失败

同一探针，3 秒全零 PCM（96000 B）加 1000 ms 尾静音。退出码 1：`No non-empty user transcript.final`。

这是“有连接、有 PCM、无回答”的局部复现。说明字节数量通过仍可无回答；**没有证明实际麦克风输入为全零**。

### 4.3 当前 C 状态机差分：复现 command_timeout

临时 harness 直接链接当前 `p68_afe_flow.c` 和 `p68_local_turn.c`，使用完全相同的低幅非零样本，只改变传入的 VAD 决策。命令：

```bash
cc -std=c11 -Wall -Wextra -Werror -I esp32/firmware/main \
  /tmp/tivoo-no-answer/replay.c \
  esp32/firmware/main/p68_afe_flow.c esp32/firmware/main/p68_local_turn.c \
  -o /tmp/tivoo-no-answer/replay
/tmp/tivoo-no-answer/replay
```

实际输出：

```text
forced_vad=0 bytes=0 complete=0 reason=command_timeout
forced_vad=1 bytes=32000 complete=1 reason=none
```

第一组开 gate、ready 都正常，但没有有效 speech，最终零上送。第二组同样几乎没有声学信息的样本可完成上送。这准确展示了强制 VAD 压测的覆盖缺口；没有模拟真实 ESP-SR 算法判断，所以不是声学根因证明。

源码存为证据 `vad-contract-replay.c.txt`，可复制至临时路径后重跑。

### 4.4 针对性现有测试

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q \
  tests/esp32/test_p68_afe.py tests/esp32/test_p68_uplink_batch.py
```

**4 passed，2 个 pytest 配置 warning，0.90 s。** 这些是状态机/运行适配和合包回归，不是完整问答验收。

## 5. 原定真实复现流程（本轮已完成一次；后续用于修复验收）

在正常固件上连续三次执行：唤醒词 → 等“我在”结束 → “现在几点了”。记录距离与开始讲话时间，不能强制 VAD 或自动伪造 wake。

每轮以 S3 session UUID、HA generation、Qwen session/turn ID 关联以下证据：

1. S3 wake、prompt drain、gate sample/time、VAD START/END、valid/sent samples、最终 abort/outcome。
2. HA gate、speech_start、接收 PCM 总量、首末包时间、input_eof、output_bytes，以及异常类型。
3. Qwen speech_started/stopped、user transcript、response/audio 事件。
4. 若已产生音频，再记录 TTS_PLAY、HTTP GET 和 physical completed。

若 `command_timeout`、input_bytes=0：只排查 gate 后真实语音为何未成为 START；不要调查回复播放。

若 input_bytes>0、input_eof 已发生但没有云端 speech_started：采集同一轮短时原始双麦、AFE enhanced 和 HA ingress，计算 RMS/peak/非零率/削顶率/持续时间，并核对传输前后字节。可先测元数据，确需 PCM 时只保留短诊断片段。把 HA ingress 离线回放到同一 Qwen 与清晰样本对照。

若 cloud speech_started 有而 stopped 无：才进入端点/尾静音分析。若 audio.delta 有：才进入播放分析。

初查串口窗口只有空闲状态；21:32 后续真人复现已补齐 wake/turn 和 HA 异常，详见第 1 节。修复后仍需重复完整验收。

## 6. 初查备选方案（仅在协议修复后仍有相应症状时采用）

### 优先级一：把无回答定位到准确边界

保持已有吞吐修复，增加有界的诊断观测设计：一轮 gate 后 PCM 统计、VAD 状态和时间、上送确认；HA 记录“未开始输入/输入中断/输入完成但未识别/已生成未播放”的独立结局。不要只用 `success=False` 或笼统超时。

持续默认日志只留元数据；原始音频采集作为明确的一次性诊断模式，避免持续录音。所有时间标明设备样本时钟或主机单调时钟，跨端不能直接相减。

### 优先级二：按实测输入问题选择最小修复

| 实测结果 | 应修改位置与措施 | 必须通过的验证 |
|---|---|---|
| 原始双麦已有极低幅/单边无声/严重相消 | 检查 INMP441 左右槽与有效位转换、通道顺序、两麦几何与接线；仅依据原始样本调整幅度/配置 | 原始样本有清晰语音，左右通道各自有效且不削顶 |
| 原始双麦清晰，AFE enhanced 明显衰减/失真 | 检查 MMNR、参考对齐、BSS/AEC 配置与实际麦克风布局；一次只改变一个变量做声学 A/B | 同一句话增强后和 HA ingress 回放能触发 cloud speech_started 与正确转写 |
| enhanced 可识别，但本地不触发 START | 核查 gate 与 VAD reset 后有效帧时序、实际 VAD 决策和三秒窗口；先修时序错误，再以测量结果考虑阈值/窗口 | 自然讲话在窗口内触发；提示音尾音/静音不误触发；无跨 gate 音频泄漏 |
| S3 enhanced 正确但 HA ingress 不同 | 比对样本序列、有效样本数和边界，修实际发生的截断/错序/丢包 | 两端字节一致；持续上送不丢帧 |
| 云端已 START，END 后仍不停止 | 验证实际收到的 1 秒补静音及模型端点设置；只有接口允许时才设计显式 commit/response 控制 | 不重复提交、不抢断半句，短句和长句都能稳定结束 |
| Qwen 已返回音频但无播放 | 查 owner/session fence、HTTP PCM claim、SRC 和 DAC completed | 真实硬件发声及 completed，不能只靠 audio.done |

不建议先放宽 `command_timeout` 或增加软件增益：前者不能让无效音频变清楚，后者可能放大噪声和削顶。也不建议关闭本地 VAD 或把强制语音分支保留到生产。

### 优先级三：修正验收定义和失败反馈

- “持续采集”“输入提交”“云端识别”“生成音频”“实际播放”分别核销。
- 完整用例必须通过真实 WakeNet 和真实 VAD；至少覆盖自然起音、短句、长句、连续两轮、静音取消。
- 对未识别/无输入提供可区分的结束原因；提示音/交互策略可以随后设计，但不能借此掩盖识别失败。
- 自动压力只继续承担吞吐/稳定性回归；B8.7 完整问答、打断、续聊和 B9 保持 HOLD。

## 7. 操作范围与证据

本轮进行 SSH 检查、真人唤醒同步串口/HA/Qwen 观察、独立 Gateway 音频对照、MCP initialize 和本地状态机/事件回放测试；没有刷机、重启 HA/Qwen、修改生产实现或实现上述方案。原有工作区修改保留。

为现场观察，临时开启 Tivoo INFO；结束时恢复原先继承的日志级别。最初尝试用 MCP 专用凭据访问一般 HA logger API 得到 401，这是本轮诊断请求，不能当作生产模型失败根因；同一 MCP 端点 initialize 成功。后续在 HA 容器内使用已有认证状态签发短时凭据完成日志切换，未新增账户/长期令牌、未输出凭据。

第一段串口采集受到一次辅助打开串口默认波特率影响而含乱码，已丢弃；保留重新以 115200 采集的正常片段。未通过复位获取启动日志。

证据目录：[2026-11-23-p68-no-answer-analysis](evidence/2026-11-23-p68-no-answer-analysis/)。包括清晰输入真实 Qwen 响应、静音预期失败、生产/对照事件摘录、正常串口空闲观测及 C 状态机复现源码/输出。诊断用合成语音会话历史保留在 Qwen 独立 session，不混入生产 session。

## 8. 已定位根因的具体解决方案（仅设计，未实施）

### 8.1 修改边界与语义

修改目标为 HA `homeassistant/custom_components/tivoo/qwen_realtime.py` 的 `_handle()`，无需先修改 S3 固件或 Qwen provider。

将“清空已有播放”与“撤销当前输入所有权”分开：

- 对正常的首次起音 `playback.clear(reason=user_interruption)`，若当前 MIC owner 仍有效、尚未建立当前 Gateway turn，且没有当前 response、缓冲音频、已下发播放或待消费资源，应作为没有旧播放可清理的幂等事件处理，继续等待 `turn.started`，保留输入发送与 socket。
- 判断必须基于当前 owner 生命周期，不仅检查 `reason`，也不能仅检查 `output_bytes==0`：回复已开始但尚未收到音频时，也不应盲目当作首次起音。
- 不应以 `input_drained==False` 作为唯一放行条件：短句可能在云端开始识别前就已完成本地输入。应以“当前 turn/response/播放尚未建立”的语义判断。
- 当前 owner 已有响应或播放时，继续按现有取消合同清理它；`input.suspend`、`voice.deactivated`、实际 response.interrupted 和失去 generation 的事件仍必须终止，不得被新分支放行。
- 不要全局丢弃 playback.clear；不要去掉 Gateway 的 clear 事件。它在真正打断与播放清理时仍有作用。
- 同 socket follow-up 也会有新的初始 clear。必须确保旧 owner 音频资源已结束/清理，才允许新 owner 的初始空操作；保留 parent session、retired turn、generation 和物理 completed 的既有隔离。
- clear 本身没有 turnId，不能依靠不存在的身份字段做关联，也不能伪造 responseId。先以明确生命周期分类，再由后续 turn.started 建立身份。

该方案只解除误杀，不声称解除后所有声学/播放问题都消失；其余问题按实际新日志再分类。

### 8.2 为什么现有测试没发现

`test_qwen_realtime.py` 的 `response()` 成功路径直接从 turn.started 开始，遗漏了真实 Gateway 在此前发送的 playback.clear。已有 clear 测试在 output/playback 已建立后注入 clear，验证的是取消已有播放，不能覆盖正常首次起音。

应先补充真实顺序的回归，再实施最小修复：

1. voice.ready → 初始 clear(user_interruption) → turn.started → 用户转写 → response/audio → physical completed，应完成一轮，clear 不关闭 socket、不取消 MIC。
2. 本地输入已结束但云端首次 turn 尚未来到时，初始 clear 仍按同样合同处理。
3. 没有音频但已有 response.started 的 clear、已有缓冲但未下发 TTS 的 clear、正在播放的 clear，分别验证清理与失效，不能被初始分支误放行。
4. 初始 clear 后紧随 input.suspend/voice.deactivated，仍终止且不遗留资源。
5. 同 socket 合法 follow-up 的首次 clear 保留新 owner；旧代际的延迟事件不能清理或复活新代际。
6. 成功路径 fixture 默认包含真实初始 clear，防止后续单元测试继续模拟错误协议顺序。

### 8.3 本轮确定性失败回放

证据 `replay-initial-clear.py.txt` 直接导入真实 HA 模块，构造尚无回复/播放的 owner，并调用原方法。不是复制分支逻辑，也没有修改模块：

```bash
PYTHONPATH=homeassistant .venv/bin/python /tmp/tivoo-no-answer/replay-initial-clear.py
```

实际 exit=1，报错 `RuntimeError: Qwen response delivery was revoked`，与实机 HA 堆栈同一行。临时 owner 仅用于隔离该前置分支；它不是完整 async_run 成功测试，正式回归应按 8.2 使用完整 owner 和 socket fixture。

真实 Gateway 元数据摘录：

```text
voice.ready
playback.clear reason=user_interruption
turn.started turnId=voice-1795440954832-1
voice.state
transcript.delta ...
```

独立 Gateway 探针在此顺序下仍成功完成问答，进一步把故障定位到 HA 的事件解释，而不是 Gateway 必然无法回答。

### 8.4 实施后实机验收与当前状态

后续实施时先部署最小 HA 修复并保留回滚副本，再用本轮相同固件重复真人“现在几点了”。要求：同一 generation 从 input_eof 到正确转写、output_bytes>0、TTS_PLAY、HTTP PCM 获取、真实听到回答和 physical completed 全部成立。继续做真实播放中打断及条件续聊，证明正常 clear 放行没有削弱取消。

本轮只更新分析及证据，没有改 HA/S3/Qwen 实现，没有宣称已修复。真实故障已复现，直接根因已定位，修复验证尚未实施。临时 INFO 在采集结束后恢复 NOTSET（继承原级别）；未重启或刷机。

## 9. 本次修复实施结果（21:42 后）

已按第 8 节实施最小 HA 协议修复，仅修改 `homeassistant/custom_components/tivoo/qwen_realtime.py` 与对应回归测试；未修改或刷写 S3 / Classic 固件，也未调整 VAD、AFE、队列、超时或 Qwen Gateway。

`_handle()` 现在只在当前 MIC owner 尚未建立 Gateway turn、response、PCM stream、playback/dispatched/final response，且事件为 `playback.clear(reason=user_interruption)` 时，将其作为首次起音的幂等空清理事件继续处理。已有 turn/response/缓冲/播放状态下的 clear 仍撤销当前 owner；`input.suspend`、`voice.deactivated`、`response.interrupted` 仍保持致命撤销语义。该判断不依赖 `input_drained`，因此本地输入已结束但云端首次 turn 尚未来到的短句也允许通过。

测试先观察到旧实现的确定性 RED：真实协议顺序加入成功 fixture 后，基础完整回答与“本地 EOF 后首次 clear”均因旧无条件撤销失败。修复后针对性 6/6 通过；随后 Qwen realtime/lifecycle/satellite/P6.8 local-session 相关回归 104 passed。fixture 按真实协议改为每个新 `turnId` 只注入一次首次 clear，因此同一 turn 的工具后续 response 不会伪造第二次首次 clear，而同 socket follow-up 的新 turn 会再次覆盖该事件。

NAS `192.168.3.94` 已部署同一修复文件并重启 HA。部署前文件 SHA256 为 `af557a2404a810032533f93cbbf2863bf4583d088284deff89b31049ec1e9e35`，备份为 `/volume1/docker/homeassistant/config/custom_components/tivoo/qwen_realtime.py.bak-20261123-initial-clear`；部署后 SHA256 为 `645e452fafcc1ae8a6eabca93d854dac51165e697a3f680099586fe58fa21638`，与工作区一致。HA 重启后 `http://127.0.0.1:8123/` 返回 200，启动窗口未见 Tivoo/Qwen traceback/error，`qwen-audio-agent` 保持运行。

本次没有用强制 VAD、伪造 wake 或测试固件替代自然语音验收。修复针对 21:32 真人复现已经证实的 HA 协议误杀根因；完整自然 WakeNet → VAD → Qwen → 物理播放的 B8.7 其它 gate 仍按原计划独立核销，不在本修复范围内。
