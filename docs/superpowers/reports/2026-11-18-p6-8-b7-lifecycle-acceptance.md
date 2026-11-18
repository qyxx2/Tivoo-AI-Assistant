# P6.8b7：打断、续聊、所有权（软件验收）

实现：18d4dcbb3865e6151a1e8e71d2d016d84643f377；同一分支 feature/p6-8-s3-local-wake。依据本项目 b0.4/b0.5/b0.6 合同、b3–b6 已有实现、开发机实际 HA Core 2026.11.0 public Satellite / IntentResponse API、IDF 6.1、现有 AstrBot SSE/Stop 与 Wyoming owner。未部署、未连接 NAS、未刷写任何 ESP32；未进入 b8。

## 实现和约束

- **T07-A / LIFE-C01/02/03/08**：S3 真实 wake 先失效旧 UUID/授权和 PCM，按捕获的 epoch+UUID 停旧 HTTP/输出 generation，再等待释放和声学 tail；短 prompt 仍由 AFE mask、普通 VAD 无抢占权。HA 同步换代、取消旧 timers 和 dispatch，由后台 retirement barrier 定向发 0x31（有真实 playback ID 时）、取消/join 原 public caller 与 TTS owner，最新轮不能抢先复用 public caller。迟到事件、旧回调、旧 END、旧/重复 START 不改变新轮。旧清理未确认则替换轮失败，不假装成功。legacy 分支保留。
- **T07-B / LIFE-C04**：普通回复沿用唯一 HTTP worker / output manager；匹配旧 session/playback/epoch 的停止作用于其捕获资源，不能停止新 prompt；数字 drain 确认后才释放 generation，若超限保留隔离，等待真实排尽后再释放。旧普通输出的真实 DMA 样本完成时间叠加 b6 待标定 tail；完成消息在 owner 释放后发出。HTTP 既有 EAGAIN 长间隙填静音与 EOF/错误终态保持不变。软件 fake resource + 实际 C turn adapter / output queue / parser，非真实 DMA 或 HTTP worker 时序测量。
- **T07-C / LIFE-C05**：复用原 HA ResultStream token / Proxy cache / Wyoming FIN→peer EOF / FFmpeg producer 关闭；5s stop-send、15s Wyoming、5s conversion、10s AstrBot stop 保留，捕获原 owner 的失败传回 barrier。AstrBot 仍只在 accepted 且未 SSE end 时由唯一 owner Stop，保留 partial，成功 stop 沿用会话；失败隔离当前 session UUID 并持久化 stop_unconfirmed，reload/TTL 不自动解除，显式 new_conversation 恢复。不能据此宣称已执行工具回滚。
- **T07-D / LIFE-C06/07**：0x27 仅协商 local_wake_stt_v1，严格布尔 true、非空 STT、合法成功 intent 类型、RUN_END/正常 caller 返回、实际普通 playback completed 双顺序或无 TTS 尝试，才允许单次 grant。TTS 有尝试但无播放 ID、错误、发送失败/超时、false/缺失等不授权。local_followup 新 UUID+parent_session_id、无 wake phrase，独立既有 beep；设备安全 gate 后4s，初次3s、1s ready、15s speech 不变；5s grant handoff 过期定向 stop，旧 grant 无效。普通回复无授权结束 0x23/22；真实新 wake 撤销旧授权。HA 监察沿原首轮5s到续聊6s（设备4s严格窗口+原2s传输余量），并非延长设备窗口。

## 软件证据

| 检查 | 结果 |
|---|---|
| 初次 ingress/turn RED | 4 failed |
| 初次 coordinator RED | 1 failed, 5 passed |
| AstrBot stop 失败 RED | 4 failed, 2 passed |
| 设备 grant RED | 1 failed |
| B7 lifecycle 最终专项 | 21 passed（含六个阶段抢占、旧 caller finally/先定向 stop、连续3次、失败 barrier、严格授权、双顺序、5s expiry、late START） |
| HA 独立全量（六个阶段专项追加前，生产代码相同） | 527 passed, 248 warnings |
| HA 追加阶段专项 | 上述21项全通过，新增6项 |
| ESP32 独立全量 | 91 passed, 35 warnings（含新增实际 s3_local_turn.c host harness） |
| Sherpa suite | 135 passed, 1 warning |
| S3 IDF 6.1 单线程 Ninja | exit 0 |
| Git diff --check | PASS |

初次按计划联合执行 HA/ESP32：607 passed、3 failed、1 teardown error。新增 0x27 后旧 codec 精确集合未更新，补充正确枚举及 round-trip 后指定回归76 passed；ESP32 本地 HTTP fixture 被 HA socket 插件拦截，单独以项目既有禁用插件方式测试 PASS；旧 device_status 模拟器 pipe 命令与 TCP 查询的时序断言首次不一致，未改无关代码，独立全量通过，不能宣称该偶发时序已修复。

S3 app 2,101,920 B，8MiB app 分区余 75%（0x5fed60）；SHA256 8d305408ca3abe285498df336b4724ec35b878d03842f643af5a91534f0377bb。沿用现有 toolchain，CMAKE_BUILD_PARALLEL_LEVEL=1、ninja -j1；仅 build。TIVOO_P68_TEST_GATE 与 TIVOO_P68_PROMPT_CALIBRATED 均关闭。宿主机未失联。无独立 reviewer 工具，按现有合同、代码和测试自审。

日志 .superpowers/p68-b7/：red*.log、green*.log、host-lifecycle.log、full.log、recheck-ha.log、ha-final-lifecycle.log、ha-full-final.log、ha-phase-final.log、esp-standalone.log、sherpa.log、s3-build.log。
命令：PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath" bash scripts/test-ha.sh tests/homeassistant -q；PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32 -q；bash scripts/test-sherpa-wyoming.sh；开发机已安装 IDF 6.1 activate 脚本、ninja -C build -j1。

## 保留 GAP

S3/第二颗 INMP441 未到，B6 校准仍禁用；禁止把软件 fake resource、真实 HA Core+模拟服务、host parser/queue 测试当真实双板/声学结果。T07-B 实际旧 HTTP stop、数字 drain 与最后可闻声音延迟、真实长回复/间隙/抢占，T07-C 真实部署上的 Wyoming/AstrBot Stop 链路、取消延迟与失败率，T07-D 真实 beep/gate/续聊4s/自播负样本，T07-A 真机各阶段反复唤醒和断线，均需实物到位后综合核销。当前软件不需要新的人工产品选择；无物理参数猜测，生产可用状态不得宣称 PASS。报告仅覆盖 b7。
