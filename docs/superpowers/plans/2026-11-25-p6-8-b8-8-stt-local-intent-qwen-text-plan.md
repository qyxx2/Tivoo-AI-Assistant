# P6.8 B8.8 STT Local-Intent Qwen Text Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前 P6.8 的本地语音输入改为 `S3 PCM → Sherpa device-endpoint STT → HA local-first → local miss 才提交 Qwen 文本`，同时保持现有 Qwen 音频输出链和 S3 固件不变。

**Architecture:** S3 继续上传现有 16 kHz mono S16LE PCM；HA 先复用 B5 已验收的 Wyoming/Sherpa device-endpoint 仅完成 STT，再用 HA Core 的 sentence trigger 与 local intent API 做本地匹配。本地命中继续由 HA 现有本地响应所有权完成；本地未命中时，将同一 Sherpa final transcript 通过 Qwen GCP 7.0 `conversation.item.create(parts[text])` 提交到当前 Audio Agent，并复用现有 tool/audio/playback/follow-up 生命周期。Qwen `audio.delta` 之后的输出实现为硬冻结区。

**Tech Stack:** Home Assistant 2026.11.0、Python 3.14、Wyoming 1.10.2、Sherpa-ONNX Paraformer device endpoint、Qwen Audio Agent v2.1.0 / GCP 7.0、qwen3.8-omni-flash-realtime、pytest。

**Spec:** `docs/superpowers/specs/2026-11-25-p6-8-b8-8-stt-local-intent-qwen-text-contract-matrix.md`

## Global Constraints

- S3 当前 MIC 输入已是 Sherpa 所需格式：16,000 Hz、16-bit、mono、S16LE；B5 已验证现有 HA→Wyoming 路径 64,000 B 逐字节一致，因此 **不得增加重采样、WAV 中转、落盘、二次 ring 或 B8.8 固定重分块层**。
- `esp32/firmware/**` 在 B8.8 实现提交中必须零 diff。
- 继续使用 `Sherpa ONNX Paraformer Device Endpoint`：`requires_external_vad=false`、`supports_transcript_streaming=false`；正常 EOF 只允许一次 `AudioStop` 和一次最终 decode。
- Sherpa final transcript 是用户文本权威；Qwen 的 user `transcript.final` 只作为 Gateway 回显，不能重新判定 STT 成功。
- 本地匹配顺序固定为 sentence trigger → HA local intent；已匹配但执行失败仍属于 local hit，不允许再 fallback 到 Qwen 重复副作用。
- local miss 只提交一次 GCP `conversation.item.create`，payload 使用 `parts:[{type:"text",text: transcript}]`；HA Client 不发送第二个 `response.create`。
- local miss 禁止 replay 原始 PCM 给 Qwen，也禁止文本+同一音频双输入。
- Qwen Agent 的 Prompt、persona/memory、Frontend MCP、tool-result continuation、response/follow-up 逻辑保持。
- 从 `QwenRealtimeBridge._handle()` 接收 `audio.delta`、`QwenPcmStream`、`TivooQwenPcmView`、`_open_output()`、`async_send_tts_play()` 到 S3 playback/AUDIO_STATE 的现有输出路径禁止为 B8.8 额外修改。
- 不新增 TTS 引擎；local hit 若有本地响应，复用当前 HA pipeline 的 TTS/播放所有权。
- 不加固定 sleep；不等待 Qwen user transcript 后才进入 thinking；不新增额外预缓冲。
- 所有新路径继续使用当前 MIC session_id、HA Context/generation、Qwen turnId/responseId、playback_id 隔离，不建立第二套状态机。

## Review Focus

