# P6.8 B8.3 — Qwen Frontend MCP 与内网 HTTP 例外验收

> 日期：2026-11-22；基线：`db6e801`；分支：`feature/p6-8-s3-local-wake`。
> 结论：**B8.3 软件交付 PASS**。仅本批代码补丁、占位模板、说明及本地自动化测试。
> 未部署 NAS 配置/补丁，未修改 HA/ESP32 生产代码，未调用真实 HA 工具或刷写固件。

## 交付与范围

- `deploy/nas/qwen/patches/0001-frontend-mcp-private-http.patch`：只修改锁定 Qwen 2.1.0 的 `server/src/frontend/tools/mcp/frontend-mcp-config.mjs`。
- `deploy/nas/qwen/frontend-mcp.json.example`：一个 `homeassistant` Streamable HTTP server；完整 URL 和 Authorization 仅用环境引用；工具键为明确待替换占位符。
- `deploy/nas/qwen/README.md`：来源/hash、最小补丁、真实部署前提、回滚、现有合同能力白名单、HA 权限边界、工具命名及上游配置上限。
- `deploy/nas/qwen/patches/test.sh`、`tests/*.test.mjs`、`test-runtime/package*.json`：隔离临时源码副本中的 RED→GREEN、锁定测试依赖与本地集成测试。

没有新增 HA MCP Server、路由、代理或 GCP Client Action。没有进入 B8.4 及后续批次。

## 锁定源码与 NAS 只读核对

本地 checkout 为上游 QwenAudio/qwen-audio-agent 2.1.0 提交
`a9f4478da8df400d04facbb099ac2933ce8b11bc`。使用用户提供 NAS IPv6、已有可信
`HostKeyAlias=192.168.3.94`、严格 host-key 校验，以 root SSH 仅执行容器内版本及文件 hash 读取。
NAS package.json 显示 **2.1.0**，以下文件与本地锁定源码逐字节 hash 一致：

| 文件（相对 Qwen 安装根目录） | SHA256 |
|---|---|
| server/src/frontend/tools/mcp/frontend-mcp-config.mjs | 361c6bd6afbd73aeb3519991227e7b2688b65004465788095545d3635d0965da |
| server/src/frontend/tools/mcp/frontend-mcp-client.mjs | 21db33a9d524a9decd1ed0a72872656758b047ee9dd9257ab015a32e7fcfc9e1 |
| server/src/frontend/tools/tool-call-handler.mjs | d969069501f1655a78fc11fccd4f7bbe55d82e93c7ff4607db7f03294497f490 |
| server/src/voice/realtime-presentation-runtime.mjs | 0f71e77fcd14081ae2cf427f2bd60e5a183aa5a49381a9e57460a1dd8b06bea3 |

`FrontendMcpClient` 原有代码直接使用 MCP SDK `StreamableHTTPClientTransport`，将
normalized headers 通过 `requestInit.headers` 交给 SDK，支持 initialize、tools/list、tools/call。
无需修改 client 或 ToolCallHandler。

## URL 与权限合同

`QWEN_AUDIO_FRONTEND_MCP_ALLOW_PRIVATE_HTTP` 默认关闭，只接受字符串 `true`。
HTTP 例外必须同时满足：Node URL 解析后 hostname 是 Node `isIP` 确认的 IPv4，位于
10/8、172.16/12 或 192.168/16，并携带合法的完整 Bearer header。

公网、域名（不进行 DNS 推断）、link-local、CGNAT 和 IPv6 HTTP 不进入例外；
URL userinfo、fragment、非法 URL/协议继续拒绝。远程 HTTPS 与原 header-free loopback
逻辑保留。认证头缺失、环境引用缺失、无效 Bearer 或注入头不能获得新例外。
HTTPS 原有 header 策略不扩大修改。

