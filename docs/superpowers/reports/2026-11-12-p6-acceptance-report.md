# P6b6 — P6 最终集成与验收报告

- 日期：2026-11-12
- 分支：feature/p6-esp32-ha-bidirectional-communication
- 基线：43e3ece99289e4b1481c60540bc7d3e1dd804ceb（P6b5）
- 范围：仅 P6b6；未执行 P6.5、P7 或 P8。
- 合同依据：[P6 合同矩阵](../specs/2026-11-12-p6-esp32-ha-bidirectional-contract-matrix.md)；执行顺序：[P6 分批执行计划](../plans/2026-11-12-p6-esp32-ha-bidirectional-batch-execution-plan.md)。

## 结论

**P6-C01–C20 均有对应自动化、构建、源代码审查或真实设备证据，P6 阶段验收通过。** 本批补齐了之前尚未实机触发的 SPP DEVICE_EVENT、P6 ERROR，以及 7777 单独断线时 7778 保持运行的设备侧证据。P6 不包含真实 MIC producer 或音频解码/播放，不能把这些后续阶段能力描述为已完成。

## 自动化回归与固件构建

| 验证 | 结果 |
|---|---|
| HA Tivoo + P3 conversation/session/SSE 回归 | **288 passed**, 59 warnings |
| ESP32 P5/P6 POSIX 全量测试 | **52 passed**, 33 warnings |
| 新增 C/Python cross-language golden test | PASS；8 种通用消息，加专用 ERROR/DIAGNOSTIC_LOG 发送路径，逐字节比较完整 TVIO frame |
| Ruff check / format check | PASS |
| Python compileall | PASS |
| git diff --check | PASS |
| ESP-IDF v6.1.0、ESP32 target clean full build | PASS |

ESP32 首次回归曾出现一个单次时序性失败：test_wifi_ip_loss_closes_both_ports_and_new_sessions_recover。立即单测重跑通过，随后完整 suite 重跑通过；本批没有为该偶发结果修改产品代码。最终新增 golden test 后的完整结果为 52 passed。

Clean build 产物：

- 文件：esp32/firmware/build/tivoo_firmware.bin
- 大小：1,465,584 bytes（0x165cf0）
- SHA-256：f52bd312d0d89a1ef7fdbeec2293ec61ffa963120c462ad5960b376dbd361ef1
- App partition 剩余约 83%；现有 16 MiB flash、分区和 PSRAM 配置未修改。

## ESP32 实机刷写

使用 NAS 已有的 tivoo-esptool:4.8.1 持久容器和 /dev/ttyACM0。仅刷写 app image 到 0x10000，擦写范围为 0x00010000–0x00175fff。没有执行 erase_flash，没有写 bootloader、partition table 或 NVS。

esptool 完成串口写入及 flash read-back 校验，结果为 **verify OK (digest matched)**。板卡重启后的 HELLO 上报：

- firmware_version=0.1.0+43e3ece
- protocol_version=1
- capabilities 包含 spp_control、spp_reverse、remote_diagnostics、device_status、device_events、audio_resource_http、audio_control。

板卡固件版本与 P6 分支 clean build 镜像对应。镜像和 NAS 原始记录保存在 /volume1/docker/tivoo-esptool/artifacts/p6b6/；本仓库也保留了[实机原始验收日志](2026-11-12-p6b6-device-acceptance.txt)。

## 真实设备验收

测试时短暂停止 HA 以释放单 client TCP socket；测试脚本退出时自动启动 HA。持久 tivoo-esptool 容器始终保持运行。测试完毕后 HA 恢复，两条 NAS → ESP32 连接均重新达到 ESTABLISHED。

