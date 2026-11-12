# P7A 验收报告 — P7Ab8 HA/NAS 集成验收

- 日期：2026-11-10
- 项目分支：`feature/p7a-sherpa-wyoming-service`
- P7Ab8 基线：`80e5888a1cad0a08811c034a630292274c808603`（P7Ab7）
- 当前 NAS 实际运行镜像：`ghcr.io/qyxx2/tivoo-sherpa-wyoming:sha-315df317d3934383fd5105686de6fa749866c4ad`
- 镜像 digest：`sha256:d08e61250aa08594dc813bbe5dac9ac32c76c524578e2cfda9ea56257c5a4a31`
- GitHub Actions：[run 42801034360 — success](https://github.com/qyxx2/Tivoo-AI-Assistant/actions/runs/42801034360)

## 1. 结论

**P7Ab8 验收已完成；P7A 阶段门 PASS，允许 P5/P6 将该 Sherpa Wyoming 服务作为稳定语音依赖。**

服务镜像、模型、单服务入口、三类 Wyoming Provider、生产 HA Config Flow/单 Entry/三个实体、KWS hit/miss、Paraformer、非流式/流式 TTS、Assist Pipeline 阶段门、P3 Conversation Agent 文本衔接，以及 NAS 同进程资源数据均有可复核证据。

阶段放行依据：

1. C36 按用户接受的边界 PASS：NAS host namespace 作为可信边界；Sherpa 使用独立 `internal=true`、`attachable=false` bridge，不发布 host/LAN/WAN 端口，不接共享网络或其它容器。NAS 本机进程仍可访问 Wyoming，这是已记录并接受的剩余风险。
2. 正式 `WAKE_WORD_PHRASE=大肥鱼` 已配置；关键词生成成功，真实 HA Wyoming Wake Word Provider 正样本返回 Detection、官方负样本返回 NotDetected。
3. 生产 NAS HA 已持久化唯一 Wyoming Config Entry，host/port 为 `172.23.0.2:10400`；同一 Entry 下 KWS、STT、TTS 三个实体已注册且未禁用。生产 HA Core 的实际 STT/TTS Provider 代码路径也已连接 NAS 服务并通过官方样本及普通/流式合成。

C01–C39 的 MUST 项全部 PASS。C40–C43 仍 DEFERRED，C44 仍 N/A/禁止新增。原有 C38 Pipeline 自动化阶段门使用本地 Mock SSE；2026-11-10 又补充完成生产 HA Assist Pipeline → 真实 AstrBot SSE → Sherpa TTS → HA TTS Proxy 的两轮 WAV 端到端验证，详见[补充报告](2026-11-10-ha-assist-astrbot-stt-tts-e2e-report.md)。P7A 完成不代表真实 Tivoo 麦克风、ESP32 音频传输或设备扬声器播放已验收。

## 2. 部署与环境

| 项目 | 结果 |
|---|---|
| NAS | Synology DS920，x86_64 |
| Docker / Compose | Docker 20.10.3；docker-compose 1.28.5 |
| HA | `ghcr.io/home-assistant/home-assistant:2026.11.0`，host 网络 |
| CI 镜像 | NAS pull 成功；实际镜像为 amd64/linux，digest 与 Actions 发布记录一致 |
| Wyoming 入口 | 容器内部 TCP 10400；无 host port mapping；无 10500/API 端口 |
| Compose CI | Actions 完成 amd64 build/smoke、Compose CLI config、GHCR SHA tag 发布，均 success |
| NAS 构建 | 未在 NAS 执行 Dockerfile/build/buildx/Compose CLI 构建或容器测试 |
| 部署目录 | `/volume1/docker/tivoo-sherpa-wyoming` |
| 服务网络 | `tivoo-sherpa-ha-private`，bridge、`internal=true`、`attachable=false`、`172.23.0.0/24`，仅接入 Sherpa 容器 |
HA 使用 host 网络、当前没有 HA bridge。Sherpa 使用独立 internal-only bridge，没有接入现有共享 `bridge`、AstrBot 或其他应用网络；该方法避免 LAN 端口映射和其他容器网络变更。host namespace 仍可访问它，不能证明只有 HA 进程具有访问权限；该剩余风险已由用户明确接受，按修订后的 C36 合同通过，不声称进程级隔离。

### 2.1 镜像与 CI

- 当前 NAS GHCR 镜像 tag：`sha-315df317d3934383fd5105686de6fa749866c4ad`。
- NAS 本地镜像架构：`amd64/linux`；当前 RepoDigest 为 `sha256:d08e61250aa08594dc813bbe5dac9ac32c76c524578e2cfda9ea56257c5a4a31`。
- GitHub Actions run [42801034360 — success](https://github.com/qyxx2/Tivoo-AI-Assistant/actions/runs/42801034360) 对当前镜像提交完成 Dockerfile check、Buildx linux/amd64、runtime image build、CI smoke image、Sherpa API/entrypoint 检查、Compose CLI config 和 GHCR SHA tag 发布；结论 success。
- NAS 只执行 pull、模型准备、Compose 启停和运行时验收，没有在 ARM Ubuntu 或 NAS 构建容器。

### 2.2 模型持久化和完整启动

- 14 个运行时模型文件逐项通过 `services/sherpa_wyoming/MODEL_SHA256SUMS` 校验。
- NAS 已有 Paraformer、Matcha Baker、Vocos 权重通过目录链接复用 `/volume1/docker/sherpa-onnx-test`，没有重复复制旧的约 1.5 GB 模型缓存。
- 缺少的 KWS runtime 文件从 ARM 开发缓存传入 NAS；模型归档、WAV 样本和模型权重没有加入 Git。
- 首次 NAS 启动：KWS 1.917 s、STT 2.966 s、TTS 5.757 s，总模型加载 13.609 s；Python 3.11.18、Sherpa-ONNX 2.0.1、Wyoming 1.10.2、CPU provider。
- 容器重启后：KWS 1.989 s、STT 2.822 s、TTS 5.021 s，总模型加载 13.011 s；健康检查恢复为 healthy，Describe/Info 确认 wake/asr/tts 全部 installed。
- 重启前后 14/14 模型 SHA-256 均为 OK；模型从持久化挂载加载，没有重新下载。
- P7Ab7 已验证模型缺失/哈希错误会使准备过程非零退出，且不会覆盖损坏文件；服务加载代码和现有服务测试覆盖完整模型加载失败时不开放半成品 listener。

## 3. HA / Wyoming / Assist Pipeline 实际联调

### 3.1 单一 Config Entry 和 Provider 发现

使用 HA Core 2026.11.0 实际 Wyoming Config Flow，连接运行中的 NAS 服务（测试通过 SSH 本地转发到 172.23.0.2:10400）。HA 发送 Describe 并获得完整 Info，创建一个 Wyoming Config Entry。一次 setup 后注册以下三个实体：

- `wake_word.sherpa_onnx_wake_word`
- `stt.sherpa_onnx_paraformer`
- `tts.sherpa_onnx_matcha_baker`

同一 Entry 下发现 wake_word、stt、tts 三个平台；Wake model ID 为 `tivoo-wake`，phrase 与服务配置一致；ASR 语言和 `requires_external_vad` 元数据正确；TTS 仅提供 zh-CN voice 0 并声明 streaming。Config Flow/实体测试结果：2 项 HA 临时验收测试中对应的独立 Config Flow 测试通过。初始自动化 Config Flow 用临时 HA 测试实例执行；生产 NAS HA 的唯一 Config Entry 后续由用户通过 UI 持久化创建，并在 §11 复核。
### 3.2 KWS → STT → P3 的 Assist Pipeline 阶段门

通过 HA Core 2026.11.0 真实 `assist_pipeline.async_pipeline_from_audio_stream`，使用实际 Wyoming Wake Word / STT Provider 和现有 P3 Conversation Agent；P3 的 HTTP/SSE 后端使用测试内本地模拟端点，没有访问生产 AstrBot。

- KWS miss：输入官方负样本 `zh_3.wav`，收到 WAKE_WORD start/end 后 pipeline 结束；没有 `STT_START`、没有 `INTENT_START`，本地 P3 请求数为 0。
- KWS hit：输入官方正样本 `zh_5.wav`，后接 0.25 秒静音和 Paraformer 官方语音指令样本；HA Pipeline 继续进入 STT，产生最终 Transcript，并触发既有 `conversation.astrbot` Agent。
- 本地模拟 P3 endpoint 收到一次请求，用户名映射和 streaming 参数符合现有 P3 合同，并通过 SSE 返回测试响应。
- 同一阶段门用例重复运行通过，避免将偶发网络/时序结果当作验收证据。
- 临时 HA Config Flow 与 Pipeline 两个用例结果：`2 passed, 7 warnings in 24.04s`；随后独立 Pipeline 回归 `1 passed, 6 warnings in 23.23s`。警告为现有 HA/aiohttp 兼容性提示。

### 3.3 Paraformer STT

- 使用 Paraformer zh-small INT8 2024-03-09 官方 WAV，通过 HA Wyoming Provider 真实调用。
- `0.wav`（zh-CN，5.033 秒）与项目既有基准转写一致；NAS 解码约 0.417–0.464 秒，RTF 约 0.083–0.092。
- `2-zh-en.wav`（en-US，8.100 秒）与项目基准一致；NAS 解码约 0.788–0.802 秒，RTF 约 0.097–0.099。
- 两个请求并发运行时返回互不串接的结果。有效静音 PCM 的服务级空结果/错误区分已有 P7Ab3 测试覆盖；1 秒纯静音样本在离线 Paraformer 实际推理中可能返回非空猜测文本，因此端点静音切分由 HA external VAD 负责，不能把离线模型对纯静音的输出当成唤醒或静音准确性证明。

### 3.4 Matcha/Vocos TTS

- 非流式经 HA Wyoming Provider 返回可解析 WAV：22,050 Hz、16-bit、mono。
- 流式测试先发送第一句，再暂停 4 秒才发送第二句；首个 PCM 在约 0.566 秒到达，早于第二句文本输入结束。
- 观测流式 PCM 约 122,334 bytes，队列峰值 93,234 bytes（小于 128 KiB 上限），HA 接收端以流式完成事件正常结束。
- 服务日志记录首块时间 0.566 s、队列峰值 93,234 bytes、流式音频 122,334 bytes；服务单测另覆盖 4 KiB chunk 上限、PCM 帧对齐、兼容 Synthesize 去重、AudioStart 单次输出、SynthesizeStopped、错误/取消和无迟到 PCM。

### 3.5 生产 HA Assist Pipeline → AstrBot → TTS Proxy 两轮端到端

- 使用 HA WebSocket `assist_pipeline/run` 驱动生产 HA Core 2026.11.0，临时 Pipeline 绑定 `stt.sherpa_onnx_paraformer`、`conversation.astrbot`、`tts.sherpa_onnx_matcha_baker`；真实 AstrBot HTTP/SSE 后端，无 Mock。
- 两轮 16 kHz/mono/PCM16 WAV 均获得最终 Paraformer Transcript，进入 AstrBot 并返回可见回复，再由 HA 调用 Matcha TTS；HA TTS Proxy 两轮均输出可下载 `audio/mpeg`。
- 两个 MP3 分别为 22,050 Hz mono，248,726 bytes / 22.970 s 与 193,039 bytes / 19.603 s，FFmpeg 全量解码均通过；HTTP 首块时间分别约 2.215 s、0.200 s（仅从发起 Proxy GET 后计时，不代表全链路首音延迟）。
- 第二轮复用第一轮 HA `conversation_id`；AstrBot 第二轮回复引用第一轮主题，HA 持久化 session 的 `last_activity_at` 被刷新。
- 测试 Pipeline 已删除，原有 preferred Pipeline 未改动。测试从 STT stage 开始，不包含本轮 KWS；真实麦克风、Satellite 和物理扬声器播放仍留在后续硬件验收。详细 transcript、会话和格式记录见[补充报告](2026-11-10-ha-assist-astrbot-stt-tts-e2e-report.md)。

## 4. NAS 同进程组合资源数据

以下数据全部来自 NAS 同一个容器、同一个进程加载 KWS + STT + TTS 后的实际 HA/Provider 请求，不使用多个单模型 RSS 推算组合内存。

| 指标 | NAS 实测 |
|---|---:|
| KWS / STT / TTS 首次加载 | 1.917 s / 2.966 s / 5.757 s |
| 三模型总加载时间 | 13.609 s |
| 同进程模型运行峰值 RSS | 374,276 KiB |
| docker stats 空闲内存 | 364.5 MiB |
| docker stats 请求期间峰值内存 | 380.4 MiB |
| docker stats 请求期间峰值 CPU | 75.58% |
| KWS 正样本处理（官方 1.43–1.54 s 音频） | 命中约 1.45–1.80 s wall time；模型计算约 0.12–0.18 s |
| KWS 负样本处理（8.03 s 音频） | 未命中；wall time 约 8.1–10.1 s，模型计算约 0.68–1.03 s |
| KWS processing lag | 观测约 -1.25 至 -1.42 s；没有持续追不上实时输入 |
| STT RTF | 官方中英样本约 0.086–0.099 |
| TTS 流式首 PCM | 约 0.566 s |
| TTS 流式队列峰值 | 93,234 bytes / 131,072 bytes |

重启后的第二次组合加载为 13.011 s；启动 RSS 约 356,976 KiB。不同阶段的 RSS 值受模型加载及运行时内存页状态影响，以上明确区分了启动 RSS、进程日志峰值和 Docker 容器内存采样。
## 5. P7A-C01 至 C44 逐项验收追踪

状态定义：PASS = 有本批或前序批次可复核证据；BLOCKED = 尚缺实际部署条件/验收证据；DEFERRED = 明确由后续阶段负责；N/A = 禁止或不适用。当前结果：C01–C39 全部 PASS；C40–C43 DEFERRED；C44 N/A/禁止新增。

| 合同 | 状态 | 证据/说明 |
|---|---|---|
| C01 | PASS | NAS Compose 只有一个 Sherpa service/进程，单一 Wyoming TCP 入口 10400。 |
| C02 | PASS | HA Core Config Flow 对 NAS 服务执行 Describe，收到完整 Info。 |
| C03 | PASS（生产 HA Config Entry） | 生产 HA 存储中恰有一个 Wyoming Entry（`01M72MYQF1GFKY64SR87ZPWMKA`），host=`172.23.0.2`、port=`10400`；三个实体均引用该 Entry，且均未禁用。 |
| C04 | PASS（生产 Info） | 生产 HA Core 收到 Wake Info：installed=true、ID tivoo-wake、phrase=大肥鱼、zh-CN/en-US；实际 Provider 正负样本通过。 |
| C05 | PASS | ASR Info 为 Paraformer zh-small、zh-CN/en-US、requires_external_vad=true，不声明 transcript streaming。 |
| C06 | PASS | Matcha/Vocos、单 voice 0 / zh-CN，且真实 HA 流式 TTS 消费通过。 |
| C07 | PASS | 仅容器内部 expose 10400，无 host port mapping、无 10500/API 端口。 |
| C08 | PASS | Python 3.11、Sherpa-ONNX 2.0.1、Wyoming 1.10.2、CPU provider、固定依赖。 |
| C09 | PASS | 官方 zh-en Zipformer 3M 2025-12-20 chunk16/left64 权重和哈希清单通过。 |
| C10 | PASS | 正式配置“大肥鱼”经 text2token 生成 `d à f éi y ú @大肥鱼`；NAS 容器启动后 Info phrase 与实际配置一致，HA Wake Word Provider 正负样本均通过。 |
| C11 | PASS | Detect(tivoo-wake) 真实 HA Provider 路径及不支持模型 ID 的服务测试通过。 |
| C12 | PASS | 16 kHz/16-bit/mono PCM、分块顺序和 timestamp 保留的 provider/HA 测试通过。 |
| C13 | PASS | 正样本返回 Detection(name=tivoo-wake)，无 Transcript 伪造。 |
| C14 | PASS | 负样本正常返回 NotDetected，HA Pipeline 随即结束 wake 阶段。 |
| C15 | PASS | 错误、取消和 request stream 清理的服务测试通过。 |
| C16 | PASS | HA Pipeline miss 不进入 STT/P3；hit 进入 STT。 |
| C17 | PASS | Paraformer zh-small 2024-03-09 model/tokens SHA-256 与清单一致。 |
| C18 | PASS | HA 真实 Transcribe/AudioStart/AudioChunk/AudioStop 请求返回最终结果。 |
| C19 | PASS | AudioStop 后仅返回一个最终 Transcript，无增量转写声明。 |
| C20 | PASS | 空输入/错误分类服务测试通过；静音 endpoint 仍由 HA VAD 提供。 |
| C21 | PASS | 300 秒/9,600,000 bytes 限制、请求隔离、取消和并发 STT 测试通过。 |
| C22 | PASS | HA Info 声明 external VAD；HA Core 实际 Pipeline 使用其 VAD 职责边界。 |
| C23 | PASS | Matcha Baker + Vocos 22.05 kHz、FST/lexicon/tokens 及 SHA-256 验证通过。 |
| C24 | PASS | HA 实际非流式调用接收有效 22.05 kHz/16-bit/mono WAV。 |
| C25 | PASS | 流式事件顺序与末尾兼容 Synthesize 去重通过 HA Core 实际协议测试。 |
| C26 | PASS | 中英文句末标点、80 字符回退、原文顺序和尾句 flush 测试通过。 |
| C27 | PASS | Sherpa callback PCM 复制、转换、异步发送路径测试通过。 |
| C28 | PASS | 流式响应单 AudioStart，22,050 Hz/16-bit/mono，块帧对齐。 |
| C29 | PASS | 128 KiB 有界队列、4 KiB chunk 和背压测试通过；NAS 观测峰值 93,234 bytes。 |
| C30 | PASS | 流式结束使用 SynthesizeStopped；非流式仍使用 AudioStop。 |
| C31 | PASS | stream cancel/error/disconnect 清理及无迟到 PCM 测试通过。 |
| C32 | PASS | KWS/STT/TTS 单模型有界 worker、请求状态隔离和并发服务测试通过。 |
| C33 | PASS | NAS 模型 bind mounts 持久化；容器重启后 14/14 SHA-256 再次通过。 |
| C34 | PASS | 完整模型加载后 Describe/Info healthcheck 检查三 Provider installed；容器重启后 healthy。 |
| C35 | PASS | NAS 同进程加载、RSS/CPU、KWS lag、STT RTF、TTS 首块和队列数据见第 4 节。 |
| C36 | PASS（用户接受的边界） | 独立 internal-only、不可 attach bridge；无 host port mapping；仅 Sherpa 容器接入；Docker isolation rules 阻断其它转发网络。接受 NAS host 进程可访问这一剩余风险。 |
| C37 | PASS | 服务日志未记录 PCM、完整 transcript/TTS 正文、token 或短时 URL 凭据；只记录耗时、字节数、错误类别。 |
| C38 | PASS（Mock 阶段门 + 生产 E2E） | 既有 KWS hit/miss 自动化阶段门使用 Mock SSE；另有生产 HA Pipeline 从 STT 起始，经 Paraformer、真实 `conversation.astrbot` HTTP/SSE、Matcha TTS 和 HA TTS Proxy 完成两轮连续对话，音频全量解码通过，详见 §3.5 和补充报告。 |
| C39 | PASS | C01–C38 MUST 均有 PASS 证据；生产 HA 已保存唯一 Wyoming Entry 并注册同 Entry 下 KWS/STT/TTS 三实体；P7A 服务可作为 P5/P6 的稳定语音依赖。 |
| C40 | DEFERRED | 实际 INMP441 安装位置、噪声、误唤醒/漏唤醒和距离由 P7 验收。 |
| C41 | P6 部分 PASS / P7 DEFERRED | P6 已完成 TCP 7778 MIC 消息协议及 HA 有界 session dispatch；ESP32 I²S RX、AFE/VAD、真实 MIC_PCM producer 和 Assist Satellite 音频会话由 P7 验收。 |
| C42 | P6 部分 PASS / P8 DEFERRED | §3.5 已验证生产 HA TTS Proxy URL HTTP GET 返回 MP3 且 FFmpeg 全量解码通过；P6 已完成 ESP32 HTTP 流式资源获取，解码、PCM 缓冲、I²S DAC/AUX 和 TTS_STATE 由 P8 验收。 |
| C43 | P5/P6 部分 PASS / P10 DEFERRED | P5/P6 已完成屏幕/SPP 命令和双向通信基础；长时间屏幕/SPP/Wi-Fi/音频硬件并发由 P10 验收，屏幕视觉帧连续性仍需实测。 |
| C44 | N/A（禁止新增） | P7A 不直连 AstrBot、不持有 session_id、不提供 OpenAI API。 |

## 6. ARM64 开发机组合模型 Smoke 与代码级验证

使用 Python 3.11 `.venv-sherpa`，在 ARM64 Ubuntu 中以同一个 ModelBundle 一次加载三模型，真实调用 provider：

- 14 个模型 runtime 文件校验通过；组合加载耗时 5.344 s。
- KWS 官方正样本 Detection、官方负样本 NotDetected。
- Paraformer 官方 `0.wav` 返回非空 28 字符 Transcript，decode 0.109 s。
- Matcha/Vocos 真实合成输出 22,050 Hz、52,960 bytes PCM，generation 0.340 s。
### 6.1 最终自动化验证

| 验证 | 命令/结果 |
|---|---|
| Sherpa 服务全量测试 | `./scripts/test-sherpa-wyoming.sh tests/services/sherpa_wyoming -q` → **128 passed, 1 warning in 1.73s** |
| P3 Conversation Agent 回归 | `./scripts/test-ha.sh tests/homeassistant/custom_components/astrbot -q` → **92 passed, 63 warnings in 7.01s** |
| Ruff | `ruff check services/sherpa_wyoming tests/services/sherpa_wyoming` → All checks passed |
| Ruff format | `ruff format --check services/sherpa_wyoming tests/services/sherpa_wyoming` → 24 files already formatted |
| Python compile | Python 3.11 `compileall` for service and service tests → passed |
| Runtime dependencies | `uv pip check --python .venv-sherpa/bin/python` → 14 packages compatible |
| Model preparation shell | `bash -n deploy/nas/scripts/prepare-sherpa-wyoming-models.sh` → passed |
| Diff whitespace | `git diff --check` → passed |

唯一 Sherpa 警告是已知 Wyoming `audioop` 弃用提醒；HA/P3 警告为既有 Home Assistant/aiohttp 兼容性/Deprecation 警告，本批没有修改 P3 代码或 Sherpa runtime 依赖。

## 7. 阶段阻塞、裁定和后续边界

### 7.1 裁定：接受 HA host 网络下的 NAS host 信任边界

HA 现有容器使用 host 网络，没有 HA 专属 Docker bridge。按用户明确接受的范围，Sherpa 使用独立 `internal=true`、`attachable=false` bridge；只有 Sherpa 容器接入，Compose 无 `ports`，`docker inspect .NetworkSettings.Ports` 为 `{}`，`docker port` 无输出。没有连接共享 bridge、其它业务容器、ESP32 或 LAN/WAN 入口。

NAS 实际 `DOCKER-ISOLATION-STAGE-1` 规则会 DROP 从非 `172.23.0.0/24` 来源转发进入此 bridge 的流量；HA host 通过 NAS host namespace 路由访问 `172.23.0.2:10400`。NAS host 上其它本机进程同样可以访问容器 IP，这是用户接受的剩余风险。按修订后的合同范围，C36 标记 PASS，不声称进程级 HA 身份隔离。

**错误代价：** 若 NAS host 上出现不可信本机代码/用户，Wyoming 端口没有应用层鉴权，可能被其直接访问；此时应重新评估 host 信任边界，或增加隔离/认证，而不是把当前 internal bridge 当成进程级 ACL。

### 7.2 正式唤醒词配置和模型验证

用户已正式确定 `WAKE_WORD_PHRASE=大肥鱼`。NAS active `.env` 使用该短语（文件权限 600，不进入 Git）；启动时自动经 `sherpa-onnx-cli text2token --tokens-type phone+ppinyin` 生成关键词。生成文件为 `d à f éi y ú @大肥鱼`。使用 Matcha 生成短语语音并追加 1 秒静音后，KWS 正样本在实际 HA Core Wake Word Provider 路径返回 `Detection(tivoo-wake, 大肥鱼)`；官方负样本 `zh_3.wav` 返回 `NotDetected`。这不是 Tivoo 实际麦克风的误唤醒率/距离验收，仍留在 P7。

### 7.3 生产 HA Config Entry 与 Provider 可用性

生产 NAS HA Core（2026.11.0）的 `/config/.storage/core.config_entries` 中现有且仅有一个 `domain=wyoming` 的 Entry：`01M72MYQF1GFKY64SR87ZPWMKA`，名称 `Sherpa ONNX Paraformer`，host=`172.23.0.2`、port=`10400`。`core.entity_registry` 中三个实体 `wake_word.sherpa_onnx_wake_word`、`stt.sherpa_onnx_paraformer`、`tts.sherpa_onnx_matcha_baker` 均引用该 Entry，`disabled_by=null`、`hidden_by=null`。用户已确认 HA UI 显示三实体注册且连接。

本次在生产 HA 容器中调用 HA Core 2026.11.0 的实际 `WyomingSttProvider` 和 `WyomingTtsProvider` 类，连接同一 NAS `172.23.0.2:10400`：官方中文和中英样本均返回成功 Transcript；普通 TTS 返回有效 22.05 kHz/16-bit/mono WAV；流式 TTS 产生 44-byte WAV stream header、首块 PCM 约 0.643 s 到达并正常结束。详细测试记录见 §11。

C38 原有自动化阶段门仍使用本地 Mock SSE，以隔离验证 KWS hit/miss 对 P3 Agent 的触发条件；随后已补做真实生产 E2E：HA Assist Pipeline 的最终 STT 文本经生产 P3 Conversation Agent 进入 AstrBot，真实 SSE 回复再经 Sherpa TTS 和 HA TTS Proxy 输出，详见 §3.5 / [补充报告](2026-11-10-ha-assist-astrbot-stt-tts-e2e-report.md)。

### 7.4 明确不属于 P7Ab8 / P7A 完成的内容

- 后续阶段复验：C40 由 P7 验收；C41 的 P6 通信部分已完成、P7 物理麦克风/Satellite 部分待验收；C42 的 P6 HTTP 获取部分已完成、P8 解码/播放部分待验收；C43 的 P5/P6 通信路径已完成、P10 长时间硬件并发仍待验收。
- C44 继续 N/A / 禁止新增：P7A 不接入 AstrBot API、不持有 P3 session_id、不暴露 OpenAI API。
- 本次阶段收尾更新 P7A 验收记录、合同状态、实施/批次计划追踪和 README 阶段标记；没有修改 P3 合同、AstrBot 或 ESP32 实现。P5/P6 现在具备开始依赖该服务的前置条件，但其自身批次尚未因此自动完成。

## 8. 清理与当前部署状态

- NAS Sherpa Compose 容器当前持续运行：`compose_sherpa-wyoming_1`，`restart=unless-stopped`，health=`healthy`。
- active `.env` 位于 NAS 部署目录，权限 600；`WAKE_WORD_PHRASE=大肥鱼`。该文件不在 Git 中。
- 模型权重保留在 NAS 持久化目录；本次准备脚本确认 14/14 文件 SHA-256 匹配；容器启动时没有重复下载模型。
- GHCR 镜像仍保留在 NAS Docker image cache，部署使用 CI SHA tag，不在 NAS 构建镜像。
- `tivoo-sherpa-ha-private` 网络目前 internal=true、attachable=false，仅 Sherpa 容器接入；NAS host 通过 `172.23.0.2:10400` 可达。`docker port` 为空，没有 host port mapping。
- 开发机和 HA 容器的临时测试 WAV/Python 脚本已清理；临时 SSH 隧道已关闭。
- 生产 HA 已有且仅有一个 Wyoming Config Entry，持久化 host=`172.23.0.2`、port=`10400`；三个实体均绑定同一 Entry、未禁用。用户确认 HA UI 显示三实体已连接。

## 9. 最终阶段结论

**P7Ab8 验收完成，P7A 阶段门 PASS；C01–C39 全部 PASS，允许进入 P5/P6。C40–C43 DEFERRED，C44 N/A/禁止新增。**

生产 NAS Sherpa 容器持续 healthy；HA 保存唯一 Wyoming Config Entry，KWS/STT/TTS 三个实体绑定同一 Entry。HA Core 的生产 Wyoming STT/TTS Provider 类经实际容器连接验证通过。P7A 仅交付稳定语音服务依赖，不代表 Tivoo 实际麦克风、ESP32 音频链路或设备播报完成。

### Review

按 P7Ab8 合同、最终阶段门及实施计划 Review Focus 自审。本次没有可用的独立 reviewer/subagent 调度工具，因此这是作者自审，不声称已完成独立审查。

## 10. 2026-11-10 生产部署后续记录（按用户决定修订 C36）

用户明确接受 NAS host 进程可访问 Wyoming 的剩余边界，并指定正式唤醒词为“大肥鱼”。本节是对前序 P7Ab8 验收结果的增量更新，取代第 1、5、7、8、9 节中关于“容器已移除、没有正式唤醒词、C36 BLOCKED”的旧状态描述。

### 10.1 C36 风险裁定

- HA 当前使用 Docker host network，不能与 Sherpa 同时加入 bridge。为避免改变现有 HA/AstrBot 容器，继续采用独立的 `tivoo-sherpa-ha-private` bridge：`internal=true`、`attachable=false`、CIDR `172.23.0.0/24`。
- 仅 `compose_sherpa-wyoming_1` 接入该网络；`docker inspect` 看到 `ports={}`，`docker port` 无输出，没有 TCP 10400 host port mapping。
- NAS host 路由 `172.23.0.2` 到 Docker bridge 网卡，HA host network 通过该地址访问 Wyoming。
- NAS 当前 iptables `DOCKER-ISOLATION-STAGE-1` 包含两条隔离规则：非 `172.23.0.0/24` 来源发往 `docker-6dec10ab` 的转发流量被 DROP；来自 `docker-6dec10ab`、目的地不属于该 subnet 的转发流量被 DROP。该 bridge 未接入共享业务网络。
- 已接受的剩余风险：NAS 本机 host namespace 的其它进程可以访问 `172.23.0.2:10400`。Wyoming 本身无应用层鉴权，因此 NAS host 必须继续视为可信管理边界；不可信容器不得被接入该 bridge。
- 按用户批准的修订范围，C36 标记 PASS；这不是“HA 进程级唯一访问”保证。若 NAS 后续运行不可信本机代码/用户，需重新评估网络边界。

### 10.2 正式唤醒词与模型

- NAS active `.env`（权限 600，未进入 Git）：`WAKE_WORD_PHRASE=大肥鱼`。
- `sherpa-onnx-cli text2token` 使用模型 `tokens.txt`、`phone+ppinyin`、`en.phone` 正常生成：`d à f éi y ú @大肥鱼`。
- NAS 模型准备脚本报告 KWS/STT/TTS assets all present；14/14 个运行时权重 SHA-256 全部 OK，没有重新下载模型。

### 10.3 NAS 真实容器状态

| 项目 | 生产验收值 |
|---|---|
| Container | `compose_sherpa-wyoming_1` |
| Image | `ghcr.io/qyxx2/tivoo-sherpa-wyoming:sha-315df317d3934383fd5105686de6fa749866c4ad` |
| Digest | `sha256:d08e61250aa08594dc813bbe5dac9ac32c76c524578e2cfda9ea56257c5a4a31` |
| Network | `tivoo-sherpa-ha-private` / `172.23.0.0/24` / `internal=true` / `attachable=false` |
| Container IP | `172.23.0.2` |
| Host port mapping | none (`NetworkSettings.Ports={}`；`docker port` 无输出) |
| Restart policy | `unless-stopped` |
| Health | `healthy`；wake/asr/tts installed |
| Current image restart model load | KWS 1.969 s + STT 2.971 s + TTS 5.082 s = 13.144 s |

容器使用 GitHub Actions 已发布的 immutable SHA 镜像；NAS 只执行模型准备、Compose pull/up 和运行时测试，没有构建镜像。

### 10.4 生产 HA Core 2026.11.0 实际 Provider 请求

在正在运行的 NAS Home Assistant 容器中执行 HA Core 自身 `WyomingService.create("172.23.0.2", 10400)`，Describe/Info 成功，结果如下：

- `wake_word` installed；model `tivoo-wake`；phrase `大肥鱼`；languages `zh-CN`, `en-US`。
- `stt` installed；Paraformer zh-small；languages `zh-CN`, `en-US`；`requires_external_vad=true`；`supports_transcript_streaming=false`。
- `tts` installed；Matcha Baker；voice 0 / zh-CN；`supports_synthesize_streaming=true`。

随后直接使用 HA Core 实际 `WyomingWakeWordProvider._async_process_audio_stream` 发送实时节奏的音频块：

- 正样本：Matcha 模型生成“大肥鱼”语音、重采样为 16 kHz mono S16LE，并在尾部追加 1 秒静音；HA Provider 返回 `Detection`，`wake_word_id=tivoo-wake`，`wake_word_phrase=大肥鱼`；本次音频 1.788 秒，Provider 调用约 1.162 秒。
- 负样本：Sherpa 官方 `zh_3.wav` 末尾补足 1 秒静音；同一 HA Provider 返回 `NotDetected`。
- 这是真实生产 HA Python Provider 到 NAS Wyoming 容器的请求，不是直接调用容器内 KWS session。但正样本由 TTS 合成，不能代替 Tivoo/INMP441 真人收音、距离和环境噪声验收。

### 10.5 生产 HA Config Entry 阶段状态

生产 NAS HA Core（2026.11.0）的 `/config/.storage/core.config_entries` 中现有且仅有一条 `domain=wyoming` 的 Entry：`01M72MYQF1GFKY64SR87ZPWMKA`，title 为 `Sherpa ONNX Paraformer`，host=`172.23.0.2`、port=`10400`。`core.entity_registry` 中三个实体 `wake_word.sherpa_onnx_wake_word`、`stt.sherpa_onnx_paraformer`、`tts.sherpa_onnx_matcha_baker` 均引用该 Entry，`disabled_by=null`、`hidden_by=null`；用户也确认 HA UI 中三个实体均显示已连接。

因此 C03 已 PASS。配合 C01–C38 的既有与本次复验结果，C39 阶段门 PASS，P5/P6 可以将该服务作为稳定语音依赖。P3 回归仍使用本地模拟 SSE，不调用生产 AstrBot，也不据此声称生产 AstrBot 对话完成。

### 10.6 最新 CI 发布和容器更新

- Follow-up commit：`315df317d3934383fd5105686de6fa749866c4ad`。
- GitHub Actions run [42801034360 — success](https://github.com/qyxx2/Tivoo-AI-Assistant/actions/runs/42801034360)：Dockerfile check、linux/amd64 runtime build、CI smoke image、dependency/API/entrypoint smoke、Compose config、GHCR immutable SHA tag 发布均 success。
- NAS 已拉取最新 tag `sha-315df317d3934383fd5105686de6fa749866c4ad` 并通过 Compose recreate 容器。新镜像 RepoDigest 为 `sha256:d08e61250aa08594dc813bbe5dac9ac32c76c524578e2cfda9ea56257c5a4a31`，amd64/linux。
- 新容器重新加载 KWS 1.969 s、STT 2.971 s、TTS 5.082 s，总计 13.144 s；health 恢复 healthy，restart policy 仍为 unless-stopped；容器地址仍是 `172.23.0.2`，ports 仍是 `{}`。
- 14 项模型 SHA-256 在新容器重建后全部 OK；模型没有重新下载；active `.env` 仍为 mode 600，`IMAGE_TAG` 更新为 `sha-315df317...`，`WAKE_WORD_PHRASE=大肥鱼` 未变。
- 新容器启动后再次从生产 HA Core 2026.11.0 执行 Describe/Info：wake_word/stt/tts 均 installed；Wake phrase 仍为“大肥鱼”；STT zh-CN/en-US；TTS streaming true、voice 0。


## 11. 2026-11-10 生产 HA Entry 持久化与 Provider 回验

### 11.1 Config Entry / Entity Registry

在生产 NAS HA 容器中读取 .storage/core.config_entries 与 .storage/core.entity_registry：

- Wyoming Config Entry 数量：1。
- Entry ID：01M72MYQF1GFKY64SR87ZPWMKA；标题：Sherpa ONNX Paraformer；host：172.23.0.2；port：10400。
- 三实体：wake_word.sherpa_onnx_wake_word、stt.sherpa_onnx_paraformer、tts.sherpa_onnx_matcha_baker。
- 三实体的 config_entry_id 均为上述 Entry ID；disabled_by=null、hidden_by=null。
- 用户同时确认 HA UI 中三个实体显示已注册并连接。

C03 的生产持久化配置条件现已满足。C39 的服务与 Provider 阶段门据此通过。

### 11.2 生产 HA Core Wyoming STT Provider

在运行中的生产 HA Core 2026.11.0 容器内，通过 HA 自身 WyomingService.create 和 WyomingSttProvider.async_process_audio_stream，实际连接 NAS Sherpa 172.23.0.2:10400。使用项目已有 Paraformer 官方 WAV：

| 样本 | HA Provider language | 音频时长 | 输入字节 | HA Provider wall time | 结果 |
|---|---|---:|---:|---:|---|
| 官方 0.wav | zh-CN | 5.612 s | 161,058 | 0.516 s | SUCCESS，非空 Transcript，28 字符 |
| 官方 2-zh-en.wav | en-US | 8.100 s | 259,200 | 0.810 s | SUCCESS，非空 Transcript，41 字符 |

该项验证覆盖 HA Wyoming STT Provider 到 NAS 服务的真实网络/协议路径，不只是直接调用容器内模型。样本用于确认可用性和与既有基准相符，不作为人工逐字真值或 CER/WER 准确率结论。

### 11.3 生产 HA Core Wyoming TTS Provider

在同一生产 HA Core 容器中，通过 HA 自身 WyomingTtsProvider 方法调用 NAS 服务：

- **非流式：** async_get_tts_audio 成功返回 WAV；采样率 22,050 Hz、16-bit、mono；57,747 frames，PCM 115,494 bytes。
- **流式：** async_stream_tts_audio 成功返回 wav；首个 44-byte RIFF/WAVE header 正常，首块 PCM 在约 0.643 s 到达；共收到 118,260 bytes PCM，Producer task 正常结束。

该项覆盖 HA Core Wyoming TTS Provider 的普通和流式接收实现。流式测试直接调用生产 HA Provider 方法；为隔离 Provider 本身，后台任务注册使用轻量任务调度适配器，并非由 Assist Pipeline 驱动的完整生产语音会话。流式首块时间是本次分段测试的实测值，不等同于 Tivoo AUX/DAC 的真实端到端播报延迟；实体设备播放链仍按 C42 所属后续阶段验收。

### 11.4 本次最终自动化回归

ARM64 Ubuntu 开发机，代码未改动：

| 验证 | 本次结果 |
|---|---|
| Sherpa 全量测试 | `./scripts/test-sherpa-wyoming.sh tests/services/sherpa_wyoming -q` → **128 passed, 1 warning in 1.69s** |
| P3 Conversation Agent 回归 | `./scripts/test-ha.sh tests/homeassistant/custom_components/astrbot -q` → **92 passed, 63 warnings in 7.29s** |
| Ruff check | All checks passed |
| Ruff format | 24 files already formatted |
| Python 3.11 compileall | passed |
| uv pip check | 14 packages compatible |
| 模型准备脚本 bash -n | passed |
| git diff --check | passed |

Sherpa 的单条 warning 是上游 Wyoming 对 Python audioop 的弃用提示；P3 测试的 63 条为现有 Home Assistant/aiohttp/backoff deprecation/compatibility warnings。本次未修改 Sherpa 服务代码、P3 代码或运行时依赖。

本节验收用的临时 Python 脚本及两个 WAV 已从开发机和生产 HA 容器临时目录删除。生产 Sherpa 容器、模型、网络、active .env 和 HA Config Entry 均未修改。
## 12. 生产首选 Astrbot Pipeline 正式绑定与复测

首轮端到端验证后复核发现，生产 HA 的 preferred Pipeline `Astrbot` 虽然已有真实 Conversation Agent，但 STT/TTS/KWS 字段均为空。该缺口已在本次收尾中直接修复，没有再保留为后续待办。

使用 HA Core 2026.11.0 正式 WebSocket 管理 API `assist_pipeline/pipeline/update` 更新原 Pipeline（未新建替代项、未更改 preferred ID），并再次读取 HA Pipeline 存储确认持久化：

| 字段 | 已保存值 |
|---|---|
| Pipeline ID / preferred | `01m6zwpb0h8ze3jn3606s3d22m`（保持原值） |
| Conversation Engine | `conversation.astrbot` |
| Conversation Language / Pipeline Language | `*` / `zh`（保持原值） |
| STT Engine / Language | `stt.sherpa_onnx_paraformer` / `zh-CN` |
| TTS Engine / Language / Voice | `tts.sherpa_onnx_matcha_baker` / `zh-CN` / `0` |
| Wake Word Entity / ID | `wake_word.sherpa_onnx_wake_word` / `tivoo-wake` |

随后以**同一个 preferred Pipeline ID** 再次执行真实 HA Assist Pipeline，从 STT stage 送入仓库 `0.wav`：

- Paraformer Transcript：`对我做了介绍啊那么我想说的是呢大家如果对我的研究感兴趣呢`。
- 真实 `conversation.astrbot` 返回 107 字符回复。
- Sherpa Matcha TTS 经 HA TTS Proxy 返回 `audio/mpeg`，209,518 bytes；FFprobe 确认为 MP3、22,050 Hz、mono、21.561 s；FFmpeg 全量解码通过。
- 运行 Pipeline ID 与 preferred ID 一致；运行后再次检查 HA 持久化 `assist_pipeline.pipelines`，上述字段全部保留。
- KWS entity 和模型 ID 已绑定；其 Provider 正负样本及实际 HA Wake Word Provider 测试证据见 §3.2/§7.2。本次首选 Pipeline 复测从 STT stage 开始，因此没有重复执行 KWS acoustics。

本次修改只更新 HA 的原 preferred Pipeline；没有改动 Conversation Agent、Wyoming Config Entry、实体、容器或 AstrBot 配置。HA、AstrBot、Sherpa 容器均保持运行。临时 Token 副本、脚本和音频测试文件已清理。
