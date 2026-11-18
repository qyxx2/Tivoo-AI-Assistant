# P6.8 b1 独立固件构建验收报告（软件通过，实机待验）

日期：2026-11-18。实现提交：`9b42658a32357371441c93b743c721bdbe67ff17`。
范围：仅 b1；依据 b0.2/b0.3 冻结合同及 b1–b10 执行计划。
开发机：ARM64 Ubuntu，ESP-IDF v6.1（`fff9895c82d744c7237be8847347bdd1b07c6643`），Xtensa GCC 15.2.0，esptool 5.6.0。
软件构建和离线验证通过；没有新 S3/第二颗 INMP441 实物，T01-B 不执行、不宣称通过。用户禁止刷写现生产经典板；本次未连接 NAS、未刷写任何设备、未部署、未启动 b2。

## T01-A 软件证据

- `esp32/firmware` 固定 esp32s3，独立 sdkconfig/锁/分区，16 MiB DIO 80 MHz flash，8 MiB Octal PSRAM 80 MHz 配置，GPIO4/5/6/7 为新 I2S 默认值。Wi-Fi/7777/7778 为 scaffold，未实现的 SPP/audio/mic capability 不发布。GPIO38 RGB 需实际板版确认后启用。
- `esp32/bridge_firmware` 固定 esp32，独立 sdkconfig/锁/分区，16 MiB DIO 40 MHz flash、Quad PSRAM 40 MHz 配置，原 NVS/PHY/factory/storage 布局保留；原 SPP 安全/会话/传输代码复用；GPIO27 灭灯逻辑，NVS 初始化失败停止，不执行 erase。桥侧仅本地 UART0 日志；UART1 转发属于 b2。
- IDF BT 传递依赖 esp_wifi，并非项目启动 Wi-Fi。实际 ELF 已定义符号检查：经典板含 esp_bt_controller_init、esp_spp_enhanced_init、tivoo_spp_start，不含 esp_wifi_start、esp_wifi_connect、tivoo_wifi_station_start、esp_srmodel_init、afe_config_init、i2s_new_channel、esp_http_client_init。S3 含 tivoo_wifi_station_start、esp_srmodel_init、afe_config_init，不含上述 Classic SPP 启动符号。
- S3 锁 ESP-SR 2.6.1、codec 2.6.2、effects 1.4.5；编译探针与冻结 MMNR/FD HIGH_PERF/BSS/VADNet1/WakeNet 一致，默认 volatile false 不执行。模型包从实际二进制解析出且仅含 wn9_hilexin（嗨，乐鑫，仅 smoke，非最终选择）和 vadnet1_medium；验证文件范围连续、无越界，并保留每个文件的哈希与元数据。AFE 运行初始化、实测通道/声学属于 b4。
- 两生成分区表经 IDF 解码，逐项与合同匹配；所有分区及生成 flash segment 无重叠、无越界。S3 factory 8 MiB、model 4 MiB；经典 NVS 0x9000/0x6000 不迁移；经典分段包不覆盖 NVS。完整镜像包含全 FF 的 NVS 区间，**绝对不能作为保留原 Bond 的升级方式**。

## 测试和构建

