from __future__ import annotations

import time
from typing import Any

import numpy as np
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error
from wyoming.event import Event

from ..config import ServiceConfig

_SAMPLE_RATE = 16_000
_SAMPLE_WIDTH = 2
_CHANNELS = 1
_PCM_BYTES_PER_SECOND = _SAMPLE_RATE * _SAMPLE_WIDTH


class STTProvider:
    """Creates request-local Wyoming sessions around one loaded Paraformer model."""

    def __init__(self, config: ServiceConfig, recognizer: Any) -> None:
        self.config = config
        self.recognizer = recognizer

    def create_session(self) -> STTSession:
        return STTSession(
            self.recognizer,
            max_seconds=self.config.stt_max_seconds,
            max_bytes=self.config.stt_max_bytes,
        )


class STTSession:
    """Collects one complete PCM utterance and returns one final transcript."""

    def __init__(
        self,
        recognizer: Any,
        *,
        max_seconds: int,
        max_bytes: int,
    ) -> None:
        self._recognizer = recognizer
        self._max_seconds = max_seconds
        self._max_bytes = max_bytes
        self._stream: Any | None = None
        self._transcribe_received = False
        self._audio_started = False
        self._terminal = False
        self._audio_bytes = 0
        self._decode_seconds = 0.0
        self.language: str | None = None

    @property
    def stream(self) -> Any | None:
        return self._stream

    @property
    def audio_bytes(self) -> int:
        return self._audio_bytes

    @property
    def decode_seconds(self) -> float:
        return self._decode_seconds

    def handle_event(self, event: Event) -> Event | None:
        """Handle one Wyoming event; return a response only when terminal."""

        if self._terminal:
            return None

        if isinstance(event, Transcribe):
            return self._handle_transcribe(event)
        if isinstance(event, AudioStart):
            return self._handle_audio_start(event)
        if isinstance(event, AudioChunk):
            return self._handle_audio_chunk(event)
        if isinstance(event, AudioStop):
            return self._handle_audio_stop()

        return self._fail(
            f"unsupported STT event: {event.type}",
            "invalid_event",
        )

    def cancel(self) -> None:
        """Release a disconnected or cancelled request without sending a reply."""

        self._terminal = True
        self._release_request()

    def _handle_transcribe(self, event: Transcribe) -> Error | None:
        if self._transcribe_received or self._stream is not None:
            return self._fail("duplicate Transcribe event", "invalid_state")

        try:
            self._stream = self._recognizer.create_stream()
        except TimeoutError:
            return self._fail("STT stream creation timed out", "timeout")
        # Normalize Sherpa/NumPy failures at the Wyoming protocol boundary.
        except Exception as exc:  # noqa: BLE001
            return self._fail(f"STT stream creation failed: {exc}", "model_error")

        self._transcribe_received = True
        self.language = event.language
        return None

    def _handle_audio_start(self, event: AudioStart) -> Error | None:
        if self._stream is None or not self._transcribe_received or self._audio_started:
            return self._fail(
                "AudioStart is not valid in the current STT state",
                "invalid_state",
            )
        if (event.rate, event.width, event.channels) != (
            _SAMPLE_RATE,
            _SAMPLE_WIDTH,
            _CHANNELS,
        ):
            return self._fail(
                "STT audio must be 16000 Hz, 16-bit, mono PCM",
                "audio_format",
            )

        self._audio_started = True
        return None

    def _handle_audio_chunk(self, event: AudioChunk) -> Error | None:
        if self._stream is None or not self._audio_started:
            return self._fail(
                "AudioChunk received before a valid AudioStart",
                "invalid_state",
            )
        if (event.rate, event.width, event.channels) != (
            _SAMPLE_RATE,
            _SAMPLE_WIDTH,
            _CHANNELS,
        ):
            return self._fail(
                "STT AudioChunk must be 16000 Hz, 16-bit, mono PCM",
                "audio_format",
            )
        if len(event.audio) % _SAMPLE_WIDTH:
            return self._fail(
                "STT PCM chunk is not 16-bit frame aligned",
                "audio_format",
            )
        if not event.audio:
            return None

        total_bytes = self._audio_bytes + len(event.audio)
        duration_seconds = total_bytes / _PCM_BYTES_PER_SECOND
        if total_bytes >= self._max_bytes or duration_seconds >= self._max_seconds:
            return self._fail(
                "STT audio exceeded the configured request limit",
                "audio_limit",
            )

        try:
            samples = np.frombuffer(event.audio, dtype="<i2").astype(np.float32)
            samples /= 32_768.0
            self._stream.accept_waveform(_SAMPLE_RATE, samples)
        except TimeoutError:
            return self._fail("STT audio processing timed out", "timeout")
        # Normalize Sherpa/NumPy failures at the Wyoming protocol boundary.
        except Exception as exc:  # noqa: BLE001
            return self._fail(f"STT audio processing failed: {exc}", "model_error")

        self._audio_bytes = total_bytes
        return None

    def _handle_audio_stop(self) -> Event:
        if self._stream is None or not self._audio_started:
            return self._fail(
                "AudioStop received before a valid AudioStart",
                "invalid_state",
            )
        if self._audio_bytes == 0:
            return self._fail("STT audio input is empty", "empty_audio")

        stream = self._stream
        decode_started = time.perf_counter()
        try:
            self._recognizer.decode_stream(stream)
            text = stream.result.text
            if not isinstance(text, str):
                raise TypeError("Paraformer returned a non-text result")
        except TimeoutError:
            return self._fail("STT decoding timed out", "timeout")
        # Normalize Sherpa/NumPy failures at the Wyoming protocol boundary.
        except Exception as exc:  # noqa: BLE001
            return self._fail(f"STT decoding failed: {exc}", "model_error")
        finally:
            self._decode_seconds = time.perf_counter() - decode_started

        self._terminal = True
        self._release_request()
        return Transcript(text=text, language=self.language)

    def _fail(self, message: str, code: str) -> Error:
        self._terminal = True
        self._release_request()
        return Error(text=message, code=code)

    def _release_request(self) -> None:
        self._stream = None
        self._audio_started = False
        self._audio_bytes = 0
