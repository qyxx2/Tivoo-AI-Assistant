"""Generate deterministic spoken Chinese probe prompts with the repo's AISHELL3 VITS model."""

from __future__ import annotations

import argparse
import json
import time
import wave
from pathlib import Path

import sherpa_onnx

ROOT = Path(__file__).resolve().parents[3]
MODEL = ROOT / "benchmarks/voice/tts/nas/models/vits-icefall-zh-aishell3"
PROMPTS = {
    "ask_ascii": "我计划周末去旅行，请先问我一个最重要的问题，最后用英文半角问号结尾。",
    "ask_fullwidth": "我计划周末去旅行，请先问我一个最重要的问题，最后用中文全角问号结尾。",
    "answer_hangzhou": "我想去杭州，喜欢西湖和自然风景，行程不要太紧凑。",
    "answer_followup": "我想坐高铁去，计划住两晚，主要看风景和吃当地美食。",
    "plain_statement": "请用一句简短的话告诉我杭州适合周末旅游吗，只回答结论，不要向我提问。",
    "short_control": "好的，已完成。",
    "normal_statement": "今天我挺开心的。",
    "ask_beginner": "我想开始学习吉他，完全没有乐理基础。请先问我一个最重要的问题，帮助你判断应该怎么教我。",
    "answer_beginner": "我以前没有弹过吉他，也不认识和弦，每天大概能练二十分钟。",
    "ask_first_week": "那第一周我具体应该练什么？请给我一个简单的计划。",
    "ask_short_ascii": "只用一个简短问题询问我每天能练习多久，结尾使用英文半角问号。",
    "ask_short_fullwidth": "只用一个简短问题询问我每天能练习多久，结尾使用中文全角问号。",
    "statement_no_question": "用一句简短陈述告诉我每天练习十分钟是否有意义，不要向我提问。",
    "user_question_only": "你觉得我每天练习十分钟有意义吗？请只回答收到，不要向我提出问题。",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--speaker", type=int, default=21)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(MODEL / "model.onnx"),
                lexicon=str(MODEL / "lexicon.txt"),
                tokens=str(MODEL / "tokens.txt"),
            ),
            num_threads=args.threads,
            provider="cpu",
        ),
        rule_fsts=",".join(
            str(MODEL / name) for name in ("phone.fst", "date.fst", "number.fst")
        ),
        max_num_sentences=1,
    )
    if not config.validate():
        raise SystemExit("AISHELL3 VITS configuration is invalid")
    started = time.perf_counter()
    tts = sherpa_onnx.OfflineTts(config)
    print(
        json.dumps(
            {
                "event": "tts_loaded",
                "load_s": round(time.perf_counter() - started, 3),
                "sample_rate": tts.sample_rate,
                "speaker": args.speaker,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    for name, text in PROMPTS.items():
        generation = sherpa_onnx.GenerationConfig()
        generation.sid = args.speaker
        generation.speed = 1.0
        start = time.perf_counter()
        result = tts.generate(text, generation)
        path = args.output_dir / f"{name}.wav"
        samples = bytearray()
        for sample in result.samples:
            value = max(-32768, min(32767, round(sample * 32768)))
            samples.extend(value.to_bytes(2, "little", signed=True))
        with wave.open(str(path), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(result.sample_rate)
            target.writeframes(samples)
        duration = len(result.samples) / result.sample_rate
        print(
            json.dumps(
                {
                    "event": "fixture",
                    "name": name,
                    "text": text,
                    "duration_s": round(duration, 3),
                    "sample_rate": result.sample_rate,
                    "generate_s": round(time.perf_counter() - start, 3),
                    "path": str(path),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