1. 新增 T01-A 四项用例先 RED（4 failed），软件实现后 GREEN（5 passed，含既有内存用例）。补充冻结 AFE 编译探针用例先 RED（1 failed、5 passed），修正后 GREEN。
2. `bash scripts/test-ha.sh tests/esp32/test_p5_hardware_memory.py tests/esp32/test_p5b3_bootstrap.py -q`：17 passed，exit 0。T01-A 节点为 test_p68_s3_partition_layout、test_p68_bridge_preserves_legacy_nvs_and_partition_layout、test_p68_independent_target_defaults_and_model_selection、test_p68_independent_project_source_graph、test_p68_s3_compile_probe_matches_frozen_afe_graph；原内存及 Classic 安全、Bond 和启动断言保留。
3. `bash scripts/test-ha.sh tests/esp32 tests/homeassistant -q`：552 passed、1 failed、1 error，exit 1。唯一失败和 teardown error 同源：既有 test_controlled_http_fixture_covers_stream_and_failure_responses 的本地 socket 创建被 HA 全局禁网 fixture 拦截；不是产品逻辑失败。未更改此用例或降低 HA 测试禁网保护。单独以 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -p pytest_socket --allow-hosts=127.0.0.1 tests/esp32/test_p6_audio_resource.py::test_controlled_http_fixture_covers_stream_and_failure_responses -q`：1 passed，exit 0。两次运行覆盖 553 个通过的独立测试，不能将原合并命令报告为 exit 0。未修改 Sherpa，未运行其独立环境。
4. 前次无上限并行构建中断（用户确认宿主机卡死），恢复后使用 `CMAKE_BUILD_PARALLEL_LEVEL=2`，两工程串行、`nice -n 5 ninja -C build -j2`，保持 IDF 实际生成的 Ninja 构建图，避免 idf.py 默认不限制并发。两个完整构建及提交后重新配置/增量构建均 exit 0。S3 最终修正后重编译通过。过程中所观察到的 MemAvailable 约 3.1–3.8 GiB，未再次卡死；这是抽样，不是峰值计量。
5. 从实现提交重新生成 `idf.py reconfigure`、限并发 Ninja、`idf.py size`、`idf.py size-components`、`idf.py merge-bin --format raw --flash-offset 0x0 --pad-to-size 16MB`，全部成功。实际生成 flash_args/flasher_args.json、依赖锁、map、size/size-components、model、分段包及完整包归档。完整镜像逐段字节比对一致。未执行 flash。
6. 自审项目入口、合同和构建产物；未进行独立子代理审查或实机验证。

## 构建产物（字节）

| 目标 | APP 文件大小 | 8 MiB app 剩余 | 静态内部内存（IDF size） |
|---|---:|---:|---|
| ESP32-S3 | 1,633,200 | 6,755,408 | DIRAM 136,307/341,760；IRAM 16,384/16,384（独立保留区，不等于运行 heap 已满）；external RAM BSS 18,232 |
| ESP32 Classic | 694,288 | 7,694,320 | IRAM 103,619/131,072；DRAM 46,451/124,580 |

S3 model 579,214 B，4 MiB 区间剩余 3,615,090 B。静态链接占用不代表实际运行 heap、PSRAM free 或双麦实时吞吐。

| 目标 | 偏移 | 文件 | bytes | SHA-256 |
|---|---|---|---:|---|
| esp32s3 | 0x0 | `bootloader/bootloader.bin` | 21120 | `c770d63809a27e4a0459fa0fe7b178e136e9474ef481dc9f32e9543bb0709092` |
| esp32s3 | 0x8000 | `partition_table/partition-table.bin` | 3072 | `3474e872c7915f718ccbbd3319c9164ac4d55b6be8570796d151796c7facbeb0` |
| esp32s3 | 0x10000 | `tivoo_firmware.bin` | 1633200 | `4d94f90e774425cd06643ba3b8dd381515290320ada23d41ae7979dda139eb30` |
| esp32s3 | 0x810000 | `srmodels/srmodels.bin` | 579214 | `f1a1a39defc1d1c52d112b45629fb221adad4dfda85785ed9f527cb53a145e19` |
| esp32s3 | 0x0 | `full-16MB.bin` | 16777216 | `587d2b656a4ab4740d80efaf9fb2a901491af06ad05177db41713d62063146a2` |
| esp32 | 0x1000 | `bootloader/bootloader.bin` | 26176 | `0a454f64280290aef640d7dda827b5f1c537c1f6d43876f9a21be9d64cd4cb36` |
| esp32 | 0x8000 | `partition_table/partition-table.bin` | 3072 | `fc0cac519e0c7119f7ed0fa70326b9516f35a4c98ca3cd1ad50262b415f6dc90` |
| esp32 | 0x10000 | `tivoo_bridge_firmware.bin` | 694288 | `50f63f0f8be6a555ab84ed71d36d5d7fe928fea0c817419300b906c910820476` |
| esp32 | 0x0 | `full-16MB.bin` | 16777216 | `067059e551d0fe5f29d8084da14bf5a29794292a3900f8c519bbaaf2bc50c3bc` |

归档位置（开发机工作区本地、Git 忽略）：`.superpowers/p68-b1/artifacts/{esp32s3,esp32}/`，各自 `manifest.json` 记录源提交、完整/分段镜像、分区和全部文件 SHA-256；`toolchain.txt` 记录工具版本。旧生产构建目录与本地 sdkconfig 保存在 `.superpowers/p68-b1/legacy/`，不提交凭据或二进制到 Git。日志在 `.superpowers/p68-b1/` 及对应归档目录。

## 未核销硬件门禁

| 合同 | 本批结果 | 必须补验 |
|---|---|---|
| P68-HB01 | GAP | 实物丝印/PCB 版本、接线与通断、供电电压、双 USB 独立枚举及安全 |
| P68-HB02 | 软件 PASS / 实机 GAP | 两板独立启动、运行角色及日志 |
| P68-HB03 | 软件 PASS / 实机 GAP | flash_id、实际 flash/PSRAM/heap、模型 mmap；b4/b10 运行资源 |
| P68-HB04 | 软件产物 PASS / 实机 GAP | 两物理 USB 对应、独立刷写与复位、经典 NVS/Bond 保全、旧生产回退 |
| AFE-C06/C08 | b1 smoke PASS / 实机 GAP | S3 实际加载模型，b4 最终词选定、模型初始化及正负样本 |

S3 到货后才按 b0.2 核实双 USB、丝印、GPIO38 RGB 和电源，再在明确授权的维护窗口分别刷写并记录启动/ID/heap/Bond。当前经典固件保持生产运行。不核销 T01-B；不进入 b2 真机，不提前实现 b2。
