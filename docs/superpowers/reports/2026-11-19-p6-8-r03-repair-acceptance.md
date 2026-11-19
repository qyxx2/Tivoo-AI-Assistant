# P6.8 R03 DMA 时轴、旧 PCM、可信 drain 与恢复修复验收

日期：2026-11-19；feature/p6-8-s3-local-wake；基线 3b5893cbca4707644293c62cd72a08944a5e56d6（R02）。依据 [执行计划](../plans/2026-11-19-p6-8-review-repair-execution-plan.md) R03、B3/B6 原审查；仅 F05 / B3-R01/R02/R04(12槽)、B6-R01/R02；AFE-C04/05/12、VOICE-C07/09、T03-B/T06-B 对应软件子项。不核销 F06/F07/F13/F14 或整套物理门禁。

## R03.1 驱动与 owner 顺序

查开发机锁定 ESP-IDF v6.1 实际源码 esp_driver_i2s/i2s_common.c：244–330 start/stop 重置 FIFO/GDMA、从首描述符开始/停止；710–735 新描述符 DMA buffer calloc、循环链接；829–864 TX sent 回调先给出完成槽再 auto-clear（保留已有关闭 auto-clear 的真实参考/回填路径）；1510–1543 disable 仅 task 上下文，停止通道并恢复 READY；1314、1370–1415 delete 非运行通道及释放描述符；esp_driver_dma/src/gdma.c 907–970 删除 GDMA 通道关闭、清除待处理中断。两通道同 I2S、32k、12×160 samples；正常 STOP 只停止播放 owner，不停 RX。不能凭漏报槽的地址写槽：它可能再次被 DMA 使用。仅回填实际 EOF 槽。初始学习看见重复指针而未学满、运行时跳槽/错序、错误长度、RX 100ms 超时可检测；不可观测的整圈/首次 EOF 之前遗漏不声称能识别。

恢复选择同一驱动分配核上的短生命周期 task（不在 ISR 操作 driver；实际主核 affinity CPU0）。先置 fault，使当前播放 generation 永久不能成功 drain、拒绝新 owner，并丢弃未送 PCM/旧参考；禁用旧 callback 消费，停 RX/TX 两边，留一个 tick 给已 pending 的同核 ISR 退出后删除双通道，驱动释放 IRQ 和旧 ring；重建共享时轴，以 max(RX next block, TX completed)+1 为共同 base；两边重新学习描述符、清 reference/decimator/RX queue，先 RX 后 TX 启动。新 ring 是 fresh calloc，绝不手动写未完成 DMA 槽。跳变显式 gap/invalid，不补造连续样本。既有 26 block settle 后须得到有效非 gap 的同轴 frame 才重新 available；额外最多一 ring（12 block）仍不能形成有效帧或再次故障则停止并标记 unavailable，不无限重试；创建/停启失败记录错误且隔离。真实 IRQ/物理槽时序必须实机复验。

锁与父子顺序：output spinlock 统一 fault/generation/ref/clock/可信 release；ISR 不持资源 mutex、不执行分配/重建。父 audio_resource 可通过 output lock 检查/正常 release 或失败 discard；仅清逻辑 owner 不会解除故障期间的硬件隔离。local turn 维护 fault serial、在调用 resource 前释放 shared turn lock；RX bind/followup 取当前 fault serial 后检查 shared 授权，不在 turn lock 内再拿 output lock。普通 TTS 与短提示使用同一恢复入口，不另加 owner 系统。

## R03.2–4 修复核销

| 来源 | 修复 / 实际证据 |
|---|---|
| B3-R01 / F05 | startup 学序单漏不再使整个 boot 永久失配；检测错误→capture 返回非 OK/显式 gap，双向重建，恢复后同轴有效帧。 |
| B3-R02/R04(12槽) / F05 | 模拟实 12 槽中 nonzero PCM，实际 TX callback 跳槽即使 drain clock 数值足够也不可信；当前 gen failed、reference invalid，只有完成槽可清零，旧 ring 删除后才使用新零槽，不让旧 PCM 混入新 gen。 |
| B6-R01/R02 / F05 | 提示 5s watchdog 无法证明 drain 就 abort 当前 turn、请求同一 DMA recovery；prompt_discard 非 completed，保持 mask 直至有效新 epoch，按新 clock boundary+tail+offset 解除屏蔽，不发送 canceled turn completed gate。恢复前不得新 owner；故障不可恢复则明确 unavailable。 |
| 共用 release / F05 | output_release_drained 在同一锁验证并释放。普通资源 350ms drain timeout 同一 fault recovery/失败 owner discard；普通长流中无数据并非 EOF，正常 stop/drain/下一 owner 不重建 RX。取消的 ordinary worker 保持 canceled/stopped 语义，故障不能是 completed。完整真实 worker terminal/enqueue 时序补证归 R08。 |
| 自审补证 | 恢复后在 fetch 尚未 tick 的窗口，旧 session 授权按 fault serial 立即失效；新轮不接收旧 playback/followup。初次重建但尚无有效 frame 不允许抢占 owner；重复 fault 或 stalled TX 按有界失败路径停机。 |

## RED / GREEN（不替换原证据）

开发机 .superpowers/p68-r03/ 保存全部日志。ESP 测试使用现有 .venv/bin/python 原生 pytest；第一次尝试 scripts/test-ha.sh 因 HA SocketBlockedError 在本地 HTTP fixture 失败/teardown error（10 passed，1 failed，1 error，baseline.log）；未修改该 fixture 或生产逻辑绕过。原生基线 11 passed（baseline-native.log）。

