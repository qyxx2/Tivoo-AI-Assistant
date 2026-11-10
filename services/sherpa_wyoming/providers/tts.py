from __future__ import annotations

from typing import Any

import numpy as np
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error
from wyoming.event import Event, Eventable
from wyoming.tts import Synthesize, SynthesizeTextFormat

from ..config import ServiceConfig

_SAMPLE_RATE = 22_050
_SAMPLE_WIDTH = 2
_CHANNELS = 1
_VOICE_NAME = "0"
_LANGUAGE = "zh-CN"


class TTSProvider:
    """Generate one complete Wyoming audio response with the loaded Matcha model."""

    def __init__(self, config: ServiceConfig, tts_engine: Any) -> None:
        self.config = config
        self.tts_engine = tts_engine

    def synthesize(self, request: Synthesize) -> list[Eventable] | Error:
        """Synthesize plain text using the only configured voice (speaker 0)."""

        voice_error = self._validate_voice(request)
        if voice_error is not None:
            return voice_error

        if not request.text.strip():
            return Error(text="TTS text cannot be empty", code="empty_text")

        if request.text_format not in (None, SynthesizeTextFormat.TEXT, "text"):
            return Error(
                text="Only plain text synthesis is supported",
                code="unsupported_text_format",
            )

        try:
            generated = self.tts_engine.generate(request.text, sid=0, speed=1.0)
        except TimeoutError:
            return Error(text="TTS generation timed out", code="timeout")
        # Normalize Sherpa/NumPy failures at the Wyoming protocol boundary.
        except Exception as exc:  # noqa: BLE001
            return Error(text=f"TTS generation failed: {exc}", code="model_error")

        try:
            sample_rate = int(generated.sample_rate)
            samples = np.asarray(generated.samples, dtype=np.float32)
        except (AttributeError, TypeError, ValueError) as exc:
            return Error(
                text=f"TTS returned an invalid audio result: {exc}",
                code="audio_format",
            )

        if sample_rate != _SAMPLE_RATE:
            return Error(
                text=f"TTS audio must be {_SAMPLE_RATE} Hz, got {sample_rate} Hz",
                code="audio_format",
            )
        if samples.ndim != 1 or not np.isfinite(samples).all():
            return Error(
                text="TTS audio must be finite mono PCM samples",
                code="audio_format",
            )
        if samples.size == 0:
            return Error(text="TTS generated no audio samples", code="empty_audio")

        pcm = np.clip(samples, -1.0, 1.0)
        pcm = np.clip(np.rint(pcm * 32_768.0), -32_768, 32_767)
        pcm_bytes = pcm.astype("<i2").tobytes()

        chunk_size = self.config.tts_chunk_bytes
        chunk_size -= chunk_size % _SAMPLE_WIDTH
        if chunk_size < _SAMPLE_WIDTH:
            return Error(
                text="TTS_CHUNK_BYTES must allow at least one PCM sample",
                code="invalid_config",
            )

        response: list[Eventable] = [
            AudioStart(rate=_SAMPLE_RATE, width=_SAMPLE_WIDTH, channels=_CHANNELS)
        ]
        response.extend(
            AudioChunk(
                rate=_SAMPLE_RATE,
                width=_SAMPLE_WIDTH,
                channels=_CHANNELS,
                audio=pcm_bytes[offset : offset + chunk_size],
            )
            for offset in range(0, len(pcm_bytes), chunk_size)
        )
        response.append(AudioStop())
        return response

    @staticmethod
    def _validate_voice(request: Synthesize) -> Error | None:
        voice = request.voice
        if voice is None:
            # Wyoming permits omitting the voice; the service has one default.
            return None

        if voice.name is not None and voice.name != _VOICE_NAME:
            return Error(
                text=f"Unsupported TTS voice: {voice.name}",
                code="unsupported_voice",
            )
        if voice.language is not None and voice.language != _LANGUAGE:
            return Error(
                text=f"Unsupported TTS language: {voice.language}",
                code="unsupported_voice",
            )
        if voice.speaker is not None and voice.speaker != _VOICE_NAME:
            return Error(
                text=f"Unsupported TTS speaker: {voice.speaker}",
                code="unsupported_voice",
            )
        return None

    def handle_event(self, event: Event) -> list[Eventable] | Error:
        """Handle the non-streaming Wyoming TTS request used by this batch."""

        if not Synthesize.is_type(event.type):
            return Error(
                text=f"Unsupported non-streaming TTS event: {event.type}",
                code="invalid_event",
            )
        return self.synthesize(Synthesize.from_event(event))
