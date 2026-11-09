#!/usr/bin/env python3
"""CPU benchmark for Matcha Baker and MeloTTS using sherpa-onnx."""
import argparse
import json
import os
import platform
import resource
import time
from datetime import datetime, timezone
from pathlib import Path

import sherpa_onnx
import soundfile as sf

TEXT = (
    "你好，我是你的智能助手。你可以直接告诉我想做什么，我会帮你处理。"
    "今天我也可以帮你打开客厅的灯、播放音乐，或者设置一个十分钟的倒计时。"
)

def build_tts(engine: str, model_root: Path, threads: int):
    if engine == "matcha":
        model = model_root / "matcha-icefall-zh-baker"
        model_config = sherpa_onnx.OfflineTtsModelConfig(
            matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(
                acoustic_model=str(model / "model-steps-3.onnx"),
                vocoder=str(model_root / "vocos-22khz-univ.onnx"),
                tokens=str(model / "tokens.txt"),
                lexicon=str(model / "lexicon.txt"),
            ),
            num_threads=threads,
            provider="cpu",
        )
        rule_fsts = ",".join(str(model / name) for name in ("phone.fst", "date.fst", "number.fst"))
    elif engine == "melo":
        model = model_root / "vits-melo-tts-zh_en"
        model_config = sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(model / "model.onnx"),
                tokens=str(model / "tokens.txt"),
                lexicon=str(model / "lexicon.txt"),
            ),
            num_threads=threads,
            provider="cpu",
        )
        rule_fsts = ",".join(str(model / name) for name in ("phone.fst", "date.fst", "number.fst"))
    else:
        raise ValueError(engine)

    config = sherpa_onnx.OfflineTtsConfig(
        model=model_config,
        max_num_sentences=1,
        rule_fsts=rule_fsts,
    )
    if not config.validate():
        raise RuntimeError(f"Invalid {engine} model config")
    return sherpa_onnx.OfflineTts(config)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=("matcha", "melo"), required=True)
    parser.add_argument("--threads", type=int, choices=(1, 2, 4), required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    tts = build_tts(args.engine, args.model_root, args.threads)
    load_s = time.perf_counter() - started
    common = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "engine": args.engine,
        "threads": args.threads,
        "python": platform.python_version(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "sherpa_onnx": getattr(sherpa_onnx, "__version__", "unknown"),
        "sample_rate": int(tts.sample_rate),
        "speakers": int(tts.num_speakers),
        "model_load_s": round(load_s, 4),
    }
    print(json.dumps({"event": "loaded", **common}, ensure_ascii=False), flush=True)

    for phase in ("first", "warm"):
        started = time.perf_counter()
        audio = tts.generate(TEXT, sid=0, speed=1.0)
        generate_s = time.perf_counter() - started
        duration_s = len(audio.samples) / audio.sample_rate
        filename = f"{args.engine}_t{args.threads}_{phase}.wav"
        output_path = args.output_dir / filename
        sf.write(str(output_path), audio.samples, audio.sample_rate, subtype="PCM_16")
        record = {
            "event": "measurement",
            **common,
            "phase": phase,
            "text": TEXT,
            "audio_duration_s": round(duration_s, 4),
            "generation_s": round(generate_s, 4),
            "rtf": round(generate_s / duration_s, 4),
            "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
            "wav": filename,
        }
        print(json.dumps(record, ensure_ascii=False), flush=True)
        with (args.output_dir / "benchmark.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    main()
