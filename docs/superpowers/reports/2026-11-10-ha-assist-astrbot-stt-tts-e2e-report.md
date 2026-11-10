# HA Assist Pipeline / AstrBot / Sherpa STT-TTS 生产端到端补充验收

- 日期：2026-11-10
- 目标环境：Synology NAS 上的 Home Assistant Core 2026.11.0、AstrBot 生产实例、P7A Sherpa Wyoming 服务
- 开发分支：`feature/p7a-sherpa-wyoming-service`
- 结果：**两轮真实生产语音输入/对话/语音输出通过**

## 1. 验收目标

补齐 P7A 初次验收中 C38 的真实后端边界：此前 HA Assist Pipeline 的 KWS/STT 阶段门测试使用本地 Mock SSE；本次继续使用生产 HA Core 和实际 Wyoming Provider，但将 P3 Conversation Agent 后端切换为已配置的生产 AstrBot，验证最终 STT 文本、真实 SSE 对话、TTS Proxy 音频输出及连续会话。

## 2. 测试方式

通过 HA 官方 WebSocket `assist_pipeline/run` 执行实际 Pipeline，不直接调用 Wyoming Provider 或 AstrBot API 来代替 Pipeline：

`16 kHz / mono / PCM16 WAV → HA Assist Pipeline(STT) → Sherpa Paraformer → conversation.astrbot → AstrBot HTTP/SSE → HA TTS → Sherpa Matcha Baker → HA TTS Proxy`

测试临时创建的 Pipeline 配置：

| 字段 | 值 |
|---|---|
| Name | `P7A E2E Temporary` |
| Conversation Engine | `conversation.astrbot` |
| Conversation Language | `zh` |
| STT Engine / Language | `stt.sherpa_onnx_paraformer` / `zh-CN` |
| TTS Engine / Language | `tts.sherpa_onnx_matcha_baker` / `zh-CN` |
| TTS Voice | Provider 默认 voice |
| Start / End Stage | `stt` → `tts` |

输入使用仓库 Paraformer 官方 WAV 样本，按 HA Core WebSocket 二进制音频协议分块上传；测试由 HA 自己的 Pipeline 触发 STT、Conversation Agent 和 TTS。使用 `start_stage=stt` 是因为样本中没有“大肥鱼”唤醒词；KWS 正负样本以及 WAKE_WORD 阶段此前已独立通过，不把本次 STT 起始测试冒充为 KWS 测试。

## 3. 两轮实测

| 指标 | 第一轮 | 第二轮 |
|---|---|---|
| 输入文件 | `1.wav` | `0.wav` |
| 输入时长 | 5.153 s | 5.033 s |
| Paraformer Transcript | 重点呢想谈三个问题首先呢就是这一轮全球金融动荡的表现 | 对我做了介绍啊那么我想说的是呢大家如果对我的研究感兴趣呢 |
| AstrBot | 收到真实 STT 文本并返回 SSE 回复 | 收到真实 STT 文本并返回 SSE 回复；回答明确引用第一轮提到的“三个关于全球金融动荡的问题” |
| HA TTS Proxy MIME | `audio/mpeg` | `audio/mpeg` |
| 实际编码 / 采样 | MP3 / 22,050 Hz / mono | MP3 / 22,050 Hz / mono |
| 音频字节数 | 248,726 | 193,039 |
| 解码时长 | 22.970 s | 19.603 s |
| HTTP 首块时间 | 2,214.5 ms | 199.7 ms |
| FFmpeg 全量解码 | PASS | PASS |

HTTP 首块时间从收到 HA `tts_output` 后开始下载 TTS Proxy URL 计时；它是代理下载的首块到达时间，不是从用户说完到首个声音的全链路延迟。

**格式观察：** Wyoming Matcha Provider 的上游输出是 WAV/PCM；本次 HA TTS Proxy 对外提供的是 MP3（`audio/mpeg`），两轮均经 FFprobe 识别并由 FFmpeg 全量解码成功。后续 ESP32 音频获取/解码需要以 Satellite/TTS Proxy 实际返回的 MIME 为准，不能假设代理 URL 一定是 WAV。

## 4. 连续会话证据

- 两轮执行使用相同 HA WebSocket 用户上下文；第二轮复用第一轮 Pipeline 返回的 HA `conversation_id`。
- 第二轮 AstrBot 答复主动引用第一轮的“全球金融动荡”话题，符合会话上下文连续行为。
- HA 持久化的 `astrbot_session` 记录仍存在：`created_at=2026-11-09T10:12:21Z`，本轮后 `last_activity_at=2026-11-10T14:53:17Z`。session manager 的活动记录被刷新，没有因两轮请求重新建立 session。
- 生产 AstrBot 返回的是实际可见回答 SSE，不是本地 Mock；HA 继续将 Conversation Agent 输出交给 TTS。

## 5. 清理与未覆盖范围

- 通过 HA WebSocket 临时创建 `P7A E2E Temporary` Pipeline；两轮结束后已成功删除。
- 清理后重新读取 Pipeline 列表：只剩原有 `Home Assistant` 和 `Astrbot` 两项；原 preferred Pipeline 仍为 `Astrbot`，未被更改。
- 生产 HA Config Entry、Wyoming 实体、AstrBot Config Entry、生产 Pipeline 存储和服务容器均未修改。
- 本次从 STT stage 开始，没有执行 KWS；KWS 独立验证证据仍见 P7A 验收报告 §3.2/§7.2。
- 没有使用 INMP441、ESP32 Assist Satellite、Tivoo AUX/DAC 或实体扬声器；本次验证到 HA TTS Proxy 的真实音频资源并完成离线解码，不代表物理播放验收。
- **现有 preferred `Astrbot` Pipeline 仍配置为 `stt_engine=null`、`tts_engine=null`、`wake_word_entity=null`。** 本次为了保护原配置，使用临时 Pipeline 完成验证并删除。若要让 HA Web Assist / 后续 Satellite 直接使用该 preferred Pipeline 进行语音交互，还需要在 HA Voice assistants 中给原 Pipeline 绑定 Sherpa STT、TTS（以及需要服务端唤醒时绑定 KWS）。这项配置没有在本次测试中擅自持久化更改。
