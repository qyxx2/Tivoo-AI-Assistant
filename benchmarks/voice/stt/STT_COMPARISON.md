# STT 对比测试记录

测试日期：2026-11-07

## 测试对象

同一份 sherpa-onnx Paraformer zh-small INT8（2024-03-09）模型、同一批模型官方测试 WAV，分别在 Synology NAS 和 ARM Ubuntu 上运行。

模型文件 SHA-256：

```
3ef6c19369b912f7caf3cef8e545c5ccd1a33d9d7ec792a46668dc41c4b229ec  model.int8.onnx
4b2d964e18b9cf139b473003b6698fb2ed9a2a5ec55b93daa677b28f578897aa  tokens.txt
```

每段音频先 warm-up 一次，再测量 5 次，以中位数作为比较值。使用 CPU provider、greedy_search、OfflineRecognizer。所有输入均为 16 kHz、单声道、16-bit PCM WAV。

## NAS：Synology DS920

硬件：Intel Celeron 1005M @ 1.90 GHz，2 logical CPUs，约 3.89 GiB RAM。测试在 Docker Python 3.11 环境中运行，容器内存上限 1 GiB。

模型加载耗时：1 线程 2.865 s；2 线程 2.839 s。进程峰值 RSS 分别约 170.4 MB、170.0 MB。

| 线程 | 音频 | 音频时长 | 中位识别耗时 | RTF | 实时倍速 |
|---:|---|---:|---:|---:|---:|
| 1 | 0.wav | 5.033 s | 0.651 s | 0.129 | 7.73× |
| 1 | 1.wav | 5.153 s | 0.659 s | 0.128 | 7.82× |
| 1 | 2-zh-en.wav | 8.100 s | 0.998 s | 0.123 | 8.11× |
| 2 | 0.wav | 5.033 s | 0.447 s | 0.089 | 11.25× |
| 2 | 1.wav | 5.153 s | 0.462 s | 0.090 | 11.17× |
| 2 | 2-zh-en.wav | 8.100 s | 0.736 s | 0.091 | 11.01× |

NAS 原始测试日志：`nas/nas_stt_benchmark_20261107.log`。执行脚本：`nas/bench.py`。

## ARM Ubuntu

硬件：ARM Cortex-A77 / Qualcomm Kryo-4XX-Silver class，8 logical CPUs，10 GiB RAM。Linux 4.19.113 aarch64，Python 3.14.4，sherpa-onnx 2.0.1 原生 ARM64 wheel，直接运行于宿主系统，不使用 Docker。

模型加载耗时：1 线程 1.434 s；2 线程 1.481 s；4 线程 1.497 s。进程峰值 RSS 分别约 186.6 MB、186.9 MB、186.1 MB。

| 线程 | 音频 | 音频时长 | 中位识别耗时 | RTF | 实时倍速 |
|---:|---|---:|---:|---:|---:|
| 1 | 0.wav | 5.033 s | 0.134 s | 0.0266 | 37.55× |
| 1 | 1.wav | 5.153 s | 0.139 s | 0.0270 | 37.08× |
| 1 | 2-zh-en.wav | 8.100 s | 0.214 s | 0.0264 | 37.92× |
| 2 | 0.wav | 5.033 s | 0.104 s | 0.0206 | 48.44× |
| 2 | 1.wav | 5.153 s | 0.103 s | 0.0199 | 50.21× |
| 2 | 2-zh-en.wav | 8.100 s | 0.149 s | 0.0184 | 54.33× |
| 4 | 0.wav | 5.033 s | 0.068 s | 0.0134 | 74.48× |
| 4 | 1.wav | 5.153 s | 0.068 s | 0.0132 | 75.68× |
| 4 | 2-zh-en.wav | 8.100 s | 0.101 s | 0.0125 | 80.05× |

原始逐次结果：`arm-ubuntu/results.jsonl`；每组完整日志：`arm-ubuntu/logs/`。

## 结论与限制

- 两台设备均远快于实时语音时长，STT 推理不是这套链路的性能瓶颈。
- ARM Ubuntu 4 线程在这批样本上约为 74–80 倍实时；NAS 2 线程约为 11 倍实时。
- NAS 只有 2 个逻辑 CPU，因此测 1/2 线程；ARM Ubuntu 测 1/2/4 线程。
- 这批标准样本上的解码文本在两台设备上相同。测试没有提供人工标注的逐字真值，也没有计算 CER/WER，因此不能据此下结论说识别准确率达到某个数值。
- 这些是模型随包测试音频，不是 Tivoo 实际 HFP 麦克风录音。后续仍需用真实麦克风采样验证采音质量、噪声、回声和识别准确率。
- 本测试使用 OfflineRecognizer，意味着整段话结束后再识别；它不代表流式识别首字延迟。

## 复现

ARM Ubuntu：`./run-arm-ubuntu.sh`。

NAS：参照 `nas/bench.py` 和 `nas/nas_stt_benchmark_20261107.log`，使用 Docker Python 3.11、sherpa-onnx 2.0.1，容器内存限制 1 GiB。
