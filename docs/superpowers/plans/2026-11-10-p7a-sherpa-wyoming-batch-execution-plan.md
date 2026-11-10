# P7A Sherpa Wyoming — Batch Execution Plan

> 状态：批次已拆分，等待实施计划审阅；任何服务代码、镜像、Compose 或 NAS 配置均未在本计划任务中实现。
> 工作分支：`feature/p7a-sherpa-wyoming-service`
> 基线提交：`aeef5183fef17e53bafbdda0e55f7de2300a8fdd`
> 实施计划：[P7A Implementation Plan](2026-11-10-p7a-sherpa-wyoming-implementation-plan.md)
> 唯一服务合同：[P7A Sherpa Wyoming Contract Matrix](../specs/2026-11-10-p7a-sherpa-wyoming-contract-matrix.md)
> 补充业务合同：[STT/TTS end-to-end pipeline spec](../specs/2026-11-09-stt-tts-end-to-end-pipeline-spec.md)
> 日期：2026-11-10

本文定义 P7A 的逐批执行合同。每次只执行当前指定 Batch，并单独提交；不得将下游批次的实现混入当前工作。发生合同冲突时先更新合同/计划，不得通过降低验收标准绕过。

## 1. 分支、基线和权威顺序

- Base：P7A 合同矩阵所在的 `feature/p7a-sherpa-wyoming-service`；本计划起点为 `aeef518`。
- 当前实现分支保持 `feature/p7a-sherpa-wyoming-service`；全部批次完成前不切换 main、不 push、不 merge。
- 每批开始重新确认 branch、HEAD、working tree；当前工作区若有未提交改动，先识别归属，不覆盖或清理用户数据。
- 权威顺序：
  1. [P7A 合同矩阵](../specs/2026-11-10-p7a-sherpa-wyoming-contract-matrix.md)：三 Provider、模型、事件、资源、网络、隐私和 P7A 阶段验收的唯一服务合同。
  2. [P7A 实施计划](2026-11-10-p7a-sherpa-wyoming-implementation-plan.md)：模块边界、接口、文件职责和批次目标。
  3. [STT/TTS 端到端链路规格](../specs/2026-11-09-stt-tts-end-to-end-pipeline-spec.md)：HA STT/TTS、流式文本、音频回传业务时序。
  4. `README.md`：项目整体拓扑与 P7A → P5/P6 阶段关系。
  5. 固定上游 `ptbsare/sherpa-onnx-tts-stt@c307e6835a079157e71df28545f17d76bca1cbc2`、Sherpa-ONNX 2.0.1、Wyoming 1.10.2 和 HA Core 2026.11.0 源码：用于核对实际 API/事件生命周期，不取代项目合同。
- 上游来源和用户许可范围已经确认：个人实验、非商业用途允许直接复用；保留来源/commit/原有声明，不将上游标成未声明的许可证。只有具体文件或模块存在实质冲突时才调整对应模块。
- 当前仓库的 HA 测试环境为 Python 3.14；Sherpa 服务 runtime 固定 Python 3.11 系列。两套运行时分开验证，不为 Sherpa 改动 HA 既有环境。

## 2. 批次与依赖关系

| Batch | 内容 | 依赖 | 交付级别 |
|---|---|---|---|
| P7Ab0 | 上游来源、运行时版本、模型资产和本地验证前置核查 | 无 | 必须 |
| P7Ab1 | 配置、模型清单/哈希、模型加载骨架和 Python 3.11 测试环境 | P7Ab0 | 必须 |
| P7Ab2 | KWS 模型配置、关键词生成和 Wyoming Wake Provider | P7Ab1 | 必须 |
| P7Ab3 | Paraformer STT Provider | P7Ab1 | 必须 |
| P7Ab4 | Matcha + Vocos 非流式 TTS Provider | P7Ab1 | 必须 |
| P7Ab5 | 流式 TTS、callback PCM 队列、背压和取消 | P7Ab4 | 必须 |
| P7Ab6 | 单端口 Server、三 Provider Info、连接路由、并发和日志 | P7Ab2、P7Ab3、P7Ab5 | 必须 |
| P7Ab7 | Dockerfile、Compose、模型持久化、私网和健康检查 | P7Ab6 | 必须 |
| P7Ab8 | HA/NAS 最终验收、资源数据、P3 回归和阶段收尾 | P7Ab7 | 必须 |

```text
P7Ab0 → P7Ab1 ─┬→ P7Ab2 ─┐
                ├→ P7Ab3 ─┼→ P7Ab6 → P7Ab7 → P7Ab8
                └→ P7Ab4 → P7Ab5 ─┘
```

P7Ab2、P7Ab3、P7Ab4 在代码职责上可独立测试，但本工作区按一个批次一个提交串行执行；没有必要为了并行引入更多分支或协调层。

## 3. 全局实现和验证约定

