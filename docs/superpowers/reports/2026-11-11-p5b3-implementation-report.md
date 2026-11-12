# P5b3 TCP 7777、Classic SPP 与 Bond Key 实施报告

日期：2026-11-11
分支：`feature/p5-esp32-minimal-firmware`
基线：`6fd5f8912e3693a7426ffd63b4ffeab4c26ee3da`
权威合同：`docs/superpowers/specs/2026-11-11-p5-esp32-minimal-firmware-contract-matrix.md`
执行计划：`docs/superpowers/plans/2026-11-11-p5b3-tcp-7777-spp-bond-implementation-plan.md`

## 1. 结果

P5b3 软件实现完成。HA 通过 TCP 7777 把语义命令编码为 Tivoo 原始帧；ESP32 以字节流方式解析控制命令/帧，按顺序提交至独立 Classic SPP worker；SPP worker 使用 HA 当前 Config Entry 的 MAC 连接目标 Tivoo，并在 BlueDroid 中完成认证和原生 Bond Key 存储。

保留了 P5b1/P5b2 的配置、listener 和 7778 诊断职责。没有实施 P5b4 的固件刷写、实机首次配对、重启/断电后重连验收。

## 2. 实现内容

### 2.1 HA 命令编码和 7777 TCP 会话

- 新增 `protocol.py`：Tivoo 外层帧、长度和 checksum；16×16 RGB palette/image frame；静态图片 `0x44`；动画 `0x49` 及 200-byte 分块；亮度、音量、倒计时 payload。
- 复用现有 HA 服务生成的 pixel frames，不把图片解码/调色板编码搬到 ESP32。
- 亮度、音量、倒计时、图片/动画 payload 与工作区已有 Tivoo SDK 源码及 P4 合同交叉核对；协议帧和像素编码保留上游归属说明。
- 每次 7777 TCP 会话连接成功后，HA 立即发送 `0x69 + ConfigEntry.tivoo_bluetooth_mac` 六个原始 MAC 字节。TCP 连接断开不自动发送 `0x96`。
- 服务命令在当前连接上按锁串行发送；未连接时明确报错。诊断端口 7778 保持独立。
- 新增真实 Config Entry 更新/reload loopback 测试，确认新会话首包使用更新后的 MAC。

### 2.2 TCP 7777 固件控制桥

- 新增 `control_bridge.[ch]`：7-byte `0x69/0x96 + MAC` 累积解析和 Tivoo frame 互斥状态机。
- 新增 `tivoo_frame_stream.[ch]`：从 MIT 上游 `esp32-divoom` 固定 commit `e90a77bbade7e92523bfb5b69bc5cb1e4d167520` 移植 frame-size、checksum、escape、pending 和 append 算法；保留 4608-byte 帧流缓冲。
- TCP 接收缓冲采用 ESP-IDF 当前 `CONFIG_LWIP_TCP_MSS`。不假设单次 recv 对应单条命令或完整帧。
- payload 内的 `0x69/0x96` 不会被误解析为控制命令；TCP 断开只清理 parser state，不主动拆除已有 SPP。
- 上游 append helper 也会把非帧残余交给通用 handler；bridge handler 另行要求输入恰好通过完整 frame/checksum 校验。pending 阈值修正为 2-byte checksum 的最小完整帧长度，checksum 错误候选不会被转发或无限缓存。
- listener 仍为每个端口一个活动 client；7778 诊断通道行为独立。

### 2.3 Classic SPP、GAP 安全和 NVS

- 使用 ESP-IDF 原生 Controller、Bluedroid、GAP 和 SPP API；Classic-only controller mode，SPP callback mode。
- SPP initiator 对 HA 指定 MAC 执行 SDP SCN 发现；结果有效使用发现的 SCN，否则回退 SCN 1。没有设备 Inquiry、BLE Scan 或设备名自动选择。
- 新增 32-entry FIFO SPP worker。TCP listener 不等待蓝牙配对/连接/写完成。
- 每次新的 `0x69`，包括相同 MAC，都按序先断开旧 SPP 会话，再连接目标 peer；帧按最多 330 bytes 分块，每块等待 CONG/WRITE completion，成功帧间隔 15 ms。
- 显式声明 `ESP_BT_IO_CAP_NONE`；Legacy PIN 按 `min_16_digit` 回复 16 个 ASCII 零或 ASCII `1234`；SSP 数字确认和 passkey 输入请求 fail-closed；KEY_NOTIF 不记录 passkey。
- 认证完成必须匹配当前目标 MAC、成功状态，并与 SPP OPEN 一起才能继续；还要确认目标地址出现在 BlueDroid bond list。
- 移除 Wi-Fi 侧自动全擦 NVS 的恢复分支。启动顺序为 NVS → Controller/Bluedroid/SPP → TCP listeners → Wi-Fi；NVS 初始化失败时不启动后续模块。
- BlueDroid 原生 Bond Key 持久化源码路径已核对：`bta_dm_new_link_key_cback` → `btc_dm_auth_cmpl_evt` → `btc_storage_add_bonded_device` → `btc_config_flush` → OSI config NVS backend。应用层仅读取 peer 地址列表，不复制或记录 Link Key。

