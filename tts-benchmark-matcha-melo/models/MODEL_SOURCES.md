# Model source files

All model archives came from the sherpa-onnx official GitHub release assets.

- Matcha Baker: https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/matcha-icefall-zh-baker.tar.bz2
- Vocos 22 kHz: https://github.com/k2-fsa/sherpa-onnx/releases/download/vocoder-models/vocos-22khz-univ.onnx
- MeloTTS Chinese/English: https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-melo-tts-zh_en.tar.bz2

The MeloTTS archive contains model.onnx. Its model.int8.onnx entry is a Git LFS pointer file rather than the corresponding 53.5 MB ONNX payload. This benchmark therefore uses model.onnx.
