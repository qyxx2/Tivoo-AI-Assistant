# P7A Sherpa Wyoming 语音服务实施计划

> 状态：实施计划已拆分，待用户审阅后逐批执行；尚未开始 P7A 服务代码实现。
> 工作分支：`feature/p7a-sherpa-wyoming-service`
> 计划基线：`aeef5183fef17e53bafbdda0e55f7de2300a8fdd`
> 合同依据：[P7A Sherpa Wyoming 合同矩阵](../specs/2026-11-10-p7a-sherpa-wyoming-contract-matrix.md)
> 日期：2026-11-10

> **For agentic workers:** 每次只执行批次计划中的一个 Batch。优先使用 superpowers:executing-plans；若存在可用的独立 agent 且任务边界互不重叠，才考虑 superpowers:subagent-driven-development。每个新行为先使用 superpowers:test-driven-development，出现故障时使用 superpowers:systematic-debugging，提交前使用 superpowers:verification-before-completion。步骤使用 checkbox 跟踪。

**Goal:** 在 NAS 上交付一个独立的 Sherpa Wyoming 容器，由一个 Python 服务进程和一个 TCP 10400 入口同时向 HA 提供 KWS、STT、TTS 三种 Provider，并通过 HA 原生 Wyoming 集成完成发现和语音链路验收，作为 P5/P6 的前置服务。

**Architecture:** 复用固定上游 `ptbsare/sherpa-onnx-tts-stt@c307e6835a079157e71df28545f17d76bca1cbc2` 的 Wyoming 服务端骨架、STT/TTS 模型加载路径和可复用事件处理代码。保留一个 `AsyncTcpServer`；在其连接级 Handler 内根据 Wyoming 事件分派到独立的 Wake、STT、TTS Provider。配置、模型对象和推理执行器由服务级对象持有；音频流、句子缓冲、PCM 队列和取消状态始终属于单个请求。移除上游无关的 FastAPI、10500 端口、GPU 自动探测、浮动依赖和与本项目不一致的 HiFi-GAN 默认加载。

**Tech Stack:** ARM64 Ubuntu 原生 Python 3.11 开发/代码测试；Sherpa-ONNX 2.0.1、Wyoming 1.10.2、NumPy、asyncio；GitHub Actions ubuntu-24.04 amd64 runner 执行 Dockerfile 检查和 linux/amd64 镜像构建；Docker Compose 仅在 NAS 部署时使用。

**Spec:** [P7A 合同矩阵](../specs/2026-11-10-p7a-sherpa-wyoming-contract-matrix.md)；STT/TTS 行为补充依据为 [STT/TTS 端到端链路规格](../specs/2026-11-09-stt-tts-end-to-end-pipeline-spec.md)。

## 1. 全局约束

- 方案 B 已冻结：一个容器、一个 Python 服务进程、一个 Wyoming TCP 监听端口 10400，同时发布 wake、asr、tts 三类 installed Provider。
- 所有服务代码开发、pytest、Ruff、compileall、模型 API smoke 和代码级调试均在当前 ARM64 Ubuntu 开发机完成；不在 GitHub Actions 或 NAS 执行应用层 pytest。服务开发/测试使用独立 Python 3.11 aarch64 venv（例如 `.venv-sherpa`），不污染项目现有 Python 3.14 HA 测试环境。Sherpa-ONNX 2.0.1 提供 CPython 3.11 manylinux aarch64 wheel，可原生安装，不需要 Docker 运行服务单测。
- GitHub Actions 是唯一 Docker 构建/测试环境：使用 GitHub-hosted `ubuntu-24.04` amd64 runner，执行 Dockerfile/buildx 校验、linux/amd64 镜像构建、镜像内依赖/入口 smoke、Compose 配置检查和 GHCR 推送。ARM 开发机和 NAS 都不执行 docker build/buildx，也不做 Dockerfile 测试。
- 固定 Sherpa-ONNX 2.0.1、Wyoming 1.10.2；生产依赖及其解析后的传递依赖都必须锁定。不得在构建时安装 Wyoming git HEAD 或浮动版本。
- 只使用 CPU Execution Provider；不得自动探测 NVIDIA、自动切换 CUDA 或引入 GPU 依赖。
- 只监听 TCP 10400。不得启动/映射 FastAPI、OpenAI 兼容 API、10500 或其他服务端口；ESP32 不直接连接本容器。
- 三个模型在服务启动时分别加载一次。KWS、STT、TTS 任一模型、必要模型文件、关键词配置或模型校验失败时，进程启动失败且不得先开放一个不完整的监听端口。
- KWS 使用 `sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20` 的 chunk-16/left-64 文件组合；唤醒短语来自必填配置 `WAKE_WORD_PHRASE`，通过 Sherpa 官方 text2token 工具生成关键词文件。
- KWS 是 HA Assist Pipeline 的独立 WAKE_WORD Provider。未命中时不得进入 STT 或 P3 Conversation Agent；不得用 STT 转写后的字符串过滤替代 KWS。
- STT 使用 Paraformer zh-small INT8 2024-03-09，输入 16 kHz、mono、S16LE；AudioStop 后只执行一次离线解码并返回一个最终 Transcript。有效无文本与协议/推理错误必须区分。
- STT 每请求默认最多 300 秒 / 9,600,000 bytes；超限返回 Wyoming Error 并释放该请求状态。
- TTS 使用 Matcha Baker + 项目已实测的 Vocos 22,050 Hz 配置；不要复制上游 HiFi-GAN 默认。仅暴露 speaker/voice 0、zh-CN。
- 普通 TTS 使用 Synthesize → AudioStart/AudioChunk+ → AudioStop。流式 TTS 必须正确处理 HA 的重复兼容 Synthesize，PCM 22,050 Hz/16-bit/mono，每请求 128 KiB 有界队列、单 chunk 最大 4 KiB，背压不丢数据，最后发送 SynthesizeStopped。
- KWS/STT/TTS 的阻塞推理不能直接运行在 asyncio event loop；每类模型的并发入口及等待队列有界；首期按每模型 1 个执行中任务 + 最多 1 个等待任务，超出容量时快速返回可诊断错误。同一模型对象在没有线程安全证据前按请求串行执行。
- 所有请求级状态独立。不得共享全局音频 buffer、当前 STT stream、TTS 文本 buffer 或 PCM 队列。
- 模型权重保存在持久化挂载目录 `/models/{kws,stt,tts}`，不提交进 Git。模型来源和实际加载文件均有 SHA-256 清单。
- 日志只保留请求类型、关联 ID、耗时、错误类别、模型版本和资源指标；不记录 PCM、完整 Transcript、完整 TTS 回答、Token 或短时 URL 凭据。
- Wyoming 10400 仅供 HA 所在 Docker 私有网络访问；不发布公网，不建立到 AstrBot 或 ESP32 的连接。
- 优先直接复用固定上游已有实现；只剔除与合同冲突的代码并补足缺失行为。不得因单个上游模块不合适就拒绝整个上游，也不得重新编写 Wyoming 协议栈或 Sherpa 推理算法。
- P7A 只交付独立语音服务及 HA Provider 验收；真实 INMP441 收音/声学性能属于 P7，ESP32 音频传输属于 P6/P7，TTS 下载播放属于 P6/P8，SPP/屏幕控制属于 P5/P6。

