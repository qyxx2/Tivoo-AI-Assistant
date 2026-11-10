# P7A model sources and integrity records

All paths below are relative to the runtime model root (/models). Model weights
stay outside Git and are supplied through the persistent model volume.
MODEL_SHA256SUMS is the runtime integrity manifest consumed before any model
object is constructed.

## Keyword spotting — SHA-256 pending

- Model: sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20
- Official model documentation: https://k2-fsa.github.io/sherpa/onnx/kws/pretrained_models/index.html
- Official release archive:
  https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20.tar.bz2
- Required chunk-16 / left-64 files from the same release:
  - kws/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx
  - kws/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/decoder-epoch-13-avg-2-chunk-16-left-64.onnx
  - kws/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx
  - kws/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/tokens.txt
  - kws/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/en.phone
- The P7Ab0 workspace inventory found no copy of this release. Its five checksums
  are therefore not fabricated or copied from another model. P7Ab2 owns
  acquisition, archive/file hashing, Sherpa 2.0.1 compatibility smoke and
  keyword generation. Until those entries are added to MODEL_SHA256SUMS,
  complete model-bundle validation correctly fails closed.

## Speech recognition — Paraformer zh-small INT8

- Model: sherpa-onnx-paraformer-zh-small-2024-03-09
- Official release archive:
  https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-paraformer-zh-small-2024-03-09.tar.bz2
- Model file: stt/sherpa-onnx-paraformer-zh-small-2024-03-09/model.int8.onnx
  - SHA-256: 3ef6c19369b912f7caf3cef8e545c5ccd1a33d9d7ec792a46668dc41c4b229ec
- Tokens: stt/sherpa-onnx-paraformer-zh-small-2024-03-09/tokens.txt
  - SHA-256: 4b2d964e18b9cf139b473003b6698fb2ed9a2a5ec55b93daa677b28f578897aa
- Existing, locally benchmarked files: benchmarks/voice/stt/sherpa-onnx-paraformer-zh-small-2024-03-09/.
  The benchmark directory is the provenance source; it is not implicitly the
  runtime /models directory.

## Text-to-speech — Matcha Baker with Vocos 22.05 kHz

- Matcha archive:
  https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/matcha-icefall-zh-baker.tar.bz2
- Vocos asset:
  https://github.com/k2-fsa/sherpa-onnx/releases/download/vocoder-models/vocos-22khz-univ.onnx
- tts/matcha-icefall-zh-baker/model-steps-3.onnx
  - SHA-256: 78a9fd17e9a6c20198dca4e69d18f941303f8ab39ec61dde04cfc7595262ddfd
- tts/matcha-icefall-zh-baker/tokens.txt
  - SHA-256: 56209b2bf609d5ac1d66ede6dae7bf5254bd3f8aa24c4a6823713d5b884d87ba
- tts/matcha-icefall-zh-baker/lexicon.txt
  - SHA-256: 38b886d46aefa50da6322a64d72fd595d5f4fae1051adb160d647541b1e0a4a2
- tts/matcha-icefall-zh-baker/phone.fst
  - SHA-256: 1ac2b6fa56b1442320c4de7db08353bab8963a2b57f365eebcdd3a2d3562f8d7
- tts/matcha-icefall-zh-baker/date.fst
  - SHA-256: eb8aa079ae3cb81d8f4404992f39d61a0cb990947512b5b8d1e54d1f6980e718
- tts/matcha-icefall-zh-baker/number.fst
  - SHA-256: 743f402181fcfebf76cc2f0546b71fa26476e626fbe4e460fb7b4c3a7a8bd5bd
- tts/vocos-22khz-univ.onnx
  - SHA-256: 0574a135aa1db2de6e181050db2ec528496cacd4a4701fc5d7faf9f9804c0081

The files are already present under tts-benchmark-matcha-melo/models/.
The loader follows that project's benchmark configuration: Matcha acoustic
model + Vocos vocoder + tokens/lexicon + phone/date/number FST, CPU provider,
sid=0 at the later synthesis boundary. It intentionally does not use the
upstream HiFi-GAN default.

## Runtime validation

model_utils.verify_model_files() checks every required model path against
MODEL_SHA256SUMS before models.load_models() constructs any model. It does
not download models, extract archives, generate keywords or silently select
an alternate model. Model preparation remains a separate deployment task.
