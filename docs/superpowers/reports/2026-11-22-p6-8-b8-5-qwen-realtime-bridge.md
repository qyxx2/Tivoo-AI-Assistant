# P6.8 B8.5 — HA Qwen Realtime Bridge

日期：2026-11-22；基线：`5a7a198`；分支：`feature/p6-8-s3-local-wake`。

**结论：B8.5 软件交付 PASS。** 完成 bridge、local-wake Satellite 接入、一次性有界 PCM HTTP 资源、最小 Gateway 兼容补丁及 Prompt overlay 片段。只执行 B8.5。没有修改 NAS 安装包/环境/Prompt、重启服务或刷机，未进入 B8.6/B8.7/B9。

## 门禁与用户决策

首先用锁定 Qwen 2.1.0 原始 runtime 复现合同矩阵 §2.1：启用/禁用播放回执时，先输出最终问句，再以 completed/cancelled/incomplete 结束，客户端可收到相同事件。工具中间响应也可包含最终问句和 audio.done。原版门禁保持 HOLD。

复现入口：`node tests/integration/qwen_realtime/terminal_gate.mjs /path/to/qwen-audio-agent-v2.1.0`。原版预期退出 2，明确输出 HOLD；这是原版缺口诊断，不是补丁验收命令。

用户随后明确批准“允许最小兼容补丁，继续完成 B8.5”，调整原计划“不实施新接口”的限制。选定方案保留 GCP 7.0/既有 audio.done，增加 capability `response.terminal-status`，以及 `responseStatus`、`awaitsToolFollowUp`、`hasFunctionCall` 字段。没有创建新事件类型、服务、工具接口或设备协议。

NAS 使用用户提供 IPv6、已有 HostKeyAlias=192.168.3.94、StrictHostKeyChecking=yes 只读查询。运行包仍为 2.1.0，presentation/session runtime 与 realtime-events、gateway-events、gateway-client-protocol 五文件 SHA256 均与锁定 commit `a9f4478da8df400d04facbb099ac2933ce8b11bc` 一致。原文件 hash、补丁与复现脚本在 `deploy/nas/qwen/patches/`。没有读取/记录真实凭据。

**门禁核销范围：补丁源码副本 PASS，原 NAS 未安装仍 HOLD。** HA 明确要求 capability 回显及严格终态字段，原版 Gateway 无法被误当作兼容部署。

## 已交付行为

- ConfigEntry 持有一个 Gateway socket。URL sessionId=entry_id；client.instance_id=`tivoo-<entry_id>`，每轮 MIC UUID/HA Context/playback UUID 仍独立。握手检查 GCP 7.0、hello 关联、voice.ready 顺序、16 kHz 输入、能力和错误；处理相关联的 ping/pong。
- 生产 local-wake runner 跳过旧 Pipeline 验证及 STT/Intent/TTS。沿用 ingress subscription、pull 时 STT_READY、本地 gate/EOF 和旧 owner 清理屏障。旧非 local 测试/接口保留；生产 setup 必须注入 bridge，没有旧链路 fallback。
- 输入只读当前 subscription 的 PCM16，正常 EOF/drain 后追加 50 × 640-byte、20 ms 静音帧（1000 ms）。早到输出只缓存；EOF 前不发 TTS_PLAY。同 MIC 第二个不同 turnId 失败收口。
- 输出只接收实际 24/32 kHz mono S16LE，base64 严格解码、原样交付 ESP32 的对应 MIME，不在 HA 重采样。工具中间响应不结束整轮 PCM；普通成功需精确 final 文本、正常终态、所有相关 response/audio 排尽、HTTP 完成与匹配设备 completed。
- 正常工具受理语音 `hasFunctionCall=true/awaitsToolFollowUp=false` 可以结束 PCM，但等待已观察工具全部成功，再返回 `followup_eligible=false` 并关闭 socket；不等待上游已抑制的第二次回复，不将工具文字用于续聊。
- 一次性 `/api/tivoo/qwen/audio/{stream_id}` 随机 UUID GET；字节上限 **512 KiB**，重复 GET 拒绝，采样率流内一致。finish/cancel 使用独立 EOF/abort 标志，不向满队列等待 sentinel。当前 MIC/generation、response 集合及 playback UUID 关联保留在输出 owner/resource。
- GET 等待 10 s；单次 HTTP 读/写停滞 10 s；Gateway/物理完成无进展 45 s；整轮 120 s；定向 stop/socket close/HTTP join 各 5 s。异常/取消/卸载撤销缓存、定向 AUDIO_STOP、response.cancel、关闭连接并 join 子任务/HTTP handler，移除映射。重复 close 幂等。一次性 URL 不进入本模块日志或持久状态，日志只记录 generation/字节数/阶段毫秒数。
- 显式成功保留接口 `owner.keep_socket` 与匹配 parent_session_id 移交测试覆盖同 socket、新 MIC、旧事件隔离、旧 owner retire、缺失连接拒绝重连和保留超时（5 s）。当前 Satellite **不设置**该标志；B8.6 再接问号策略、4 s gate 与 0x27。
- `deploy/nas/qwen/prompt-overlay.md` 仅为片段；B8.7 追加到完整锁定 PROMPT.md 副本，校验 16,000 字符上限后安装。本批没有替换 Prompt。

