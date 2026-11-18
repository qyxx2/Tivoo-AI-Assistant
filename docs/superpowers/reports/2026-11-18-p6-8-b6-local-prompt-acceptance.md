# P6.8b6：本地提示音与 endpoint（软件验收）

实现提交：358741a6a1feb62b65b003e8593d479e56ad10d4；分支 feature/p6-8-s3-local-wake。仅实施 b6。依据 b0.4 HA/STT/prompt 合同、b0.5 owner 合同及 b3–b5 实现、ESP-IDF 6.1 本地源码。未连接 NAS、未部署、未刷写任何固件。

## 实现

- T06-A：复用四个冻结 MP3。CMake 配置时运行 generate_prompts.py，校验源 SHA256 与输出长度，FFmpeg 解码为 s16le、32kHz、mono；汇编 .incbin、4 字节对齐，实际 ELF 符号均在映射 Flash .flash.rodata 范围。源文件不改，缺失素材生成空资产；错误 hash/长度拒绝构建。ready 池随机、相邻不重复，缺失不跨池；followup 单独 beep，未接 b7 授权。无运行时 MP3 解码、HTTP 拉取或 TTS 合成。
- T06-B：p68_prompt 复用同一个 audio_output_manager 的 generation/owner，非阻塞分段送 PCM，短音跳过普通流 120ms 预缓冲，保留 FIFO/真实 DMA drain、已有 TX/reference 机制；ordinary TTS 保持预缓冲与 wake 检测。短 prompt 不产生 ordinary AUDIO_STATE（代码路径核对）。AFE fetch poll 使用真实 DMA 样本计数及保守 drain 边界，叠加待标定声学 tail 和有符号 AFE offset；清除旧候选和 history，短音后需 neutral 重置，仅在有效样本边界开放新收音。缺资产也需确认当前无声；5s watchdog、epoch 变更、MIC STOP/gap 取消本轮，无确认 drain 时保留隔离 owner/mask，迟到的安全 drain 仅释放，不为取消轮开 gate。owner 不可用时本轮失败，不停止未知旧 owner；b7 实现完整交接。
- VOICE-C05–10：沿用 b5 session/gate/READY/PCM/END 协议、20ms 帧及尾帧补零、1s READY / 3s 首命令 / 15s 命令期限。正常本地提示完成或缺失时使用 completed/skipped；无安全边界以取消结束，不发送错误 gate。HA 已有接收实现无需生产代码变更；扩展 all-result gate/READY 时序、真实 HA Core / mock Wyoming 的 completed gate 验证。b7 续聊 4s 授权与打断不在本批范围。

## 资产构建证据

FFmpeg 8.0.1-3ubuntu2；源 SHA256 → PCM SHA256：

| 文件 | PCM B | 源 SHA256 | PCM SHA256 |
|---|---:|---|---|
| ready_01 | 47402 | 17727761db1100511d7728038d5212ec896e1aa141e666283a1c474d12e92d80 | 7ab8cf1c2a023d7bed202c1fddf99312a8e336643000cb77fd47447eeec698b9 |
| ready_02 | 47784 | f4e90f5588f87d23b49adf76fca2907422bf92e41da77ab76b8c352326a88c67 | 021b952f363c4eba98ef4f68b9d5b0a3f08df646a00d26d884a6a047db2c2151 |
| ready_03 | 53254 | 22e7ec8ce43ee406de94f95b46a988ac7a44cf0c838d93b05cfed80a166634a7 | 1494b183047d416a58abcd0d19c0e70699dfd0a6cf836324e1427c9c9ac23b02 |
| followup_01 | 30720 | 67b5d7ccced82fa74b52dc0e0fe56388dbc6386022f662f54f855b66674cb978 | d0bc3aec088f0dd7838d3f1f242fa5c74e7a4930d935655ea57308c555a20ba5 |
| 总计 | 179160 | | |

最终 app 2,100,688 B，8MiB app 分区余 6,287,920 B（构建报告 75%）；SHA256 a17ce604aed0d5461fc77454b4f710cf70c34f5e42f3770a9f988211f133a6ce。模型 SHA256 f1a1a39defc1d1c52d112b45629fb221adad4dfda85785ed9f527cb53a145e19，与 b5 相同。ELF .flash.rodata 起始 0x3c150120，资产 start/end 范围 0x3c16d2a4–0x3c198e80。只 build，不 flash。

## 软件验证

| 测试 | 结果 |
|---|---|
| 新增 prompt RED | 2 failed（缺实现） |
| prompt/AFE/audio GREEN | 6 passed, 2 warnings |
| ESP32 standalone 首次全量 | 89 passed, 1 failed, 35 warnings |
| 旧 diagnostics 模块独立复测 | 25 passed, 29 warnings |
| ESP32 standalone 最终全量 | 90 passed, 35 warnings |
| HA prompt/assets/audio_session/assist_satellite/local_session/real_pipeline 指定回归 | 97 passed, 9 warnings |
| S3 IDF 6.1 最终实现提交重新配置 / 单线程 Ninja | exit 0 |
| Git diff --check | 通过 |

fake clock/marker 测试含真实 host PCM queue、无预缓冲、drain+tail、skip、5s watchdog/stop once、迟到 drain 不给取消轮 gate、旧 wake 丢弃、短命令 marker 与 480 个有效样本+160 个补零样本、PCM 确定性转换两次及资产缺失/源篡改。HA completed gate 测试使用真实 Core + mock ASR endpoint，64000 字节一致、一次 AudioStop、不发远程提示音；不是实机 VAD 或真实 ASR 精度测试。

首次全量唯一失败为旧 test_queued_records_survive_disconnect_and_replay_after_new_handshake TCP reset；该 diagnostics 生产路径未修改，独立模块和全量复跑通过，不能由此认定该偶发故障已经修复。HA 全量及 Sherpa 全量不重复运行（b6 不改相关生产模块，执行计划要求指定回归）。无独立 reviewer 工具，进行实现者自审。构建首次 shell SDK 激活路径不正确，显式使用现有 IDF/venv 环境解决，未安装或修改宿主配置；CMAKE_BUILD_PARALLEL_LEVEL=1、ninja -j1。

日志：.superpowers/p68-b6/（red.log、green-core.log、esp-all.log、diagnostics-recheck.log、esp-final.log、ha-focused.log、s3-build-final.log）。ESP32：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32 -q；HA：PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath" bash scripts/test-ha.sh 对应六个 test 文件 -q。

## 物理验收阻塞

S3 与第二颗 INMP441 未到：不能确定真实 TX/RX 起始相位、声学尾部或 AFE 样本映射，不沿用旧 ESP32 47.5ms。新增 TIVOO_P68_PROMPT_CALIBRATED 默认关闭，TIVOO_P68_PROMPT_TAIL_SAMPLES / TIVOO_P68_PROMPT_AFE_OFFSET_SAMPLES 的 0 是待测占位而非可用默认；未标定 production local wake 明确 prompt_calibration_required 取消，不播放/不上送命令。TIVOO_P68_TEST_GATE 默认关闭，仅测试可用。实物到位须用 TX/RX/AFE marker 标定并验证头尾、听完立即说、短命令、500ms 真实 VAD endpoint、3s 首命令窗口、真实 AudioStop、普通 TTS wake 不受影响及提示音自播负样本。T06-B 保留 physical GAP。无阻塞当前软件实现的新增人工选择；禁止将软件 PASS 当生产可用。b7 未进入。