### 3.1 固定运行边界

- Python 3.11 系列、Sherpa-ONNX 2.0.1、Wyoming 1.10.2、CPU provider。
- 一个容器、一个服务进程、一个 TCP 10400；同一个 Info 同时声明 wake/asr/tts。
- 不启动 FastAPI/OpenAI API，不开放 10500，不接 ESP32，不连接 AstrBot。
- 模型存储在持久卷 `/models/{kws,stt,tts}`；模型二进制不提交。
- 一个模型对象在未证明线程安全前串行；推理由有界执行入口承接，不能阻塞 asyncio event loop。
- KWS/STT/TTS 的请求状态和缓存独立；每类模型首期最多 1 个执行中任务 + 1 个等待任务，超出时明确失败，不无限排队。
- 非流式 TTS 结束为 AudioStop；流式 TTS 结束为 SynthesizeStopped；两者不混用。
- `supports_synthesize_streaming=true` 只能在 P7Ab5 的 C25–C30 验收通过后，在 P7Ab6 的最终 Info 中启用。

### 3.2 测试执行环境

- P7A Python 服务测试使用 Python 3.11 test target；不直接使用项目根目录 Python 3.14 的 HA .venv 安装 Sherpa。当前 RDM 开发机为 aarch64，Docker CLI、Compose 和 Buildx CLI v0.38.1 已安装，但 Docker socket（root:docker）对当前登录账号返回 permission denied，无法检查或使用 builder；未检测到 QEMU，也未发现 uv/Podman/Buildah。P7Ab0 必须先取得获准的 Python 3.11 测试环境及可访问的 linux/amd64 构建能力，不能把这两个条件当成已就绪。
- P7A 服务测试统一入口在 P7Ab1 建立：`./scripts/test-sherpa-wyoming.sh`。后续命令以该脚本为准，可将 pytest 参数透传到测试容器。
- HA/P3 测试继续用现有入口：`./scripts/test-ha.sh -q`。本地 HA Assist Pipeline 测试不连接生产 AstrBot，不触发真实 Tivoo 动作。
- 静态检查：Ruff check/format、Python compileall、runtime image 内 `pip check`、Compose config 和 `git diff --check`。
- 使用 fake Sherpa model 的测试用于协议、取消、并发和边界；真实模型 smoke 使用已校验模型文件和固定 WAV。Fake 测试不能代替真实模型 smoke，真实模型 smoke 也不能代替 HA 协议测试。
- 模型文件/hash 必须来自矩阵指定 release；测试样本来源和是否为 Tivoo 录音要明确标注。P7A 不做真实 INMP441 噪声/距离最终验收。
- 每批完成后记录命令、退出码、测试数量、RED/GREEN 证据、变更文件和提交 SHA；未运行的检查写 BLOCKED/DEFERRED，不允许写 PASS。

### 3.3 单批执行步骤

1. 阅读本计划当前 Batch、实施计划对应 Task 和矩阵相关章节。
2. 检查分支/HEAD/工作区；确认没有上批遗留变更。
3. 只实现本批允许的文件和行为。先写可观察行为测试并确认 RED。
4. 实现最小行为，运行 GREEN 和本批必要回归。
5. 检查本批文件范围、Ruff、compileall、依赖和 diff；必要时做独立 self-review。
6. 更新本地 SDD progress ledger，记录证据/未完成项。
7. 只 stage 本批文件，单独 commit；不 push/merge。
8. 下一批开始前重新读本计划及上批提交状态。

## 4. P7Ab0 — 上游来源、运行时和资产前置核查

**Purpose:** 复核已有合同和上游固定提交，确认直接复用代码、Python 3.11 容器环境、模型文件和真实测试入口。此批仅做前置核查和记录，不实现服务逻辑。

**Allowed files:**
- Create: `services/sherpa_wyoming/UPSTREAM.md`
- Create: `docs/superpowers/reports/2026-11-10-p7a-preflight-report.md`
- Update: `.superpowers/sdd/2026-11-10-p7a-sherpa-wyoming/progress.md`