## 2. 文件与模块规划

以下为目标文件职责。若上游复用代码的实际结构需要小幅调整，允许在保持边界的前提下调整文件名；不得借机扩张服务职责。

| 路径 | 职责 |
|---|---|
| `services/sherpa_wyoming/run.py` | 进程入口、一个 AsyncTcpServer、连接级 Wyoming Handler、事件路由；由上游 run.py 结构改造 |
| `services/sherpa_wyoming/config.py` | 环境变量解析、类型转换、默认值和启动前配置校验 |
| `services/sherpa_wyoming/model_utils.py` | 复用/调整上游模型文件准备、校验和加载辅助；启动阶段不做无校验的自动下载 |
| `services/sherpa_wyoming/models.py` | KWS/STT/TTS 模型对象加载、ModelBundle 和模型级执行资源 |
| `services/sherpa_wyoming/providers/wake.py` | KWS 请求状态、音频输入、Detection/NotDetected/Error 和 EOF 收尾 |
| `services/sherpa_wyoming/providers/stt.py` | Paraformer 请求状态、PCM 累计上限、最终 Transcript 和错误语义 |
| `services/sherpa_wyoming/providers/tts.py` | Matcha 非流式与流式请求、分句、callback、PCM 队列与结束语义 |
| `services/sherpa_wyoming/UPSTREAM.md` | 固定上游仓库、commit、直接复用/改动/删除的模块和许可材料现状 |
| `services/sherpa_wyoming/MODEL_SOURCES.md`、`MODEL_SHA256SUMS` | 模型来源、版本、实际加载文件清单和校验值 |
| `services/sherpa_wyoming/requirements.txt`、`requirements-dev.txt`、`Dockerfile` | 服务 runtime 和 ARM64 本地测试依赖；Dockerfile 由 GitHub CI 构建/检查 |
| `.github/workflows/sherpa-wyoming-image.yml` | 唯一容器 CI：amd64 Dockerfile check/build/smoke、Compose config 和 GHCR image 发布 |
| `.python-version`、`.venv-sherpa/` | 固定 ARM 开发测试 Python 3.11；独立虚拟环境，不提交环境目录 |
| `tests/services/sherpa_wyoming/` | 配置、模型、Provider 事件、请求隔离、运行时、健康检查测试 |
| `scripts/test-sherpa-wyoming.sh` | 在 ARM Ubuntu 的本地 Python 3.11 venv 运行服务代码测试；不使用 Docker，不污染 HA .venv |
| `deploy/nas/compose/sherpa-wyoming.yml` | 单容器 Compose，接入 HA 私有网络，仅内部暴露 10400 |
| `deploy/nas/config/sherpa-wyoming/` | 环境变量和关键词源文件模板，不含密钥或模型权重 |
| `deploy/nas/scripts/prepare-sherpa-wyoming-models.sh` | 模型首次准备、文件完整性检查和 SHA-256 校验 |
| `docs/superpowers/reports/2026-11-10-p7a-acceptance-report.md` | P7A 最终合同追踪、验证证据和仍然 DEFERRED 的设备范围 |

测试至少按以下职责拆分：`test_config.py`、`test_models.py`、`test_wake.py`、`test_stt.py`、`test_tts_nonstream.py`、`test_tts_stream.py`、`test_runtime.py`、`test_server.py`、`test_healthcheck.py`、`test_compose.py`。可以在实际代码规模较小时合并测试文件，不要求为每个类单独建文件。

## 3. 稳定接口和数据对象

后续批次以以下接口作为模块间约定；实现时不得在不同批次为同一对象引入不同字段或含义。

### 3.1 配置

`config.py` 提供：

- `ServiceConfig`：不可变配置对象。
- `load_config(environ: Mapping[str, str] | None = None) -> ServiceConfig`：解析配置并在启动前验证必填项和边界。
- 固定配置字段：`host`、`port`、`models_dir`、`wake_word_phrase`、`kws_num_threads`、`kws_score`、`kws_threshold`、`kws_num_trailing_blanks`、`stt_num_threads`、`stt_max_seconds`、`stt_max_bytes`、`tts_num_threads`、`tts_max_sentence_chars`、`tts_queue_bytes`、`tts_chunk_bytes`、`max_pending_per_model`。
- 首期默认值：host=`0.0.0.0`、port=`10400`、models_dir=`/models`、KWS threads=1/score=1.0/threshold=0.25/trailing_blanks=1、STT threads=2/max_seconds=300/max_bytes=9600000、TTS threads=1/max_sentence_chars=80/queue_bytes=131072/chunk_bytes=4096；每模型最多 1 个执行中任务和 1 个等待任务，超出时快速失败。
- `WAKE_WORD_PHRASE` 必须显式配置，拒绝空白值；不在代码里预设实际唤醒词。