- R03.2 新 test_dma_runtime_recovery 编译实际 audio_capture.c/audio_output_manager.c（ESP_PLATFORM），边界为小型 fake IDF/FreeRTOS driver、队列及任务；非另造算法。旧实现 RED 1 failed/2 passed（red-dma.log）。7 个运行模式 startup、tx、normal、failure、early_release、repeat、stalled_tx；normal 真实队列预填、长间隔继续 PCM、STOP、可信 release、新 owner，RX 创建仍为一次；tx 用非零槽断言旧 gen 引用/可信 release 均无效，新 ring 全零；failure 驱动新建失败；repeat 重建未证明有效前再次漏；stalled_tx 新 ring 有 RX 无 TX EOF。初次 GREEN 后扩展 early_release/stalled_tx 又 RED（red-recovery-readiness.log），补有效 frame 与有界失败后通过。启动单漏测试先学槽0再漏槽1，不假造无法观测的第一次 EOF。
- R03.4 test_local_lifecycle_adapter 执行真实 s3_local_turn/p68_local_turn/p68_prompt，fake owner/SDK/transport；prompt_fault 5s 联动测试旧实现 RED 1 failed/1 passed（red-prompt.log），断言一次恢复、一次 failed discard、无旧 gate、期间 wake 被拒，恢复后新 turn 才 gate。保留正常生命周期/续聊/打断断言及原短提示测试。
- 自审 stale_fault 模式在已授权回复时模拟 fault serial 增加而 fetch 未 tick，旧代码仍允许 bind（red-stale-fault.log，1 failed/1 passed）；修复后随全量通过。
- 定向六文件回归 12 passed（green-recovery-readiness.log）。最终完整 ESP suite 初跑 101 passed、1 failed（green-full-esp32.log）；唯一失败既有 P5B2 cross-language golden TCP 读取 5s 超时，当时 S3 正构建。该测试独立编译 network_listeners/control_bridge/tivoo_frame_stream/diagnostics/cJSON/stub/simulator（没有 R03 修改的任何源文件），不修改其代码；不能凭一次超时断言根因，脱离编译负载全量串行重跑 102 passed、0 failed、0 skipped、35 warnings、61.96s、exit 0（green-full-esp32-serial.log）。warnings 为 native 未启用 HA/asyncio/socket marker 插件导致的既有配置/mark 提示及依赖弃用。R11 全 HA/Sherpa 回归未运行。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest \
  tests/esp32 -q -p no:cacheprovider
```

## S3 构建

使用既有 EIM v6.1，不安装/升级；S3 开发配置 TEST_GATE/PROMPT_CALIBRATED 禁用、空 Wi-Fi 凭据（R01 独立 dummy Wi-Fi 证据保留）；无生产配置改变。只重编本批 S3 target，串行 ninja -j1；最终 reconfigure/build/size 全 exit 0（s3-final-build.log），首次 build 与最后 build 记录都保留。APP 2104560 bytes，image size 报告 2104449 bytes，DIRAM 196487/341760 bytes（57.49%）；非实机 RAM 峰值/性能数据。

```bash
source ~/.espressif/tools/activate_idf_v6.1.sh
cd esp32/firmware
CMAKE_BUILD_PARALLEL_LEVEL=1 idf.py -B build reconfigure
nice -n 5 ninja -C build -j1
CMAKE_BUILD_PARALLEL_LEVEL=1 idf.py -B build size
```

APP SHA256：9f4ddd1a373ab5923dd65d0b6e79db5fe379046ad65057c063cb60958708f1d0。归档 .superpowers/p68-r03/firmware/{tivoo_firmware.bin,tivoo_firmware.elf,flasher_args.json,SHA256SUMS}，三文件 hash 校验通过；不复制 sdkconfig 凭据。Classic 无本批编译义务，R02 证据保留；两 target clean build 和完整镜像核销归 R11。

## R04 接口、裁决与未验收事项

- capture_next 非 OK、frame.gap / reference_valid / first_sample 已是真实时轴与断裂接口；恢复不复用旧 sample epoch。capture_running 与 output_available 是新 epoch 是否已验证及当前是否可用；output_fault_serial 可识别隔离的旧轮；output_failed(generation) 拒绝把 discard 当完成；recovery_boundary 为 16k 样本位置，供 R04/R05 按实际标定及 AFE 状态使用。现 s3_afe feed 已消费 non-OK/gap/ref invalid 触发 reset 请求，本批不改 vendor AFE 生命周期、动态能力发布、VAD 跨 gate 和 raw trace。
- R03.1–5 对应软件修复/证据完成。按 Superpowers systematic-debugging/test-driven-development/requesting-code-review/verification-before-completion 执行；无独立 reviewer/subagent 工具，实际 diff、锁顺序、状态、断言自审，补 early-release/stalled TX 和 stale authorization 后未发现本批已知 Critical/Important 遗留。fake driver 同步任务调用不能证明 IDF 多核 ISR 调度，不能证明真实同步相位、FIFO 尾部、AUX 物理静音/尾音；故障触发到停止之间旧槽可能尚有输出，不承诺零泄漏瞬时止声。若同一故障无法形成有效帧则本次启动安全隔离，不无限重启；真正实物持续故障后的恢复需求属硬件实测，不声称验证完毕。R04 对外能力、R05 测量、R08 worker 和 R11 总验收保留。
- S3/第二颗麦克风未到位，未访问 NAS、未部署/刷写/擦 NVS、未启用测试 gate，不改 legacy 清理、配置或协议。仅 R03 本地提交；原 B1–B10 计划已有链接改动维持原状，不纳入本批；R04–R11/B9/B10 未执行。
