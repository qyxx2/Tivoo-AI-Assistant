# P6.8 本次构建摘要与 HA 决策

日期：2026-11-25（Asia/Shanghai）。状态：已部署，真人反馈“播放顺畅”。这是本次 S3 + HA 组合的参考快照，不代表 P6.8 全部阶段已经验收。

## 构建与部署标识

| 项目 | 本次基线 |
| --- | --- |
| 分支 | `feature/p6-8-s3-local-wake` |
| 实现提交 | `c9e5e860e2b18b9c503a7e6ab7a86b0c4983f157` |
| S3 SDK | ESP-IDF v6.1 |
| 优化选项 | `CONFIG_COMPILER_OPTIMIZATION_PERF=y`，应用及 SDK 使用 `-O2` |
| 断言 / 性能探针 | 断言保留；正常固件关闭 trace/runtime stats，无静音或自动播放测试入口 |
| S3 app 大小 | 2,501,312 字节 |
| S3 app SHA256 | `da04bb22e36fdde204a9882e46eb467972648b9fdd3376b979b92f671c0b37d4` |
| NAS 已部署 app 副本 | `/volume1/docker/tivoo-esptool/artifacts/fixed-normal.bin`，使用前核对上述 SHA256 |
| 本地 app 副本 | `.superpowers/p68-streaming-followup/fixed-normal.bin`，被 Git 忽略 |
| 写入范围 | 仅 S3 app `0x10000`，写后独立 verify_flash 成功 |
| HA | NAS `homeassistant` 容器，集成目录 `/config/custom_components/tivoo/` |
| HA 依赖变化 | 新增并固定 `wyoming==1.10.2`，使用其有状态音频转换器 |

固件二进制不纳入 Git；上述提交、配置与哈希用于定位源码和核对归档，不承诺不同构建环境能逐字节复现相同二进制。`sdkconfig` 被忽略，重新构建应检查已有配置是否实际选择 PERF；只修改 defaults 不会保证旧 sdkconfig 自动切换。部署和回退均按 app 哈希核对，不能凭集成 manifest 的 `0.1.0` 区分这次修复。

配套 HA 文件（哈希同时见 [部署清单](evidence/2026-11-25-p68-streaming-deployment/ha-files.json)）：

| 文件 | SHA256 |
| --- | --- |
| `__init__.py` | `8c9c76fa967350d8de79a8102063c3e134e7d4d610850ca4d961450f6b11e5e2` |
| `manifest.json` | `7feae4b5d6adeff748ac6c0482b3f928cd4de26fe3fa5758cc07f4c41c58f4a8` |
| `qwen_realtime.py` | `5066dba827b6ee96b732ca898b4e80dbcea601f0819035a1796ab0b2e28db6e8` |

## HA 决策及理由

| 决策 | 理由与后续约束 |
| --- | --- |
| 保持增量播放 | 首个合法 PCM delta 到达且本地 MIC 输入排空后即可派发；HTTP chunked 逐块写出。不能重新加入等待 `audio.done` / `stream.finished` 的派发门槛或整段 body 拼接，避免退回非流式播放。 |
| HA 承担 24→32 kHz SRC | 每条流复用有状态 `AudioChunkConverter`，跨 delta 保留转换状态；S3 消费 32 kHz mono S16LE，避免增加本已紧张的设备 CPU 开销。原生 32 kHz 无需转换。 |
| 区分 provider 等待与网络写超时 | HTTP prepare/write/write_eof 仍受 10 秒 I/O 期限约束；等待下一段音频由 owner 的 45 秒事件进度、120 秒整轮期限控制，允许工具调用后的合法语音间隔。 |
| 保持有界缓冲和明确取消 | 消费落后超过既有字节上限会失败；客户端离开、owner 取消和 STOP 继续终止旧流并清理资源，不能靠无限积压掩盖设备吞吐不足。 |
| 保存分段诊断 | `qwen_pcm_metrics` 记录 session 下 delta 最大间隔、HTTP 写间隔及最长写等待；设备告警记录 generation/session、水位与缺失样本。指标不记录问话、原始音频或资源能力凭据；两台机器的单调时钟不能直接相减。 |

这些是当前实现决策，未来变更应重新验证流式首包、工具等待、客户端断开和实际设备播放。详细行为及自动化见 [流式改进报告](2026-11-25-p68-streaming-improvement.md)。

## S3 决策与本次卡顿原因

原 `-Og` 构建在 AFE 持续运行时，CPU0 接收/处理预算不足，即使只收不播也出现 TCP 零窗口。400 ms 预填解释了开头顺畅、随后持续卡顿；继续增加初始等待只能延后症状。

保留 512 KiB PSRAM 接收环、400 ms 初始预填、事件驱动接收/馈送/DMA 空间通知、120 ms 欠载恢复预填和 40 ms PCM transport 空闲读取超时。关键修复为全应用与 SDK `-O2`。不改变 AFE 采样率、任务核绑定/优先级及 DMA 时序；回调继续满足内部 IRAM 要求。40 ms 不是整个 HTTP read 的墙钟上界；预填和性能编译也不能保证上游停顿时永远不断粮。

已撤回的试验：只优化原生 32 kHz 路径无效；把 HTTP 移到 core1 在 30 秒回答仍严重欠载。后续排查不要把这两项当作已部署修复。

## 验证结论

- 修复前真人复现：560 次欠载、89600 个缺失采样、27 次重新缓冲。
- 修复后真人同轮：underruns / missing_samples / rebuffers / missed_eofs 均为 0，drained=1；用户反馈“播放顺畅”。
- 数字对照：6 秒 chunked 从 10.434 秒 / 698 次欠载改善到 6.471 秒 / 0 次；30 秒 paced 为 30.530 秒 / 0 次。数字测试以 DAC 静音探针运行，真人复测使用正常固件。
- 最终提交前：ESP32 全量 168 passed、HA Qwen 相关 53 passed；此前完整 HA + integration 为 694 passed、services 为 140 passed。不同环境与运行批次分别记录，不合并冒充单次全仓结果。
- 既有诊断/Wi-Fi 重连测试曾出现 ConnectionResetError，后续单项与全量通过，失败记录仍保存。长时间稳定性、更多网络条件及长工具等待/打断组合仍需后续观察。

详细测量、构建校验和历史失败：[CPU 预算修复报告](2026-11-25-p68-streaming-cpu-budget-fix.md)；[本次证据目录](evidence/2026-11-25-p68-cpu-budget/)。

## 回退与后续定位

S3 上一正常固件：NAS `/volume1/docker/tivoo-esptool/artifacts/p68-streaming-normal-20261125.bin`，SHA256 `50ab2ab37119e8624d35ba0b8260ff810621a52f17f7872867e4ff693213ff02`。该版本为首次流式改进、尚未修复 CPU 预算的基线，回退可能恢复卡顿；只按 app 范围操作，保留 NVS、模型及经典 ESP32。

HA 首次部署前备份：`/volume1/docker/homeassistant/config/tivoo-deploy-backups/p68-streaming-20261125-094648/tivoo-before.tar.gz`。`-O2` 后续修复没有再次修改 HA。回退 HA 应理解备份中的旧行为，并与对应设备版本重新验收；不能以等待整段生成作为卡顿修复。

若再次卡顿，先对齐同轮 session/generation 的 HA `qwen_pcm_metrics` 和 S3 `PCM supply` / 输出终态，核对实际 app/HA 哈希和有效编译选项，再比较接收环水位、缺失样本、再预填与 AFE 错误增量。用 `scripts/verify-p68-playback.py` 检查真实播放日志，保留失败证据。
