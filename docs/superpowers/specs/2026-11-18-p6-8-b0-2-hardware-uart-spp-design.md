# P6.8b0.2 双板硬件、构建/烧录与 UART/SPP 桥接规格及合同矩阵

> 2026-11-18；设计基线 81b00ae。上承 [b0.1](2026-11-18-p6-8-b0-1-overall-design-baseline.md)、[路线 §1.1](../plans/2026-11-18-p6-8-s3-local-wake-roadmap.md) 和 [旧合同索引](2026-11-18-p6-8-legacy-contract-migration-index.md)。本批只定硬件、构建与控制桥合同；不实施、不烧录、不声称新板已验收。数字为设计值或注明的源码/资料证据，实机测量另列。

## 1. 硬件与接线

以微雪 N16R8-M（WROOM-1-N16R8、16MiB Quad flash、8MiB Octal PSRAM）和现有 WROVER-E-M（WROVER-E-N16R8、16MiB flash、8MiB Quad PSRAM）为基准。S3 承担网络与音频；WROVER 只承担 Classic SPP，无 Wi-Fi、I2S/AFE/HTTP 音频。S3 无 BR/EDR，不能直接代替经典板。两个板的 USB/UART0 保留独立刷写和日志，不作板间串口。

### 1.1 设计接线表（GPIO 编号，不是排针序号）

| 连接 | S3 GPIO / 电源 | 经典 ESP32 / 外设 |
|---|---|---|
| UART1 TX → RX | GPIO17 | GPIO19 (UART1 RX) |
| UART1 RX ← TX | GPIO18 | GPIO18 (UART1 TX) |
| 共同参考地 | GND | GND（包括双麦和 DAC） |
| I2S0 BCLK | GPIO4 | 两 INMP441 SCK + PCM5102 BCK |
| I2S0 WS/LRCK | GPIO5 | 两 INMP441 WS + PCM5102 LCK |
| I2S0 RX | GPIO6 | 双 INMP441 SD 共线（L/R 分别 GND/3.3V） |
| I2S0 TX | GPIO7 | PCM5102 DIN |
| 麦克风电源 | 3V3 / GND | 两模块 3.3V；先确认模块板引脚标记及 SD 高阻/下拉 |
| DAC 电源 | 保留现有已核验供电方式 | 按现有 PCM5102 模块实际 VIN/稳压及接线标识确认；不凭芯片电压为模块直接改供电 |
| 模拟音频 | 无 | PCM5102 L/R/GND → Tivoo AUX，保留既有连接 |

