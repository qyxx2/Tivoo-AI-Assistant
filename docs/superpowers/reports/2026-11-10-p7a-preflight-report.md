# P7A Preflight Report — P7Ab0

- Date: 2026-11-10
- Branch: `feature/p7a-sherpa-wyoming-service`
- Preflight base: `c018f3e92eeffb4546bcc67830f0f99a8bec36d6`
- Scope: pinned upstream reuse review, ARM64 Python 3.11 development environment and GitHub Actions amd64/Buildx bootstrap only.
- Service code, Docker image build, Compose deployment, NAS changes and hardware tests are outside this batch.

## 1. Source and project baseline

The batch started with a clean working tree at the P7A feature branch. The current HEAD follows the P7A contract matrix, implementation plan and batch plan. The README, STT/TTS end-to-end specification, ESP32/HA bidirectional design and model provenance references required by the matrix all exist in the working tree.

The fixed upstream source was cloned and inspected at `ptbsare/sherpa-onnx-tts-stt@c307e6835a079157e71df28545f17d76bca1cbc2` (2025-11-29). The exact reuse/adaptation/removal map, source files and license caveat are recorded in [`services/sherpa_wyoming/UPSTREAM.md`](../../../services/sherpa_wyoming/UPSTREAM.md).

Key findings:

- Reusable: Wyoming `AsyncTcpServer`/`AsyncEventHandler` lifecycle, Describe/Info and event parser patterns; Paraformer `OfflineRecognizer.from_paraformer` loader; Matcha `OfflineTts` loader structure and rule-FST wiring.
- Adapt: connection-level event dispatch, request-local audio/text/PCM state, explicit model paths and hash validation, Vocos vocoder, one installed voice, three Provider metadata and error/stream semantics.
- Exclude: FastAPI/Uvicorn/API/10500, NVIDIA probing and CUDA switching, floating Wyoming Git HEAD, dynamic `eval`, assumed 101 voices, HiFi-GAN default, unverified startup download and shared audio state.
- License: the pinned upstream has no LICENSE/COPYING file and GitHub reports no declared license. This report does not assign an open-source license. Retain provenance and attribution; usage remains the user's explicitly authorized personal, non-commercial experiment scope.

## 2. ARM64 development runtime

| Item | Verified value |
|---|---|
| Device architecture | `aarch64` |
| OS/kernel | Linux `4.19.113`, aarch64 |
| uv | `0.13.7` (`aarch64-unknown-linux-gnu`), installed in `/home/Gold/.local/bin` |
| Python runtime | `3.11.18`, installed by uv under `/home/Gold/.local/share/uv/python/` |
| Project selector | `.python-version` contains `3.11` |
| Dedicated environment | `/home/Gold/WorkSpace/Tivoo-AI-Assistant/.venv-sherpa` |
| Sherpa | `sherpa-onnx==2.0.1`, `sherpa-onnx-core==2.0.1` |
| Wyoming | `wyoming==1.10.2` |
| NumPy | `numpy==2.4.6` |
| CLI helper | `click==8.5.1` (needed by the installed `sherpa-onnx-cli` entry point) |

Verification performed on this ARM64 device:

- `uv python find 3.11` resolves the installed CPython 3.11.18 aarch64 interpreter.
- `.venv-sherpa/bin/python` imports `sherpa_onnx`, NumPy and Wyoming's `AsyncTcpServer`/`AsyncEventHandler`.
- `uv pip check --python .venv-sherpa/bin/python` reports: `Checked 5 packages`; `All installed packages are compatible`.
- `.venv-sherpa/bin/sherpa-onnx-cli --help` and `.venv-sherpa/bin/sherpa-onnx-cli text2token --help` both execute successfully.
- A real `OfflineRecognizer.from_paraformer(..., provider="cpu", num_threads=1)` was created from the existing Paraformer benchmark files. It decoded the existing 16 kHz mono 16-bit WAV sample successfully (89,784 samples; decode 0.131 s in this run). This is a loader/API smoke, not a recognition-accuracy or Tivoo-microphone acceptance result.
- The system Python remains `3.14.4`; the existing HA `.venv` was not replaced or modified. `.venv-sherpa/` is ignored by Git.

Resolved packages in `.venv-sherpa`: `click==8.5.1`, `numpy==2.4.6`, `sherpa-onnx==2.0.1`, `sherpa-onnx-core==2.0.1`, `wyoming==1.10.2`.

## 3. Model asset inventory

