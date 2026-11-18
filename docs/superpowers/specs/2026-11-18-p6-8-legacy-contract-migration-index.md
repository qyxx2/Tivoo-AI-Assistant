# P6.8b0.1 历史合同迁移索引（初版）

基线 main @ d79775f，设计分支起点 be73329。每个原 ID 单独列出。原合同全文、原验收状态及原证据仍以链接原文为准；本表不重新授予 PASS。归属为本批设计路由，不是最终新合同 ID；b0.2–b0.5 按领域定新合同，b0.6 核对 ID/用例/证据闭环，b10 复验。

覆盖 192 个唯一原 ID（含 P3 的测试 ID）；矩阵源行与索引一一对应。
## [2026-11-09-p3-astrbot-conversation-contract-matrix.md](2026-11-09-p3-astrbot-conversation-contract-matrix.md)（28 项）

| 原 ID | 原合同主题（完整规则见原矩阵） | 归属 | 设计 / 实施及回归 | 迁移理由与验收方向 |
|---|---|---|---|---|
| P3-01 | HA Assist Pipeline → AstrBot Conversation Entity | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-02 | HA Conversation Entity → HA ChatLog | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-03 | HA AstrBot 集成 → AstrBot | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-04 | HA AstrBot 集成 → AstrBot 鉴权 | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-05 | HA 单用户 → AstrBot 用户 | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-06 | HA 活动会话状态 → AstrBot | 保留/独立缺测延后 | P3 后续 / b10 会话隔离 | Store/24h/API Key 轮换不因拓扑改变，未验收不核销 |
| P3-07 | AstrBot SSE → HA SSE Parser | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-08 | SSE Parser → HA ChatLog Delta | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-09 | HA ChatLog → HA Assist Pipeline | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-10 | HA Conversation Entity → Assist Pipeline | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-11 | HA 取消 → AstrBot | 迁移 | b0.5 / b7,b10 | 原 session stop owner、取消一次、真实 partial SSE/旧轮隔离 |
| P3-12 | HTTP/SSE 异常 → HA Conversation | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-T01 | HA 2026.11.0 加载自定义集成 | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-T02 | HA Assist 输入一条中文文本 | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-T03 | 检查请求体 | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-T04 | 连续多轮，HA conversation_id 不同 | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-T05 | 模拟 HA ChatSession 超过 5 分钟后重新生成 conversation_id | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-T06 | HA Core 重启，Store 记录未过期 | 保留/独立缺测延后 | P3 后续 / b10 会话隔离 | Store/24h/API Key 轮换不因拓扑改变，未验收不核销 |
| P3-T07 | 距最近活动不足 24h / 达到 24h | 保留/独立缺测延后 | P3 后续 / b10 会话隔离 | Store/24h/API Key 轮换不因拓扑改变，未验收不核销 |
| P3-T08 | AstrBot 正常 SSE | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-T09 | SSE 带 heartbeat、session_id、user_message_saved、agent_stats | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-T10 | SSE reasoning/tool_call/tool_call_result | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-T11 | SSE 正常 end | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-T12 | JSON error、401、403、SSE error、意外 EOF | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-T13 | HA 取消对话 | 迁移 | b0.5 / b7,b10 | 原 session stop owner、取消一次、真实 partial SSE/旧轮隔离 |
| P3-T14 | 开启后续支持流式输入的 TTS Provider | 保留 | b0.4 / b5,b7,b10 | HA Agent、SSE、ChatLog、身份、正常/异常及 TTS 回归；不另造会话入口 |
| P3-T15 | 使用专用 API Key 发送 Chat 后立即取消 | 迁移 | b0.5 / b7,b10 | 原 session stop owner、取消一次、真实 partial SSE/旧轮隔离 |
| P3-T16 | 轮换为新建的专用 API Key | 保留/独立缺测延后 | P3 后续 / b10 会话隔离 | Store/24h/API Key 轮换不因拓扑改变，未验收不核销 |

## [2026-11-09-p4-ha-mcp-tool-contract-matrix.md](2026-11-09-p4-ha-mcp-tool-contract-matrix.md)（15 项）

| 原 ID | 原合同主题（完整规则见原矩阵） | 归属 | 设计 / 实施及回归 | 迁移理由与验收方向 |
|---|---|---|---|---|
| P4-C01 | HA MCP Server 路由 | 保留 | b0.2,b0.5 / b2,b8,b10 | HA MCP 服务、参数和隔离不改变；新桥真实工具回归 |
| P4-C02 | Streamable HTTP 初始化 | 保留 | b0.2,b0.5 / b2,b8,b10 | HA MCP 服务、参数和隔离不改变；新桥真实工具回归 |
| P4-C03 | MCP 工具发现 | 替代历史范围限制 | b0.5 / b2,b8,b10 | 七个 MVP 不再是上限；现有扩展、mood、屏幕和服务白名单全部保留 |
| P4-C04 | 权限边界 | 保留 | b0.2,b0.5 / b2,b8,b10 | HA MCP 服务、参数和隔离不改变；新桥真实工具回归 |
| P4-C05 | 实体暴露范围 | 保留 | b0.2,b0.5 / b2,b8,b10 | HA MCP 服务、参数和隔离不改变；新桥真实工具回归 |
| P4-C06 | 工具注册过滤 | 替代历史范围限制 | b0.5 / b2,b8,b10 | 七个 MVP 不再是上限；现有扩展、mood、屏幕和服务白名单全部保留 |
| P4-C07 | 服务复用 | 保留 | b0.2,b0.5 / b2,b8,b10 | HA MCP 服务、参数和隔离不改变；新桥真实工具回归 |
| P4-C08 | 失败传播 | 保留 | b0.2,b0.5 / b2,b8,b10 | HA MCP 服务、参数和隔离不改变；新桥真实工具回归 |
| P4-C09 | 基础参数范围 | 保留 | b0.2,b0.5 / b2,b8,b10 | HA MCP 服务、参数和隔离不改变；新桥真实工具回归 |
| P4-C10 | 媒体参数边界 | 保留 | b0.2,b0.5 / b2,b8,b10 | HA MCP 服务、参数和隔离不改变；新桥真实工具回归 |
| P4-C11 | P3 回归 | 保留 | b0.2,b0.5 / b2,b8,b10 | HA MCP 服务、参数和隔离不改变；新桥真实工具回归 |
| P4-C12 | 断线与重试 | 迁移 | b0.2 / b2,b10 | 断线和真实动作；不重复非幂等动作，不以传输代替屏幕实测 |
| P4-C13 | 设备传输隔离 | 保留 | b0.2,b0.5 / b2,b8,b10 | HA MCP 服务、参数和隔离不改变；新桥真实工具回归 |
| P4-C14 | Tivoo 实机动作 | 迁移 | b0.2 / b2,b10 | 断线和真实动作；不重复非幂等动作，不以传输代替屏幕实测 |
| P4-C15 | 未声明功能边界 | 替代历史范围限制 | b0.5 / b2,b8,b10 | 七个 MVP 不再是上限；现有扩展、mood、屏幕和服务白名单全部保留 |

## [2026-11-10-p7a-sherpa-wyoming-contract-matrix.md](2026-11-10-p7a-sherpa-wyoming-contract-matrix.md)（44 项）

