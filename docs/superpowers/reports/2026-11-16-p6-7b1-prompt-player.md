# P6.7b1 PromptSoundPlayer 与物理出口所有权

- 日期：2026-11-16
- 分支：`feature/p6-7-audio-prompts`
- 基线：`e9516bb`（P6.7b0）
- 范围：仅 P6.7b1。未接入首次唤醒、确认打断或 follow-up 等待入口；未部署 NAS，未刷写 ESP32，未进行真实 Tivoo/AEC 声学验收。

## 实现

新增 `homeassistant/custom_components/tivoo/prompt_audio.py`：

- 固定只接受 `ready_01.mp3`、`ready_02.mp3`、`ready_03.mp3`，从 HA `www/tivoo/prompts` 检查实际存在的素材。
- 使用与既有 TTS URL 相同的 LAN-only `get_url(... allow_internal=True, allow_external=False, allow_cloud=False, allow_ip=True)` 约束，但单独构造 `/local/tivoo/prompts/<固定文件>`；没有放宽 `build_internal_tts_url()` 的 `/api/tts_proxy/` 限制。
- `PromptSoundPlayer` 负责 generation 去重、随机选择且相邻不重复、独立 UUID playback_id、历史提示音 ID 识别、匹配 ID 的定向 `AUDIO_STOP`、释放等待与超时降级。
- 正常 TTS 通过 `async_yield_to_tts(playback_id)` 获得物理播放优先级：已有提示音时先定向停止并等待 terminal state；正常 TTS 已占用时新的提示音直接跳过，不依赖设备 `audio_busy` 重试。
- 缺素材、LAN URL 不可用、提示音发送失败、stop 发送失败或释放超时均只影响提示音自身；不会把提示音异常传播成 Pipeline 失败。

修改 `audio_resource.py`：

- `TtsResourceManager` / `PipelineTtsEvents` / `create_pipeline_event_callback()` 新增可选 `prepare_playback(playback_id)` awaitable。
- 该回调只在真实 TTS `TTS_PLAY` 发出前执行一次；默认 `None`，因此现有所有调用路径行为保持不变。
- b1 只建立协作 seam；将具体 `PromptSoundPlayer` 实例接到 Satellite playback dispatcher 和三个等待入口属于 b2。

## RED → GREEN 证据

RED：

1. 新测试首次运行因 `custom_components.tivoo.prompt_audio` 不存在而失败。
2. 加入 API 骨架后，URL、generation 去重、随机不连播、定向 stop、TTS 让位、旧 generation 隔离、超时降级等行为测试均失败。
3. `audio_resource` 的 prepare seam 测试以 `unexpected keyword argument 'prepare_playback'` 明确失败。

GREEN：

- `test_prompt_audio.py + test_audio_resource.py`：28 passed。
- P6.7/TTS/Assist/transport 相关回归：85 passed。
- `tests/homeassistant/custom_components/tivoo` 全目录：365 passed。
- Ruff check：PASS。
- Ruff format --check：PASS。
- `git diff --check`：PASS。

测试过程中曾发现两个“缺素材/单素材”用例被 `tests/testing_config/www/tivoo/prompts` 的上一次残留文件污染；根因确认后仅修复测试夹具的前后清理，没有修改生产逻辑来迁就测试。

最终自审补齐了“HA 内网 URL 不可用”和“定向 STOP 发送失败”两条失败路径测试；分别移除对应保护做故障注入时测试按预期失败，恢复生产实现后重新通过。

## b1 合同结果

| 合同 | b1 结果 | 证据 |
| --- | --- | --- |
| PR-C08 | PASS | 固定三素材、存在性过滤、generation 去重、相邻不重复、无可用文件静默跳过 |
| PR-C10 | PASS | 独立固定 `/local/tivoo/prompts/` helper；原 TTS Proxy helper 白名单未变 |
| PR-C11 | PASS（软件） | 仍调用现有 `async_send_tts_play()` / `TYPE_AUDIO_STOP`，未新增 TVIO 消息或 DAC owner；实机部分留 b3 |
| PR-C12 | PASS（owner seam） | 提示音独立 UUID；`on_playback()` 按 ID 消费提示音状态，正常 TTS ID 返回未消费；Satellite 实际先路由给 owner 留 b2 |
| PR-C13 | PASS（b1 边界） | 提示音 terminal state 只结束提示音 owner，不调用正常 TTS/follow-up/display；实际 Satellite dispatcher 接线留 b2 |
| PR-C14 | PASS | 新 generation 定向停止旧提示音；旧 generation cancel 和迟到状态不能覆盖新提示音 |
| PR-C15 | PASS（独立 owner） | TTS prepare 会先停止/等待提示音释放；正常 TTS reservation 期间提示音跳过；b2 再接真实生命周期 |
| PR-C19 | PASS（HA 单元范围） | 缺素材、发送失败、stop 失败、释放超时均静默降级且不抛入 Pipeline；真实断线/DAC/HTTP 现场留 b2/b3 |

## 边界

P6.7b1 没有自动触发任何提示音。当前新增 owner 只有在后续 b2 显式创建并接入 `AudioSessionCoordinator` 时才会进入实际语音流程，因此不会提前改变现有 P6.5/P6.6 行为。P6.7 整体仍未完成，尤其 P65-A13 与提示音播放期间真人讲话/AEC 现场证据仍属于 b3。
