# Sherpa Wyoming upstream reuse record

## Pinned source

- Repository: [ptbsare/sherpa-onnx-tts-stt](https://github.com/ptbsare/sherpa-onnx-tts-stt)
- Commit: `c307e6835a079157e71df28545f17d76bca1cbc2` (2025-11-29, `Merge pull request #11 from fargies/feat-default-models`)
- Local review checkout used for this record: `/tmp/p7a-upstream-sherpa` (detached at the commit above; not part of this repository)
- Reviewed files: `run.py`, `model_utils.py`, `models/stt/sherpa-onnx-paraformer-zh-small-2024-03-09.py`, `models/tts/matcha-icefall-zh-baker.py`, `Dockerfile`, and `api.py`.

The pinned revision is the reference implementation for the P7A server and model lifecycle. Reuse its existing protocol/library integration and model construction patterns; do not reimplement Wyoming framing or Sherpa inference.

## Reuse map

| Upstream source | Existing useful implementation | P7A treatment |
|---|---|---|
| `run.py` | `AsyncTcpServer` + `AsyncEventHandler` lifecycle; Describe/Info response; Wyoming event classes and the basic STT/TTS request flow | Reuse the Wyoming 1.10.2 server/event APIs and adapt the handler into one connection-level dispatcher. Preserve one server and port; add the Wake provider and per-request state. |
| `models/stt/sherpa-onnx-paraformer-zh-small-2024-03-09.py` | `OfflineRecognizer.from_paraformer` construction with the project's Paraformer model, tokens, 16 kHz input, greedy decoding and CPU provider | Adapt the loader to the P7A fixed model directory, verified files and `ServiceConfig`; do not carry over download-at-startup behavior. |
| `models/tts/matcha-icefall-zh-baker.py` | `OfflineTts` / `OfflineTtsConfig` / Matcha model configuration, lexicon/tokens and rule-FST wiring | Adapt the loader to the project-tested `vocos-22khz-univ.onnx` vocoder, 22,050 Hz output and fixed `/models/tts` paths. Do not use the upstream HiFi-GAN default. |
| `model_utils.py` | Model directory conventions, the built-in loader layout and the separation between model preparation and model construction | Reuse the useful structure only. Replace dynamic imports/evaluation and unchecked startup downloads with explicit paths and startup file/hash validation. |
| `Dockerfile` | Python 3.11 base-runtime reference | Reference only; do not copy the image recipe wholesale. P7A has a CPU-only, pinned runtime and the image is built exclusively by GitHub Actions. |

The upstream `run.py` constructs one `AsyncTcpServer` and injects model objects into a connection handler. It also includes an existing Wyoming Describe response and parses `Synthesize`, `Transcribe`, `AudioStart`, `AudioChunk` and `AudioStop` events. Those existing boundaries are preferable to a new protocol implementation.

## Required adaptations and exclusions

The following upstream behaviors are not carried into P7A:

- FastAPI, Uvicorn, `api.py`, the OpenAI-compatible HTTP API and TCP port `10500`; P7A exposes only Wyoming TCP `10400`.
- `nvidia-smi` probing and automatic CUDA selection; the service uses the CPU execution provider.
- Floating `wyoming` installation from Git HEAD; P7A pins `wyoming==1.10.2` and `sherpa-onnx==2.0.1`.
- `eval()`-based custom model expressions and implicit dynamic model-module loading; P7A uses explicit configuration and loaders.
- The assumed 101 TTS voices; the project's Matcha model exposes only voice/speaker `0`.
- The upstream Matcha loader's `hifigan_v2.onnx`; P7A uses the locally benchmarked Vocos 22.05 kHz vocoder.
- Shared mutable audio accumulation and handler-wide STT stream state as a cross-request design; P7A keeps audio, text, PCM queue and cancellation state request-local.
- Converting model failures into an empty successful Transcript; P7A distinguishes a valid empty result from protocol, model, timeout and service errors.
- Logging full transcripts or synthesized text; P7A logs only request metadata, correlation IDs, timing and error categories.

The upstream Dockerfile is not a deployment template for P7A: it installs floating dependencies and API packages, contains optional GPU logic, and exposes both `10400` and `10500`. P7A Dockerfile checks/builds and Compose validation belong to GitHub Actions; no Docker build is part of P7Ab0.

## License and attribution status

At the pinned commit, the repository tree contains no `LICENSE` or `COPYING` file, and GitHub repository metadata reports no declared license. This record therefore does **not** assign MIT, Apache-2.0 or another license to the upstream source. The project owner explicitly approved use for personal, non-commercial experimentation. Keep the repository URL, exact commit and source-file attribution with adapted code, and do not describe the upstream as permissively licensed or treat this note as a redistribution grant.

## Model asset inventory at P7Ab0

P7Ab0 records existing files; it does not copy, download, relocate or commit model weights.

| Provider | Contract model/files | Current workspace evidence | Status for this batch |
|---|---|---|---|
| KWS | `sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20`, chunk-16/left-64 encoder/decoder/joiner, `tokens.txt`, `en.phone` | No matching KWS asset was found in the workspace during the P7Ab0 inventory | Missing; model preparation and hashes remain for P7Ab1/P7Ab2. |
| STT | Paraformer zh-small INT8, `model.int8.onnx`, `tokens.txt` | Present under `benchmarks/voice/stt/sherpa-onnx-paraformer-zh-small-2024-03-09/`; source and SHA-256 manifests exist under `benchmarks/voice/stt/` | Existing benchmark asset, not yet installed into the P7A runtime model directory. Matrix hashes: model `3ef6c19369b912f7caf3cef8e545c5ccd1a33d9d7ec792a46668dc41c4b229ec`; tokens `4b2d964e18b9cf139b473003b6698fb2ed9a2a5ec55b93daa677b28f578897aa`. |
| TTS | Matcha Baker acoustic model, lexicon/tokens and phone/date/number FSTs; `vocos-22khz-univ.onnx` | Present under `tts-benchmark-matcha-melo/models/`; source and SHA-256 manifests exist | Existing benchmark assets, not yet installed into the P7A runtime model directory. The matrix already records acoustic model `78a9fd17e9a6c20198dca4e69d18f941303f8ab39ec61dde04cfc7595262ddfd`, lexicon `38b886d46aefa50da6322a64d72fd595d5f4fae1051adb160d647541b1e0a4a2`, and Vocos `0574a135aa1db2de6e181050db2ec528496cacd4a4701fc5d7faf9f9804c0081`; tokens/FST hashes still need inclusion in the P7A manifest. |

The existing model benchmark files and matrix remain the source of truth for model provenance. P7Ab1 must create the complete runtime manifest and verify every required file before model loading. No weight binary belongs in Git.
