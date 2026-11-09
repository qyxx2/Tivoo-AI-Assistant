# NAS TTS 测试记录

测试日期：2026-11-07。设备为 Synology DS920，系统报告 Intel Celeron 1005M @ 1.90 GHz，2 logical CPUs，约 3.89 GiB RAM。测试使用 Docker Python 3.11、CPU provider；各测试容器内存限制 1 GiB。

## 测试结果

### VITS AISHELL3

- sherpa-onnx VITS AISHELL3，8 kHz 单声道输出。
- 模型包含 174 个 speaker，可通过 sid 选择音色。
- 模型加载约 1.58–1.60 s。
- 1 线程：sid 21 / 41 / 45 对相同短句的 RTF 分别为 0.370 / 0.345 / 0.353。
- 2 线程：相应 RTF 分别为 0.241 / 0.234 / 0.295。
- 长句（约 10.361 s 音频）2 线程合成耗时 2.305 s，RTF 0.222，峰值 RSS 212.6 MB。
- 两条短句 2 线程：1.263 s 音频耗时 0.457 s（RTF 0.362）；1.587 s 音频耗时 0.510 s（RTF 0.321）。

输出样本：`samples/aishell3_*.wav`、`samples/good_done_sid21.wav`、`samples/happy_today_sid41.wav`。

**限制：** 8 kHz 输出带宽较窄，不能仅凭 RTF 判断最终听感。它的优势是推理速度和可选音色数量。

### Kokoro INT8

| 音色 | sid | 输出采样率 | 音频时长 | 合成耗时 | RTF |
|---|---:|---:|---:|---:|---:|
| female zf_001 | 3 | 24 kHz | 13.114 s | 80.938 s | 6.172 |
| male zm_009 | 58 | 24 kHz | 12.866 s | 80.371 s | 6.247 |

这次单线程测试明显慢于实时，峰值 RSS 约 473.3 MB。音频样本位于 `samples/kokoro_*.wav`。

### Matcha Baker

- 22.05 kHz，单 speaker。
- NAS 单线程生成 11.985 s 音频耗时 7.171 s，RTF 0.598。
- 本轮进程先加载 Kokoro，再加载 Matcha；Matcha 加载耗时 5.110 s。进程峰值 RSS 639.0 MB 是两个模型先后驻留的进程峰值，不是 Matcha 独占内存数据。
- 样本：`samples/matcha_baker_t1.wav`。

### MeloTTS 中文

- 使用 full-precision `model.onnx`，单线程。
- 11.229 s 音频合成耗时 55.336 s，RTF 4.928。
- 输出 44.1 kHz，峰值 RSS 403.7 MB。
- 样本：`samples/melo_chinese_t1.wav`。

### ZipVoice Distill INT8

- 2 线程，使用 Kokoro 女声参考音频做声音条件。
- 生成 2.517 s 短音频耗时 48.051 s，RTF 19.088。
- 峰值 RSS 707.1 MB。
- 样本：`samples/zipvoice_distill_short_2t.wav`。

## NAS 侧结论

本轮 NAS 测试中，AISHELL3 的速度余量最大，但输出只有 8 kHz；Matcha Baker 单线程也达到 RTF 0.598，输出规格为 22.05 kHz。Kokoro、MeloTTS 和本次 ZipVoice 配置没有达到实时合成速度。

NAS 结果不能直接替代 ARM Ubuntu 的 TTS 测试。两台设备的 CPU、线程数、Python 环境和模型运行参数不同。ARM Ubuntu 上 Matcha Baker / MeloTTS 的独立对照见项目根目录的 `tts-benchmark-matcha-melo/README.md`。

## 已保留材料

- `scripts/`：NAS 上执行过的原始 Python 测试脚本。
- `samples/`：NAS 生成的 WAV 试听样本。
- `models/`：NAS 测试所用的 AISHELL3、Kokoro、ZipVoice 和 Vocos 24 kHz 模型权重。
- Matcha Baker、MeloTTS 和 Vocos 22 kHz 与 ARM Ubuntu 测试使用同一模型文件；SHA-256 已验证一致，因此复用 `tts-benchmark-matcha-melo/models/` 下的模型，不重复占用空间。
- 完整模型来源见 `MODEL_SOURCES.md`；NAS 独有模型权重校验见 `models/SHA256SUMS`。
