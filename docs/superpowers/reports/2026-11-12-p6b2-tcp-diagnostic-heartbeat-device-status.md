# P6b2 — TCP 7778 心跳、状态快照和设备事件执行报告

**日期：** 2026-11-12
**分支：** `feature/p6-esp32-ha-bidirectional-communication`
**基线：** `9af6a2c`（P6b1 本地验证提交）
**批次范围：** 仅 P6b2；P6b3–P6b6 未实现。

## 结果

P6b2 合同矩阵 C07–C10/C17 对应实现完成。HA 诊断通道与原始 SPP 控制通道保持独立，状态来源复用现有 Wi-Fi、listener 和 SPP 所有者，没有建立第二套 SPP 状态机。

### HA 7778 transport

- 接受 HELLO_ACK 后发送一次 GET_STATUS，并为当前会话保存唯一 request_id；只接受匹配该 request_id 的 DEVICE_STATUS。
- 按固定 15 秒间隔发送空 PING；只有空 PONG 更新时间戳。连续 45 秒没有有效 PONG 时，终止当前诊断会话并复用原有独立连接循环重连 7778。
- 心跳发送或初始状态请求失败也会退出当前诊断会话，交给 7778 重连循环处理；不会关闭 7777、发送 SPP 断开或影响 Wi-Fi。
- 严格校验 DEVICE_STATUS 和 DEVICE_EVENT，清洗未知/非法可选字段，更新状态快照和事件缓存；断开后清除旧会话缓存。
- 接受 P6 ERROR codes，并保留 P5 logger 映射。标准日志中对 URL、Bearer、token、密码/SSID、PCM 字段做脱敏。

### ESP32 firmware

- 新增 `device_status.c/.h` 并注册为 TVIO 入站消息处理器：空 PING 回复空 PONG；GET_STATUS 校验 request_id 并回显到 DEVICE_STATUS；非法请求报告 `protocol_invalid_payload`，不主动关闭通道。
- DEVICE_STATUS 使用真实 getter：Wi-Fi 连接/IP/RSSI 来自 ESP-IDF netif/AP，TCP 7777/7778 来自现有 listener client 状态，SPP state/MAC 来自现有状态变量和 peer snapshot。
- HTTP resource 通过 `tivoo_device_status_set_audio_resource()` 提供当前 `idle`/`fetching` 与 playback_id 状态。当前批次没有 HTTP GET producer，因此默认保持 idle；P6b5 可在资源生命周期中更新此状态。
- Wi-Fi GOT_IP/断开和 SPP 状态转换报告固定事件，并通过状态变化检查避免重复发送。SPP `spp_connecting` 事件在 worker 接受连接请求时发出，目标 peer 已先发布；SPP close 事件在真实 CLOSE 回调中发出。
- ESP32 错误码 allow-list 增加 `audio_busy`、`audio_http_failed`、`audio_http_status`、`audio_content_type_mismatch`、`operation_cancelled` 等 P6 项，保留 P5 项。

## 验证

最终联合命令：

```bash
./scripts/test-ha.sh \
  tests/homeassistant/custom_components/tivoo/test_transport.py \
  tests/homeassistant/custom_components/tivoo/test_diagnostics.py \
  tests/esp32/test_p6_device_status.py \
  tests/esp32/test_p5b1_network_listeners.py \
  tests/esp32/test_p5b2_diagnostics.py -q
```

**结果：73 passed, 5 warnings。** 5 条为当前 Home Assistant/Python 依赖的弃用警告，不是测试失败。

额外重点覆盖：

- fake clock 验证 15 秒 PING、有效 PONG 续期、无效 PONG 不续期、45 秒超时、诊断通道自动重连以及 7777 连接保持。
- HELLO_ACK 后仅一次 GET_STATUS，request_id 匹配和失配/无效请求拒绝。
- ESP32 POSIX simulator 通过真实 `device_status.c`、`diagnostics.c`、`network_listeners.c` 与 cJSON 运行；注入 Wi-Fi/IP/RSSI、SPP peer 和 audio-resource fetching 状态，验证状态快照内容。
- Wi-Fi/SPP 相同状态重复输入不重复发事件；覆盖全部 P6 ERROR codes，并运行 P5 listener/diagnostics 回归。
- ESP32/P5 focused subset：22 passed。

静态检查通过：

```bash
.venv/bin/ruff check homeassistant/custom_components/tivoo/transport.py \
  tests/homeassistant/custom_components/tivoo/test_transport.py \
  tests/esp32/test_p6_device_status.py
.venv/bin/ruff format --check homeassistant/custom_components/tivoo/transport.py \
  tests/homeassistant/custom_components/tivoo/test_transport.py \
  tests/esp32/test_p6_device_status.py
.venv/bin/python -m compileall -q homeassistant/custom_components/tivoo/transport.py \
  tests/homeassistant/custom_components/tivoo/test_transport.py \
  tests/esp32/test_p6_device_status.py
git diff --check
```

### ESP-IDF 构建

ESP-IDF **v6.1 / ESP32** target build 成功，最后一次构建包含本批次全部 C 变更。产物：

- `esp32/firmware/build/tivoo_firmware.bin`
- 大小：1,269,392 bytes (`0x135e90`)
- SHA-256：`59bcf3c9411d6271a11734764dfd8d755e9c84f091f89b28eeef4d9a88c4ad86`
- 最小 app partition 仍有约 85% 空间。

开发机缺失 IDF 安装脚本引用的 `espidf.constraints.v6.1.txt`，构建时复用已有 v6.1 Python 环境并跳过该文件存在性校验；不修改项目 requirements。构建成功。Kconfig 输出包含现有依赖中的 bool 默认值/deprecation 提示，没有阻断构建。

## 收尾边界

本次未刷写 ESP32、未重启设备、未部署/重启 NAS HA 容器、未执行真实设备验收；该批次按计划完成自动化和目标构建门。未实现 MIC、TTS/HTTP GET、AUDIO_STOP、decoder/playback 或其他 P6b3–P6b6 内容。未 push、未 merge。代码和本报告一并纳入本批次本地提交。
