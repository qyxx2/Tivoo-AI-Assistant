# P6.8 R10 修复验收 — 本地 TTS Mood 内容与真实显示传输组合

- 基线：356c2ce2ac1df9eb27ac6b2fd22560241433d156（R09），feature/p6-8-s3-local-wake。
- 范围：F17/B8-R01、F18/B8-R03；VIEW-C01–04、ESM-C09/C11/C19、T08-A/B/C；R02/R09 证据不改写。
- 用户裁决（2026-11-19）：优先采用在 TTS 输出区间替代默认图像的 Mood，有 SetMood 时显示其情绪表情，否则默认 TTS 图像；若复杂不可控才用独立播放后尾部方案。实际选择前者，仅改现 coordinator 的 speaking payload，无独立尾部、计时器或 owner。
- 方法：Superpowers executing-plans、receiving-code-review、brainstorming（用户明确裁决且授权直接实施）、TDD、systematic-debugging、verification-before-completion；无可用独立 reviewer，执行作者自审，不冒充独立复审。

## R10.1–R10.2 合同和实现

本地 generation 有效 STT 后接受现白名单/Context 校验的 Mood，以最新值替换前值。在真实当前 UUID、playback ID、tts_http playing 区间，coordinator 保持 SPEAKING 赢家，仅将其默认 music 命令替换为该 Mood。提交时无普通 TTS playing 不额外起屏；等待语音生成及长 TTS 不受原 5s TTL 截断；终态、取消、新 wake/followup、断线/unload/无 TTS 结束均清除，终态后拒绝。已知旧 Context 拒绝、无关联 ID 仍仅能按当前有效回复判断；不虚构来源。无 TTS 不显示，无额外尾部补播（实施者根据用户指定的 TTS 区间作最小裁决）。legacy 模式保持 AI_MOOD 独立 intent 和 5s TTL。

实现限定于 display_state.py（当前 generation 的 speaking 内容及原有清理接缝、复用单 lock/异步 recompute）、assist_satellite.py（本地 generation 选择该行为）、LLM/service 描述。SetMood local 接受不等待 SPP，service_completed 表示请求已接受，非物理像素成功；不更改 schema、DisplayState 优先级、思考/工具状态、gate、音频生命周期或播放协议。同步 B0.5 规格、ESM 规格/矩阵、迁移索引并在 R10 计划记录裁决，历史 B8/T08-C 本地 5s 约束以 R10 修订为准。

## R10.3 真实组合

复用 R09 真实 HA Public Satellite Pipeline、AstrBot HTTP SSE、Wyoming STT/TTS TCP、MP3 HTTP GET 及 R02 真实 TCP transport；新增 display_wire_on/off。真实 HELLO/ACK、请求对应 DEVICE_STATUS、DEVICE_EVENT、发送 MAC、编码 7777 字节；在已经写入 question 后人为阻塞 control writer.drain（非 RF 物理阻塞），真实 7778 MIC_SESSION_START、COMMAND_GATE、MIC_ACTIVITY、MIC_PCM、终点和匹配 0x32 仍执行；实际 STT/Intent/TTS/GET 完成。LLM SetMood 工具走真实服务注册及活动 Context，在慢写期间不阻塞 pipeline。错误 session/playback/source 无效，解除慢写直接出现当前 happy，不回放排队的 listening/thinking；完成后恢复显式 fish。7778 重连不回收正常 7777，connecting/非目标 connected 期间不发送，匹配 connected 重申最新 music 或 OFF，无过期命令补播。

原 full/no_tts 场景扩展真实工具调用：普通完整播放 happy、完成后不残留，真实授权 followup 新 Context 拒绝旧 tool 且未设置 Mood 的第二轮实际发 music；合法无 TTS 接受调用但没有出图。另以实际 local satellite 状态事件验证长于原 5s 的合成等待与播放、播放期间修改、OFF/ON、显式内容恢复、真实新 wake 打断正在显示的 mood 后默认 music、断开清理。保留原测试断言；本批不重做 transport/SPP 协议。

## 验证与日志

忽略目录 .superpowers/p68-r10/。本地测试使用既有开发环境、PYTHONDONTWRITEBYTECODE=1 和 PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath"。

| 阶段 | 结果 | 日志 |
|---|---|---|
| RED test_local_mood_is_speaking_content_not_independent_intent | before/during 2 failed（实际 music 非 happy），none 1 passed；exit 1 | red.log |
| GREEN test_p68_display.py | 16 passed；exit 0 | green.log |
| 新增真实 HA 组合 fixture 首轮 | full/no_tts 2 passed；2 wire failed：强制重发表情产生额外 happy，TCP 分段合并读断言不足；exit 1 | real-first.log |
| fixture 第二轮 | 2 wire failed：多预期了一次 thinking，实际正确直接 fish；exit 1 | real-second.log |
| fixture 修正后 | 双 wire 2 passed；exit 0 | real-third.log |
| 全 R10 指定 HA 回归含原 LLM 测试 | 202 passed、92 warnings；exit 0 | ha-focused.log |
| HA 独立全量 | 591 passed、270 warnings；exit 0 | ha-full.log |
| 全量已开始后额外新增的 active-Mood interruption probe | 1 passed、16 deselected；exit 0；不将该额外节点计入 591 | cancel-mood.log |

实际最终命令（repo root）：

```bash
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath"
bash scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_p68_display.py -k local_mood_is_speaking -q -p no:cacheprovider
bash scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_p68_display.py -q -p no:cacheprovider
bash scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_p68_real_pipeline.py -k 'display_wire or full or no_tts' -q -p no:cacheprovider
bash scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_p68_real_pipeline.py -k display_wire -q -p no:cacheprovider
bash scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/{test_p68_display,test_display_state,test_transport,test_p68_real_pipeline,test_services,test_p68_lifecycle,test_p68_local_session,test_tivoo_p4b4_llm}.py -q -p no:cacheprovider
bash scripts/test-ha.sh tests/homeassistant -q -p no:cacheprovider
bash scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_p68_display.py -k playing_mood_is_retired -q -p no:cacheprovider
git diff --check
```

初始 wire 失败属于 fixture 错误（不是生产故障），保留日志；修正测试对字节流的真实断言，没有删旧有效断言或改变生产 transport。保留既有依赖弃用/pytest/aiohttp 警告。未涉及固件，未重构音频或构建；沿 R09/R08 构建归档，R11 仍须双 target clean build。

## 自审/保留边界

按 R10.1–4 与 F17/F18 检查整个本批 diff，确认无状态优先级提升、无新增 timer/owner、无控制和诊断互相等待；本地 mood 随现 generation 失效，迟到旧 Context、旧 wire terminal 不恢复旧内容；既有 legacy TTL、显式内容、硬 OFF、多 owner/temporary wake、idle、HA reload 和 R09 owner 测试回归通过。无独立 reviewer；未发现本批 Critical/Important 软件缺口。已经提交的物理 SPP 字节不可撤销，短播放或严重慢 SPP 可能来不及实际显示，此为原运输边界，不伪报 last_sent 为像素 ACK。无来源的外部 MCP 迟到调用仍不能精确识别旧轮。实物屏幕、两板 RF/UART、生产部署及延迟保留 GAP；R11 总复验、B9/B10 不执行。工作区原 B1–B10 计划未提交链接保持不变，不 NAS、不部署、不刷写、不 push。
