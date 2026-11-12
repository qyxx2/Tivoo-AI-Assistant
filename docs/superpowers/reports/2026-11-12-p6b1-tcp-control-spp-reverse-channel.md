# P6b1 — TCP 7777 SPP 原始反向通道执行报告

分支：feature/p6-esp32-ha-bidirectional-communication
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

## 验证

| 命令/范围 | 结果 |
|---|---:|
| P6 reverse channel + P5b1 listener + P5b2 diagnostics + P5b3 control bridge + P5b4 integration POSIX 回归 | 31 passed |
| HA transport + services 回归 | 29 passed |
| Ruff check（本次修改的 Python 文件） | passed |
| Ruff format check（本次修改的 Python 文件） | passed |
| ESP-IDF v6.1 / ESP32 target idf.py build | passed |\n| git diff --check | passed |

POSIX simulator 覆盖 raw byte 顺序、队列已满时拒绝新 chunk 且保留原有 bytes、通过链接包装强制 partial send、填满非阻塞 socket 触发 EAGAIN、恢复读取后继续发送并逐字节核对、无 TCP client 不缓存数据、断开 7777 清队列且不关闭 7778。HA 测试覆盖单字节 hint、合并字节块保持 raw、asyncio control reader 接收和分发 raw bytes。

## 构建环境与结果

开发机已有完整 ESP-IDF v6.1 工具链和 Python venv。正确激活方式为 source /home/Gold/.espressif/tools/activate_idf_v6.1.sh；官方 export.sh 的默认 Python 目录与该机 EIM 安装布局不同，不应在这台机器上代替该激活脚本。激活后 idf.py --version 为 ESP-IDF v6.1，Xtensa GCC 15.2.0、CMake 4.0.3、Ninja 1.12.1 均可用。

执行 cd esp32/firmware && idf.py build 成功，完成 ELF 链接与 ESP32 binary image 生成；产物为 esp32/firmware/build/tivoo_firmware.bin。构建首次发现 link_peer_matches() 使用了定义在后面的 same_address()，已改为直接 memcmp() 并重新构建通过。

## 未执行 / 验收限制
2. **真实板卡 SPP 验收未执行。** 未刷写固件，未在真实 Tivoo/ESP32 上验证 Bluedroid ESP_SPP_DATA_IND_EVT 到 TCP 7777 的原始回传。模拟器通过不等同于实机验收。
3. **上游源码对照未执行。** BluetoothBridgeTest/esp32-divoom 的 output_bluetooth.cpp、input_tcp.cpp、hardware_bluetoothctl.cpp 不在当前工作区；语义依据 P6 合同矩阵/分批计划中冻结的 0x69/0x96 定义实现。

因此，本报告确认 P6b1 代码实现、POSIX 与 HA 自动化测试、ESP-IDF v6.1 固件构建已完成；真实 SPP 硬件验收仍是明确的未完成门槛，不虚报为通过。

收尾边界：仅 P6b1；不 flash、不部署、不 push、不 merge，不触及 P6b2。
