import time, statistics, resource
from pathlib import Path
import sherpa_onnx
import soundfile as sf

root=Path("/work/vits-icefall-zh-aishell3")
text="你好，我是你的智能助手。今天过得怎么样？有什么需要我帮忙的吗？"
rule_fsts=",".join(str(root/x) for x in ["phone.fst","date.fst","number.fst"])

def build(threads):
    cfg=sherpa_onnx.OfflineTtsConfig(
      model=sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
          model=str(root/"model.onnx"),
          lexicon=str(root/"lexicon.txt"),
          tokens=str(root/"tokens.txt"),
        ),
        num_threads=threads,
        provider="cpu",
      ),
      rule_fsts=rule_fsts,
      max_num_sentences=1,
    )
    if not cfg.validate():
        raise RuntimeError("TTS config validation failed")
    t0=time.perf_counter()
    tts=sherpa_onnx.OfflineTts(cfg)
    return tts,time.perf_counter()-t0

for threads in (1,2):
    print(f"\n=== THREADS {threads} ===",flush=True)
    tts,load_s=build(threads)
    print(f"MODEL_LOAD_SECONDS={load_s:.3f} NUM_SPEAKERS={tts.num_speakers} SAMPLE_RATE={tts.sample_rate}",flush=True)
    for sid in (21,41,45):
        gen=sherpa_onnx.GenerationConfig()
        gen.sid=sid
        gen.speed=1.0
        t0=time.perf_counter()
        audio=tts.generate(text,gen)
        elapsed=time.perf_counter()-t0
        duration=len(audio.samples)/audio.sample_rate
        path=f"/work/aishell3_sid{sid}_t{threads}.wav"
        sf.write(path,audio.samples,audio.sample_rate,subtype="PCM_16")
        print(f"RESULT sid={sid} threads={threads} elapsed={elapsed:.3f}s audio={duration:.3f}s RTF={elapsed/duration:.3f} realtime_x={duration/elapsed:.2f} file={path}",flush=True)
    if threads==2:
        longer="Tivoo 可以听到你的声音，也能通过网络连接家庭助理。你可以让我打开灯光、查询天气、设置倒计时，或者直接和我聊天。"
        gen=sherpa_onnx.GenerationConfig(); gen.sid=21; gen.speed=1.0
        t0=time.perf_counter(); audio=tts.generate(longer,gen); elapsed=time.perf_counter()-t0
        duration=len(audio.samples)/audio.sample_rate
        sf.write("/work/aishell3_long_t2.wav",audio.samples,audio.sample_rate,subtype="PCM_16")
        print(f"LONG_RESULT elapsed={elapsed:.3f}s audio={duration:.3f}s RTF={elapsed/duration:.3f} file=/work/aishell3_long_t2.wav",flush=True)
print(f"PROCESS_PEAK_RSS_MB={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.1f}",flush=True)
