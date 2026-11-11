# P5 ESP32 最小固件合同矩阵

> 状态：待执行；本文件是 P5 实施与验收权威合同
> 日期：2026-11-11
> 分支：`feature/p5-esp32-minimal-firmware`
> 硬件：Waveshare ESP32-DEV-KIT-WROVER-E-M，SKU 35528，模组 ESP32-WROVER-E-N16R8
> 技术基线：ESP-IDF v6.1，`IDF_TARGET=esp32`

## 1. 目标与阶段边界

P5 交付一份能运行于指定 WROVER-E 板子的 ESP-IDF 固件：连接 Wi-Fi；接受 HA 通过 TCP 7777 发来的 Tivoo 原始控制命令并转发到 Classic Bluetooth SPP；通过 TCP 7778 完成设备握手、基础日志和错误回传。

**P5 只实现最终通信规格的最小子集。** 使用最终端口和 7778 的最终 16-byte TVIO 封装，不创造临时端口或第二套日志协议。

| 阶段 | 本项目责任 | 不提前承担的工作 |
|---|---|---|
| P5 | Wi-Fi Station、TCP 7777 单向 Tivoo→SPP 控制、TCP 7778 HELLO/ACK/诊断日志/错误 | SPP 回传、完整状态/心跳、麦克风 PCM、TTS/HTTP、I²S/AEC/VAD |
| P6 | 在 P5 通路上完成双向 7777/7778、设备状态/事件/音频消息、连接管理和 HTTP 音频资源 GET | 不重做 P5 已验收协议 |
| P7 | I²S RX、经典 ESP32 ESP-SR AFE AEC/VAD、Assist Satellite 麦克风上行 | 不把本地 WakeNet 或 S3 专用 AEC 当作 WROVER-E 能力 |
| P8 | I²S TX、PCM5102、解码/SRC、统一音频输出和停止 | 不归入 P5 最小固件 |

P5 的“HA 可控制 Tivoo”只表示控制命令经网络到达 ESP32 并交给 SPP。由于 P5 不实现 SPP 反向数据通道，不能将 TCP 写入成功描述为 Tivoo 已确认执行；实际显示结果由实机观察验收，SPP 连接/错误状态通过 7778 诊断日志查看。

## 2. 固定硬件与构建目标

| 项目 | 合同 |
|---|---|
| 开发板选项 | Waveshare 商品页选择 **ESP32-DEV-KIT-WROVER-E-M**，SKU **35528**；不是 WROOM、WROVER-IE 或 ESP32-S3 |
| 模组 | ESP32-WROVER-E-N16R8 |
| 芯片/架构 | 原始 ESP32，双核 Xtensa LX6；使用 Classic Bluetooth |
| Flash | 16 MB |
| PSRAM | 8 MB |
| USB-UART | CH343P；USB-C |
| ESP-IDF target | `esp32` |
| 蓝牙 host stack | Bluedroid；P5 使用 Bluetooth Classic SPP，不使用 NimBLE 代替 SPP |
| 天线/引脚 | GPIO、I²S 引脚和外设接线不得在本合同中猜定；按实际板卡引脚图与用户最终接线在对应硬件批次确认 |

**刷写边界：** ARM Ubuntu 负责源码、编译、测试与合并镜像打包，不要求其访问 USB/串口。Windows 仅接收已验收的最终镜像并负责刷写；不在 Windows 安装或维护开发工具链，不在 Windows 编译/调试。P5 不以开发机 USB 串口可用作为前置条件。