| 原 ID | 原合同主题（完整规则见原矩阵） | 归属 | 设计 / 实施及回归 | 迁移理由与验收方向 |
|---|---|---|---|---|
| P7A-C01 | P7A → 项目 | 保留/条件迁移 | b0.4,b0.6 / b5,b9,b10 | 保持现有 STT/TTS 与服务；是否取消 wake Provider/模型需确认其他消费者，健康/性能相应调整 |
| P7A-C02 | HA → P7A | 保留/条件迁移 | b0.4,b0.6 / b5,b9,b10 | 保持现有 STT/TTS 与服务；是否取消 wake Provider/模型需确认其他消费者，健康/性能相应调整 |
| P7A-C03 | P7A → HA | 保留/条件迁移 | b0.4,b0.6 / b5,b9,b10 | 保持现有 STT/TTS 与服务；是否取消 wake Provider/模型需确认其他消费者，健康/性能相应调整 |
| P7A-C04 | P7A → HA | 保留/条件迁移 | b0.4,b0.6 / b5,b9,b10 | 保持现有 STT/TTS 与服务；是否取消 wake Provider/模型需确认其他消费者，健康/性能相应调整 |
| P7A-C05 | P7A → HA | 保留/迁移端点 | b0.4 / b5,b6,b10 | 整句 STT/格式/错误/有界/最终一次 decode；C22 的 HA 端点责任需查真实 API |
| P7A-C06 | P7A → HA | 保留 | b0.4,b0.5 / b5,b7,b10 | TTS/并发/网络/隐私/隔离及停止回归，不引入直接调用 |
| P7A-C07 | P7A → HA | 保留/条件迁移 | b0.4,b0.6 / b5,b9,b10 | 保持现有 STT/TTS 与服务；是否取消 wake Provider/模型需确认其他消费者，健康/性能相应调整 |
| P7A-C08 | 构建 → 运行时 | 保留/条件迁移 | b0.4,b0.6 / b5,b9,b10 | 保持现有 STT/TTS 与服务；是否取消 wake Provider/模型需确认其他消费者，健康/性能相应调整 |
| P7A-C09 | KWS 模型 → KeywordSpotter | 替代 Tivoo 路径 | b0.3,b0.4 / b4,b5,b9,b10 | Tivoo 去远程 KWS；非 Tivoo 消费者未核实，不全局删除 |
| P7A-C10 | 配置 → KWS | 替代 Tivoo 路径 | b0.3,b0.4 / b4,b5,b9,b10 | Tivoo 去远程 KWS；非 Tivoo 消费者未核实，不全局删除 |
| P7A-C11 | HA → KWS | 替代 Tivoo 路径 | b0.3,b0.4 / b4,b5,b9,b10 | Tivoo 去远程 KWS；非 Tivoo 消费者未核实，不全局删除 |
| P7A-C12 | HA → KWS | 替代 Tivoo 路径 | b0.3,b0.4 / b4,b5,b9,b10 | Tivoo 去远程 KWS；非 Tivoo 消费者未核实，不全局删除 |
| P7A-C13 | KWS → HA | 替代 Tivoo 路径 | b0.3,b0.4 / b4,b5,b9,b10 | Tivoo 去远程 KWS；非 Tivoo 消费者未核实，不全局删除 |
| P7A-C14 | KWS → HA | 替代 Tivoo 路径 | b0.3,b0.4 / b4,b5,b9,b10 | Tivoo 去远程 KWS；非 Tivoo 消费者未核实，不全局删除 |
| P7A-C15 | KWS → HA | 替代 Tivoo 路径 | b0.3,b0.4 / b4,b5,b9,b10 | Tivoo 去远程 KWS；非 Tivoo 消费者未核实，不全局删除 |
| P7A-C16 | KWS → HA Pipeline | 替代 Tivoo 路径 | b0.3,b0.4 / b4,b5,b9,b10 | Tivoo 去远程 KWS；非 Tivoo 消费者未核实，不全局删除 |
| P7A-C17 | STT 模型 → OfflineRecognizer | 保留/迁移端点 | b0.4 / b5,b6,b10 | 整句 STT/格式/错误/有界/最终一次 decode；C22 的 HA 端点责任需查真实 API |
| P7A-C18 | HA → STT | 保留/迁移端点 | b0.4 / b5,b6,b10 | 整句 STT/格式/错误/有界/最终一次 decode；C22 的 HA 端点责任需查真实 API |
| P7A-C19 | STT → HA | 保留/迁移端点 | b0.4 / b5,b6,b10 | 整句 STT/格式/错误/有界/最终一次 decode；C22 的 HA 端点责任需查真实 API |
| P7A-C20 | STT → HA | 保留/迁移端点 | b0.4 / b5,b6,b10 | 整句 STT/格式/错误/有界/最终一次 decode；C22 的 HA 端点责任需查真实 API |
| P7A-C21 | STT 请求 → STT 请求 | 保留/迁移端点 | b0.4 / b5,b6,b10 | 整句 STT/格式/错误/有界/最终一次 decode；C22 的 HA 端点责任需查真实 API |
| P7A-C22 | HA STT Pipeline → P7A | 保留/迁移端点 | b0.4 / b5,b6,b10 | 整句 STT/格式/错误/有界/最终一次 decode；C22 的 HA 端点责任需查真实 API |
| P7A-C23 | TTS 模型 → OfflineTts | 保留 | b0.4,b0.5 / b5,b7,b10 | TTS/并发/网络/隐私/隔离及停止回归，不引入直接调用 |
| P7A-C24 | HA → TTS | 保留 | b0.4,b0.5 / b5,b7,b10 | TTS/并发/网络/隐私/隔离及停止回归，不引入直接调用 |
| P7A-C25 | HA → TTS | 保留 | b0.4,b0.5 / b5,b7,b10 | TTS/并发/网络/隐私/隔离及停止回归，不引入直接调用 |
| P7A-C26 | TTS → HA | 保留 | b0.4,b0.5 / b5,b7,b10 | TTS/并发/网络/隐私/隔离及停止回归，不引入直接调用 |
| P7A-C27 | TTS → HA | 保留 | b0.4,b0.5 / b5,b7,b10 | TTS/并发/网络/隐私/隔离及停止回归，不引入直接调用 |
| P7A-C28 | TTS → HA | 保留 | b0.4,b0.5 / b5,b7,b10 | TTS/并发/网络/隐私/隔离及停止回归，不引入直接调用 |
| P7A-C29 | TTS → HA | 保留 | b0.4,b0.5 / b5,b7,b10 | TTS/并发/网络/隐私/隔离及停止回归，不引入直接调用 |
| P7A-C30 | TTS → HA | 保留 | b0.4,b0.5 / b5,b7,b10 | TTS/并发/网络/隐私/隔离及停止回归，不引入直接调用 |
| P7A-C31 | TTS → HA | 保留 | b0.4,b0.5 / b5,b7,b10 | TTS/并发/网络/隐私/隔离及停止回归，不引入直接调用 |
| P7A-C32 | 多请求 → 服务 | 保留 | b0.4,b0.5 / b5,b7,b10 | TTS/并发/网络/隐私/隔离及停止回归，不引入直接调用 |
| P7A-C33 | 容器 → 模型目录 | 保留/条件迁移 | b0.4,b0.6 / b5,b9,b10 | 保持现有 STT/TTS 与服务；是否取消 wake Provider/模型需确认其他消费者，健康/性能相应调整 |
| P7A-C34 | 容器 → 运维 | 保留/条件迁移 | b0.4,b0.6 / b5,b9,b10 | 保持现有 STT/TTS 与服务；是否取消 wake Provider/模型需确认其他消费者，健康/性能相应调整 |
| P7A-C35 | 服务 → 运维 | 保留/条件迁移 | b0.4,b0.6 / b5,b9,b10 | 保持现有 STT/TTS 与服务；是否取消 wake Provider/模型需确认其他消费者，健康/性能相应调整 |
| P7A-C36 | P7A → 网络 | 保留 | b0.4,b0.5 / b5,b7,b10 | TTS/并发/网络/隐私/隔离及停止回归，不引入直接调用 |
| P7A-C37 | P7A → 日志 | 保留 | b0.4,b0.5 / b5,b7,b10 | TTS/并发/网络/隐私/隔离及停止回归，不引入直接调用 |
| P7A-C38 | HA Pipeline → P3 Agent | 迁移 | b0.4 / b5,b10 | 本地 wake 确认后 STT→本地 intent/AstrBot/TTS，未唤醒不能触达 |
| P7A-C39 | P7A → P5/P6 | 保留/条件迁移 | b0.4,b0.6 / b5,b9,b10 | 保持现有 STT/TTS 与服务；是否取消 wake Provider/模型需确认其他消费者，健康/性能相应调整 |
| P7A-C40 | Tivoo 实际麦克风 → KWS | 替代声学验收 | b0.3 / b4,b10 | 真实双麦 WakeNet，不将旧 NAS 声学项标 PASS |
| P7A-C41 | ESP32 → HA | 迁移 | b0.3,b0.4 / b3,b5,b6,b10 | 物理采集与设备端点 |
| P7A-C42 | HA TTS Proxy → ESP32 | 迁移 | b0.3 / b3,b7,b10 | 实际下行、DAC 及取消 |
| P7A-C43 | ESP32 ↔ Tivoo | 迁移 | b0.2,b0.3 / b2,b3,b10 | SPP 与双板并发 |
| P7A-C44 | P7A 容器 → AstrBot | 保留 | b0.4,b0.5 / b5,b7,b10 | TTS/并发/网络/隐私/隔离及停止回归，不引入直接调用 |

