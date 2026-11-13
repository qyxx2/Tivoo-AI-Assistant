# P6.5b7 HA 持久 MIC ingress 验收

- 模拟 ESP32 通过真实 7778 TCP 发送 HELLO、MIC_SESSION_START、MIC_ACTIVITY 和二进制 MIC_PCM。已覆盖 capability 区分、无效活动字段、旧 UUID、帧序号和 AUDIO_STATE 路由。
- 同一 MIC session 先运行 WAKE_WORD Pipeline，再在匹配播放完成后用 STT 启动 follow-up。测试覆盖 RUN_END 和资源下载结束期间的 VAD 活动、旧 playback ID、3/15/5/8 秒定时器、重连时等待旧轮取消、Pipeline 返回后断线仍清理 TTS owner，以及 STT 已结束收音但仍等待结果时持续上传。
- PCM 按 HA ingress 字节偏移分发。模拟延迟 Detection 时，从 Detection 前 1 秒的偏移读取已经收到的 PCM 和后续帧各一次。交接缓冲的 15 秒、480,000 bytes 上限包含预录，超限清理匹配会话并发送一次 MIC_CAPTURE_STOP。
- HA Core 2026.11.0 的公开 Satellite Pipeline 入口使用生产 Tivoo Satellite 的 MP3 配置，真实 HA TTS Proxy 返回 `audio/mpeg` 和带 ID3 的 MP3。真实 Wyoming STT transport 连接项目 P7A handler，使用模拟模型与确定性 VAD 分数。P7A 的 `requires_external_vad` 使 HA 约在 0.3 秒发出 STT_VAD_START，在累计 1 秒命令及约 0.7 秒静音后结束收音。15 秒分段默认值由 HA 合同测试覆盖。
- AstrBot Satellite 正常回复开启续聊。文字会话按 HA ChatLog 原生问号判断续聊，AstrBot session TTL 继续由 P3 管理。

B7 的设备信号和跨轮测试使用模拟设备。B8 提供真实 MIC 采集与上传，B9 接入生产 side KWS 与打断交接，B10 提供真实播放终态。此次未部署 NAS 或刷写 ESP32。

## 本地回归

- `./scripts/test-ha.sh -q --tb=short --disable-warnings tests/homeassistant` 通过 345 项。
- `./scripts/test-sherpa-wyoming.sh -q` 通过 130 项。
- 本批次 Python 文件通过 Ruff check 和格式检查，暂存差异通过 `git diff --cached --check`。
