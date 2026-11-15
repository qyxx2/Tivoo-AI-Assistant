# 2026-11-14 Tivoo MCP / SPP 能力补全报告

## 结论

当前 feature/p6-5-ha-cancellation-preflight 已把原 P4 的 7 个 Tivoo Assist/MCP Tool 扩展为 27 个，并继续复用现有 HA Service -> TivooCommand -> TCP 7777 -> ESP32 -> Classic SPP 链路。没有增加第二套传输协议，也没有修改或刷写 ESP32 固件。

生产 NAS 上使用 AstrBot 现有 Streamable HTTP MCP 配置直接连接 /api/mcp/assist，实际 tools/list 返回 27 个 tivoo__* Tool。最终同步并重启 HA 后再次验证仍为 27 个，7777/7778 两条连接均恢复 ESTABLISHED。

## 上游核对

本次重新核对了项目文档已引用的三个 Tivoo 上游：

- d03n3rfr1tz3/esp32-divoom：e90a77bbade7e92523bfb5b69bc5cb1e4d167520。
- d03n3rfr1tz3/hass-divoom：0e9959a9009d9f8ce3be79476f464d593d85bc91；Tivoo 型号专用 driver、通用 Divoom driver 和 tests/goldens/Tivoo。
- solar2ain/tivoo-control：6f24deaf631820089259177805d1a6a6615f6d7e。

hass-divoom 的 Tivoo 型号专用实现明确支持 lyrics 与 scoreboard，并明确拒绝 equalizer 和 keyboard light。通用基类及 Tivoo golden vectors 还确认了 screen power、playstate、clock、datetime、weather、light、timer、noise、alarm、memorial、radio/source、sleep、design、effects、visualization、game/game control 等 SPP 命令。

raw 任意协议帧没有暴露给 MCP；equalizer/keyboard 没有暴露；effects/visualization/game 的有效索引依设备/App 版本变化，因此只暴露协议允许的受限整数，不伪造索引名称。ESP32 DEVICE_STATUS/DEVICE_EVENT 仍作为链路/设备健康状态，不把尚未解析的原始 SPP reverse 字节冒充完整业务状态 API。

## 当前 27 个 MCP Tool

GameControl、PlayAnimation、SetAlarm、SetAudioSource、SetBrightness、SetDateTime、SetExpression、SetLight、SetMemorial、SetNoiseMeter、SetPlayState、SetScreenPower、SetSleepMode、SetTimer、SetVolume、SetWeather、ShowClock、ShowDesign、ShowEffects、ShowGame、ShowImage、ShowLyrics、ShowScoreboard、ShowText、ShowVisualization、StartCountdown、StopCountdown。

对应 HA Service 同样为 27 项。新增 device_commands.py 只负责纯 payload 构造；protocol.py 继续统一添加 Tivoo 外层 framing/checksum；services.py 负责参数约束和语义分发；llm.py 只委派 HA Service。

## 自动化验证

最终完整 Tivoo HA 回归：

- ./scripts/test-ha.sh tests/homeassistant/custom_components/tivoo -q
- 272 passed，126 warnings；warnings 均为既有 HA/aiohttp/Python dependency deprecation 或测试 socket 提示。
- 最终 protocol.py 聚焦复测：41 passed。
- git diff --check：PASS。
- Ruff（所有本次改动 Python 文件）：PASS。
- services.yaml：YAML 解析 PASS，共 27 个 service description。

新增 protocol golden 覆盖 screen power、playstate、clock、datetime、weather、light、lyrics、scoreboard、timer、noise、audio source、sleep、design、effects、visualization、game/game control、alarm、memorial；日期时间继续保持本项目固定 esp32-divoom 的 7 字段格式，没有因 hass-divoom 新版额外 weekday 字段擅自改变已验证协议。

## 生产 NAS / ESP32 / Tivoo 实机补充验收

NAS：用户提供的 DS920 root SSH；ESP32 当前地址 192.168.3.28。测试前后 HA -> ESP32 的 7777 control 与 7778 diagnostic 均保持/恢复 ESTABLISHED。

生产 MCP 真机调用共执行 17 次，全部返回 OK：SetDateTime、SetWeather、ShowLyrics、ShowScoreboard、SetTimer start/stop、SetNoiseMeter start/stop、ShowDesign、ShowEffects、ShowVisualization、ShowGame、GameControl、SetAudioSource(linein)、SetScreenPower off/on、ShowClock 恢复。

为避免破坏真实设备既有设置，没有为了“全点一遍”真机修改 alarm、memorial、sleep、brightness、volume 等可能留下持久或用户可感知配置的能力；它们由上游源码/golden vectors、本地协议编码与完整 MCP HTTP 测试覆盖。

真机期间在 NAS 抓取 7777 TCP：126 packets captured，0 dropped。ESP32 -> HA 方向不仅有 TCP ACK，还收到多个非空、完整 0x01...0x02 Divoom/Tivoo SPP reverse frame。命令序列后 HA 日志没有新增 spp_disconnected / spp_connect_failed，双通道仍为 ESTABLISHED。

持久证据位于：

/volume1/docker/tivoo-esptool/artifacts/mcp-spp-expand/

- production-spp-smoke.pcap SHA256 5793328499c21dff463e53218058c4f1c8bc5e61beff7cd7cd232d17a8d6791f
- production-spp-smoke-tcpdump.log SHA256 a0c3e0c6efb6ef17395458451d36420a52320f536fa5f24d05484330f8800e59
- production-spp-reverse.txt SHA256 93cedaa6f4b4e241cdea44bebf747fcae64606b8a0c528a96ea450c09655f70f

部署前 HA Tivoo 集成备份：

/volume1/docker/tivoo-backups/tivoo-pre-mcp-expand-20261114-183119.tar.gz

## ESP32 刷写判定

本次没有刷写 ESP32。新增功能全部复用 P5/P6 已完成的“HA 生成完整 Tivoo frame -> 7777 -> ESP32 原样转发 SPP”和 SPP reverse 能力；真实设备已对新增命令返回 SPP 数据，说明没有固件侧缺口。为了形式上的部署而重刷相同能力固件没有测试收益。
