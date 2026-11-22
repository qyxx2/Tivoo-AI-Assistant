"""PCM fixture helpers for the isolated P6.8 B8.2 Gateway probe.

The live Gateway client lives in gateway_probe.mjs so its authentication token
is read only inside the existing Qwen container. This module only transforms
local test WAV/PCM fixtures; it has no network or device I/O.
"""

from __future__ import annotations

import array
import math
import random
import sys
import wave
from pathlib import Path

SAMPLE_RATE = 16_000
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
FRAME_BYTES = FRAME_SAMPLES * 2


def _decode_pcm(pcm: bytes) -> array.array:
    if len(pcm) % 2:
        raise ValueError("PCM16 input must be 16-bit aligned")
    values = array.array("h")
    values.frombytes(pcm)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def _encode_pcm(values: array.array) -> bytes:
    if values.itemsize != 2:
        raise RuntimeError("platform short is not 16-bit")
    if sys.byteorder != "little":
        values.byteswap()
    return values.tobytes()


def iter_pcm_frames(pcm: bytes):
    """Yield the ESP32 ingress format: 20 ms, 640-byte, mono S16LE frames."""
    if len(pcm) % 2:
        raise ValueError("PCM16 input must be 16-bit aligned")
    for offset in range(0, len(pcm), FRAME_BYTES):
        yield pcm[offset : offset + FRAME_BYTES].ljust(FRAME_BYTES, b"\x00")


def make_silence(duration_ms: int) -> bytes:
    if duration_ms < 0 or duration_ms % FRAME_MS:
        raise ValueError("silence duration must be a non-negative multiple of 20 ms")
    return bytes(duration_ms * SAMPLE_RATE // 1000 * 2)


def scale_pcm(pcm: bytes, gain: float) -> bytes:
    if not math.isfinite(gain) or gain < 0:
        raise ValueError("gain must be finite and non-negative")
    values = _decode_pcm(pcm)
    return _encode_pcm(
        array.array(
            "h", (max(-32768, min(32767, round(value * gain))) for value in values)
        )
    )


def insert_pause(pcm: bytes, duration_ms: int, *, at_fraction: float = 0.5) -> bytes:
    if duration_ms < 0 or duration_ms % FRAME_MS:
        raise ValueError("pause duration must be a non-negative multiple of 20 ms")
    if not 0 < at_fraction < 1:
        raise ValueError("pause insertion fraction must be between 0 and 1")
    values = _decode_pcm(pcm)
    split = round(len(values) * at_fraction / FRAME_SAMPLES) * FRAME_SAMPLES
    split = max(0, min(len(values), split))
    return (
        _encode_pcm(values[:split])
        + make_silence(duration_ms)
        + _encode_pcm(values[split:])
    )


def add_background_noise(pcm: bytes, *, snr_db: float = 18, seed: int = 7) -> bytes:
    if not math.isfinite(snr_db) or snr_db <= 0:
        raise ValueError("SNR must be positive and finite")
    values = _decode_pcm(pcm)
    if not values:
        return pcm
    rms = math.sqrt(sum(value * value for value in values) / len(values))
    noise_rms = rms / (10 ** (snr_db / 20))
    rng = random.Random(seed)
    return _encode_pcm(
        array.array(
            "h",
            (
                max(-32768, min(32767, round(value + rng.gauss(0, noise_rms))))
                for value in values
            ),
        )
    )


def trim_trailing_silence(
    pcm: bytes, *, threshold_rms: float = 180, keep_ms: int = FRAME_MS
) -> bytes:
    """Remove generated WAV padding but leave the final local-VAD boundary frames."""
    if keep_ms < 0 or keep_ms % FRAME_MS:
        raise ValueError(
            "kept trailing duration must be a non-negative multiple of 20 ms"
        )
    values = _decode_pcm(pcm)
    if not values:
        return pcm
    last_speech_frame = None
    for index in range(math.ceil(len(values) / FRAME_SAMPLES)):
        frame = values[index * FRAME_SAMPLES : (index + 1) * FRAME_SAMPLES]
        if (
            frame
            and math.sqrt(sum(sample * sample for sample in frame) / len(frame))
            >= threshold_rms
        ):
            last_speech_frame = index
    if last_speech_frame is None:
        return pcm
    end_sample = min(
        len(values),
        (last_speech_frame + 1 + keep_ms // FRAME_MS) * FRAME_SAMPLES,
    )
    return _encode_pcm(values[:end_sample])


def resample_pcm(pcm: bytes, source_rate: int, target_rate: int = SAMPLE_RATE) -> bytes:
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("sample rates must be positive")
    values = _decode_pcm(pcm)
    if source_rate == target_rate or not values:
        return pcm
    output = array.array("h")
    for index in range(round(len(values) * target_rate / source_rate)):
        position = index * source_rate / target_rate
        left = min(int(position), len(values) - 1)
        right = min(left + 1, len(values) - 1)
        fraction = position - left
        sample = values[left] + (values[right] - values[left]) * fraction
        output.append(max(-32768, min(32767, round(sample))))
    return _encode_pcm(output)


def load_wav(path: str | Path, *, trim_silence: bool = True) -> tuple[bytes, dict]:
    with wave.open(str(path), "rb") as source:
        rate, channels, width = (
            source.getframerate(),
            source.getnchannels(),
            source.getsampwidth(),
        )
        pcm = source.readframes(source.getnframes())
    if channels != 1 or width != 2:
        raise ValueError(
            f"{path}: expected mono PCM16 WAV, got {channels}ch/{width * 8}bit"
        )
    converted = resample_pcm(pcm, rate)
    original_duration = len(converted) / (SAMPLE_RATE * 2)
    if trim_silence:
        converted = trim_trailing_silence(converted)
    return converted, {
        "path": str(path),
        "source_sample_rate": rate,
        "sample_rate": SAMPLE_RATE,
        "channels": channels,
        "sample_width_bits": width * 8,
        "duration_s": round(len(converted) / (SAMPLE_RATE * 2), 3),
        "trimmed_duration_s": round(
            original_duration - len(converted) / (SAMPLE_RATE * 2), 3
        ),
    }


def pcm_stats(pcm: bytes) -> dict:
    values = _decode_pcm(pcm)
    if not values:
        return {"samples": 0, "duration_s": 0, "peak": 0, "rms": 0}
    return {
        "samples": len(values),
        "duration_s": round(len(values) / SAMPLE_RATE, 3),
        "peak": max(abs(value) for value in values),
        "rms": round(
            math.sqrt(sum(value * value for value in values) / len(values)), 1
        ),
    }
