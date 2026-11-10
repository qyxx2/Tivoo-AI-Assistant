from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    wake_word_phrase: str
    host: str = "0.0.0.0"
    port: int = 10400
    models_dir: Path = Path("/models")
    kws_num_threads: int = 1
    kws_score: float = 1.0
    kws_threshold: float = 0.25
    kws_num_trailing_blanks: int = 1
    stt_num_threads: int = 2
    stt_max_seconds: int = 300
    stt_max_bytes: int = 9_600_000
    tts_num_threads: int = 1
    tts_max_sentence_chars: int = 80
    tts_queue_bytes: int = 131_072
    tts_chunk_bytes: int = 4_096
    max_pending_per_model: int = 1


def _parse_int(environ: Mapping[str, str], key: str, default: int) -> int:
    try:
        return int(environ.get(key, str(default)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc


def _parse_float(environ: Mapping[str, str], key: str, default: float) -> float:
    try:
        return float(environ.get(key, str(default)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc


def _positive(key: str, value: int) -> None:
    if value <= 0:
        raise ValueError(f"{key} must be greater than zero")


def load_config(
    environ: Mapping[str, str] | None = None,
) -> ServiceConfig:
    """Load and validate the immutable service configuration."""

    values = os.environ if environ is None else environ
    phrase = values.get("WAKE_WORD_PHRASE", "").strip()
    if not phrase:
        raise ValueError("WAKE_WORD_PHRASE is required and cannot be blank")

    host = values.get("HOST", "0.0.0.0").strip()
    if not host:
        raise ValueError("HOST cannot be blank")

    raw_models_dir = values.get("MODELS_DIR", "/models").strip()
    if not raw_models_dir:
        raise ValueError("MODELS_DIR cannot be blank")

    port = _parse_int(values, "PORT", 10400)
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be between 1 and 65535")

    kws_num_threads = _parse_int(values, "KWS_NUM_THREADS", 1)
    kws_score = _parse_float(values, "KWS_SCORE", 1.0)
    kws_threshold = _parse_float(values, "KWS_THRESHOLD", 0.25)
    kws_num_trailing_blanks = _parse_int(values, "KWS_NUM_TRAILING_BLANKS", 1)
    stt_num_threads = _parse_int(values, "STT_NUM_THREADS", 2)
    stt_max_seconds = _parse_int(values, "STT_MAX_SECONDS", 300)
    stt_max_bytes = _parse_int(values, "STT_MAX_BYTES", 9_600_000)
    tts_num_threads = _parse_int(values, "TTS_NUM_THREADS", 1)
    tts_max_sentence_chars = _parse_int(values, "TTS_MAX_SENTENCE_CHARS", 80)
    tts_queue_bytes = _parse_int(values, "TTS_QUEUE_BYTES", 131_072)
    tts_chunk_bytes = _parse_int(values, "TTS_CHUNK_BYTES", 4_096)
    max_pending_per_model = _parse_int(values, "MAX_PENDING_PER_MODEL", 1)

    for key, value in (
        ("KWS_NUM_THREADS", kws_num_threads),
        ("STT_NUM_THREADS", stt_num_threads),
        ("STT_MAX_SECONDS", stt_max_seconds),
        ("STT_MAX_BYTES", stt_max_bytes),
        ("TTS_NUM_THREADS", tts_num_threads),
        ("TTS_MAX_SENTENCE_CHARS", tts_max_sentence_chars),
        ("MAX_PENDING_PER_MODEL", max_pending_per_model),
    ):
        _positive(key, value)

    if not math.isfinite(kws_score) or kws_score < 0:
        raise ValueError("KWS_SCORE must be finite and non-negative")
    if not 0.0 <= kws_threshold <= 1.0:
        raise ValueError("KWS_THRESHOLD must be between 0 and 1")
    if kws_num_trailing_blanks < 0:
        raise ValueError("KWS_NUM_TRAILING_BLANKS cannot be negative")

    if not 0 < tts_queue_bytes <= 131_072:
        raise ValueError("TTS_QUEUE_BYTES must be between 1 and 131072")
    if not 0 < tts_chunk_bytes <= 4_096:
        raise ValueError("TTS_CHUNK_BYTES must be between 1 and 4096")
    if tts_chunk_bytes > tts_queue_bytes:
        raise ValueError("TTS_CHUNK_BYTES cannot exceed TTS_QUEUE_BYTES")

    return ServiceConfig(
        host=host,
        port=port,
        models_dir=Path(raw_models_dir),
        wake_word_phrase=phrase,
        kws_num_threads=kws_num_threads,
        kws_score=kws_score,
        kws_threshold=kws_threshold,
        kws_num_trailing_blanks=kws_num_trailing_blanks,
        stt_num_threads=stt_num_threads,
        stt_max_seconds=stt_max_seconds,
        stt_max_bytes=stt_max_bytes,
        tts_num_threads=tts_num_threads,
        tts_max_sentence_chars=tts_max_sentence_chars,
        tts_queue_bytes=tts_queue_bytes,
        tts_chunk_bytes=tts_chunk_bytes,
        max_pending_per_model=max_pending_per_model,
    )