**Tasks:**
- [ ] 对比当前 HEAD 与 P7A 合同矩阵提交，确认没有其他未提交文件；确认 README、STT/TTS spec、ESP32/HA spec 与矩阵引用关系仍有效。
- [ ] 从固定 commit 读取上游 `run.py`、`model_utils.py`、STT loader、TTS loader、Dockerfile，记录可直接复用的文件/函数。
- [ ] 明确复用清单：AsyncTcpServer/AsyncEventHandler、Describe/Info 和 Wyoming event parser、Paraformer loader 结构、Matcha loader 结构、模型下载/目录组织的可用部分。
- [ ] 明确移除/改造清单：FastAPI/uvicorn/API/10500、NVIDIA 自动探测、无版本依赖、动态 eval、错误的 101 voices、HiFi-GAN vocoder 默认、全局共享音频 buffer。
- [ ] 核对开发机架构、Docker daemon/socket 权限、Buildx/跨架构能力和可用 Python 3.11 运行环境。当前已知开发机为 aarch64，Docker socket 为 root:docker 且当前登录账号不在 docker 组；本批不自动更改用户组或 socket 权限。
- [ ] 通过用户授权的 Docker 访问或已有独立运行器建立 Python 3.11 测试环境；目标镜像需要 linux/amd64。开发机若继续为 aarch64，必须确认可用的 amd64 Buildx builder/仿真，或使用其他获准的 amd64 构建机；不把 NAS 当成日常测试/构建机。
- [ ] 在选定的 Python 3.11 环境验证 Sherpa-ONNX 2.0.1、Wyoming 1.10.2、CPU wheel 和 sherpa-onnx-cli text2token 可用；不改动现有 HA Python 3.14 环境。
- [ ] 盘点现有 Paraformer、Matcha、Vocos 文件，校验已知 SHA；列出 tokens/FST 缺失 hash 和 KWS 模型 release 待下载项。
- [ ] 记录上游仓库未声明 license/未发现 LICENSE 的事实，不添加虚假的 MIT/Apache 声明；不把该资料状态扩展成全仓库停止复用。
- [ ] 输出前置报告：准确的 runtime 测试入口、要复用的 upstream 文件、模型资产缺口和后续准备命令。

**Exit gate:**
- [ ] 固定上游 commit 与目标模块的复用边界有可复核记录。
- [ ] 有实际可用的 Python 3.11 测试运行器和 linux/amd64 构建路径；若 Docker 权限/运行器尚未解决，P7Ab0 保持 BLOCKED，不开始 P7Ab1。
- [ ] 不修改开发机用户组或 Docker socket 权限，不将日常 pytest/build 搬到 NAS。
- [ ] 模型资产缺口和后续准备命令已记录；本批没有创建服务实现代码。

**Commit:** `docs(p7a): record Sherpa implementation preflight`

## 5. P7Ab1 — 配置、模型清单与三模型加载骨架

**Purpose:** 建立 Python 3.11 服务包、配置对象、模型文件校验和统一 ModelBundle；此批不处理 Wyoming 请求事件，也不开放端口。

**Allowed files:**
- Create: `services/sherpa_wyoming/__init__.py`、`config.py`、`model_utils.py`、`models.py`、`providers/__init__.py`
- Create: `services/sherpa_wyoming/requirements.txt`、Python 3.11 Dockerfile scaffold、`MODEL_SOURCES.md`、`MODEL_SHA256SUMS`
- Create: `tests/services/sherpa_wyoming/conftest.py`、`test_config.py`、`test_models.py`
- Create: `scripts/test-sherpa-wyoming.sh`

**RED / GREEN tasks:**
- [ ] RED：`load_config` 缺少/空白 WAKE_WORD_PHRASE、非法端口、非法线程数、负阈值或错误队列值均失败；默认值逐项匹配实施计划。
- [ ] RED：每类必需模型文件缺失、hash 不符、模型实例化异常时 `load_models` 失败；不能返回只有部分 Provider 的 ModelBundle。
- [ ] RED：模型对象只加载一次；重复调用服务启动入口不应在每个请求重新加载模型。
- [ ] GREEN：实现 ServiceConfig 与 load_config；只使用配置中约定的字段和默认值。
- [ ] GREEN：复用/改造上游模型文件准备和 loader 结构；下载/解包工具与启动时加载分离；运行时不使用 eval。
- [ ] GREEN：建立 ModelBundle，包含 KeywordSpotter、OfflineRecognizer、OfflineTts；模型加载任一失败整体抛出有上下文的启动错误。
- [ ] GREEN：建立已获取模型的来源和 SHA 清单；校验 STT 两项已知 hash，补齐 Matcha tokens/phone/date/number FST 和 Vocos hash。
- [ ] GREEN：建立 Python 3.11 test target 与测试脚本；依赖解析后精确锁定 Sherpa-ONNX、Wyoming、NumPy 及运行所需的传递依赖；HA 根目录依赖不变。
- [ ] 执行配置与模型测试；检查 Docker build、Ruff、compileall、pip check。

**Exit gate:**
- [ ] 配置错误在启动前失败；三个模型缺一不可；没有网络监听。
- [ ] 真实模型路径/模型配置与矩阵一致；本批已获取的模型文件 hash 全部有来源记录。
- [ ] `./scripts/test-sherpa-wyoming.sh tests/services/sherpa_wyoming/test_config.py tests/services/sherpa_wyoming/test_models.py -v` 通过。
- [ ] 依赖只用于服务 Python 3.11 runtime，不改变现有 HA/P3 环境。

**Commit:** `feat(p7a): add runtime config and model loading`