### 3.2 模型对象

`models.py` 提供：

- `ModelBundle`：`keyword_spotter`、`stt_recognizer`、`tts_engine` 三个已初始化对象，以及按模型隔离的执行入口。
- `load_models(config: ServiceConfig) -> ModelBundle`：使用固定文件路径和 Sherpa 2.0.1 API 加载三种模型；任一失败整体失败。
- KWS loader 使用矩阵规定的 chunk-16/left-64 encoder/decoder/joiner/tokens/keywords 文件。
- STT loader 复用上游 Paraformer loader 的 `OfflineRecognizer.from_paraformer` 配置和模型文件。
- TTS loader 复用上游 Matcha loader 的构造方式，但 vocoder 必须指向项目 Vocos 文件，并加载 lexicon/tokens/FST/data/dict。
- 模型文件的下载/准备与运行时加载分开：启动只检查必需文件和 SHA-256，不在服务未监听时静默切换模型或在线重新下载。

### 3.3 服务与 Provider

`run.py` 提供：

- `build_wyoming_info(config: ServiceConfig) -> Info`：一份 Info 同时声明一个 WakeProgram/WakeModel、一个 AsrProgram/AsrModel、一个 TtsProgram；语言和 voice 严格按合同。
- `create_handler_factory(config, models, info)`：创建连接级 Handler 工厂。每个 TCP 连接独立实例化请求状态，不共享可变音频/文本 buffer。
- `run_server(config, models, info) -> None`：只启动一个 `AsyncTcpServer(config.host, config.port)`。
- `SherpaWyomingEventHandler.handle_event(event: Event) -> bool`：处理 Describe 并将 Detect、Transcribe、Synthesize/SynthesizeStart 等事件路由至 Provider；未知/顺序非法事件不得伪装成功。
- `SherpaWyomingEventHandler.disconnect() -> None`：连接 EOF/断开时进行 Provider 收尾。KWS 正常未命中时可以在此发送 NotDetected；已经发送 Detection/Error 的请求不得重复发送终止事件。

Provider 模块只负责各自请求状态和模型行为；Wyoming TCP 生命周期、Describe/Info 和写事件由连接级 Handler 统一管理。避免三份各自运行的 Server 或复制三套 event loop。

## 4. 实施批次总览

| Batch | 交付目标 | 依赖 | 主要合同 |
|---|---|---|---|
| P7Ab0 | 固定上游复用核查、Python 3.11 runtime 和验证入口确认 | 无 | 实施前置 |
| P7Ab1 | 配置、模型清单/校验和三模型加载骨架 | P7Ab0 | C08、C09 的资产前置、C17、C23 的资产前置、C33 |
| P7Ab2 | 独立 KWS Provider 和 EOF/未命中语义 | P7Ab1 | C09–C15 |
| P7Ab3 | Paraformer STT Provider | P7Ab1 | C17–C22 |
| P7Ab4 | Matcha+Vocos 非流式 TTS Provider | P7Ab1 | C23–C24 |
| P7Ab5 | 真正的 Wyoming 流式 TTS | P7Ab4 | C25–C31 |
| P7Ab6 | 三 Provider 单服务整合、Info、并发/隔离和可观测性 | P7Ab2、P7Ab3、P7Ab5 | C01–C06、C32、C37 |
| P7Ab7 | Python 3.11 镜像、Compose、模型准备和健康检查 | P7Ab6 | C07、C33、C34、C36 |
| P7Ab8 | HA/NAS 集成验收、组合资源测量和 P7A 收尾 | P7Ab7 | C02、C03、C16、C35、C38、C39；最终复核全部 MUST |

依赖图：

```text
P7Ab0 → P7Ab1 ─┬→ P7Ab2 ─┐
                ├→ P7Ab3 ─┼→ P7Ab6 → P7Ab7 → P7Ab8
                └→ P7Ab4 → P7Ab5 ─┘
```

KWS、STT、TTS 的 Provider 代码分别有独立测试边界；在同一工作区按批次串行提交，不并行修改共享入口。P7Ab5 必须等待非流式 TTS 已稳定，P7Ab6 必须等待三个 Provider 均有独立行为测试，P7Ab7 必须等待单进程服务已能运行。

## 5. 任务计划

### Task 0 — P7Ab0：复用前置和运行环境确认

**Purpose:** 复核上游复用并建立两条基础路径：ARM64 Ubuntu 的原生 Python 3.11 开发/代码测试环境，以及 GitHub Actions 的 amd64 Docker 构建基础设施。此批不实现服务逻辑。

**Files:**
- Create: `services/sherpa_wyoming/UPSTREAM.md`
- Create: `docs/superpowers/reports/2026-11-10-p7a-preflight-report.md`
- Create: `.github/workflows/sherpa-wyoming-image.yml`（CI foundation；实际 Dockerfile 构建从 P7Ab1 启用）
- Create: `.python-version`（3.11）
- Modify: `.gitignore`（忽略 `.venv-sherpa/`）
- Update: `.superpowers/sdd/2026-11-10-p7a-sherpa-wyoming/progress.md`

