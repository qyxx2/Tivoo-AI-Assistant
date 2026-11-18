# P6.8b4：双麦 AFE、本地 WakeNet（软件验收）

日期：2026-11-18；实现提交：84fd5b35764093af02fb45b64c61b22eb6d96819。仅 b4；S3、第二颗 INMP441 未到货，未连接 NAS、未部署、未刷写任一固件。参考 b0.3 AFE 合同、b0.4/b0.5 gate/owner 边界、b3 实现与执行计划。工作继续在 feature/p6-8-s3-local-wake。

## 实现与依据

- S3 正常启动改为单一 b3 RX 队列消费者 s3_afe；编译图新增 s3_afe / p68_afe_flow，旧单麦前端仍不编入 S3。AFE 初始化失败仅保留 b3 物理音频与采集诊断，绝不启用旧 NAS KWS。没有新增 7778 wire capability、HA session、网络发送、显示事件或本地提示播放，后续归 b5–b8。
- 核对实际 ESP-IDF v6.1、ESP-SR 2.6.1 的 esp_afe_config.h、esp_afe_sr_iface.h、esp_wn_iface.h、model_path.c 和 _MODEL_INFO_。CMake 从实际启用的 Kconfig WakeNet 项取唯一精确模型 ID，拒绝零/多个；运行时要求 model partition 恰好包含指定 WakeNet 和 vadnet1_medium，校验元数据、以分号分隔实际词、记录 list 与词。保留 b1 的 wn9_hilexin（元数据“嗨，乐鑫”）和 VADNet1 medium，属于合同允许的 smoke，**不是用户最终词**。不替用户选最终词、不换版本。
- 真实运行路径 afe_config_init("MMNR", models, AFE_TYPE_FD, AFE_MODE_HIGH_PERF)，AEC FD HIGH_PERF、BSS=true、NS=false、VADNet1 medium、vad_mute_playback=false；128/500/128ms speech/noise/delay，优先 PSRAM，保留模型/AGC 初值。afe_config_check 后校验有效配置和 M/M/N/R indices，create 后动态查 feed/fetch chunks、4输入/1输出/16k；调用 print_pipeline，打印实际阈值与资源。初始化和打印是固件代码，未在实物运行，不把编译当作初始化通过。
- b3 的 80-sample L/R/reference 块按动态 feed chunk 累积，交织 L/R/0/TX；独立 core1 feed/fetch task 调用实际 vendor API。成功 fetch 校验返回码、实际字节数、偶数、上限，再同步送本地非阻塞 callback；跨回调必须复制。RX timeout/缺参考/跳号、feed/fetch 错误暂停 feed、停止事件发布、清空部分 chunk 和命令历史，使用 API reset_buffer/reset_vad（失败禁用 local wake），恢复后先见 neutral 再 arm。gap 不产生正常 speech_end。实际 vendor 内部缓存、reset 的声学状态清空和恢复吞吐仍需实测。
- multi raw channel DETECTED 仅保存已知单模型候选，CHANNEL_VERIFIED 使用匹配的候选 ID（缺省 verified index 可用候选）；重复 verified 不重发，neutral 后新候选可重触发；单 raw channel 以 DETECTED 确认。短 prompt gate 后清除旧候选，按逻辑样本边界屏蔽跨界 wake；普通 TTS 无此门控。状态、raw channels、model/word/trigger channel trace 保留，实际模型序列未实测。
- 命令默认 gate 关闭；本地 sink 事件 WAKE/START/PCM/END/GAP，不上传待机或候选音频。gate 后所有有效增强块（含静音）进入有界 8000-sample/500ms PCM history；首 speech 先 START 再按 index 回补 history/当前块，silence 转换消费尾块后 END，不叠额外静音 timer。VAD cache 无独立 sample index，沿用旧前端连续 fetch history 的防重叠语义，不盲目把 cache 再拼接，计数并保留实物 marker 校验；若证明 cache 存在真正未覆盖音频须按实测修订。短 gate 可切分逻辑帧，已丢弃/重复开 gate 拒绝并 GAP。4项非阻塞控制队列供后续调用；session generation、重复 wire gate 幂等、ready/1s限、20ms帧装配、物理 prompt 与尾部安全 gate 由相应后续批次接入。
- 时间轴裁决：每连续 epoch 由首个实际提交的 b3 capture index 锚定，成功 fetch 按返回样本数递增；此为**逻辑增强流索引**，vendor API 不提供物理源样本索引/处理延迟。严禁把 fetch index 或当前 0 参考延迟当成已标定的声学时钟，b4/b6 真机标记测量后再把物理安全 gate 映射到该轴。gap 清除 epoch/context，不能拼接。
- 运行诊断包含实际 model/pipeline、阈值、动态 chunk、wake 状态、RX拒绝块/原始 overruns 与 missed EOF、feed/fetch error、reset、cache count、ring、耗时最大值、stack water、internal min/largest/DMA largest/PSRAM。RX拒绝块不是物理丢帧次数，静态 size 与日志接口不证明实时资源。P95、CPU per core、声学相对延迟、ERLE、连续负载须真机补测。

