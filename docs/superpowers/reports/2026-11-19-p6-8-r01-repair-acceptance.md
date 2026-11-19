# P6.8 R01 双 target 构建与真实入口修复验收

日期：2026-11-19；分支 feature/p6-8-s3-local-wake；B8 源码基线 0b312dda75b3d3b392e5d953a7cd66e60b2ac44c。依据 [R01 执行计划](../plans/2026-11-19-p6-8-review-repair-execution-plan.md)、[硬件/UART 规格](../specs/2026-11-18-p6-8-b0-2-hardware-uart-spp-design.md) 与 .superpowers/p68-b1/review.md；F01/B1-R01–04、P68-HB02–04/HB11、T01-A。只做开发机软件证据补齐，无生产源码或默认配置变更。

## 审查问题核销

| 源编号 | 当前软件证据 |
|---|---|
| B1-R01 | 非生产 dummy SSID 单独生成的 S3 ELF 同时定义 esp_wifi_init/start/connect、AFE/SR、I2S 与诊断/listener，解决空 SSID 编译分支被优化掉的证据缺口。 |
| B1-R02 | test_active_targets_boot_and_memory 核对固定 target/CMake 入口、两入口 board memory、NVS 失败停止且不擦除、S3 NVS→诊断→双 listener→Wi-Fi、Classic GPIO27 RMT 灭灯；实际 compile_commands.json 与 ELF 符号交叉校验。原 legacy 断言保留。 |
| B1-R03 | 两本批独立构建生成 effective-sdkconfig.txt（白名单键，去除 Wi-Fi SSID/password），并对配置、实际 ELF/map、分区、Flash manifest、归档锁/默认值等计算 SHA-256。没有补造历史 B1 配置或改写历史报告。 |
| B1-R04 | 生成配置断言独立为 test_effective_target_configs_after_configure；默认没有两个生成配置时仅此项明确 skip；TIVOO_P68_CONFIG_ROOT 指向独立配置时文件缺失必 FAIL。生成后实际 19 项全通过，保留并强化 SMP/BR_EDR/SPP 断言。 |

## 测试证据

- 基线：PYTHONDONTWRITEBYTECODE=1 bash scripts/test-ha.sh tests/esp32/test_p5_hardware_memory.py tests/esp32/test_p5b3_bootstrap.py -q -p no:cacheprovider → 17 passed, 5 warnings, exit 0（baseline.log）。
- 新增两项断言首次运行 19 passed, exit 0（source-tests.log）。源代码已经符合合同；依据计划按补证处理，不虚构 RED、不修改 Wi-Fi/NVS/RGB/AFE 生产逻辑。
- 无生成配置的干净源码副本：git archive HEAD esp32 tests/esp32 | tar -x 到本批 ignored clean-source，再覆盖本批两个测试文件；PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 原 .venv/bin/python -m pytest 两文件 -q -p no:cacheprovider → 18 passed, 1 skipped, 2 warnings, exit 0（clean-source-tests.log）。仅配置后测试跳过。显式 TIVOO_P68_CONFIG_ROOT=无实际配置的 clean-source 时单独运行 test_effective_target_configs_after_configure → FileNotFoundError, 1 failed, exit 1（missing-explicit-config.log，预期负控，不是产品故障）。
- 独立配置最终专项：TIVOO_P68_CONFIG_ROOT="$PWD/.superpowers/p68-r01" PYTHONDONTWRITEBYTECODE=1 bash scripts/test-ha.sh tests/esp32/test_p5_hardware_memory.py tests/esp32/test_p5b3_bootstrap.py -q -p no:cacheprovider → 19 passed, 5 warnings, exit 0（configured-tests.log；warnings 为既有测试依赖弃用）。不主张全量回归，R11 仍需按计划跑全量。

## 可复现构建（repo root）

使用已有 ESP-IDF v6.1 EIM 激活脚本；普通 export.sh 初次尝试找不到其默认 Python 3.14 virtualenv（idf.py 127），改用项目规格已经确认的 activate_idf_v6.1.sh，未安装/改变工具链。以下在全新生成目录运行；若已有 sdkconfig 则其值优先，不用旧生产 sdkconfig，也不要覆盖历史归档。没有 set-target 临时切换，因为两个 CMake 都固定 target。

