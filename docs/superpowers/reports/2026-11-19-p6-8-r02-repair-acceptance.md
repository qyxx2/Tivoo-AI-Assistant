# P6.8 R02 UART/SPP 连接与可信状态修复验收

日期：2026-11-19；feature/p6-8-s3-local-wake；基线 a5dd5c31897f172c1c0008616fd562e34f1f201f（R01）。依据 [R02 执行计划](../plans/2026-11-19-p6-8-review-repair-execution-plan.md)、[硬件/UART 合同](../specs/2026-11-18-p6-8-b0-2-hardware-uart-spp-design.md) §3–5、生命周期/显示合同、B2/B8 审查及 [R01 报告](2026-11-19-p6-8-r01-repair-acceptance.md)。范围 F02/F03/F04、B2-R01–04、B8-R02；HB06/07/08/10/12/13/14、VIEW-C04、ESM-C19；T02-A/B/C、T08-C 对应软件子项，不核销物理门禁或其他 R 批。

## 实现与审查问题核销

| 来源 | 实际修复和软件断言 |
|---|---|
| B2-R01 / F02 / R02.1 | S3 真实 listener pump 在解析未提交 staging 前用 nonblocking MSG_PEEK 检查可见 EOF/RST 和当前 UART 有效性。关闭走原清 parser/staging、CLIENT_CLOSE 或未 ACK 时失效 session/token；不回滚已开始的 SPP write、不自动重传。FIN/RST 复现均不再向桥送第二帧，7778 独立。既有正常连续两帧和 UART fault 关闭 TCP 断言保留。 |
| B2-R04 / F04 / R02.2 | 真实 SPP worker 的 connect/disconnect/write/not_connected 结果经过已有 request generation 定位非零 control_epoch，保留 code/seq=0/1B payload。以固定每代码有界槽汇总当前 epoch，保留原优先小控制队列及发送失败重试；旧代次未提交 error 随 owner 退休，仅留板端日志，不重新标成新 epoch 或全局 error。已经进入 UART 小队列的旧 error 保留原 epoch/token。真正初始化等全局 error 才用 epoch=0，reverse overflow 仍用受影响 epoch。 |
| B2-R03 / F04 / R02.2 | 加 host adapter（实际 uart_wire/link/router/transport、tivoo_spp worker/session、control_bridge）和小型 deterministic fake UART/FreeRTOS/SPP driver。32 FIFO 满、33rd 不 ACK，实际 8192 reverse ring 与双向 in-flight 独立背压；S3 实际 reverse ring 经 socketpair drain 后 ACK；CLOSE/OPEN 丢弃旧 generation 未开始帧，已执行的首帧保持；reverse overflow code6 关闭匹配 client，旧 code6/3 不闭新 client；已接受旧 target select 失败不会归到新 owner；bridge invalidation 失效/恢复与重复状态、诊断队列拒绝 offline 时仍发布恢复；HA encode_command 实际 256 个 GIF chunk 经 UART wire decode/FIFO/SPP write 按序逐字节比对。原 codec/link/router golden、security/session 测试均保留。 |
| B2-R02 / F03 / R02.3 | 最小方案：S3 对匹配当前 epoch 的 code3 与原 code6 一样令 client_fault，原 listener 清除该 7777；HA 原 reconnect loop 自动再次发送当前配置 MAC（0x69+6B）。桥仍保留可证明旧 A 的 connected/MAC，不向 A 误送 B 帧，不再新增竞争性 bridge 重试系统。fake driver 两路径（disconnect API fail / CLOSE timeout）均验证旧 A 保持、B 帧拒绝、HA 新 epoch 后重选 B，实际 B 写入成功；新 epoch 错误不会由旧结果触发。既有 7777 回连与 Config Entry MAC change/reload 回归保留。 |
| B8-R02 / F03 / R02.4 | HA 以可信 STATUS/EVENT 的三态、配置 MAC、实际未 closing 的 7777 writer 更新内部显示资格；connecting、非当前/缺失 MAC 的 connected 撤销资格（内部 spp_unavailable，不新增 wire 枚举、不虚报物理断开）。仅诊断 EOF 不撤销。诊断 session 内拒绝旧 uptime 快照覆盖更新 SPP 观察，重复有效资格不重复同步；匹配恢复/新控制连接才重算最新赢家或重申 OFF。真实双 TCP + coordinator + encoder fixture 直接断言 7777 wire，独立验证 connecting 或 wrong MAC 首快照、屏幕 ON/OFF、多次 desired 更新、旧快照/重复通知及 7777 回连重发 MAC/当前状态、7778 未重连。未改 gate/owner、语音 UUID 或公开 HA/MCP schema。 |

