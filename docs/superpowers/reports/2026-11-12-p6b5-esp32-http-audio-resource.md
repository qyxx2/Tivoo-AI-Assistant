# P6b5 — ESP32 HTTP 音频资源获取与停止执行报告

- 日期：2026-11-12
- 基线：ffe427bf97ba5bd843a4e43642f6c6ab983aecff（P6b4）
- 分支：feature/p6-esp32-ha-bidirectional-communication
- 范围：仅 P6b5；未开始 P6b6，未执行 P6.5/P7/P8。

## 结果

P6b5 实现与真实 ESP32 HTTP/STOP 验收通过。ESP32 在独立 FreeRTOS task 中发起 ESP-IDF HTTP GET，按 1 KiB 有界 HTTP buffer 读取，并逐块交给 reader。只接受 2xx 和与 TTS_PLAY 预期类型一致的 audio Content-Type；chunked/未知 Content-Length 不需要整段缓存。AUDIO_STOP 能停止唯一活动请求，过期/重复停止为 no-op。

resource_ready 只代表整个 HTTP body 已交给 reader，不代表播放完成。默认 drain reader 在 P8 decoder 注册前逐块接收并丢弃数据；P8 可以通过 tivoo_audio_resource_set_reader() 注册 decoder sink。本批未实现任何 decoder、SRC、PCM 队列、I²S TX、DAC/AUX 或 playing/completed 状态。

## 实现

- 新增 esp32/firmware/main/audio_resource.c/.h：TTS_PLAY schema/URL 校验、单活动 GET、独立 HTTP task、2xx/MIME 检查、bounded reader、失败/完成/停止状态以及 typed start/stop API。
- AUDIO_STOP 校验 UUID request_id、reason 和可选 expected_audio_id；只停止匹配活动请求，未提供 expected ID 时停止唯一活动请求。
- main.c 将 0x30/0x31 分发给 audio resource manager；其他消息保留现有 device-status handler。diagnostics listener 不执行阻塞 HTTP perform。
- CMakeLists.txt 使用 ESP-IDF 内置 esp_http_client/mbedtls。HTTPS 使用 ESP-IDF 默认 CA bundle 和证书校验，未关闭 TLS 验证；redirect 禁用。
- sdkconfig.defaults 固定 HTTP Client HTTPS/标准 CA bundle，并允许明确标记的 BSS 缓冲位于 PSRAM。
- 为解决新 HTTP/TLS 依赖使 ESP32 内部 DRAM 初次链接溢出 264 bytes，将 diagnostics 的 16 KiB TX staging byte buffer 放入设备原有 PSRAM。没有改动 RX 协议缓冲、SPP、NVS 或蓝牙状态。
- 新增 tests/esp32/test_p6_audio_resource.py、C parser harness、本地 HTTP fixture 和 p6b5_device_acceptance.py。复用了既有 P5b2 diagnostics simulator 对 0x30/0x31 的入站分发覆盖，没有另起一套帧模拟器。
- 更新 esp32/firmware/README.md 记录 reader 所有权和 P8 交接合同。

## 自动化与构建

| 验证 | 结果 |
|---|---|
| PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32 -q | **51 passed**, 27 warnings |
| ./scripts/test-ha.sh tests/homeassistant/custom_components/tivoo -q | **225 passed**, 16 warnings |
| Ruff check（P6b5 Python tests/fixtures） | PASS |
| Ruff format check（P6b5 Python tests/fixtures） | PASS |
| python3 -m compileall -q tests/esp32 | PASS |
| git diff --check | PASS |
| ESP-IDF v6.1 / target esp32 idf.py build | PASS |

最终固件 build/tivoo_firmware.bin：1,465,584 bytes（0x165cf0），SHA-256：

20ad4f95a1881ff0798a2df9ea84ca86e93bf872555d71100c2c41e9189e04d6

