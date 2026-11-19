# P6.8 R09 修复验收 — 真实 HA 完整 Pipeline 与 owner 生命周期组合

- 范围：R09.1–R09.4；F16 / B5-R03、B7-R04；VOICE-C02、LIFE-C03/04/05/06/08、T05-A/C、T07-A/C/D。
- 基线：c94e47e7a4a2193862f2308d48f142b070c8be4f（R08），feature/p6-8-s3-local-wake。前置 R05–R08 软件证据保留原结论。
- 方法：Superpowers executing-plans、systematic-debugging、test-driven-development、receiving-code-review、requesting-code-review 清单自审、verification-before-completion。无独立子代理，非独立复审。沿用用户指定工作区和分支，保留原 B1–B10 计划既有未提交链接。
- 交付：仅扩展原 test_p68_real_pipeline.py 的 R06 public API fixture，不替换既有11种场景或其断言，不增加生产接口，不 patch HA Core，不改合同/实现。此次 F16 属于软件组合验证遗漏；新增真实组合在修正测试 fixture 后直接 GREEN，无确凿生产 RED，因此不制造 RED 或顺手修改生产代码。

## R09.1：真实完整 public Pipeline

保留 ASR-only fake Wyoming TCP peer、真实 HA Core 2026.11.0 与现有 AssistSatellite public run、真实 AstrBot integration 和 loopback HTTP SSE。增加独立 fake Wyoming TTS TCP endpoint（宣告真实 TTS/streaming voice），真实 HA ResultStream、PipelineTtsOwner、FFmpeg MP3 转码和实际 HTTP Proxy GET。使用原 session manager 的 gate/speech/PCM/end 入口；除 no_tts 的 conversation provider 返回值 seam 外不替换 public run、Intent 或 TTS。原 R06 故障组仍按原有 Intent end-stage 检查不得发 Intent 的契约，不能拿它代替本批完整运行。

新增同一个 pytest 参数化测试的8节点：

| 节点参数 | 验证 |
|---|---|
| full | 真 STT→Intent→TTS→RUN_END；实际 0x30 描述符 UUID/playback/URL/MIME 与 RUN_START token、ResultStream 一致；HTTP 200、MP3 ID3、有音频字节；真实 conversation Context 与轮次匹配；RUN_END 和错误 session/playback/source 不发 grant；匹配 completed 后一次 0x27，重复 completed 无效；新 followup UUID 实际完成第二次 STT/TTS/GET，Context/playback 不同而 AstrBot session 延续；第二轮非问句自然完成不再 grant。 |
| no_tts | 保留有效 TTS 配置，仅让 conversation provider 返回合法无语音响应；真实 Core INTENT_END/RUN_END，无 TTS_START/ERROR，未尝试播放且无发送失败；conversation_complete，不误判 pipeline_failed。 |
| send_failure | 真实 adapter 编码的 0x30 写入后注入 drain OSError；真实 send_failed、pipeline_failed 和回收，禁止 grant。 |
| lost_terminal | 真 7778 loopback 连接循环/HELLO ACK/GET_STATUS/序号；正常 pipeline 已返回、资源 GET 完成仍无 completed 时，旧连接实际关闭，manager 退休，禁止 grant；重新协商后新 READY 序号从2开始，旧 UUID 的 completed 经真 RX 不影响新轮。 |

full 等常规场景的设备边界是最小 fake writer 和已注册 AUDIO_STATE handler，实际 transport 编码与匹配判断未替换；lost_terminal 另通过真实 TCP 收发与重连。ready 与 terminal 均不是人为发 HA pipeline event。输入 gate/PCM 采用 manager API，非两板硬件 RX；显示器为已有 RecordingAdapter，不代表实际像素。

## R09.2：旧 owner 取消、失败隔离与恢复

| 节点参数 | 验证 |
|---|---|
| cancel_owner | TTS provider 已送 PCM，真实 GET 进行中；新 wake 使旧资源连接 FIN，fake peer 有意延迟 EOF；旧 owner close 未完成期间新轮不 READY/不 RUN_START。释放 peer 后 GET/旧 caller/owner 收敛，新轮独立 Context；0x31 绑定旧 session/playback；迟到终态对新轮无效，disconnect 清理。 |
| stop_unconfirmed | 超过 Core streaming 字符门槛的真实 SSE 部分内容，同时存在旧 caller 和 TTS owner。实际 /api/v1/chat/sessions/{session_id}/stop 被调用；等待 Stop 和 Wyoming FIN 时新轮不进入；Stop 返回 HTTP500、peer EOF 后旧轮关闭，新申请不得进入；另一起 STT 请求仍不能向旧 AstrBot session 发 chat；真实 astrbot.new_conversation 服务后不同 session 实际完成 TTS/GET/terminal。 |
| unload | TTS peer FIN 后故意延迟 EOF，实际 entity.async_will_remove_from_hass 等待旧 close，释放后 owner/caller 均结束，无 grant。 |
| eof_unconfirmed | 真 Wyoming FIN 后不确认 EOF，测试内将现有 timeout 从15s 缩短到0.5s；实际 owner close 抛 HomeAssistantError，新轮 pipeline_failed、无 READY/grant；释放 fake peer 结束测试。生产时限未改。 |

保留 B7 test_repeated_wake_serializes_public_caller、test_true_wake_retires_each_local_phase、grant 真假及先后顺序等原测试。R09 不重写全部 mock；正常 RUN_END 之后 caller 可以先结束而资源 owner 仍活跃，必须分别判断，不能把 public caller done 当作 owner done。

