# P6.8 R08 修复验收 — 普通 TTS terminal 和真实资源 worker

- 范围：R08.1–R08.3；F14 / B7-R02/R03；LIFE-C02/04/06/07/08、VOICE-C07、T07-A/B/D。
- 基线：60a1736e225ca455d47413ffab1c072b1a80ff21（R07），feature/p6-8-s3-local-wake。
- 方法：Superpowers executing-plans、根因追踪、test-driven-development、receiving-code-review、requesting-code-review 清单自审、verification-before-completion。无独立子代理工具，非独立复审。继续用户指定工作区，保留原 B1–B10 计划既存未提交链接。

## R08.1：终态丢失与同连接收敛

旧 send_audio_state 在 250ms 尝试后仅记录失败，连接仍健康时 HA matching playback owner 可能无限等待终态。实际 audio_resource.c worker 注入暂满/永久拒绝复现永久失败；再加入 active→pending 交接，复现旧 epoch 的 pending 仍可能领取 output 与启动 HTTP。修复优先采用既有诊断 teardown，而不另设 terminal 重播协议。

- 短暂拒绝仍沿用原 250ms 有界入队；JSON 分配或字段构造失败同样属于未入队。普通 TTS 的 terminal 未入队（包含本来不重试的拒绝终态）触发 matching epoch 失效；buffering/playing 仍 best-effort。没有伪造 completed，没有无限重试，没有固定播放总时长限制。
- tivoo_diagnostics_invalidate_mic 在诊断 mutex 内比较当前已 ACK 的 generation 和有效 fd，仅调用原 disconnect_client_locked：关闭 7778 当前连接、清理 ACK、generation 与消息队列；listener 仍拥有 fd 生命周期。旧 epoch 不关闭新连接。RX 在派发资源 handler 前已释放诊断锁，诊断发送 worker 不获取 resource mutex，未新增逆序锁；控制 7777 不被该函数触及。
- worker 接到已经退休的 pending 时不发布 fetching/buffering、不获取输出、不发 HTTP；领取输出前再次检查 generation。原 active/pending 串行交接、匹配的停止/释放、drain/quarantine 保留，旧轮终态不能变成新连接终态。实际 drain 完成与 terminal 传输送达仍是不同事实。
- HA 使用原 disconnect teardown：未收到匹配 completed 时不发 followup grant；连接失效后关闭 ingress/turn owner，不对已经断开的连接发送 stop，重连后旧 completed 对新 UUID 无效。不需要 HA 生产代码改动。

## R08.2：实际资源 worker 与协议证据

新增 p68_resource_worker_host.c 编译并运行真实 audio_resource.c，保留最小 RTOS/HTTP/decoder/output/诊断 seam，socketpair 使用真实 shutdown。test_local_resource_worker 九个参数：temporary、permanent、old_epoch、pending、pending_lost、timeout、normal、long_stream、matching_stop。断言终态 UUID/playback/epoch、释放 owner 后才发送、匹配 stop 与旧 UUID/epoch 隔离、HTTP socket 确实 shutdown、旧 pending 不建 HTTP/不发布 fetching、drain timeout/quarantine 不伪报 completed、pending 新 owner 正常接续、重复 stop、正常完成一次及模拟 8s EAGAIN 长流不中断。

诊断 simulator 真 loopback 测试 test_terminal_loss_invalidates_only_own_diagnostic_epoch：匹配失效关闭当前连接，重新 HELLO/ACK 后旧 epoch invalidate 无效，7777 原连接存活。p68_lifecycle_host normal_end 则使用实际诊断 parser/sender 与 socketpair，0x23 conversation_complete 调到实际 tivoo_s3_local_turn_stop，实际返回 0x22，逐帧验证类型/序号/UUID、仅一次、gate 关闭和 owner retire，新 wake 后旧 stop 无效。既有 turn fake 与 prompt 路径断言原样保留；复用 prompt SDK stub 生成函数，不增加第二套 SDK fixture。

HA test_local_grant_waits_for_both_playback_and_run[terminal_lost] 在既有 pipeline fixture 下验证 run 返回但未收到终态时，实际 manager disconnect 清理并禁止 grant；旧迟到 completed 不影响重连新轮。这个测试不是完整真实 public pipeline 与实际 C worker 的端到端组合；R09 仍需按计划完成。