**Tasks:**
- [ ] 确认当前分支、基线 SHA、工作树和模型资产；核对 README、STT/TTS spec、ESP32/HA spec 的引用关系。
- [ ] 按固定上游 commit 核对 `run.py`、`model_utils.py`、Paraformer loader、Matcha loader、Dockerfile；记录直接复用、复制后修改和移除的部分。
- [ ] 明确保留 Wyoming AsyncTcpServer/AsyncEventHandler、事件类型、现有 STT/TTS loader 的可复用部分；移除 FastAPI/uvicorn/API/10500、GPU 自动切换、浮动依赖、动态 eval、错误的 101 voices、HiFi-GAN 默认和全局共享音频 buffer。
- [ ] 将服务代码开发与 Docker 构建职责分离：ARM64 Ubuntu 只负责 Python 代码开发/代码级测试；GitHub Actions 负责所有 Dockerfile 检查、容器构建和镜像 smoke；NAS 只 pull/run CI 已构建的镜像。
- [ ] 在 ARM64 Ubuntu 安装/准备 Python 3.11 原生解释器；优先使用 uv 管理该版本（`uv python install 3.11`），创建独立 `.venv-sherpa`。不复用 Python 3.14 的 HA .venv，也不为 Python 3.11 安装而启用 Docker。
- [ ] 在 ARM64 Python 3.11 环境验证 Sherpa-ONNX 2.0.1、Wyoming 1.10.2、CPU wheel 和 `sherpa-onnx-cli text2token` 可用；记录平台/解释器/包版本。Sherpa-ONNX 2.0.1 的 CPython 3.11 manylinux aarch64 wheel 已在 PyPI 发布。
- [ ] 创建 GitHub Actions workflow foundation：使用 GitHub-hosted `ubuntu-24.04` runner；workflow 断言 runner 为 x86_64/amd64，初始化 Buildx 并验证 linux/amd64 builder。Dockerfile 尚未建立时此批只验收 runner/Buildx，不构建服务镜像。
- [ ] workflow 触发条件覆盖 P7A feature branch 的 push、相关路径的 pull_request 和 workflow_dispatch；paths 至少包括 workflow、`services/sherpa_wyoming/**`、NAS Compose。默认只读 contents 权限；CI 不需要 NAS 凭据或个人 token。
- [ ] 明确 GHCR 包名 `ghcr.io/qyxx2/tivoo-sherpa-wyoming`。正式发布 job 在 P7Ab7 配置，仅使用 GitHub 自动提供的 GITHUB_TOKEN 和 packages:write；不把 PAT 或 NAS 凭据写入仓库。
- [ ] 在 UPSTREAM.md 记录固定上游 commit、复用文件及许可材料现状；列出模型资产缺口、已知 SHA 和来源。

**Exit gate:**
- [ ] 上游复用边界和模型资产缺口有可复核记录。
- [ ] ARM64 Ubuntu 已有独立 Python 3.11 venv，Sherpa-ONNX 2.0.1/Wyoming 1.10.2 可原生安装。
- [ ] GitHub Actions workflow foundation 已在远端 feature branch 触发成功；ubuntu-24.04 runner 确认原生 linux/amd64 Buildx builder 可用。
- [ ] 开发机 Docker socket 权限不再是前置条件；P7Ab0 不执行 Docker build，也不修改开发机 Docker 权限。

**Commit:** docs(p7a): record Sherpa implementation preflight

### Task 1 — P7Ab1：配置、模型资产和加载骨架

**Files:**
- Create: `services/sherpa_wyoming/config.py`、`model_utils.py`、`models.py`、`requirements.txt`、`requirements-dev.txt`、`MODEL_SOURCES.md`、`MODEL_SHA256SUMS`
- Create: `services/sherpa_wyoming/__init__.py`、`providers/__init__.py`、`Dockerfile` runtime/ci-smoke stages
- Create: `tests/services/sherpa_wyoming/test_config.py`、`test_models.py`、`conftest.py`

**Interfaces:**
- Provides: `ServiceConfig`、`load_config(environ=None)`、`ModelBundle`、`load_models(config)`。
- Consumes: P7Ab0 核实的 Sherpa 2.0.1 API、Wyoming 1.10.2 和固定上游加载实现。

**Tasks:**
- [ ] RED：验证必填 `WAKE_WORD_PHRASE`、host/port、数值范围、默认线程数和音频/队列上限；空短语、非法端口、负阈值和不合法上限必须拒绝。
- [ ] RED：验证缺失/损坏/哈希不匹配的任一必需模型文件使加载失败，不返回不完整 ModelBundle。
- [ ] 从上游可复用 loader 改造 STT/TTS 模型加载；增加 KWS loader 配置入口，但不在此批实现 KWS 请求事件。
- [ ] 建立 `ModelBundle`，固定包含 KeywordSpotter、OfflineRecognizer、OfflineTts；模型对象仅初始化一次。
- [ ] 计算并记录 STT 已知模型 hash；补齐 Matcha tokens、phone/date/number FST hash；记录 Vocos hash；对 KWS 同 release 资产登记文件名和待取得 hash 的准备步骤。
- [ ] 分离模型准备与运行时加载：下载/解包在准备工具执行，启动阶段只做存在性和校验后加载；不得使用动态 eval 加载配置代码。
- [ ] 锁定 Python 3.11 runtime 依赖及 ARM 本地开发测试依赖；在 `.venv-sherpa` 中通过 ARM64 wheel 安装 Sherpa-ONNX 2.0.1、Wyoming 1.10.2 和测试工具；不改变根目录 HA Python 3.14 环境。
- [ ] GREEN：执行配置、哈希校验、加载成功/失败测试；使用 fake 模型验证失败不会产出半成品对象。所有 pytest/Ruff/compileall 在 ARM Ubuntu 本地执行。
- [ ] 为 Dockerfile 建立 runtime 与 ci-smoke stage；更新 GitHub Actions，使 P7Ab1 起对 Dockerfile 执行 `docker buildx build --check`、linux/amd64 ci-smoke build 和镜像依赖导入 smoke。GitHub CI 不执行应用 pytest。

**Exit gate:** 配置边界和模型加载测试在 ARM64 Ubuntu 通过；本地 Python 3.11 环境可重复建立；GitHub CI 已实际完成 Dockerfile check、linux/amd64 ci-smoke image build 和依赖导入 smoke；服务尚未开放监听端口。

**Commit:** `feat(p7a): add runtime config and model loading`

### Task 2 — P7Ab2：KWS Wake Word Provider

**Files:**
- Create: `services/sherpa_wyoming/providers/wake.py`
- Modify: `services/sherpa_wyoming/model_utils.py`、`MODEL_SOURCES.md`、`MODEL_SHA256SUMS`（仅 KWS 资产）
- Create: `tests/services/sherpa_wyoming/test_wake.py`

