# Paraformer 中文/中英双语 STT 基准测试

使用 sherpa-onnx Paraformer zh-small INT8（2024-03-09）。NAS 与 ARM Ubuntu 使用同一模型文件和同一组官方测试音频，便于比较纯 CPU 推理速度。

模型来自 sherpa-onnx 官方 release：
https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-paraformer-zh-small-2024-03-09.tar.bz2

模型说明：支持普通话、英语及部分中文方言，不支持时间戳。官方说明和下载方式见：
https://k2-fsa.github.io/sherpa/onnx/pretrained_models/offline-paraformer/paraformer-models.html

随模型发布的 `test_wavs` 被用于两台设备的测试。它们不是 Tivoo 实机录音，因此本测试衡量的是模型推理延迟，不代表 Tivoo 麦克风下的识别准确率。

## 目录

- `sherpa-onnx-paraformer-zh-small-2024-03-09/`：模型、token 和官方测试 WAV
- `benchmark.py`：统一的 Python 基准脚本
- `run-arm-ubuntu.sh`：在 ARM Ubuntu 上复现实测
- `arm-ubuntu/`：ARM Ubuntu 的硬件信息、逐项结果和完整日志
- `nas/`：NAS 的硬件信息、原运行脚本和完整测试日志

## 测量方法

使用 `OfflineRecognizer.from_paraformer`、CPU provider、greedy_search。每段音频先 warm-up 一次，再独立解码 5 次。结果报告 5 次推理耗时的中位数、最小值、最大值和 RTF。

`RTF = 推理耗时 / 输入音频时长`。RTF 小于 1 表示识别快于音频本身时长。

本次是整段音频离线识别，不是流式识别。对应 Tivoo 的使用方式是：唤醒后采集到一段完整语音，结束后提交给 HA/STT，再把识别文本送往 AstrBot。

## ARM Ubuntu 复现

```bash
./run-arm-ubuntu.sh
```

下载依赖使用设备本机代理 `http://127.0.0.1:7897`。脚本把 Python 环境放在 `/tmp/tivoo-stt-venv`，不会把虚拟环境放进项目目录。
