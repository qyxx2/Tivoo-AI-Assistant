import argparse, time, statistics, resource, wave
from pathlib import Path
import numpy as np
import sherpa_onnx

p=argparse.ArgumentParser()
p.add_argument("--model-dir", required=True)
p.add_argument("--threads", type=int, required=True)
p.add_argument("--repeat", type=int, default=5)
args=p.parse_args()
md=Path(args.model_dir)

wav_files=sorted((md/"test_wavs").glob("*.wav"))
if not wav_files:
    raise SystemExit("No downloaded test WAV files")

t0=time.perf_counter()
rec=sherpa_onnx.OfflineRecognizer.from_paraformer(
    paraformer=str(md/"model.int8.onnx"),
    tokens=str(md/"tokens.txt"),
    num_threads=args.threads,
    sample_rate=16000,
    feature_dim=80,
    decoding_method="greedy_search",
)
print(f"MODEL_LOAD_SECONDS={time.perf_counter()-t0:.3f}", flush=True)
print(f"THREADS={args.threads}", flush=True)

for path in wav_files:
    with wave.open(str(path),"rb") as f:
        sr,ch,width=f.getframerate(),f.getnchannels(),f.getsampwidth()
        n=f.getnframes()
        raw=f.readframes(n)
    if (sr,ch,width)!=(16000,1,2):
        print(f"SKIP {path.name}: {sr}Hz {ch}ch {width*8}bit", flush=True)
        continue
    audio=np.frombuffer(raw,dtype="<i2").astype(np.float32)/32768
    duration=len(audio)/sr

    def infer():
        s=rec.create_stream()
        s.accept_waveform(sr,audio)
        t=time.perf_counter()
        rec.decode_streams([s])
        return time.perf_counter()-t,s.result.text

    warm,text=infer()
    times=[]
    for _ in range(args.repeat):
        dt,text=infer()
        times.append(dt)
    med=statistics.median(times)
    print(
      f"RESULT file={path.name} audio={duration:.3f}s warmup={warm:.3f}s "
      f"median={med:.3f}s min={min(times):.3f}s max={max(times):.3f}s "
      f"RTF={med/duration:.3f} realtime_x={duration/med:.2f} "
      f"runs={','.join(f'{v:.3f}' for v in times)} text={text}",
      flush=True
    )
print(f"PROCESS_PEAK_RSS_MB={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.1f}", flush=True)