**Interfaces:**
- Consumes: `ServiceConfig`、`ModelBundle.keyword_spotter`。
- Produces: KWS 请求状态及可供连接 Handler 调用的 Detect/音频输入/EOF 收尾行为。

**Tasks:**
- [ ] RED：覆盖 Detect.names 指定 `tivoo-wake`、names 缺省/为空时使用唯一配置模型、未声明 ID、AudioStart 格式、AudioChunk 顺序和 timestamp 传递。
- [ ] RED：覆盖命中时只返回 Detection、不返回 Transcript；正常 EOF 未命中返回 NotDetected 并结束；模型错误返回 Error。
- [ ] 使用上游/官方 KeywordSpotter API 建立每连接独立 Stream；按 16 kHz S16LE mono PCM 输入，执行模型所需 float32 归一化。
- [ ] 复用官方 `sherpa-onnx-cli text2token`，由 WAKE_WORD_PHRASE + tokens.txt + en.phone 生成 keywords 文件；Info phrase、模型名和生成文件保持一致。
- [ ] 正常未命中处理在 Wyoming 1.10.2 的 disconnect/EOF 生命周期中完成；用请求状态防止 Detection/Error 之后重复发送 NotDetected。
- [ ] 命中后立即发 Detection(name=`tivoo-wake`) 并结束请求；timestamp 只代表检测确认的输入块时间。
- [ ] 验证无命中、取消、断开均释放当前 Stream，不影响另一个连接的 KWS 请求。
- [ ] GREEN：fake KeywordSpotter 协议测试通过；使用真实模型、官方模型测试 WAV、与当前 WAKE_WORD_PHRASE 对应的自定义中文正样本 WAV 和负样本做模型 smoke，记录阈值起测参数和样本来源，不把它描述成 Tivoo 机内声学验收。

**Exit gate:** C09–C15 具备测试证据；未命中不会产生伪 Detection；HA EOF 语义已覆盖；P7A 尚未要求真实 Tivoo 麦克风测试。

**Commit:** `feat(p7a): add Wyoming wake word provider`

### Task 3 — P7Ab3：Paraformer STT Provider

**Files:**
- Create: `services/sherpa_wyoming/providers/stt.py`
- Create: `tests/services/sherpa_wyoming/test_stt.py`

**Interfaces:**
- Consumes: `ServiceConfig`、`ModelBundle.stt_recognizer`。
- Produces: 每请求独立的 STT 状态，以及 AudioStop 后的最终 Transcript 或 Wyoming Error。

**Tasks:**
- [ ] RED：覆盖 Transcribe → AudioStart → AudioChunk* → AudioStop，AudioStop 之前不输出 Transcript，结束后仅 decode 一次。
- [ ] RED：区分有效静音/无识别结果的 Transcript(text="") 与空输入、错误 PCM、非法事件顺序、模型异常、超时的 Error。
- [ ] RED：覆盖 300 秒/9,600,000 bytes 上限、超限即终止、两请求不串音频、取消/断开释放 Stream/buffer。
- [ ] 复用上游 Paraformer OfflineRecognizer Stream 路径；保持模型线程配置 2，输入 16 kHz、mono、S16LE，不新增 KWS 或第二套 VAD。
- [ ] Transcribe.language 作为请求元数据保留，不按语言切换模型；Info 后续声明 zh-CN/en-US。
- [ ] GREEN：测试固定假模型和音频格式转换；使用既有官方 WAV 检查实际 Paraformer 模型输出与已有基准一致。

**Exit gate:** C17–C22 通过；最终转写只有一个；空结果和错误语义可区分；输入内存严格有界。

**Commit:** `feat(p7a): add Paraformer Wyoming STT provider`

### Task 4 — P7Ab4：Matcha + Vocos 非流式 TTS

**Files:**
- Create/modify: `services/sherpa_wyoming/providers/tts.py`（先完成非流式路径）
- Modify: `services/sherpa_wyoming/models.py`、`MODEL_SOURCES.md`、`MODEL_SHA256SUMS`（TTS 配置核对）
- Create: `tests/services/sherpa_wyoming/test_tts_nonstream.py`

**Interfaces:**
- Consumes: `ServiceConfig`、`ModelBundle.tts_engine`。
- Produces: 只接受 voice 0 / zh-CN 的非流式 Synthesize 响应。

**Tasks:**
- [ ] RED：覆盖有效 Synthesize 生成一份 AudioStart、一个或多个 AudioChunk、一个 AudioStop；错误时不发送伪造 AudioStop。
- [ ] RED：拒绝不支持的 voice/speaker；空文本按矩阵返回 Error，不调用模型。
- [ ] 复用上游 Matcha loader；vocoder 必须是 Vocos 22.05 kHz，使用 lexicon、tokens、phone/date/number FST 和项目 benchmark 实测配置。
- [ ] 按 sid=0、speed=1.0 调用 OfflineTts；输出转换为 22,050 Hz、mono、S16LE，AudioChunk 保持样本帧对齐。
- [ ] 将 callback 能力留给下一批流式实现；本批非流式路径不声明 streaming 能力。
- [ ] GREEN：使用 Fake OfflineTts 覆盖错误/voice/事件顺序；真实模型生成音频并确认采样率、声道、位宽和可播放结果。

**Exit gate:** C23–C24 通过；HA 可接收非流式语音；声学模型/Vocos/FST/lexicon 与项目已有实测配置一致。

**Commit:** `feat(p7a): add Matcha Vocos non-streaming TTS`

### Task 5 — P7Ab5：流式 TTS 输入和 PCM 输出

**Files:**
- Modify: `services/sherpa_wyoming/providers/tts.py`
- Create: `tests/services/sherpa_wyoming/test_tts_stream.py`