- **本地已匹配但服务执行失败：** 必须只返回本地失败结果，Qwen 无 user turn、MCP 无二次控制；Task 4 增加覆盖。
- **follow-up 本地命中：** 不提交 Qwen 文本，并释放上一轮保留 socket，不能泄漏到下一次独立 wake；Task 5 增加覆盖。
- **STT 正常 EOF 前被 supersede/disconnect：** 不产生可执行 transcript、不发 Qwen 文本；Task 3/5 增加覆盖。
- **Qwen text submit 成功但 response/tool/audio 迟到到旧 generation：** 继续按现有 owner fencing 丢弃；Task 5 增加覆盖。
- **local hit 与 Qwen fallback 双播：** 一个 turn 只能拥有 HA local playback 或 Qwen playback 之一；Task 4/5 增加互斥断言。

---

### Task 1: 锁定 B8.8 输入与输出基线

**Files:**
- Modify: `tests/homeassistant/custom_components/tivoo/test_p68_real_pipeline.py`
- Modify: `tests/homeassistant/custom_components/tivoo/test_qwen_realtime.py`
- Reference only: `esp32/firmware/main/s3_local_turn.c`
- Reference only: `services/sherpa_wyoming/providers/stt.py`
- Reference only: `homeassistant/custom_components/tivoo/qwen_realtime.py`

**Interfaces:**
- Consumes: S3 `MIC_SESSION_START(sample_rate=16000, channels=1, sample_format=s16le)`、现有 `AudioSessionManager.audio_subscription()`。
- Produces: B8.8 的回归保护；不新增生产接口。

- [ ] **Step 1: 写 PCM 直通 characterization test**

在 `test_p68_real_pipeline.py` 增加 `test_b88_s3_pcm_reaches_device_endpoint_byte_exact()`，使用现有 local session/真实 HA Core + fake Wyoming endpoint fixture，断言：

```python
assert wire_audio_start == (16000, 2, 1)
assert b"".join(wire_audio_chunks) == source_pcm
assert audio_stop_count == 1
assert stt_vad_events == []
```

同时断言测试源 PCM 直接由现有 `async_push_pcm()` / `audio_subscription()` 流过，不引入新的项目级 PCM converter fixture。

- [ ] **Step 2: 跑 RED/characterization 基线**

Run:
```bash
pytest -q tests/homeassistant/custom_components/tivoo/test_p68_real_pipeline.py -k 'b88_s3_pcm or device_endpoint'
```

Expected: 既有 device-endpoint 断言 PASS；若新测试因当前 Qwen 分支绕过 Sherpa 而 FAIL，失败必须明确落在“Qwen local branch 未进入 Wyoming”，不是格式错误。

- [ ] **Step 3: 增加 Qwen 输出冻结回归组**

在 `test_qwen_realtime.py` 用现有 fixture 增加/归并一组 `test_b88_output_path_baseline_unchanged()`，固定当前行为：`audio.delta` → 单个 `QwenPcmStream` → 当前 24/32 kHz 转 32 kHz mono → 单个 `TTS_PLAY` → matching playback terminal。测试只锁现有行为，不改变生产代码。

- [ ] **Step 4: 跑输出基线**

Run:
```bash
pytest -q tests/homeassistant/custom_components/tivoo/test_qwen_realtime.py
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add tests/homeassistant/custom_components/tivoo/test_p68_real_pipeline.py tests/homeassistant/custom_components/tivoo/test_qwen_realtime.py
git commit -m "test(p6.8): lock b8.8 pcm and output baselines"
```

### Task 2: 为现有 Qwen bridge 增加真实 GCP 文本输入

**Files:**
- Modify: `homeassistant/custom_components/tivoo/qwen_realtime.py:350-760`
- Modify: `tests/homeassistant/custom_components/tivoo/test_qwen_realtime.py`
- Modify: `tests/integration/qwen_realtime/gateway_probe.mjs` only if the existing probe lacks text-turn coverage

**Interfaces:**
- Consumes: `QwenTurnOwner`、已建立的 GCP 7.0 socket。
- Produces: `QwenRealtimeBridge.async_run_text(owner: QwenTurnOwner, text: str, on_event: Callable[[dict], None], *, on_result: Callable[[QwenResult], None] | None = None) -> QwenResult`。
- Wire contract: `conversation.item.create` with `parts:[{type:"text", text:<non-empty transcript>}]`。