## 3. 合同追踪

| 合同 | 软件验证结果 | 仍需 P5b4 的部分 |
|---|---|---|
| P5-C09 | PASS：控制命令/帧分流、逐字节解析、FIFO 投递和队列满错误路径 | — |
| P5-C10 | PASS：指定 MAC、SDP SCN、SCN 1 fallback、FIFO session mock、330-byte chunk 和 WRITE completion gate | Tivoo 真实 RFCOMM/SDP/认证互操作 |
| P5-C11 | PASS：TCP fragmentation/coalescing、控制/帧交错、payload 内控制字节、错误 checksum 拒绝、断开仅清 parser | — |
| P5-C12 | PASS：未实现 SPP DATA_IND 反向通道 | — |
| P5-C22 | PASS：HA Config Entry 是唯一 MAC 来源；固件无固定 MAC/扫描；reload loopback 使用新 MAC | 手机确认实际 Tivoo-audio MAC |
| P5-C23 | PASS：HA reload 新 MAC + 新 7777 首包；session mock 对相同/不同 peer 先断后连 | 更换真实 Tivoo 的实机确认 |
| P5-C24 | PASS（软件策略）：IO_CAP_NONE、Legacy PIN、拒绝不可交互 SSP、AUTH_CMPL peer/status gating、安全掩码编译 | AUTHENTICATE+ENCRYPT 与当前 Tivoo 固件的真实配对兼容性 |
| P5-C25 | PASS（启动/源码）：NVS 前置、无全擦路径、BlueDroid 原生 Bond Key NVS 保存链已确认 | 软件重启和完全断电后的实际 Bond 复用 |

## 4. 验证

| 验证项 | 命令/环境 | 结果 |
|---|---|---:|
| P5b1/P5b2/P5b3 + Tivoo HA 集成全量回归 | `.venv`、Home Assistant 预导入 bootstrap、pytest 指定测试组 | **179 passed，7 warnings** |
| Ruff lint | `.venv/bin/ruff check`，12 个变更 Python 文件 | PASS |
| Ruff format | `.venv/bin/ruff format --check`，12 个变更 Python 文件 | PASS |
| Patch whitespace | `git diff --check` | PASS |
| ESP-IDF 固件构建 | IDF v6.1，`IDF_TARGET=esp32`，`idf.py build` | PASS |
| ESP-IDF size | `idf.py size` | PASS |

最终固件：`esp32/firmware/build/tivoo_firmware.bin`

- Binary size：`0xBC0E0` bytes（770,272 bytes）。
- 应用分区：`0x800000` bytes；剩余 `0x743F20` bytes，约 91%。
- IRAM：100,999 / 131,072 bytes（77.06%），剩余 30,073 bytes。
- DRAM：79,955 / 124,580 bytes（64.18%），剩余 44,625 bytes。
- RTC SLOW：64 / 8,192 bytes（0.78%）。
- ESP-IDF `size` 汇总的 image size：770,155 bytes。

7 个 pytest warnings 来自当前 Home Assistant/Python 依赖弃用提示、pytest plugin rewrite 提示，以及既有非 loopback 网络拦截测试；不是用例失败。

## 5. 验收边界

本批次未刷写 ESP32，也未通过实际 Tivoo 测试首次配对、SPP 音画命令传输、软件重启后自动复用 Bond Key 或完全断电后的复用。这些是 P5b4 的实机验收项，不能用 host mock 或固件成功编译替代。

P5b3 未合并、未推送；提交只包含本批次实现、测试及文档。P5b4 的边界和批次定义未修改。