## 6. P7Ab2 — KWS Wake Word Provider

**Purpose:** 完成独立 Wyoming Wake Provider，覆盖命中、未命中、EOF、错误及请求隔离。

**Allowed files:**
- Create: `services/sherpa_wyoming/providers/wake.py`
- Modify: KWS 部分的 `model_utils.py`、`MODEL_SOURCES.md`、`MODEL_SHA256SUMS`
- Create: `tests/services/sherpa_wyoming/test_wake.py`
- Test artifacts only: 本地/忽略的模型文件和 KWS WAV，不提交模型权重或无来源的音频。

**RED / GREEN tasks:**
- [ ] RED：Detect.names 指定 tivoo-wake 时启动本请求；names 缺省/为空时使用唯一配置模型；未声明模型 ID 返回 Wyoming Error。
- [ ] RED：AudioStart 仅接受 16 kHz/16-bit/mono；AudioChunk 严格顺序处理并保留时间戳。
- [ ] RED：Fake KeywordSpotter 命中时只发 Detection(name=tivoo-wake)，不发 Transcript；timestamp 是命中确认块时间。
- [ ] RED：正常 TCP EOF 且未命中时发送 NotDetected；已发送 Detection/Error 的请求 disconnect 时不得重复发送 NotDetected。
- [ ] RED：模型异常、错误采样格式、主动取消/断开正确返回 Error 或清理 Stream。
- [ ] GREEN：按矩阵固定 chunk-16/left-64 三个 ONNX 文件和 tokens/en.phone 加载 KeywordSpotter；CPU threads=1。
- [ ] GREEN：从 WAKE_WORD_PHRASE 通过 `sherpa-onnx-cli text2token --tokens ... --tokens-type phone+ppinyin --lexicon ...` 生成 keywords 文件；Info phrase 和实际文件配置一致。
- [ ] GREEN：在 Wyoming 1.10.2 disconnect() 收尾中处理 HA Core 2026.11.0 的 EOF 未命中语义；每连接一个独立 KWS Stream。
- [ ] 用 Fake KeywordSpotter 跑完整 RED/GREEN；再使用真实 KWS 模型、官方模型测试 WAV、与当前 WAKE_WORD_PHRASE 对应的自定义中文正样本 WAV 和负样本做实际识别 smoke，记录阈值起测值，不把单次样本写成最终准确率。

**Exit gate:**
- [ ] P7A-C09 至 C15 有测试证据。
- [ ] 未命中、命中、错误、取消四种路径互斥且能正确关闭连接。
- [ ] 单个请求 EOF 不污染其他连接；不通过 STT Transcript 做唤醒词过滤。

**Commit:** `feat(p7a): add Wyoming wake word provider`

## 7. P7Ab3 — Paraformer STT Provider

**Purpose:** 完成离线最终转写 Provider、AudioStop 解码、请求上限与错误分类。

**Allowed files:**
- Create: `services/sherpa_wyoming/providers/stt.py`
- Create: `tests/services/sherpa_wyoming/test_stt.py`

**RED / GREEN tasks:**
- [ ] RED：必须先收到 Transcribe 和有效 AudioStart；AudioChunk 按序追加；AudioStop 前不能发 Transcript。
- [ ] RED：AudioStop 触发一次 decode_stream，只返回一个最终 Transcript；不得每个 chunk 识别一次。
- [ ] RED：有效静音/无识别内容返回 Transcript(text="")；空输入、错误 PCM、事件顺序错误、模型异常/超时返回 Wyoming Error。
- [ ] RED：请求累计达到 300 秒或 9,600,000 bytes 时终止并 Error；之后的 chunk 不再追加。
- [ ] RED：第二个请求不能读到第一个请求音频；取消/断开清除 Stream、PCM 缓冲和任务。
- [ ] GREEN：复用 Paraformer zh-small OfflineRecognizer 与官方模型文件，保留 16 kHz S16LE mono 和 zh-CN/en-US 语言声明所需信息。
- [ ] GREEN：Transcribe.language 作为请求元数据，不用它切换模型；不在 STT 里运行 VAD/KWS。
- [ ] 使用 fake recognizer 验证事件与错误语义，再使用现有 benchmark WAV 复核识别结果和既有基准一致性。

**Exit gate:**
- [ ] P7A-C17 至 C22 全部有证据。
- [ ] 一轮音频只 decode 一次；空结果不等于异常；请求内存和处理时长上限生效。
- [ ] 没有增量 Transcript、第二套 endpoint 或音频跨请求拼接。

**Commit:** `feat(p7a): add Paraformer Wyoming STT provider`

## 8. P7Ab4 — Matcha + Vocos 非流式 TTS

**Purpose:** 先交付标准 Wyoming Synthesize 兼容，不在本批加入流式文本状态机。

