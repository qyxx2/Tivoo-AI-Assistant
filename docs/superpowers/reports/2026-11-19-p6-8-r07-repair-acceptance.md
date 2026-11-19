# P6.8 R07 修复验收 — 轮次身份、拒绝发送、超时与诊断

- 执行范围：R07.1–R07.5；F11/F12，B5-R05/R06、B7-R01/R05；VOICE-C01/04/05/07、LIFE-C01/03/07/08、B0.5 §3.1、T05-C/T06-B/T07-A/C/D。
- 基线：70dd4dd5f2bd3d987bc0c9b955c0e36a75ac6160（R06），feature/p6-8-s3-local-wake。沿用既有工作区、SDK 与测试环境；保留原 B1–B10 计划既存未提交的链接变更。
- 方法：Superpowers executing-plans、systematic-debugging、test-driven-development、receiving-code-review、requesting-code-review（无独立子代理，按审查清单自审）、verification-before-completion。软件专项，不代表实机通过。

## R07.1 / R07.2：轮次与拒绝发送

原问题经实际测试复现：过期 UUID 的 ACTIVITY 在身份筛选前读取/验证字段，异常可中断 RX；当前重复 gate/activity 的冲突被误当幂等；非法 followup 的定向 stop 在 reader 内等待发送，异常和挂起影响后续合法帧。

- ACTIVITY 先校验 UUID、筛除非当前轮，再解析 payload；旧轮的坏 state/uptime 不影响新轮。当前非法字段、冲突 gate（uptime/prompt_result）、冲突 speech start/end（uptime、PCM 样本数）仅停止当前轮，完全相同的已知合同字段重复不重复 callback。START 保留 monotonic uptime / UUID 去重，协议方向和 schema 不变（实际常量 0x24 ACTIVITY／0x26 COMMAND_GATE；原计划接口行的合并标注修正为各自编号）。
- 无有效 parent grant 的 UUID 不归属 ingress；同连接内记为已见，防止迟延/重复 START 重新占有轮次。定向 0x23 通知异步 best-effort，复用既有 5s stop 通知上限；不等待远端通知才进行本地清理，不增加 ACK。断线/unload 取消未完成的拒绝通知，重连清空 epoch 去重历史。
- 7778 write lock 前捕获 writer，取得锁后验证仍为同一 writer，防止旧等待者写入新连接。已 write 的发送序号即使 drain 超时也不回退。正常诊断 teardown 仍沿用原路径。
- 真 loopback TCP 测试分别注入 HomeAssistantError、write-lock 挂起、真实 adapter drain 挂起；一次读入非法 followup、下一新 START、旧非法 ACTIVITY、新 gate。断言在拒绝通知仍挂起时已接收新 gate、当前 UUID 不变；通知结束后断线重连、低 uptime 的合法 START 与 gate 恢复；7777 控制连接始终同一条。另有已取消的拒绝通知与新 epoch UUID 循环、旧 writer 等待者不能写新 socket 的断言。

## R07.3：S3 实际 turn pump

原 pump 在已超时/aborted 且从未成功入队 START 时仍会先尝试 START，造成 HA 迟到开轮。现直接令本地 turn 失效；没有远端 owner 时不发 ABORT。已发 START 的失败轮仍重试匹配 ABORT；保留现有 FIFO、每次最多 8 PCM 帧、pending 上限和 1s/3s/15s 合同。测试使用实际 C turn 与阻塞 send seam，断言短时阻塞恢复的顺序及帧内容、过期未入队 START 不出现、已入队 START 有定向 ABORT、已成功发送 speech_start 后 PCM 挂起直到发送截止时间并丢弃 pending。原 timeout/overflow 测试明确先发 START 再断言 ABORT，并非删除历史保护。

## R07.4：逐轮诊断

S3 仅在首次输入终态输出一条 turn_metrics（session、epoch、outcome、ready_latency_ms、gate_ready_wait_ms、peak_pending_samples、send_failures、send_attempts、start_sent）；未完成输入的替换/断线同样有终态。ready latency 为唤醒至接受 ready；gate 等待为 gate 至 ready（ready 先到记 0），不可测记 -1。pending 为 PCM 样本数高水位（包含尾部 padding）；send 失败次数/尝试次数统计截至首次终态决定，包含已进行的 ABORT 尝试，不将后续重试重复计入轮次。日志中 ready_timeout 轮数 / 总输入终态记录数即超时率，非 input_complete 的轮数 / 总记录数是输入非正常完成率，非最终语义成功率。假时钟三轮 host 日志（turn-metrics-host.log）断言：1 次 input_complete，ready 100ms、peak 320、send 0/5；2 次 ready_timeout（一轮未送出 START），无重复记录。此为测试分母 3、分子 2，不能当实机超时率或 P95。

