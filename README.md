# Tivoo AI Assistant

Tivoo AI Assistant 是基于 Divoom Tivoo、ESP32-S3、经典 ESP32、Home Assistant、Sherpa-ONNX 与 Qwen Audio Agent 的本地语音终端项目。

> **当前基线（2026-11-26）**：P6.8 双板架构已经进入稳定迭代阶段。S3 本地 WakeNet、双麦 AFE、Sherpa device-endpoint STT、HA local-first、Qwen 文本回退、Qwen 流式音频播放以及 Classic ESP32 SPP 屏幕控制均已在真实环境运行。历史 P3–P7A/P6.x/P6.8 分批计划全部归档，不再作为活动 backlog 或发布门禁。后续发现实际问题时，针对问题建立专用分支和计划处理。
>
> 当前最有代表性的运行证据见 [P6.8 构建与 HA 决策](docs/superpowers/reports/2026-11-25-p68-build-summary-and-ha-decisions.md) 和 [B8.8 验收记录](docs/superpowers/reports/2026-11-25-p6-8-b8-8-acceptance.md)。完整文档入口见 [文档地图](docs/README.md)。

## 当前架构

~~~
                        NAS
┌──────────────────────────────────────────────────────┐
│ Home Assistant                                       │
│ ├─ Tivoo 自定义集成                                  │
│ ├─ Sherpa device-endpoint STT                        │
│ ├─ HA local intent / 本地设备控制                    │
│ ├─ Qwen Realtime Bridge                              │
│ └─ HA MCP Server / Tivoo tools                       │
│             │                          ▲              │
│             │ text fallback            │ MCP          │
│             ▼                          │              │
│        Qwen Audio Agent ────────────────┘              │
│             │ 24 kHz PCM                              │
│             ▼                                         │
│        HA 有状态 24→32 kHz SRC                        │
└─────────────┬────────────────────────────────────────┘
              │ Wi-Fi / TCP 7777 + 7778 / HTTP PCM
              ▼
┌──────────────── ESP32-S3 ────────────────────────────┐
│ 双 INMP441 → ESP-SR AFE/AEC/VAD/WakeNet             │
│ 本地提示音 / 本地 ACK / 音频输出 owner              │
│ PCM5102 I²S DAC → Tivoo AUX                          │
│ UART ↔ Classic ESP32                                 │
└─────────────┬────────────────────────────────────────┘
              │ UART
              ▼
┌──────────── Classic ESP32 ───────────────────────────┐
│ Bluetooth Classic SPP → Tivoo 屏幕/亮度/倒计时等     │
└──────────────────────────────────────────────────────┘
~~~

### 一轮语音的当前路径

1. S3 常驻双麦 AFE，在本地运行 WakeNet；待机环境 PCM 不持续上传 NAS。
2. 本地唤醒确认后播放 S3 Flash 内提示音，提示音结束后开放命令采集。
3. 命令 PCM 经现有 7778 音频会话交给 Sherpa device-endpoint STT，得到最终文本。
4. HA 先尝试本地 intent：action_done 直接执行 HA 动作并由 S3 播放固化成功/失败 ACK；query_answer 使用 HA 本地动态 TTS；未命中则只把 Sherpa 文本提交给 Qwen，不再次上传/识别原始 PCM。
5. Qwen 可通过 HA MCP 调用家庭设备/Tivoo 工具；回答音频以流式 PCM 返回。
6. HA 使用有状态 SRC 把 Qwen 24 kHz PCM 转成 32 kHz mono S16LE，边生成边提供给 S3。
7. S3 通过统一 output owner、PCM5102 和 AUX 播放；实际播放终态继续参与 generation/follow-up 生命周期。
8. 屏幕和 Tivoo 原生控制由 Classic ESP32 通过 SPP 完成，S3 与 Classic 之间走 UART。

## 主要组件

| 组件 | 当前职责 |
|---|---|
| ESP32-S3 N16R8 | Wi-Fi、双麦 I²S、AFE/AEC/VAD/WakeNet、命令 PCM、提示音/ACK、Qwen/TTS PCM 播放、PCM5102 |
| Classic ESP32 WROVER-E | Bluetooth Classic SPP、Bond/重连、Tivoo 屏幕与原生控制 |
| Home Assistant | 设备/实体、语音生命周期、Sherpa STT、本地 intent、播放 owner、显示状态、MCP |
| Sherpa Wyoming | 当前仍承担 Tivoo device-endpoint STT；历史 KWS/TTS Provider 资料仍保留 |
| Qwen Audio Agent | 未命中本地 intent 后的对话、工具调用、人格/记忆扩展和语音回答 |
| Divoom Tivoo | AUX 扬声器、16×16 屏幕、原生 SPP 功能 |

### AstrBot 状态

AstrBot/P3/P4 代码、规格、报告和历史计划**保留但归档**。它们用于追溯早期 Conversation Agent、SSE、Persona 与 MCP 设计，不再代表当前主要语音架构，也不要求为了关闭历史 checkbox 继续做 HA 重启、24 小时 session、API Key 轮换、Persona 故障注入等测试。

不主动删除这些历史实现；如果以后需要复用，可从对应提交和文档恢复上下文。

## 硬件基线