**Allowed files:**
- Create/modify: `services/sherpa_wyoming/providers/tts.py`
- Modify: `services/sherpa_wyoming/models.py` 和 TTS 模型清单/hash
- Create: `tests/services/sherpa_wyoming/test_tts_nonstream.py`

**RED / GREEN tasks:**
- [ ] RED：voice 0 / zh-CN 的有效 Synthesize 返回一次 AudioStart、按顺序的 AudioChunk 和一个 AudioStop。
- [ ] RED：不支持 voice、空文本、模型失败返回 Wyoming Error，不伪造 AudioStop 或空成功音频。
- [ ] RED：AudioStart 与全部 AudioChunk 固定 22,050 Hz、16-bit、mono；payload 保持样本帧对齐。
- [ ] GREEN：复用上游 Matcha Baker loader，但明确加载 Vocos 22.05 kHz vocoder、lexicon/tokens 和 phone/date/number FST；不加载 HiFi-GAN。
- [ ] GREEN：OfflineTts 使用 sid=0、speed=1.0；非流式保持原始完整文本路径。
- [ ] GREEN：按项目测试资产补齐 TTS 所有实际加载文件 SHA；检查模型源、文件名和运行路径一致。
- [ ] Fake TTS 测试通过后，使用真实 Matcha/Vocos 生成 WAV，读取文件头/音频参数并实际试听一段，记录非流式生成耗时。

**Exit gate:**
- [ ] P7A-C23、C24 通过。
- [ ] 非流式输出由 HA Wyoming 接收器按 AudioStop 正常完成；只公布真实 voice 0。
- [ ] 本批不声明 TTS streaming 已可用。

**Commit:** `feat(p7a): add Matcha Vocos non-streaming TTS`

## 9. P7Ab5 — Wyoming 流式 TTS

**Purpose:** 在普通 Synthesize 路径已经稳定后，加入 HA Wyoming 2026.11.0 流式文本输入与 Sherpa callback PCM 输出。

**Allowed files:**
- Modify: `services/sherpa_wyoming/providers/tts.py`
- Create: `tests/services/sherpa_wyoming/test_tts_stream.py`

**RED / GREEN tasks:**
- [ ] RED：验证事件序列 SynthesizeStart → SynthesizeChunk* → 完整兼容 Synthesize → SynthesizeStop；兼容全文不能再次进入缓冲或产生第二次合成。
- [ ] RED：验证 。！？ 和 .!? 强句末切分；超过 80 个 Unicode 字符强制提交；收到 Stop flush 残余文本；拼接提交片段与原文严格一致。
- [ ] RED：每次流式请求恰好一个 AudioStart；所有 PCM 为 22,050 Hz/16-bit/mono；chunk ≤ 4 KiB 且 sample-frame aligned。
- [ ] RED：队列最多 128 KiB；慢消费者时 callback 有背压，不丢失、不重复、不乱序；处理完 Stop 后全部音频发送完成才发送 SynthesizeStopped。
- [ ] RED：断连、取消、模型错误、consumer 失败都停止后续生成；取消后不发迟到音频；错误路径不发送 SynthesizeStopped。
- [ ] GREEN：用 Fake OfflineTts callback 产生确定性 samples；生产/发送使用独立线程/async consumer；callback 复制临时 samples，分块入有界线程安全队列；callback 返回 1 继续生成、返回 0 停止生成。
- [ ] GREEN：实现有限时间的队列等待和取消检查；模型 callback 不直接执行 socket write；流式结束与非流式 AudioStop 完全分开。
- [ ] 运行 HA Core 2026.11.0 流式接收行为测试，确认首块可在后续文本到齐前发送，且不会等待完整答案后才输出。
- [ ] 使用真实 Matcha/Vocos 做一次短流和长文本测试，记录首块时间、队列水位和总耗时；资源压力/组合并发数据留 P7Ab8。

**Exit gate:**
- [ ] P7A-C25 至 C31 全部有测试证据。
- [ ] 无双重合成、无 PCM 丢失/乱序、队列始终有界。
- [ ] 正常流式结束只发 SynthesizeStopped；非流式仍只发 AudioStop。
- [ ] 提交前完整服务测试通过；streaming Info 标记留给 P7Ab6 启用。

**Commit:** `feat(p7a): add bounded streaming Wyoming TTS`

## 10. P7Ab6 — 单进程服务整合和三 Provider Info

**Purpose:** 将三个独立 Provider 接入一个连接级 Wyoming Handler 和一个 AsyncTcpServer，完成并发隔离、错误路由与日志。

**Allowed files:**
- Create/modify: `services/sherpa_wyoming/run.py`、`models.py`、必要的轻量执行器模块
- Create: `tests/services/sherpa_wyoming/test_runtime.py`、`test_server.py`
- Modify: 相应服务测试/Provider glue code

