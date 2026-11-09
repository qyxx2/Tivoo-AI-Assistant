import time, resource
from pathlib import Path
import sherpa_onnx, soundfile as sf
ROOT=Path("/data")
TEXT="你好，我是你的智能助手。你可以直接告诉我想做什么，我会帮你处理。今天我也可以帮你打开客厅的灯、播放音乐，或者设置一个十分钟的倒计时。"
model=ROOT/"vits-melo-tts-zh_en"
cfg=sherpa_onnx.OfflineTtsConfig(
 model=sherpa_onnx.OfflineTtsModelConfig(
  vits=sherpa_onnx.OfflineTtsVitsModelConfig(
   model=str(model/"model.onnx"),
   tokens=str(model/"tokens.txt"),
   lexicon=str(model/"lexicon.txt"),
  ),
  num_threads=1,
  provider="cpu",
 ),
 rule_fsts=",".join(str(model/x) for x in ["phone.fst","date.fst","number.fst"]),
)
if not cfg.validate(): raise ValueError("Melo config invalid")
print("loading",flush=True)
t0=time.perf_counter()
tts=sherpa_onnx.OfflineTts(cfg)
print(f"loaded={time.perf_counter()-t0:.3f}s sample_rate={tts.sample_rate} speakers={tts.num_speakers}",flush=True)
t0=time.perf_counter()
a=tts.generate(TEXT,sid=0,speed=1.0)
elapsed=time.perf_counter()-t0
duration=len(a.samples)/a.sample_rate
out=ROOT/"melo_chinese_t1.wav"
sf.write(out,a.samples,a.sample_rate,subtype="PCM_16")
print(f"duration={duration:.3f}s synth={elapsed:.3f}s RTF={elapsed/duration:.3f} peakRSS={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.1f}MB file={out.name}",flush=True)
