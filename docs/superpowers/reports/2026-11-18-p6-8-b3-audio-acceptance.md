# P6.8b3：音频物理通路与真实参考（软件验收）

日期：2026-11-18；实现提交：801e5a5d956c30618fe7fa0ca04dc4469cd5c625。
依据：b0.2 硬件冻结、b0.3 AFE 规格、b1–b10 执行计划。
范围仅 b3；S3 与第二颗 INMP441 尚未到货。未连接 NAS、未部署、未刷写任何固件；原经典 ESP32 不变。

## 实现与依据

- S3 的 I2S0 TX/RX 全双工，共享 GPIO4 BCLK、GPIO5 WS，GPIO6 双麦 SD、GPIO7 DAC DIN。核对锁定 ESP-IDF v6.1 的 i2s_common.c / i2s_std.c：先初始化 TX master、后初始化 RX slave，共享时钟；先 arm RX 再启 TX；EOF 回调先于驱动自动清理。不虚构硬件启动相位。
- 32 kHz stereo、32-bit slot，高24位有符号 INMP441；独立左/右 31-tap FIR、同相位 32→16 kHz、饱和 s16；26 个 5 ms 块丢弃（130 ms，覆盖128 ms启动约束）。不会把双麦平均或旧单麦 AFE 当作 BSS。
- RX EOF ISR 拷贝 DMA 数据进入12块有界队列，按顺序索引输出每声道80个16 kHz样本、原始RX/TX标记、gap/reference_valid。缺块由索引距离计数一次；异常启动描述符顺序标记不确定，缺参考不冒充有效，断点重置滤波历史。整个DMA环周次的完全丢失不能仅凭重复描述符地址无歧义恢复，真实时序和恢复能力需实机验收。
- TX 在实际 EOF 先保存完成的32 kHz mono PCM，再写下一轮 DMA；160 ms 原始参考环、60 ms DMA、160 ms播放队列、120 ms初次预填；TX与双麦共用同一31-tap滤波器，参考采样索引可追溯。缺块明确标记；DMA EOF 不等于最终 AUX 波形或声学时间。
- 中间欠载输出零、保持同一播放流并不重新预填；输入结束且尾部 drain 才完成。停止清掉待提交队列，不修改可能已经被GDMA预取的描述符，保留最多60 ms已提交DMA及保守FIFO余量（实际尾部延迟待测）。参考延迟配置改为0（未校准初值，而非实测结论）；旧47.5 ms不移植。
- 复用 audio_playback、audio_resource、HTTP/HTTPS URL、TLS、MP3、raw PCM、SRC 与原协议。S3 仅在 I2S 正常时宣告下行能力；旧单麦 frontend 不进入 S3 target，未引入 WakeNet、AFE/BSS/VAD 或上传。b6 的本地提示音门控尚未实施。
- 采集 task 提供运行期队列水位、样本/参考缺口、输入电平、内部heap最小值、DMA余量和栈水位日志；实际数值未测。ELF符号检查确认 RX/TX EOF及其相关实时函数位于IRAM，ISR块、队列及参考环位于DRAM。

## 软件验证

| 项目 | 结果 |
|---|---|
| TDD：双声道/分块、参考同滤波器、启动顺序异常 | red→green；新增主机用例通过 |
| b3 定向（下列五文件） | 7 passed |
| ESP32 全量 standalone | 第一轮83 passed；第二轮82 passed、1 failed；失败项单独复跑1 passed |
| HA transport/audio_resource/diagnostics | 76 passed |
| S3 IDF v6.1 reconfigure + ninja -j1 + size | exit 0，最终提交重建通过 |
| git diff --check | 通过 |

定向：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32/test_p68_audio.py tests/esp32/test_audio_rx_timeline.py tests/esp32/test_p65b8_audio.py tests/esp32/test_p65b10_output.py tests/esp32/test_p6_audio_resource.py -q。
HA：bash scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_transport.py tests/homeassistant/custom_components/tivoo/test_audio_resource.py tests/homeassistant/custom_components/tivoo/test_diagnostics.py -q。

异常记录：HA runner 运行旧 HTTP host fixture 时受 socket fixture 限制（1 fail/1 teardown error）；改用独立 host runner 后定向全过，未改旧 fixture。首次完整编译遇零延迟预处理配置的 unsigned 比较警告，修复后构建通过。第二轮全量失败为 test_wifi_ip_loss_closes_both_ports_and_new_sessions_recover，旧断线测试期望 FIN，却收到 ConnectionResetError；单独复跑通过，未将其称为稳定通过，未扩展 b3 去修改网络模块。独立 host runner 有 pytest 配置/mark 与依赖警告。HTTP fixture 为主机模拟，HTTPS/TLS 实机连通性仍待验收。日志存 .superpowers/p68-b3/。
代码由本次实现者自审，未得到独立 reviewer 的结论。

## 构建记录

ESP32-S3 app 1,908,480 B；最小 app partition 8 MiB，剩余 6,480,128 B（77%）；模型 579,214 B。DIRAM 195,831 / 341,760 B，剩余 145,929 B；专用 IRAM 16,384 / 16,384 B，含 vectors；该静态统计不能作为 runtime heap/CPU 的通过证据。
App SHA256：26de65d55e47ab410366e0f4ac9f1a484a21370449825e752e95552fbb40653a。
本地忽略目录 .superpowers/p68-b3/artifacts/esp32s3/ 保存最终实现提交的镜像、生成的 flash 参数和校验清单。仅归档，不刷机。
构建采用 CMAKE_BUILD_PARALLEL_LEVEL=1 与 ninja -j1；开发机可用内存抽样约4.3–4.6 GiB。

## 合同与待补验

| 合同 | 软件 | 实物 GAP |
|---|---|---|
| AFE-C01 | GPIO/I2S双麦配置与数据路径已实现 | 供电、L/R选通、独立敲击、示波 |
| AFE-C02 | 采样格式、FIR、饱和及分块主机测试通过 | 实际左右相位、初始130 ms及声道采集 |
| AFE-C03 | 原播放代码与32k mono输出接入、回归 | AUX 波形、真实MP3/PCM及HTTPS播放；本地提示音属b6 |
| AFE-C04 | EOF参考、gap及同FIR主机测试通过 | DMA起始相位、真实TX/RX索引对齐、脉冲相关和声学延迟；双讲属b4 |
| AFE-C05 | 有界预填、欠载不中断、取消与drain主机验证 | 实际长空挡、断网、恢复和stop尾部波形 |
| AFE-C12 | 静态构建、数据路径和日志接口 | 实际内部heap/DMA/CPU/并发水位、长期丢帧与异常恢复 |

T03-A/B 保留未完成的硬件 GAP；仅软件验收完成，不宣称整阶段实机通过。无本批软件必须提前人工确认的新增决定；b4未启动。