**RED / GREEN tasks:**
- [ ] RED：Describe 返回一份同时包含一个 installed WakeProgram、一个 AsrProgram、一个 TtsProgram 的 Info；WakeModel ID/phrase/languages、ASR languages=zh-CN/en-US 且 requires_external_vad=true / supports_transcript_streaming=false、TTS voice 0/zh-CN 且 supports_synthesize_streaming=true 全部核对。
- [ ] RED：单个服务进程只绑定 10400 一次；HA 对同一个 host/port Describe 可发现三种平台所需的 Info 元数据。
- [ ] RED：任一个模型加载失败，服务入口不创建/不启动 server；不存在部分 Provider 可用的半启动状态。
- [ ] RED：每个 TCP 连接独立 Handler 和请求状态；KWS、STT、TTS、多连接之间不共享 buffer/Stream/PCM queue。
- [ ] RED：模型阻塞推理不运行在 event loop；同一模型最多按设定并发；等待队列有限，队列满时返回可诊断错误。
- [ ] RED：Describe/Info 探测不会被长 TTS generate 阻塞；取消一个请求不终止其他连接。
- [ ] GREEN：复用上游 AsyncTcpServer/AsyncEventHandler；一个 Handler 依据首个请求事件路由 provider；删除上游 FastAPI/uvicorn/10500/API 路径。
- [ ] GREEN：建立模型级有界执行入口，默认内部线程 KWS=1、STT=2、TTS=1；未证明模型线程安全时同一模型实例串行。
- [ ] GREEN：所有模型完整加载并构造 Info 后才 bind；设置 Info.tts.supports_synthesize_streaming=true 的前提是 P7Ab5 的 C25–C30 测试全部通过。
- [ ] GREEN：增加允许字段的结构化日志和资源计数；敏感内容不进入日志。
- [ ] 以 fake models 启动 localhost TCP，运行 Describe、KWS、STT、TTS 全链协议测试，并检查单一 listener 和进程启动失败行为。

**Exit gate:**
- [ ] P7A-C01–C06、C32、C37 有证据。
- [ ] 单容器预期的单 Python process、一个 Wyoming TCP endpoint、一个 Info、三类 installed Provider 已形成可运行闭环。
- [ ] 为 P7Ab8 的 HA Assist Pipeline miss/hit 阶段门保留测试入口；本批只验收 Provider 协议和单服务路由，不提前声称 C16/C38 通过。
- [ ] P3 HTTP/SSE/session/ChatLog 代码未被改动。

**Commit:** `feat(p7a): integrate three providers in one Wyoming server`

## 11. P7Ab7 — Docker、Compose、持久化和私网健康检查

**Purpose:** 将已验证的单进程服务封装为 NAS amd64 CPU 容器，完成模型持久化与仅 HA 私网可达的部署配置。

**Allowed files:**
- Modify: `services/sherpa_wyoming/Dockerfile`、`requirements.txt`
- Create: `deploy/nas/compose/sherpa-wyoming.yml`
- Create: `deploy/nas/config/sherpa-wyoming/.env.example`、`keywords.raw.txt.example`
- Create: `deploy/nas/scripts/prepare-sherpa-wyoming-models.sh`、健康检查模块
- Create: `tests/services/sherpa_wyoming/test_healthcheck.py`、`test_compose.py`

**RED / GREEN tasks:**
- [ ] RED：Compose 只包含一个 sherpa-wyoming service；只 expose 内部 10400；没有 ports host mapping、10500、FastAPI 或其他 API。
- [ ] RED：Compose 使用 HA 已存在的 external Docker network；网络名由 `HA_DOCKER_NETWORK` 配置；不臆造 NAS network 名。
- [ ] RED：`/models/kws`、`/models/stt`、`/models/tts` 持久化挂载；容器重建后模型文件仍在。
- [ ] RED：healthcheck 通过本地 Wyoming Describe 读取 Info，并分别断言 wake/asr/tts 三项 installed；仅端口可连接但 Info 不完整时失败。
- [ ] GREEN：Dockerfile 基于 Python 3.11 slim amd64，依赖全部精确锁定，CPU-only；入口只运行单一服务进程。
- [ ] GREEN：模型准备脚本从官方 release/已知模型源下载缺失文件，验证 MODEL_SHA256SUMS；下载/校验失败非零退出，不覆盖已有有效资产。
- [ ] GREEN：.env.example 仅说明所需变量；真实 WAKE_WORD_PHRASE、HA_DOCKER_NETWORK、NAS 路径由部署时配置，不提交实际 .env、Token 或个人凭据。
- [ ] GREEN：Compose 不连接 AstrBot 或 ESP32，不暴露公网；模型和配置目录只读/可写属性按真实运行需要设置，不做过度加固。
- [ ] 在已授权且能构建 linux/amd64 的构建机 build/run Compose；优先具备 Docker 权限的开发机构建器或独立 amd64 builder。当前 aarch64 开发机只有在 Docker socket 权限解决且选定的 builder 实际支持 linux/amd64（或授权启用 QEMU/binfmt）后才能承担该任务；用 fake/已准备模型完成三 Provider healthcheck，检查进程数、监听端口、挂载路径和网络范围。