```bash
p="$PWD/.superpowers/p68-r01"
mkdir -p "$p/esp32s3" "$p/esp32"
printf '%s\n' 'CONFIG_TIVOO_WIFI_SSID="TIVOO_R01_DUMMY_ONLY"' 'CONFIG_TIVOO_WIFI_PASSWORD=""' > "$p/esp32s3/dummy.defaults"
source ~/.espressif/tools/activate_idf_v6.1.sh
cd esp32/firmware
CMAKE_BUILD_PARALLEL_LEVEL=1 idf.py -B "$p/esp32s3/build" -D "SDKCONFIG=$p/esp32s3/sdkconfig" -D "SDKCONFIG_DEFAULTS=$PWD/sdkconfig.defaults;$p/esp32s3/dummy.defaults" reconfigure
nice -n 5 ninja -C "$p/esp32s3/build" -j1
idf.py -B "$p/esp32s3/build" size
cd ../bridge_firmware
CMAKE_BUILD_PARALLEL_LEVEL=1 idf.py -B "$p/esp32/build" -D "SDKCONFIG=$p/esp32/sdkconfig" -D "SDKCONFIG_DEFAULTS=$PWD/sdkconfig.defaults" reconfigure
nice -n 5 ninja -C "$p/esp32/build" -j1
idf.py -B "$p/esp32/build" size
cd ../..
```

S3 使用独立的非生产测试 SSID，密码为空，原默认空凭据机制不变；两独立构建串行，ninja -j1，期间 MemAvailable 抽样约 4.5–5.2 GiB，无 OOM。有效配置 TEST_GATE/PROMPT_CALIBRATED 均未启用。原工作区 sdkconfig/build 与历史 B1/legacy 归档未覆盖。

## 构建、有效配置与真实产物证据

两 configure、ninja、idf.py size、size-components 均 exit 0；verify-builds.py 双目标校验 exit 0。工具链 IDF v6.1，提交 fff9895c82d744c7237be8847347bdd1b07c6643，esptool v5.6.0；依赖锁保持原版本，S3 ESP-SR 2.6.1 / codec 2.6.2 / effects 1.4.5。CMake 有组件 include path 提示，未造成配置/构建失败。未更新工具链。

| 项目 | ESP32-S3 | Classic ESP32 |
|---|---|---|
| APP（字节） | 2,503,360 | 718,608 |
| 8MiB app 剩余（字节） | 5,885,248（约70%） | 7,670,000（约91%） |
| 静态内部内存 | DIRAM 232,299/341,760；109,461 剩余；独立 IRAM 16,384/16,384 | IRAM 104,591/131,072；DRAM 46,483/124,580 |
| external RAM BSS | 31,180 B | 以实际 size/map 为准 |
| flash / PSRAM 配置 | 16MiB DIO 80MHz / Octal 80MHz，Wi-Fi/LwIP 优先 PSRAM | 16MiB DIO 40MHz / Quad 40MHz，BT 优先 PSRAM，BANKSWITCH_RESERVE=8 |
| CPU / BT | 240MHz 双核；Classic 未启用 | 240MHz 双核；BT SMP、BR/EDR only、SPP 均启用 |

S3 model 579,214 B；实际打包报告仅 vadnet1_medium、wn9_hilexin，后者仍为 smoke 词；model SHA 与 B1 原包一致。静态链接内存不等于实际运行 free heap/PSRAM、AFE DMA 负载或 RF 性能。

实际 compile_commands.json 验证两 active app_main、board_boot 源文件已编译，旧 main/hardware_memory 不在两 active 源图中。S3 ELF 有 esp_wifi_init/start/connect、tivoo_wifi_station_start、esp_srmodel_init、afe_config_init、tivoo_s3_afe_start、i2s_new_channel、esp_http_client_init、diagnostics/listeners、nvs_flash_init、board memory；无 esp_bt_controller_init、esp_spp_enhanced_init、tivoo_spp_start。Classic ELF 有 app_main、nvs_flash_init、esp_bt_controller_init、esp_spp_enhanced_init、tivoo_spp_start、tivoo_board_rgb_off、board memory；无上述 S3 Wi-Fi、SR/AFE、I2S、HTTP 音频入口。Classic IDF 传递组件含 esp_wifi 并不意味着 Wi-Fi runtime 链接；实证以 ELF defined symbol 为准。