选脚依据：微雪 [S3 系列官方原理图](https://files.waveshare.com/wiki/ESP32-S3-DEV-KIT-N8R8/ESP32-S3-DEV-KIT-N8R8-schematic.pdf) 的 P1 GPIO4–7/17/18 均直连模组并引出；RGB_CTRL 是 GPIO38，原生 USB 为 GPIO19/20，CH343 接 UART0；图标注 N8R8，是同系列载板而非已取到 N16R8-M 实物版次的证据。[现行型号表](https://docs.waveshare.com/ESP32-S3-DEV-KIT-N8R8) 确认 N16R8-M、GPIO35/36/37 NC。微雪 [经典系列原理图](https://files.waveshare.com/wiki/ESP32-DEV-KIT-XX/ESP32-DEV-KIT-XX.pdf)（开发机成功读取）显示 GPIO18/19 引出、GPIO27 接 RGB、UART0 接 USB 转串口；图标注 WROOM-32E，另用 [WROVER-E 模组数据手册](https://documentation.espressif.com/esp32-wrover-e_esp32-wrover-ie_datasheet_en.html) 交叉确认 GPIO18/19 可用、16/17 为模组存储占用。IDF v6.1 本地 uart.h 提供 uart_set_pin 的 GPIO matrix 路由，两板使用 UART1 显式重映射，禁止经典板采用 UART 默认的 GPIO16/17。

- S3 禁止 GPIO0/3/45/46 启动绑带、GPIO26–32 存储总线、35–37 Octal 存储/NC、19/20 原生 USB、43/44 UART0、38 板载 RGB；不使用 39–42 JTAG 或未核实的 47/48。经典板禁 0/2/5/12/15 绑带、6–11 flash、16/17 PSRAM、1/3 UART0、34–39 输入专用脚不得作输出、27 RGB。经典板旧 26/25/32/33 音频连线迁走，保留 GPIO27 RMT 灭灯；S3 以 GPIO38 对应同类 RGB 灭灯，实际板版核实后再启用。电源指示灯不是 GPIO 控制对象。
- 初次上电前确认模块丝印、排针与实际载板版本、音频线不仍接经典板、无短路；若手中 S3 PCB 与官方图不符，暂停接线，修订本表，不随意试脚。I2S 共享时钟/双麦三态、电平与有效位、电声设计属于 b0.3；本表只锁 GPIO 资源，不预定 AFE 格式。
- 两板各自用 USB-C 5V 供电（可接同一有独立供电能力的 USB hub），只互连 3.3V TTL TX/RX/GND，不相连 5V/3V3 供电轨，不从一块板的 3V3 给另一块供电；USB 供电时不再从排针注入外部电源。S3 原理图的 VDDUSB 经肖特基与 3.3V LDO，经典板为 VSYS 与 3.3V DC/DC；不能把两板排针电源视为同一路。两板正常共电源上/下电；若要单板断电实验或独立供电，先断信号线或采用能保证断电高阻的隔离，禁止让有电 TX 向无电 MCU RX 持续注入。短线共地，远离 DAC 模拟线，必要时源端串阻/隔离在 b1 按信号测量决定，不把 UART 当 RS232/5V。
- 供电验证：b1 记录实际 USB 5V/3V3、两个麦及 DAC 模块电源条件，Wi-Fi+AFE+DAC+SPP 并发在 b3/b4/b10 测峰值电流、压降、无 brownout/重置；不以板级标称或单 MCU 平均电流给出 USB hub 容量保证。若供电不稳先换有源 hub/合适电源，不靠固件掩盖。

### 1.2 USB/烧录通道

S3 单 USB-C 内 CH334 hub 分出 CH343P UART0（DTR/RTS 自动下载）和原生 USB Serial/JTAG（GPIO19/20）；经典板独立 USB-UART。参考微雪 [S3 FAQ](https://docs.waveshare.com/ESP32-S3-DEV-KIT-N8R8/FAQ)。开发机或 NAS 连接两根 USB 数据线，可枚举各自端口而非 GPIO 串烧；S3 首选 CH343 下载/日志，原生 USB 作为独立验证/备用，具体设备节点由驱动与实际枚举决定。b1 用 lsusb、/dev/serial/by-id（若无则 by-path）、esptool chip_id / flash_id 对物理 USB 口和芯片类型建立映射；不硬编码 ttyUSB0/ttyACM0；容器只映射经过确认的端口，串口监视与 esptool 不同时占用。S3 原生 USB 与 CH343 不能误当两块 S3。首次接板或下载失败用相应板 BOOT+RESET 进入下载模式，不通过板间 UART 刷另一板。

## 2. 两个独立构建与 Flash/PSRAM

开发机实际激活 /home/Gold/.espressif/tools/activate_idf_v6.1.sh，IDF_PATH=/home/Gold/.espressif/v6.1/esp-idf，git describe 为 v6.1；现有 dependencies.lock 的 idf=6.1.0、target=esp32。保留版本，不自动升级。NAS esptool 容器仅刷写/诊断，不承担构建。本批不执行构建或修改 sdkconfig。

| 项目 | S3 主控 | 经典桥 |
|---|---|---|
| 独立 IDF project/target | esp32/firmware 迁为 esp32s3 | 新独立 esp32/bridge_firmware，esp32 |
| 配置与产物 | 各自 sdkconfig.defaults、sdkconfig、dependencies.lock、partition table、build/、版本及 target manifest；不得在原单板 build 内临时切 target 混用 | 同左；旧单板 sdkconfig 不能作为新默认；生产 fallback 保留 git 旧版本 |
| 依赖 | esp-sr 2.6.1 / codec 2.6.2 / effects 1.4.5，S3 单独解析锁；esp_driver_uart、I2S、GPIO、RMT、Wi-Fi、HTTP、cJSON 等原需要的组件 | esp_driver_uart、GPIO、RMT (RGB off)、NVS、BT、FreeRTOS 等；去掉 esp-sr/codec/effects/Wi-Fi/HTTP/I2S 直接依赖与运行启动；Bluedroid Classic BR/EDR_ONLY、SPP、SMP 派生配置仍须核对 |
| CPU / PSRAM | 240MHz、Octal PSRAM 初设 80MHz，SPIRAM_MODE_OCT / SPIRAM_SPEED_80M；16MiB flash Quad 模式初设 DIO 80MHz（实际检测并核验）；Wi-Fi/lwIP 优先 PSRAM；DMA/ISR 所需内存留内部 | 保留 240MHz、Quad 40MHz、原 bank switching 能力及 SPIRAM 优先 BT 分配；不能将 8MiB 物理当作 8MiB 线性 heap；不必在每次生产启动重复 4s 全盘 himem probe |
| NVS | 独立 NVS；Wi-Fi 凭据沿用不入库的本地配置机制 | 保持既有 NVS 及 Classic Bond；不得自动 erase |

S3 原始分区设计（十六进制，均 16MiB 内；b1 以 IDF 生成表、size/size-components、实际 flash_args 校验）：

| label/type/subtype | offset | size | 用途 |
|---|---:|---:|---|
| bootloader / partition table | 0x0 / 0x8000 | IDF 生成 | S3 ROM bootloader offset 与经典 0x1000 不同；不手抄刷写参数 |
| nvs / data / nvs | 0x9000 | 0x6000 | S3 独立 NVS |
| phy_init / data / phy | 0xf000 | 0x1000 | PHY |
| factory / app / factory | 0x10000 | 0x800000 | 8MiB app 含本地提示资产（b6） |
| model / data / spiffs | 0x810000 | 0x400000 | 4MiB 原始 srmodels.bin；不是挂载文件系统 |
| storage / data / spiffs | 0xc10000 | 0x3f0000 | 保留空间，结束 0x1000000；不因本批引入文件系统服务 |

经典桥保持现 esp32/firmware/partitions.csv 原始 NVS 0x9000/0x6000、PHY 0xf000/0x1000、factory 0x10000/0x800000、storage 0x810000/0x7f0000，不改变 Bond 所在分区。两个项目从 IDF 生成的 flasher_args.json/flash_args 获取实际 offsets/flash mode，不假定旧 app-only 包可用于 S3。

模型依据：开发机实际 managed_components/espressif__esp-sr 2.6.1（manifest repository commit b9dc43a329a68de2f72147808fc9ea29d2ace71e）的 CMakeLists.txt:138–160 按 label=model 取 size/offset，生成 build/srmodels/srmodels.bin，esptool_py_flash_to_partition(flash "model" ...)；src/model_path.c:510–533 esp_srmodel_init("model") 按 DATA label 查找并 mmap，不依赖 spiffs subtype 挂载；model/pack_model.py 头大小 4+36*模型数+40*文件数，加实际模型文件字节。实际本地模型目录 wn9/wn9l 最大文件总量 292449B，vadnet1_medium 287909B，nsnet 最大 nsnet1 825005B；三者合计约 1.41MB 未含小量包头，4MiB 有足够设计空间，但不据此选择具体算法/词或断言最终 S3 app/model 包能编译。b0.3 锁模型 Kconfig，b1/b4 以实际生成包、模型清单、size 与 mmap 成功为准；禁 MultiNet，禁复制整个模型目录/误将旧 model 镜像当新包。模型包与 app 一起记录 SHA256/版本，更新模型必须同步烧对应分区，即便 app offset 不变。

b1 构建/烧录出口：独立 idf.py build、两组生成依赖锁/target/分区/映像清单、app-only 与 16MiB full merged image（idf.py merge-bin --format raw --flash-offset 0x0 --pad-to-size 16MB，核对实际生成输入包含 S3 model）。每份附 git SHA、IDF、target、flash/PSRAM、offset+文件 SHA256。新 S3 首次安装可用完整包；经典现有已配对板禁止直接写覆盖 NVS 的 padded merged 包，沿用旧版同布局 app-only 或分段更新必要 bootloader/partition/app 且排除 NVS；若改变分区/NVS 需显式迁移决策。普通 S3 app-only 在模型未变且布局兼容时允许，否则分段写 model；恢复生产旧单板需保留旧固件及烧录清单。严禁跨 target 写入，b1 在 USB 枚举和 chip_id/flash_id 匹配后才允许烧录。实际运行日志证明 16MiB flash/PSRAM 物理与可用、分区与 target；S3 不套用 classic himem 配置，分别采集 internal heap、最大空闲块、IRAM/DRAM、PSRAM，音频负载峰值留 b3/b4/b10。

## 3. UART transport（仅两板私有，不改变 HA 协议）

### 3.1 选型与容量

使用 ESP-IDF v6.1 esp_driver_uart（本机 include/driver/uart.h 已核对 uart_driver_install、uart_set_pin、uart_read_bytes、uart_write_bytes、UART_FIFO_OVF/UART_BUFFER_FULL；RX/TX ring、事件队列）。UART1，3.3V、全双工 921600 baud / 8N1、无 RTS/CTS。设计首选 921600，两个物理板 b1/b2 验证误码/压测；若线材/电气实际不可靠，两端一起降 460800 再测，禁止单端自动猜 baud；若仍不可靠才修订布线/增加硬件流控，不先新增两根线。

保留原 4608B 最大 Tivoo wire frame，控制命令 7B。私有包采用 COBS（现成算法，如 https://github.com/cmcqueen/cobs-c ，不重造任意 byte escaping）+ 0x00 delimiter + CRC-32/ISO-HDLC（标准 check "123456789"=0xcbf43926，与 Python zlib.crc32 对照；IDF CRC API 以实际实现验证）。头 20B、payload <=4608B、CRC4B，decoded 最大4632B，COBS worst <=4652B 含 delimiter；921600 8N1 理论约50.5ms，460800约101ms，实际吞吐由 b2 测，不是实测值。每端 UART RX ring 8192B、TX ring 8192B 初设；解码 buffer 最大4632，encoded 最大4652；大于 limit 丢到下一 delimiter，CRC/length/version/type 不符绝不转发。持续 reader task、单独 bounded writer，不在 Wi-Fi/TCP/BT callback/AFE/DAC 线程内等待串口。b2 可根据内存和实测调整 ring，不能降低完整帧能力或取消背压。

### 3.2 私有帧 v1（本批项目设计，非上游 API）

全部 little-endian，无 C struct padding；CRC 覆盖 decoded header+payload，CRC 本身附于尾部，再 COBS 编码并加 0x00。

| offset | bytes | 定义 |
|---:|---:|---|
| 0 | 1 | version=1 |
| 1 | 1 | type（下表） |
| 2 | 2 | payload_len 0..4608 |
| 4 | 8 | session token（S3 每次握手新生成非零 64-bit 随机值；仅隔离旧流，不代表鉴权） |
| 12 | 4 | seq（每 sender 每方向可靠消息从1递增，0 用于非可靠控制；ACK 回显对端 seq） |
| 16 | 4 | control_epoch（S3 当前 7777 client 代次，0=无关 7777） |
| 20 | N | payload |
| 20+N | 4 | CRC32 |

| type | 方向 | payload / 语义 |
|---|---|---|
| 0x01 HELLO | S3→桥 | 空，session 新值、seq/epoch 0；新 token 清旧 UART 会话及未执行请求，不擦 Bond/不主动断已有 SPP |
| 0x02 HELLO_ACK | 桥→S3 | 空，回显 token；仅受理当前握手；不代表 SPP connected |
| 0x03 PING | S3→桥 | 空，seq/epoch 0；每1s |
| 0x04 STATUS | 桥→S3 | 8B：state 0/1/2=disconnected/connecting/connected、peer_valid 0/1、6B MAC（无效为全0）；回应 PING、握手后及真实变化时主动发送；seq/epoch 0 |
| 0x10 CLIENT_OPEN / 0x11 CLIENT_CLOSE | S3→桥 | 空，非零 7777 epoch；按 FIFO 有序设置/关闭 reverse 路由 |
| 0x12 COMMAND | S3→桥 | 原7B 0x69/0x96+MAC，可靠；同前述 epoch |
| 0x13 FRAME | S3→桥 | 一完整原 Tivoo frame 6..4608B，可靠；同前述 epoch |
| 0x14 REVERSE | 桥→S3 | 1..4608B 原始 SPP DATA_IND 字节或既有单字节 hint，可靠；同前述 epoch |
| 0x15 ACK | 双向 | 1B result: 0=accepted（目标队列/epoch 操作已接收），1=rejected（确定未接收/无效 epoch）；回显被确认 seq/epoch，不等同 SPP 完成 |
| 0x16 ERROR | 桥→S3 | 1B code：1=spp_init_failed、2=spp_connect_failed、3=spp_disconnect_failed、4=spp_tx_queue_full、5=spp_write_failed、6=reverse_queue_full、7=spp_not_connected；epoch 按关联请求或0；seq=0；S3 映射原 TVIO ERROR，不向 HA 发私有帧 |

STATUS 必须校验 state、peer_valid、MAC 的组合（connected 必须有有效 peer），无效快照不刷新 heartbeat；STATUS/HELLO/PING/ACK/ERROR 走小型有界优先发送通道，不能卡在等待 SPP data slot 的可靠发送后面；同一 UART writer 保证任何包不交错。状态可合并到最新快照但最终状态不可丢（周期 STATUS 修复）；错误计数/日志有界，禁止密钥、Wi-Fi 凭据、音频、对话。额外 bridge 本地详情走 UART0 日志，S3 只汇总连接/拥塞/错误等；不引入第二个 TVIO 或通用 RPC。未知 type/version、UART 溢出、非法 seq/epoch 按错误隔离；损坏包丢弃并依靠 ACK 超时/heartbeat 恢复，不重新解释为 raw Tivoo。

可靠数据每方向最多一个未确认包（独立双向，不能等本向 ACK 而停止读/响应对向）；接收方严格 expected seq，ACK 仅在数据完整进入有界目标队列或已处理 CLIENT_OPEN/CLOSE 后；没有容量时只保留一个待接收完整包并等待容量，不能先 ACK 或阻塞 UART reader、callback。恢复处理后 ACK；拒绝未接收的数据用 rejected；若收到 rejected，停止当前 7777 并重建 client，不把拒绝当成成功；若状态未知/ACK 超时（初始20s，覆盖现有 SPP 10s 单操作等待，有独立 3s heartbeat 故障检测），立即废弃该 transport 会话和 7777 client，不重发旧命令/帧，HA 按既有连接恢复策略重建；避免非幂等动作执行两次。不做自动重传；重复或不连续可靠 seq 视为会话异常（不重复入队），重握手。seq/epoch 回绕前重建会话。UART 物理层误包不直接中断 S3 音频/7778。

SPP FIFO 延用现有最多32项，逐帧占用 <=4608B（上界147456B payload，不是要求预分配满额），保留队列深度/错误语义，不另建无界队列；改现 queue_request 的阻塞入队等待为桥接 worker 有界等待/可唤醒，UART RX 和 SPP callback 不等待。S3 TCP 只保留一个待发送完整帧及解析 buffer，未 ACK 时暂停读取 7777（TCP receive window 形成背压），不阻塞 7778 listener 或 AFE/TTS；禁止静默截断 GIF。反向两侧各 8192B 有界原始字节队列，按 <=4608B 片段顺序转发；callback 只复制、不得阻塞、不得持有指向 callback 临时 buffer 的指针。反向溢出报告 reverse_queue_full、关闭受影响 7777 会话以防半帧被当成成功，SPP 不因此断开。FIFO 已接收不等于完成，任何 UART ACK 不外露为命令执行确认。

## 4. 复用原 SPP、HA 与恢复边界

实查固定上游 d03n3rfr1tz3/esp32-divoom@e90a77bbade7e92523bfb5b69bc5cb1e4d167520 的 components/divoom/util.h（4608），input_tcp.cpp:177/194/218/248（拆帧/0x69/0x96/raw reverse），output_bluetooth.cpp:25–34（连接提示），hardware_bluetoothctl.cpp:182–185（SPP write）。以本仓已适配的 control_bridge.c、tivoo_frame_stream.c、tivoo_spp.c、tivoo_spp_session.c、bt_security_policy.c 为实际兼容权威（保留 MIT notice）；上游允许可选额外 connect bytes，本仓现行严格7B，不扩大。HA protocol.py MAX_TIVOO_PACKET_SIZE=4608、ANIMATION_CHUNK_SIZE=200；encode_animation 0x49+2B total+1B index、最多256 chunks，故正常 GIF 单个 wire 包至多210B，整体数据至多51200B，不能把整 GIF 当作一个 UART payload。现 transport.py writer.write(join(packets))+drain 可能一次交给 TCP，故须暂停 recv 而不是在32项 SPP FIFO 满时持续发送/丢包。现 SPP session header 330B 写片、15ms 帧间延迟，WRITE_EVT 和 CONG_EVT 等待逻辑已有生产证据；UART 不改变帧顺序/间隔。

- 7777 原 TCP IPv4 raw single client；S3 保留 control_bridge parser、仅完整校验 frame 或 7B connect/disconnect 下发，不在 frame payload 中识别 0x69/0x96。经典板复核原帧边界/checksum 后进入原 SPP worker；无新 Tivoo codec/命令/重编码，不改变 HA service/MCP、原始反向 DATA_IND 和单字节 connecting/disconnected hint。HA 仍是唯一语义命令/显示所有者。
- MAC 唯一权威 HA Config Entry tivoo_bluetooth_mac，0x69+MAC 每新7777会话下发；S3 不自己选地址，经典不扫描/用默认 MAC。经典板复用 tivoo_spp_session、原 target 状态/连接重试、SDP 找 SCN（失败/超时/缺 SCN fallback 1），同 peer 已连幂等，不同 peer 先有序断再连接，旧 peer 队列不得跨地址发送；explicit disconnect 停止针对该 peer 自动重连。连接建立必须走认证+加密、IO_CAP_NONE、原 Legacy PIN 逻辑/拒绝不具备 UI 的 SSP；首次 AUTH_CMPL 真成功与 Bond List，复用 Bond 时 OPEN 成功及前后 Bond List；按 P5-C24/C25 不降低安全、不复制密钥、不自动擦 NVS。SPP callback 非阻塞；原有重连延迟及 timeout 先复用。
- 7778 原 TVIO v1 16B header、方向/sequence、HELLO/ACK、PING/PONG 15s/45s、GET_STATUS request_id、DEVICE_STATUS、DEVICE_EVENT、日志/error、原 audio/资源接口全部独立留在 S3。现 transport.py 校验 DEVICE_STATUS.spp.state 只接受 disconnected/connecting/connected，故不新增 unknown 枚举；桥不可达、尚无新鲜 STATUS 时 S3 对 HA 报 disconnected 且不带 MAC（表示桥服务不可用，不声称物理蓝牙必然已断），原 ERROR/诊断说明 UART 不可达。首次 STATUS 到达或状态变化才发布相应 spp_* 事件；周期快照不重复发状态事件；物理相同但 UART 会话重建通过先失效后恢复产生一次恢复通知，使 HA 既有 ESM-C19 OFF/ON 重申逻辑生效。GET_STATUS 用当前新鲜桥状态与 S3 自身 Wi-Fi/TCP/HTTP 状态；HELLO 能力仅在已实现的目标功能上宣告，b0.4 新语音事件另定。不能仅因 UART/7777/Wi-Fi连通报告 SPP connected。HA transport.py 当前在 7777 建连后可能基于早到的 DEVICE_STATUS 触发同步，且现有状态校验未校对 MAC；b2 必须将 connected 同步限定为当前配置 MAC 与已验证快照/event 的 MAC 一致（以已发送当前 0x69 的 FIFO 顺序保护后续帧），不匹配或未取得 MAC 不触发 connected；同 peer 已连重新握手仍需使现有同步触发一次。状态/错误不能以旧 epoch 的响应关闭新 TCP client。
- 7777 正常断开只清 parser、当前 reverse buffer、未下发帧并发送 CLIENT_CLOSE；已进入 SPP worker/已经写出不能回滚，不主动断 SPP。桥清除该 epoch 未开始的 queued frames（不重放 stale GIF），按原连接管理保留已接受的目标选择/显式 disconnect；下一 TCP client 一定使用新 epoch，先 CLIENT_CLOSE 完成再 CLIENT_OPEN ACK 后接受其命令；若断开时还有未确认发送，直接作废 UART session/重新握手清旧队列，不在失效 epoch 上继续等待或补发；桥丢弃旧 epoch 数据和 pending reverse。SPP 回包本身无 request ID，物理上迟到的数据无法严格归属，不伪造关联/屏幕执行确认；无 client 时丢弃，新的 epoch 仅转本时刻接收的 bytes，不从旧队列搬数据。非幂等命令遇到 uncertain delivery 不自动重放，状态/屏幕由 HA 按既有当前 desired 状态重新计算；不创建第二套表情仲裁。
- 任一板重启、UART RX overflow/持续误码、3s 无有效当前 session heartbeat（S3 依据 STATUS，桥依据 PING；普通 ACK 不替代 heartbeat）、或者不相容版本：失效旧 token，停止接受旧数据、清未开始的数据/旧 reverse，S3 关闭受影响 7777 而 7778 和语音继续运行；经典板不因 UART 断开擦 NVS/强拆健康 SPP。S3 按新 token 重试 HELLO（1s），桥回复并给真实 STATUS；恢复后由 HA 新 TCP 会话发送当前 MAC，不缓存并重播原 control 请求。经典重启时原 target RAM 丢失，在新 MAC 到达后才连接；原 NVS Bond 复用。S3 重启时桥可保留健康 SPP，当前 MAC 相同不重复配对，变化则切换。握手重复同 token 幂等（不可重复重置 epoch）；旧 token 的普通包一律无效。桥可用后才接纳 7777 或对尚未 ready 的连接立即关闭；不因桥未就绪阻止 S3 Wi-Fi/AFE。
- HA Wi-Fi loss/HA 7777 断开走上述 client close，7778 独立；HA 7778 disconnect/heartbeat timeout 不重置 UART/SPP/7777。桥重启/断连不重启 S3、不触发 wake/cancel/音频状态；S3 自身重启或 HA 语音断线的会话取消、表情轮次问题归 b0.4/b0.5，不能从 bridge status 构造音频事件。
- 大 GIF 测试以实际 HA encode 上限、大帧、长连续动画及与双向状态查询、长 TTS/录音同时进行。S3 UART worker/控制 TCP 与 AFE/DAC、7778 任务分离，不等待 SPP 才处理音频；诊断记录 uart CRC/overflow、最大队列、水位、ACK wait、SPP error、I2S underrun、任务时间与内存；b2 验证真实 GIF 及控制不丢截，b3/b4/b10 验证播放过程中上述负载不造成新的欠载/中断或唤醒退化。HA 当前 batch drain 仅运输证据，不能承诺物理显示成功；真机观察亮度/屏幕/倒计时/GIF等另验。

## 5. 分域合同矩阵（P68-HB，未实机验收）

| ID | 合同/验收判据 | 对应旧合同或需求 | 实施 / 证据 |
|---|---|---|---|
| P68-HB01 | 两实际型号、3.3V 接线和避让表；原理图/丝印/通断/电压校验，双 USB 安全独立 | H16/H18、P5-C05/C06 | b1 核对 GPIO/供电/板版，b3/b10 并发电压 |
| P68-HB02 | 双独立 target、IDF v6.1、分开配置/依赖锁，经典不启 Wi-Fi/音频，S3 不启 Classic | P5-C01–C06、H16 | b1 两 build、生成配置/依赖图、启动日志 |
| P68-HB03 | 16MiB flash、正确 Quad/Octal 配置、PSRAM/内部资源证据，S3 model 分区包与 app 同步 | P5-C01–C06/C20、H15/H16 | b1/b4 分区/size/flash args/model list/实机 memory/mmap |
| P68-HB04 | 独立 USB 映射、chip_id/flash_id、两 target 完整/分段包及 hash；经典保留 NVS，不误刷 | P5-C20/C25 | b1 两 USB serial 独立烧录及复位/Bond 复用 |
| P68-HB05 | UART1 pin、baud/8N1、COBS、CRC、长度、类型、seq；最大4608，拆/粘包、任意字节、坏包恢复 | P5-C09/C11、P6-C01、H16 | b2 C host golden/CRC、随机切分/坏 CRC/超限/旧 token；双板误码压测 |
| P68-HB06 | UART 私有 session/epoch、ACK 仅入队、独立双向 stop-and-wait/控制优先；满队列有界背压，不重复非幂等 | P4-C08/C12/C14、P5-C09/C10/C11、P6-C19 | b2 FIFO、32满/慢 SPP、ACK lost/timeout、seq 重复、双向同时满；无重放 |
| P68-HB07 | 7777 raw 7B connect/disconnect 与完整 Tivoo frame 复用，校验/原序/兼容、MAC 唯一 HA 权威 | P5-C07–C11/C22/C23、P6-C01 | b2 现 P5 control host、HA protocol/transport golden、同/异 peer、旧 frame隔离及更换 MAC 时旧状态不触发错误同步 |
| P68-HB08 | 原 Bluedroid SDP/SCN fallback、FIFO/330B/15ms/WRITE_EVT/拥塞、重连及显式断开 | P5-C04/C10/C23/C24、P4-C12/C14 | b2 现 session/security tests、真实 SPP 各路径/拥塞 |
| P68-HB09 | 新配对/已有 Bond 分别认证+加密与 Bond List、NVS 不擦、重启/断电复用 | P5-C24/C25 | b2 首配/已有 Bond、错误认证/PIN逻辑、断电验证（不得为测试擅自擦现生产 Bond） |
| P68-HB10 | reverse 原字节/0x69/0x96、有界非阻塞/epoch 隔离，溢出关闭受影响 TCP（不拆 SPP） | P5-C12、P6-C02–C04/C19 | b2 现 reverse queue host、拆包/粘包/二进制、无 client/溢出/换 client |
| P68-HB11 | S3 TVIO v1兼容、单 client 独立端口/HELLO/heartbeat/日志/error；原音频接口不经 UART | P5-C07/C08/C13–C19/C21、P6-C05–C07/C10/C17 | b1/b2 现 diagnostics/listener host 与 HA transport、错误码/seq/脱敏，b5 新事件另测 |
| P68-HB12 | 真实 SPP 状态/MAC 与 S3本地快照合成；断桥失效、恢复后重新上报，7778 GET_STATUS 回显 request_id | P6-C08/C09、ESM-C19、P4-C08 | b2 fake and real 状态查询，三态/旧状态/桥失效/恢复；b8 真实画面 |
| P68-HB13 | 任一板 reset/断链、HA/Wi-Fi断开恢复，旧 token/epoch/请求隔离，不重复非幂等，不因桥错误阻塞音频或拆健康 SPP | P4-C12、P5-C11/C17/C23/C25、P6-C04/C17、H03/H15 | b2 分板重启、单边断 TX/RX、HA reload/7777/7778 单断、失包及恢复，b10 综合 |
| P68-HB14 | 大 GIF/最大帧和长播放/收音并行，无静默截断/新增音频欠载；测吞吐、队列、水位、资源与实际显示 | P4-C14、P7A-C43、H03/H15、H16 | b2 256 chunks/最大帧/反向流、真实 GIF/MCP；b3/b4/b10 AFE/TTS 并发 |
| P68-HB15 | 保留原 HA/MCP schema、权限、服务、参数/错误/状态边界，HA 唯一语义及显示 owner | P4-C01/C02/C04/C05/C07–C14、ESM-C19/C20 | b2/b8 原测试、实机屏幕/亮度/倒计时、mood/息屏不被桥覆盖；b0.5 事件另定 |

历史索引仍为总路由：跨域 P5-C03/C05、P6-C05–C07/C10、P7A-C43、ESM-C19 等只在本批冻结硬件/transport 部分，音频/会话/显示部分归后续领域；P6-C20 全量回归留 b0.6/b10。P4 安全/MCP 原合同仍保留，非本批改动。没有删除原 PASS/GAP。

## 6. 未实测事项、交接及本批审查

| 待核实 | 方法 / 责任 / gate |
|---|---|
| 新板实际版次、模块标记、双麦外围、DAC VIN、实际 USB 节点及电源峰值 | b1 上电/接线前同图核对，禁止不匹配时盲接；b0.3 确认双麦共享数据/采样，b3/b10 并发电源实测 |
| 921600 信号、最坏队列、断线及实际 GIF 速度 | b1 基本链路，b2 两端短线/负载/误码/最大帧压测，必要时双方改460800并复验；20s ACK/3s heartbeat 是初始工程参数，记录实测再调，不牺牲失败可见性 |
| S3 实际完整构建、model/app 大小、PSRAM mode、internal/DMA 余量 | b1 独立构建/烧录，b0.3 锁模型与音频合同，b4 实际 AFE 模型加载；任何分区超限须先修订表再烧 |
| 已有经典板当前运行版本、真实 Bond 状态 | b1 正常 USB/HELLO/刷写前验证；本批不占用正在生产的串口、不重启或读取 Bond 内容；b2 保留 Bond 验证 |
| 真实跨域性能、TVIO 新事件与表情 | b0.3–b0.5 拥有具体接口；b0.6 交叉审查；b10 实机综合，不以本设计宣称通过 |

证据：本机 IDF v6.1 和安装的锁定 ESP-SR 2.6.1 实际源码、现有库 README/partitions.csv/sdkconfig.defaults/dependencies.lock、control_bridge/tivoo_spp/device_status 与 HA transport/protocol、固定上游四文件、两系列厂商图及 WROVER 模组资料均核对。新 S3 不在已确认在线硬件中；不访问生产 NAS/串口、不重新部署。本批选择 UART1 及 COBS/CRC/stop-and-wait、分区空间、初始 baud/timeout、两个 project 路径是设计裁决，不是厂商规定；理由与成本见 §1–3，b1/b2 失败可按上述 gate 修订，不得把猜测当实测。文档自审：逐项验证路线 b0.2 及旧合同归属，数字/区间/私有字段一致性，b0.3–b0.6 保留边界；独立 reviewer 不可用，b0.6 仍需交叉审查。
