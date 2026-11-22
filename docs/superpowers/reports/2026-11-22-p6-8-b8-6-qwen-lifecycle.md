# P6.8 B8.6 — Qwen 会话、打断与条件续聊生命周期

日期：2026-11-22；基线：`7e7a3f1`；分支：`feature/p6-8-s3-local-wake`。

**结论：B8.6 软件交付 PASS。** 本批只完成 B8.6，未进入 B8.7/B9。没有连接或部署 NAS、修改 Gateway/Prompt/MCP 配置、重启服务或刷机；真实模型、HA 和设备端到端验收仍归 B8.7。

## 已交付行为

- 复用 `_Turn.continue_conversation`，只使用 Bridge 验证过身份和正常终态的最终 assistant `transcript.final` 文本，按 `rstrip().endswith(("？", "?"))` 决定续聊。delta、用户文本、工具中间问句、idle/audio.done 不授权。普通标点、缺失文本、cancelled/incomplete/failed、工具失败、播放失败和网络断开均收口。
- Bridge 增加可选的本地 `on_result` 回调，在已有 input drain、正常最终 response、所有工具/response 完成、HTTP 结束和匹配设备 playback completed 屏障之后、socket 清理之前调用。Satellite 在该回调决定 keep_socket；协议没有增加事件或字段。文本晚于物理完成也能汇合；无最终文本仍超时失败。
- 复用 `grant_followup()`、0x27 和设备既有 4 秒 gate/beep，匹配物理 completed 后只授权一次。不新增授权状态机。授权的下一轮从 ingress 的 `on_end(reason=followup)` 传递父 MIC 身份，新 MIC UUID、新 HA Context/generation 在旧 owner 清理屏障后复用原活动 socket。
- grant 发送失败、handoff 超时、新 wake、设备断开或 unload 的 retire 只释放匹配 parent 的保留连接。保留期间收到 playback.clear、input.suspend、voice.deactivated 或网络断开，关闭连接并通知 Satellite 撤销 ingress grant。下一轮不能通过重连冒充原 socket 续聊。
- 用户 final 转写映射 thinking；tool.call received/running 映射 TOOLUSE，全部在途工具完成后才清除。只有匹配的设备 playing 才进入 speaking；物理 completed 仍是播放终态。旧 generation 回调忽略。
- 生成中、MCP 执行中、播放中被新 wake 打断时，继续通过既有 owner 定向 stop、GCP response.cancel、socket close 和任务 join 屏障收口后启动最新轮。HA 保持服务/显示/播放权限所有者，SetMood schema 与未关联 MCP 调用限制不变。
- ConfigEntry 的稳定 URL sessionId / client.instance_id 保持 B8.5 实现；普通独立 wake 使用新连接，同 entry 身份不变，不同 entry 分区不同。旧 Pipeline 的 INTENT_END.continue_conversation 路径不变。

## 验证

新增 `test_qwen_lifecycle.py`：使用真实 Satellite、AudioSessionManager、Bridge 和 Display Coordinator，仅替换 socket/设备线缆 I/O；共 30 个专项用例。覆盖中英文问号/末尾空白、句号、delta、错误 playback ID、重复 completed、同 socket 新身份移交、4 秒边界、超时/撤销/断网、生成/工具/播放打断、异常终态、缺失/迟到文本、最终工具问句、并行工具显示、grant 发送失败、shutdown、普通 wake 重连、entry 隔离与 occupied owner。

先在原代码运行得到问号/移交/撤销用例的预期 RED，再实现后 GREEN。并行工具显示用例也先复现 RED，再聚合 owner.tools 状态修正并 GREEN。测试启动最初直接使用 pytest 遇到既有 httpx/httpx2 插件加载冲突，改用仓库 `scripts/test-ha.sh`；测试构造中的 ready 时序、取消任务等待及 fixture 导入问题均已修正，最终整组回归通过。

最终定向回归命令：

```bash
bash scripts/test-ha.sh \
  tests/homeassistant/custom_components/tivoo/test_qwen_lifecycle.py \
  tests/homeassistant/custom_components/tivoo/test_qwen_realtime.py \
  tests/homeassistant/custom_components/tivoo/test_qwen_satellite.py \
  tests/homeassistant/custom_components/tivoo/test_assist_satellite.py \
  tests/homeassistant/custom_components/tivoo/test_audio_session.py \
  tests/homeassistant/custom_components/tivoo/test_p68_lifecycle.py \
  tests/homeassistant/custom_components/tivoo/test_p68_display.py \
  tests/homeassistant/custom_components/tivoo/test_p68_local_session.py -q
```

**198 passed，8 warnings，21.42 s，exit 0。** warnings 为 HA/aiohttp/backoff 的既有弃用和 NotAppKeyWarning。未执行全量测试、上游全量测试或固件构建。日志在忽略目录 `.superpowers/p68-b86/`。

变更 Python 文件的 Ruff check（忽略已有 BLE001）与 git diff --check 通过；两个 BLE001 均在基线已有的通用异常清理分支，本批未新增。独立只读审查未发现 Critical/Important；唯一并行工具显示问题已由 RED→GREEN 回归解决，无遗留审查项。

## 计划核销与边界

| B8.6 步骤 | 软件证据 |
|---|---|
| 1 身份/恢复 | 同 entry 独立 wake 两次连接的 sessionId/instance 稳定；不同 entry 隔离。真实 journal/history 重连恢复沿用 [B8.2 §5.3](2026-11-22-p6-8-b8-2-qwen-gcp-pcm-preflight.md#53-断开重连-journal-恢复)，本批未对假 socket 声称验证上游历史。 |
| 2 owner/能力/心跳 | occupied 拒绝且不上传、不主动开第二 Client；既有能力及 ping/pong 回归。真实同实例替换/不同实例占用沿用 B8.2 lease 预检，生产复验留 B8.7。 |
| 3 生命周期显示 | user final、工具状态、实际 playing/completed、并行工具回归。 |
| 4 打断 | 生成、工具和播放三阶段新 wake；response.cancel、旧连接关闭、任务 join、新 generation 隔离。 |
| 5 条件续聊 | 最终文本/成功屏障、一次 0x27、4 秒 gate、新 MIC/Context、原 socket 移交及失败关闭。 |
| 6 HA 权限 | 未改变 HA MCP/服务接口或设备控制协议，沿用已有 HA 所有者。 |
| 7 mood 关联 | 未改 SetMood/Context schema，已有旧 Context 拒绝与手动 schema 测试通过。 |
| 8 断开/重启 | 网络关闭、保留连接撤销、旧连接事件隔离、shutdown、ConfigEntry unload/reload 回归。真实 Gateway 重启/lease replacement 与实机诊断断线验收留 B8.7。 |

实施判断：当前工作区继续，不另建 worktree；按用户要求用定向回归替代技能默认全量测试。最终文本标点在已验证最终响应汇合点计算，避免把工具中间 response 问句临时当作授权意图；无需第二套解析/状态机。如果后续改为更早记录意图，仍必须保留全部成功屏障。原 NAS 的终态 capability 补丁尚未安装，不能把本批软件 PASS 当作生产放行；B8.7 必须核对补丁、Prompt、MCP 与真实设备验收。