- [ ] **Step 1: 写 handshake/text-input RED tests**

新增测试覆盖：

```python
assert "input.text" in hello["capabilities"]
assert server_ready_without_input_text_is_rejected
assert sent_user_events == [{
    "type": "conversation.item.create",
    "parts": [{"type": "text", "text": "讲一个火星故事"}],
}]
assert not any(e["type"] == "input_audio_buffer.append" for e in client_events)
assert not any(e["type"] == "response.create" for e in client_events)
```

保留当前 `input.audio` capability，不在 B8.8 顺手删除。

- [ ] **Step 2: 跑 RED**

Run:
```bash
pytest -q tests/homeassistant/custom_components/tivoo/test_qwen_realtime.py -k 'text or capability'
```

Expected: FAIL because `input.text` / `async_run_text` 尚不存在。

- [ ] **Step 3: 实现最小 text sender**

在 `QwenRealtimeBridge` 增加：

```python
async def _input_text(self, owner: QwenTurnOwner, text: str) -> None
async def async_run_text(
    self,
    owner: QwenTurnOwner,
    text: str,
    on_event: Callable[[dict], None],
    *,
    on_result: Callable[[QwenResult], None] | None = None,
) -> QwenResult
```

要求：
- `text.strip()` 为空直接拒绝；
- `_input_text()` 只发一次 `conversation.item.create`；
- 成功发送后设置现有 `owner.input_drained=True`、`mark("input_eof")`、`changed.set()`；
- 不发 `input_audio_buffer.append`、tail silence 或客户端 `response.create`；
- 抽取最小公共 response-loop 供 audio/text 两条入口共享时，**不得改动** `QwenPcmStream`、`_handle()`、`_open_output()` 和 playback terminal 语义。

- [ ] **Step 4: 跑 GREEN + 现有 audio 回归**

Run:
```bash
pytest -q tests/homeassistant/custom_components/tivoo/test_qwen_realtime.py
```

Expected: PASS，包括原 audio-input tests。

- [ ] **Step 5: 用锁定 v2.1.0 Gateway probe 验证真实事件**

若现有 `gateway_probe.mjs` 没有 text turn，用它的同一连接方式增加一次 `conversation.item.create` probe，确认 server 接受 `input.text`、产生 `turn.started` / user `transcript.final` / response lifecycle；probe 不连接真实 S3、不播放物理音频。

Run:
```bash
pytest -q tests/integration/qwen_realtime/test_probe.py
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add homeassistant/custom_components/tivoo/qwen_realtime.py tests/homeassistant/custom_components/tivoo/test_qwen_realtime.py tests/integration/qwen_realtime
git commit -m "feat(p6.8): add qwen text turn input"
```

### Task 3: 在 Qwen local 模式恢复 Sherpa device-endpoint STT

**Files:**
- Modify: `homeassistant/custom_components/tivoo/assist_satellite.py:70-520,698-820`
- Modify: `tests/homeassistant/custom_components/tivoo/test_qwen_satellite.py`
- Modify: `tests/homeassistant/custom_components/tivoo/test_p68_real_pipeline.py`

**Interfaces:**
- Consumes: `TivooAssistSatellite.validate_local_pipeline() -> tuple[str, str]`、`AssistSatelliteEntity.async_accept_pipeline_from_satellite(..., start_stage=STT, end_stage=STT)`、现有 `audio_subscription()`。
- Produces: `_Turn.transcript: str | None`；只有正常 drain 后的 `STT_END.stt_output.text` 可赋值。

- [ ] **Step 1: 写 Qwen-present 仍走 Sherpa 的 RED tests**

新增/调整测试：即使 `entity.qwen_bridge is not None`，local turn 也必须先：
1. validate dedicated local pipeline；
2. 通过现有 `audio_subscription()` 进入 public Satellite STT；
3. 收到正常 `STT_END` 后保存 transcript；
4. STT 阶段不向 Qwen 发送 audio/text。

关键断言：