**Interfaces:**
- Consumes: P7Ab4 的 OfflineTts 和非流式音频转换；Wyoming SynthesizeStart/Chunk/Stop 事件。
- Produces: 每个流式请求一条连续 AudioStart/AudioChunk 序列，以 SynthesizeStopped 结束。

**Tasks:**
- [ ] RED：按 HA Core 2026.11.0 真实顺序发送 SynthesizeStart、多个 SynthesizeChunk、完整兼容 Synthesize、SynthesizeStop；断言兼容完整 Synthesize 不会再次合成/追加文本。
- [ ] RED：覆盖中英文强句末标点、max_sentence_chars=80 长句回退、末尾残余文本 flush；拼接已提交句子必须与输入文本完全一致。
- [ ] RED：覆盖一个流仅一个 AudioStart、22,050 Hz/16-bit/mono、PCM chunk 最大 4 KiB 且帧对齐、队列最多 128 KiB。
- [ ] RED：覆盖队列满时生产受到背压、不丢块、不重排；SynthesizeStop 后全部 PCM 发送完才发 SynthesizeStopped。
- [ ] RED：覆盖客户端断开、主动取消、模型异常、队列消费者异常；取消后不再发送迟到 PCM。
- [ ] 将 Sherpa callback 的 samples 复制到独立缓冲，转换为 S16LE 后切分入有界线程安全队列；callback 返回 1 表示继续生成、返回 0 表示停止生成；callback 不直接网络写入。
- [ ] 生成与网络发送解耦：async 消费端按序发送；队列满时 callback 等待有界时间并检查取消状态，失败时结束当前请求。
- [ ] 只在流式事件路径发送 SynthesizeStopped；普通完整 Synthesize 继续由 P7Ab4 的 AudioStop 结束。
- [ ] GREEN：用确定性 Fake OfflineTts callback 驱动慢速 consumer，验证背压/顺序/取消；再以真实模型测首块输出，不把单次快照当最终 NAS 实测。

**Exit gate:** C25–C31 通过；流式和非流式结束标记没有混用；无 PCM 丢失/重复/无界累积；Info 的 streaming 声明仍由 P7Ab6 最终组合验证决定。

**Commit:** `feat(p7a): add bounded streaming Wyoming TTS`

### Task 6 — P7Ab6：单服务运行时整合

**Files:**
- Create/modify: `services/sherpa_wyoming/run.py`、`models.py`、必要的轻量 `execution.py`
- Create: `tests/services/sherpa_wyoming/test_runtime.py`、`test_server.py`

**Interfaces:**
- Consumes: `load_config`、`load_models`、三个 Provider、Wyoming 1.10.2 AsyncTcpServer。
- Produces: `build_wyoming_info(config) -> Info`、`create_handler_factory(...)`、`run_server(...)` 和可启动服务进程。

**Tasks:**
- [ ] RED：同一 Describe/Info 同时含一个 installed WakeProgram、AsrProgram、TtsProgram；WakeModel ID/phrase/languages 正确；ASR languages=zh-CN/en-US、requires_external_vad=true、supports_transcript_streaming=false；TTS 仅 voice 0/zh-CN 且 supports_synthesize_streaming=true。
- [ ] RED：单服务仅绑定一次 10400；一个 Wyoming 连接可处理 Describe，Provider 连接只路由到其所属 Provider。
- [ ] RED：任一模型加载失败时 AsyncTcpServer 不启动；Info 探测不会被长 TTS 推理阻塞。
- [ ] RED：多个连接的 KWS/STT/TTS 请求状态不共享；同一模型并发受限；等待队列容量有上限，超出时返回可诊断错误而不是无限排队。
- [ ] 复用 AsyncTcpServer 和 AsyncEventHandler，建立单一 Handler 路由；移除上游 FastAPI、uvicorn、api.py、ModelContainer 和 10500 启动路径。
- [ ] 用模型级 bounded worker/executor 承接阻塞推理，不在 event loop 直接运行 sherpa decode/generate；默认模型线程数 KWS=1、STT=2、TTS=1。
- [ ] 实现启动顺序：load_config → 校验模型资产 → load_models → build Info → bind 单一 Wyoming Server；不提供部分 Provider 的降级启动。
- [ ] 按合同记录 model load time、请求耗时、错误类别、KWS 处理滞后、STT RTF、TTS 首块/队列水位和同进程 RSS；不记录音频/完整文字。
- [ ] GREEN：使用 fake 模型启动真实 TCP 端口并完成 Describe、Wake、STT、TTS 协议集成；检查端口监听数量为一个。
- [ ] 为最终 HA/P3 集成验收保留可替换的 Agent 测试接缝；本批不将 C16/C38 标记为 PASS，KWS miss/hit 阶段门和 Transcript 到 P3 的最终验证留到 P7Ab8。

**Exit gate:** C01–C06、C32 有运行时/自动化证据；单进程、单端口、单 Info 可发现三 Provider；模型全加载前不监听；日志隐私满足 C37。HA Assist Pipeline 的 C16 阶段门在 P7Ab8 验收。

**Commit:** `feat(p7a): integrate three providers in one Wyoming server`

### Task 7 — P7Ab7：Docker 镜像、模型准备和 NAS Compose

**Files:**
- Modify: `services/sherpa_wyoming/Dockerfile`、`requirements.txt`
- Create: `deploy/nas/compose/sherpa-wyoming.yml`（只引用 GHCR image；不含 build:）
- Create: `deploy/nas/config/sherpa-wyoming/.env.example`、`keywords.raw.txt.example`
- Create: `deploy/nas/scripts/prepare-sherpa-wyoming-models.sh`、服务健康检查脚本/模块
- Create: `tests/services/sherpa_wyoming/test_healthcheck.py`、`test_compose.py`（YAML/Compose 语义测试在 ARM 本地运行；Docker Compose CLI 校验由 GitHub CI 执行）

**Interfaces:**
- Consumes: P7Ab6 可启动单进程服务；`/models/{kws,stt,tts}` 目录合同。
- Produces: 单服务 Compose 部署、持久化模型准备、Describe/Info 健康检查。

