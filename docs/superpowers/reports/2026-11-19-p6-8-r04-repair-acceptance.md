# P6.8 R04 AFE 状态真实性与 VAD 跨 gate 隔离验收

日期：2026-11-19；feature/p6-8-s3-local-wake；基线 504c05653d98b665682314207c8f35accfd74f9f（R03）。依据 [执行计划](../plans/2026-11-19-p6-8-review-repair-execution-plan.md) R04，F06/F08、B4-R03/R01；AFE-C06/10/12、VOICE-C04/05/09、T04-A/T06-B/T05-C 的本批软件子项。不核销整个物理测试组。

## R04.1–2 AFE 可用性

- 任务创建、首次完整有效 feed、首次通过结构/指针/长度校验的 fetch、reset pending、vendor fatal 区分。仅最后验证有效的运行 epoch 才允许发布 local wake。首次持续 capture invalid 不发布能力；每10s现诊断日志有原因与 rx_gaps/feed_errors/fetch_errors/resets。reset_buffer/reset_vad 返回非1分别报告原因；清旧 flow/队列，禁止旧 gate。正常 reset 后重新验证 feed/fetch 才恢复；fatal 停 vendor 调用，不无限重建 AFE，不改变 R03 DMA 恢复。
- fetch 任务独占发布可用性；feed 只请求 reset，避免跨任务的发布顺序竞争。reset pending 即拒绝新 gate，fetch 已有250ms等待边界后撤销能力并运行既有 turn tick；异常结果不再进入 flow。fatal 后 tick 继续收尾已取消的 prompt，feed 将独占 RX 消费职责交现 capture monitor，监测创建失败有明确日志；没有另造 DMA supervisor。此交接的真实调度与剩余内存属硬件 GAP。
- TVIO v1 已核对：HELLO/ACK 是每连接一次，HA 仅 echo 所声明的 local_wake_stt_v1，断连清能力/manager/旧 turn 并独立重连。复用 diagnostics worker 关闭旧7778；revision 覆盖短暂 false→true，旧 ACK 不复活；新 HELLO 捕获一致 snapshot，只有匹配当前 revision 的已接受 epoch 才有 local wake generation。7777/SPP 与 DAC owner/驱动保持独立，未增加消息 ID、伪造 wake 或改变普通能力声明。7778 重握手有短暂不可用窗口；不能承诺事务无中断，已绑定失效语音 epoch 的普通回复按既有合同撤销。B0.5 LIFE-C04/0x30/0x31 要求当前 UUID/ID/epoch，不新增无会话播放或放宽授权。普通下行的协议通道保留，host 模拟器验证普通帧正常流转，不冒充 HTTP/MP3/DAC worker 真实输出（R08/实物）。

## R04.3 VAD gate

核对开发机锁定 ESP-SR 2.6.1 的 esp_afe_sr_iface.h（reset_vad/reset_buffer 成功1、失败-1，fetch cache 无索引），并对实际链接 libesp_audio_front_end.a 的 esp_afe_sr_2mic.c.obj 执行 xtensa-esp32s3-elf-objdump -dr。afe_fetch_with_delay 内先 sr_rb_read（0x98），继而 afe_vad_run_multi_mic（0x126）、WakeNet（0x130）、afe_fetch_out（0x144）；afe_reset_vad 调模型 reset/或 vad_reset_trigger 并清保存状态（0x48），返回1。两者区别于重置增强 ring 的 reset_buffer。选择同一 fetch owner、首次完整落于 gate 后的 fetch 前 reset_vad；不重置 buffer、feed、WakeNet，不关闭常驻 AFE、不额外等待500ms。

gate 已成功开放而当前 fetch 的 VAD 是开放前计算的，或跨 gate 的 fetch：只保留合法后半 PCM 到既有500ms history，vad_valid=false，不能据此 START、END 或确认 VAD neutrality。下一完整合法 fetch 先重置 vendor VAD 再使用决策。额外只在 onset 有歧义时拒绝全数字零帧，不采用新的能量阈值/二次声学 VAD；正常端点仍由原厂 hysteresis 确定。边界前的 PCM、未索引 cache 不拼入；真实即时语音由 history 回补，不要求先经历 silence。迟到 gate 原 fail-closed，B6 prompt_rearm 和真实 neutral 保留。reset_vad 失败走既有 reset handshake，失败 fatal 传播能力。R05/R09 需复用 gate index + vad_valid（决策是否来自本 gate）与现 owner，不以数字历史证明物理首声或缓存对应关系。

## RED/GREEN、回归