```python
assert turn.transcript == "打开客厅灯"
assert wyoming_pcm == source_pcm
assert qwen_audio_append_count == 0
assert qwen_text_create_count == 0
```

- [ ] **Step 2: 跑 RED**

Run:
```bash
pytest -q tests/homeassistant/custom_components/tivoo/test_qwen_satellite.py tests/homeassistant/custom_components/tivoo/test_p68_real_pipeline.py -k 'stt or sherpa or b88'
```

Expected: FAIL because current Qwen branch直接调用 `qwen.async_run(..., audio, ...)`。

- [ ] **Step 3: 改 local turn 的输入 owner**

在 `_start_turn()` 中，local 模式首先使用现有 `PipelineTtsEvents` 作为 STT/local-response owner；不要在 turn 创建时立即把 PCM owner 设为 Qwen。

在 `_run_turn()` local 分支：
- 无论 Qwen bridge 是否存在，都调用 `validate_local_pipeline()`；
- 用 public `async_accept_pipeline_from_satellite(audio, PipelineStage.STT, end_stage=PipelineStage.STT, wake_word_phrase=..., context=turn.context)` 完成一次 STT；
- 不对 `audio` 做新的 project-level reframe；
- 保持现有 ready/on_eof、`local_input_drained()`、45 s finalize watchdog、supersede/cancel 语义。

- [ ] **Step 4: 在 `on_pipeline_event()` 记录 transcript**

给 `_Turn` 增加：

```python
transcript: str | None = None
```

只有满足：
- 当前 turn；
- local mode；
- `STT_END`；
- input 已自然 drain；
- `command_started`；
- 非空 text；
- 无 error；

才设置 `turn.transcript=text.strip()` 与 `turn.valid_stt=True`，并立即进入现有 THINKING 显示。Qwen user transcript 不再设置 `valid_stt`。

- [ ] **Step 5: 覆盖取消/空文本/早 EOF**

测试至少覆盖 disconnect、superseded、empty transcript、provider error、unexpected HA VAD；这些情况均：

```python
assert turn.transcript is None
assert qwen_text_create_count == 0
```

- [ ] **Step 6: 跑 GREEN**

Run:
```bash
pytest -q tests/homeassistant/custom_components/tivoo/test_qwen_satellite.py tests/homeassistant/custom_components/tivoo/test_p68_real_pipeline.py
```

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add homeassistant/custom_components/tivoo/assist_satellite.py tests/homeassistant/custom_components/tivoo/test_qwen_satellite.py tests/homeassistant/custom_components/tivoo/test_p68_real_pipeline.py
git commit -m "feat(p6.8): restore sherpa stt before qwen"
```

### Task 4: 增加 HA local-first 路由并保持 local hit 在 HA 内完成

**Files:**
- Modify: `homeassistant/custom_components/tivoo/assist_satellite.py`
- Modify: `tests/homeassistant/custom_components/tivoo/test_qwen_satellite.py`
- Modify: `tests/homeassistant/custom_components/tivoo/test_p68_real_pipeline.py`

**Interfaces:**
- Consumes: `turn.transcript`、HA `conversation.async_handle_sentence_triggers()`、`conversation.async_handle_intents()`、当前 dedicated local pipeline 的 language/TTS 配置。
- Produces: private `LocalRouteResult` with exact fields:
  - `handled: bool`
  - `speech: str`
  - `continue_conversation: bool`
- Produces: `AudioSessionCoordinator._async_route_local_transcript(turn: _Turn) -> LocalRouteResult`。

- [ ] **Step 1: 写 local hit/miss RED tests**

覆盖：
- sentence trigger hit；
- HA entity query/control intent hit；
- no-match；
- matched intent but service/target failure；
- empty/no transcript 不进入 router。

关键断言：

```python
assert local_hit.handled is True
assert qwen_text_create_count == 0
assert service_side_effect_count == 1