| 项目 | 真实设备观察 | 结果 |
|---|---|---|
| HELLO / capabilities | 新固件 0.1.0+43e3ece，P6 能力声明完整 | PASS |
| GET_STATUS / DEVICE_STATUS（C08） | request_id 原样回显；Wi-Fi connected、IP 192.168.3.28、RSSI -10 dBm；7777/7778 connected；SPP connected 并回报当前已配对 peer；audio resource idle | PASS |
| DEVICE_EVENT（C09） | 对真实 Tivoo SPP 链路执行断开/重连，依次收到 spp_disconnected、spp_connecting、spp_connected | PASS |
| ERROR（C10） | 向 7778 发送结构合法但缺少字段的 TTS_PLAY {}，真实收到 protocol_invalid_payload，module 为 audio_resource | PASS |
| 7777 单独断开（C17） | 关闭 7777 TCP socket 后，在未断开的 7778 socket 上再次 GET_STATUS，设备报告 7777 disconnected、7778 connected | PASS |
| 7777 恢复（C17） | 新建 7777 socket 后，再通过原 7778 socket 查询，两个端口均报告 connected | PASS |
| 长文本滚动压力（7777） | 3 组中英文滚动内容，394 个动画协议块、82,429 bytes；7777/7778/SPP 持续 connected，未观察到 ERROR | PASS（传输稳定性） |
| HTTP chunked / 未知长度（C13–C14） | 256 KiB 资源得到 resource_ready，bytes_received=262144 | PASS |
| 大资源流式（C14） | 10 MiB chunked 资源得到 resource_ready，bytes_received=10485760；超过板载 8 MiB PSRAM，未整段缓存 | PASS |
| 同时请求限制（C15） | 活动 GET 期间提交另一个 playback，收到 audio_busy | PASS |
| 过期 STOP（C15） | expected_audio_id 不匹配时服务端继续发送，活动请求未被停止 | PASS |
| 匹配及重复 STOP（C15） | 匹配 STOP 后状态 stopped；重复相同 STOP 没有额外状态/错误帧 | PASS |
| MIME 错误（C13/C16） | HTTP 200 但 Content-Type 不匹配，状态 failed、audio_content_type_mismatch、0 bytes | PASS |
| HTTP 错误（C13/C16） | HTTP 503 返回 audio_http_status，状态 failed、0 bytes | PASS |

此前 [P6b1 真实设备报告](2026-11-12-p6b1-tcp-control-spp-reverse-channel.md)已经验证 SPP DATA_IND 原始数据经 reverse queue → TCP 7777 → HA adapter 返回，亮度状态回显共收到 82 bytes；本报告复用该实机证据，不重复制造另一套 SPP 测试装置。此前 [P6b2 报告](2026-11-12-p6b2-tcp-diagnostic-heartbeat-device-status.md)也记录了 7778 心跳与失联重连时 7777 保持在线的设备观察。

## P6-C01–C20 逐项证据索引

| 合同 | 结果 | 主要证据 |
|---|---|---|
| C01 | PASS | HA/ESP32 P5 regression；P6b0–b6 联合回归 |
| C02 | PASS | P6b1 实机 SPP DATA_IND 原始返回；test_p6_reverse_channel.py |
| C03 | PASS | 0x69/0x96 状态提示与解析测试；P6b1 报告 |
| C04 | PASS | 有界 reverse queue、满队列/断线测试；C17 实机独立断线 |
| C05 | PASS | C/Python golden test；P6 codec、拆包/粘包及 Sequence 测试 |
| C06 | PASS | HELLO/ACK 测试及新固件实机 HELLO |
| C07 | PASS | 15s PING / 45s timeout 自动化与 P6b2 设备验收 |
| C08 | PASS | 本报告 GET_STATUS 实机快照 |
| C09 | PASS | 自动化 transition/dedup 测试及本报告真实 SPP 事件 |
| C10 | PASS | error schema/redaction 与本报告真实 ERROR |
| C11 | PASS | MIC schema、binary PCM 边界、bounded async iterator、mock receiver 测试 |
| C12 | PASS | HA Core internal_url/LAN fallback、TTS Pipeline event 顺序及 TTS_PLAY payload 测试 |
| C13 | PASS | HTTP 2xx/MIME 自动化与本报告真实 HTTP fixture |
| C14 | PASS | chunked/unknown length、有界 reader 测试及 256 KiB/10 MiB 实机数据 |
| C15 | PASS | busy、stale/matching/repeated STOP 自动化及本报告实机数据 |
| C16 | PASS | error/state 自动化及 MIME/503 设备观察 |
| C17 | PASS | HA reconnect/独立通道自动化；此前 7778 失联实测；本报告 7777 单独断开/恢复实测 |
| C18 | PASS | 源码/构建范围审查：没有实现 I²S RX/AEC/VAD、decoder/SRC、I²S TX 或播放管理器 |
| C19 | PASS | SPP 原始字节与固定 hint 合同测试、P6b1 实机 reverse evidence；未添加 command ACK/message bus |
| C20 | PASS | HA 288 passed、ESP32 52 passed、IDF clean build、P6b6 设备验收 |

