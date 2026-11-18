# P6.8b5：HA STT 入口与有界会话（软件验收）

实现提交：8257cfa1ec89adeb4c7aa872087263e9fec5b012；当前 feature/p6-8-s3-local-wake。只做 b5，依据 b0.4/b0.5 合同、b4 逻辑增强流和 HA Core 2026.11.0 / Wyoming 1.10.2 / ESP-IDF 6.1 实际源码。NAS 仅 SSH 只读核对现有 Sherpa 容器网络，10401 未监听；未改配置、未部署、未重启、未刷任何固件。

## 实现和合同

- T05-A / VOICE-C02/03：接入 HA 自带 AssistPipelineSelect，local 模式只调用指定 pipeline 的 public Satellite API（STT 起始，真实 wake phrase 和 Context）；无选择、preferred、同名、无效、非设备端点 Provider 均拒绝。legacy 保持原 preferred 路径。测试用真实 HA Core 和 mock Wyoming/AstrBot HTTP/SSE，确认只读时间问题不请求 AstrBot，其他问题 fallback，连续请求维持 ID，现有 new_conversation 后轮换 ID，intercept 不触发 STT，待处理 ask_question 走实际 STT-only。原 P3 ChatLog/SSE 和 TTS ownership 回归保留。
- T05-B / VOICE-C03/04/06：10400 原 KWS/ASR/TTS、requires_external_vad=true 不变；10401 是独立 ASR-only 元数据、requires_external_vad=false；两个 listener 共享已有模型、STT provider 与有界 executor，不重复加载。拒绝 10401 的 Detect、Synthesize 及 SynthesizeStart。镜像/compose 增内部端口和双端口 healthcheck；未发布宿主端口。真实 HA/Wyoming 测试在第一个 pull 时 READY，经 Transcribe/AudioStart 之后才上传；64000 字节逐字节一致、一次 AudioStop、没有 HA STT_VAD start/end；部分 PCM 后断线不产生 AudioStop/STT_END/INTENT_START。
- T05-C / VOICE-C01/04/05/06/07、LIFE-C01/C04：7778 v1 握手明确回显 local_wake_stt_v1，重连重置 epoch，旧端不发送新会话音频。S3 确认 wake 创建 UUID，AFE fetch 所有者输出单一有序流，16k/20ms/640B 帧，16000 样本 PSRAM pending ring，最后一帧补零并报实际 wire pcm_samples；gate/ready 两种顺序均支持，gate 后 1s READY、3s 等待首命令、15s 命令、5s gate 等待和 TX 超时。早端点、计数错、gap、超时、溢出、旧 UUID/断线走取消而非正常 EOF；同包 PCM/end/new START 不将旧数据拼到新会话。普通 TTS 基础 session/playback/epoch 绑定和 stop 定向清理；已有完整 TTS 回归、真实 TCP fake peer 的 0x30/31/32 验证，未声称物理播放测试。
- S3 测试 gate CONFIG_TIVOO_P68_TEST_GATE 默认关闭，仅显式 test build 可在该次启动尚未有音频输出时使用 b4 逻辑 gate。b6 才提供实际提示音和物理安全边界，默认固件不能当作完整可用语音固件。保留 smoke 模型 wn9_hilexin（嗨，乐鑫）和 vadnet1_medium，不替用户确定正式唤醒词。
- 实际 HA Core run.py accept_wake_word / const.py 保留原生同词 2s 去重，未改 Core；后续 b7 快速打断与重唤醒需要纳入该约束。b7 完整 active interruption/续聊、b8 表情协调不在本次范围。

## 软件验证

| 测试 | 结果 |
|---|---|
| HA 全量首次 | 506 passed, 247 warnings，exit 0 |
| 实现提交后 HA 全量 | 506 passed, 247 warnings；另 1 teardown error，exit 1 |
| 上述 config flow 文件独立重跑 | 14 passed, 17 warnings，exit 0 |
| 追加真实 HA 端到端 | 1 passed（含 intercept/ask/cancel/intent/AstrBot/会话轮换多阶段断言） |
| 追加 7778 TCP / 同包 / 定向 STOP | 1 passed，26 deselected |
| Sherpa Wyoming 全量 | 135 passed, 1 warning，exit 0 |
| ESP32 standalone 全量 | 88 passed, 35 warnings，exit 0 |
| S3 IDF 6.1 最终实现提交重配置与单线程 Ninja | exit 0 |
| git diff --check / cached check | 通过 |

HA 第二次全量中所有 506 测试断言通过；test_reconfigure_adds_explicit_host_and_preserves_existing_media 的 fixture teardown 发现 tivoo_esp32_control 仍在等待，独立重跑整个 config flow 文件 14 项全过。未将其解释为已证实的生产故障，也不隐去该非零退出；最终全量严格意义非全绿，非复现清理异常待后续关注。没有为该次异常改动无关生产逻辑。无独立 reviewer 工具，执行实现者自审。

日志 .superpowers/p68-b5/：ha-full.log、ha-full-final.log、config-recheck.log、ha-real-intent-final.log、coalesced-final.log、sherpa-all.log、esp-full.log、s3-build-final.log，以及 RED/GREEN 原始记录。HA .venv 的 Wyoming 采用原有 Sherpa venv 的 1.10.2 pure-python 模块和 dist-info 的局部链接，经 PYTHONPATH 注入，不安装/替换生产软件；requirements_test.txt 明确 pin。HA 命令：PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath" bash scripts/test-ha.sh tests/homeassistant；Sherpa bash scripts/test-sherpa-wyoming.sh；ESP32 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32 -q。编译限制 CMAKE_BUILD_PARALLEL_LEVEL=1、ninja -j1，抽样可用内存约4.5GB，无宿主失联。

## 构建

app 1,919,200 B，8MiB app partition 余77%，SHA256 783b0002bbdaa991f0577fb51030f6738202864b2cae87b61df9ce5041cc3cfd。模型 SHA256 f1a1a39defc1d1c52d112b45629fb221adad4dfda85785ed9f527cb53a145e19 与 b4 相同。构建产物 esp32/firmware/build/，仅 build，不执行 flash。

## 留待实机 / 下一批

S3 与第二颗 INMP441 未到货，VOICE-C01–07/LIFE-C01/C04 的物理实际抓包、真实模型识别/端点、声学 gate 与 marker、动态 PSRAM/CPU、ready/延迟 P50/P95、正常实际 TTS 输出未验收；本次软件可继续，不需要新的人工选择。后续部署时，先使独立 10401 可用，在 HA 新增 Wyoming 集成对应 endpoint，单独配置 Tivoo pipeline（复制实际会话/TTS/语言、本地优先设置，STT 改新入口、无 HA wake，Tivoo selector 选择唯一名称），全局 preferred 及原 10400 不变。现没有对生产 HA 注册或选择该 pipeline。b6 物理提示 gate，b7 完整打断/连续对话，b8 表情来源按计划后置。