HA retire_metrics 在捕获旧 turn 的 identity 失效时记录单调时钟，finally 记录 session/reason/duration_ms/clean，包含串行等待前 owner 与本轮实际 task/TTS close；clean 沿用原清理合同，不意味着通知送达或物理播放停止。假时钟断言只对应一次捕获的旧 UUID、旧迟到终态不再产生 retirement 记录。未引入监控服务或新 wire 字段。

## R07.5：验证证据

日志与产物目录：.superpowers/p68-r07/（本地忽略目录）。

| 阶段 | 证据 | 结果 |
|---|---|---|
| RED 身份/发送/FIFO | red-identity-fifo.log | 8 failed, 36 passed，exit 1；旧坏 ACTIVITY、2 个 gate 冲突、2 个 activity 冲突、拒绝 sender error/hung、C unsent START 断言 |
| GREEN 对应修复 | green-identity-fifo.log | 44 passed，exit 0 |
| RED 指标 | red-metrics.log | retirement/真实 S3 adapter 2 failed（缺少日志），exit 1 |
| GREEN 首次专项 | green-focused-first.log | 116 passed，exit 0 |
| GREEN 扩展专项 | green-focused-final.log | 124 passed，exit 0 |
| 最终 PCM 阻塞断言增强 | green-host-final.log | 2 passed，exit 0 |
| HA 全量 | ha-full.log | 577 passed，exit 0 |
| ESP 全量 | esp-full.log | 108 passed，exit 0（本次无 R05 历史诊断波动） |
| S3 默认构建 | s3-build.log | reconfigure/build/size exit 0；镜像 2106457 bytes，bin 2106576 bytes；DIRAM 196503/341760 |

复验命令（repo root）：

```bash
export PYTHONDONTWRITEBYTECODE=1
PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath" bash scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_p68_local_session.py tests/homeassistant/custom_components/tivoo/test_p68_lifecycle.py tests/homeassistant/custom_components/tivoo/test_transport.py tests/homeassistant/custom_components/tivoo/test_diagnostics.py tests/esp32/test_p68_turn.py tests/esp32/test_p68_prompt.py -q -p no:cacheprovider
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32/test_p68_turn.py -q -p no:cacheprovider
PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath" bash scripts/test-ha.sh tests/homeassistant -q -p no:cacheprovider
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32 -q -p no:cacheprovider
source ~/.espressif/tools/activate_idf_v6.1.sh
cd esp32/firmware
CMAKE_BUILD_PARALLEL_LEVEL=1 idf.py reconfigure
nice -n 5 ninja -C build -j1
idf.py size
```

构建归档 firmware/ 的 SHA256SUMS 已逐一校验 OK：
- ELF 6a4f8ff490f54a5cbecd9b5d60a918ac97ace7b0e323341ed3ef355a63398f18
- BIN c3db989104226dc581c0014c39c86a1ab0f2822a1ecbff80b5da3bc831b02e1a
- flasher_args.json 061fae2603918e686c1ce8fab3f529195936a08f9992a4a706183563549254f1

当前目标 ESP32S3；TEST_GATE、PROMPT_CALIBRATED、CALIBRATION_TRACE 均未启用。不修改 Classic 固件，不触发双目标 clean build。

## 审查与后续约束

自审实际 Git diff 和真实断言，未引入协议变更、跨 UUID 清理、ACK 或独立采集服务；保留 R06 drained EOF、已有播放 owner/epoch 检查及单调 uptime。R09 复用本批 loopback fixture 和退役 Future：拒绝通知可能晚于 START handler 返回，须等待通知 own task/settled（不能假定同步发送）；检查 rejected UUID 不成为 owner、合法 UUID 保持、旧 epoch writer 不提交及断线新 epoch 重置、旧轮 cleanup 完成才复用 owner。R09 仍需真实 ESP/HA/Sherpa 纵向工作流证据，不用本批单测替代。

R08–R11 未实施；不触及普通 TTS 资源 worker、全链路和表情裁决。保留真实双板、麦克风、生产 pipeline/网络、声学、时序 P95、真实 stop/资源回收、T01–T08 原硬件及部署 GAP。无 NAS、无部署、无刷写、无推送。
