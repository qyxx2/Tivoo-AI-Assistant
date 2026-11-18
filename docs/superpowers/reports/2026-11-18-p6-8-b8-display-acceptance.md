# P6.8b8：表情事件来源（软件验收）

实现 e5c5d7775eeea805c8ba389fc8fb1b1d268e7c4d，基线 dc8a1cc，分支 feature/p6-8-s3-local-wake。依据 b0.5 §5/VIEW-C01–04、b0.2 transport/SPP 合同、b0.6 交叉审计及 b7 生命周期代码。开发机实际 HA Core 2026.11.0；保持 B7 固件源码、构建产物、wire schema 和生产配置不变。未连接 NAS、未部署、未刷写两块板，未进入 b9。

## 实现和验收边界

- **T08-A / VIEW-C01**：唯一 ExpressionCoordinator 保持原优先级、待机 preset/30–90s 与显式内容；本地 START 创建真实 wake question（不走 legacy candidate 概率/延时），gate 后真实 speech_start 原子清除 wake/followup 并 listening，speech_end 清 listening，只有已验证 endpoint/非空 STT_END 才 thinking，同时开放本地 reply mood；空 STT、错误、退出同步失效 generation。无命令/失败停止沿用 b7 的 session watchdog；legacy candidate 与原测试均保留。
- **T08-B / VIEW-C02**：local_followup START 不显示 wake，在新轮 COMMAND_GATE 后才 followup_wait；speech_start 原子转换。普通 TTS 由既有 transport 当前 session UUID、source=tts_http 与当前 turn playback ID 校验，playing 才 speaking，buffering/TTS_START/END/短 prompt 不置位。completed 立即清 speaking/tooluse、拒绝新的 mood；正常 run 返回与 playback terminal 双条件后清 generation，失败/打断定向清理。AstrBot phase 保留 satellite_id+Context.id 校验，本地有效 STT 后才允许 tool phase，INTENT_END 清 tooluse 并拒绝同 Context 迟到 phase；新轮同步换代，旧 callback/TTL/terminal 不修改新轮。无需变更协议或新增仲裁。
- **T08-C / VIEW-C03/04**：保留 public SetMood schema/name 白名单/5s TTL；核对 llm.py 实际将 LLMContext.context 透传 HA service，因而无需修改 llm.py。服务用实际 Context.id/parent_id 匹配 runtime 已见的 voice generation；已知旧 context 拒绝，无关联来源仅在当前有效 reply 时采用当前 generation。独立 MCP/手动调用无 voice ID，无法认定所有迟到上游请求；不猜造 ID。已见 Context 只在本 RAM runtime 生命周期存在，旧 runtime 的 gate/显式内容亦不承诺持久。原 screen owner、temporary wake、显式内容/preset/schema 保留；真实校验的 SPP MAC/status 才启用配置了 host 的新 runtime，关闭/重连时不继承 last_sent；拒绝 closing 的 stale 7777 writer。离线 OFF 重申 OFF，ON 重发赢家。SPP 状态 observer 的发送任务与诊断 RX 解耦，stop 取消并 join；同一个 display lock 按最新状态重算，慢 power write 后复查 gate/revision，unload 后排队任务不得再发送。已经进入 transport 的在途命令无法撤回；last_sent 仅是写入证明，实际屏幕变化留实测。

## 软件测试证据

