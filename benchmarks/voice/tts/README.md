# 语音合成测试

- [NAS TTS 测试记录](nas/README.md)：AISHELL3、Kokoro、Matcha Baker、MeloTTS 和 ZipVoice。
- [ARM Ubuntu Matcha Baker / MeloTTS 完整测试](../../../tts-benchmark-matcha-melo/README.md)：本机 ARM64 设备 1/2/4 线程对照、逐项日志、原始 JSONL、CSV、WAV 样本和模型文件。

两台设备的模型、输出采样率、线程数和测试文本并不完全相同。跨设备比较应以同一模型、相同输入文本、相同线程配置的复测为准；不能仅凭不同模型的 RTF 排名推导主观音质。
