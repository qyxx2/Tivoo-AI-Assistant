# P6.8 流式播放改进部署

> 后续更新：已进一步修复持续吞吐不足并重新部署，真人复测顺畅。当前固件与证据见 [CPU 预算修复报告](2026-11-25-p68-streaming-cpu-budget-fix.md)。以下保留首次改动/部署记录。

日期：2026-11-25，Asia/Shanghai。用户明确要求部署本次改动。分支 `feature/p6-8-s3-local-wake`，保留未提交工作区；没有合并或提交。

**配套HA代码与S3正常固件已部署，HA已重启，S3已退出下载模式正常运行。** 未自动触发唤醒或声音播放，未进行真人听感验收。

## HA

NAS `192.168.3.94` 的 `homeassistant` 容器，更新 `/config/custom_components/tivoo/` 下三个文件：

| 文件 | SHA256 |
| --- | --- |
| `__init__.py` | `8c9c76fa967350d8de79a8102063c3e134e7d4d610850ca4d961450f6b11e5e2` |
| `manifest.json` | `7feae4b5d6adeff748ac6c0482b3f928cd4de26fe3fa5758cc07f4c41c58f4a8` |
| `qwen_realtime.py` | `5066dba827b6ee96b732ca898b4e80dbcea601f0819035a1796ab0b2e28db6e8` |

部署前备份整个Tivoo集成（排除pycache）：

`/volume1/docker/homeassistant/config/tivoo-deploy-backups/p68-streaming-20261125-094648/tivoo-before.tar.gz`。

该目录名的时间戳由HA容器生成。源文件先核对哈希和语法，再替换目标文件并重启HA。运行环境已有 `wyoming==1.10.2`，24→32kHz转换探针正常，未安装依赖、修改凭据、改HA配置条目或重启Qwen/Sherpa。

HA刚重启8秒时一次HTTP检查为ConnectionRefused，继续等待后HTTP返回200；没有把初始未就绪写成成功。最终服务HTTP 200；HA进程持有到S3 `192.168.3.40:7777/7778` 的两条ESTABLISHED连接；启动检查未发现Tivoo设置失败或缺依赖异常。

另在HA容器中使用**实际已部署的类**和真实aiohttp HTTP连接，启动仅绑定localhost的临时测试服务器：保持 `finished=False`，分别推入两个24kHz PCM片段，确认在audio.done前收到增量转换后的32kHz PCM、使用chunked、没有Content-Length，完成后清理registry。探针未调用设备适配器、未向S3发送命令，服务器已关闭。这证明部署代码与依赖具备流式交付行为，不代表真实Qwen或物理播放已验收。

## S3

- 确认串口 `/dev/ttyACM1`，芯片ESP32-S3 QFN56 rev0.2，MAC `b8:1f:3f:aa:82:e0`。没有刷写Classic ESP32。
- 正常app大小2,533,936B；SHA256 `50ab2ab37119e8624d35ba0b8260ff810621a52f17f7872867e4ff693213ff02`，与实施阶段构建产物及部署前源文件哈希匹配。
- NAS正常app副本：`/volume1/docker/tivoo-esptool/artifacts/p68-streaming-normal-20261125.bin`。
- 部署前读取应用区前三MiB，按ESP image segment长度定位完整旧app，并校验其附加SHA256。提取的旧app为2,532,736B，SHA256 `43ca3636b4f79754e750a553f75b96894e005210bcbb440c5a082c2acd8d7191`。
- 回滚app：`/volume1/docker/tivoo-esptool/artifacts/p68-streaming-rollback-app-20261125.bin`；原始3MiB回读保留为 `p68-streaming-before-app-20261125.bin`。
- 只写 `0x10000` 应用；保留bootloader、分区表、NVS和模型分区。esptool写入输出 `Hash of data verified`，随后独立 `verify_flash` 输出 `verify OK (digest matched)`，再正常RTS复位。

## 启动与稳定性核验

正常复位后被动采集85秒串口，执行：

```bash
python scripts/verify-p68-afe-boot.py \
  .superpowers/p68-streaming-deploy/deployed-boot.log \
  --min-runtime-seconds 60
```

exit0，`passed=true`，非initialization-only，8份AFE快照覆盖70.12秒：

- feed155→1251，fetch310→2501。
- feed_errors/fetch_errors/resets/capture_overruns/missed_eof均0。
- 启动累计rx_gaps=1、overruns=41在观察期间未增长。
- AFE available，Wi-Fi station_connected，UART协议错误/超时计数均0。
- 无重启、AFE不可用或WDT故障；没有触发任何HTTP音频generation。

串口采集程序已退出、串口已释放。设备留在正常应用运行状态。

## 回滚与证据

需要回滚时，HA恢复上述归档内三个原文件并重启；S3仅在相同串口和0x10000写回上述已验证旧app并正常复位。备份已保留，当前没有执行回滚。

关键记录见 [evidence/2026-11-25-p68-streaming-deployment](evidence/2026-11-25-p68-streaming-deployment/)。完整原始日志保存在git忽略的 `.superpowers/p68-streaming-deploy/` 和NAS artifacts目录。

实施阶段 `artifact.json` 中 `deployed=false` 是当时的构建快照，保持不改写；当前部署状态由本报告及部署证据中的 `deployment.json` 记录。启动/静默稳定性通过不能替代真人短答、长答、工具等待、打断和实际卡顿复测。