## R09.3–R09.4：复验与实际日志

本地忽略日志目录：.superpowers/p68-r09/。此前 R06 提前 Transcript/排空/异常 EOF 与 provider_error、R07 旧 UUID/拒绝/并发入口、R08 terminal_lost/transport 由 HA 指定回归与新增同一 fixture 覆盖；额外复跑实际固件资源 worker 和 turn wire host（独立 pytest 环境，避免 R08 已知 HA pytest_socket 与 ESP HTTP fixture 混跑冲突）。

| 阶段 | 日志 | 实际结果 |
|---|---|---|
| 初始 fixture | first.log | 7 failed、11 deselected；exit 1。HA 已自动加载 TTS entry，又重复 setup 导致 OperationNotAllowed；无配置 TTS 不等于合法无语音结果。 |
| fixture 第二轮 | second.log | 4 passed、3 failed、11 deselected；exit 1。两个错误断言把已 RUN_END caller 当未完成 owner；SSE 太短未超过 Core streaming 门槛，未进入目标取消窗口。 |
| 修正取消 fixture | third.log | 3 passed、15 deselected；exit 0。 |
| 新增真实 TCP/恢复/未确认 EOF | expanded.log | 7 passed、1 failed、11 deselected；exit 1。fake TCP 把出站序号当入站序号，真实 decoder 拒绝，修正独立方向序号并于新 epoch 重置。 |
| R09 新增8节点 | expanded-final.log | 8 passed、11 deselected、15 warnings；exit 0。 |
| 计划 HA 指定8文件 | ha-focused.log | 179 passed、86 warnings；exit 0。 |
| HA 全量独立 | ha-full.log | 586 passed、268 warnings；exit 0。 |
| R08 实际资源 worker 复跑 | esp-worker.log | 9 passed、3 deselected、2 warnings；exit 0。 |
| R08 turn wire host 复跑 | esp-turn.log | 2 passed、2 warnings；exit 0。 |

以上初始失败是 fixture 接口/时序错误，不是已复现生产问题；日志保留，未删改原有效断言。警告含既有依赖弃用、pytest 配置与 aiohttp AppKey，不作硬件失败判断。

复验命令（repo root，使用原开发环境）：

```bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath"
bash scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_p68_real_pipeline.py -k 'full or no_tts or send_failure or lost_terminal or cancel_owner or stop_unconfirmed or unload or eof_unconfirmed' -s -q -p no:cacheprovider
bash scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/{test_p68_real_pipeline,test_p68_lifecycle,test_p68_local_session,test_audio_resource,test_transport}.py tests/homeassistant/test_assist_pipeline_tts_cancellation.py tests/homeassistant/custom_components/astrbot/{test_session,test_conversation}.py -q -p no:cacheprovider
bash scripts/test-ha.sh tests/homeassistant -q -p no:cacheprovider
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32/test_p6_audio_resource.py -k local_resource_worker -q -p no:cacheprovider
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32/test_p68_turn.py -q -p no:cacheprovider
```

## R10 所需真实事件基线

expanded-final.log 的 R09 full 记录：RUN_START → STT_START → STT_END → INTENT_START → INTENT_PROGRESS ×2 → INTENT_END → TTS_START → TTS_END → RUN_END。本次短问句走正常非延迟 partial 流程；长 partial SSE 另由 stop_unconfirmed 覆盖流式 TTS 取消。匹配资源实际由 0x30 发出，设备 0x32 playing、completed 独立于 RUN_END；grant 在两者满足后一次，新的 START/gate/READY 属于另一 Context/session。STT_END→thinking，后续 thinking/tooluse/speaking 优先级与显示尾部由原合同和 R10 裁决，不从该次序推断 mood 已可见。合法 no-TTS 有 INTENT_END/RUN_END 而无 TTS_START 或 0x30；terminal 丢失应走 disconnect，不伪造 completed。真实 TCP 记录 epoch0 READY(seq2)、TTS_PLAY(seq3)，epoch1 READY(seq2)，旧 session terminal 无 grant。R10 可直接复用该 fixture 与现有 R02 fake SPP socket；本批不进行 F17 产品裁决，不修改显示生产代码。

## 自审与边界

按 reviewer template 检查 R09.1–4、F16 和 diff：原 11 节点保留，新增断言针对真实 public caller、真实 HTTP/TCP 和所有权，fake 仅负责外部设备/provider/故障。检查破坏性语义（提前 grant、旧 UUID 完成新轮、Stop 未确认复用、未排空即进入新 caller）均有可失败的对应断言。未发现 Critical/Important 范围缺口；测试扩展较长，集中共享 R06 fixture，未重构其他测试。无独立 reviewer，结论为自审及软件复验。

Declined to judge：物理 DAC/I2S、真实 S3 设备与生产网络/TTS/AstrBot Stop，不具实物且未获部署授权，保留 GAP；实际硬件 C worker 与 HA 未接在同一真实设备上，分别由既有 host 和新增 HA loopback 验证，不描述为硬件 E2E。R10 mood/真实 SPP 输出不属于 R09；F17 产品合同仍未获批准。R11 clean build/总核销、B9 条件清理和 B10 现场验收不提前执行。未变更生产固件/HA/AstrBot 代码、配置或依赖，无受影响固件构建/新 hash，沿用 R08 归档。未访问 NAS、部署、刷写、推送远端或切换 main。
