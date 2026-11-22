# P6.8 B8.2 — Probe 与预检交付代码审查

> 日期：2026-11-22
> 范围：相对 B8.2 基线 efb12029650cc253577fed990893d60c6845b962 的未提交变更；只审查当前 worktree。
> 结论：**B8.2 预检交付可验收；不等于后续 HA 生产桥接或部署可合并。**

## Strengths

- 实时 Gateway 探针在 NAS 容器内读取运行凭据，认证 Token 不进入开发机输入文件、报告或 Git。
- 输入帧格式和 ESP32 现有 contract 一致：16 kHz mono S16LE、20 ms、640 bytes；VAD EOF 后的静音由 PCM append 发送，没有伪造 commit 事件。
- 探针会区分 assistant/user transcript，要求非空最终文本、匹配 turnId、匹配 responseId 与 audio.done，并检查最终 response 的非空 audio.delta 和 sampleRate。
- 同 socket 场景直接检查第二客户端 lease 拒绝、主连接仍活动、各轮 turnId/responseId 更新、journal 持久化，以及新 session 空历史；没有把 reconnect journal 恢复冒充 immediate follow-up。
- 音频输出只计数和丢弃；没有向 HA、ESP32 或设备播放路径发送数据。
- PCM 处理 helper 独立于网络探针，12 项测试覆盖帧边界、尾静音、噪声、停顿、增益和重采样。

## Issues

### Critical

无。

### Important

无。以下试验分支发现不是当前 B8.2 变更中的生产缺陷，但属于后续迁移的明确阻塞合同，不能在复制试验代码时遗漏。

### Minor

无未处理项。初审发现 WAV 夹具重采样辅助函数缺少独立单元断言；已添加 8 kHz→16 kHz 样本数/插值边界测试，重新运行后 12 项测试通过。

## Deferred findings — B8.5 / B8.4 必须处理

1. **TTS_PLAY 缺少当前 MIC session 身份。** 试验分支 homeassistant/custom_components/tivoo/qwen_realtime.py:275-277 调用 async_send_tts_play(playback_id, url, mime_type) 时没有传 session_id。当前 P6.8 transport.py:429-444 对 local-wake TTS_PLAY 强制要求 descriptor.session_id 等于当前 active MIC session，并要求本地输入已完成；当前 adapter 的参数定义位于 transport.py:458-475。试验桥接不能原样复制，B8.5 必须传入当前 turn 对应的 MIC session_id。
2. **有界 HTTP 队列结束可能等待。** 试验分支 qwen_realtime.py:123-126 的 QwenPcmStream.finish() 使用 await queue.put(None)。当队列已满且 HTTP consumer 尚未启动或已断开时，producer cleanup 可能卡在结束标记投递。B8.5 应在 stream owner 中处理 consumer disconnect，并确保 producer 清理能终止。
3. **一次性无登录 HTTP URL 的 capability 边界。** 试验分支 qwen_realtime.py:129-155 使用 requires_auth=False 和 UUID stream_id 的单次 GET。此设计可以复用，但 B8.5 应确保 URL 不进入日志/持久状态，stream id 仅对匹配播放有效，并在完成、取消、超时和断连时移除映射。
4. **24 kHz→32 kHz SRC 不应复制试验实现。** 试验分支的 Pcm16LinearResampler 是线性插值。B8.4 应按总体计划复用 ESP Audio Effects SRC，并在 HA 侧保留实际采样率验证，不把试验算法带入生产。

以上四项只基于 test/qwen-realtime-audio-bridge worktree 和当前 P6.8 adapter/transport 合同的只读比对；该试验 worktree 未被修改，本批也没有新增 route 或生产播放逻辑。

## Behaviors considered and set aside

- 真实 Tivoo 麦克风 AFE 的实际声压、房间声学和物理回声：B8.2 明确使用现有测试 WAV/离线语音，不做硬件声学验收。
- ESP32 实际 32 kHz 播放、SRC 音质和 HTTP 播放时序：B8.2 禁止播放，分别归 B8.4/B8.5。
- HA 内部 HTTP endpoint 的实际访问和真实 TTS_PLAY：只核对接口/权限合同，不部署 HTTP view。
- Qwen Frontend MCP 的安装、工具发现与实际工具调用权限：归 B8.3 和 B8.7；B8.2 仅验证 Gateway 自身对话/工具响应事件顺序。

## Recommendations

- 保持 B8.2 不修改生产 HA、ESP32、NAS 持久配置；继续按 B8.3、B8.4、B8.5、B8.6、B8.7 顺序推进。
- 将 Deferred findings 纳入对应批次合同矩阵/回归测试，尤其是 session_id fence 和 HTTP stream disconnect/cleanup。
- 将本批真实语料与 Gateway 输出留在被忽略的 .superpowers/sdd/.../fixtures/，Git 仅提交可重复探针、测试和报告。

## Assessment

**Ready to accept B8.2?** Yes.

**Ready to merge the whole Qwen migration?** No; this review covers only the B8.2 isolated preflight. Later production implementation, integration and NAS deployment remain unstarted.

**Reasoning:** B8.2 的探针、自动化断言、运行证据和报告与当前范围相符，未发现当前变更中的 Critical/Important 问题。试验桥接中发现的身份/队列边界已明确归入后续批次，不能按原样复制。