硬件规格来源：[Waveshare ESP32-DEV-KIT-XX 商品页（选择 ESP32-DEV-KIT-WROVER-E-M）](https://docs.waveshare.net/ESP32-DEV-KIT-XX/?variant=ESP32-DEV-KIT-WROVER-E-M)；模组存储配置参考 [Espressif ESP32-WROVER-E 数据手册](https://documentation.espressif.com/esp32-wrover-e_esp32-wrover-ie_datasheet_en.html)。

## 3. 开发环境与全阶段版本锁

### 3.1 固定版本决策

| 层 | 固定候选版本 | 兼容性依据/约束 |
|---|---|---|
| ESP-IDF | **v6.1** | ESP32 v6.1 官方编程指南；作为 P5–P8 唯一框架基线，须通过 B0 组合 API 编译/链接门 |
| IDF 安装器 | Espressif Installation Manager CLI（EIM，Linux AArch64） | 官方 EIM Linux CLI；显式选择 v6.1，不使用“自动安装最新版本” |
| Xtensa 工具链 | **`xtensa-esp-elf esp-15.2.0_20251204`（linux-arm64）** | ESP-IDF v6.1 `tools/tools.json` 明确列有 linux-arm64 下载项；由 EIM 按该版本工具清单安装，不使用主机 GCC 或 x86 模拟 |
| ESP-SR | **2.6.1** | 组件清单要求 IDF `>=5.0`；存在 `include/esp32/` AFE API 与 ESP32 预编译库；2.5.0 changelog 已记录修复 IDF v6.1 Kconfig 兼容性 |
| ESP Audio Codec | **2.6.2** | 组件清单要求 IDF `>=4.4`；ESP32 在支持目标表中；Simple Decoder 提供 MP3/WAV 流式入口及 `get_info()` 获取实际 PCM 格式 |
| ESP Audio Effects | **1.4.5** | ESP32 支持；Rate Conversion 的源/目标采样率需为 4,000 或 11,025 的整数倍，22,050→32,000 Hz 满足该约束 |
| ESP-SR 传递依赖 | 由锁文件解析；清单当前包含 `esp-dl ~3.3.12`、`dl_fft >=0.6.0`、`cjson ^1.7.19`，以及 ESP32 target 条件下的 `esp-dsp 1.8.0` | 由 `dependencies.lock` 固定完整解析结果，不手动漂移 |
| Audio Effects 传递依赖 | `espressif/gmf_fft ~1.1` | 由 `dependencies.lock` 固定 |

选择 v6.1 是为了固定在同一代 IDF 上实现 P5 网络/SPP、P6 HTTP、P7 I²S/AFE 与 P8 解码/SRC。静态资料证明各组件的 IDF 下限和 ESP32 目标声明覆盖该组合，但这不等于整个组合已实机验证；**B0 的组合 smoke build 是进入固件实现的强制兼容性门**。

### 3.2 B0 必须冻结的内容

- 使用官方 Linux AArch64 EIM CLI，显式选择 **ESP-IDF v6.1**（命令 `eim install -i v6.1`）；记录实际 `idf.py --version`、IDF Git revision、EIM 版本和 Xtensa 编译器版本。EIM `-i` 参数用于指定 IDF 版本；不得使用无版本参数安装的 latest、`master`、v6.2 预发布版或未记录版本。
- 使用 EIM 管理 IDF 所需工具及 Python virtual environment；不得把 ESP-IDF Python 依赖安装到系统 Python，也不得让主机 Python 3.14 环境成为 IDF 运行时。
- 设置并固定 `IDF_TARGET=esp32`。Bluedroid/SPP 的关键 IDF v6.1 Kconfig 应在生成的 `sdkconfig` 中确认为：`CONFIG_BT_ENABLED=y`、`CONFIG_BT_BLUEDROID_ENABLED=y`、`CONFIG_BT_CONTROLLER_ENABLED=y`、`CONFIG_BT_CLASSIC_ENABLED=y`、`CONFIG_BT_SPP_ENABLED=y`。不要照搬上游旧版 `hardware_bluetoothctl.h` 中的 `CONFIG_BLUEDROID_ENABLED` 宏名；IDF v6.1 使用 `CONFIG_BT_BLUEDROID_ENABLED`。项目配置/检查脚本必须拒绝错误 target 或非 v6.1 IDF。
- 在项目组件清单中精确固定 ESP-SR 2.6.1、ESP Audio Codec 2.6.2、ESP Audio Effects 1.4.5；提交生成的 `dependencies.lock`，锁住所有传递依赖。
- 在同一个 ESP-IDF v6.1 / `esp32` target 的兼容性 smoke build 中同时引入三种组件，并实际编译/链接后续会用到的 API。SPP 编译 `esp_bt_controller_init/enable()`、`esp_bluedroid_init/enable()`、`esp_bt_gap_register_callback()`、`esp_spp_register_callback()`、`esp_spp_enhanced_init()`、`esp_spp_start_discovery()`、`esp_spp_connect()`、`esp_spp_write()`、`esp_spp_disconnect()`；I²S 编译 `i2s_new_channel()`、`i2s_channel_init_std_mode()`、`i2s_channel_enable()`、`i2s_channel_read()`、`i2s_channel_write()`；Wi-Fi 编译 `nvs_flash_init()`、`esp_netif_init()`、`esp_event_loop_create_default()`、`esp_netif_create_default_wifi_sta()`、`esp_wifi_init()`、`esp_wifi_set_mode()`、`esp_wifi_set_config()`、`esp_wifi_start()`、`esp_wifi_connect()`；Socket 使用 IDF lwIP BSD API；AFE 编译 `afe_config_init("MR", NULL, AFE_TYPE_SR, AFE_MODE_HIGH_PERF)`、`esp_afe_handle_from_config()`、`create_from_config()`、`feed()`、`fetch()`、`get_feed_chunksize()`；Simple Decoder 编译 `esp_audio_simple_dec_open/process/get_info/close()`；SRC 编译 `esp_ae_rate_cvt_open/process/get_max_out_sample_num/close()` 并配置 22,050 Hz→32,000 Hz、Mono、S16LE。分别通过而组合链接失败不算通过。
- smoke build 必须覆盖 Classic SPP initiator、Wi-Fi STA/TCP socket、I²S Standard TX/RX 同 Controller 全双工、ESP-SR ESP32 AFE 的 MR 输入/AEC/VAD 配置、MP3/WAV Simple Decoder 入口、22,050→32,000 Hz SRC 配置。AFE 配置调用 `afe_config_init("MR", NULL, AFE_TYPE_SR, AFE_MODE_HIGH_PERF)`，再设置 `aec_init=true`、`aec_mode=AEC_MODE_SR_HIGH_PERF`、`vad_init=true`、`vad_mute_playback=false`；输入是 16 kHz signed 16-bit，MR 交错格式最后一个 channel 是 playback reference，帧长按 v2.6.1 的 `get_feed_chunksize()` 查询，不硬编码。SRC 测试配置按 v1.4.5 头文件设定 `src_rate=22050`、`dest_rate=32000`、`channel=1`、`bits_per_sample=16`、`complexity=3`，`perf_type` 在 B0 同时编译合法枚举选项，最终运行档由 P8 实机性能测试确定。此阶段只编译/链接，不启动音频实时任务或模型。Codec 的 MP3 实际输出采样率/声道由 `esp_audio_simple_dec_get_info()` 在后续设备音频测试读取，不在合同中假定一定是 22,050 Hz Mono。
- WROVER-E-N16R8 的 B0 构建配置必须是 `CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y`、`CONFIG_SPIRAM=y`、`CONFIG_SPIRAM_TYPE_ESPPSRAM64=y`、`CONFIG_SPIRAM_USE_MALLOC=y`、`CONFIG_SPIRAM_SPEED_40M=y` 和 `CONFIG_SPIRAM_BANKSWITCH_ENABLE=y`；ESP32 target 的 Quad PSRAM 模式由 IDF v6.1 Kconfig 默认开启（生成配置应显示 `CONFIG_SPIRAM_MODE_QUAD=y`），启动初始化默认开启（`CONFIG_SPIRAM_BOOT_INIT=y`）。B0 验收构建配置和 partition layout；最终镜像首次刷写后的实机阶段再验证 16MB Flash/8MB PSRAM 实际识别及可用 heap，不能将 cross-build 当作硬件初始化通过。
- 如任一目标组件不能在 IDF v6.1/经典 ESP32 下编译或链接，**P5b0 停止**：先修正组件版本/依赖锁/框架基线并重新通过整组 smoke build，再开始 P5b1。不得把问题留到 P7/P8 后再迁移整个固件。B0 只证明 API 编译/链接和配置闭合，不宣称 AEC 音质、MP3 性能或音频任务负载已在 WROVER-E 上通过；这些由 P7/P8 的硬件验收完成。

B0 是 P5 和后续 P6/P7/P8 共用的唯一框架版本门。通过后，P5 到 P8 沿用同一 IDF v6.1 和依赖锁；框架升级必须作为单独迁移任务，不能在某个后续批次顺手升级。

### 3.3 主机工具与构建约定

- EIM/IDF 使用自己的 Xtensa 工具链、CMake/Ninja 和 Python 环境；系统已有 GCC、CMake、Ninja 不代替 IDF 指定版本工具。
- Ubuntu 系统依赖按 IDF v6.1 Linux 安装文档检查，缺少时补齐 `flex`、`bison`、`gperf`、`ccache`、`dfu-util` 等包；已有的 `libffi-dev`、`libssl-dev`、`libusb`、CMake、Ninja 不重复安装。
- 初次构建以可复现的 IDF CMake 工程为唯一固件工程；不引入 PlatformIO/Arduino framework 作为第二个构建系统。
- 先使用有限并行度完成 B0 smoke build；后续根据 ARM Ubuntu 实际内存/交换情况设定并行度。
- P5 产物由 IDF 构建与 `idf.py merge-bin` 生成；合并地址/烧录参数使用 IDF 本次构建生成的 flash arguments，不手写猜测偏移。输出合并镜像、构建版本/commit 清单及 SHA256。Windows 不需要源码或 IDF 工程即可刷写。

### 3.4 官方版本/API 依据

- [ESP-IDF v6.1 Linux / EIM 安装](https://docs.espressif.com/projects/esp-idf/en/v6.1/esp32/get-started/linux-setup.html)
- [ESP-IDF v6.1 SPP API](https://docs.espressif.com/projects/esp-idf/en/v6.1/esp32/api-reference/bluetooth/esp_spp.html)
- [ESP-IDF v6.1 Classic Bluetooth](https://docs.espressif.com/projects/esp-idf/en/v6.1/esp32/api-reference/bluetooth/classic_bt.html)
- [ESP-IDF v6.1 I²S API](https://docs.espressif.com/projects/esp-idf/en/v6.1/esp32/api-reference/peripherals/i2s.html)
- [ESP-IDF v6.1 `tools.json`（Xtensa linux-arm64 工具链版本）](https://github.com/espressif/esp-idf/blob/v6.1/tools/tools.json)
- [ESP-IDF v6.1 ESP32 PSRAM Kconfig](https://github.com/espressif/esp-idf/blob/v6.1/components/esp_psram/esp32/Kconfig.spiram)
- [ESP-IDF v6.1 Bluedroid Kconfig](https://github.com/espressif/esp-idf/blob/v6.1/components/bt/host/bluedroid/Kconfig.in)
- [ESP-IDF v6.1 SPP API header](https://github.com/espressif/esp-idf/blob/v6.1/components/bt/host/bluedroid/api/include/api/esp_spp_api.h)
- [ESP-IDF v6.1 Log API header](https://github.com/espressif/esp-idf/blob/v6.1/components/log/include/esp_log_write.h)
- [ESP-SR 2.6.1 Component Registry](https://components.espressif.com/components/espressif/esp-sr/versions/2.6.1/readme)
- [ESP-SR 2.6.1 component manifest](https://github.com/espressif/esp-sr/blob/b6774a31118de04742e51ab57dd68c9001fa1091/idf_component.yml)
- [ESP Audio Codec 2.6.2](https://components.espressif.com/components/espressif/esp_audio_codec/versions/2.6.2/readme)
- [ESP Audio Codec component manifest](https://github.com/espressif/esp-adf-libs/blob/7162d32381d6e1f8c8cba2ee5edcbfe82bc964b1/esp_audio_codec/idf_component.yml)
- [ESP Audio Effects 1.4.5](https://components.espressif.com/components/espressif/esp_audio_effects/versions/1.4.5/readme)
- [ESP Audio Effects component manifest](https://github.com/espressif/esp-adf-libs/blob/7162d32381d6e1f8c8cba2ee5edcbfe82bc964b1/esp_audio_effects/idf_component.yml)

## 4. 本地代码复用基线

P5 的 Tivoo TCP/SPP 适配以工作区现有仓库为参考，不把它的 Arduino 网络运行时搬入 ESP-IDF：

- 来源：`BluetoothBridgeTest/esp32-divoom`
- 已核对 commit：`e90a77bbade7e92523bfb5b69bc5cb1e4d167520`
- 许可证：仓库 `LICENSE` 为 MIT；复制/改编代码保留原版权和许可声明。
- `components/divoom/util.cpp/.h`：优先复用 `getFrameSize()`、`isFramePending()`、`appendFrames()` 的 Tivoo 数据帧识别、TCP 拆包/粘包和未完成帧保留逻辑。缓冲基线 `FRAME_BUFFER_SIZE=4608`；接收块使用 IDF 当前 `CONFIG_LWIP_TCP_MSS`，不得硬编码假定一次 recv 即一个完整帧。
- 上游 `appendFrames()` 的 pending 检查只识别以 `0x01` 开头的 Tivoo 数据帧，不会自动保留被拆开的 `0x69`/`0x96` 固定长度控制命令。P5 必须在 TCP 字节流入口增加最小的 7-byte 控制命令累积/解析，再将普通 Tivoo 数据帧交给上游 frame parser；不重写数据帧 checksum/escape 实现。
- `components/divoom/input_tcp.cpp`：复用其 `0x69` 连接、`0x96` 断开、`0x01...0x02` 原始 Tivoo frame 识别与 15 ms pacing 的协议行为；使用 ESP-IDF 原生 BSD socket 替换 Arduino AsyncTCP。
- `components/divoom/bluetooth_spp.cpp`、`hardware_bluetoothctl.cpp`、`output_bluetooth.cpp`：复用 Bluedroid SPP initiator、SDP SCN 发现、发送队列/拥塞事件处理和数据转发职责；按照 IDF v6.1 SPP API 做最小适配，不把 Arduino/PlatformIO 平台层带入固件。
- 不重复实现图片量化、调色板或动画帧编码；这些仍由 HA 侧现有 Python Tivoo 编码逻辑完成。

来源代码的 `platformio.ini` 使用 Arduino framework 和 AsyncTCP，是上游工程自身的构建方式，不是本项目采用的构建方式。本项目唯一固件框架为 ESP-IDF v6.1。

## 5. P5 网络拓扑与配置合同

### 5.1 连接方向

| 通道 | ESP32 角色 | HA 角色 | 固定端口 | P5 内容 |
|---|---|---|---:|---|
| Tivoo 控制桥 | TCP Server | TCP Client | **7777** | HA 发送控制帧；ESP32 转发到 Tivoo Classic SPP |
| 诊断/握手 | TCP Server | TCP Client | **7778** | HELLO/ACK、DIAGNOSTIC_LOG、ERROR |

- ESP32 使用 Wi-Fi Station 加入用户指定的 2.4 GHz WLAN；取得 IP 后才启动两个 TCP Server。
- ESP32 不开放 HTTP Server，不直接连接 NAS/AstrBot/MCP/云端服务。
- HA 是 ESP32 的唯一业务网络客户端。HA 连接 ESP32 的用户配置地址；建议路由器对 ESP32 做 DHCP reservation，避免地址变化导致 HA 连接失效。
- P5 不增加 mDNS、MQTT、WebSocket、UDP、HTTP 日志或第三个 TCP 端口。
- 两条 TCP 通道相互独立。7778 断开不主动拆除仍工作的 7777/SPP；7777 断开也不阻止 7778 日志回传。

### 5.2 Wi-Fi 凭据和 HA 配置

- ESP32 使用 ESP-IDF 原生 `esp_wifi` Station API；初始化调用 `nvs_flash_init()`、`esp_netif_init()`、`esp_event_loop_create_default()`、`esp_netif_create_default_wifi_sta()`，再按 `esp_wifi_init()`、`esp_wifi_set_mode(WIFI_MODE_STA)`、`esp_wifi_set_config(WIFI_IF_STA, ...)`、`esp_wifi_start()` 启动；在 `IP_EVENT_STA_GOT_IP` 后启动两个 TCP Server，断线由 `WIFI_EVENT_STA_DISCONNECTED` 处理并重连。不实现 AP 配网门户。
- SSID/密码由本地 Kconfig/menuconfig 输入并写入被 Git 忽略的 `sdkconfig`。不得写入 `sdkconfig.defaults`、源码、日志或 Git。发布的最终二进制包含运行所需的设备网络配置，交付时按用户本地网络生成。
- ESP32 使用 DHCP 获取地址。HA Tivoo Config Flow 增加必需的 `esp32_host`（用户配置的 ESP32 局域网地址/主机名）和可编辑的 `tivoo_bluetooth_mac`；MAC 默认值为本地实测协议记录的 `11:75:58:97:49:98`。P4 当前 Config Entry 还只有 `media_directory`：P5 必须保留该字段并迁移 Entry 版本；旧 Entry 不得猜测设备地址，未配置 `esp32_host` 时传输状态保持 unavailable，并要求用户通过集成重新配置补齐主机地址。
- 7777、7778 为本合同固定端口，不提供配置项；配置错误时不得静默改用其他端口。
- Wi-Fi 断开时，停止接受新的网络控制数据并记录状态；按 ESP-IDF Station 事件恢复连接。网络日志队列不得阻塞 Wi-Fi 事件任务。

## 6. TCP 7777：Tivoo 原始控制桥

### 6.1 连接控制命令

TCP 7777 是原始字节流，不是 JSON，也没有新增外层头部。P5 使用以下上游协议字节：

| 命令 | 字节格式 | 含义 |
|---|---|---|
| SPP 连接 | `69 <MAC:6 bytes>` | `0x69` 后跟 6 个原始蓝牙 MAC 字节；P5 使用用户配置 MAC |
| SPP 断开 | `96 <MAC:6 bytes>` | `0x96` 后跟 6 个原始蓝牙 MAC 字节 |
| Tivoo 控制帧 | `01 <frame bytes...> 02` | 完整 Tivoo 原始协议帧，不转成十六进制文本 |

P5 的 MAC 默认值 `11:75:58:97:49:98` 在 TCP 中以六个二进制字节发送：`11 75 58 97 49 98`。不得发送 ASCII 字符串 `"11:75:58:97:49:98"`。

### 6.2 SPP 寻址与客户端角色

- ESP32 是 Bluetooth Classic SPP **initiator/client/master**，Tivoo 是远端 SPP acceptor；ESP32 不启动一个供 Tivoo 连接的本地 SPP Server。
- `0x69 + MAC` 不带额外通道字节时，沿用上游默认行为：先使用 SDP discovery 查找远端 RFCOMM SCN；上游 `SPP_CHANNEL_AUTO=0xFF00`。若 SDP 没有得到 SCN，按上游逻辑回退到 SCN **1**，与本机 `protocol-reference.md` 记录的 Tivoo RFCOMM Port 1 一致。
- P5 不扫描设备、不依赖 BLE GATT；直接使用已知 MAC 建立 Classic SPP。
- SPP 发送需处理 `ESP_SPP_CONG_EVT` 和 `ESP_SPP_WRITE_EVT`；TCP recv 任务只解析并入队，独立 SPP worker 执行 SDP/connect/disconnect 和发送，不能在 Wi-Fi/TCP 回调中等待 SPP 写完成。SPP 初始化使用 `esp_spp_enhanced_init()` 且 `cfg.mode=ESP_SPP_MODE_CB`，保证收到 DATA_IND/CONG/WRITE callback；P5 只消费 CONG/WRITE 事件，不处理 DATA_IND 反向数据。
- 发送队列沿用上游基线：`SPP_TX_QUEUE_SIZE=32`、聚合写缓冲 `SPP_TX_MAX=330` bytes、队列写入/拥塞/WRITE 完成等待各 1000 ms、SPP ready timeout 10000 ms、连接打开 settle 500 ms。P5 若需调整，必须记录原因并通过吞吐/断线测试。
- SPP 安全参数按 IDF v6.1 `esp_spp_api.h` 的 Security Setting Mask 列表处理：发起端允许 `ESP_SPP_SEC_NONE`、`ESP_SPP_SEC_AUTHENTICATE`、`ESP_SPP_SEC_AUTHENTICATE | ESP_SPP_SEC_ENCRYPT`；上游固定 commit 使用最后一种组合，P5 保留该上游行为。不要使用该头文件列为受限的 `ESP_SPP_SEC_AUTHORIZE`、`ESP_SPP_SEC_MODE4_LEVEL4` 或 `ESP_SPP_SEC_MITM`。实际 Tivoo 配对必须实机验收。
- 上游 GAP PIN 请求行为也按固定 commit 复用：收到 `ESP_BT_GAP_PIN_REQ_EVT` 时，若 `min_16_digit`，回复 16 个 ASCII `'0'`；否则回复 ASCII `1234`。若 Tivoo 实测要求固定 PIN，则通过项目私有 Kconfig 项提供覆写，不把 PIN 写入日志或提交到仓库。

### 6.3 Tivoo frame 格式与 TCP 流处理

本地 `BluetoothBridgeTest/tivoo/protocol-reference.md` 记录的普通 Tivoo 帧：

```text
01 <length_lo> <length_hi> <command> <params...> <crc_lo> <crc_hi> 02
```

- Length 为 payload 加 2-byte checksum 的长度，小端；checksum 是从 length 两字节起对 payload 求和的低 16 位，小端；外层结束字节为 `0x02`。
- 上游 `util.cpp` 还处理较大帧的 4-byte checksum 与转义内容；移植时以该固定 commit 的 `getFrameSize/isFramePending/appendFrames` 实现为准，不删减为只支持单个 recv 的简化解析器。
- TCP 是字节流：一个 frame 可以拆成多次 recv，多帧也可以粘在一次 recv；必须使用流缓存恢复完整 frame。
- 上游默认 `TCP_MAX=3`、`TCP_PACING=15 ms`、`FRAME_BUFFER_SIZE=4608`。P5 保留 15 ms frame pacing 和 4608-byte 帧流缓存基线；HA 常规只建立一个 7777 连接。
- TCP 分段测试必须分别覆盖：`0x69+MAC` 的 7 bytes 被拆成多次 recv、`0x96+MAC` 被拆分、Tivoo 数据帧被拆分、多个帧粘连及控制命令与数据帧相邻。控制命令不完整时不得调用 SPP，也不得把 MAC 尾部误转发为 Tivoo 数据。
- HA 已生成 Tivoo 命令/图像/动画原始帧；ESP32 不解码 PNG/JPG/GIF、不做像素调色板编码，只做 TCP frame 边界处理和 SPP 原样转发。

### 6.4 P5 的返回语义

P5 **不实现** 7777 SPP 反向数据通道，包括上游的 SPP DATA_IND 返回、连接状态单字节回送等。SPP 连接成功/失败、网络断开和帧发送错误经 TCP 7778 的 ERROR/DIAGNOSTIC_LOG 回报 HA。没有设备协议回执时，HA 不得显示 `confirmed` 或将发送成功等同于 Tivoo 屏幕已显示。

## 7. TCP 7778：P5 消息合同

### 7.1 固定消息封装

每条消息使用项目双向通信规格定义的 **16-byte little-endian TVIO header**：

| Offset | 长度 | 字段 | P5 约定 |
|---:|---:|---|---|
| 0 | 4 | Magic | ASCII `TVIO` |
| 4 | 1 | Version | `1` |
| 5 | 1 | Message Type | 本节列出的 P5 类型 |
| 6 | 2 | Flags | little-endian，P5 固定为 `0` |
| 8 | 4 | Payload Length | little-endian，无符号 payload 字节数 |
| 12 | 4 | Sequence | little-endian；每个发送方向独立计数，每条新 TCP 连接从 0 开始递增 |
| 16 | N | Payload | 对本节 JSON 消息使用 UTF-8 JSON object；不带 NUL 结束符 |

- 接收方按 Payload Length 组装完整消息，不假设一次 recv 就是一条消息。
- P5 JSON Payload 最大 16 KiB；诊断日志单条 JSON 最大 1 KiB。超限、非法 JSON、错误 Magic/Version 或无效长度不得导致任务崩溃。
- P5 保留未知 Message Type 忽略行为；错误协议版本通过拒绝 HELLO_ACK 后关闭本连接。
- P5 不发送 PCM binary payload，不发送图片/动画/TTS 文件。

### 7.2 P5 Message Type 子集

| Type | 名称 | 方向 | P5 行为 |
|---:|---|---|---|
| `0x01` | HELLO | ESP32 → HA | TCP 7778 建立后首条应用消息 |
| `0x02` | HELLO_ACK | HA → ESP32 | HA 接受或拒绝本次设备协议连接 |
| `0x41` | ERROR | ESP32 → HA | 设备侧错误 |
| `0x42` | DIAGNOSTIC_LOG | ESP32 → HA | 运行日志 |

其余已在总通信规格中分配的类型，按 P6/P7/P8 阶段实现；P5 不提前使用。

### 7.3 JSON Payload 结构

**HELLO**（必须字段）：

```json
{
  "device_id": "tivoo-esp32",
  "firmware_version": "0.1.0+<git-short-sha>",
  "protocol_version": 1,
  "capabilities": ["spp_control", "remote_diagnostics"],
  "reset_reason": "<ESP-IDF reset reason name>"
}
```

`device_id` 在 P5 固定为 `tivoo-esp32`；`firmware_version` 使用 SemVer 加构建 commit 短 SHA；`reset_reason` 来自 IDF `esp_reset_reason()`，不得用猜测的文本代替实际返回值。

**HELLO_ACK**：

```json
{"accepted": true}
```

拒绝时：

```json
{"accepted": false, "reason": "unsupported_protocol_version"}
```

`accepted` 必须为 boolean；拒绝时 `reason` 为非空字符串。P5 不发送 heartbeat/session 参数；心跳间隔由 P6 引入。

**DIAGNOSTIC_LOG**：

```json
{
  "level": "INFO",
  "module": "wifi_station",
  "message": "station_connected",
  "uptime_ms": 12345,
  "correlation_id": "optional-operation-id",
  "dropped_count": 0
}
```

- 必需字段：`level`、`module`、`message`、`uptime_ms`。
- `level` 只允许 `DEBUG`、`INFO`、`WARNING`、`ERROR`；ESP-IDF `WARN` 映射为 `WARNING`。
- 可选字段：`correlation_id`、`dropped_count`。丢弃计数为上次成功上报后累计被队列丢弃的日志数，在下一次成功日志上报后清零。
- 不包含墙钟时间；HA 收到时使用 HA 自己的接收时间。设备侧时间使用 `uptime_ms`。

**ERROR**：

```json
{
  "error_code": "spp_connect_failed",
  "module": "tivoo_spp",
  "message": "Classic SPP connection failed",
  "uptime_ms": 45678,
  "correlation_id": "optional-operation-id"
}
```

`error_code`、`module`、`message`、`uptime_ms` 必需；`correlation_id` 可选。P5 由 ESP32→HA 上报，不要求 HA→ESP32 错误消息。P5 项目 ERROR code 固定为：`wifi_connect_failed`、`tcp_listen_failed`、`spp_connect_failed`、`spp_disconnect_failed`、`spp_tx_queue_full`、`spp_write_failed`。SDP 未返回 SCN 但回退到 RFCOMM 1 时只发 WARNING `spp_scn_fallback`，不冒充连接失败；协议不兼容由 HELLO_ACK `accepted=false`/`reason` 表达，不额外定义 ERROR。以上为项目定义值，不是 Tivoo 上游帧协议的返回码。

## 8. 日志与故障证据

- 项目模块使用 `TIVOO_LOGE/W/I/D` 分级宏；宏同时调用对应 ESP-IDF `ESP_LOG*` 保留 UART/console 输出，并把明确的 level、TAG、格式化消息放入网络诊断队列。第三方组件内部日志仍走本地 UART；不解析全局格式化字符串推断日志级别，也不替换全局 `vprintf` handler。
- 日志通过非阻塞、有界 RAM 队列交给低优先级 TCP 发送任务；日志宏只格式化/入队，Wi-Fi callback、TCP recv 和 SPP event callback 不直接执行阻塞 socket send。
- 诊断队列初始默认深度 16 条，单条日志 `message` 最多 384 UTF-8 bytes，序列化后的 DIAGNOSTIC_LOG JSON 最大 1 KiB；达到上限时丢弃新记录并累计计数，不能等待队列空位。B0 必须记录队列静态/运行内存占用，若需调整只在 B0 阶段记录并冻结数值。
- 只有在 7778 握手成功且 `accepted=true` 后发送日志。断线期间暂存有限记录，重连并重新 HELLO/ACK 后按入队顺序补发；重启会丢失 RAM 队列，这是预期行为。
- 普通日志不逐条写 Flash，不建立日志文件系统，不让 ESP32 连接 NAS。启动时报告 Reset Reason；P5 不实现 Flash persistent log store 或 Core Dump 网络传输。
- HA Tivoo 集成将日志写入 `custom_components.tivoo` 标准 Python logger：设备 ERROR→ERROR、WARNING→WARNING、INFO→INFO、DEBUG→DEBUG。HA Container 主日志默认位于 `/config/home-assistant.log`；由既有 NAS `/config` volume 负责持久化，不创建第二套 NAS 日志收集服务。
- 禁止记录 Wi-Fi 密码、Authorization/API Token、短时音频 URL 凭据、原始 PCM、完整语音转写或完整 LLM 回答正文。只记录模块、短事件、错误码、设备 uptime、版本和关联 ID。

## 9. HA Tivoo 集成责任

- 保持 HA 为 ESP32 唯一业务入口。HA 使用 Config Entry 中的 `esp32_host` 作为 TCP 目标地址；固定连接 7777 和 7778。
- 在 P5 生产 Adapter 中实现：7777 TCP client、7778 TCP client、7778 header/JSON 编解码、HELLO/ACK、ERROR/DIAGNOSTIC_LOG 接收，以及断线后的重连和日志 logger 映射。
- 现有 `UnavailableCommandAdapter` 由 P5 的最小传输 Adapter 替换；业务服务仍通过现有 `TivooCommand` 语义接缝提交命令。命令转换继续复用 HA 侧已有 Tivoo frame/payload builder，不把原始字节接口暴露给 MCP。
- 7777 TCP 连接建立后发送一次 `0x69 + MAC`；同一连接中后续发送原始完整 Tivoo frames。连接重建后重新发送连接命令，再接受新的控制请求。
- 7778 断线重连独立于 7777，不重置正常的 SPP 连接；重连后重新 HELLO/ACK。
- TCP write 成功只能报告数据已提交给本地传输层；P5 不提供 SPP 反向数据或设备确认，HA 不得声称屏幕动作已被设备确认。
- 日志交由 HA 标准 logger，使用 HA 当前日志轮换/持久化配置，不在 integration 内自行追加文件。

## 10. P5 实施批次与合同门

| 批次 | 实施内容 | 退出条件 |
|---|---|---|
| **P5b0（首要任务）** | ARM64 EIM/ESP-IDF v6.1 环境；工具/Python 环境；ESP32 target；三项音频组件精确版本与依赖锁；Classic SPP、I²S、AFE、codec、SRC 组合 smoke build；16MB Flash/8MB PSRAM sdkconfig 与分区表检查 | 所有后续阶段所需 API 在 IDF v6.1 + ESP32 target 下组合编译/链接；依赖锁和环境版本记录提交；未通过不得开始 P5b1；不进行硬件刷写 |
| P5b1 | ESP-IDF 工程骨架、Kconfig Wi-Fi 凭据、Station 状态机、Reset Reason、7777/7778 listeners；HA Config Entry 迁移、reconfigure flow 和连接 Adapter 骨架 | 保留 P4 `media_directory`；旧 Entry 不猜 ESP32 地址，完成用户重新配置后才启用传输；自动化测试验证 IP 事件后启停监听、连接/断线状态和凭据不入仓库；使用网络模拟器，不刷写开发板 |
| P5b2 | 7778 TVIO framing、HELLO/ACK、ERROR/DIAGNOSTIC_LOG、HA logger 和断线补传 | 协议/HA 自动化测试通过；HA 日志进入标准 logger，由 NAS 上已有 HA `/config` 持久化；断线重连、补传、队列满和 dropped_count 测试通过 |
| P5b3 | 7777 raw bridge、固定长度控制命令累积、上游帧流解析复用、Classic SPP initiator、SDP/SCN fallback、原样 SPP 转发 | 网络模拟器、frame goldens、SPP mock 和分段测试通过；不在此批次刷写开发板 |
| P5b4 | 合并固件集成、故障注入、`merge-bin` 打包；将已通过构建及自动化验收的最终镜像交由 Windows 刷写，再通过 HA 网络验收 Wi-Fi/7777/7778/实际 Tivoo SPP | 所有 MUST 合同通过；Windows 只执行最终镜像刷写，不参与源码、构建、测试或日志分析；若修复后需要重新做实机回归，Windows 仍只重复刷写新生成的最终镜像；输出 merged image、flash 参数、版本清单和 SHA256 |

### 10.1 P5 合同矩阵

| ID | 合同 | 等级 | 验证方式 |
|---|---|---|---|
| P5-C01 | 开发环境锁定 ESP-IDF v6.1、target esp32 和完整组件依赖图；不得随 P6/P7/P8 漂移 | MUST | B0 版本输出、Git revision、dependencies.lock |
| P5-C02 | ARM64 主机能使用 EIM 获取 v6.1 Xtensa 工具链并完成原生交叉编译 | MUST | 工具版本、clean build |
| P5-C03 | ESP-SR 2.6.1、Audio Codec 2.6.2、Audio Effects 1.4.5 在同一 ESP32 target 组合编译/链接 | MUST | B0 combined smoke build |
| P5-C04 | Classic SPP API 使用 IDF v6.1 Bluedroid；生成配置启用 BT/Controller/Bluedroid/Classic/SPP 五项 Kconfig；不得以 NimBLE 或 ESP32-S3-only API 替代 | MUST | B0 sdkconfig assertion + SPP initiator compile |
| P5-C05 | I²S Standard TX/RX 以同 Controller 全双工 API 可编译 | MUST | B0 I²S compile smoke |
| P5-C06 | WROVER-E-N16R8 的 16MB Flash、Quad ESP-PSRAM64、40MHz PSRAM、PSRAM malloc 与 8MB bank switching 配置符合 IDF v6.1 | MUST | B0 sdkconfig assertion/build；真实容量与 heap 识别留最终镜像硬件验收 |
| P5-C07 | Wi-Fi Station 成功关联 WLAN 并获得 IP 后启动 7777/7778；HA 旧 Config Entry 迁移后须配置 `esp32_host` 才可连接 | MUST | Wi-Fi/IP event test、Entry migration/reconfigure test、最终镜像 HA TCP connect test |
| P5-C08 | ESP32 TCP Server 固定监听 7777 与 7778；HA 是 TCP Client | MUST | socket integration test |
| P5-C09 | 7777 接受 7-byte `0x69+MAC`、7-byte `0x96+MAC` 和完整 Tivoo raw frame；对两种控制命令进行独立的固定长度累积解析 | MUST | golden/frame tests + split-control tests |
| P5-C10 | SPP initiator 使用已配置 MAC，经 SDP 查找 RFCOMM SCN，失败回退到 SCN 1 | MUST | mocked GAP/SDP test + Tivoo 实机 |
| P5-C11 | TCP 拆包/粘包时只转发完整原始 Tivoo frame；控制命令与数据帧采用各自明确的流解析规则，数据帧复用上游 frame-stream parser | MUST | upstream goldens + control/data segmentation tests |
| P5-C12 | 7777 只做 HA→ESP32→SPP；不实现 SPP DATA_IND 回传/确认 | MUST | code review + negative test |
| P5-C13 | 7778 使用 TVIO magic、version 1、16-byte header 和 P5 message subset | MUST | header encode/decode tests |
| P5-C14 | HELLO/HELLO_ACK 字段及 accepted/reject 语义符合 §7.3 | MUST | schema + protocol tests |
| P5-C15 | DIAGNOSTIC_LOG / ERROR 使用明确的 JSON fields 和 level enum | MUST | schema tests + HA logger capture |
| P5-C16 | Reset Reason、firmware version、device ID 在启动 handshake 上报 | MUST | restart reason test / HELLO assertion |
| P5-C17 | 日志队列有界、非阻塞；网络断线不阻塞 SPP；重连后补传，队列满报告 dropped_count | MUST | queue saturation + disconnect/reconnect test |
| P5-C18 | HA 使用标准 Tivoo logger，日志由 HA 主日志和现有 NAS /config volume 持久化 | MUST | HA integration test + NAS path confirmation |
| P5-C19 | 凭据、PCM 和完整对话文本不出现在固件日志 | MUST | log redaction tests / source review |
| P5-C20 | Windows 不参与开发；ARM64 生成可独立刷写的 merged image 和校验信息 | MUST | artifact manifest + SHA256 verify |
| P5-C21 | P5 不实现完整 7777 reverse channel、7778 heartbeat/DEVICE_STATUS/audio messages、HTTP audio、I²S/AEC/VAD | MUST boundary | scope/code review |

## 11. 明确排除项与不得扩张的内容

P5 不实现：

- 7777 SPP 返回数据、状态字节回送、设备 ACK 或画面确认；
- 7778 PING/PONG 心跳、GET_STATUS/DEVICE_STATUS、DEVICE_EVENT、MIC_SESSION、MIC_PCM、TTS_PLAY、AUDIO_STOP、AUDIO_STATE、AUDIO_INTERRUPTED；
- HTTP Client 音频资源获取、HTTP Server、媒体流、PCM 和音频解码；
- I²S RX/TX 实际驱动、INMP441、PCM5102、ESP-SR AFE runtime、AEC/VAD runtime、SRC/decoder runtime；
- BLE GATT、WakeNet 本地唤醒、A2DP、OTA、Core Dump 网络回传、日志写入 Flash、配网门户、mDNS、MQTT 或额外协议；
- Windows 编译/调试/日志分析环境。

B0 为 P7/P8 提前验证组件兼容性，不等于 P5 实现了音频功能；P5 合并固件不需启动 AFE、codec 或 SRC。

## 12. 交付和验收产物

每批记录：基线 SHA、实际修改文件、IDF/组件版本、RED/GREEN 命令与结果、失败/阻塞项和提交 SHA。

P5 完成时至少产出：

- ESP-IDF 工程源码及 `sdkconfig.defaults`（不包含 Wi-Fi 凭据）；
- `dependencies.lock` 和 IDF v6.1 环境/工具版本记录；
- 可复现构建命令；
- IDF `merge-bin` 生成的完整合并镜像；
- 本次 build 的 flash arguments / offset 文件；
- 固件版本、Git commit、target、Flash 配置和 SHA256 manifest；
- P5b0–P5b4 验收结果。

**阶段退出条件：** P5-C01 至 P5-C20 全部 MUST 通过，P5-C21 边界检查通过；失败项不得通过修改 P6/P7/P8 合同来规避。
