# P6.8 B8.1 合同矩阵审查报告

> **结果：审查工作完成；迁移放行状态 HOLD。** 本报告只核销 B8.1，没有执行 B8.2–B8.7，没有修改运行时代码或 NAS 配置。

## 1. 执行范围

- 分支：feature/p6-8-s3-local-wake
- 审查基线：9be427dcc85e3150ba16b65b6c44424cf2a968be
- 合同矩阵：../specs/2026-11-22-p6-8-b8-1-qwen-realtime-contract-matrix.md
- 迁移计划：../plans/2026-11-22-p6-8-qwen-realtime-migration-plan.md
- Qwen 上游：Qwen Audio Agent v2.1.0，commit a9f4478da8df400d04facbb099ac2933ce8b11bc
- Superpowers：按设备已安装的 using-superpowers、executing-plans、verification-before-completion 流程执行。当前 Remote Desktop Commander 没有可用子代理调度接口，因此按单批次逐项检查源代码和最终 diff。

本批次仅增加合同矩阵和审查报告，修正 B8.1 计划入口及与该批次直接相关的事件/身份错误。未将 test/qwen-realtime-audio-bridge 实验代码复制到生产分支，也未将其路由或方法当作现有接口。

## 2. 核验结果

| 检查项 | 结果 | 依据 |
|---|---|---|
| P6.8 新增 49 条合同数量 | PASS | P68-HB 15 + AFE 12 + VOICE 10 + LIFE 8 + VIEW 4；与 B0.6 交叉审查一致 |
| GCP 输入事件名 | PASS（纠正计划） | 客户端线上事件 input_audio_buffer.append；Gateway 内部归一化为 audio.append |
| VAD / PCM EOF 边界 | PARTIAL | HA audio_subscription 和 speech_end/drain 已存在；静音尾帧成功率和长度未做 B8.2 实测 |
| Qwen response/tool/audio 事件 | PASS（协议定义） | v2.1.0 GCP schema 定义 response.started、audio.delta、audio.done、transcript、tool.call；audio.done 不是物理 playback completed |
| Qwen session 身份 | PASS（项目映射） | URL query sessionId 与 Gateway owner/session journal 有源码依据；用 ConfigEntry.entry_id 映射，不虚构 HA ChatSession |
| HA Assist MCP | PASS（既有接口） | /api/mcp/assist 已有 P4 合同及普通非管理员 Token 的 Streamable HTTP tools/list/tools/call 测试 |
| 私网 HTTP + Bearer | BLOCKED（有后续实现路径） | Qwen 2.1.0 URL validator 当前拒绝 LAN HTTP；B8.3 需有边界的 opt-in patch 与策略测试 |
| 原始 PCM HTTP 输出资源 | PARTIAL | 0x30 TTS_PLAY 和设备 HTTP GET 存在；HA 当前只生成 /api/tts_proxy URL，没有 Qwen 原始 PCM 资源路由 |
| 24 kHz → 32 kHz SRC | PARTIAL | ESP Audio Effects SRC 当前被 MP3 解码路径调用；raw PCM 24 kHz 路径未实现 |
| 中断与 MCP 副作用 | PASS（取消边界已定义） | response.cancel 取消模型 response；session close 才 abort Gateway MCP toolScope；HA 已执行 Service 无通用回滚保证 |
| Owner 冲突 | PASS | 一个 Gateway owner 单活动 Client；不同 client.instance_id 占用时必须 fail closed |
| Follow-up 授权 | BLOCKER | LIFE-C06/C07 需要显式 continue_conversation=true；GCP 7.0 无对应字段或事件 |

## 3. 本次发现并修正的错误前提

1. GCP 客户端线上输入事件不是内部 audio.append，而是 input_audio_buffer.append；Gateway 内部才做别名归一化。
2. input_audio_buffer.speech_stopped / committed 是上游 Provider 侧事件，不是 GCP 7.0 客户端事件；不能在 HA WebSocket 上发送 Provider 消息或臆造 commit。
3. 当前 Tivoo AssistSatellite 每轮创建 HA Context()；Tivoo 集成没有 HA ChatSession / conversation_id 调用。长期 Qwen 会话映射到稳定 ConfigEntry.entry_id。
4. ownerId 是 Gateway 认证主体；sessionId 是对话历史分区；client.instance_id 是客户端 lease 身份；MIC session_id、HA Context.id 和 ESP32 playback_id 仍独立。
5. GCP 客户端取消事件是 response.cancel；interrupt 是 Gateway 内部归一化事件。
6. GCP 公共 server event 没有 response.done；audio.done 只结束某次 response 的音频生成，不表示整轮完成或设备播放完成。
7. HA 生产代码目前没有 Qwen raw PCM HTTP 资源路由；试验 worktree 的路径不能当作生产接口。
8. Qwen 2.1.0 当前不允许 RFC1918 HTTP + Bearer；需要 B8.3 实施有范围限制的 URL policy patch。
9. readOnly / approval 不是 Qwen Frontend MCP 有效配置字段，上游代码明确拒绝。HA Assist MCP 的真实工具权限由 HA 用户权限、Assist 暴露范围及实际 Tool/Service 校验约束。
10. 原 follow-up 显式授权在 Qwen GCP 中没有等价来源；不能把 audio.done、voice.state=idle 或 transcript.final 当作授权。

