# P6.5 Patch — HA Assist Pipeline / TTS Proxy 取消链路前置验证

- **状态：** 待执行；P7/P8 取消逻辑实现前的必做验证批次
- **插入位置：** `README.md §10 实施顺序`，P6 之后、P7 之前
- **目标版本：** 项目固定的 Home Assistant Core 2026.11.0
- **任务性质：** 只验证、追踪和记录，不在本批次修改生产取消逻辑

## 1. 目的

在实现 Tivoo Assist Satellite、音频会话协调器和设备播放管理器的取消行为之前，先确认 HA Core 当前实际的任务取消传播路径：

`AssistSatelliteEntity` 外层任务
→ Assist Pipeline
→ Conversation Agent / AstrBot SSE
→ HA TTS Proxy（ResultStream / TTSCache 后台生成任务）
→ HA Wyoming TTS Provider
→ Wyoming TCP 请求
→ P7A Sherpa TTS 请求与 callback worker。

当前源码审查已发现一个需要验证的风险：HA Pipeline 的失败清理会删除 TTS ResultStream 的 token 映射；TTS Proxy 的音频缓存生成任务则由 HA 后台任务独立运行。仅观察到 Pipeline 任务结束或 HTTP GET 消费端关闭，不能证明缓存生成任务、文本流生成器和 Wyoming 合成任务一并结束。

本批次要用可控测试确认每一层任务的实际终止行为，并确定缺口由哪个组件持有和修复。**测试结果是后续 P7/P8 取消逻辑的架构依据，不预先假定 TTS Proxy 一定随 Pipeline 取消。**

## 2. 边界

### 本批次包含

- 使用真实 HA Core 2026.11.0 的 Assist Satellite 基类、Assist Pipeline、TTS Proxy 和 Wyoming Provider 代码。
- 使用测试 Satellite Entity 走公开的 `async_accept_pipeline_from_satellite()` 入口；不要求本批次先实现生产版 `tivoo.assist_satellite`。
- 通过测试事件屏障控制取消时机，分别观察 LLM/SSE 尚未结束、TTS Proxy 已启动、HTTP 音频 GET 正在消费时的任务状态。
- 对接本地测试 Wyoming TCP Server / P7A Provider 实现，追踪 TCP EOF、请求清理、callback 停止及迟到 PCM。
- 复用 P3 现有 Conversation Agent 取消行为，验证 SSE reader 关闭和同一 owner session 的 Stop 调用。
- 记录正常完成、Pipeline 取消、HTTP GET 消费端单独断开三种情况的差异。

### 本批次不包含

- 不实现或修改 `homeassistant/custom_components/tivoo/` 的生产模块。
- 不修改 HA Core 源码，不通过 monkey patch 或调用 HA 私有方法实现生产取消。
- 不改 P3 AstrBot API/session 合同或 P7A Wyoming Provider；只有测试证据明确指出缺陷时，才在后续独立任务中安排对应修复。
- 不接真实 ESP32、INMP441、AEC、DAC/AUX 或执行 TCP 7778 硬件联调。P6 已完成 7778 双向通信及 HTTP 资源获取；真实 I²S/AFE/VAD/MIC_PCM 与 Assist Satellite 接入属于 P7，解码和 DAC/AUX 播放属于 P8。

## 3. 测试批次

建议新增单一 HA 集成测试文件：`tests/homeassistant/test_assist_pipeline_tts_cancellation.py`。测试可 mock AstrBot HTTP 端点及 Sherpa 推理引擎，但 HA Pipeline、TTS Proxy、Wyoming Provider 和 P7A 请求处理必须运行真实项目/HA 代码。

### P6.5b0 — 固定环境与任务所有权清点

- 确认测试运行的 HA Core 版本为 2026.11.0，并记录对应依赖版本。
- 以当前安装源码为准，标出以下任务的创建者、持有者、取消入口和清理函数：
  - Satellite 调用者任务及 HA 基类的 Pipeline task。
  - Pipeline processor、TTS ResultStream、TTSCache 后台 producer 和文本流 generator。
  - Wyoming TTS 的连接处理任务与 `_write_tts_message` 请求任务。
  - P7A TTS 请求状态、PCM callback 和 worker。
  - P3 Conversation SSE reader 与 AstrBot session Stop。