日志：.superpowers/p68-r04/。相对于基线先执行实际断言，保留失败日志：
- red-flow-diag.log：test_local_afe_flow 的 50×160 静音残留 speech 触发 START/END；test_p68_capability_rehandshake_preserves_nonvoice_channels 因旧 HELLO 保持而等待关闭超时；2 failed，exit 1。
- red-runtime.log：test_afe_runtime_availability 编译实际 s3_afe.c feed_task/fetch_task + 实际 portable flow 与锁定 vendor headers，仅 fake RTOS/capture/vendor 调用边界；首次持续 invalid 计数存在而没有报告，assert reports>0 失败，1 failed，exit 1。初始 fixture 编译调整不当作产品 RED。最终 recover/buffer_fail/vad_fail 分别验证8次 invalid、首次 feed 不发布、首有效 fetch 发布、故障 GAP、reset 计数与明确原因、fatal gate 拒绝、monitor 交接及恢复重新发布。
- red-gate-reset.log：扩展实际 runtime gate/gate_cross 后，开放前的 VAD 提前启动，跨块后首次完整 fetch 未调用 reset_vad；1 failed，exit 1。最终两个模式真实执行 reset_vad 调用顺序及 START/PCM sample index/内容连续；portable flow 50帧静音无 START/END，即时非零后半块与下一帧不重叠、不丢首；原 late/gap/cache、WakeNet neutral 测试保留。
- 初步 green-first.log 4 passed；加入 gate runtime 后 green-esp-target.log 35 passed/1 failed：新诊断连接在 listener accept 先于旧 fd recv/close 时被拒绝（socket closed after 0 of 16 bytes）。不改生产 listener；按现 HA retry_interval 重试 socket 层失败，仍严格验证每个 HELLO/ACK/普通帧与保持原7777连接。green-review-target.log 6 passed。扩展快速 false→true、fatal 原因断言后最终 green-esp-full.log **104 passed，0 failed/skip，36 warnings，63.74s，exit 0**，含计划四文件及普通音频回归。native pytest 原因沿 R03（HA socket-block 插件不用于 ESP host）。
- HA 现 B5 pythonpath 与 test-ha.sh：test_diagnostics.py/test_transport.py 66 passed、7 warnings、10.88s、exit 0（green-ha.log）。再补证 test_p68_afe_capability_reconnect_retires_old_turn_only：实际 HA adapter/AudioSessionManager，fake TCP peer HELLO true→false→true，验证 ACK、旧 UUID 释放、不可用时 READY 被拒、新 UUID 可开轮、同一7777未断；1 passed、5 warnings、0.65s、exit 0（green-ha-reconnect.log）；补证为现实现已经正确，不改 HA 生产代码。

开发机复验命令：
```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/esp32 -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/.superpowers/p68-b5/pythonpath" bash scripts/test-ha.sh tests/homeassistant/custom_components/tivoo/test_diagnostics.py tests/homeassistant/custom_components/tivoo/test_transport.py -q -p no:cacheprovider
```
警告为 native pytest 未加载 HA/asyncio/socket marker 插件的既有配置提示及依赖弃用；无测试删除、无生产兼容性绕过。

## S3 构建

既有 EIM ESP-IDF v6.1，esp32/firmware 现 S3 开发配置、TEST_GATE/PROMPT_CALIBRATED 均未启用；不改生产配置、不升级依赖。reconfigure / nice -n 5 ninja -C build -j1 / idf.py size 均 exit 0（s3-build.log）。APP 2105920 bytes，image size 2105801 bytes，DIRAM 196503/341760 bytes (57.50%)，不是运行资源峰值。复制 bin、elf、flasher_args.json 至 .superpowers/p68-r04/firmware/ 并 sha256sum -c SHA256SUMS 全 OK。BIN SHA256 2aa1233d7463b0f7eedb9b36a5ee149c9b76a9f7fba006d0d8c07cb0428a7828。两 target 清洁总复验留 R11。

## 审查与未验收

按 Superpowers executing-plans、TDD、systematic-debugging、requesting-code-review、verification-before-completion 执行。无独立 reviewer/subagent 工具，仅依据实际完整 diff、B4/B6 规格、vendor 调用顺序、测试断言自审。修订初步附加能量门槛为 vendor reset + 明确 vad_valid，无另加声学阈值；修复测试重连窗口并补真实 HA 生命周期证据。未发现本批剩余明确软件缺陷。边界说明：fake vendor/RTOS 不证明真实 AFE 内部时序、残响或低声/远场表现；真实三种 ready、followup、声学、物理 offset、cache overlap、恢复资源余量仍 GAP。R05 trace/真实 prompt adapter、R08 普通 worker terminal 证据、R09 实际组合/R11 总复验不提前实施。普通下行不绕过 LIFE-C04（若需 AFE fatal 时独立无会话 TTS，另行产品裁决）。S3/第二颗麦未到位，未访问 NAS、未部署/刷写旧 ESP32、未启用 gate。原 B1–B10 计划已有链接改动保留原状，R05–R11 未实施。