分别用 IDF gen_esp32part.py 解码实际表并对照源码分区；两 flash_args/flasher_args.json 与 target/offset 一致、分区无重叠/越界，分段不覆盖 NVS 0x9000–0xefff。使用实际 @flash_args 调用 esptool merge-bin -f raw -t 0x0 --pad-to-size 16MB，逐段逐字节比对通过，完整镜像两者都是 16,777,216 B、NVS 区全 FF。**这些是软件验证产物，禁止刷写；尤其完整镜像不能用于保留 Bond。**

| 目标 | 偏移 / 文件 | 字节 | SHA-256 |
|---|---|---:|---|
| esp32s3 | 0x0 / build/bootloader/bootloader.bin | 21,120 | `e0bd66ab1cdb4f3593913a2475b50f661c01718d770b8920d2bab20369d64cb7` |
| esp32s3 | 0x8000 / build/partition_table/partition-table.bin | 3,072 | `3474e872c7915f718ccbbd3319c9164ac4d55b6be8570796d151796c7facbeb0` |
| esp32s3 | 0x10000 / build/tivoo_firmware.bin | 2,503,360 | `47e8fe55aab97cb3448edf7b52c1b185dcd74b0d6f5e726989b7603ae8768f3b` |
| esp32s3 | 0x810000 / build/srmodels/srmodels.bin | 579,214 | `f1a1a39defc1d1c52d112b45629fb221adad4dfda85785ed9f527cb53a145e19` |
| esp32s3 | 0x0 / full-16MB.bin | 16,777,216 | `fa8ff45e4016f00e4340cf36bf71567b256ff102508863f4309de21106b375fc` |
| esp32 | 0x1000 / build/bootloader/bootloader.bin | 26,176 | `965e472f0c30af090dfc66fb4fcb4bfb136b2542bf5180c2d374f850b12d178e` |
| esp32 | 0x8000 / build/partition_table/partition-table.bin | 3,072 | `fc0cac519e0c7119f7ed0fa70326b9516f35a4c98ca3cd1ad50262b415f6dc90` |
| esp32 | 0x10000 / build/tivoo_bridge_firmware.bin | 718,608 | `6bc754d37c69c36edf97799288ceb569deede21ef1c16ae3342b19c3aa384189` |
| esp32 | 0x0 / full-16MB.bin | 16,777,216 | `ccfdd1eae633602ce19e624518e2a60da273572e5c1eb01f9246179035c6593c` |

所有实际证据存于 `.superpowers/p68-r01/{esp32s3,esp32}/`：build/ 内两 ELF、实际 map/compile_commands/flash_args/分段包，目录内 effective-sdkconfig.txt、dependencies.lock、sdkconfig.defaults、manifest.json、full-16MB.bin、size.txt、size-components.txt、defined-symbols.txt、partition-table-decoded.csv 与日志；脚本 verify-builds.py 位于本批根目录，重新验证实际产物并生成 manifest。执行 `nice -n 5 ninja -C "$p/$target/build" -j1 size-components`（两目标串行），再从仓库根目录 `python "$p/verify-builds.py" "$p"`（激活 IDF 环境）复验；verify.log 保留实际断言输出。manifest 内每个哈希已重新计算一致。

## 结论与剩余门禁

- F01 / B1-R01–04：本批软件证据缺口已核销，T01-A 当前软件 PASS（不是重新补造历史 B1 结果）。P68-HB02/03/04/HB11 仅本批所涉及的构建与启动结构部分通过；T01-B 未核销。R02/R03 可使用两独立 target 当前构建证据，R11 仍将独立 clean build 与全量回归。
- HB01/02/03/04/HB11 物理 GAP：S3/第二颗 INMP441 未到位；实际 AP 关联、HELLO、双板 USB/chip_id/flash_id、RGB GPIO38/27、真实 memory/PSRAM/himem/峰值、实际 NVS/Bond 保全与旧固件回退、供电和接线仍待授权后验证。无实机/NAS/部署/刷写/擦除；不启用未标定 gate。
- 自审（无独立子代理）：按 requesting-code-review 模板复核两测试文件 diff、实际构建图、符号、分区及哈希、配置隔离，无 R01 内 Critical/Important 遗留。R02–R11、B9/B10、其他 F 项不执行、不核销；真实硬件而非静态行为另验。工作区初始已有原 B1–B10 计划添加 R 批入口的未提交修改，保持原样、不纳入 R01 提交；新增 R 批计划原先未跟踪，纳入本次勾选及引用。无 push/merge。