**Exit gate:**
- [ ] P7A-C07、C33、C34、C36 有完整测试证据。
- [ ] 只有一个服务、一个进程、一个监听端口；HA 私网内可达，宿主公网无端口映射。
- [ ] 模型持久化且 hash 校验生效；健康检查检查 Provider，不仅检查 TCP。

**Commit:** `feat(p7a): package Sherpa Wyoming container for NAS`

## 12. P7Ab8 — HA/NAS 集成验收和 P7A 阶段收尾

**Purpose:** 用真实 HA Wyoming integration 和 NAS 合并模型运行数据验收服务；只在全部 MUST 通过后关闭 P7A 并放行 P5/P6。

**Allowed files:**
- Create: `docs/superpowers/reports/2026-11-10-p7a-acceptance-report.md`
- Modify only for verified fixes: P7A tests/service code
- Modify only after all MUST pass: P7A matrix status and `README.md` phase status

**Tasks:**
- [ ] 在开发机运行完整 Python 3.11 服务测试、服务 Docker build、Compose config、Ruff、compileall、pip check；运行 HA 2026.11.0/P3 全套回归。
- [ ] 只对 NAS 执行必要操作：检查 HA Docker 网络、准备持久模型目录、下载/校验模型、部署一个 Compose service 和运行轻量 smoke；不在 NAS 跑 pytest/build/compile 或其他耗时开发测试。
- [ ] 在 HA 只创建一个 Wyoming Config Entry，host 指向 NAS 私网服务地址、port=10400；确认同一 Entry 下同时发现 wake_word、stt、tts Provider。
- [ ] 使用固定正/负 KWS 测试音频验证 Detection 与 NotDetected；确认 miss 不进入 STT/P3 Agent，hit 才进入 STT；真实 INMP441 误唤醒率/距离不在本批。
- [ ] 在 HA Assist Pipeline 中验证 STT 最终 Transcript 被既有 P3 Conversation Agent 接收；测试环境优先用本地/模拟 Agent，不将完整用户对话内容写入日志。
- [ ] 使用 Paraformer 官方样本验证 zh-CN/en-US 识别路径、有效静音空文本、无效/超时错误和请求隔离。
- [ ] 在 HA 分别验证非流式 TTS 与流式 TTS；检查 WAV/PCM 参数、句子顺序、首块时机、单 AudioStart、兼容 Synthesize 去重、SynthesizeStopped。
- [ ] 在 NAS 同一个容器/进程测量三模型总加载时间、常驻/峰值 RSS、CPU、KWS 实时处理 lag、STT RTF、TTS 首块时间/队列水位；与旧单模型基准分开报告。
- [ ] 验证缺失/损坏模型导致启动失败；容器重启时模型不重新下载；重启后 HA 三 Provider 恢复；健康检查能识别 Info 不完整。
- [ ] 检查日志无 PCM、完整 Transcript、TTS 整段文字、Token 或短时 URL 凭据；保留模型版本/哈希、错误类别和性能数据。
- [ ] 建立报告逐项追踪 P7A-C01 至 C44：C01–C39 MUST 每项给出 PASS/BLOCKED 和证据；C40–C43 保持 DEFERRED；C44 明确 N/A/禁止新增。
- [ ] 若任意 MUST BLOCKED，不更新 README 为 P7A 完成，不放行 P5/P6；把实际缺口和对应批次写入报告后停止。
- [ ] 仅全部 MUST 通过时，更新矩阵验收状态及 README 阶段状态；明确 P7A 已完成并允许进入 P5/P6，但不声称 P7 真实麦克风/设备播报完成。
- [ ] 最终运行：P7A Python 3.11 全套 tests、HA/P3 回归、Ruff check/format、compileall、pip check、Compose config、Markdown/link 校验、合同 ID 追踪、git diff --check。

**Exit gate:**
- [ ] 单个 HA Wyoming Config Entry 同时发现 KWS/STT/TTS。
- [ ] C01–C39 所有 MUST 都有可复现 PASS 证据，不以开发机 fake 测试代替 NAS 组合资源/HA 真正集成证据。
- [ ] 三模型组合 RSS/CPU/KWS lag/STT RTF/TTS 首块数据来自 NAS 同进程实测。
- [ ] C40–C43 明确延后，C44 不实现；不把 P7A 完成扩大成 P7/P8 完成。
- [ ] README/矩阵的阶段状态与最终报告一致。

**Commit:** `test(p7a): verify Sherpa Wyoming deployment and HA pipeline`

## 13. 合同 ID 主批次追踪

