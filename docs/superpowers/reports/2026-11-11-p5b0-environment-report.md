# P5b0 ESP-IDF 环境与组合兼容性验收报告

> 日期：2026-11-11
> 分支：`feature/p5-esp32-minimal-firmware`
> 批次：P5b0（只执行合同矩阵中已定义的 B0）
> 基线：`4e519c883316416bd68b033a5bc3507a260f2357`
> 结果：**PASS — ESP-IDF v6.1 / ESP32 组件组合 smoke build 与链接通过**

## 1. 范围

本报告只记录 `docs/superpowers/specs/2026-11-11-p5-esp32-minimal-firmware-contract-matrix.md` §3 和 §10 中 P5b0 的实际执行证据。该合同矩阵仍是 P5b0–P5b4 唯一权威批次定义；本报告及配套执行计划没有另行定义或调整批次边界。

本批建立可复现的 ARM64 EIM / ESP-IDF v6.1 / `esp32` 环境，固定音频组件依赖，并在同一 smoke project 中编译、链接 Classic SPP、Wi-Fi/socket、I²S、ESP-SR AFE、Simple Decoder 和 SRC API。

**明确未做：** 未创建 P5b1 生产固件骨架或业务逻辑；未实现 TCP 服务、HA Adapter 或 SPP 转发；未启动音频实时任务/模型；未连接或刷写开发板；未做 Wi-Fi、Tivoo 配对、Flash/PSRAM 实际容量及 heap 实机测试；未开始 P5b2–P5b4。

## 2. 开发主机与工具链

| 项目 | 实际结果 |
|---|---|
| 主机系统 | Ubuntu 26.04.1 LTS，Linux AArch64（`aarch64`） |
| EIM | Espressif Installation Manager CLI 0.19.0 |
| ESP-IDF | v6.1；`idf.py --version` 输出 `ESP-IDF v6.1` |
| ESP-IDF Git revision | `fff9895c82d744c7237be8847347bdd1b07c6643` |
| Xtensa toolchain | `xtensa-esp-elf esp-15.2.0_20251204`；GCC 15.2.0 |
| Python | EIM 独立 venv，Python 3.14.4，pip 25.1.1 |
| CMake / Ninja | EIM 安装的 CMake 4.0.3、Ninja 1.12.1 |
| 安装位置 | `/home/Gold/.espressif/v6.1/esp-idf` |
| 工具目录 | `/home/Gold/.espressif/tools` |
| Python venv | `/home/Gold/.espressif/tools/python/v6.1/venv` |
| 构建 target | `esp32` |

安装命令使用 EIM 显式指定版本和 target：

```bash
eim --do-not-track true install \
  --path /home/Gold/.espressif \
  --target esp32 \
  --idf-versions v6.1 \
  --cleanup true
```

主机缺少的 `flex`、`bison`、`gperf`、`ccache`、`dfu-util` 和必要运行库以 Ubuntu ARM64 软件包解包到用户目录 `~/.local/p5b0-host-tools`，供 EIM 前置检查使用；未通过 apt/dpkg 修改系统包状态，也未安装系统级开发环境。

EIM 安装时尝试复制 OpenOCD udev 规则到 `/etc/udev/rules.d`，因当前用户没有系统目录写权限而未完成该可选步骤。该设备规则不影响源码构建与链接；本批不需要串口烧录，因此没有提升权限或修改系统规则。

## 3. 组件版本锁

项目 manifest 精确声明：

- `espressif/esp-sr` **2.6.1**
- `espressif/esp_audio_codec` **2.6.2**
- `espressif/esp_audio_effects` **1.4.5**

ESP Component Manager 解析并写入 `esp32/tests/p5b0_compatibility/dependencies.lock`，实际锁定的完整依赖版本如下：

| 组件 | 锁定版本 |
|---|---:|
| `espressif/cjson` | 1.7.19~2 |
| `espressif/dl_fft` | 0.8.0 |
| `espressif/esp-dl` | 3.3.15 |
| `espressif/esp-dsp` | 1.8.0 |
| `espressif/esp-sr` | 2.6.1 |
| `espressif/esp_audio_codec` | 2.6.2 |
| `espressif/esp_audio_effects` | 1.4.5 |
| `espressif/esp_new_jpeg` | 1.0.2 |
| `espressif/gmf_fft` | 1.1.0 |
| `idf` | 6.1.0 |

其中 IDF / 三项指定音频组件版本均与合同一致，传递依赖也已锁定。未将 EIM 本地同步的其他组件注册表条目误当作项目依赖。

## 4. 组合 API smoke build

测试工程路径：`esp32/tests/p5b0_compatibility`。这是独立 compile/link compatibility probe，不是生产固件。

`main/p5b0_smoke.c` 的探测调用由外部可写的 `volatile bool p5b0_enable_api_probe` 控制，默认值为 `false`。该设计使编译器/链接器保留 API 调用，同时默认不会启动蓝牙、Wi-Fi、socket、I²S、AFE 或解码器。接口字段、类型和调用签名在构建期参与编译；不执行运行时动作。

已编译并链接的 API 家族：