assert local_miss.handled is False
assert service_side_effect_count == 0
```

对“已匹配但执行失败”：

```python
assert result.handled is True
assert qwen_text_create_count == 0
```

- [ ] **Step 2: 跑 RED**

Run:
```bash
pytest -q tests/homeassistant/custom_components/tivoo/test_qwen_satellite.py -k 'local_intent or sentence_trigger or local_miss'
```

Expected: FAIL because local router 尚不存在。

- [ ] **Step 3: 实现最小 local router**

在 `assist_satellite.py` 使用 HA 2026.11.0 已核对 API：
- `conversation.async_prepare_intents(hass, language)`
- `conversation.ConversationInput(...)`
- `chat_session.async_get_chat_session(...)`
- `conversation.async_get_chat_log(...)`
- `conversation.async_handle_sentence_triggers(...)`
- `conversation.async_handle_intents(...)`

固定顺序：
1. sentence trigger；
2. local intents；
3. 两者都返回 None 才 `handled=False`。

不要调用 `conversation.async_converse()`；因此 AstrBot/其它 LLM 不可能在 B8.8 local router 中先执行一次。

- [ ] **Step 4: local hit 复用现有 HA TTS owner**

local hit 有 speech 时，用当前 dedicated pipeline 的既有 TTS 配置执行 **TTS-only** HA Pipeline；不得重新跑 STT/Intent。使用 HA `PipelineRun` + `PipelineInput(tts_input=..., start_stage=PipelineStage.TTS, end_stage=PipelineStage.TTS)`，event callback 继续交给当前 `PipelineTtsEvents`，从而保持既有 HA TTS proxy → `TTS_PLAY` 所有权。

local hit 无 speech 时直接完成本轮，不创建 Qwen turn，也不新增 TTS 引擎。

- [ ] **Step 5: 锁定 local/Qwen playback 互斥**

新增断言：
- local hit：`turn.tts` 仍是 local `PipelineTtsEvents`，Qwen bridge 没有 owner/user turn；
- local miss：本 Task 只返回 miss，不播放 HA TTS；
- 同一 session 不得出现两个不同 playback owner。

- [ ] **Step 6: 跑 GREEN**

Run:
```bash
pytest -q tests/homeassistant/custom_components/tivoo/test_qwen_satellite.py tests/homeassistant/custom_components/tivoo/test_p68_real_pipeline.py -k 'local or b88'
```

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add homeassistant/custom_components/tivoo/assist_satellite.py tests/homeassistant/custom_components/tivoo/test_qwen_satellite.py tests/homeassistant/custom_components/tivoo/test_p68_real_pipeline.py
git commit -m "feat(p6.8): route sherpa text through ha local intents"
```

### Task 5: local miss 切换到 Qwen text turn，并收口 lifecycle/follow-up

**Files:**
- Modify: `homeassistant/custom_components/tivoo/assist_satellite.py`
- Modify: `homeassistant/custom_components/tivoo/qwen_realtime.py` only for retained-socket release API if required
- Modify: `tests/homeassistant/custom_components/tivoo/test_qwen_satellite.py`
- Modify: `tests/homeassistant/custom_components/tivoo/test_qwen_lifecycle.py`

**Interfaces:**
- Consumes: Task 2 `QwenRealtimeBridge.async_run_text(...)`、Task 4 `LocalRouteResult`。
- Produces: local-miss handoff；必要时新增 `QwenRealtimeBridge.async_release_retained(parent_session_id: str) -> None`，只用于 follow-up local hit 后释放上一轮 retained socket。

- [ ] **Step 1: 写 local-miss text handoff RED test**

固定一次 local miss 的顺序：

```python
assert events.index("stt_final") < events.index("local_miss")
assert qwen_user_events == [{
    "type": "conversation.item.create",
    "parts": [{"type": "text", "text": transcript}],
}]
assert qwen_audio_append_count == 0
assert qwen_client_response_create_count == 0
```

之后模拟当前 `tool.call` / `audio.delta` / terminal-status / physical playback，断言现有 Qwen 输出行为保持 Task 1 基线。

- [ ] **Step 2: 跑 RED**

