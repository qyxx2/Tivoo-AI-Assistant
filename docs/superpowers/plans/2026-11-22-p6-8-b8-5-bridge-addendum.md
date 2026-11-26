# B8.5 Bridge 执行补充

> **ARCHIVED / 历史轨迹（2026-11-26）**：本计划已退出活动开发，不再是 backlog、发布门禁或后续执行入口。`[x]` 仅表示已有实现、测试、报告或部署证据；未勾选项表示当时未执行、被后续架构替代，或因复现成本/发生概率不值得主动验收。若实际使用暴露问题，再建立专用分支与针对性计划处理。当前文档入口见 [文档地图](../../README.md)。


> 使用 executing-plans 与 TDD；只执行 B8.5。用户在本次会话明确允许最小兼容协议补丁并继续完成 B8.5，取代原计划“不实施新接口”的限制。

沿用原迁移计划及合同矩阵 §2.1。当前 feature checkout 原地继续；不进入 B8.6/B8.7，不部署 NAS，不运行全量测试。

## 已选方案与设计

保留 GCP 7.0 的现有 `audio.done`，增加 `responseStatus`、`awaitsToolFollowUp`、`hasFunctionCall`；客户端请求并校验 `response.terminal-status` capability。状态未知、缺少字段、取消或不完整均不作为成功。其他方案（靠 idle 猜测成功、永久禁用成功续聊、新增公开事件）不满足既有合同或扩大变更。

Qwen bridge 是 ConfigEntry 的 socket owner；Satellite 继续持有 MIC/Context/generation 与清理屏障。每轮输出 owner 复用原 TTS 的 stop/close/playback 接口，PCM HTTP 资源仅负责单次有界传输。实际 24/32 kHz PCM 原样转发，不在 HA 重采样。B8.5 提供显式连接保留/parent 移交接口；问号解析及 0x27 授权仍属 B8.6。

## 执行与验证

- [x] 终态补丁：先 RED，后兼容补丁及 capability/schema/工具/取消/晚文本定向 GREEN；仅打包，不安装 NAS。
- [x] Bridge：先握手、PCM 与清理边界 RED，再实现 `qwen_realtime.py`；测试 auth、顺序/采样率、ping/pong、当前输入 EOF+1000 ms 尾帧、工具中间响应、正常终态、迟到文本、物理播放、字节上限、单次 GET、断连、取消、同 socket 显式保留/移交。
- [x] Satellite/setup：local-wake 调用 bridge，跳过旧 pipeline validation 与 STT/Intent/TTS，保留 subscription gate 和 retire barrier；定向测试正常、错误、unload。
- [x] 独立 review、修复重要问题、重新运行受影响专项；保存验收报告与本地提交。

实现细化：正常 `hasFunctionCall=true/awaitsToolFollowUp=false` 的工具受理语音在工具成功结束后允许正常完成交付，但返回 `followup_eligible=false`；不等待上游明确抑制的第二次回复。这不放宽续聊终态条件。详见 B8.5 验收报告。

复核重点：早端点不得提前 TTS_PLAY；同 MIC 多 turnId 失败；旧 turn 事件不得交付新 MIC；`playback.clear` 撤销交付；满缓存 finish/cancel 不阻塞；文本、HTTP EOF 和设备 completed 均为独立条件；保留连接不得被旧轮 retire 关闭。