IDF size 报告：内部 DRAM 72,647 / 124,580 bytes（51,933 bytes free）；app 分区剩余 83%。PSRAM BSS 已承载选定的大型 staging buffer。

测试环境说明：未激活 ESP-IDF 环境变量的干净 shell 中执行 POSIX/GCC 回归。ESP-IDF activation 会把 esp32ulp-elf/ld 插到系统 PATH 前面；若在同一 shell 里运行 POSIX 主机测试，会错误调用 ULP linker。清洁 shell 的最终 51 项回归全部通过。

## 真实设备验收

复用 NAS 上已运行的 tivoo-esptool:4.8.1 持久容器及 /dev/ttyACM0。目标为 ESP32-D0WD-V3 rev 3.1（16 MiB flash，MAC 58:2a:bd:d5:4c:90，LAN 192.168.3.28）。

仅将 app image 写入 0x10000，esptool --verify 回读 digest 一致。实际擦写范围为 0x00010000–0x00175fff；没有 erase_flash，没有写 bootloader/partition table/NVS，已有 Wi-Fi/SPP Bond 保留。

为释放设备的单 client 7778 连接，实机验收时短暂停止 HA 容器；测试退出时通过 shell trap 自动启动。验收结束后确认 HA 为 Up，7777 与 7778 两条 TCP 会话均重新 ESTABLISHED。持久 esptool 容器未停止或重建。

受控 HTTP server 运行在 NAS 192.168.3.94:8765，直接连设备 7778 并完成 HELLO/ACK。实测结果：

| 设备行为 | 结果 |
|---|---|
| 256 KiB chunked、无 Content-Length | PASS；resource_ready.bytes_received=262144 |
| 10 MiB chunked、无 Content-Length | PASS；resource_ready.bytes_received=10485760，超过板载 8 MiB PSRAM，证明没有整段缓存 |
| 活动 GET 时提交不同 playback_id | PASS；返回 audio_busy |
| stale AUDIO_STOP（expected_audio_id 不匹配） | PASS；NAS 端仍继续发送数据 |
| 匹配的 AUDIO_STOP | PASS；状态 stopped，已接收 66,560 bytes 后停止 |
| 重复相同 AUDIO_STOP | PASS；无额外状态/错误帧 |
| HTTP 200 但 Content-Type 错误 | PASS；failed/audio_content_type_mismatch，bytes_received=0 |
| HTTP 503 | PASS；failed/audio_http_status，bytes_received=0 |
| 板卡启动、HELLO capability | PASS；上报 audio_resource_http |

完整输出保存在 NAS：
/volume1/docker/tivoo-esptool/artifacts/p6b5/device-acceptance.log

## 边界与未执行项

- 本轮真实 HTTP 使用 LAN HTTP；HTTPS CA bundle 已在 IDF 构建配置中启用，代码使用标准 bundle attach，但没有在本批用生产 HTTPS URL 单独实测 TLS 握手。
- 没有执行真实音频解码或播放；这是 P8 边界。
- 不验证 HA Pipeline/TTS Proxy/AstrBot 的端到端取消传播；该链路属于 P6.5 独立前置验证。
- P6b6 的 C01–C20 全量阶段验收仍未开始；P6b5 不代替 P6b6。

## Review

- 对照 P6b5 plan/contracts 审查了输入校验、单活动资源、HTTP headers gate、chunk forwarding、reader 生命周期、stop matching/idempotency、状态语义和日志脱敏。
- 确认没有 URL/token 打印；没有完整响应体缓存或按 Content-Length 分配内存。
- 确认未增加额外 TCP 端口、代理、消息总线、decoder、播放状态机或 P6.5/P7/P8 行为。
- 当前没有可用的独立 reviewer/subagent 调度工具；本报告记录的是作者自审，不声称独立 Reviewer 通过。

结论：**P6b5 实现、自动化验证、ESP-IDF 构建和本批 HTTP/STOP 真实板卡验收完成。** 仅本地提交；不 push、不 merge；P6b6 未开始。
