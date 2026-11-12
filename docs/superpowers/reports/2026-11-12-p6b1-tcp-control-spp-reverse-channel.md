# P6b1 — TCP 7777 SPP 原始反向通道执行报告

分支：feature/p6-esp32-ha-bidirectional-communication
代码提交：5440685892c0a4e4917407186a53427200723707 (`5440685`)
基线：P6b0 commit c221af94fb94ebd6cc91ff649280924601d756be
范围：仅 P6b1（P6-C02–C04、C19）；未实现 P6b2 或后续批次。

## 实现

- ESP_SPP_DATA_IND_EVT 只将当前 SPP handle 收到的原始 bytes 复制到 control bridge 的固定 8 KiB reverse queue；回调中不执行 socket send、不等待 TCP 消费者。
- reverse queue 使用短临界区保护；容量不足时整块拒绝并由 listener task 异步报告 reverse_queue_full。没有 7777 client 时丢弃当前数据，不为后续 client 缓存。
- TCP 7777 listener 仅在 queue 有待发数据时将该 client 加入 select writable fd set。发送处理实际 send() 返回长度；EAGAIN/EWOULDBLOCK/EINTR 不消费队列，下一次 writable 再续发。
- 7777 client disconnect 清空其待回传队列，只结束当前 TCP client，不调用 SPP disconnect，也不关闭 7778 endpoint。
- SPP frame submission 区分 QUEUED/CONNECTING/DISCONNECTED/QUEUE_FULL。未连接状态不延迟保存 frame；connecting 返回单字节 0x69，disconnected 返回单字节 0x96。
- SPP 状态和目标 peer 快照与 s_session worker-owned 数据隔离，listener 通过短临界区保护的 peer 快照判断，不跨任务读取 session 对象。
- HA adapter 的 7777 reader 不再只 drain socket：独立单字节 0x69/0x96 更新 best-effort hint；其他 read 块作为 opaque raw bytes 原样交给注册的 async consumer。raw bytes 不写日志，也不被包装为 TVIO message 或命令 ACK。
- 增加 reverse_queue_full 错误码允许列表。
- 更新 P5b4 host SPP stub 的队列返回类型，避免共享接口从 bool 改为结果枚举后出现测试原型冲突。

## 自动化验证

| 命令/范围 | 结果 |
|---|---:|
| P6 reverse channel + P5b1 listener + P5b2 diagnostics + P5b3 control bridge + P5b4 integration POSIX 回归 | 31 passed |
| HA transport + services 回归 | 29 passed |
| Ruff check / Ruff format / py_compile | passed |
| git diff --check | passed |
| ESP-IDF v6.1 / ESP32 target build（最终提交 SHA 已重新 reconfigure） | passed |

POSIX simulator 覆盖 raw byte 顺序、队列已满时拒绝新 chunk 且保留原有 bytes、通过链接包装强制 partial send、填满非阻塞 socket 触发 EAGAIN、恢复读取后继续发送并逐字节核对、无 client 时不缓存数据、断开 7777 清队列且不关闭 7778。HA 测试覆盖单字节 hint、合并字节块保持 raw、asyncio control reader 接收和分发 raw bytes。

## 实机刷写与验证

目标设备：ESP32-D0WD-V3 rev 3.1，MAC `58:2a:bd:d5:4c:90`，Flash 16 MB，PSRAM 8 MB。NAS USB 串口 `/dev/ttyACM0`，使用既有 `tivoo-esptool` 持久容器（esptool 4.8.1；restart policy `unless-stopped`），未重建或重启该容器。

最终 app image：`esp32/firmware/build/tivoo_firmware.bin`
固件上报版本：`0.1.0+5440685`（与代码提交短 SHA 一致）
大小：1,265,648 bytes
SHA-256：`fb3130f85c237d973de3b697e36520435f8abe32a9ef594757e45635ed85d693`
NAS 镜像：`/volume1/docker/tivoo-esptool/artifacts/p6b1/tivoo_firmware.bin`（SHA-256 相同）

