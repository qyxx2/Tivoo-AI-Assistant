# P6.6b5 — Tivoo 表情状态机全量验收与生产部署

日期：2026-11-16
分支：`feature/p6-6-tivoo-expression-state-machine`
基线：`2c32d09`（P6.6b4）
范围：P6.6b5 验证、生产部署、真机验收与文档收尾，以及同日针对 b5 暴露的 ESM-C19 stale 7777 恢复缺口所做的 post-b5 修复；未修改 ESP32 firmware/protocol，未刷写固件。

## 1. 结论

**P6.6b5 已执行；b5 暴露的 ESM-C19 生产缺口已在同日 post-b5 修复并完成 gate ON/OFF 真机复验。P6.6 仍不能标记为“完整真机验收通过”，原因只剩真人语音链未执行。**

自动化合同、HA/AstrBot 部署、生产 MCP 28 Tool、idle 定时切换、screen-off 硬门控与 ON 恢复均取得真实证据。b5 原始验收曾发现：ESP32 单独硬重启后 7778 能自动重连，但 HA 侧旧 7777 control socket 可持续保持 ESTABLISHED，导致 SPP/winner 不恢复。根因确认后，transport 现在使用**已校验的 ESP32 `DEVICE_STATUS.tcp["7777"]`**与 HA 本地 control 状态对账；只有 ESP32 明确报告 7777 disconnected、而 HA 仍认为 connected 时，才关闭 stale writer 并复用既有 control reconnect + Bluetooth MAC 握手流程。该修复已通过自动化 RED/GREEN 与两次真实 ESP32 hard reset。

此外，本次会话没有可替代真人物理讲话的输入，因此 KWS→STT→thinking→真实 TTS playback→speaking→follow-up、TTS 播放中真人 KWS 打断、真实 AstrBot tool phase、active-generation mood 三项生产语音链路按计划记为 **GAP / NOT RUN**；已有自动化证据保持 PASS，不伪装成真机结果。

## 2. 本地验证

| 验证 | 结果 |
|---|---|
| `./scripts/test-ha.sh -q tests/homeassistant/custom_components/tivoo tests/homeassistant/custom_components/astrbot` | **441 passed, 0 failed**, 235 warnings |
| `./scripts/test-ha.sh -q tests/homeassistant/test_assist_pipeline_tts_cancellation.py tests/homeassistant/custom_components/tivoo/test_assist_satellite.py` | **33 passed, 0 failed**, 17 warnings |
| P6.6 从 `0fafc20` 起实际改动的 22 个 Python 文件：Ruff check | **PASS** |
| 同 22 文件：Ruff format --check | **PASS** |
| Tivoo/AstrBot compileall | **PASS** |
| `pip check` | **PASS — No broken requirements found** |
| `git diff --check` | **PASS** |
| C19 post-b5：`test_transport.py` | **25 passed, 0 failed**；含新增 stale-control reset 回归 |
| C19 post-b5：Tivoo 全量 | **342 passed, 0 failed**, 169 warnings |

全目录 Ruff 仍报告 27 个历史问题，全部位于未被 P6.6 修改的 `presets/emotion_presets.py` 与 `presets/presets.py`；`git diff 0fafc20..HEAD -- homeassistant/custom_components/tivoo/presets` 为空。该基线不在 b5 范围内，本批没有为了“全绿”顺带修改 preset 素材代码。

## 3. NAS / 生产部署

- 目标：Synology NAS `192.168.3.94`，HA `ghcr.io/home-assistant/home-assistant:2026.11.0`。
- 部署前备份：`/volume1/docker/tivoo-backups/p6-6b5-pre-20261116-104237.tar.gz`。
- 仅覆盖 `/config/custom_components/tivoo` 与 `/config/custom_components/astrbot`；生产容器内 compileall **PASS**。
- 仅重启 `homeassistant`；HTTP 恢复 **200**。
- 部署后 7777 / 7778 均恢复 ESTABLISHED；最终恢复检查分别使用新的本地连接端口，日志未发现新增 Tivoo/AstrBot traceback、protocol error 或 reconnect loop。
- AstrBot 现有 `mcp_server.json` 继续使用 `streamable_http` → `/api/mcp/assist`；未输出 Authorization token。
- 使用生产 AstrBot 保存的 MCP 配置直接执行 initialize/list_tools：**28 个 `tivoo__*` Tool，且包含 `tivoo__SetMood`**。恢复后的最终复核结果仍为 28 个。
- 生产 MCP 在无 active voice generation 时调用 `tivoo__SetMood(happy)` 返回 `isError=true`，文本明确为 `Tivoo mood requires an active voice generation`；未改变设备显示。
- 没有发现 Persona 中显式 Tivoo Tool allowlist，因此没有修改 Persona。