## 软件验证

| 项目 | 结果 |
|---|---|
| T04 host + 接入图（首次 RED） | 2 failed（缺实现/源文件），exit 1 |
| T04 迟到/重复 gate RED→GREEN | 1 failed → 定向通过 |
| T04 + b3 定向 | 4 passed，exit 0 |
| ESP32 standalone 全量（含 T03 回归） | 85 passed, 34 warnings，exit 0 |
| S3 IDF v6.1 reconfigure + 单线程 Ninja + size | exit 0；实现提交重建完成 |
| git diff --check / staged diff check | 通过 |

命令：`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32 -q`；定向为 `tests/esp32/test_p68_afe.py tests/esp32/test_p68_audio.py`。C host 用例覆盖 MMNR 标记、重复 candidate/verified、未知词、再确认、跨 gate、任意 fetch chunk、history 环绕/500ms 上限、cache 不重复、START/PCM/END 顺序、gap 丢弃与拒绝迟到/重叠 gate。端点用例模拟 vendor 已应用 500ms hysteresis 的 state 切换，并非运行 VADNet 模型。

构建初始 shell 默认 IDF 激活查找错误路径及缺 ESP_IDF_VERSION；定位实际已安装 v6.1 SDK/venv/tools 后显式设置已有环境（不安装新依赖/不改宿主环境），CMAKE_BUILD_PARALLEL_LEVEL=1、ninja -j1，初次 GDB ROM 路径警告通过指定现有 ESP_ROM_ELF_DIR 消除。独立 pytest runner 有配置、旧 mark 与依赖弃用警告；无测试失败。构建期间抽样 MemAvailable 约4.6GB。无独立 reviewer 工具，按 Superpowers 完成实现者自审；迟到 gate 的缺陷已 RED→GREEN。没有硬件运行证据，未宣称 AFE runtime、CPU/延迟、声学性能或物理门禁通过。

## 构建与归档

ESP32-S3 app 1,914,784 B（8MiB app partition 剩 6,473,824 B，77%）；模型579,214 B；DIRAM195,927/341,760 B（余145,833 B）；专用 IRAM16,384/16,384 B（含 vectors）。这些静态值不能证明内部动态 AFE 内存够用。app SHA256 dd1e7f1c2e314bf9e983b09ae8cc3cc5cfd3453cf4f16bcc8285bee0fc8dc458；model SHA256 f1a1a39defc1d1c52d112b45629fb221adad4dfda85785ed9f527cb53a145e19。实现提交版本 0.1.0+84fd5b3。原始日志 .superpowers/p68-b4/；分段镜像/真实生成 flash_args、flasher_args.json 及 SHA256SUMS 存 .superpowers/p68-b4/artifacts/esp32s3/（仅归档）。没有执行 flash。

## 合同核销

| 合同 | 软件证据 | 实物 GAP |
|---|---|---|
| AFE-C06/07 | 真实 API 编译链接、有效配置检查及动态 chunk 路径 | 实际模型 mmap/init/print_pipeline、真实 feed/fetch |
| AFE-C08 | 单 smoke 模型精确 ID/元数据校验路径、model 包/哈希 | 用户最终词、实物加载及每个词正负样本 |
| AFE-C09 | 主机 candidate/verified/gate/gap/再触发 | 真模型 raw channels/state 序列与实际重触发、TTS 双讲 |
| AFE-C10 | 逻辑历史/cache 防重、端点顺序、gate 主机测试 | 实际增强流/marker、cache覆盖、物理 gate 样本映射、500ms实际端点 |
| AFE-C11 | 不强制叠 NSNet2/3，保留本地 wake 流程 | 实际5cm布局、1m/3m/坐姿、电视负样本与同词、TTS、ERLE、误漏/延迟 |
| AFE-C12 | 静态大小、运行诊断与故障处理路径 | runtime heap/DMA/PSRAM/CPU/P95、reset恢复、Wi-Fi/TTS/UART并发、长时无丢帧 |

T04-A 只验收本批软件部分；T04-B 全部物理验收 GAP。按用户要求新实物到位后才刷两板并验证。b5 未实施，无需当前人工选词才能继续 smoke 软件开发；最终词及实测物理安全边界不得由代码猜定。