## R08.3：验证记录

日志与产物目录：.superpowers/p68-r08/（本地忽略目录）。

| 阶段 | 日志 | 结果 |
|---|---|---|
| RED 永久入队拒绝 | red-worker.log | 1 failed、5 passed，exit 1；未触发匹配 epoch 失效 |
| RED 增加 pending_lost | red-worker-expanded.log | 2 failed、5 passed，exit 1；永久拒绝与旧 pending HTTP |
| GREEN 首轮专项 | green-worker.log | 16 passed，exit 0 |
| RED stale fetching | red-stale-status.log | 1 failed、8 passed，exit 1；旧 pending 多一次 fetching |
| 真 TCP epoch | green-epoch.log | 1 passed，exit 0 |
| 真正常结束 wire | normal-wire.log | 2 passed，exit 0 |
| HA 指定三文件 | ha-focused.log | 80 passed，exit 0 |
| ESP/HA 混跑 | focused-final.log | 128 passed、1 failed、1 error，exit 1；旧 HTTP fixture 被 HA pytest_socket 拦截 |
| ESP 全量独立 | esp-full.log | 118 passed，37 warnings，exit 0 |
| HA 全量独立 | ha-full.log | 578 passed，260 warnings，exit 0 |
| S3 reconfigure/build/size | s3-build.log | exit 0 |

混跑失败节点为 test_controlled_http_fixture_covers_stream_and_failure_responses（HASocketBlockedError），原断言未删改；独立 ESP 全量包括该用例，全部通过。测试警告保留日志（包括既有依赖弃用、pytest marker/config、aiohttp AppKey）；不作硬件故障判断。

复验命令（repo root）：

```bash
export PYTHONDONTWRITEBYTECODE=1
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32/test_p6_audio_resource.py -k local_resource_worker -q -p no:cacheprovider
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32/test_p68_turn.py -q -p no:cacheprovider
PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath" bash scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_p68_lifecycle.py tests/homeassistant/custom_components/tivoo/test_audio_resource.py tests/homeassistant/custom_components/tivoo/test_transport.py -q -p no:cacheprovider
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32 -q -p no:cacheprovider
PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath" bash scripts/test-ha.sh tests/homeassistant -q -p no:cacheprovider
source ~/.espressif/tools/activate_idf_v6.1.sh
cd esp32/firmware
CMAKE_BUILD_PARALLEL_LEVEL=1 idf.py reconfigure
nice -n 5 ninja -C build -j1
idf.py size
```

S3 默认配置：esp32s3，TEST_GATE/PROMPT_CALIBRATED/CALIBRATION_TRACE 均未启用；image 2106685 bytes，bin 2106800 bytes，DIRAM 196503/341760。归档 firmware/ 内 ELF、BIN、flasher_args.json 与 SHA256SUMS，sha256sum -c 全部 OK：
- ELF 885b1d8876d4af11303385f3e3abad69c97a05254977fc9aa9d5c5511fc6f45c
- BIN c8add1b951cdeb626a22d47722a4879323858f7b13adf386b7ec40a75ff2f688
- flasher_args.json 061fae2603918e686c1ce8fab3f529195936a08f9992a4a706183563549254f1

## 审查、交接与门禁

自审生产 diff、调用/锁边界与测试断言，无新增协议字段或公共 HA API，无并行 owner、无固定短播放期限；R03 output manager、R05 prompt 与 R07 turn 生产逻辑未修改。独立审查工具不可用，不能宣称独立 reviewer 通过。R08 软件验收通过，F14 软件修复完成。R09 复用真实 HA fixture、现有 7778 teardown/terminal failure、匹配 session/playback/epoch 与 0x23/0x22 边界；不得把本批 seam 等同完整真实链路。R09–R11 未执行。真实双板、DAC/HTTP/HTTPS/MP3、物理 drain、生产 TTS/AstrBot stop 及原硬件/部署 GAP 保留；未访问 NAS、未部署、未刷写、未推送。仅按计划构建 S3，未另做 Classic build。
