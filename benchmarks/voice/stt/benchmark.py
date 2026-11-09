#!/usr/bin/env python3
"""Benchmark sherpa-onnx offline Paraformer on the standard test WAVs."""
import argparse
import json
import platform
import resource
import statistics
import time
import wave
from pathlib import Path

import numpy as np
import sherpa_onnx

p = argparse.ArgumentParser()
p.add_argument("--model-dir", type=Path, required=True)
p.add_argument("--threads", type=int, required=True)
p.add_argument("--repeat", type=int, default=5)
p.add_argument("--output", type=Path, required=True)
args = p.parse_args()

model_dir = args.model_dir
wav_files = sorted((model_dir / "test_wavs").glob("*.wav"))
if not wav_files:
    raise SystemExit(f"No test WAVs found in {model_dir / 'test_wavs'}")

t0 = time.perf_counter()
recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
    paraformer=str(model_dir / "model.int8.onnx"),
    tokens=str(model_dir / "tokens.txt"),
    num_threads=args.threads,
    sample_rate=16000,
    feature_dim=80,
    decoding_method="greedy_search",
    provider="cpu",
)
load_s = time.perf_counter() - t0
print(json.dumps({
    "event": "loaded",
    "engine": "sherpa-onnx-paraformer-zh-small-int8",
    "threads": args.threads,
    "model_load_s": round(load_s, 4),
    "python": platform.python_version(),
    "machine": platform.machine(),
    "cpu_count": __import__("os").cpu_count(),
    "sherpa_onnx": getattr(sherpa_onnx, "__version__", "unknown"),
}, ensure_ascii=False), flush=True)

for path in wav_files:
    with wave.open(str(path), "rb") as f:
        sr, channels, width = f.getframerate(), f.getnchannels(), f.getsampwidth()
        raw = f.readframes(f.getnframes())
    if channels != 1 or width != 2:
        print(f"SKIP {path.name}: {sr} Hz, {channels} ch, {width * 8} bit")
        continue
    audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    duration = len(audio) / sr

    def infer():
        stream = recognizer.create_stream()
        stream.accept_waveform(sr, audio)
        started = time.perf_counter()
        recognizer.decode_streams([stream])
        return time.perf_counter() - started, stream.result.text

    warm_s, recognized = infer()
    samples = []
    for _ in range(args.repeat):
        elapsed, recognized = infer()
        samples.append(elapsed)
    median_s = statistics.median(samples)
    row = {
        "event": "result",
        "file": path.name,
        "sample_rate": sr,
        "audio_duration_s": round(duration, 4),
        "warmup_s": round(warm_s, 4),
        "median_s": round(median_s, 4),
        "min_s": round(min(samples), 4),
        "max_s": round(max(samples), 4),
        "rtf": round(median_s / duration, 4),
        "realtime_x": round(duration / median_s, 3),
        "runs_s": [round(x, 4) for x in samples],
        "text": recognized,
    }
    print(json.dumps(row, ensure_ascii=False), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

print(json.dumps({
    "event": "finished",
    "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
}, ensure_ascii=False), flush=True)
