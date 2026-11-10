# P7A 验收报告 — P7Ab8 HA/NAS 集成验收

- 日期：2026-11-10
- 项目分支：`feature/p7a-sherpa-wyoming-service`
- P7Ab8 基线：`80e5888a1cad0a08811c034a630292274c808603`（P7Ab7）
- 实际验收镜像：`ghcr.io/qyxx2/tivoo-sherpa-wyoming:sha-80e5888a1cad0a08811c034a630292274c808603`
- 镜像 digest：`sha256:dd31586274e7055f8e08549309221b406127acc8481de17e5327e202529cfef4`
- GitHub Actions：[run 42788716057 — success](https://github.com/qyxx2/Tivoo-AI-Assistant/actions/runs/42788716057)

## 1. 结论

**P7Ab8 验收工作已经完成；P7A 阶段门仍为 BLOCKED，不放行 P5/P6。**

服务镜像、模型、单服务入口、三类 Wyoming Provider、HA Core 2026.11.0 Config Flow/实体发现、KWS hit/miss、Paraformer、非流式/流式 TTS、Assist Pipeline 阶段门、P3 Conversation Agent 文本衔接，以及 NAS 同进程资源数据均取得可复核证据。

阻止 P7A 标记完成的事项：

1. 用户明确接受放宽 C36：NAS host namespace 作为可信边界；Sherpa 使用独立 `internal=true`、`attachable=false` bridge，不发布 host/LAN/WAN 端口，不接共享网络或其它容器。NAS 本机进程仍可访问 Wyoming，这是已接受的剩余风险，不再阻塞容器部署。
2. 用户已确定正式 `WAKE_WORD_PHRASE=大肥鱼`。模型词典生成成功；真实 HA Wyoming Wake Word Provider 正样本返回 Detection、官方负样本返回 NotDetected。
3. 生产 NAS HA 的 Config Entry 尚未持久化添加。HA 生产容器到 `172.23.0.2:10400` 的 Describe/Info 和 KWS Provider 正负样本请求已实际验证；还需在 HA UI 添加一个 Wyoming Config Entry，使三个实体注册并持久化。P3 端到端测试继续使用本地模拟 SSE，不调用生产 AstrBot。

因此 C39 阶段放行条件尚不满足。未更新 README 将 P7A 标记为完成，也未将阶段状态更改为 PASS。

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
| 测试网络 | `tivoo-sherpa-ha-private`，bridge、`internal=true`、`172.23.0.0/24`，测试期间仅接入 Sherpa 容器 |
HA 使用 host 网络、当前没有 HA bridge。隔离验收时没有将 Sherpa 接入现有共享 `bridge`、AstrBot 或其他应用网络，而是创建上述独立 internal-only bridge。该方法避免 LAN 端口映射和其他容器网络变更，但 host namespace 仍可访问它，不能证明只有 HA 进程具有访问权限；严格 C36 仍未满足。

### 2.1 镜像与 CI

- GHCR 镜像 tag：`sha-80e5888a1cad0a08811c034a630292274c808603`。
- NAS 本地镜像检查：`amd64/linux`；RepoDigest 为 `sha256:dd31586274e7055f8e08549309221b406127acc8481de17e5327e202529cfef4`。
- GitHub Actions run 42788716057 负责 Dockerfile check、Buildx linux/amd64、runtime image build、CI smoke image、Sherpa API/entrypoint 检查、Compose CLI config 和 GHCR SHA tag 发布；结论 success。
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

同一 Entry 下发现 wake_word、stt、tts 三个平台；Wake model ID 为 `tivoo-wake`，phrase 与本次临时测试配置一致；ASR 语言和 `requires_external_vad` 元数据正确；TTS 仅提供 zh-CN voice 0 并声明 streaming。Config Flow/实体测试结果：2 项 HA 临时验收测试中对应的独立 Config Flow 测试通过。该 Entry 在临时 HA 测试实例中创建，未写入生产 NAS HA 的 Config Entry 存储。
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

状态定义：PASS = 有本批或前序批次可复核证据；BLOCKED = 尚缺实际部署条件/验收证据；DEFERRED = 明确由后续阶段负责；N/A = 禁止或不适用。

| 合同 | 状态 | 证据/说明 |
|---|---|---|
| C01 | PASS | NAS Compose 只有一个 Sherpa service/进程，单一 Wyoming TCP 入口 10400。 |
| C02 | PASS | HA Core Config Flow 对 NAS 服务执行 Describe，收到完整 Info。 |
| C03 | BLOCKED（生产 HA Config Entry） | HA Production Core 已成功 Describe/Info 且 Provider 可用；但尚未通过 HA Config Flow 持久化添加唯一 Wyoming Config Entry，因此三个实体尚未在生产 HA 注册。 |
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
| C38 | PASS（模拟 P3 后端） | 真实 HA Pipeline hit 的最终 STT 文本进入既有 P3 Conversation Agent；使用本地 SSE 模拟端点，miss 请求数为 0。 |
| C39 | BLOCKED | C36 已按用户接受的范围通过，正式唤醒词已配置；生产 HA Config Entry 尚未持久化添加，尚未形成单 Entry 三实体的生产配置证据。完成 HA UI 添加后再复核阶段门。 |
| C40 | DEFERRED | 实际 INMP441 安装位置、噪声、误唤醒/漏唤醒和距离由 P7 验收。 |
| C41 | DEFERRED | ESP32 I2S RX、AFE/VAD、TCP 7778 和 Satellite 音频会话由 P6/P7 验收。 |
| C42 | DEFERRED | HA TTS Proxy、HTTP 获取、WAV 解码、DAC/AUX 播放由 P6/P8 验收。 |
| C43 | DEFERRED | 屏幕、SPP、ESP32 双向通信及硬件并发由 P5/P6/P10 验收。 |
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

### 7.3 生产 HA Config Entry 尚未持久化添加

生产 HA Core（2026.11.0）容器已实际执行 `WyomingService.create("172.23.0.2", 10400)`，成功完成 Describe/Info；随后真实 `WyomingWakeWordProvider` 使用同一服务地址分别处理 KWS 正样本和负样本，返回 Detection 与 NotDetected。该结果证明网络、服务和 HA Provider 请求路径已连通，但直接创建 Python Provider 实例不会写入 HA Config Entry 存储，也不会在 HA UI 注册三个实体。

生产 HA 尚需通过 Settings → Devices & Services → Add Integration → Wyoming 添加一个条目，Host=`172.23.0.2`、Port=`10400`。Config Flow 应为该唯一条目创建 wake_word、stt、tts 三个平台。完成前 C03/C39 保持 BLOCKED。P3 对话端点继续用本地 mock SSE 验证，未使用生产 AstrBot 凭据。

### 7.4 明确不属于 P7Ab8 / P7A 完成的内容

- C40–C43 继续 DEFERRED，须分别在 P7、P6/P7、P6/P8、P5/P6/P10 真实硬件阶段验收。
- C44 继续 N/A / 禁止新增：P7A 不接入 AstrBot API、不持有 P3 session_id、不暴露 OpenAI API。
- 本批没有修改 P3 合同、AstrBot、ESP32、P5/P6 或 README 阶段状态。

## 8. 清理与当前部署状态

- NAS Sherpa Compose 容器当前持续运行：`compose_sherpa-wyoming_1`，`restart=unless-stopped`，health=`healthy`。
- active `.env` 位于 NAS 部署目录，权限 600；`WAKE_WORD_PHRASE=大肥鱼`。该文件不在 Git 中。
- 模型权重保留在 NAS 持久化目录；本次准备脚本确认 14/14 文件 SHA-256 匹配；容器启动时没有重复下载模型。
- GHCR 镜像仍保留在 NAS Docker image cache，部署使用 CI SHA tag，不在 NAS 构建镜像。
- `tivoo-sherpa-ha-private` 网络目前 internal=true、attachable=false，仅 Sherpa 容器接入；NAS host 通过 `172.23.0.2:10400` 可达。`docker port` 为空，没有 host port mapping。
- 开发机和 HA 容器的临时测试 WAV/Python 脚本已清理；临时 SSH 隧道已关闭。
- 生产 HA Config Entry 尚未通过 HA UI 持久化添加。此前 HA Core 生产容器已直接使用该地址完成 Describe/Info 与 Wake Word Provider 正负样本，但该连接不会自动创建 HA 集成配置。

## 9. 最终阶段结论

**P7Ab8 批次验收报告完成；随后按用户接受的网络边界完成真实 NAS 部署。当前 C01–C02、C04–C38 有 PASS 证据；C03/C39 BLOCKED（生产 HA Config Entry 尚未持久化添加）；C40–C43 DEFERRED；C44 N/A/禁止新增。暂不更新 README 为 P7A 完成，不放行 P5/P6。**

生产 NAS 容器已运行且 HA Core 实际能发现三类 Provider Info、通过 KWS 正负样本检测。剩余 C39 工作聚焦于 HA UI 中添加唯一 Wyoming Config Entry，并验证该 Entry 持久化后实体注册。

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

上述生产 HA `WyomingService.create` 和真实 Wake Word Provider 请求证明 HA 容器网络到服务可用，但**不会写入 HA Config Entry 存储，也不会自动注册实体**。截至本次记录，生产 HA UI 尚未持久化添加 Wyoming Config Entry，因此：

- C02：生产 HA Describe/Info 已通过。
- C03：BLOCKED，等待唯一 Wyoming Config Entry 经 HA Config Flow 保存并创建 `wake_word`、`stt`、`tts` 实体。
- C04、C10：正式 phrase 为“大肥鱼”，生产 Info 和 KWS 正负样本通过。
- C36：按用户批准的 NAS host 信任边界 PASS。
- C39：继续 BLOCKED，直到 C03 的生产 Config Entry/实体注册完成并重新检查阶段门。

HA 添加方式：Settings → Devices & Services → Add Integration → Wyoming；Host `172.23.0.2`，Port `10400`。只添加一个条目。保存后检查三个平台实体存在；无需新建自定义 Provider 集成。

生产 AstrBot 未被调用或重新配置；P3 的模拟 SSE 回归仍只证明测试文本路径，不声称生产 Assist 对话已完成。

### 10.6 最新 CI 发布和容器更新

- Follow-up commit：`315df317d3934383fd5105686de6fa749866c4ad`。
- GitHub Actions run [42801034360 — success](https://github.com/qyxx2/Tivoo-AI-Assistant/actions/runs/42801034360)：Dockerfile check、linux/amd64 runtime build、CI smoke image、dependency/API/entrypoint smoke、Compose config、GHCR immutable SHA tag 发布均 success。
- NAS 已拉取最新 tag `sha-315df317d3934383fd5105686de6fa749866c4ad` 并通过 Compose recreate 容器。新镜像 RepoDigest 为 `sha256:d08e61250aa08594dc813bbe5dac9ac32c76c524578e2cfda9ea56257c5a4a31`，amd64/linux。
- 新容器重新加载 KWS 1.969 s、STT 2.971 s、TTS 5.082 s，总计 13.144 s；health 恢复 healthy，restart policy 仍为 unless-stopped；容器地址仍是 `172.23.0.2`，ports 仍是 `{}`。
- 14 项模型 SHA-256 在新容器重建后全部 OK；模型没有重新下载；active `.env` 仍为 mode 600，`IMAGE_TAG` 更新为 `sha-315df317...`，`WAKE_WORD_PHRASE=大肥鱼` 未变。
- 新容器启动后再次从生产 HA Core 2026.11.0 执行 Describe/Info：wake_word/stt/tts 均 installed；Wake phrase 仍为“大肥鱼”；STT zh-CN/en-US；TTS streaming true、voice 0。