- ESP32-S3：ESP32-S3-DEV-KIT-N16R8-M，16 MB Flash / 8 MB PSRAM。
- Classic ESP32：ESP32-DEV-KIT-WROVER-E-M，16 MB Flash / 8 MB PSRAM。
- 麦克风：2 × INMP441，同步双麦输入。
- DAC：PCM5102，I²S → 模拟 AUX。
- 终端：Divoom Tivoo。
- S3 与 Classic ESP32 使用独立固件目标和独立刷写流程；Classic 侧不承担主语音链 Wi-Fi/AFE。

具体 GPIO、时序与 AFE 合同保留在 [P6.8 硬件设计](docs/superpowers/specs/2026-11-18-p6-8-b0-2-hardware-uart-spp-design.md) 和 [音频/AFE 设计](docs/superpowers/specs/2026-11-18-p6-8-b0-3-audio-afe-design.md)。这些设计文档仍可作为实现参考，但对应执行计划已经归档。

## 当前实现原则

- **本地优先**：能由 HA local intent 确定完成的操作不进入 Qwen。
- **单一音频 owner**：提示音、ACK、动态 TTS、Qwen 回复共享现有输出所有权与 generation 隔离。
- **不重复 ASR**：local miss 只向 Qwen 发送 Sherpa transcript，不回放 MIC PCM。
- **流式播放**：HA 收到首个合法 Qwen PCM delta 后即可开始有界输出，不等待整段 audio.done。
- **SRC 在 HA**：当前 Qwen 24→32 kHz 转换放在 HA，减少 S3 持续播放 CPU 压力。
- **真实终态**：逻辑响应完成与设备实际 AUDIO_STATE 分开处理。
- **问题驱动验证**：低概率、难复现、成本高的历史验收不再作为固定门禁；实际使用中出现问题后再针对性复现和修复。

## 仓库目录

~~~
homeassistant/
  custom_components/tivoo/     当前 HA Tivoo 集成
  custom_components/astrbot/   历史 AstrBot 集成，保留归档

esp32/
  firmware/                    ESP32-S3 主固件
  bridge_firmware/             Classic ESP32 SPP/UART 桥

services/
  sherpa_wyoming/              Sherpa Wyoming 服务

deploy/
  nas/                         NAS/Qwen/HA 部署材料

tests/
  homeassistant/
  esp32/
  services/
  integration/

docs/
  README.md                    当前文档地图
  superpowers/
    plans/                     全部为历史归档计划
    specs/                     规格/合同；含当前与历史设计
    reports/                   验收、故障调查和运行证据

tivoo-rotating-base/           Tivoo 可旋转底座参数化 CAD
~~~

## 开发与验证

日常改动优先在开发机完成测试；真实部署、刷写和声学验证只在确有需要时进行。

常用入口：

~~~
./scripts/test-ha.sh tests/homeassistant/custom_components/tivoo -q
./scripts/test-sherpa-wyoming.sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/esp32
~~~

固件构建继续使用项目锁定的 ESP-IDF v6.1 环境。刷写前必须重新识别真实串口对应芯片，S3 与 Classic 不按历史 /dev/ttyACM* 编号猜测。

## 文档与历史计划规则

从 2026-11-26 起：

- docs/superpowers/plans/ 下现有计划全部视为**历史轨迹**，不会自动恢复执行。
- 归档计划中的 [x] 表示已经有实现/验证证据。
- 未勾选项只表示历史上没有执行或完整核销，不代表当前待办。
- AstrBot、旧 NAS KWS、旧单板、旧 P7/P8/P10 等计划不会因为还有未勾选项而重新进入开发。
- 若实际使用发现 bug，单独建立修复分支，以真实故障为入口设计最小复现和修复。
- 新功能同样从当前稳定基线建立独立分支；只有复杂功能需要时才新增新的活动计划。

详细分类、权威文档和历史索引见 [docs/README.md](docs/README.md)。

## 当前非阻塞边界

以下内容可以继续观察，但不是进入新功能开发的前置条件：

- 远场命令的正式定距统计、削波率与完整声学 benchmark。
- 电视、双讲、连续打断等组合场景的系统化矩阵。
- AP 人工断电、极端丢包、响应丢失重放等低概率故障注入。
- 第二台 Tivoo/JTAG 软件重启等旧 P5 专项。
- 对每一条历史合同做形式化全量重新核销。
- B8.8 剩余真人声学 ACK/query 延迟证据。

这些问题若在实际使用中形成可感知缺陷，再按真实症状处理。

## 历史阶段摘要

| 阶段 | 结果 |
|---|---|
| P3/P4 | AstrBot Conversation/MCP 历史实现；当前归档 |
| P5 | Classic ESP32 最小固件与 SPP 基础完成，后被双板架构吸收 |
| P6 | ESP32↔HA 双向通信阶段验收通过 |
| P6.5 | 常驻音频/取消/打断基础，后续语音拓扑被 P6.8 替代 |
| P6.6 | 表情状态机、mood、screen gate 完成 |
| P6.7 | 提示音/自触发处理完成，后来迁移为 S3 本地资产 |
| P7A | Sherpa Wyoming 服务完成；当前继续复用 device-endpoint STT |
| P6.8 | S3 + Classic 双板、本地 WakeNet、Qwen、local-first 已形成当前稳定基线 |

历史逐批过程、失败试验和验收报告全部保留在 docs/superpowers/，用于定位回归和理解设计来源，不再用于驱动日常开发。