说明：UART ACK 仅证明被目标队列接受，HA drain 仅证明运输；不承诺 Tivoo 物理像素已执行。可见 EOF/RST 才能检测，不声称可预知网络断开。旧 7777 的已接受 connect/disconnect 仍按原合同处理，未开始的旧 FRAME 跳过；SPP 原始异步回包本身无 request ID，不伪造物理归属。现有 330B/15ms、认证加密/Bond/NVS、SDP fallback、双向 stop-and-wait、心跳/错误 ID 与语音链路保持。

## RED / GREEN / 补证

共同运行方式：repo root，PYTHONDONTWRITEBYTECODE=1 bash scripts/test-ha.sh <paths> -q -p no:cacheprovider；HA 组合 fixture 按 B5 已有本地测试环境附加 PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath"（不改生产依赖）。

- R02.1：test_p68_closed_client_discards_uncommitted_staging[fin/rst] 旧代码 RED 2 failed（本地 socket 已可见 FIN/RST，延迟 ACK 后错误读到 FRAME 01030022250002 而非 CLOSE），.superpowers/p68-r02/r021-red.log；修复后 test_p5b3_control_bridge.py 8 passed，r021-green.log。原已 ACK/未 ACK 场景保留。
- R02.2/3：test_real_uart_worker_request_error[bridge-1/bridge-2/bridge-connect] RED 缺失 epoch=1 的 code3/code2；test_real_uart_adapter_worker[master] RED 匹配 code3 未令 client_valid=false；旧代码 4 failed、18 passed、3 参数角色 skip（r022-red-final.log）。队列实测与 256-chunk 测试旧代码已经通过，为补证、不制造 RED。早期 r022-red.log 自身 GIF 只生成 254 chunk 是测试数据问题，已改用 49 满 palette＋100 色帧核对实际 256 后重跑，以上才是有效 RED。修复后 22 passed、3 角色 skip（r022-green.log）；后续改用明确 bridge/master 参数、加 retired request 和实际 wire decode、S3 ring、恢复通知断言，消除非适用角色 skip。
- R02.4：test_p68_spp_status_reconnect_revokes_display_eligibility[False/True] RED 2 failed，connecting 快照后 TCP 仍到达旧显示帧（预期 read timeout 未发生，r024-red.log）。初次 fixture 错用非编码 show_text 参数已先修正并重新 RED，未作产品证据。修复后 test_transport/test_display_state/test_p68_display 63 passed（r024-green.log）。扩展参数分别 testing connecting 与 wrong peer、OFF/ON，真实 TCP 回连、旧/重复快照等后，UART+HA transport 54 passed（expanded-green.log）。
- 最终完整本批回归 102 passed、0 failed、0 skipped、9 warnings、exit 0（regression.log，29.69s）。警告为既有 HA/asyncio、aiohttp 依赖弃用或 NotAppKeyWarning。保留旧有效测试，仅将虚拟 connected 状态的 B8 fixture 补真实 writer mock，并明确无 writer 不合格；旧 observer 测试新增撤销状态断言。未跑 R11 全量。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath" \
  bash scripts/test-ha.sh \
  tests/esp32/test_p68_uart.py \
  tests/esp32/test_p5b3_control_bridge.py \
  tests/esp32/test_p5b3_session.py tests/esp32/test_p5b3_security.py \
  tests/esp32/test_p6_reverse_channel.py tests/esp32/test_p6_device_status.py \
  tests/homeassistant/custom_components/tivoo/test_transport.py \
  tests/homeassistant/custom_components/tivoo/test_display_state.py \
  tests/homeassistant/custom_components/tivoo/test_p68_display.py -q -p no:cacheprovider