- 不把源码推测写成实测结论；每项都需要在后续测试中获得对应的任务结束/取消证据。

**产出：** 测试中的任务追踪表和 HA Core 版本基线。

### P6.5b1 — 正常完成控制组

- 通过测试 Satellite Entity 启动一次可完整结束的流式 Pipeline。
- 确认 AstrBot SSE、TTS 文本流、TTS Proxy、Wyoming 请求和 P7A 合成按正常结束顺序收尾。
- 确认没有遗留后台任务，且正常完成不会误触发 AstrBot Stop。
- 记录 TTS Proxy token、缓存 producer 和 Wyoming 请求的开始/完成位置，供取消组对照。

**验收：** 得到一条正常完成的任务生命周期基线；否则先修正测试夹具，不进入取消结论。

### P6.5b2 — TTS 开始前取消

- 让 AstrBot SSE 响应保持打开，并用事件屏障确认 Conversation Agent 正在消费 SSE。
- 取消调用 `async_accept_pipeline_from_satellite()` 的外层任务，并等待取消传播完成。
- 验证 Pipeline task 结束、SSE reader 被关闭、P3 对同一 session_id 最多调用一次 Stop。
- 验证尚未创建的 TTS Proxy / Wyoming 请求不会在取消后迟到启动。

**验收：** 外层 Satellite 调用者、Pipeline 和 P3 对话流的状态均有明确结果；取消异常按约定继续传播，不被转换为正常完成。

### P6.5b3 — TTS Proxy 活动期间取消

- 启动实际 HA 流式 TTS 路径，等待 TTS Proxy token 已创建、后台缓存 producer 已开始，并让 HTTP GET 消费端处于读取状态。
- 在 Wyoming TTS 请求已建立、callback 正在等待/输出可控 PCM 的位置设置事件屏障。
- 取消 Satellite 外层 Pipeline 任务并等待其完成。
- 分别检查以下对象是否真正退出，不能只检查 ResultStream token 是否被删除：
  - Pipeline processor 与 TTS ResultStream。
  - TTSCache 后台 producer task。
  - `tts_input_stream_generator` 及其队列等待。
  - HA Wyoming `_write_tts_message` 和连接读写任务。
  - P7A 对应连接、请求、callback 和 worker。
- 取消后再次尝试推进测试 PCM/文本，确认不会产生迟到音频块或让旧请求继续合成。

**验收：** 对每个任务记录 `done/cancelled/pending`、退出原因和资源 owner。只删除 URL/token 映射不算生成任务已取消。

### P6.5b4 — HTTP 消费端断开对照组

- Pipeline 与 TTS Proxy producer 保持运行，只关闭 HTTP GET 消费端。
- 独立观察缓存 producer、文本流 generator、Wyoming TCP 和 P7A 请求是否继续运行。
- 随后再执行 Pipeline 取消，确认两种事件不会被混为一谈。

**验收：** 明确区分“客户端停止下载”和“上游 Pipeline/合成任务取消”；不能用 HTTP 断开推断 TTS 推理已经停止。

### P6.5b5 — 汇总与模块边界决策

生成报告：`docs/superpowers/reports/2026-11-11-ha-cancellation-preflight-report.md`。报告必须包含环境版本、测试命令、关键事件时间线、被追踪任务及 owner、每条链路的 PASS/GAP/BLOCKED 结果，以及对后续模块的具体决策。

## 4. 结果如何决定后续模块取消逻辑