- KWS: no matching `sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20` model files were found. Download/preparation and SHA-256 capture remain for the appropriate later batches.
- STT: Paraformer zh-small INT8 model, tokens and official sample WAVs exist under `benchmarks/voice/stt/sherpa-onnx-paraformer-zh-small-2024-03-09/`. The matrix's model/tokens hashes and upstream source manifest are recorded in the existing STT benchmark directory.
- TTS: Matcha Baker model, lexicon/tokens/FSTs and the project-tested Vocos 22.05 kHz vocoder exist under `tts-benchmark-matcha-melo/models/`. Existing hashes cover the acoustic model, lexicon and vocoder; the P7A runtime manifest still needs hashes for all other files actually loaded.
- This preflight did not copy, download, relocate or commit any model weights. Benchmark assets are not yet the P7A `/models/{kws,stt,tts}` runtime layout.

## 4. GitHub Actions bootstrap

Repository: `qyxx2/Tivoo-AI-Assistant` (default branch `main`). GitHub Actions are enabled. The workflow is `.github/workflows/sherpa-wyoming-image.yml` and is configured for:

- push to `feature/p7a-sherpa-wyoming-service` when the workflow, Sherpa service subtree or the future Sherpa NAS Compose file changes;
- pull requests targeting `main` with the same path filter;
- manual `workflow_dispatch`.

The sole bootstrap job runs on GitHub-hosted `ubuntu-24.04`, asserts `x86_64` and `amd64`, initializes Buildx with `linux/amd64` using `docker/setup-buildx-action@v4.4.1` (Node 24 runtime), then inspects the builder and asserts that `linux/amd64` is advertised. Workflow permissions are only `contents: read`. It does not need a PAT, NAS secret or other repository secret. The reserved image destination is `ghcr.io/qyxx2/tivoo-sherpa-wyoming`.

**This batch intentionally does not build an image.** P7Ab0 has no service Dockerfile yet. Dockerfile/buildx check, linux/amd64 image build, image dependency/entrypoint smoke, Compose validation and `packages:write` publishing are enabled in their later planned batch (P7Ab1/P7Ab7 as specified). The first feature-branch run (42762304875) passed with the v3 action but emitted its Node 20 deprecation annotation. The workflow was updated to `docker/setup-buildx-action@v4.4.1`; the final run [42762539673](https://github.com/qyxx2/Tivoo-AI-Assistant/actions/runs/42762539673) on commit `f66526477a90fcd67c0b8407e5bd2025b489bf78` completed successfully, including both runner architecture and `linux/amd64` builder checks, in 12 seconds. The preceding v4.4.1 run [42762412996](https://github.com/qyxx2/Tivoo-AI-Assistant/actions/runs/42762412996) also passed.

## 5. Boundaries preserved

- Application development and code-level tests use ARM64 Ubuntu and `.venv-sherpa`.
- All Dockerfile validation, image builds, container smoke tests and Compose CLI checks use GitHub Actions on the amd64 runner.
- NAS only pulls and runs an image already built by GitHub CI in the future deployment batch.
- No local Docker build was run; Docker socket permissions were not changed.
- No NAS, production config, ESP32, microphone or hardware path was touched.
- No service implementation, dependencies file, Dockerfile, Compose file, KWS model download or P7Ab1 work was added.

## 6. Validation evidence

| Check | Result |
|---|---|
| Git branch/worktree baseline | PASS — expected feature branch, clean starting tree |
| Referenced architecture/spec/model docs | PASS — all required files exist |
| Fixed upstream source checkout | PASS — detached at the specified commit |
| ARM64 Python 3.11 runtime and isolated venv | PASS — CPython 3.11.18/aarch64 |
| Sherpa/Wyoming/NumPy imports and versions | PASS — exact contract versions |
| CPU Paraformer construction and sample decode | PASS — API smoke only |
| `sherpa-onnx-cli text2token --help` | PASS |
| uv dependency compatibility check | PASS — 5 packages, no conflicts |
| GitHub Actions workflow lint | PASS — actionlint 1.7.12, no findings |
| Existing HA/P3/P4 regression suite | PASS — 205 passed, 74 warnings, 16.49 s (Python 3.14 environment) |
| Existing STT and Matcha/Vocos asset SHA-256 checks | PASS — all 7 entries in the two existing manifests match (STT 2, TTS 5) |
| `.venv-sherpa/` ignore rule | PASS — `git check-ignore` resolves `.gitignore` rule |
| GitHub Actions amd64 Buildx job | PASS — [run 42762539673](https://github.com/qyxx2/Tivoo-AI-Assistant/actions/runs/42762539673), job 129651412307; CI ran on `f665264` (subsequent commits only corrected this report; workflow and service files are unchanged); `ubuntu-24.04` architecture and `linux/amd64` builder checks passed with action v4.4.1 (12 s) |
| ARM Docker build / NAS deployment | NOT RUN — explicitly outside this batch |

## 7. P7Ab0 outcome

P7Ab0 exit gate passed: the ARM64 Python 3.11 environment is usable, upstream reuse and model gaps are recorded, and the final GitHub Actions run confirms the native amd64 Buildx builder. No Docker image was built and no P7Ab1 work is included in this batch.