| 检查 | 结果 |
|---|---|
| 首轮 RED：真实 listening/endpoint、completed、旧 context、未进入 reply 即 mood | 5 个预期断言失败 |
| 慢 SPP RED（修正 fixture 使用实际 MAC 配置后） | 1 失败：通知等待 display I/O |
| 首轮 GREEN | 6 passed |
| 自审 RED：tool phase 遗留、慢 OFF/ON 顺序、unload 后排队写 | 3 failed（含泄漏 timer 的 teardown error） |
| 自审 GREEN | 9 passed |
| 额外 RED：物理 terminal 后仍接受 mood | 1 失败；temporary TTL fake-clock 用例需让 timer 创建的 task 调度，修正测试等待，不改 TTL |
| 额外 GREEN + config reload 回归 | 13 passed（12 个 B8 专项 + 1 config） |
| HA 全量最终（追加 HA reload 专项前，生产代码完全相同） | 545 passed, 249 warnings，exit 0 |
| B8 最终专项（含追加的真实 HA runtime reload） | 13 passed, 7 warnings，exit 0 |
| T02/T07 ESP32 host 回归 | 27 passed, 5 warnings，exit 0 |
| Git diff --check / cached --check | PASS |

HA 首轮全量 539 passed、1 teardown error：test_reconfigure_adds_explicit_host_and_preserves_existing_media 中 Core async_update_reload_and_abort 计划异步 reload，测试未等待完成便退出 fixture，日志显示 setup/reload 未退出、TCP reconnect task 仍存活。单项在新代码复现，隔离 B7 基线同项 1 passed。测试保留全部原断言，补等待真实 config entry LOADED 并显式 unload；专项及最终全量均通过，不改变生产 config flow。原 HA / pytest 插件警告未改；无新增包。

B8 专项 node（tests/homeassistant/custom_components/tivoo/test_p68_display.py）：
- T08-A: test_physical_wake_listen_endpoint_and_stt[command / 空白]；原 test_display_state.py 中 idle rotation、priority/restore、candidate 不变。
- T08-B: test_followup_wait_only_at_gate_and_terminal_removes_speaking、test_tool_phase_ends_at_intent_end_and_old_context_cannot_change_winner；T07 原 test_p68_lifecycle.py / test_transport.py 的 current-session TTS/授权/旧轮结束回归包含在全量。
- T08-C: test_mood_rejects_known_old_context_but_preserves_manual_schema、test_local_mood_requires_valid_stt_reply、test_mood_is_not_accepted_after_physical_reply_terminal、test_spp_reconnect_does_not_wait_for_slow_screen_write、test_slow_power_write_does_not_send_before_latest_power、test_pending_recompute_cannot_write_after_unload、test_local_off_survives_wake_replacement_reconnect_and_expiry、test_new_runtime_waits_for_validated_spp_and_reasserts_off、test_ha_reload_initial_sync_uses_new_runtime_default_gate；原 services/LLM/MCP HTTP schema、mood TTL/owner/gate/transport tests 全部保留并回归。

命令（开发机 repo 根）：
```sh
PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath" bash scripts/test-ha.sh tests/homeassistant -q
PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath" bash scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_p68_display.py -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32/test_p68_uart.py tests/esp32/test_p68_turn.py tests/esp32/test_p5b3_control_bridge.py tests/esp32/test_p6_device_status.py -q
git diff --check
```

日志 .superpowers/p68-b8/：red.log、red-spp.log、green-first.log、red-review.log、green-review.log、ha-full-first.log、config-repro.log、config-baseline.log、red-final.log、green-final.log、ha-full-final.log、ha-display-final.log、host-t02-t07.log。新代码只改 HA；无需重新构建固件，没有将上批固件 SHA 当本批的新构建结果。无独立 reviewer 工具；依规格及 diff 自审，新增 RED/GREEN 见上。

## 保留 GAP（实机）

S3 与第二颗 INMP441 未到位，两板真实 UART→SPP、Tivoo 实际像素/息屏/亮屏、wake/打断/续聊在真实音频、慢 SPP/重连/HA reload 时的物理赢家及时序仍需 b10 核销；不宣称生产 PASS。现有已知 Context 绑定可验证，外部 MCP 无关联 ID 的延迟调用不能凭空区分；HA reload 默认内存 gate 是既定约束，不保证原 OFF 自动持久化。无需额外人工产品选择。只完成 b8 软件任务。