| 实测结果 | 后续归属与处理 |
|---|---|
| 取消 Satellite 外层任务能取消并等待 HA Pipeline task | `tivoo/assist_satellite.py` 只负责通过公开入口持有并取消/等待当前 Pipeline run；不复制 HA 的 Pipeline 调度器，不调用私有取消方法。 |
| Pipeline cleanup 同时结束 TTSCache producer、文本 generator 和 Wyoming 请求 | 不新增 TTS Proxy 专用取消层；`tivoo/audio_session.py` 负责会话级取消编排和等待即可。 |
| Pipeline 已结束，但 TTSCache producer / 文本 generator 仍 pending | 记录仍存活任务的准确 owner 与可访问句柄。后续必须在实际拥有该 producer 的 TTS Proxy/资源边界补充定向取消能力；不能把泛化的 `asyncio.all_tasks()` 清理或 `audio_session.py` 中猜测任务名当成修复，也不能把删除 token 当成取消生成。若 HA 没有可用的受支持取消接口，先形成单独设计决策，不在 P7/P8 中偷偷绕过。 |
| HA Wyoming 连接关闭后 P7A 请求、callback 和 worker 均结束 | 保持 P7A 当前请求级取消实现，不重复添加另一套停止协议。 |
| Wyoming TCP 已关闭但 P7A 请求仍存活 | 后续修复放在 `services/sherpa_wyoming/providers/tts.py` 的请求/断连边界，并增加连接级回归测试；不把此责任塞入 HA Tivoo 集成。 |
| P3 SSE reader 关闭且同一 session Stop 正确执行 | 保持 `astrbot` 为 AstrBot 会话 Stop 的唯一 owner；`tivoo` 只取消 Pipeline，不直接调用 AstrBot API。 |
| P3 SSE / Stop 未按预期结束 | 在 P3 的 `conversation.py`、API 或 session 边界单独修复；不能在 Tivoo 协调器中复制 P3 Stop 逻辑。 |
| `tts_response_finished()` 只改变 Satellite 状态 | 保持其为响应状态收尾动作；它不能替代 Pipeline、TTS Proxy、Wyoming 或 AstrBot 的取消。 |

无论测试结果如何，后续职责边界保持：

- `tivoo/transport.py`：接收和发送设备事件、传输层断连；不持有 AstrBot/TTS 生成任务。
- `tivoo/assist_satellite.py`：Assist Satellite 实体及 Pipeline 公开入口生命周期。
- `tivoo/audio_session.py`：音频会话关联、取消幂等、等待旧 run 收尾；新 barge-in PCM 使用有界缓冲，旧任务未收尾前不得启动新 STT Pipeline。
- `astrbot`：P3 SSE reader 与 owner session Stop。
- `services/sherpa_wyoming/providers/tts.py`：单个 Wyoming TTS 请求及 callback 的断连/取消清理。
- ESP32 `audio_output_manager`：最终输出层立即停止所有受控音频；不能等待 HA 或模型服务取消后才停止扬声器。

若 P6.5 发现 HA TTS Proxy 存在脱离 Pipeline 的后台任务，P7 可以继续实现麦克风接入和非打断路径；依赖该缺口的 HA 端完整打断/取消验收与 P8 收尾必须保持 BLOCKED，直到单独确定并验证正确的取消 owner。

## 5. 测试执行与通过门槛

在 ARM Ubuntu 开发设备运行，不需要在 NAS 上执行容器构建，也不需要真实 ESP32：

```bash
./scripts/test-ha.sh tests/homeassistant/test_assist_pipeline_tts_cancellation.py
./scripts/test-ha.sh tests/homeassistant/custom_components/astrbot/test_conversation.py
./scripts/test-ha.sh tests/services/sherpa_wyoming/test_tts_stream.py tests/services/sherpa_wyoming/test_server.py
git diff --check
```

测试应以 `asyncio.Event` 等可控屏障等待任务进入指定状态，不使用固定 `sleep` 猜测时序。可在测试中包装 HA 后台任务创建和连接边界收集任务证据；不得因此增加生产监控框架或修改 HA Core 源码。

**P6.5 通过门槛：** 所有控制组和取消组均能稳定复现；每个任务都有明确的 owner、退出状态和证据；如存在 GAP，必须准确定位到仍存活的任务以及后续修复边界。未完成任务归属判定时，不得宣称取消链路已验证通过。

## 6. 权威依据

- `docs/superpowers/specs/2026-11-09-esp32-ha-bidirectional-communication-design.md` §7.4、§8、§13、§14。
- `docs/superpowers/specs/2026-11-09-stt-tts-end-to-end-pipeline-spec.md` §7–§10。
- `docs/superpowers/specs/2026-11-09-p3-astrbot-conversation-contract-matrix.md` 的 SSE/Stop 取消合同。
- `docs/superpowers/specs/2026-11-10-p7a-sherpa-wyoming-contract-matrix.md` §9.7 的 Wyoming TTS 请求取消合同。
- 当前开发环境中 HA Core 2026.11.0 的 Assist Satellite、Assist Pipeline、TTS Proxy 和 Wyoming TTS 源码。