**Tasks:**
- [ ] RED：Compose 只包含一个 sherpa-wyoming service；使用 GHCR image tag，不包含本地 build:；不映射 host/public ports、不暴露 10500；只在 HA 私有网络内部 expose 10400。
- [ ] RED：模型目录持久化挂载；容器重建不重新下载模型；配置示例不含生产唤醒短语以外的秘密值/Token。
- [ ] RED：healthcheck 必须对 localhost:10400 发送 Wyoming Describe 并检查 wake/asr/tts 三个 installed Provider；仅 TCP connect 不能返回 healthy。
- [ ] 构建 Python 3.11 CPU-only 镜像；固定直接和传递依赖；不包含 FastAPI/uvicorn/OpenAI API；镜像入口只运行 run.py。
- [ ] 增加模型准备脚本：只下载缺少文件，按来源/版本解包；逐项校验 MODEL_SHA256SUMS，失败时以非零退出，不覆盖有效模型。
- [ ] KWS 关键词源文件从 `WAKE_WORD_PHRASE` 生成；生成文件与 Info phrase 必须一致；不要把实际 `.env` 或用户私有唤醒短语提交。
- [ ] Compose 使用外部 HA 网络变量（例如 `HA_DOCKER_NETWORK`）；具体 network 名在实际 NAS 执行时读取已有 HA 容器连接，不猜测或创建重复网络。
- [ ] GREEN：将最终 Dockerfile/buildx/容器 smoke/Compose config 全部交给 GitHub Actions 的 ubuntu-24.04 amd64 runner。CI 完成 `buildx --check`、`linux/amd64` 完整镜像 build、无模型条件下的依赖/入口 smoke、Compose config 校验；通过后使用 GITHUB_TOKEN 发布 `sha-<commit>` tag 到 GHCR。CI 失败不得发布 tag。
- [ ] workflow 在 pull_request 上只 build/test、不发布；feature branch push 在 Docker smoke 通过后发布 SHA tag，供 P7Ab8 测试；不发布 latest。无需自定义 GitHub Actions secret。
- [ ] 不在本批将服务部署到生产 NAS；最终部署与 NAS 资源验收由 P7Ab8 执行。

**Exit gate:** C07、C33、C34、C36 的镜像/Compose/健康测试通过；GitHub CI 产出可按 commit SHA 拉取的 linux/amd64 GHCR image；Compose 没有本地 build；模型可跨容器重建持久化。

**Commit:** `feat(p7a): package Sherpa Wyoming container for NAS`

### Task 8 — P7Ab8：HA/NAS 最终集成验收和收尾

**Files:**
- Create: `docs/superpowers/reports/2026-11-10-p7a-acceptance-report.md`
- Modify only after acceptance: P7A 合同矩阵验收状态、`README.md` 阶段状态及必要的交叉引用
- Modify: relevant integration tests only for discovered contract defects

**Interfaces:**
- Consumes: P7Ab7 可部署镜像/Compose 和现有 HA 2026.11.0、P3 Conversation Agent。
- Produces: C01–C39 MUST 的逐项证据和 P7A 阶段结论；C40–C43 继续标记 DEFERRED，C44 保持禁止新增。

**Tasks:**
- [ ] 在 ARM Ubuntu 开发机运行服务全套 Python 3.11 tests、真实模型 smoke、HA/P3 回归、Ruff 和 compileall；代码级测试不得移到 GitHub runner 或 NAS。Dockerfile/buildx/镜像 smoke/Compose config 结果从 GitHub Actions run 读取，不在 ARM 上重跑。
- [ ] 在 NAS 仅执行必要的模型准备、登录 GHCR、`docker compose pull`、Compose 启动和运行时冒烟；Compose 只 pull GitHub CI 已发布的 linux/amd64 image，严禁在 NAS 执行 build/buildx。沿用已存在的 HA Docker 私有网络，不修改无关容器、网络和配置。
- [ ] 在 HA 只添加一个 Wyoming host:10400 Config Entry；验证 wake_word、stt、tts 三个平台同时发现，模型、语言和 voice 信息正确。
- [ ] 用正/负测试音频验证 KWS hit/miss；miss 时不触发 STT/P3 Agent；hit 时进入 STT，并验证最终 Transcript 到达现有 P3 Conversation Agent。不得连接真实 AstrBot 做非必要对话或泄露内容。
- [ ] 使用既有 Paraformer 官方 WAV 检查中英文识别输出、空结果/错误区分和多请求隔离。
- [ ] 在 HA 中分别验证非流式 TTS 与流式 TTS；流式验证首句在后续文本发送完成前开始输出、兼容 Synthesize 不重复合成、单 AudioStart、SynthesizeStopped 结束。
- [ ] 在 NAS 同一个服务进程/容器内记录三模型总加载耗时、常驻/峰值 RSS、CPU、KWS 处理 lag、STT RTF、TTS 首块延迟和队列水位；不得用单模型 RSS 推算组合资源占用。
- [ ] 验证模型缺失/哈希错误时启动失败；容器重启后模型不重复下载、三个 Provider 恢复；健康检查确认全部 installed。
- [ ] 记录 HA Config Entry、端口、Docker 网络、模型版本/哈希和验收数据；日志检查不得包含 PCM、完整转写/TTS 正文或凭据。
- [ ] 逐项更新 P7A-C01–C39 的 PASS/BLOCKED 及证据链接；P7A 只有所有 MUST 均有通过证据才可标记完成。C40–C43 不因 P7A 完成而提前验收，C44 不实现。
- [ ] 只有 C01–C39 全部通过，才更新 README 将 P7A 状态记为完成并放行 P5/P6；若存在 BLOCKED，保留阶段状态并在报告列明，不得提前放行。
- [ ] 在 ARM Ubuntu 运行全套 Python 3.11 服务测试、HA/P3 回归、Ruff、compileall、pip check、Markdown/link 检查和 `git diff --check`。
- [ ] 从 GitHub Actions run 核对 Dockerfile buildx check、linux/amd64 image build/smoke、Compose config 和 GHCR 发布结果；不在 ARM 或 NAS 执行 Dockerfile/buildx/Compose CLI 容器测试。

