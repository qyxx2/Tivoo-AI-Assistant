from __future__ import annotations

from typing import Any

import numpy as np
from wyoming.audio import AudioChunk, AudioStart
from wyoming.error import Error
from wyoming.event import Event
from wyoming.wake import Detect, Detection, NotDetected

from ..config import ServiceConfig
from ..model_utils import WAKE_WORD_ID


class WakeWordProvider:
    """Creates isolated Wyoming KWS request sessions around one loaded model."""

    def __init__(self, config: ServiceConfig, keyword_spotter: Any) -> None:
        self.config = config
        self.keyword_spotter = keyword_spotter

    def create_session(self) -> WakeWordSession:
        return WakeWordSession(self.keyword_spotter)


class WakeWordSession:
    """Request-local state; the caller sends returned events on its connection."""

    def __init__(self, keyword_spotter: Any) -> None:
        self.keyword_spotter = keyword_spotter
        self._stream: Any | None = None
        self._audio_started = False
        self._terminal = False

    @property
    def stream(self) -> Any | None:
        return self._stream

    def handle_event(self, event: Event) -> Event | None:
        if self._terminal:
            return None

        if isinstance(event, Detect):
            return self._handle_detect(event)
        if isinstance(event, AudioStart):
            return self._handle_audio_start(event)
        if isinstance(event, AudioChunk):
            return self._handle_audio_chunk(event)

        return self._fail(f"unsupported KWS event: {event.type}", "invalid_event")

    def _handle_detect(self, event: Detect) -> Event | None:
        if self._stream is not None:
            return self._fail("duplicate Detect event", "invalid_state")

        requested_names = event.names or []
        unsupported_names = [name for name in requested_names if name != WAKE_WORD_ID]
        if unsupported_names:
            return self._fail(
                f"unsupported wake word model: {', '.join(unsupported_names)}",
                "unsupported_model",
            )

        try:
            self._stream = self.keyword_spotter.create_stream()
        except RuntimeError as exc:
            return self._fail(f"could not create KWS stream: {exc}", "model_error")

        return None

    def _handle_audio_start(self, event: AudioStart) -> Event | None:
        if self._stream is None or self._audio_started:
            return self._fail(
                "AudioStart is not valid in the current state", "invalid_state"
            )
        if (event.rate, event.width, event.channels) != (16_000, 2, 1):
            return self._fail(
                "KWS audio must be 16000 Hz, 16-bit, mono PCM", "audio_format"
            )

        self._audio_started = True
        return None

    def _handle_audio_chunk(self, event: AudioChunk) -> Event | None:
        if self._stream is None or not self._audio_started:
            return self._fail("AudioChunk received before AudioStart", "invalid_state")
        if (event.rate, event.width, event.channels) != (16_000, 2, 1):
            return self._fail(
                "KWS AudioChunk must match 16000 Hz, 16-bit, mono PCM",
                "audio_format",
            )
        if len(event.audio) % 2:
            return self._fail(
                "KWS PCM chunk is not 16-bit frame aligned", "audio_format"
            )
        if not event.audio:
            return None

        try:
            samples = np.frombuffer(event.audio, dtype="<i2").astype(np.float32)
            samples /= 32_768.0
            self._stream.accept_waveform(16_000, samples)

            while self.keyword_spotter.is_ready(self._stream):
                self.keyword_spotter.decode_stream(self._stream)
                result = self.keyword_spotter.get_result(self._stream)
                if result:
                    self._terminal = True
                    self._release_stream()
                    return Detection(name=WAKE_WORD_ID, timestamp=event.timestamp)
        except RuntimeError as exc:
            return self._fail(f"KWS model inference failed: {exc}", "model_error")

        return None

    def on_eof(self) -> NotDetected | None:
        """Finish a normally ended Wyoming audio stream as a miss when pending."""

        if self._terminal:
            return None
        if self._stream is None:
            self._terminal = True
            return None

        self._terminal = True
        self._release_stream()
        return NotDetected()

    def cancel(self) -> None:
        """Release request state without replying to a cancelled connection."""

        self._terminal = True
        self._release_stream()

    def _fail(self, message: str, code: str) -> Error:
        self._terminal = True
        self._release_stream()
        return Error(text=message, code=code)

    def _release_stream(self) -> None:
        self._stream = None
        self._audio_started = False
