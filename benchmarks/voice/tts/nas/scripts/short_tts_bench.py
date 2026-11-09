import time, resource
from pathlib import Path
import sherpa_onnx, soundfile as sf
root=Path("/work/vits-icefall-zh-aishell3")
cfg=sherpa_onnx.OfflineTtsConfig(
 model=sherpa_onnx.OfflineTtsModelConfig(
  vits=sherpa_onnx.OfflineTtsVitsModelConfig(
   model=str(root/"model.onnx"),
   lexicon=str(root/"lexicon.txt"),
   tokens=str(root/"tokens.txt")),
  num_threads=2, provider="cpu"),
 rule_fsts=",".join(str(root/x) for x in ["phone.fst","date.fst","number.fst"]),
 max_num_sentences=1)
t0=time.perf_counter(); tts=sherpa_onnx.OfflineTts(cfg)
print(f"LOAD={time.perf_counter()-t0:.3f}s sample_rate={tts.sample_rate} speakers={tts.num_speakers}",flush=True)
for sid,text,name in [(21,"好的，已完成。","good_done"),(41,"今天我挺开心的。","happy_today")]:
 gen=sherpa_onnx.GenerationConfig(); gen.sid=sid; gen.speed=1.0
 t0=time.perf_counter(); audio=tts.generate(text,gen); elapsed=time.perf_counter()-t0
 duration=len(audio.samples)/audio.sample_rate
 sf.write(f"/work/{name}_sid{sid}.wav",audio.samples,audio.sample_rate,subtype="PCM_16")
 print(f"SHORT text={text} sid={sid} elapsed={elapsed:.3f}s duration={duration:.3f}s RTF={elapsed/duration:.3f} file={name}_sid{sid}.wav",flush=True)
print(f"PEAK_RSS_MB={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.1f}",flush=True)