## 验证

遵从用户要求，没有执行全量测试。最终本地结果：

| 定向验证 | 结果 |
|---|---|
| HA bridge、Qwen Satellite、原 Satellite、audio_session、local_session、lifecycle、transport、prompt_audio 八文件 | **200 passed**，8 个上游依赖/HA 既有 warning |
| Gateway 终态补丁及 protocol/presentation/session 定向回归 | **100 passed**；原版 RED 20 个预期断言失败、1 个兼容用例通过 |
| 新 Python 模块/测试与 setup Ruff、Shell syntax、Node syntax、git diff --check | PASS |

HA 命令：

```bash
PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath" bash scripts/test-ha.sh \
  tests/homeassistant/custom_components/tivoo/test_qwen_realtime.py \
  tests/homeassistant/custom_components/tivoo/test_qwen_satellite.py \
  tests/homeassistant/custom_components/tivoo/test_assist_satellite.py \
  tests/homeassistant/custom_components/tivoo/test_audio_session.py \
  tests/homeassistant/custom_components/tivoo/test_p68_local_session.py \
  tests/homeassistant/custom_components/tivoo/test_p68_lifecycle.py \
  tests/homeassistant/custom_components/tivoo/test_transport.py \
  tests/homeassistant/custom_components/tivoo/test_prompt_audio.py -q -p no:cacheprovider
bash deploy/nas/qwen/patches/test-terminal.sh /path/to/qwen-audio-agent-v2.1.0
```

新增 bridge 专项 **40 项**、Satellite **6 项**。HTTP 使用真实本地 aiohttp server/client 覆盖单次原样流、重复 GET、消费者断连、写入阻塞时取消并 join；Gateway 和 ESP32 是协议边界 double。覆盖无 GET、满字节缓存、异常采样率/base64/PCM、取消/不完整终态、工具续接、晚文本、缺失文本或物理回执超时、定向 stop 失败仍关闭 WS、heartbeat、同 socket 显式移交等。

## 独立审查与修正

独立 reviewer 无 Critical，发现两项 Important，均先复现 RED 再修正 GREEN：

1. 有效用户转写后遗留 45 s STT finalize timer：在接受当前有效 user transcript 时取消，若 transcript 早于 EOF 则 EOF 不重新 arm。`test_user_transcript_cancels_stt_deadline_while_playback_pending` 验证等待播放期间跨过 45 s 仍不被中止。
2. 工具受理语音没有第二次回复时 PCM 悬挂：区分交付结束与续聊资格，等待工具终态；`test_tool_acceptance_without_second_response_finishes_delivery_only` 覆盖 completed/failed 两路径。

执行中额外专项也复现并修正设备 stop 发送失败跳过 WS close、取消未 join 正在写 HTTP 的 handler。全部受影响定向回归最终通过，无延后 Minor。

## 实施判断与保留边界

按用户当前工作区要求在现有 feature checkout 执行；全量测试要求由用户的“除非必要排除全量测试”覆盖。B8.5 的连接保留只提供可验证接口，不提前实现 B8.6 的产品授权。最小补丁由本次明确授权纳入本批，安装仍留 B8.7；判断若不符合后续部署版本，应停止应用补丁并重新核对 capability/hash，不放宽成功条件。

未声称真实模型→HA→ESP32 的端到端部署已完成；真实 NAS MCP 配置、Prompt 合并、固件/音质和实际长回复播放验收由原 B8.7 范围负责。B8.4 保留的实机 SRC/音质 GAP 不在本批关闭。