每个 MUST 合同有唯一主批次；后续端到端验收会复验，不表示重复实现。

| 合同 | 主批次 | 复验/备注 |
|---|---|---|
| P7A-C01 | P7Ab6 | P7Ab8 核对单进程/端口 |
| P7A-C02 | P7Ab6 | P7Ab8 在 HA 单 Entry 下复验 |
| P7A-C03 | P7Ab8 | 单一 Config Entry 实际发现 |
| P7A-C04 | P7Ab6 | Wake Info 与配置短语一致 |
| P7A-C05 | P7Ab6 | ASR Info 语言/VAD/streaming flags |
| P7A-C06 | P7Ab6 | 建立于 P7Ab5 流式验证之后 |
| P7A-C07 | P7Ab7 | 不发布 10500/host port |
| P7A-C08 | P7Ab1 | 固定 runtime dependencies |
| P7A-C09 | P7Ab2 | KWS release/chunk16/hash |
| P7A-C10 | P7Ab2 | text2token 和 phrase 一致性 |
| P7A-C11 | P7Ab2 | Detect.names |
| P7A-C12 | P7Ab2 | KWS PCM 规格/顺序/timestamp |
| P7A-C13 | P7Ab2 | Detection |
| P7A-C14 | P7Ab2 | EOF NotDetected |
| P7A-C15 | P7Ab2 | Error/cancel/Stream cleanup |
| P7A-C16 | P7Ab8 | HA WAKE_WORD miss/hit 阶段门 |
| P7A-C17 | P7Ab3 | Paraformer 模型/hash |
| P7A-C18 | P7Ab3 | Transcribe/AudioStart/Chunk/Stop |
| P7A-C19 | P7Ab3 | 一次 decode / final Transcript |
| P7A-C20 | P7Ab3 | 空结果与错误区分 |
| P7A-C21 | P7Ab3 | 300 秒/9,600,000 bytes/隔离 |
| P7A-C22 | P7Ab3 | external VAD 由 HA 负责 |
| P7A-C23 | P7Ab4 | Matcha/Vocos/FST/lexicon/hash |
| P7A-C24 | P7Ab4 | Synthesize/AudioStop |
| P7A-C25 | P7Ab5 | 流式事件和兼容 Synthesize 去重 |
| P7A-C26 | P7Ab5 | 强标点/80 字符分句/无损 |
| P7A-C27 | P7Ab5 | callback copy/异步发送 |
| P7A-C28 | P7Ab5 | 22.05 kHz PCM/单 AudioStart |
| P7A-C29 | P7Ab5 | 128 KiB queue/4 KiB chunk/backpressure |
| P7A-C30 | P7Ab5 | SynthesizeStopped |
| P7A-C31 | P7Ab5 | cancel/error/no late PCM |
| P7A-C32 | P7Ab6 | 请求隔离/有界 worker |
| P7A-C33 | P7Ab7 | 模型持久化/容器重建 |
| P7A-C34 | P7Ab7 | 完整模型启动/Describe healthcheck |
| P7A-C35 | P7Ab8 | NAS 同进程资源指标 |
| P7A-C36 | P7Ab7 | HA 私有网络/无 10500 |
| P7A-C37 | P7Ab6 | 日志隐私 |
| P7A-C38 | P7Ab8 | STT transcript → P3、KWS miss 不触发 Agent |
| P7A-C39 | P7Ab8 | P5/P6 阶段门 |
| P7A-C40 | P7 / DEFERRED | 实际麦克风、噪声、误唤醒/漏唤醒、距离 |
| P7A-C41 | P6/P7 / DEFERRED | ESP32 I2S/AFE/TCP 7778/Satellite |
| P7A-C42 | P6/P8 / DEFERRED | HTTP TTS Proxy、解码和 DAC 播放 |
| P7A-C43 | P5/P6/P10 / DEFERRED | 屏幕、SPP 和硬件并发 |
| P7A-C44 | N/A / 禁止新增 | 不直接连接 AstrBot、不持有 session_id |

## 14. 每批完成报告字段

每批更新 `.superpowers/sdd/2026-11-10-p7a-sherpa-wyoming/progress.md`，至少记载：

- Batch ID、开始时 branch/HEAD、结束 commit SHA。
- 本批允许/实际修改文件；确认没有提前修改下游批次。
- 每个行为测试的 RED 命令/失败点与 GREEN 命令/结果。
- Python 3.11 runtime、实际模型 smoke、HA/P3 回归、Ruff/compileall/pip check/Compose/diff 检查的结果。
- 模型文件版本、下载来源、SHA-256；只记录路径和哈希，不复制模型权重。
- 已通过合同 ID、BLOCKED/DEFERRED ID、下一批的明确输入。
- 是否执行独立 review；没有 reviewer/subagent 工具时记为 self-review，不得声称独立审核。