## 4. 验证与边界

- 对照 P6.8 生产 Python/C 代码、对应测试和原始新增合同规格逐项检查。
- 对照 Qwen Audio Agent v2.1.0 固定 tag 本地源码；未用 GitHub 当前 main 替代锁定版本。
- 只读参考独立 test/qwen-realtime-audio-bridge worktree；没有改动该实验工作树。
- 本批次没有生产运行时代码变更，因此不宣称 HA/ESP32 测试通过，也没有执行 firmware build、flash、NAS 部署或硬件播放验收。
- 收尾验证：合同 ID 计数、链接目标、未实现接口名称检查、git diff --check 和完整 Git status/diff 复核。

## 5. 放行决定

**B8.1 审查产物完成，Gate 仍为 HOLD。**

当前唯一必须先解决的产品合同冲突是 follow-up 授权：P6.8 只允许在显式 continue_conversation=true 且实际播放 completed 后打开 0x27 的 4 秒 gate；GCP 7.0 没有该字段或事件。自动为每次回答打开续聊会改变旧合同；直接禁用也会改变交互行为。B8.1 不代替用户决定，也不新增虚构事件或工具。

按迁移计划的门禁，B8.2–B8.7 本轮未开始；B9/B10 也未触及。需先确认 follow-up 产品策略，再把它写成由真实接口支撑的可测试合同，然后才可重新评估后续放行。

---

## 6. 2026-11-22 用户决策补充：Qwen 条件续聊方案 A

本报告 §5 的 Gate HOLD 是原始审查完成时的有效结论。随后用户明确选择方案 A，解决了“Qwen 路径是否保留条件续聊、如何表达续聊意图”的产品策略决策；本补充不改写原始审查事实，也不声称技术接口已完成实测。

### 已确定的应用层策略

- Qwen 核心 Prompt 的 P6.8 overlay 要求：只有确实等待用户补充、选择或确认时，最终面向用户的完整助手回复才以中文“？”或英文“?”结束；普通完成回复不得附加礼貌性反问。
- HA 只消费当前 generation 的助手 `transcript.final`，对 `content.rstrip()` 判断末尾是否为“？”/“?”。不读取 `transcript.delta`，不读取用户角色文本，不使用 `tool.call`、`audio.done` 或 `voice.state=idle` 作为续聊信号。
- 问号只表示当前 turn 的待续聊意图，不立即开放麦克风。继续保留原合同的有效 turn/输入 drain/正常 response/匹配物理 `AUDIO_STATE=completed` 条件，复用 `AudioSessionManager.grant_followup()`、`TYPE_FOLLOWUP_OPEN (0x27)`、单次 4 秒 local_followup gate 和现有独立 beep。
- immediate follow-up 保持原活动 Gateway WebSocket；新一轮仍创建新的 ESP32 MIC UUID、HA Context/generation 和 Gateway turnId/responseId。不要只保留 sessionId 字符串、关闭 socket 后再重连来代替同活动连接。
- 这是项目级 Prompt/应用层约定，不是 Qwen GCP 7.0 原生 `continue_conversation` 字段或结构化授权回执。未收到 final transcript、普通标点、失败/中断默认关闭；不新增工具、Client Action 或第二套状态机。旧 AstrBot/Pipeline 路径原有 `INTENT_END.continue_conversation` 不变。

完整设计：[Qwen Realtime 条件续聊设计](../specs/2026-11-22-p6-8-qwen-realtime-followup-design.md)。NAS 当前 Qwen Audio Agent 2.1.0 配置、Prompt loader 和一次真实只读工具探测：[Qwen Audio Agent 运行时核查报告](2026-11-22-p6-8-qwen-audio-agent-runtime-investigation.md)。

### 新的技术 Gate

产品决策已解决，B8.2 可以开始只读/预检和协议验证；但 B8.5/B8.6 生产实现仍不得开始，直到 B8.2 完成下列真实验证：

1. 锁定 NAS 当前 Qwen Agent 2.1.0，验证助手最终文本通过 `transcript.final` 抵达，且中文“？”、英文“?”、普通句号保留；字段中的 role、turnId、responseId 关联正确。
2. 在同一活动 Gateway WebSocket 上完成至少两轮实际输入/响应：第一轮结束后不关闭 socket，第二轮输入经原 socket 发出，确认第二轮能利用第一轮上下文，session/活动 socket 不变而 turnId/responseId 更新。
3. 将“普通应答完成后关闭 socket、同 sessionId/client.instance_id 重连时 journal 是否恢复”作为独立测试，不得替代第 2 项。
4. 工具调用中间 response 不触发续聊；只对工具结果之后最终面向用户的 assistant transcript 做标点判断。
5. response failed/cancelled/incomplete、最终文本缺失或当前 generation 失效时，默认不续聊。

**更新后的状态：B8.1 产品策略决策完成；B8.2 技术 Gate PENDING。** 本补充没有修改生产代码、NAS Prompt/配置或设备状态，没有开始 B8.2，更未开始 B8.5/B8.6。