- **Classic Bluetooth / Bluedroid / SPP：** Controller 状态/init/enable、Bluedroid 状态/init/enable、GAP callback、SPP callback/enhanced init、scan mode、device name、Class of Device、PIN、SDP discovery、connect/write/disconnect。
- **Wi-Fi STA / netif / NVS：** `nvs_flash_init`、netif 初始化、default STA netif、event loop、Wi-Fi init/mode/config/start/connect。
- **lwIP BSD sockets：** `socket`、`setsockopt(SO_REUSEADDR)`、`bind`、`listen`、`accept`、`recv`、`send`、`shutdown`、`close`。
- **I²S Standard full duplex：** 对同一 `I2S_NUM_0` 同时申请 TX/RX channel，编译 std-mode 初始化、enable、read/write；使用 `I2S_GPIO_UNUSED`，没有确定或占用实际硬件引脚。
- **ESP-SR AFE：** 使用零初始化 `srmodel_list_t`，MR 输入、AEC SR high-performance、内置 WebRTC VAD 配置，编译 AFE config/handle/create/feed/fetch/get-feed-chunk-size 接口。
- **Simple Decoder：** 默认 Decoder 注册、Simple Decoder 注册、WAV/MP3 类型检查，以及 decoder open/process/get-info/reset/close 接口。
- **Audio Effects SRC：** 22,050 Hz → 32,000 Hz、Mono、S16LE、complexity 3；同时编译 MEMORY/SPEED 两种 perf enum，并引用 open/get-max-output/process/close。

通过 `xtensa-esp-elf-nm -u` 检查 smoke object，以上外部 API 调用均保留为待链接符号；最终 `p5b0_compatibility.elf` 成功链接，未发生未解析符号错误。AFE interface 的 feed/fetch/get-feed-chunk-size 是通过组件接口表调用，已参与 C 编译；本批不加载模型或调用这些函数执行实时处理。

## 5. sdkconfig 与分区表验证

最终从空白 `sdkconfig` 重新执行 `idf.py reconfigure`，未在 defaults 手动设置派生的 `CONFIG_BT_SMP_ENABLE`。Kconfig 自动生成的结果仍为 `CONFIG_BT_SMP_ENABLE=y`。

生成配置已确认：

| 配置 | 生成值 |
|---|---|
| `CONFIG_IDF_TARGET` | `esp32` |
| `CONFIG_ESPTOOLPY_FLASHSIZE_16MB` | `y` |
| `CONFIG_SPIRAM` | `y` |
| `CONFIG_SPIRAM_TYPE_ESPPSRAM64` | `y` |
| `CONFIG_SPIRAM_MODE_QUAD` | `y` |
| `CONFIG_SPIRAM_SPEED_40M` | `y` |
| `CONFIG_SPIRAM_BOOT_INIT` | `y` |
| `CONFIG_SPIRAM_USE_MALLOC` | `y` |
| `CONFIG_SPIRAM_BANKSWITCH_ENABLE` | `y` |
| `CONFIG_BT_ENABLED` | `y` |
| `CONFIG_BT_BLUEDROID_ENABLED` | `y` |
| `CONFIG_BT_CONTROLLER_ENABLED` | `y` |
| `CONFIG_BT_CLASSIC_ENABLED` | `y` |
| `CONFIG_BT_SPP_ENABLED` | `y` |
| `CONFIG_BT_SMP_ENABLE` | `y`（由 Kconfig 推导） |

IDF `gen_esp32part.py` 对构建生成的二进制分区表执行了解析与验证，结果：

| 分区 | Offset | Size |
|---|---:|---:|
| nvs | `0x9000` | 24 KiB |
| phy_init | `0xf000` | 4 KiB |
| factory | `0x10000` | 8 MiB |
| storage | `0x810000` | 8128 KiB |

分区边界覆盖 16 MiB Flash，无重叠或越界；没有创建 ESP-SR `model` 分区。WROVER-E 的 8 MiB PSRAM 这里只确认了生成配置，不代表真实芯片容量、heap 或 bank-switching 已通过硬件初始化验收。

## 6. 构建结果

完整首次组合构建命令：

```bash
source /home/Gold/.espressif/tools/activate_idf_v6.1.sh
cd esp32/tests/p5b0_compatibility
export IDF_TARGET=esp32 CMAKE_BUILD_PARALLEL_LEVEL=2
idf.py build
```

首次完整构建完成 **1627/1627** 个 Ninja 步骤，bootloader、主 ELF 链接、ESP32 image 生成、分区尺寸检查均成功，退出码 **0**。其后将 probe guard 改为外部可写 volatile，并从 defaults 移除派生 Kconfig 项，重新生成配置；最终源码和最终配置的增量 build 再次成功，退出码 **0**。

最终产物（本地构建目录，已由项目 `.gitignore` 忽略，不提交）：

| 文件 | 大小 |
|---|---:|
| `build/p5b0_compatibility.elf` | 约 15 MiB |
| `build/p5b0_compatibility.bin` | 2,234,880 bytes（`0x221a00`） |
| `build/bootloader/bootloader.bin` | 约 26 KiB |
| `build/partition_table/partition-table.bin` | 3.0 KiB |

主应用 binary 使用最小 app 分区 8 MiB，IDF 检查报告剩余 `0x5de600` bytes（约 73%）。这些是 B0 测试工程构建产物，不是 P5b4 的最终 merge-bin 交付物。

## 7. 非阻断提示与验收边界

构建过程中有 ESP-IDF v6.1 自身的 Kconfig 布尔默认值/十六进制字面量弃用提示，以及 esp_wifi / wpa_supplicant 私有 include 路径一致性 warning；它们未导致配置失败、编译失败或链接失败。本报告未修改 IDF 上游源码来消除这些警告。

**P5b0 退出条件通过：** ARM64 工具链与 venv 建立、target 固定、三项组件精确锁定、SPP/I²S/Wi-Fi/socket/AFE/Decoder/SRC 的组合编译链接、16MB Flash / 8MB PSRAM 配置及 model-free 分区表验证全部完成。

本批不刷写开发板，因此不能据此宣称真实 16MB Flash/8MB PSRAM 识别、Classic SPP 配对、Wi-Fi 连接、音频性能或任何 Tivoo 屏幕行为通过。