通过 esptool 只将 app image 写入 `0x10000`，覆盖范围 `0x10000–0x144fff`。未擦除 Flash，未写 bootloader、partition table 或 NVS；Wi-Fi credential 与已配对 Bond 得以保留。esptool 输出 `Wrote 1265648 bytes`、`Hash of data verified`、`Hard resetting via RTS pin`，退出码 0。

刷写后的真实设备验证：

- ESP32 启动成功并恢复 Wi-Fi，NAS 对 `192.168.3.28` 的 ping 成功；neighbor MAC 与目标板 MAC 一致。
- 直连 TCP 7778 完成 TVIO v1 HELLO/HELLO_ACK。设备上报 `firmware_version=0.1.0+5440685` 和 capability `spp_reverse`，证明最终提交版本已在运行。
- 7778 诊断日志确认 Classic SPP 初始化。首次连接尝试未成功，自动重试后通过已有 Bond 完成 `spp_bond_reused_after_open`、`authenticated_spp_peer_ready`、`spp_reconnected`；未重新配对。
- 在已认证 SPP 会话下，7777 建连并发送重复 `0x69 + MAC`，设备返回 `spp_connect_duplicate_ignored`。关闭 7777 后 7778 仍保持连接；重新建立 7777 再发送同一请求，仍返回 duplicate ignored；再次关闭 7777 后 7778 仍保持连接。这验证了 7777 TCP 生命周期与现有 SPP session、7778 endpoint 的隔离。
- 7778 在 7777 关闭期间保持连接；另一个观察窗口内，7777 已关闭时 7778 仍收到 SPP 自动重试与 Bond 认证诊断事件。没有观察到 ESP32 因 7777 disconnect 主动断开 SPP。
- 使用真实 SPP 连接开启 20 秒 TCP 7777 raw capture，未收到 Tivoo 上行字节（0 bytes）。该窗口内未观测到可确认的设备端 DATA_IND payload，因此**真实板卡的 SPP DATA_IND → 7777 raw payload 实测仍为 NOT RUN/BLOCKED**；不能以 HELLO、SPP 已连接或模拟器通过替代该项验收。
- NAS 原有 HA Tivoo 集成仍是 P5 版本：旧 `transport.py` 只接受 `spp_control`/`remote_diagnostics`，旧 `diagnostics.py` 缺少 P6b0 双向 codec 导出的消息类型常量。已先备份旧文件，再仅同步工作区 P6b0/P6b1 所需的 `diagnostics.py` 与 `transport.py`；备份位于 `/volume1/docker/tivoo-esptool/artifacts/p6b1/diagnostics.py.pre-p6b0`、`transport.py.pre-p6b1`。容器内两文件 SHA 与工作区一致，HA 容器内 `py_compile` 通过。重启 HA 后未再出现 `invalid HELLO payload` 或 Tivoo 组件导入错误，HA 进程同时保持到 ESP32 7777、7778 的 ESTABLISHED TCP 连接。
- 上游 BluetoothBridgeTest/esp32-divoom 的 `output_bluetooth.cpp`、`input_tcp.cpp`、`hardware_bluetoothctl.cpp` 不在当前工作区，因此未完成这三份文件的逐行语义对照；具体限制不影响上述已执行的本地合同测试。

## 结论与范围边界

P6b1 代码、自动化回归、ESP-IDF build、真实 app-only flash、设备启动/HELLO、SPP Bond 认证以及 7777/7778 生命周期隔离均已完成。真实设备主动产生 SPP 上行数据并由 7777 收到原始字节这一项尚无观测证据，保留为 P6b1 的唯一硬件数据路径验收缺口；上游源码对照也未执行。后续不能将这两项标记为 PASS。

本次仅做 P6b1 验证与报告更新；未开始 P6b2–P6b6，未修改固件代码，未 push、未 merge。NAS 的 Home Assistant 容器重启以加载同步的 P6b0/P6b1 依赖文件并清理旧 TCP socket；持久化 `tivoo-esptool` 容器一直运行，未重启。
