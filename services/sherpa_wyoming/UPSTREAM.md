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
| KWS | `sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20`, chunk-16/left-64 encoder/decoder/joiner, `tokens.txt`, `en.phone` | Downloaded from the official release into the developer's local model cache; archive SHA-256 matched the GitHub Release API digest; five runtime asset hashes recorded in `MODEL_SHA256SUMS` | Assets prepared and checksummed in the P7Ab1 follow-up; weights remain outside Git. P7Ab2 owns actual Wake Provider behavior, custom phrase generation and request tests. |
| STT | Paraformer zh-small INT8, `model.int8.onnx`, `tokens.txt` | Original benchmark files remain under `benchmarks/voice/stt/`; unified local model root links to the same directory; both hashes are in `MODEL_SHA256SUMS` | Prepared for local P7A model loading without duplicating weights; no model binary belongs in Git. |
| TTS | Matcha Baker acoustic model, lexicon/tokens and phone/date/number FSTs; `vocos-22khz-univ.onnx` | Original assets remain under `tts-benchmark-matcha-melo/models/`; unified local model root links to Matcha/Vocos assets; all seven hashes are in `MODEL_SHA256SUMS` | Prepared for local P7A model loading without duplicating weights; no model binary belongs in Git. |

The existing model benchmark files and matrix remain the source of truth for STT/TTS provenance. The official KWS archive and its five selected runtime files are now separately checksum-verified in the local user cache and recorded in MODEL_SOURCES.md / MODEL_SHA256SUMS. The unified local model root resolves all 14 runtime assets; no weight binary belongs in Git.