白名单只选择现有 P4/P6.8 授权合同能力和 Assist 暴露实体；部署时用 NAS 真正返回的原始
工具名逐项列出，保留现有能力，不把测试 fixture 数量冻结为生产事实。
新出现的非合同能力默认不启用；不增加任意 HA 管理/服务调用。
HA 专用非管理员 Token、Assist 暴露、Tool/Service schema 与服务权限是实际授权边界；
Qwen 不支持 `readOnly`/`approval` 配置，模板没有伪造这些字段。
模板尚不能直接部署：所有工具名和生产 URL 必须在 B8.7 核销，真实 Token 只进入 NAS secret/config.env。

## 自动化证据

| 验证 | 实际结果 |
|---|---|
| 未补丁锁定源码，新增策略测试 | 5 项中 2 项按预期失败：RFC1918 HTTP + Bearer 被原策略拒绝；3 项原有拒绝/兼容行为通过 |
| 补丁后新增策略测试 | 5 passed |
| 本地集成测试 | 5 passed |
| 原版 config/client/ToolCallHandler/presentation runtime 回归 | 188 passed |
| 隔离脚本合计 | **198 passed**，复用依赖、全新 npm ci 两条路径均通过 |
| HA 全量（包含现有 P4b5 MCP HTTP endpoint 测试） | **592 passed, 270 warnings**，127.89 s |
| Node 语法、bash -n、git diff --check | PASS |

本机 mock 使用真实 Node HTTP server，绑定本机 RFC1918 网卡地址和随机端口；
没有将真实 SDK transport 替换成假 client，也没有连接 NAS/HA。
请求经过补丁后的正常配置解析和真实 Qwen Client/MCP SDK：

- initialize → notifications/initialized → tools/list；精确环境引用展开为测试用 Bearer。
- 只发现启用白名单，tools/call 使用原始工具名和原始参数；禁用工具不能发出调用。
- 多字节结果保持 1024-byte 上界，工具 `isError`、JSON-RPC 错误、HTTP 401、
  缺失白名单工具、100 ms 超时及主动 AbortSignal 都有失败断言。
- 真实 ToolCallHandler 使用真实 MCP Client；RealtimePresentationRuntime 和 AnnouncementWindow
  在工具请求未完成时收到中间 audio.done/response.done，仍保留当前 turn。
  结果携相同 call_id/turnId 回传，触发一次 `afterToolResults` 后续响应请求，generation 不变。
  只有后续最终 response 完成才解除 turnPending。

模型网络接口是内存观测边界，不是实时模型生成或物理播放；不把此测试宣称为 B8.7 端到端验收。
测试 server/timer/client 由测试 teardown 清理，脚本临时源码和安装目录退出即删除。

复现入口：

```bash
bash deploy/nas/qwen/patches/test.sh /path/to/qwen-audio-agent-v2.1.0
PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath" bash scripts/test-ha.sh \
  tests/homeassistant -q -p no:cacheprovider
```

脚本要求 Node 22+、Git、patch、npm、本机 RFC1918 IPv4 网卡；
按锁定提交创建临时副本，校验原文件 hash，不修改传入源码树或 NAS。
本地完整输出留在被忽略的计划 workspace `b83/`，Git 保存可重复入口与报告。

## 审查与后续门禁

独立 reviewer 审查本批补丁、模板、说明、测试与依赖锁文件，并独立复跑预期 RED 和
198 项 GREEN；无 Critical / Important / Minor 待处理项。

执行决策：沿用用户指定的当前 P6.8 feature checkout；遵从全局 TDD，将计划中 Step 4 的
RED 测试提前到 Step 3 实现之前。没有扩展产品设计或修改公开工具 schema。

**B8.3 Gate：PASS（软件交付）。** NAS 运行包仍保留原版远程 HTTPS 限制；
真实部署、HA Token 拒绝、生产 tools/list 与工具调用由 B8.7 负责。
B8.5/B8.6 的正常终态可观测性等门禁仍按合同矩阵 §2.1，未被本批测试解除。