## 4. 真机显示链路证据

### 4.1 idle

保持无人工显示调用时抓取 HA→ESP32 `7777`：

- 第一次独立显示 burst：epoch `1794797257.600595`，513 bytes。
- 第二次独立显示 burst：epoch `1794797333.165513`，266 bytes。
- 间隔约 **75.565 秒**，落在 30–90 秒合同范围内。

NAS `tcpdump -i any` 会把同一包显示两次，因此以 timestamp/seq 去重；这里只证明 HA→ESP32 transport 写入，不声称 Tivoo 物理像素 ACK。

### 4.2 screen-off / desired / ON 恢复

真实生产 HA Service + 7777 抓包：

1. `tivoo.set_screen_power(false)` → HTTP 200；捕获一个独立 **17-byte** 电源写入。
2. OFF 期间调用 `tivoo.set_expression(name=happy)` → HTTP 200；7777 **0 个 payload packet**，证明只更新 desired，没有显示写入。
3. `tivoo.set_screen_power(true)` → HTTP 200；先捕获 **17-byte** 电源写入，随后 **266-byte** 当前 winner 重绘。

多 owner / temporary wake 的组合由自动化测试覆盖；生产只实际操作兼容 bool owner，符合计划边界。

## 5. ESP32 reset / SPP reconnect 验收

NAS 已有 `tivoo-esptool:4.8.1` 使用 `/dev/ttyACM0`。执行：

`python -m esptool --chip esp32 --port /dev/ttyACM0 run`

只进入 ROM/stub 并 **Hard resetting via RTS pin**，没有 `write_flash`。

串口证据确认 ESP32 重启、Wi-Fi 重新连接并取得 `192.168.3.28`。7778 从旧连接切换到新 source port，证明 diagnostic channel 实际重建。7777 却继续保留重启前的旧 HA socket；随后重复显式显示请求没有产生 7777 payload，串口窗口内也没有看到 SPP connected。

代码与实测共同定位到恢复缺口：validated `spp_disconnected` 会令 Coordinator 停止显示发送，而 7777 control loop 没有 heartbeat；没有后续 write 就没有错误触发旧 socket 退出/重连。**这是 b5 当时的真实 GAP。**

为恢复当时生产状态，b5 随后只重启 HA；7777/7778 建立新连接。该动作只用于恢复生产，不被算作 C19 通过。

### 5.1 C19 post-b5 修复与复验

修复不新增 heartbeat，也不耦合 7777/7778 的正常独立重连。新的规则只处理一个已校验的状态冲突：当 ESP32 新的 `DEVICE_STATUS.tcp["7777"] == "disconnected"`，而 HA 本地 `states["control"] == "connected"` 且仍持有 writer 时，以 ESP32 侧状态为准关闭 stale writer；既有 control loop 随即重连并重新发送 Bluetooth MAC。普通 7778 重连若 ESP32 仍报告 7777 connected，不触发 control 重连。

TDD 证据：

- RED：新增 `test_device_status_recycles_stale_control_socket_after_esp32_reboot`，修复前 **1 failed**，只观察到第一次 7-byte MAC 握手，第二个 diagnostic session 报 7777 disconnected 后没有第二条 control 连接。
- GREEN：新增测试 + diagnostic heartbeat 独立性 + DEVICE_STATUS 状态测试 **3 passed**。
- 完整 `test_transport.py`：**25 passed**。
- Tivoo custom-component 全量：**342 passed, 0 failed**。
- 变更文件 Ruff check / format、compileall、`git diff --check`：**PASS**。

生产只部署更新后的 `transport.py`，部署前备份为 `/volume1/docker/tivoo-backups/transport.py.pre-c19-20261116-111804`；HA 重启后 7777/7778 正常 ESTABLISHED。

**gate ON 真机：**

- reset 前：`48508→7777`、`36174→7778`，当前 explicit winner 固定为 `happy`。
- 使用 esptool `run` 仅 hard reset ESP32，不写 flash。
- HA 未重启；约 19 秒后自动形成新连接 `49510→7777`、`37098→7778`。
- 新 7777 先发送 **7-byte** Bluetooth MAC 握手，随后约 1.37 秒自动发送 **266-byte** 当前 `happy` winner。
- 因此 gate ON 的“reset → stale 7777 回收 → control/SPP 恢复 → winner 重发” **PASS**。

