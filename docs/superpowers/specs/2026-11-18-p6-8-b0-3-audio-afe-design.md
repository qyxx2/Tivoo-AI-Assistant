# P6.8b0.3 双麦 I2S、DAC、AFE 与本地唤醒规格及合同矩阵

> 2026-11-18；基线 3cd456f。上承 [总体设计](2026-11-18-p6-8-b0-1-overall-design-baseline.md)、[硬件/UART/模型分区](2026-11-18-p6-8-b0-2-hardware-uart-spp-design.md)、[路线](../plans/2026-11-18-p6-8-s3-local-wake-roadmap.md)。本批只定音频分域合同，不实施、不刷机；b3 建立数字音频，b4 实际 AFE/声学验收，b0.4/b0.5 定 HA 事件及 owner 生命周期。新板未验收。

## 1. 双 INMP441、PCM5102 与硬件时钟

保留 b0.2 GPIO4 BCLK、5 WS、6 RX（两麦共享 SD）、7 TX（DAC DIN）。两颗同型号 INMP441 分别 L/R=GND/3V3（左 WS 低、右 WS 高），共同 3V3/GND/SCK/WS；检查两模块实际 L/R 绑带、SD 三态和板载下拉，整条共享 SD 合理等效约 100 kΩ 下拉，不盲目重复加电阻。TDK [INMP441 数据手册](https://invensense.tdk.com/wp-content/uploads/2015/02/INMP441.pdf) 规定 I2S MSB 延后一 BCLK、24-bit 有效数据、每个 stereo frame 64 clocks、非本 slot 高阻、共用 SD 的双麦接法；上电前核对模块，先静音验证再接 AUX。复用 PCM5102 三线 I2S，模块 FMT/SCK/XSMT/VIN 保持原实际可用配置，不推断模块具体版本；[TI PCM5102A 数据手册](https://www.ti.com/lit/ds/symlink/pcm5102a.pdf) 亦支持 BCK PLL、I2S 32-bit slot、32kHz。实际 DAC 版本/电平以实物为准。

- 保留现 audio_capture.c 中 I2S0 master 标准 Philips 全双工同一对 TX/RX handle；32kHz LRCK、2.048MHz BCLK、2×32-bit stereo slot，MCLK unused。IDF [S3 v6.1 I2S](https://docs.espressif.com/projects/esp-idf/zh_CN/release-v6.1/esp32s3/api-reference/peripherals/i2s.html) 支持同 controller 共享 BCLK/WS。两麦按同帧 L/R 采样，不用两个独立时钟、不各自重采样到漂移。启动及待机/播放/普通停止的时钟不停；INMP441 上电最初 2^18 SCK 周期（本设计约128ms）无有效音频，初始化丢弃这段，AFE settle 之后才能标记可唤醒。
- RX DMA 每帧 8B，L/R 32-bit word 内高24位为有符号样本，低8位非有效；复用 tivoo_inmp441_sample 的符号扩展；两路独立同系数/同相位 31-tap Q15 低通 32→16kHz（现 audio_capture.c，6.72kHz cutoff，15 个 32k 样本群延迟），同样舍入饱和为 s16，禁止先把两麦平均丢空间信息。按单独 tap/probe 验证 L/R、正负值、左右相位、一麦静音、增益差、clipping/DC、混叠/正弦和跨块连续性。
- Playback 仍以 32kHz s16 mono 为内部唯一格式，TTS proxy 已有 32k mono 直通；保留 audio_playback.c 对原 MP3 解码、立体声降为 mono、esp_ae_rate_cvt 转 32k、raw PCM 校验，不将采样率改成 AFE 16k 或重新引入每帧转换。DAC 每个 mono sample 复制到左右 32-bit slot 高16位（低位为0）。本地 ready/beep 走同一 TX 输出，b6 定资产和门控；不另起 I2S 或独立播放器抢 DMA。音量/静音/stop 后最终 TX 才是 AEC 参考。

## 2. 真实参考、缓冲与故障边界

现 audio_output_manager.c/h 以 DMA EOF、due block、reference ring 记录最终写入 TX 的 PCM，当前参考将相邻 32k 样本平均为 16k；旧 audio_frontend.c 处理 MR、预填只写步长2的 R 列，不能原样用于双麦。保留 DMA block 序号和终态语义，改为双麦与参考共用 16k 样本时间轴，参考明确单独 mono 数组再交织，禁止旧 stride=2 越界。若复用参考两点平均，其与麦 31-tap 滤波器的群延迟不同，校准时计入；优先使用同相位/同低通的连续参考抽取（任务上下文，不在 ISR 运行长 FIR）。b3 以实际 DMA 和声学相关性验证，禁止从 HTTP body、解码但未播放、队列提前入队、原 TTS 文件构造参考。对正常静音写零；零填、部分块、取消清除的 descriptor 同步修正参考，已进 FIFO/已播尾巴不能假装消失。

- 32k DMA 初值沿用 160 frames/5ms、12 descriptors/60ms、单方向 15,360B，两方向共30,720B（不含 descriptor），TX queue 5120 samples/160ms/10240B，初始 prefill 3840 samples/120ms；短输入 finish 后可立即走现有 drain。已进入播放后临时断供填零并保持 owner、时钟与 RX，不结束、不再次 prefill，后续 PCM 一到继续；真正输入结束且最后有效 DMA 排空才是完成，stop 按旧 generation 定向清空并等待实际尾巴。网络/decoder 不得阻塞 RX/feed/fetch/ISR；沿用 bounded backpressure。提示音短素材的起播延迟 b6 验证，可单独利用已知完整输入，不强制等待120ms。
- 现 32×5ms reference ring 仅160ms，设计初值保留；以最大现场延迟+调度/块边界实测是否充足，若不足只扩大必要部分，不建另一套时间轴。缺块/未对齐单独计数，不能把错误伪作真实静音。依据 DMA EOF 样本计数而非 task/wall time 对齐；两个麦及参考同步处理同一 RX sample index。单一物理丢帧不得被 missed EOF 与 queue overrun 重复累加；故障时丢未完成的 AFE 输入、重建滤波相位/时间轴映射，显式标记 gap，当前命令不静默拼接错误数据；新轮恢复，禁止普通停播重置 RX/AFE。
- 校准：b3 在固定实际 Mic/Tivoo/AUX 音量布置下播放短宽带脉冲/扫频（仅受控实机测试），同步保存最终 TX、两个原始 RX 的样本索引，互相关求各延迟/正负号/漂移，包含 DMA、SRC、DAC/音箱、空气及滤波；用多次/长运行/不同音量测量确定共同参考延迟和容忍范围，分别报告两路残留，不对两路单独移动来抹掉空间信息。旧 760 samples @16k (47.5ms) 不是新值。对正常声学反馈校准 AEC filter length（先取 AFE 默认，不机械照抄旧 2 块），测 ERLE/残响及双讲真人保留，再修改必要参数。记录实际首声和 stop 尾巴，不拿数字 EOF 冒充真实声学。
- 两麦同高、同朝向开孔、距中心对称、隔振且不要被音箱外壳或麦板遮挡；乐鑫[麦克风设计指南](https://docs.espressif.com/projects/esp-sr/en/latest/esp32/audio_front_end/Espressif_Microphone_Design_Guidelines.html) 双麦间距4–6.5cm；先按5cm中心距可移动安装，b4 比较实际固定、不同说话方向/距离/电视方位及噪声，不把候选值当实测。BSS 非说话者身份识别；电视若播放相同唤醒词仍可能命中，只有自身 AUX 输出有数字 AEC reference。

## 3. 锁定 ESP-IDF/ESP-SR 与 AFE 图

开发机 IDF git describe=v6.1，已有 esp32s3-elf GCC；ESP-SR 2.6.1（manifest commit b9dc43a329a68de2f72147808fc9ea29d2ace71e）idf >=5.0，CMake 对 S3 选择 lib/esp32s3，实际有 AFE/processor/WakeNet/VADNet/NSNet3 archives 和 S3 专用 header。CHANGELOG 2.5.0 修复 IDF v6.1 Kconfig 兼容并加入 WN10，2.4.3 加 FD AEC/AFE，2.6.1 修 wn10_hiesp kernel；2.5.5 修 nsnet3 内存问题。依赖实际 esp-dl 3.3.15 (S3 idf>=5.3)、dl_fft 0.8.0 (idf>=5.0)，ESP-SR 2.6.1 的 esp-dl ~3.3.12、dl_fft>=0.6.0，S3 不要求 esp-dsp；audio codec 2.6.2 idf>=4.4、effects 1.4.5/gmf_fft ~1.1，两者本地均含 lib/esp32s3。保留 v6.1/2.6.1，不因新版本号而换；属于源码/依赖与模型打包兼容，b1 才独立生成 S3 锁、完整编译链接、flash，b4 初始化验证，不将目前经典 target lock 当 S3 成品。

AFE 主选官方已发表的 **MMNR, FD, HIGH_PERF**：交织 [L16,R16,0,REF16]，这里 R16 为右麦，字符串 R 指 reference，N 为人工零占位而非物理第3麦。每帧按 samples-per-channel×4×2B 输入，AFE 单声道16k s16输出。本方案明确采用官方 benchmark 已验证的4列格式而不是假定3列 MMR 与同一预编译算法等价；数据量仅128kB/s，物理 I2S仍双 slot。官方 [AFE/数据布局](https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/audio_front_end/README.html)、[S3 benchmark](https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/benchmark/README.html) 给出 FD 双麦 AEC→SE(BSS)→VADNet→WakeNet，FD 额外非线性回声抑制适用于打断；与既有 SR_HIGH_PERF 对比（若 FD 双讲漏检或失真更差，允许 b4 依据同一实测切 SR_HIGH_PERF 并记录修订）。不运行两个 AFE 实例。锁定 header esp_afe_config.h 明确双麦 SE 优先于 NS，停用 SE 则只用第一个麦；所以不要同时强制 BSS 与 NSNet2/3，主路径 se_init=true/ns_init=false，SR_NSN_WEBRTC 只作为 Kconfig 无独立模型的选项，并非运行 NS；NSNet2/3 确实支持 S3，但只在单麦对照或后续经证据修订时单独验证，NSNet4 仅 P4/S31。AGC 使用官方初始默认/记录，不另加全局增益或叠第二个 VAD/AEC；vad_mute_playback=false。

- Kconfig: MODEL_IN_FLASH=y, AFE_INTERFACE_V1=y（实际 API 以组件 header 为准，不由 selector 名推断旧 API），SR_VADN_VADNET1_MEDIUM=y, SR_NSN_WEBRTC=y, SR_MN_CN_NONE=y, SR_MN_EN_NONE=y；单个经选择的 SR_WN_<MODEL>=y，不开外部模型路径。b1 为可重复构建可暂用 wn9_hilexin 作 smoke model，明确不是用户最终词；b4 用户选择最终模型，不自动把 smoke 固化生产。
- 用 esp_srmodel_init("model") 读取实际模型列表、esp_srmodel_exists 校验精确 ID、esp_srmodel_get_wake_words 校验词，禁止仅按前缀选第一个。afe_config_init("MMNR", models, AFE_TYPE_FD, AFE_MODE_HIGH_PERF) 后显式校验 aec_init/AFE FD mode、se_init、vad_init、vad_model_name、wakenet_init/wakenet_model_name、ns_init、vad_mute_playback；afe_config_check 会修改冲突选项，核对实际有效值及 print_pipeline，不把 requested 配置当有效。wakenet_mode 初始沿用该图官方默认（DET_MODE_2CH_95/90 等以实际返回为准；header 特别指出 90 flash load 仅 WN10，95 PSRAM load，禁止把不同代模型的 mode/threshold 当同义）。可优先 AFE_MEMORY_ALLOC_MORE_PSRAM，实测内部/DMA 余量与吞吐决定是否回 BALANCE。esp_afe_handle_from_config→create_from_config；get_feed_channel_num=4、get_fetch_channel_num=1、get_samp_rate=16000；动态 query get_feed_chunksize/get_fetch_chunksize，禁止硬编码 512；check/create失败或模型缺失停止发布 wake/语音 ready、报告明确原因，不悄悄回退远程 KWS。AFE 销毁后释放模型；保持模型内存映射有效。
- feed 任务和 fetch_with_delay 独立持续运行，成功才消费 data/data_size（字节、偶数、复制后才能跨下一 fetch），不能在 fetch 任务阻塞 socket、HTTP/UART/等待 HA。可复用现 core1 feed/fetch 方案，实际任务栈/亲和/priority 以 b4 运行测值防止 Wi-Fi/BT桥业务饿死。官方 FD HIGH_PERF MMNR benchmark约68.1KB internal、1238.5KB PSRAM、feed 30.4% / fetch 22.9%（各自单核；SR HIGH_PERF约68.1KB/1200.4KB/24.9%/22.9%）；是官方指定板/模型的参考量，非本机预算保证。b4/b10 记录 model/app/IRAM/DRAM、最小 internal free 与最大 contiguous/DMA block、PSRAM、task stack high water、CPU per core、feed/fetch P95 和 drop/overrun，真实 Wi-Fi+TTS+双麦+UART 并行至少长回复/重复触发。持续实时无丢帧、无内存失败、无 watchdog/reboot、无增长积压才可通过，不仅看 PSRAM 总量。

## 4. WakeNet 模型约束（实际 2.6.1，不是网页最新词库）

本批不替用户选最终唤醒词。原路线写 WakeNet9 系列是设计基线，并非硬件上限；本次确认 WN10 同样可用，补充为 b4 可选原生模型，不换版本。优先既有 WN9/9L 成熟路径，若所需词仅 WN10 或声音效果更好可用 WN10（一样的 AFE API，但实际模式、性能和声学重新测试）。不把 WN9s/WN10s 低资源路线或旧 WN7/8 纳入本期；禁 MultiNet、microWakeWord、任意文本 KWS。本期恰好一个已打包的模型，若一个模型含多个官方发音/词，实际元数据列出并逐个验收；禁止用户不可控的额外词。没有模型的“小粉小粉”、Pinkman、“大肥鱼”不能直接沿用；即使发音近似亦不是官方支持的指定词。修改文字或 JSON 不会改变模型识别能力。切词需明确 model ID、重新 Kconfig/打包/校验及刷 model（app 若有配置变化也同步），重新做正负样本；不要求经用户每次修改源码或 HA 运行时下发自定义文本。只有当前已装入的模型能检测；训练/第三方文件不在本期。

证据：实际组件 wakeword_list.md（2026-10-29 生成）、Kconfig.projbuild、model/wakenet_model 目录和 model/movemodel.py 一一核对。WN10 S3 使用 p1 SIMD 变体，脚本重命名 wn10_data_p1/_MODEL_INFO_p1 为标准文件；不是把整个目录三个 target 都打包。开发机用临时 sdkconfig 逐个执行原厂 movemodel.py，校验目录精确为单 WN + vadnet1_medium、_MODEL_INFO_ 存在、WN10 p1 data 字节一致，81 次全通过：WN9 53 个 579098–579238B、WN9L 6 个 579135–580674B、WN10 22 个 666699–1083370B（含 VADNet 与包头）；最大 wn10_hilexin_int16 1083370B < 4194304B。临时目录已自动删除，无生产构建/烧写。模型目录存在但无菜单的 wn9_customword、wn9_histackchan_tts3、wn9_hixiaoxing_tts、wn9_nihaoxiaozhi、wn9_sophia_tts_v1、wn9l_heygigi 不列为直接可用；菜单 SR_WN_WN9L_HEYGIGI_TTS3 对应目录缺失，会被打包脚本静默跳过，禁用该项。若将来明确要扩展，需官方支持路径/文件/版本审查并重新验收，不在本阶段修组件。下表以菜单符号实际映射目录和打包成功为准；显示名优先官方 wakeword_list.md，缺项用 Kconfig 标签（其拼写不一定等于 model ID）；实际词以 _MODEL_INFO_ 和 esp_srmodel_get_wake_words() 为最终证据，而非目录音译。

| 模型系列 | 官方词/标签 | 精确模型 ID（配置=SR_WN_ 加大写 ID） |
|---|---|---|
| wn9 | Alexa | `wn9_alexa` |
| wn9 | Astrolabe | `wn9_astrolabe_tts` |
| wn9 | BlueChip | `wn9_bluechip_tts2` |
| wn9 | Computer | `wn9_computer_tts` |
| wn9 | 嗨小欧 | `wn9_hai1xiao3ou1_tts3` |
| wn9 | 嗨小象 | `wn9_hai1xiao3xiang4_tts3` |
| wn9 | Hi,小巫 | `wn9_haixiaowu_tts` |
| wn9 | Hey,Ily | `wn9_heyily_tts2` |
| wn9 | Hey Ivy | `wn9_heyivy_tts2` |
| wn9 | Hey Kira | `wn9_heykira_tts3` |
| wn9 | Heyprinter | `wn9_heyprinter_tts` |
| wn9 | Hey,Wanda | `wn9_heywanda_tts` |
| wn9 | Hey,Willow | `wn9_heywillow_tts` |
| wn9 | Hi Andy | `wn9_hiandy_tts2` |
| wn9 | Hi,ESP | `wn9_hiesp` |
| wn9 | Hi fairy | `wn9_hifairy_tts2` |
| wn9 | Hi,Jason | `wn9_hijason_tts2` |
| wn9 | Hi jolly | `wn9_hijolly_tts2` |
| wn9 | Hi,Joy | `wn9_hijoy_tts` |
| wn9 | Hi,乐鑫 | `wn9_hilexin` |
| wn9 | Hi,Lily or Hi,莉莉 | `wn9_hilili_tts` |
| wn9 | Hi,M Five | `wn9_himfive` |
| wn9 | Hi,喵喵 | `wn9_himiaomiao_tts` |
| wn9 | Hi, Telly | `wn9_hitelly_tts` |
| wn9 | Hi,Wall,E or Hi,瓦力 | `wn9_hiwalle_tts2` |
| wn9 | Jarvis | `wn9_jarvis_tts` |
| wn9 | 璃奈板 | `wn9_linaiban_tts2` |
| wn9 | 喵喵同学 | `wn9_miaomiaotongxue_tts` |
| wn9 | Mycroft | `wn9_mycroft_tts` |
| wn9 | 你好小脉 | `wn9_ni3hao3xiao3mai4_tts2` |
| wn9 | 你好小瑞 | `wn9_ni3hao3xiao3rui4_tts3` |
| wn9 | 你好百应 | `wn9_nihaobaiying_tts2` |
| wn9 | 你好东东 | `wn9_nihaodongdong_tts2` |
| wn9 | 你好喵伴 | `wn9_nihaomiaoban_tts2` |
| wn9 | 你好小安 | `wn9_nihaoxiaoan_tts2` |
| wn9 | 你好小鑫 | `wn9_nihaoxiaoxin_tts` |
| wn9 | 你好小益 | `wn9_nihaoxiaoyi_tts2` |
| wn9 | 你好小智 | `wn9_nihaoxiaozhi_tts` |
| wn9 | Sophia | `wn9_sophia_tts` |
| wn9 | 小峰小峰 | `wn9_xiao3feng1xiao3feng1_tts3` |
| wn9 | 小珈小珈 | `wn9_xiao3jia1xiao3jia1_tts3` |
| wn9 | 小爱同学 | `wn9_xiaoaitongxue` |
| wn9 | 小滨小滨,小冰小冰 | `wn9_xiaobinxiaobin_tts` |
| wn9 | 小箭小箭 | `wn9_xiaojianxiaojian_tts2` |
| wn9 | 小康同学 | `wn9_xiaokangtongxue_tts2` |
| wn9 | 小龙小龙 | `wn9_xiaolongxiaolong_tts` |
| wn9 | 小鹿小鹿 | `wn9_xiaoluxiaolu_tts2` |
| wn9 | 小美同学 | `wn9_xiaomeitongxue_tts` |
| wn9 | 小明同学 | `wn9_xiaomingtongxue_tts2` |
| wn9 | 小酥肉 | `wn9_xiaosurou_tts2` |
| wn9 | 小特小特 | `wn9_xiaotexiaote_tts2` |
| wn9 | 小鸭小鸭 | `wn9_xiaoyaxiaoya_tts2` |
| wn9 | 小宇同学 | `wn9_xiaoyutongxue_tts2` |
| wn9l | Bonjour ESP | `wn9l_fr_bonjouresp_tts3` |
| wn9l | Hi,Stack Chan | `wn9l_histackchan_tts3` |
| wn9l | こんにちは ESP | `wn9l_ja_konnichihaesp_tts3` |
| wn9l | 你好星宝 | `wn9l_ni3hao3xing1bao3_tts3` |
| wn9l | 你好小智 | `wn9l_nihaoxiaozhi_tts3` |
| wn9l | 小爱同学 | `wn9l_xiaoaitongxue` |
| wn10 | Alexa | `wn10_alexa` |
| wn10 | Hallo ESP | `wn10_de_halloesp` |
| wn10 | Hey,Buddy | `wn10_en_heybuddy` |
| wn10 | Hola ESP | `wn10_es_holaesp` |
| wn10 | Bonjour ESP | `wn10_fr_bonjouresp` |
| wn10 | Hey,Hermes | `wn10_heyhermes` |
| wn10 | Hey,Nova | `wn10_heynova` |
| wn10 | Hey,Pamet | `wn10_heypamet` |
| wn10 | Hi,ESP | `wn10_hiesp` |
| wn10 | Hi,乐鑫 | `wn10_hilexin_int16` |
| wn10 | Hi/Hey Muse | `wn10_himuse` |
| wn10 | アイリス | `wn10_ja_airisu` |
| wn10 | こんにちは ESP | `wn10_ja_konnichihaesp` |
| wn10 | Mosaico | `wn10_mosaico` |
| wn10 | 你好小智 | `wn10_nihaoxiaozhi` |
| wn10 | 你好小智 | `wn10_nihaoxiaozhi_int16` |
| wn10 | Olá ESP | `wn10_pt_olaesp` |
| wn10 | Привет ESP | `wn10_ru_privetesp` |
| wn10 | 双儿 | `wn10_shuang1er2` |
| wn10 | 涂涂你好 | `wn10_tu2tu2ni3hao3` |
| wn10 | 小爱同学 | `wn10_xiaoaitongxue` |
| wn10 | 小爱同学 | `wn10_xiaoaitongxue_int16` |

## 5. WakeNet 确认、VAD、重触发与命令 PCM

- S3 常驻采集与 AFE feed/fetch，包括待机、提示音、STT/思考/TTS/follow-up；待机只内部增强 PCM，不上传。WakeNet 不是 VAD，普通 VAD/环境声无取消权。锁定 header 定义 WAKENET_NO_DETECT=0、WAKENET_DETECTED=1、WAKENET_CHANNEL_VERIFIED=-1；官方 [esp-skainet 示例](https://github.com/espressif/esp-skainet/blob/master/examples/en_speech_commands_recognition/main/main.c) 对 raw_data_channels==1 用 DETECTED、多通道用 CHANNEL_VERIFIED（[乐鑫说明](https://github.com/espressif/esp-sr/issues/79) 多麦先 detected 再通道确认），不能以 fetch mono 判定 raw channel。按该规则只发布一次确认，多通道 DETECTED 只记录候选/索引、等 verified 后消费，后者 index 缺省时用已关联候选，拒绝无有效候选/未知词，不把 -1 判失败。b4 用实际每个选定模型的 state 序列、raw_data_channels、wake_word_index、wakenet_model_index、trigger_channel_id 验证；若实际图不同，以锁定组件及同一正负样本核验修订，不虚构两帧事件。go/no-go: 正常/打断状态均只对一次真实确认发一次事件，不能重复由 candidate/verified 两次发。
- 默认阈值来自实际模型及 mode，先记录，不沿用旧 NAS KWS。set_wakenet_threshold 的 model index 1/2，范围0.4–0.9999；VADNet threshold 0.5–0.9999，energy -100–0 dBFS（默认 -60），按返回码确认；不同时随意调多个参数。初测默认→依据误/漏样本最小调整，包括小音量/远场。不要长时间 disable WakeNet；短 ready/beep 仅屏蔽命令 gate 和其自身回声确认，播放期保持 AFE 与 WakeNet 输出及诊断，短 gate/尾部隔离后恢复确认接受；普通 TTS 不能套用屏蔽。wake candidate/verified 按同一次识别去重并丢掉跨 gate/故障 stale candidate，重新自然说词必须触发，不以固定数秒 cooldown 阻碍连续打断；b4 用同词连续两次、相邻帧重复、多次真实新发音验证重新 armed 行为。具体新旧 generation 交接 b0.5。
- VADNet1 medium：vad_min_speech_ms 初值128ms（>32），vad_min_noise_ms 初值500ms（>64，路线400–600ms范围），vad_delay_ms 初值128ms；初始 vad_mode 与阈值从默认 config 记录，采用有效 gate 内的 result->vad_state 转换；算法自带 hysteresis，不再额外串联旧 HA 700ms 静音计时；HA 端如何实际接收 AudioStop 属 b0.4，须确认不会多等/丢尾。有效 gate 之后的全部增强 fetch 包含静音，建立以样本索引为单位的 bounded history，开始说话时回补 gate 后前导，沿用现 320 samples/20ms uplink frame、25 frames/500ms preroll、50 frames/1s ring 作为初始上限，待 HA ready 的最大量与失败/超时由 b0.4 核对。vad_cache 是对截断音的补充，不能无条件 prepend 到已经保存的全部 fetch 历史（现实现明确重复）；b4 用标记音频校验 cache 是否与 data 相邻/重叠，若需要仅补未覆盖、gate 后的样本，禁止旧轮/提示音/wake tail 穿入新命令。完成时消费最后有效帧（尾部可按协商格式 flush）再发 speech_end 供 HA；端点时间从实际语音末尾至设备 VAD end 用同样本轴测量，不将静音填充当新语音。无命令、异常和失败的生命周期由 b0.4/b0.5 定。
- b4 声学对照：同词不同自然说法、正常/低声/距离（1m、3m及实际坐姿）/方位、安静/持续噪声/电视普通语音、真实 TTS 含/不含词、提示音、真人在自身 TTS 双讲发词、真人无唤醒词、重复 wake；每组记录样本数/命中/漏检/误触发/词尾到确认的P50/P95、VAD 漏首/尾/电视误断句。b10 加长时间电视/普通对话/自播稳定性；电视同词单独记录与真实用户同词区分能力的限制，禁止宣称彻底消除环境人声。按总体路线尝试词尾→确认300ms及其它延迟目标，现场真实可用性/具体阈值 b4/b10 报告与用户核对，不能用厂商 Alexa 测试结果冒充本模型效果。真实人声打断优先于追求漂亮 ERLE；若达不到则试 SR/FD、麦距、音量/参考、词和阈值，并重测完整正负样本。

## 6. 合同矩阵（设计出口；所有行待实施验收）

| 新合同 | 边界/要求 | 实施与验收证据 | 来源/旧合同 |
|---|---|---|---|
| AFE-C01 | 双 INMP441 L/R、共享 SD/时钟及供电，DAC b0.2 GPIO 不变 | b3 查实物/示波或逻辑分析、各麦独立敲击，定量左右数据与相位 | b0.2, P65-A01/A14, P7A-C41/C43 |
| AFE-C02 | 32k stereo 32-bit slot；两麦同相位 anti-alias 后16k s16 | b3 主机已知样本、跨分块相同、剪幅/正负/频响、实际采集 | P5-C05, P65-A01 |
| AFE-C03 | 32k mono播放、最终双 slot，raw/MP3/SRC 兼容，同源提示 | b3/b6 长音频、非32k、短素材、输出/波形，不引入再次 SRC | P6-C12–C16, P7A-C42 |
| AFE-C04 | 实际 TX 与 RX 共时间轴，静音/stop/欠载正确参考，校准延迟 | b3 DMA 测试、零填/部分填/取消/丢帧注入、相关测量、b4 双讲验证 | P65-A13/A14 |
| AFE-C05 | bounded DMA/ring/prefill；中途欠载填零不结束/不重预填；正常 drain | b3 按句间插入多段任意空挡、断网/stop 后恢复、原合同与 b10 长回复 | P6-C14/C15, P65-A08/A14 |
| AFE-C06 | IDF v6.1、ESP-SR 2.6.1、S3 独立目标/实际 lock+model/app | b1 完整构建/链接及 flash，b4 模型初始化/print_pipeline，b10 资源回归 | P5-C01–C03/C06/C20 |
| AFE-C07 | MMNR/FD HIGH_PERF 初始图，BSS 优先，不强开 NS，mono 16k、动态块长 | b4 打印有效 pipeline/配置及 layout，和 SR 对照，真实设备 feed/fetch | P65-A01/A13/A14 |
| AFE-C08 | 单一原厂模型按精确 ID，使用本表 WN9/9L/10 可打包组合；最终用户选词；无自定义文本/多模型兜底 | b1 单 smoke 构建；b4 确认词/ID/版本/hash、实际 mmap/模型加载，换词重测 | P7A-C09–C16/C40, 用户需求 |
| AFE-C09 | 真正 wake 跨阶段常驻；DETECTED/VERIFIED 正确归并且可重触发，VAD 无取消权 | b4 trace/重复词/旧候选/安静/普通人声；b7/b10 实际打断 | P65-A02/A03/A10–A13, ESM-C04（生命周期后续设计） |
| AFE-C10 | VADNet 本地端点与缓存按索引去重，不丢首尾，命令 gate 外不上传 | b4 标记 PCM、gate/缓存/端点测试；b5/b6 对接真实 HA/STT，b10 回归 | P65-A04/A05/A06, P7A-C41 |
| AFE-C11 | 真实回声/电视负样本、麦距与阈值校准；不可承诺电视同词免唤醒 | b4 录音、多条件命中/误漏/延迟及 SR/FD 对比，b10 长时测试 | P65-A13, P7A-C40 |
| AFE-C12 | 内存/CPU/DMA 余量与丢帧、AFE 错误不可伪装；任务全部有界 | b3/b4/b10 并发 Wi-Fi/UART/TTS+双麦实际统计、故障注入/恢复 | P5-C01/C06, P65-A01/A14, P7A-C43 |

后续接口归属：b0.4 定本地 wake/speech_end/命令 PCM 的传输、HA 准备竞态和提示音 gate 边界；b0.5 定不同代次 stop/re-arm/follow-up/表情，禁止由 AFE 候选或待机 VAD 直接触发显示。b0.6 对完整旧 ID 逐行核对，不能把本表部分分域映射当旧合同全面核销。b0.3 只修订路线与其引用，不更改既有生产代码/配置、NAS、串口、部署。

## 7. 出口证据与待决策

- 已核对当前真实代码（audio_capture/frontend/playback/output_manager、头文件和原 sdkconfig），开发机 IDF v6.1 的 S3 工具链文件与 ESP-SR 2.6.1 manifest/CHANGELOG/CMake/Kconfig/S3 headers/model files/打包脚本，以及厂商硬件数据手册/官方 AFE 图与示例。固定 commit 的 test_apps/esp-sr/main/test_afe.cpp raw URL 返回404，改用实际组件 header + 官方公开示例与 benchmark，未假称读到该 commit 的测试。
- 81 个单模型包与 VADNet 打包均通过；此测试只证明打包条件、P1 文件和分区容量，不证明每个模型的运行时效果或可链接。完整 S3 target build、实际 AFE pipeline/mmap、双 INMP441/PCM5102 模块实物与声学、延迟/负样本、内存/资源尚待 b1/b3/b4/b10，不标 PASS。
- 设计裁决：沿用 32k/32-bit共享时钟与 16k AFE，4列 MMNR（非 MMR）、FD HIGH_PERF 初始图、BSS 优先不叠 NS、5cm 初始麦距、500ms 端点、默认模型阈值及单一可换官方词；理由均在相应节，实际不满足时最小修订并复验，不能提前改 HA 或重构其它领域。用户最终词不代选；允许 WN10 是对路线不必要限制的修订，仅原生锁定版本且经过 b4 证据。文档自审，无独立 reviewer，b0.6 交叉审计仍必需。