Run:
```bash
pytest -q tests/homeassistant/custom_components/tivoo/test_qwen_satellite.py tests/homeassistant/custom_components/tivoo/test_qwen_lifecycle.py -k 'fallback or followup or text'
```

Expected: FAIL because coordinator 尚未从 local miss 切换到 `async_run_text()`。

- [ ] **Step 3: 在 local miss 时单次切换 owner**

local STT owner 完成且 router 返回 miss 后：
1. 确认 `turn.transcript` 仍属于当前 generation；
2. 关闭/结束 STT-only `PipelineTtsEvents`，它此时不得有 playback；
3. 用现有 `qwen_bridge.create_turn(session_id, context.id, current=..., prompt_player=..., parent_session_id=...)` 创建 Qwen owner；
4. 将当前 turn 的输出 owner 切换为该 Qwen owner；
5. 调用 `qwen.async_run_text(owner, turn.transcript, on_qwen_event, on_result=...)`。

不得重新打开 `audio_subscription()` 或读取历史 PCM。

- [ ] **Step 4: 更新 Qwen event 语义**

删除/失效当前“Qwen user `transcript.final` → `turn.valid_stt=True`”逻辑。Qwen event callback 只保留：
- tool.call → TOOLUSE；
- assistant transcript/final → 当前 follow-up 判定；
- 其它现有 response/audio 生命周期。

THINKING 已由 Task 3 的 Sherpa final transcript 触发。

- [ ] **Step 5: 覆盖 follow-up 两条分支**

**follow-up local miss：**
- 新 MIC UUID / 新 HA Context；
- Sherpa STT + local miss；
- `conversation.item.create` 必须发在上一轮保留的同一活动 Gateway WebSocket；
- 当前 Qwen 上下文继续。

**follow-up local hit：**
- 不发 Qwen user turn；
- local side effect 只执行一次；
- 上一轮 retained Qwen socket 必须有界释放，不能被下一次独立 wake 误复用。

若现有 bridge 没有安全释放入口，只增加最小：
```python
async def async_release_retained(self, parent_session_id: str) -> None
```
它只核对匹配的 `_retained_parent` 后关闭 retained socket/task，不触碰音频输出函数。

- [ ] **Step 6: 覆盖 cancellation/supersede**

分别在 STT、local-route 后、text submit 后、tool call、audio generation/playback 阶段触发新 wake；断言旧 generation：
- 不新增 local side effect；
- 不新增 user turn；
- late Qwen events 不播放；
- 定向 stop/close 继续沿用现有 lifecycle。

- [ ] **Step 7: 跑 GREEN**

Run:
```bash
pytest -q tests/homeassistant/custom_components/tivoo/test_qwen_satellite.py tests/homeassistant/custom_components/tivoo/test_qwen_lifecycle.py tests/homeassistant/custom_components/tivoo/test_qwen_realtime.py
```

Expected: PASS。

- [ ] **Step 8: Commit**

```bash
git add homeassistant/custom_components/tivoo/assist_satellite.py homeassistant/custom_components/tivoo/qwen_realtime.py tests/homeassistant/custom_components/tivoo/test_qwen_satellite.py tests/homeassistant/custom_components/tivoo/test_qwen_lifecycle.py
git commit -m "feat(p6.8): fallback local misses to qwen text"
```

### Task 6: B8.8 综合回归、性能证据与部署门禁

**Files:**
- Create: `docs/superpowers/reports/2026-11-25-p6-8-b8-8-acceptance.md`
- Modify tests only if an uncovered regression is found
- Do not modify: `esp32/firmware/**`

**Interfaces:**
- Consumes: Tasks 1-5 complete implementation.
- Produces: B8.8 software/deployment acceptance evidence; no new runtime API.

- [ ] **Step 1: 跑 HA/Qwen 定向回归**

