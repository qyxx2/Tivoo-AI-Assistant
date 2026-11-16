# P6.7b0 静态素材与 HA `/local` 路由验收

- 日期：2026-11-16；分支：`feature/p6-7-audio-prompts`
- 范围：仅 P6.7b0。未进入 b1 播放 owner、b2 等待入口，也未部署 NAS 静态文件或做 ESP32/Tivoo 声学验收。

## 生产 TTS 对齐

本次纠正后不再使用开发机其它 TTS 引擎。已直接核对 NAS 当前生产环境：Home Assistant 容器为 `2026.11.0`，`Astrbot` Assist Pipeline 的 TTS 为 `tts.sherpa_onnx_matcha_baker`、语言 `zh-CN`、voice `0`；实际运行的 `tivoo-sherpa-wyoming` 容器配置 `TTS_NUM_THREADS=1`。仓库生产实现使用 Matcha Baker + Vocos 22.05 kHz，`sid=0`、`speed=1.0`。

三条原始语音由 **NAS 上正在运行的生产 Sherpa Wyoming 容器本身** 一次性生成，调用与生产 Provider 相同的模型加载配置和 PCM 量化逻辑。原始 PCM 均为 22,050 Hz mono：

| 文本 | 原始生产 TTS 时长 |
| --- | ---: |
| 我在 | 0.440635 s |
| 在的 | 0.446621 s |
| 你说 | 0.532063 s |

随后只做两项资产适配：前置约 120 ms、后置约 180 ms 静音，以及转为项目静态资源所需的 32 kHz mono MP3。没有换模型、改 voice/speed、做 loudnorm、变调或其它改变音色的处理。

## 最终素材

| 文件 | 内容 | 总时长 | SHA256 |
| --- | --- | ---: | --- |
| `homeassistant/prompt_assets/ready_01.mp3` | 我在 | 0.740656 s | `17727761db1100511d7728038d5212ec896e1aa141e666283a1c474d12e92d80` |
| `homeassistant/prompt_assets/ready_02.mp3` | 在的 | 0.746625 s | `f4e90f5588f87d23b49adf76fca2907422bf92e41da77ab76b8c352326a88c67` |
| `homeassistant/prompt_assets/ready_03.mp3` | 你说 | 0.832094 s | `22e7ec8ce43ee406de94f95b46a988ac7a44cf0c838d93b05cfed80a166634a7` |

三条均为 MPEG Layer III、32,000 Hz、mono、64 kbit/s。FFmpeg `silencedetect`（-45 dB）实测：前置静音约 0.184–0.188 s，后置静音约 0.189–0.204 s；因此解码后也有明确的头尾缓冲，不再掐头去尾。原先的“嘟”声和 `ready_04.mp3` 已删除，首期只保留这三条生产同音色短句。

## HA `/local` 静态接口

HA Core 2026.11.0 的 `frontend` 在配置目录 `www` 存在时注册 `/local`，静态处理按扩展名给 MP3 返回 `audio/mpeg`。自动化测试创建临时 `www/tivoo/prompts/`，复制三条最终素材，真实加载 HA `frontend`，再以无 Authorization 的客户端 GET：

`/local/tivoo/prompts/ready_01.mp3`～`ready_03.mp3`

三条均验证 HTTP 200、无认证重定向、`audio/mpeg`，响应字节与仓库文件一致。生产部署位置仍为 `/config/www/tivoo/prompts/`；实际 NAS/ESP32 LAN 获取留给 b3。

## 测试与门禁

- RED：删除第四条后，旧测试仍要求 `ready_04.mp3`，按预期失败。
- GREEN：测试改为三条素材，并新增头尾静音门禁：开头至少 100 ms 可检测静音、结尾至少 150 ms 可检测静音；同时保留 MP3 codec、32 kHz、mono、≤0.9 s、完整 FFmpeg 解码、缺文件、伪 MP3、超时长和真实 HA `/local` HTTP 检查。
- 最终：`test_prompt_assets.py + test_transport.py` 共 **35 passed**；`ruff check`、`ruff format --check`、`git diff --check` 通过。

**P6.7b0 结论：PASS。** 当前资产数量、内容、生产 TTS 音色来源和静音边界已按最新要求锁定；b1 以后只能从这三条固定文件中选择，不能重新引入“嘟”声或换用其它 TTS 引擎。
