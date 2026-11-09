import time, resource
from pathlib import Path
import sherpa_onnx, soundfile as sf
ROOT=Path("/data")
ra, rs=sf.read(ROOT/"kokoro_zf001_t1.wav", dtype="float32")
if ra.ndim>1: ra=ra[:,0]
rt="你好，我是你的智能助手。你可以直接告诉我想做什么，我会帮你处理。今天我也可以帮你打开客厅的灯、播放音乐，或者设置一个十分钟的倒计时。"
text="好的，已经连接到家庭助理。"
cfg=sherpa_onnx.OfflineTtsConfig(
 model=sherpa_onnx.OfflineTtsModelConfig(
  zipvoice=sherpa_onnx.OfflineTtsZipvoiceModelConfig(
   tokens=str(ROOT/"sherpa-onnx-zipvoice-distill-int8-zh-en-emilia/tokens.txt"),
   encoder=str(ROOT/"sherpa-onnx-zipvoice-distill-int8-zh-en-emilia/encoder.int8.onnx"),
   decoder=str(ROOT/"sherpa-onnx-zipvoice-distill-int8-zh-en-emilia/decoder.int8.onnx"),
   data_dir=str(ROOT/"sherpa-onnx-zipvoice-distill-int8-zh-en-emilia/espeak-ng-data"),
   lexicon=str(ROOT/"sherpa-onnx-zipvoice-distill-int8-zh-en-emilia/lexicon.txt"),
   vocoder=str(ROOT/"vocos_24khz.onnx")),
  num_threads=2, provider="cpu", debug=False))
if not cfg.validate(): raise ValueError("invalid ZipVoice config")
t0=time.perf_counter(); tts=sherpa_onnx.OfflineTts(cfg)
print(f"load={time.perf_counter()-t0:.3f}s sr={tts.sample_rate}",flush=True)
g=sherpa_onnx.GenerationConfig()
g.reference_audio=ra; g.reference_sample_rate=rs; g.reference_text=rt; g.num_steps=4
t0=time.perf_counter(); a=tts.generate(text,g); elapsed=time.perf_counter()-t0
dur=len(a.samples)/a.sample_rate
sf.write(ROOT/"zipvoice_distill_short_2t.wav",a.samples,a.sample_rate,subtype="PCM_16")
print(f"duration={dur:.3f}s synth={elapsed:.3f}s RTF={elapsed/dur:.3f} peakRSS={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.1f}MB",flush=True)