## [2026-11-11-p5-esp32-minimal-firmware-contract-matrix.md](2026-11-11-p5-esp32-minimal-firmware-contract-matrix.md)（25 项）

| 原 ID | 原合同主题（完整规则见原矩阵） | 归属 | 设计 / 实施及回归 | 迁移理由与验收方向 |
|---|---|---|---|---|
| P5-C01 | 开发环境锁定 ESP-IDF v6.1、target esp32 和完整组件依赖图；不得随 P6/P7/P8 漂移 | 迁移 | b0.2,b0.3 / b1,b3,b4,b10 | 两个独立构建、各自内存/组件/烧录清单；原单 target 配置不照搬 |
| P5-C02 | ARM64 主机能使用 EIM 获取 v6.1 Xtensa 工具链并完成原生交叉编译 | 迁移 | b0.2,b0.3 / b1,b3,b4,b10 | 两个独立构建、各自内存/组件/烧录清单；原单 target 配置不照搬 |
| P5-C03 | ESP-SR 2.6.1、Audio Codec 2.6.2、Audio Effects 1.4.5 在同一 ESP32 target 组合编译/链接 | 迁移 | b0.2,b0.3 / b1,b3,b4,b10 | 两个独立构建、各自内存/组件/烧录清单；原单 target 配置不照搬 |
| P5-C04 | Classic SPP API 使用 IDF v6.1 Bluedroid；生成配置启用 BT/Controller/Bluedroid/Classic/SPP，并确认派生的 SMP=y；不得以 NimBLE 或 ESP32-S3-only API 替代 | 迁移 | b0.2 / b2,b10 | 经典板保持 SPP/MAC/配对/NVS/FIFO/分帧；新 UART 路径回归 |
| P5-C05 | I²S Standard TX/RX 以同 Controller 全双工 API 可编译 | 迁移 | b0.2,b0.3 / b1,b3,b4,b10 | 两个独立构建、各自内存/组件/烧录清单；原单 target 配置不照搬 |
| P5-C06 | WROVER-E-N16R8 的 16MB Flash、Quad ESP-PSRAM64、40MHz PSRAM 与 IDF v6.1 bank switching 配置正确；实测 8MiB PSRAM 可分为线性 heap 与 himem 物理池，具体容量按 `CONFIG_SPIRAM_BANKSWITCH_RESERVE` 和 IDF 映射窗口计算，不要求两池严格各 4MiB | 迁移 | b0.2,b0.3 / b1,b3,b4,b10 | 两个独立构建、各自内存/组件/烧录清单；原单 target 配置不照搬 |
| P5-C07 | Wi-Fi Station 成功关联 WLAN 并获得 IP 后启动 7777/7778；HA 旧 Config Entry 迁移后须配置 `esp32_host` 才可连接 | 迁移 | b0.2 / b1,b2,b5,b10 | S3 Wi-Fi/端口/HELLO/日志; 真状态不由 UART 连通推断 |
| P5-C08 | ESP32 以 IPv4 `AF_INET/SOCK_STREAM/IPPROTO_IP` 服务端固定监听 7777 与 7778；每端口只接受一个 HA client | 迁移 | b0.2 / b1,b2,b5,b10 | S3 Wi-Fi/端口/HELLO/日志; 真状态不由 UART 连通推断 |
| P5-C09 | 7777 接受 7-byte `0x69+MAC`、7-byte `0x96+MAC` 和完整 Tivoo raw frame；先做逐字节命令/数据分流，再独立累积 7-byte 控制命令并复用上游 frame parser；所有操作 FIFO 进入 SPP worker | 迁移 | b0.2 / b2,b10 | 经典板保持 SPP/MAC/配对/NVS/FIFO/分帧；新 UART 路径回归 |
| P5-C10 | SPP initiator 使用已配置 MAC，经 SDP 查找 RFCOMM SCN；上游服务发现失败/超时/无 SCN 时使用 SCN 1；连接/每帧 WRITE_EVT 完成/断开严格 FIFO | 迁移 | b0.2 / b2,b10 | 经典板保持 SPP/MAC/配对/NVS/FIFO/分帧；新 UART 路径回归 |
| P5-C11 | TCP 拆包/粘包时只转发完整原始 Tivoo frame；控制命令与数据帧采用互斥状态的流解析规则，数据帧复用上游 frame-stream parser；TCP client 断开清空 parser state 但不自动断开 SPP | 迁移 | b0.2 / b2,b10 | 经典板保持 SPP/MAC/配对/NVS/FIFO/分帧；新 UART 路径回归 |
| P5-C12 | 7777 只做 HA→ESP32→SPP；不实现 SPP DATA_IND 回传/确认 | 替代历史阶段边界 | b0.2,b0.4 / b2,b5,b10 | P6 已有 reverse/heartbeat/音频；不恢复旧单向或无音频限制 |
| P5-C13 | 7778 使用 TVIO magic、version 1、16-byte header 和 P5 message subset | 迁移 | b0.2 / b1,b2,b5,b10 | S3 Wi-Fi/端口/HELLO/日志; 真状态不由 UART 连通推断 |
| P5-C14 | HELLO/HELLO_ACK 字段及 accepted/reject 语义符合 §7.3 | 迁移 | b0.2 / b1,b2,b5,b10 | S3 Wi-Fi/端口/HELLO/日志; 真状态不由 UART 连通推断 |
| P5-C15 | DIAGNOSTIC_LOG / ERROR 使用 §7.3 固定 JSON fields、level enum 和 P5 `error_code` enum | 迁移 | b0.2 / b1,b2,b5,b10 | S3 Wi-Fi/端口/HELLO/日志; 真状态不由 UART 连通推断 |
| P5-C16 | Reset Reason、firmware version、device ID 在启动 handshake 上报 | 迁移 | b0.2 / b1,b2,b5,b10 | S3 Wi-Fi/端口/HELLO/日志; 真状态不由 UART 连通推断 |
| P5-C17 | 日志队列有界、非阻塞；网络断线不阻塞 SPP；重连后补传，队列满报告 dropped_count | 迁移 | b0.2 / b1,b2,b5,b10 | S3 Wi-Fi/端口/HELLO/日志; 真状态不由 UART 连通推断 |
| P5-C18 | HA 使用标准 Tivoo logger，日志由 HA 主日志和现有 NAS /config volume 持久化 | 迁移 | b0.2 / b1,b2,b5,b10 | S3 Wi-Fi/端口/HELLO/日志; 真状态不由 UART 连通推断 |
| P5-C19 | 凭据、PCM 和完整对话文本不出现在固件日志 | 迁移 | b0.2 / b1,b2,b5,b10 | S3 Wi-Fi/端口/HELLO/日志; 真状态不由 UART 连通推断 |
| P5-C20 | ARM64 生成可独立刷写的 16MiB merged image、app-only image、flash arguments、版本清单和 SHA256；NAS 常驻 esptool 仅作为本地板卡刷写/串口验证工具，不承担构建 | 迁移 | b0.2,b0.3 / b1,b3,b4,b10 | 两个独立构建、各自内存/组件/烧录清单；原单 target 配置不照搬 |
| P5-C21 | P5 不实现完整 7777 reverse channel、7778 heartbeat/DEVICE_STATUS/audio messages、HTTP audio、I²S/AEC/VAD | 替代历史阶段边界 | b0.2,b0.4 / b2,b5,b10 | P6 已有 reverse/heartbeat/音频；不恢复旧单向或无音频限制 |
| P5-C22 | HA Config Entry 的 `tivoo_bluetooth_mac` 是 Tivoo Classic SPP 目标地址的唯一权威来源；用户用手机确认 `Tivoo-audio` Classic MAC 后手动填写；ESP32 不持有固定/备用 MAC，不扫描或自动选择设备；`Tivoo-light` BLE 地址不得代替 | 迁移 | b0.2 / b2,b10 | 经典板保持 SPP/MAC/配对/NVS/FIFO/分帧；新 UART 路径回归 |
| P5-C23 | 更换 Tivoo 只修改 HA Config Entry 的 MAC；HA reload 后在新 7777 会话发送新 `0x69+MAC`，ESP32 有序断开旧 SPP peer 并连接新地址，不要求修改/重刷固件，也不再向旧设备发帧 | 迁移 | b0.2 / b2,b10 | 经典板保持 SPP/MAC/配对/NVS/FIFO/分帧；新 UART 路径回归 |
| P5-C24 | SPP 首次配对显式声明 `ESP_BT_IO_CAP_NONE`；按合同处理 Legacy `PIN_REQ`，对没有本机显示/输入能力的 SSP 数字确认或 passkey 交互路径 fail-closed。首次配对/新 Link Key 路径必须捕获 `AUTH_CMPL` 的目标地址、状态和 link-key type；仅当目标地址匹配且 status=0、Bond List 随后包含目标设备时才可放行。复用 NVS 中已有 Bond Key 时，Bluedroid 不保证再次发出成功 `AUTH_CMPL`；此时要求目标 MAC 在连接前已存在 Bond List、RFCOMM `OPEN_EVT status=0`（由 `ESP_SPP_SEC_AUTHENTICATE | 迁移 | b0.2 / b2,b10 | 经典板保持 SPP/MAC/配对/NVS/FIFO/分帧；新 UART 路径回归 |
| P5-C25 | Bluedroid 原生 Bond Key 持久化到 NVS；NVS 在 Bluetooth 初始化前就绪，运行时不得因常规 NVS 初始化错误自动擦除整个 NVS；相同 Tivoo 在 ESP32 软件重启/完全断电后复用已保存密钥，无需重复人工配对；不建立应用层密钥副本、不记录密钥/PIN/passkey | 迁移 | b0.2 / b2,b10 | 经典板保持 SPP/MAC/配对/NVS/FIFO/分帧；新 UART 路径回归 |

## [2026-11-12-p6-esp32-ha-bidirectional-contract-matrix.md](2026-11-12-p6-esp32-ha-bidirectional-contract-matrix.md)（20 项）

| 原 ID | 原合同主题（完整规则见原矩阵） | 归属 | 设计 / 实施及回归 | 迁移理由与验收方向 |
|---|---|---|---|---|
| P6-C01 | P5 的端口、MAC 来源、Tivoo 原始帧和 P5 7778 codec 行为保持兼容 | 迁移 | b0.2 / b2,b10 | 7777 原始双向/状态/断开隔离/桥重连和真实 SPP |
| P6-C02 | 7777 SPP DATA_IND 原始回传到当前 TCP client | 迁移 | b0.2 / b2,b10 | 7777 原始双向/状态/断开隔离/桥重连和真实 SPP |
| P6-C03 | 7777 兼容单字节 0x69/0x96 状态提示，不创建命令级 ACK | 迁移 | b0.2 / b2,b10 | 7777 原始双向/状态/断开隔离/桥重连和真实 SPP |
| P6-C04 | 反向数据使用有界队列，不阻塞 SPP callback；TCP 断开不影响 SPP | 迁移 | b0.2 / b2,b10 | 7777 原始双向/状态/断开隔离/桥重连和真实 SPP |
| P6-C05 | TVIO v1 双向 codec 支持所有 P6 message type，拆包/粘包和 Sequence 正确 | 迁移 | b0.2,b0.4 / b2,b5,b10 | TVIO 兼容、能力、heartbeat、序号与脱敏错误；新事件只由分域规格定 |
| P6-C06 | HELLO 扩展能力声明；HELLO_ACK 保持 accepted/reason 简单格式 | 迁移 | b0.2,b0.4 / b2,b5,b10 | TVIO 兼容、能力、heartbeat、序号与脱敏错误；新事件只由分域规格定 |
| P6-C07 | HA PING 每 15 秒；45 秒未收到 PONG 后只重连 7778 | 迁移 | b0.2,b0.4 / b2,b5,b10 | TVIO 兼容、能力、heartbeat、序号与脱敏错误；新事件只由分域规格定 |
| P6-C08 | GET_STATUS 返回真实 Wi-Fi/TCP/SPP/HTTP resource 状态，request_id 正确回显 | 迁移 | b0.2 / b2,b10 | 7777 原始双向/状态/断开隔离/桥重连和真实 SPP |
| P6-C09 | DEVICE_EVENT 按固定事件名上报，只在状态变化时发送 | 迁移 | b0.2 / b2,b10 | 7777 原始双向/状态/断开隔离/桥重连和真实 SPP |
| P6-C10 | ERROR 扩展 P6 error_code；P5 log/error 仍工作且敏感字段脱敏 | 迁移 | b0.2,b0.4 / b2,b5,b10 | TVIO 兼容、能力、heartbeat、序号与脱敏错误；新事件只由分域规格定 |
| P6-C11 | MIC_START/PCM/END/CAPTURE_STOP schema 和 bounded dispatch 接口完成 | 迁移 | b0.4 / b5,b6,b10 | 有界 PCM、按轮边界及尾帧结束 |
| P6-C12 | TTS URL 由 HA Core 内网 URL helper 构造，无新增配置项；不单独传 Bearer/token | 迁移 | b0.3,b0.5 / b3,b7,b10 | 普通 TTS LAN URL/HTTP 流、有界、ID 定向 stop/真实终态 |
| P6-C13 | TTS_PLAY 触发 ESP-IDF HTTP GET，校验状态码和 Content-Type | 迁移 | b0.3,b0.5 / b3,b7,b10 | 普通 TTS LAN URL/HTTP 流、有界、ID 定向 stop/真实终态 |
| P6-C14 | HTTP response body 按块流式交给 reader，未知 Content-Length 可用，不缓存完整文件 | 迁移 | b0.3,b0.5 / b3,b7,b10 | 普通 TTS LAN URL/HTTP 流、有界、ID 定向 stop/真实终态 |
| P6-C15 | 同时只允许一个 HTTP resource GET；重复/过期 AUDIO_STOP 按 playback_id 处理且幂等 | 迁移 | b0.3,b0.5 / b3,b7,b10 | 普通 TTS LAN URL/HTTP 流、有界、ID 定向 stop/真实终态 |
| P6-C16 | HTTP 错误和资源状态正确回报；P6 不把 resource_ready 说成 playback completed | 迁移 | b0.3,b0.5 / b3,b7,b10 | 普通 TTS LAN URL/HTTP 流、有界、ID 定向 stop/真实终态 |
| P6-C17 | 7777/7778 独立重连；7778 断开不重置 SPP；7777 断开不停止 7778 | 迁移 | b0.2 / b2,b10 | 7777 原始双向/状态/断开隔离/桥重连和真实 SPP |
| P6-C18 | P6 不实现 I²S RX/AEC/VAD、codec/SRC、I²S TX/播放管理器或完整 Assist Pipeline | 替代历史阶段边界 | b0.3,b0.4 / b3,b5,b10 | P6.5 已提供实际音频；不恢复历史不实施限制 |
| P6-C19 | 原始 SPP 反向内容不附加包装；不新增命令级 ACK、消息总线或通用音频代理 | 迁移 | b0.2 / b2,b10 | 7777 原始双向/状态/断开隔离/桥重连和真实 SPP |
| P6-C20 | P5 全量回归通过，新增 P6 单元/集成测试通过，IDF 固件可构建 | 迁移 | b0.6 / b10 | 原测试保留或映射，双板构建和真实回归 |

## [2026-11-13-p6-5-persistent-audio-session-and-kws-interruption-contract-matrix.md](2026-11-13-p6-5-persistent-audio-session-and-kws-interruption-contract-matrix.md)（16 项）

| 原 ID | 原合同主题（完整规则见原矩阵） | 归属 | 设计 / 实施及回归 | 迁移理由与验收方向 |
|---|---|---|---|---|
| P65-A01 | 常驻采集 | 迁移 | b0.3 / b3,b4,b10 | AFE 常驻、双麦和播放/桥并发，不以数字链证明声学 |
| P65-A02 | 首次 VAD 上传 | 替代 | b0.4 / b5,b9,b10 | 本地 wake 替代首 VAD 上传和远程候选 3/15s；待机零上行且可重唤醒 |
| P65-A03 | wakeword miss | 替代 | b0.4 / b5,b9,b10 | 本地 wake 替代首 VAD 上传和远程候选 3/15s；待机零上行且可重唤醒 |
| P65-A04 | wakeword hit 后命令等待 | 替代 | b0.4 / b5,b6,b10 | 先提示音再命令；5s 从有效命令 gate/准备边界确定，取消连说要求 |
| P65-A05 | STT endpoint | 迁移 | b0.4 / b6,b10 | S3 断句与尾帧，HA/Wyoming AudioStop 真实接口核验，不盲关 HA VAD |
| P65-A06 | 跨 Pipeline session | 迁移 | b0.4,b0.5 / b5,b7,b10 | 跨轮 PCM/有界/无旧帧串轮; 物理 MIC session 语义允许依新合同调整 |
| P65-A07 | partial SSE 取消 | 迁移 | b0.5 / b7,b10 | 显式取消与资源 owner、普通 VAD 无打断权、WakeNet 全阶段打断、授权 follow-up/代次隔离 |
| P65-A08 | 活动 TTS 取消 | 迁移 | b0.5 / b7,b10 | 显式取消与资源 owner、普通 VAD 无打断权、WakeNet 全阶段打断、授权 follow-up/代次隔离 |
| P65-A09 | HTTP GET 对照 | 迁移 | b0.5 / b7,b10 | 显式取消与资源 owner、普通 VAD 无打断权、WakeNet 全阶段打断、授权 follow-up/代次隔离 |
| P65-A10 | VAD 误触发防护 | 迁移 | b0.5 / b7,b10 | 显式取消与资源 owner、普通 VAD 无打断权、WakeNet 全阶段打断、授权 follow-up/代次隔离 |
| P65-A11 | KWS 确认打断 | 迁移 | b0.5 / b7,b10 | 显式取消与资源 owner、普通 VAD 无打断权、WakeNet 全阶段打断、授权 follow-up/代次隔离 |
| P65-A12 | AstrBot/SSE 阶段打断 | 迁移 | b0.5 / b7,b10 | 显式取消与资源 owner、普通 VAD 无打断权、WakeNet 全阶段打断、授权 follow-up/代次隔离 |
| P65-A13 | TTS 回声负样本 | 迁移 | b0.3,b0.5 / b4,b7,b10 | 真实 TTS 声学负样本、回声及含词样本 |
| P65-A14 | 全双工 DAC | 迁移 | b0.3 / b3,b4,b10 | AFE 常驻、双麦和播放/桥并发，不以数字链证明声学 |
| P65-A15 | follow-up 窗口 | 迁移 | b0.5 / b7,b10 | 显式取消与资源 owner、普通 VAD 无打断权、WakeNet 全阶段打断、授权 follow-up/代次隔离 |
| P65-A16 | generation 隔离 | 迁移 | b0.5 / b7,b10 | 显式取消与资源 owner、普通 VAD 无打断权、WakeNet 全阶段打断、授权 follow-up/代次隔离 |

## [2026-11-14-tivoo-expression-state-machine-contract-matrix.md](2026-11-14-tivoo-expression-state-machine-contract-matrix.md)（23 项）

| 原 ID | 原合同主题（完整规则见原矩阵） | 归属 | 设计 / 实施及回归 | 迁移理由与验收方向 |
|---|---|---|---|---|
| ESM-C01 | Tivoo GIF/多帧表情不以“播放完成”作为恢复依据；任意业务状态退出后由 HA `recompute` 主动发送下一赢家 | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |
| ESM-C02 | 没有更高 intent 时必须存在 `idle` 兜底；idle 首期只从当前已存在的 `standby/smiley/sleepy/sun/fish` 选取 | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |
| ESM-C03 | idle 首期 30–90 秒随机换一次；空闲候选人声约持续 700 ms 后按 35% 概率显示 `active_listening`，10 秒冷却 | 部分替代 | b0.5 / b8,b10 | 保留 idle 30–90s 随机轮换，删除候选 700ms/35%/10s 显示 |
| ESM-C04 | 有效首轮 `WAKE_WORD_END.wake_word_output` 或 side KWS Detection 必须 100% 提交 `wake_confirmed` | 替代事件来源 | b0.5 / b7,b8,b10 | S3 确认、有效命令和真实回复完成+授权；提示音不算回复 |
| ESM-C05 | `thinking` 只能在当前非错误、已开始命令的 turn 到达 `STT_END` 后进入；不得从 `STT_START` 提前进入 | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |
| ESM-C06 | 当前 Tivoo satellite 的 AstrBot `tool_call` 提交 `tooluse`；对应 `tool_call_result` 移除它并重新仲裁 | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |
| ESM-C07 | `speaking` 只由当前 playback id 的真实 `AUDIO_STATE=playing` 进入；`completed/stopped/interrupted/failed` 退出 | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |
| ESM-C08 | 仅当前 turn 的 `continue_conversation=true` 且 `AUDIO_STATE=completed` 后进入 8 秒 follow-up；等待期可显示弱 `followup_wait`，新的 `speech_start` 再进入 active listening/STT。`false`/缺失时结束会话并回 idle | 替代事件来源 | b0.5 / b7,b8,b10 | S3 确认、有效命令和真实回复完成+授权；提示音不算回复 |
| ESM-C09 | 覆盖顺序固定为：`wake_confirmed > speaking > tooluse > thinking > active_listening > explicit_content > ai_mood > followup_wait > idle` | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |
| ESM-C10 | 每个会话级 intent 必须绑定当前 turn/generation；旧轮取消、失败、session end、follow-up timeout 或新 generation 替换时统一清除旧 intents；迟到事件不得恢复旧画面 | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |
| ESM-C11 | AI mood 只能提交低优先级、session-scoped、有限 TTL 的 mood intent；首期 TTL 5 秒；不自动从回答文本做情绪分类 | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |
| ESM-C12 | AI mood 白名单首期限定当前已有 `happy/sad/angry/love/cool/cry/laugh/sleepy/shock/wink/sick/party/kiss/oops`；系统状态表情不进入 mood 白名单 | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |
| ESM-C13 | 后续可增加项目自有 mood Tool；它必须提交 intent 而不是直接发送 SPP。规格中建议名 `tivoo__SetMood` 仅是项目接口命名，不是上游 Tivoo API | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |
| ESM-C14 | 用户/自动化明确要求的 `SetExpression/ShowImage/ShowText` 等属于 `explicit_content`；瞬态系统状态可覆盖，退出后若内容仍有效则恢复 | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |
| ESM-C15 | ScreenPowerGate 为硬门控：OFF 时所有 idle/会话/mood/explicit content 只能更新 desired state，不得下发可见内容 | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |
| ESM-C16 | 底层屏幕电源继续复用现有 `tivoo.set_screen_power(value: bool)` / `tivoo__SetScreenPower`；不得新增 raw SPP 息屏协议 | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |
| ESM-C17 | 多来源息屏在内部使用 owner inhibit：任一 owner 未释放则 gate 仍为 OFF；现有公开 bool service/MCP 保持兼容并只能映射到固定 compatibility owner。需要独立 owner 的自动化/AI 必须走 Coordinator 稳定 owner 路径；公开 owner schema 留待实现批次定义 | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |
| ESM-C18 | 预留内部 `temporary_wake(owner, ttl)`：只临时绕过 gate，不删除 inhibit；到期后若仍有 inhibit 必须再次 OFF | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |
| ESM-C19 | OFF→ON 后必须立刻 recompute 并重新发送当前赢家；SPP 重连时 OFF 要重申 OFF，ON 要重发赢家；重载后已连 SPP 的初始已校验 DEVICE_STATUS 也应触发一次同步；ESP32 单独 reset 后若其已校验 `tcp["7777"]` 与 HA 旧 control socket 状态冲突，必须回收 stale 7777 并走既有重连 | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |
| ESM-C20 | HA 的 `desired_state/last_sent` 是本状态机权威；`last_sent` 只证明 transport 写入，不证明物理像素；当前不得从 opaque SPP reverse 推导“当前表情/当前像素” | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |
| ESM-C21 | 状态表情优先复用现有 preset；若后续新增专用 listening/speaking 动画，只替换角色到 preset 的映射，不改变状态机事件/优先级合同 | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |
| ESM-C22 | 未来主动告警/主动播报必须复用同一 ScreenPowerGate/ExpressionCoordinator；其 announce/start-conversation 调用接口由后续独立规格核对后再定义 | 延后 | P9 / b8,b10 保持复用约束 | 主动对话/播报后置，不另建仲裁 |
| ESM-C23 | 表情状态机不得改变 P6.5 的 VAD/KWS 打断权、8 秒 follow-up、playback id/generation 规则，也不得改变 P3 的 SSE 可见文本和 Stop owner | 保留/迁移事件 | b0.5 / b8,b10 | 原 HA 唯一仲裁、mood/screen/TTL/显式内容；匹配新真实事件与 SPP 状态，C13 已实现，C18 仅内部 |

## [2026-11-16-p6-7-ready-prompt-sound-contract-matrix.md](2026-11-16-p6-7-ready-prompt-sound-contract-matrix.md)（21 项）

| 原 ID | 原合同主题（完整规则见原矩阵） | 归属 | 设计 / 实施及回归 | 迁移理由与验收方向 |
|---|---|---|---|---|
| PR-C01 | 只在首次有效 `WAKE_WORD_END`、确认打断产生的命令等待、每轮实际 follow-up 等待各播放最多一次；`VAD` 候选、每个 `STT_START`、普通 TTS 生成不得误触发 | 迁移 | b0.4,b0.5 / b6,b7,b8,b10 | 本地素材/独立嘟声、提示音 gate、参考时间轴、唯一音频 owner、故障跳过；不把旧 HTTP/48ms 当新合同 |
| PR-C02 | 首次命中且有可用素材时，结束旧 wake Pipeline，等待提示音终态后以新鲜 PCM 启动 STT；5 秒从新 STT_START 起计，wake tail 不得取消提示音或进入命令 | 迁移 | b0.4,b0.5 / b6,b7,b8,b10 | 本地素材/独立嘟声、提示音 gate、参考时间轴、唯一音频 owner、故障跳过；不把旧 HTTP/48ms 当新合同 |
| PR-C03 | 确认打断后旧 turn owner 清理优先；新轮 STT_START 才启动 5 秒，MIC handoff 即使提示音未发出也不能丢 | 迁移 | b0.4,b0.5 / b6,b7,b8,b10 | 本地素材/独立嘟声、提示音 gate、参考时间轴、唯一音频 owner、故障跳过；不把旧 HTTP/48ms 当新合同 |
| PR-C04 | 仅当当前 turn 的 `INTENT_END.intent_output.continue_conversation` 严格为 `true` 时，跟随实际正常 TTS `completed` 或无 TTS 的有效响应打开 8 秒 follow-up；`false`/缺失时结束 MIC session；提示音 `completed` 不得打开 follow-up | 迁移 | b0.5 / b7,b10 | 严格 continue_conversation、真实回复完毕（无 TTS 有效响应例外需核对）、8s，取消错误不续轮 |
| PR-C05 | 非提示音 gate 期间的 follow-up `speech_start` 仍立刻启动免唤醒词 STT。提示音 gate 内不产生新的 VAD/MIC_ACTIVITY/MIC_PCM；整句完全落在该短窗口内可能被忽略，这是明确产品取舍。gate 恢复后下一次 `speech_start` 仍按原逻辑启动 STT | 迁移 | b0.4,b0.5 / b6,b7,b8,b10 | 本地素材/独立嘟声、提示音 gate、参考时间轴、唯一音频 owner、故障跳过；不把旧 HTTP/48ms 当新合同 |
| PR-C06 | `suppress_vad=true` 的提示音 gate 中 MIC RX/AFE/AEC 必须持续；VAD/MIC_ACTIVITY/MIC_PCM 向 HA 的输出明确暂停，已有 speech 状态最多归零一次。禁止停 RX/AEC，也禁止把 gate 扩大到普通 TTS | 迁移 | b0.4,b0.5 / b6,b7,b8,b10 | 本地素材/独立嘟声、提示音 gate、参考时间轴、唯一音频 owner、故障跳过；不把旧 HTTP/48ms 当新合同 |
| PR-C07 | 四个预制短 MP3：`ready_01`…`ready_03`（“我在/在的/你说”）和 follow-up 专属 `followup_01`（单次短“嘟”声）；32 kHz、mono、`audio/mpeg`、目标 ≤0.9 秒。三条 ready 必须由当前生产 HA 实际 TTS Provider/模型/voice 参数一次性生成；follow-up 为固定短正弦提示音、不经过 TTS；均前后保留短静音，运行时不合成 | 迁移 | b0.4,b0.5 / b6,b7,b8,b10 | 本地素材/独立嘟声、提示音 gate、参考时间轴、唯一音频 owner、故障跳过；不把旧 HTTP/48ms 当新合同 |
| PR-C08 | `ready/wake/confirmed` 只从 `ready_01..03` 随机选择且相邻两次不同；`followup` 只使用 `followup_01` 并允许跨 generation 重复。对应素材缺失时静默跳过，不回退到其它素材池、不产生推理或影响语音转移 | 迁移 | b0.4,b0.5 / b6,b7,b8,b10 | 本地素材/独立嘟声、提示音 gate、参考时间轴、唯一音频 owner、故障跳过；不把旧 HTTP/48ms 当新合同 |
| PR-C09 | 生产 URL 使用 HA 内网基址 `/local/tivoo/prompts/<固定文件>.mp3`；ESP32 GET 200，Content-Type 为 `audio/mpeg`，不经认证重定向、不可使用外网/Cloud 位置 | 删除旧路径 | b0.4 / b6,b9,b10 | 本地 Flash 资产取代 HA 静态 HTTP |
| PR-C10 | 不扩大 `build_internal_tts_url()` 的 `/api/tts_proxy/` 限制；提示音 URL 单独限定为固定本地素材 | 部分替代 | b0.4,b0.5 / b6,b7,b9,b10 | 保留正常 TTS URL 限制与唯一输出；移除远程提示音专用请求/suppress_vad 传输依赖，gate 本地 |
| PR-C11 | 复用现有 `async_send_tts_play()` / `0x30`；只增加可选 `suppress_vad` 布尔字段且默认 false，不新增 message type；ESP32 解码与 I²S TX 仍走唯一 `audio_output_manager`，不得混音或另起 DAC owner | 部分替代 | b0.4,b0.5 / b6,b7,b9,b10 | 保留正常 TTS URL 限制与唯一输出；移除远程提示音专用请求/suppress_vad 传输依赖，gate 本地 |
| PR-C12 | 每个提示音具有区别于正常 TTS 的独立 `playback_id`，`AUDIO_STATE.source` 仍是 `tts_http`；**按 ID** 分发给提示音 owner 或 `_Turn.tts`，不可按 `source` 猜音频种类 | 迁移 | b0.4,b0.5 / b6,b7,b8,b10 | 本地素材/独立嘟声、提示音 gate、参考时间轴、唯一音频 owner、故障跳过；不把旧 HTTP/48ms 当新合同 |
| PR-C13 | 正常回答的 `playing/completed/stopped/failed` 行为、P6.6 speaking 表情与 follow-up 只接受当前真实 TTS ID；提示音终态绝不触发它们 | 迁移 | b0.4,b0.5 / b6,b7,b8,b10 | 本地素材/独立嘟声、提示音 gate、参考时间轴、唯一音频 owner、故障跳过；不把旧 HTTP/48ms 当新合同 |
| PR-C14 | 新 turn/session 取消旧待发任务；旧 generation 迟到 `AUDIO_STATE` 或 stop 不能取消/覆盖新提示音或正常 TTS；重复入口不重复发声 | 迁移 | b0.4,b0.5 / b6,b7,b8,b10 | 本地素材/独立嘟声、提示音 gate、参考时间轴、唯一音频 owner、故障跳过；不把旧 HTTP/48ms 当新合同 |
| PR-C15 | 播放占用互斥：旧 TTS 尚在活动时不抢占；提示音占用时正常 TTS 下发前必须先自然结束或定向停止并确认设备释放；不以设备 `audio_busy` 作为正常仲裁 | 迁移 | b0.4,b0.5 / b6,b7,b8,b10 | 本地素材/独立嘟声、提示音 gate、参考时间轴、唯一音频 owner、故障跳过；不把旧 HTTP/48ms 当新合同 |
| PR-C16 | 首次唤醒的旧 Pipeline 事件不得取消待播提示音；其它入口有效命令开始时优先用户：未发出的提示音直接取消，已播放提示音仅允许匹配自身 ID 的 `AUDIO_STOP`；不得发无 ID 的 STOP 或停正常回答 | 迁移 | b0.4,b0.5 / b6,b7,b8,b10 | 本地素材/独立嘟声、提示音 gate、参考时间轴、唯一音频 owner、故障跳过；不把旧 HTTP/48ms 当新合同 |
| PR-C17 | 短提示音仍取最终 TX PCM 作为 AEC R，全局 `vad_mute_playback=false`；仅 `suppress_vad=true` 提示音在真实输出期间 runtime disable/reset VAD，并暂停 MIC_ACTIVITY/MIC_PCM。数字输出结束后按已标定 760 samples / 47.5 ms 声学尾部（实现 48 ms）再 enable/reset；普通 TTS VAD/MIC/KWS 打断不受影响 | 迁移 | b0.4,b0.5 / b6,b7,b8,b10 | 本地素材/独立嘟声、提示音 gate、参考时间轴、唯一音频 owner、故障跳过；不把旧 HTTP/48ms 当新合同 |
| PR-C18 | 提示音 gate 内不得出现由提示音造成的 VAD speech_start、MIC_ACTIVITY 或 MIC_PCM 上送；用户语音在该 gate 内被有意忽略。gate 关闭后必须立即恢复检测；同一音频以普通 TTS（无 `suppress_vad`）播放时必须仍能产生 VAD/MIC，证明正常 TTS 打断链未被全局关闭 | 迁移 | b0.4,b0.5 / b6,b7,b8,b10 | 本地素材/独立嘟声、提示音 gate、参考时间轴、唯一音频 owner、故障跳过；不把旧 HTTP/48ms 当新合同 |
| PR-C19 | 提示音文件 HTTP 异常、DAC busy、断线、超时均安静跳过；不能把当前 Pipeline 标为失败、永久阻塞取消/收音或遗留音频 request；断连/真实 TTS 发送失败按 ID 释放 HA TTS 占用；首次提示音等待上限 5 秒 | 迁移 | b0.4,b0.5 / b6,b7,b8,b10 | 本地素材/独立嘟声、提示音 gate、参考时间轴、唯一音频 owner、故障跳过；不把旧 HTTP/48ms 当新合同 |
| PR-C20 | 新增提示音不改 P6.6 screen power gate/idle/priority，不触发 AstrBot SSE、ChatLog、LLM/工具调用或新对话 | 迁移 | b0.4,b0.5 / b6,b7,b8,b10 | 本地素材/独立嘟声、提示音 gate、参考时间轴、唯一音频 owner、故障跳过；不把旧 HTTP/48ms 当新合同 |
| PR-C21 | NAS 实际部署包含三个静态文件，验证 LAN HTTP 获取/解码、真实输出/回声；b0/b1/b2 只表示独立软件证据，不冒充 b3 真人声学 PASS | 迁移 | b0.4,b0.5 / b6,b7,b8,b10 | 本地素材/独立嘟声、提示音 gate、参考时间轴、唯一音频 owner、故障跳过；不把旧 HTTP/48ms 当新合同 |

## 无独立矩阵 ID 的后续要求和遗留项

| 追踪项 | 依据 | 处理范围 / 责任 |
|---|---|---|
| H01 P3 独立 GAP | P3 verification、取消规格 §2–8；P6.5b6 真实 partial Stop | session Stop 同身份、单 owner、错误传播、禁止重复请求归 b7/b10；HA restart、24h、生产 key 轮换延后 P3 独立验收，不虚标通过 |
| H02 P4 扩展 | 2026-11-14-tivoo-mcp-spp-capability-expansion 报告及当前 services/llm | 已有全部工具、状态查询、亮度/音量/倒计时/屏幕及本地 intent 保留，b2/b8/b10 |
| H03 P5 未测 | P5 final、memory/bond closeout 与 README：JTAG esp_restart、第二台 Tivoo、长滚动 | 前两项保留原专项非前置；真实长 GIF/SPP 并发与掉线/独立重启 b2/b10 |
| H04 P6 未测 | P6 acceptance §未运行项 1–9 | AP 关闭恢复 b2/b10、生产 HTTPS b3/b10、真实语音音频/取消 b3/b5–b7/b10，长滚动物理像素 b2/b8/b10；JTAG/第二台同 H03 |
| H05 P6.5 b11 GAP | P65-A03/A04/A10/A11/A12/A14/A15；声学报告 | 候选 miss/连说旧流程分别替代，电视/普通人声、真实打断各阶段、双工、follow-up 分别按索引验收；A13 声学负样本也复测 |
| H06 P6.6 b5 GAP | ESM C03/04/05/06/07/08/11/23 runtime；C19 修复 | 删除旧候选显示；真人 voice/tool/mood/playback/follow-up/cancel 及真实桥重连 b8/b10 |
| H07 P6.7 C18/C21 | b3 FAIL/GAP 与 11-16 VAD gate 修复、47.5ms 标定 | 保持旧报告和后续修复；新双麦重测参考/负样本和短提示音 gate、普通播放保持 wake b3/b4/b6/b7/b10 |
| H08 提示音 stale owner / wake 顺序 | 7d2a596、11-17 ready-prompt-wake-order-fix | 先提示音后新鲜命令、失败降级、旧 Pipeline 事件不抢占；新 owner 与并行 HA 预备 b6/b7/b10 |
| H09 TV 连续人声和唤醒词 | 4a7c2b9、d320db5、11-17 TV speech wake rearm 报告 | 旧 15s rearm 只为 NAS 候选；新系统持续监听、真实持续电视对白误/漏唤醒实测 b4/b7/b10；自定义词不照搬到官方模型 |
| H10 长 TTS 截断/网络背压 | 59e1bac、b278dc3 及 P6.5 b10 报告 | 保留间隙填静音、不误终止、诊断队列/终态、分段与有界 reader 修复；普通长回复、断线/错误/stop b3/b7/b10 |
| H11 连续对话与独立提示 | 735ca78、0025556、d79775f、11-17 两份设计 | 保留问号规则、严格 true 与真实完成、独立嘟声、非授权回 idle、拒绝自触发/旧终态 b6/b7/b8/b10 |
| H12 新对话入口 | f7fa300 | 保留已有手动/工具重置入口及 session 语义，b7/b10 回归 |
| H13 原 P7/P8 | README 历史计划、P7A-C40–42、P65-A01–16 | 不再独立实施；真实采集/端点/解码/AEC/唤醒/播放/打断归 b3–b7/b10 |
| H14 原 P9 | README、ESM-C22 | 未实施主动播报/主动对话/自动化入口后置；既有 mood/显式表情不重做 |
| H15 原 P10 | README、P7A-C43 | 单板硬件并发专项被双板稳定性（长 GIF、CPU/IRAM/DRAM/PSRAM、断网、重启）替代，b10；A2DP 备选延后 |
| H16 用户新增硬件/唤醒链 | 路线 §1/1.1 | S3 N16R8-M 双同型 INMP441 + PCM5102；经典板仅 SPP；UART；原生 WakeNet 官方词、待机不上行、提示音后发命令、延迟拆分、表情事件来源 b1–b10；实物未到货/未验收不假定 |
| H17 本地命令优先/口语 | README、HA 生产配置与现有 Assist Pipeline | 保持现有本地优先与 AstrBot fallback；不另造语义学习层；在 b5/b10 验证本地状态查询和真人控制，配置实际内容由 b0.4 核对 |
| H18 GPIO 修复 | 4a14592、firmware README/Kconfig/main.c | WROVER GPIO27 RGB 灭灯、DAC DIN 已迁 GPIO33；S3 引脚/板载 RGB 另查真实板型 b0.2/b1，不能复制旧引脚 |
| H19 旧 RX 时间轴/取消超时/背压修复 | P6.5 后续提交及 b10 报告 | 保持有界 session/播放唯一 owner、取消超时清理以及 AEC 参考时间轴；b3/b5/b7 分域回归，b10 真机 |

历史证据入口：各原矩阵及同阶段 reports；以最新修复说明补充而非覆盖历史 FAIL/GAP。b0.6 逐行核对新合同 ID、测试和实测证据，所有 H 项亦须闭环或明确延后。