**Exit gate:** 单个 HA Config Entry 可获得三类 Provider；服务与现有 P3 对话文本链路连接正确；所有 C01–C39 MUST 有证据；组合资源数据来自 NAS 上同进程实测；报告明确保留物理麦克风和 ESP32 后续职责。

**Commit:** `test(p7a): verify Sherpa Wyoming deployment and HA pipeline`

## 6. Review Focus

以下五类矩阵隐含的高风险行为必须在所属批次中设置测试，不能只依赖最终端到端冒烟：

1. **KWS EOF 和终止事件边界**：HA 通过 TCP EOF 结束音频；正常未命中才可发送 NotDetected，已发送 Detection/Error 后不得重复终止。由 P7Ab2 的 `test_wake.py` 覆盖。
2. **流式 TTS 的兼容事件去重和结束标记**：HA 发出的完整 Synthesize 是兼容重复事件；流式响应最终必须是 SynthesizeStopped，非流式仍是 AudioStop。由 P7Ab5 覆盖。
3. **TTS callback、背压和取消**：callback 的临时 samples 必须复制，有限队列不得丢块；断连后 callback 能停止，不能留下线程或迟到音频。由 P7Ab5 覆盖。
4. **STT 输入结束、容量和错误分类**：静音/有效无文本与空输入、错误格式、超时不能混为一谈；300 秒/9,600,000 bytes 上限必须在 AudioStop 前持续生效。由 P7Ab3 覆盖。
5. **单进程启动/资源与请求隔离**：任一模型加载失败不得开放半成品服务；多个 Provider 不共享可变 buffer，Describe 不被推理阻塞，等待队列有界。由 P7Ab1/P7Ab6/P7Ab8 覆盖。

## 7. 全局执行与提交规则

- 一个 Batch 一个执行任务、一个本地 commit；批次完成前不得提前修改下游批次功能。
- 每个新行为使用 TDD：先写测试、运行确认 RED，再实现最小变更、运行 GREEN；不能只在事后补通过测试。
- 优先复制/改造上游现有代码及本项目 benchmark loader；只有在其行为与矩阵冲突时才重构对应小模块。
- 所有 P7A 代码开发、代码级 pytest/Ruff/compileall 和模型 API smoke 在 ARM64 Ubuntu 的 Python 3.11 `.venv-sherpa` 执行；HA Core/P3 测试沿用现有 Python 3.14 环境。不得把服务代码级测试放进 Docker/GitHub Actions，也不能为 Sherpa runtime 改动 HA 测试依赖。
- 所有 Dockerfile check、docker build/buildx、容器 smoke、Compose CLI config 和 GHCR 镜像发布只在 GitHub Actions `ubuntu-24.04` amd64 runner 执行；ARM 开发机与 NAS 均不构建容器。
- 每批至少执行聚焦测试、Ruff、compileall 和 `git diff --check`；改动 Provider 协议或服务入口的批次还要运行全部 P7A 服务测试。
- P7Ab6 之后每批运行 P3 回归，至少覆盖 Chat API、SSE、session 和 ChatLog 现有测试；不修改 P3 合同。
- NAS 只进行必要模型准备、GHCR pull、部署和真实组合资源测量；不在 NAS 跑 pytest、镜像 build/buildx、Dockerfile 测试或代码编译。
- 每批记录基线 SHA、改动文件、RED/GREEN 结果、命令输出、模型文件来源/hash、提交 SHA、未解决事项。
- 发现矩阵与 HA Core/Wyoming/Sherpa 实际行为冲突时，先停止受影响批次并核实源码，必要时更新矩阵和计划后再继续，不用猜测绕过。
- 为触发 GitHub CI，每批本地提交后将当前 P7A feature branch push 到 origin；不 push main、不 merge、不改 main。若远端分支/Actions 权限异常，记录 CI BLOCKED，不用 ARM/NAS Docker build 代替。未经用户明确要求，不部署其它服务、不执行 P5/P6/P7/P8 工作。
- 若本轮没有独立 reviewer/subagent 能力，按实际情况做独立自审并记录限制；不得伪称外部 reviewer 已审查。

## 8. 合同覆盖与阶段边界

| 合同 | 主批次 | 说明 |
|---|---|---|
| C01–C06 | P7Ab6 | 单入口与三类 Provider Info；HA 实际发现由 P7Ab8 复验 |
| C07、C36 | P7Ab7 | 仅内部 10400、私有网络、无 10500 |
| C08 | P7Ab1 | 固定依赖和 Python 3.11 runtime |
| C09–C15 | P7Ab2 | KWS 模型、关键词、事件、EOF 和请求清理 |
| C16 | P7Ab8 | HA Pipeline 中 KWS miss/hit 阶段门 |
| C17–C22 | P7Ab3 | Paraformer 模型/输入、最终结果、错误、上限与 endpoint |
| C23–C24 | P7Ab4 | Matcha/Vocos 模型和非流式兼容 |
| C25–C31 | P7Ab5 | 流式输入、分句、callback、PCM、有界队列、结束与取消 |
| C32、C37 | P7Ab6 | 并发隔离、执行队列及日志隐私 |
| C33–C34 | P7Ab1/P7Ab7 | 模型持久化、启动失败和健康检查 |
| C35、C38–C39 | P7Ab8 | 组合资源、P3 回归和 P5/P6 阶段门 |
| C40–C43 | 不属于 P7A 实施批次 | 分别留给 P7、P6/P7、P6/P8、P5/P6/P10 |
| C44 | 禁止新增 | P7A 不直接调用 AstrBot、不持有 session_id、不提供 OpenAI API |

P7A 交付只意味着独立语音服务已经可供 HA 使用，不意味着 Tivoo 真机已能采音、唤醒、播放或控制屏幕。