## 未运行项与边界

以下项目不属于已经通过的物理观察，保留为后续验证项：

1. **Wi-Fi AP 实际关闭/恢复测试：NOT RUN。** 当前 NAS 设备连接条件不具备安全地控制 AP 开关的途径；未通过停 NAS 网络来模拟 Wi-Fi 故障。已有 P5 用户实测 ESP32 断电过夜后重新通电能自动重连 Wi-Fi，且本批真实 GET_STATUS 验证了当前 Wi-Fi 信息。
2. **使用工作区最新 HA transport.py 的端到端实机断线重连：NOT RUN。** NAS 当前安装的 transport 文件与本工作区版本不同。本批未擅自部署或覆盖 NAS HA 集成；C17 的设备侧端口独立性已用真实 TCP socket 验证，HA 对应重连行为通过自动化测试覆盖。NAS 原有 HA 服务已恢复，7777/7778 均 ESTABLISHED。
3. **真实 HA Pipeline/TTS Proxy 到新固件的完整语音链路：NOT RUN。** 本批实机用 7778 直接下发 TTS_PLAY 到 NAS 受控 HTTP fixture，验证 ESP32 HTTP reader；HA URL builder、流式/非流式 Pipeline 事件与下发行为由 P6b4 自动化测试覆盖。没有声学播放结论。
4. **生产 HTTPS endpoint 的 TLS 握手：NOT RUN。** 实机 HTTP 使用内网 LAN HTTP；ESP-IDF 标准 CA bundle 配置、证书验证路径和 clean build 已检查，未为验收专门引入自签证书设施。
5. **真实 MIC_SESSION/MIC_PCM producer：NOT RUN / P7。** P6 没有 I²S microphone producer；INMP441 未参与 P6 验收。P6b3 的 schema、binary PCM 和有界 HA dispatch 通过自动化/mock receiver 测试。
6. **音频解码、DAC 输出与播放完成状态：NOT RUN / P8。** P6 只将 HTTP 字节交给 reader；resource_ready 不代表音频已经播放。没有连接 DAC 也不影响 P6b6。
7. **P6.5 Pipeline/TTS Proxy/AstrBot 取消传播：NOT RUN。** 由 P6.5 单独负责，不纳入 P6。
8. **Tivoo 屏幕视觉帧连续性：NOT RUN。** 本批已发送 394 个长文本动画协议块、82,429 bytes，且两条 TCP 与 SPP 连接稳定；当前没有屏幕采集/摄像头，无法自动判断实际像素帧是否连续或是否有显示端丢帧。原始传输压力日志见 [scroll stress record](2026-11-12-p6b6-scroll-stress.txt)。
9. **P5 JTAG 软件重启、第二台 Tivoo 更换配对等历史遗留项：仍按 P5 文档记录。** 本批 app-only flash 未擦除 NVS，现有配对数据保留。

上述 NOT RUN 项不会被编译、模拟器或 GET_STATUS 证据代替，也不改变 C01–C20 的合同验收结果。

## Review 与交付状态

- 已自审新增 golden test、报告和阶段文档；确认没有改变 P6 协议、固件业务逻辑、NAS HA 集成或 P6.5/P7/P8 范围。
- 未使用独立 reviewer/subagent；本报告记录的是作者自审。
- NAS 的 HA component 未部署；HA 容器与持久 esptool 容器均恢复运行。
- P6b6 变更仅本地提交；不 push、不 merge。