```

## 构建

同工作区现有开发 build 双 target 串行，IDF v6.1，激活 ~/.espressif/tools/activate_idf_v6.1.sh，不安装或更新工具链；不覆盖 R01 独立历史归档。S3 工作区 sdkconfig 为非生产空 Wi-Fi 凭据，TEST_GATE/PROMPT_CALIBRATED 均未启用，R01 已用非生产 dummy 证明实际 Wi-Fi 入口；本批未修改 Wi-Fi 入口或配置。先增量编译受影响 C 文件、链接与 size，随后依执行计划执行 reconfigure → ninja -j1 → size。产物仅供开发机验证，禁止刷写。证据目录 .superpowers/p68-r02/{bridge_firmware,firmware}，内含本批 ELF、APP、flasher_args.json、SHA256SUMS，原 R01 配置与镜像记录不动。

```bash
source ~/.espressif/tools/activate_idf_v6.1.sh
for target in bridge_firmware firmware; do
  (cd "esp32/$target"; CMAKE_BUILD_PARALLEL_LEVEL=1 idf.py -B build reconfigure
   nice -n 5 ninja -C build -j1
   CMAKE_BUILD_PARALLEL_LEVEL=1 idf.py -B build size)
done
```

最终两 target reconfigure、ninja、size 均 exit 0（bridge_firmware-final-build.log、firmware-final-build.log，合计约 75s），APP 文件长度与 SHA256：

| 目标 | APP 字节 | APP SHA256 |
|---|---:|---|
| Classic ESP32 | 718768 | 6257b234b3010ae23a5174a913dbe359176cbce6daab51e2d935804a2cb7ada4 |
| ESP32-S3 | 2101968 | 2d43124275b1ae71fa6b56936f5905ae00ac37e55fa00846a1f22cea356466cf |

ELF hash 见两 SHA256SUMS，实际编译图重编相关 C 文件，原 IDF Kconfig 提示及依赖弃用不造成失败。R02 使用空凭据配置，因此 S3 APP 大小不能与 R01 dummy Wi-Fi 直接比较；真实 Wi-Fi 启动证据仍见 R01，不冒充本次实机测试。

## 最终裁决与保留门禁

R02.1–R02.5 软件修复与证据完成：F02/F03/F04、B2-R01–04、B8-R02 核销对应软件问题；T02-A/B/C、T08-C 仅本批控制链和恢复资格子项 PASS。独立 reviewer 代理不可用，按 requesting-code-review/verification-before-completion 自审实际 diff（协议 ID、generation/epoch、队列边界、错误回传及旧请求隔离、TCP close、HA 实际 wire/OFF、旧测试兼容）；无本批已知 Critical/Important 遗留。不是独立 RF 或线程实时性能验证。真实 UART 921600 水位/吞吐、双板 reset、电气、配对/Bond/NVS、TVIO/HA 生产部署、物理屏幕 OFF/ON/GIF、长音频并行等仍 GAP。S3/第二颗麦克风未到位；不连接 NAS、不部署、不刷写、不擦 NVS、不启用 TEST_GATE，保留 legacy。R03–R11/B9/B10 未执行；R10 可复用新增实际双 TCP fixture 补慢显示/语音组合。既存原 B1–B10 计划链接变更不动、不纳入 R02 提交；仅本批文件、计划勾选、报告独立本地提交，不 push/merge。
