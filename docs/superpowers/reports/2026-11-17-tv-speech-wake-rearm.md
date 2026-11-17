# 电视持续人声下的唤醒采集续接修复

- 日期：2026-11-17
- 分支：`fix/ready-prompt-stale-tts-owner`
- 修复提交：`4a7c2b9 fix(esp32): restart wake capture during continuous speech`
- 范围：修复 VAD 持续处于 speech 时，HA 结束 15 秒 wake candidate 后 ESP32 不再建立新 MIC session 的问题。

## 已确认的根因

1. ESP32 的常驻 AFE/VAD 在电视持续说话时保持 `VAD_SPEECH`，不会产生新的 `speech_start`。
2. HA 的 wake candidate 有 15 秒超时。超时后 `async_stop_session()` 通知 ESP32 停止当前上传会话，但不停止 I2S RX、AFE 或 VAD。
3. ESP32 收到 `MIC_CAPTURE_STOP` 后，正常发送 `MIC_SESSION_END` 并清空当前 session。旧实现仍保留本地 `mic->speech == true`。
4. 如果 VAD 后续帧仍然是 speech，`tivoo_mic_push()` 看不到 `false -> true` 的边沿，因此不会执行 `start_session()`。设备继续本地采集，却不再上传 PCM，KWS 也就收不到后续音频。

这与电视连续对白场景吻合；它不依赖 TTS 或 DAC 播放，也不是 Sherpa 模型加载失败。

## 修复

在成功发送 `MIC_SESSION_END` 并清理旧 session 后，只重置上传生产器的 `mic->speech` 边沿状态。下一帧若 VAD 仍为 speech，就会重新建立 session 并继续上传。物理 RX、AFE、VAD 均保持常驻，不要求电视对白先出现静音。

对应回归 `test_continuous_speech_restarts_after_stop` 覆盖：VAD 连续保持 speech、HA 发出 stop、旧 session 结束后下一帧必须创建第二个 session；中间不注入 speech_end。

## 验证与部署

- 针对性 ESP32 host：2 passed。
- ESP32 host 全套：56 passed，33 warnings。
- ESP-IDF：v6.1，完整 `reconfigure build` 成功。
- 固件内版本字符串：`0.1.0+4a7c2b9`；应用 bin 约 1.7 MB，8 MB app 分区有充分余量。
- 通过 NAS `tivoo-esptool` 容器刷写 bootloader、partition table 和 app；三段写入均通过 Hash 校验。
- 实机启动确认：ESP32-D0WD-V3 rev 3.1、8 MB PSRAM、I2S/AFE 初始化成功、Wi-Fi 获得 `192.168.3.28`。45 秒串口观察中 RX errors、DMA overruns、missed EOF、AEC reference underruns/misalignment 均为 0；已收到 HA 的 `MIC_CAPTURE_STOP`，RX/AFE 保持运行。
- 被动观察期间出现过正常 speech_start/speech_end 与 session stop/reopen，但没有捕获到一段连续超过 15 秒、期间从未出现 speech_end 的真实电视对白。因此固件已部署、状态机回归通过，**持续对白条件下的声学实机验收仍标记 GAP**，不能冒称已完成该项实机验收。
- 本次没有播放提示音、TTS 或测试音乐。

## 与“区分电视声音和用户声音”的边界

本修复只解决连续 speech 时上传会话不续接，不负责判断声音来自用户还是电视。当前实机 AFE 启动日志显示处理链为 `AEC(SR_HIGH_PERF) -> VAD(WebRTC)`，没有启用 NS；AEC reference 是 Tivoo 自己 DAC 的播放参考，不包含电视扬声器的音频。硬件当前只有一颗 INMP441 麦克风，也没有声源方向或说话人验证。

因此：普通电视对白不会仅因 VAD speech 就直接唤醒，仍需 KWS 命中；若电视节目本身说出了配置的唤醒词，现有 KWS 无法判断说话者是电视还是用户，会触发。这不是本次 session-rearm 修复能够解决的问题。要抑制这类误唤醒，需要增加说话人验证/声纹门控，或使用电视内容中不会出现的唤醒词。单纯启用降噪不能保证分离两个人的语音。

此前观察到的 KWS `detected` 与 TTS `cancelled` 时间相邻，只能证明检测命中后触发了既有打断路径；没有对应原始 PCM 或说话人证据，不能据此断定是电视误触发。

## 生产配置观察

本次未修改 NAS 生产唤醒词配置。NAS Sherpa 容器当前 `WAKE_WORD_PHRASE` 为 `小粉小粉`；备份 `.env.pre-xiaofen-20261117` 中为 `PINKMAN`。这属于独立的运行配置状态，不与本次 ESP32 session-rearm 修复混为一谈。