Run:
```bash
pytest -q \
  tests/homeassistant/custom_components/tivoo/test_audio_session.py \
  tests/homeassistant/custom_components/tivoo/test_p68_local_session.py \
  tests/homeassistant/custom_components/tivoo/test_p68_real_pipeline.py \
  tests/homeassistant/custom_components/tivoo/test_qwen_realtime.py \
  tests/homeassistant/custom_components/tivoo/test_qwen_satellite.py \
  tests/homeassistant/custom_components/tivoo/test_qwen_lifecycle.py
```

Expected: 0 failures。

- [ ] **Step 2: 跑 Sherpa device-endpoint 回归**

Run the existing Sherpa/Wyoming focused suite used by P6.8 B5；至少确认：
- 16 kHz / 16-bit / mono；
- exact byte order；
- normal EOF exactly one AudioStop/decode；
- cancel 不伪装正常 EOF。

Expected: 0 failures。

- [ ] **Step 3: 证明 S3 与输出链未被 B8.8 改动**

Run:
```bash
git diff <B8.8-base>...HEAD -- esp32/firmware
git diff <B8.8-base>...HEAD -- homeassistant/custom_components/tivoo/qwen_realtime.py
```

要求：
- 第一条无输出；
- 第二条只允许 handshake/text-input/common-run/retained-release 所需输入侧改动；`QwenPcmStream`、`TivooQwenPcmView`、`_handle()` 的 audio output 处理、`_open_output()` 与 TTS_PLAY 行为无 B8.8 功能变化。

- [ ] **Step 4: 记录阶段延迟而不是只看总时长**

软件/实机验收日志至少记录：
- `speech_end → Sherpa STT_END`
- `STT_END → local hit/miss decision`
- `local miss → conversation.item.create send`
- `text send → first Qwen audio.delta`
- `first audio.delta → physical playing`

不得增加固定 sleep、音频 replay、等待 Qwen user transcript、额外预缓冲来改善统计。

- [ ] **Step 5: NAS 部署只更新 HA/Qwen 输入侧**

部署前备份当前 HA custom component 与 Qwen Gateway 配置。S3 不刷固件。部署后先做无物理出声的：
- Qwen text GCP probe；
- local intent dry/non-destructive query；
- local miss 文本 turn；
- MCP read-only tool。

再按当前允许的实机窗口做一轮真实 local hit 与一轮普通问答，确认现有播放链无回归。

- [ ] **Step 6: 写 acceptance report**

报告逐项核销 B88-C01–C24，并明确：
- software PASS/FAIL；
- NAS deployment PASS/FAIL；
- hardware playback 是否实测；
- local hit 与 local miss 延迟；
- 是否存在任何 S3/output diff。

- [ ] **Step 7: 最终 verification**

Run:
```bash
git diff --check
git status --short
```

Expected: 无 whitespace error；只有本任务预期文件。

- [ ] **Step 8: Commit**

```bash
git add docs/superpowers/reports/2026-11-25-p6-8-b8-8-acceptance.md
git commit -m "docs(p6.8): record b8.8 acceptance"
```

## Self-Review Result

- **Spec coverage:** B88-C01–C24 均映射到 Task 1–6；S3 零改动、PCM 直通、single ASR、local-first、text fallback、follow-up、failure/cancel、output freeze 均有对应验收。
- **Step granularity:** 每个 Task 都有 RED/实现/GREEN/commit 闭环；没有把实现代码正文写进计划。
- **Type consistency:** `turn.transcript`、`LocalRouteResult`、`async_run_text()`、可选 `async_release_retained()` 在首次出现处定义，后续使用一致。
- **Review focus coverage:** 五个高风险项分别由 Task 3、4、5 的测试固定。
- **Proportion:** 计划只固定接口、边界、测试与提交点；不提前实现业务代码。

## Execution Order

严格按 Task 1 → 2 → 3 → 4 → 5 → 6 顺序执行。Task 2 可以独立验证 Qwen text contract；Task 3/4 不依赖真实 Qwen response；Task 5 才把两边汇合。任何一步需要修改 `esp32/firmware/**` 或 Qwen audio output 冻结区才能通过时，停止该步并回到 B8.8 合同审查，不用扩大范围绕过门禁。