**gate OFF 真机：**

- 先调用 `tivoo.set_screen_power(false)`；reset 前为 `49510→7777`、`37098→7778`。
- 再次仅 hard reset ESP32；HA 未重启。
- 约 14 秒后自动形成新连接 `50366→7777`、`38148→7778`。
- 新 7777 只观察到 **7-byte** Bluetooth MAC 握手与随后 **17-byte** OFF 重申；没有 266-byte winner 显示包。
- 因此 gate OFF 的“reset → reconnect → 保持 OFF” **PASS**。

复验结束后调用 `tivoo.set_screen_power(true)` 恢复原测试前亮屏状态；7777/7778 保持 ESTABLISHED，HA 日志无新增 Tivoo traceback / protocol error。以上抓包仍只证明 HA→ESP32 transport 写入，不宣称物理像素 ACK。

## 6. ESM-C01–C23 复核

| 合同 | b5 结论 | 主要证据 |
|---|---|---|
| C01 | PASS | 自动优先级/恢复测试；ON 后重绘真实 transport |
| C02 | PASS | idle 自动化 + 生产两次独立 idle burst |
| C03 | PASS(auto) / GAP(runtime candidate) | 30–90 s 实测 75.565 s；700 ms/35%/10 s 自动化 |
| C04 | PASS(auto) / GAP(runtime voice) | KWS/side-KWS 自动化；本批无真人语音 |
| C05 | PASS(auto) / GAP(runtime voice) | STT_END thinking 自动化；本批无真人语音 |
| C06 | PASS(auto) / GAP(runtime tool phase) | AstrBot phase/context 自动化；未完成真人 Satellite 工具调用 |
| C07 | PASS(auto) / GAP(runtime playback) | playback-id / AUDIO_STATE 自动化；本批无真人 TTS 链 |
| C08 | PASS(auto) / GAP(runtime follow-up) | 8 s follow-up 自动化；本批无真人链 |
| C09 | PASS | 固定优先级自动化 |
| C10 | PASS | stale generation / delayed event 自动化 |
| C11 | PASS(auto) / GAP(active-generation runtime) | 5 s mood TTL 自动化；未伪造 active voice generation |
| C12 | PASS | 14 mood whitelist 自动化 |
| C13 | PASS | 生产 MCP 28 Tool + SetMood；delegation 自动化 |
| C14 | PASS | OFF 缓存 `happy`，ON 后真实重绘 |
| C15 | PASS | OFF 期间显式内容 0 个 7777 payload |
| C16 | PASS | 既有 golden tests；生产 off/on 17-byte transport |
| C17 | PASS | 多 owner 自动化 + 生产 compatibility bool |
| C18 | PASS(internal) | temporary wake 自动化；公开接口仍按合同延后 |
| C19 | **PASS** | HA reload/restart 恢复 PASS；post-b5 修复后 ESP32 单独 reset 的 gate ON winner 恢复与 gate OFF 重申均真机 PASS |
| C20 | PASS | desired/last_sent 自动化；报告不宣称像素 ACK |
| C21 | PASS | preset 映射与状态自动化 |
| C22 | **DEFERRED** | 主动 announce/start-conversation 明确不属于 P6.6 |
| C23 | PASS(auto) / GAP(runtime voice) | P6.5 cancellation/Assist 33 passed；P3/Tivoo/AstrBot full 441 passed |

## 7. b5 Exit Gate

- 自动化非预留合同：**PASS**；C19 post-b5 回归已加入并通过。
- 生产部署、28 MCP Tool、idle、screen OFF/ON：**PASS**。
- ESP32 单独 reset 后 7777/SPP 自动恢复：**PASS**，gate ON/OFF 均有真机证据。
- 真人完整 voice/tooluse/interrupt/mood 链：**GAP / NOT RUN**。
- ESP32 firmware/protocol：**未修改、未刷写**。
- 主动 announce/start-conversation：**DEFERRED，未实现**。

因此 C19 已关闭。P6.6 当前仍属于 **implemented with remaining runtime voice acceptance gaps**，不能标成 full real-device accepted；剩余原因不再包含 7777/SPP reset 恢复。
