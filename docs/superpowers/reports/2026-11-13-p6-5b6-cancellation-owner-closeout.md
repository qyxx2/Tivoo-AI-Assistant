# P6.5b6 取消链路验收

- 日期：2026-11-13
- 分支：`feature/p6-5-ha-cancellation-preflight`
- 结论：**B6 验收通过。单轮 TTS 本地集成验证和真实 AstrBot 4.29.4 partial-output Stop 均已完成。**

## 单轮 TTS 取消

HA Core 2026.11.0 的 `tts.async_get_stream` 只能按 token 取得 `ResultStream`。Core 的 TTSCache 启动后台 producer 后不保留该任务句柄，Pipeline 失败时只删除 token。B6 在 `RUN_START` 同步取得该轮的流，仅对由 Tivoo 包装的流式 Wyoming run 接管 producer 和 cache。适配器锁定 HA Core 2026.11.0，沿用 HA 原生 `/api/tts_proxy/{token}`、Wyoming 消息编解码和 HA WAV→MP3 FFmpeg 转码。后续 Satellite 将同一 `PipelineTtsEvents` 实例绑定给事件回调，并用 `async_run` 包住公开 Satellite caller。

取消 caller 或调用该实例的 `async_cancel(playback_id)` 时，停止旧轮的资源通知和音频交付，清空已排队的 Proxy 数据，取消并等待 Wyoming 文本 writer。Wyoming 请求发送 TCP FIN 并保留读端。P7A 在清理 request、input 和 model worker 后关闭连接，HA 读到 EOF 后完成 FFmpeg writer、进程、pipes 和 producer 的收尾。未在 15 秒内确认 Wyoming EOF 时，按清理失败处理。单次 HTTP GET 关闭仅清理它自己的 consumer queue。P7A 在收到 `SynthesizeStop` 后继续读取 TCP，因此合成期间仍能处理 EOF。输入队列连续满 1 秒会结束该连接并取消请求，避免模型阻塞时连接无法进入清理。

## 本地验证

- HA Core 2026.11.0 与 FFmpeg 8.0.1。原生 WAV 正常完成和取消缺口对照保留。另验证 Tivoo owner 的正常 WAV 流能完整下载。
- 用真实 HA Pipeline、Proxy、FFmpeg 和 P7A Wyoming TCP handler 验证活动 MP3 取消。AstrBot SSE 与声学模型使用可控替身。Proxy 返回 `audio/mpeg`，截取的响应数据由独立 FFmpeg 进程解码为 PCM。第二条 GET 在响应写入期间断开，只移除自己的 queue，第一条 GET 和 producer 仍可用。
- 两种取消入口分别运行。错误 playback ID 无法取消旧轮。取消后 producer、文本 generator、转码 generator、FFmpeg 输入 writer 和进程、Wyoming writer、HTTP queue 及 P7A 请求退出。P7A 合成 callback 在观测到 TCP EOF 后才释放，返回 0，旧轮没有新的 `TTS_PLAY`。已发送到客户端或进入网络缓冲区的字节由播放器侧停止机制处理。
- 单独验证已收到 `SynthesizeStop` 和输入队列拥塞时的 TCP EOF。修复前 callback 无法及时收到取消，修复后 request、input 和 worker 退出，服务未发出正常完成事件 `SynthesizeStopped`。
- AstrBot fake HTTP/SSE 覆盖收到会话确认后、首条 plain 前取消及收到 plain 后取消，Stop 200 / 403 / 超时，以及 complete 后缺少 end。验证 reader 关闭、同 owner Stop 一次、取消传播、无迟到文本及锁释放。

## 真实 AstrBot 验收

通过 root SSH 在 NAS 本机对 AstrBot 4.29.4 的 HTTP API 执行一次性验收。测试脚本从 NAS 文件读取 API Key，并在 NAS 上通过 AstrBot 的 key hash 查到实际 owner。API Key 未传出 NAS。

| 验收项 | 实测结果 |
| --- | --- |
| Chat | HTTP 200，`text/event-stream`。依次收到 `session_id`、`user_message_saved`、`run_started` 和首条非空 `plain` |
| Stop | 收到首条 `plain` 后使用同一 Key 发起一次 Stop。HTTP 200，`stopped_count=1` |
| SSE 终止 | 发起 Stop 后持续读取 SSE。等待 Stop 响应期间收到 30 条 `plain`，收到成功响应后新增 `plain` 为 0，随后收到 `complete` 和 `end` |
| 会话状态 | HTTP 200，creator 匹配实际 API Key owner，`is_running=false`，`active_runs=[]` |
| 清理 | 使用匹配 owner 创建的两条临时会话经 DELETE API 返回成功。另两条初始探测使用了 HA 配置中与实际 Key owner 不一致的标识，Stop 和 DELETE 返回 `Permission denied`。按 UUID 和测试文本确认后，仅删除这两条临时会话及其关联记录。已确认四条临时会话均已清理 |

SSE 验收以收到 Stop 成功响应为边界。同步等待 Stop 的初次同 owner 探测曾读到 23 条积压的 `plain`，因此复测改用并行读取 SSE，以区分响应前后的接收计数。

## 回归结果

| 命令 | 结果 |
| --- | --- |
| `./scripts/test-ha.sh tests/homeassistant -q` | 328 passed |
| `./scripts/test-sherpa-wyoming.sh -q` | 130 passed |
| 修改过的 Python 文件 Ruff check、format check、compileall；`git diff --check` | 通过 |

额外 ESP32 host 回归独立运行时 51 项通过，`test_wifi_ip_loss_closes_both_ports_and_new_sessions_recover` 首次收到 TCP reset，单独复跑通过。通过 HA pytest 插件混跑时，`test_controlled_http_fixture_covers_stream_and_failure_responses` 被 socket 拦截，该用例在独立 ESP32 回归中通过。全仓 Ruff 仍报告两份未改动的 Tivoo preset 文件中的 27 项既有问题。
