from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from sherpa_wyoming.config import ServiceConfig
from sherpa_wyoming.providers.stt import STTProvider
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error


class FakeStream:
    def __init__(self, text: str, accept_error: Exception | None = None) -> None:
        self.result = SimpleNamespace(text=text)
        self.accepted: list[tuple[int, np.ndarray]] = []
        self.accept_error = accept_error

    def accept_waveform(self, sample_rate: int, samples: np.ndarray) -> None:
        if self.accept_error is not None:
            raise self.accept_error
        self.accepted.append((sample_rate, samples.copy()))


class FakeRecognizer:
    def __init__(
        self,
        texts: list[str] | None = None,
        *,
        create_error: Exception | None = None,
        accept_error: Exception | None = None,
        decode_error: Exception | None = None,
    ) -> None:
        self.texts = list(texts or ["recognized"])
        self.create_error = create_error
        self.accept_error = accept_error
        self.decode_error = decode_error
        self.streams: list[FakeStream] = []
        self.decode_calls: list[FakeStream] = []

    def create_stream(self) -> FakeStream:
        if self.create_error is not None:
            raise self.create_error
        text = self.texts.pop(0) if self.texts else "recognized"
        stream = FakeStream(text, self.accept_error)
        self.streams.append(stream)
        return stream

    def decode_stream(self, stream: FakeStream) -> None:
        self.decode_calls.append(stream)
        if self.decode_error is not None:
            raise self.decode_error


def make_provider(
    recognizer: FakeRecognizer,
    *,
    max_seconds: int = 300,
    max_bytes: int = 9_600_000,
) -> STTProvider:
    config = ServiceConfig(
        wake_word_phrase="tivoo",
        stt_max_seconds=max_seconds,
        stt_max_bytes=max_bytes,
    )
    return STTProvider(config, recognizer)


def start_session(session, *, language: str = "zh-CN") -> None:
    assert session.handle_event(Transcribe(language=language)) is None
    assert session.handle_event(AudioStart(rate=16_000, width=2, channels=1)) is None


def audio_chunk(raw: bytes, *, rate: int = 16_000, width: int = 2, channels: int = 1):
    return AudioChunk(
        rate=rate,
        width=width,
        channels=channels,
        audio=raw,
    )


def test_transcribes_once_after_audio_stop_and_normalizes_pcm() -> None:
    recognizer = FakeRecognizer(["final transcript"])
    session = make_provider(recognizer).create_session()
    samples = np.asarray([0, 16_384, -32_768], dtype="<i2")
    raw = samples.tobytes()

    assert session.handle_event(Transcribe(language="zh-CN")) is None
    assert session.language == "zh-CN"
    assert session.stream is recognizer.streams[0]
    assert session.handle_event(AudioStart(rate=16_000, width=2, channels=1)) is None
    assert session.handle_event(audio_chunk(raw)) is None

    assert recognizer.decode_calls == []
    sample_rate, accepted = recognizer.streams[0].accepted[0]
    assert sample_rate == 16_000
    np.testing.assert_allclose(
        accepted,
        np.asarray([0.0, 0.5, -1.0], dtype=np.float32),
    )

    result = session.handle_event(AudioStop())

    assert isinstance(result, Transcript)
    assert result.text == "final transcript"
    assert result.language == "zh-CN"
    assert recognizer.decode_calls == [recognizer.streams[0]]
    assert session.decode_seconds >= 0
    assert session.stream is None
    assert session.audio_bytes == 0
    assert session.handle_event(AudioStop()) is None
    assert len(recognizer.decode_calls) == 1


def test_valid_silent_audio_returns_empty_transcript_not_error() -> None:
    recognizer = FakeRecognizer([""])
    session = make_provider(recognizer).create_session()
    start_session(session)
    assert session.handle_event(audio_chunk(bytes(320))) is None

    result = session.handle_event(AudioStop())

    assert isinstance(result, Transcript)
    assert result.text == ""
    assert len(recognizer.decode_calls) == 1


def test_empty_audio_returns_wyoming_error_without_decoding() -> None:
    recognizer = FakeRecognizer()
    session = make_provider(recognizer).create_session()
    start_session(session)

    result = session.handle_event(AudioStop())

    assert isinstance(result, Error)
    assert result.code == "empty_audio"
    assert recognizer.decode_calls == []
    assert session.stream is None


def test_audio_start_requires_transcribe_first() -> None:
    session = make_provider(FakeRecognizer()).create_session()

    result = session.handle_event(AudioStart(rate=16_000, width=2, channels=1))

    assert isinstance(result, Error)
    assert result.code == "invalid_state"
    assert session.stream is None


def test_audio_chunk_requires_audio_start() -> None:
    session = make_provider(FakeRecognizer()).create_session()
    assert session.handle_event(Transcribe(language="en-US")) is None

    result = session.handle_event(audio_chunk(b"\x01\x00"))

    assert isinstance(result, Error)
    assert result.code == "invalid_state"
    assert session.stream is None


def test_duplicate_transcribe_or_audio_start_returns_error() -> None:
    session = make_provider(FakeRecognizer()).create_session()
    assert session.handle_event(Transcribe()) is None

    result = session.handle_event(Transcribe())

    assert isinstance(result, Error)
    assert result.code == "invalid_state"
    assert session.stream is None

    session = make_provider(FakeRecognizer()).create_session()
    assert session.handle_event(Transcribe()) is None
    assert session.handle_event(AudioStart(rate=16_000, width=2, channels=1)) is None

    result = session.handle_event(AudioStart(rate=16_000, width=2, channels=1))

    assert isinstance(result, Error)
    assert result.code == "invalid_state"


@pytest.mark.parametrize(
    ("rate", "width", "channels"),
    [
        (8_000, 2, 1),
        (16_000, 1, 1),
        (16_000, 2, 2),
    ],
)
def test_audio_start_rejects_unsupported_pcm_format(
    rate: int, width: int, channels: int
) -> None:
    session = make_provider(FakeRecognizer()).create_session()
    assert session.handle_event(Transcribe()) is None

    result = session.handle_event(AudioStart(rate=rate, width=width, channels=channels))

    assert isinstance(result, Error)
    assert result.code == "audio_format"
    assert session.stream is None


@pytest.mark.parametrize(
    ("rate", "width", "channels", "raw"),
    [
        (8_000, 2, 1, b"\x00\x00"),
        (16_000, 1, 1, b"\x00"),
        (16_000, 2, 2, b"\x00\x00\x00\x00"),
        (16_000, 2, 1, b"\x00"),
    ],
)
def test_audio_chunk_rejects_wrong_format_or_unaligned_pcm(
    rate: int, width: int, channels: int, raw: bytes
) -> None:
    session = make_provider(FakeRecognizer()).create_session()
    start_session(session)

    result = session.handle_event(
        audio_chunk(raw, rate=rate, width=width, channels=channels)
    )

    assert isinstance(result, Error)
    assert result.code == "audio_format"
    assert session.stream is None


def test_byte_limit_rejects_the_chunk_that_reaches_limit() -> None:
    recognizer = FakeRecognizer()
    session = make_provider(recognizer, max_bytes=4).create_session()
    start_session(session)
    assert session.handle_event(audio_chunk(b"\x01\x00")) is None

    result = session.handle_event(audio_chunk(b"\x02\x00"))

    assert isinstance(result, Error)
    assert result.code == "audio_limit"
    assert len(recognizer.streams[0].accepted) == 1
    assert session.stream is None
    assert session.audio_bytes == 0
    assert session.handle_event(audio_chunk(b"\x03\x00")) is None
    assert len(recognizer.streams[0].accepted) == 1


def test_duration_limit_rejects_audio_at_configured_boundary() -> None:
    recognizer = FakeRecognizer()
    session = make_provider(
        recognizer, max_seconds=1, max_bytes=100_000
    ).create_session()
    start_session(session)
    assert session.handle_event(audio_chunk(bytes(31_998))) is None

    result = session.handle_event(audio_chunk(bytes(2)))

    assert isinstance(result, Error)
    assert result.code == "audio_limit"
    assert len(recognizer.streams[0].accepted) == 1
    assert session.stream is None


def test_sessions_use_independent_streams_and_audio() -> None:
    recognizer = FakeRecognizer(["first request", "second request"])
    provider = make_provider(recognizer)
    first = provider.create_session()
    second = provider.create_session()
    start_session(first)
    start_session(second)

    assert first.handle_event(audio_chunk(b"\x01\x00")) is None
    assert second.handle_event(audio_chunk(b"\x02\x00")) is None
    first_stream, second_stream = recognizer.streams
    assert first_stream is not second_stream
    assert first_stream.accepted[0][1].tolist() == [1 / 32768]
    assert second_stream.accepted[0][1].tolist() == [2 / 32768]

    first_result = first.handle_event(AudioStop())
    second_result = second.handle_event(AudioStop())

    assert isinstance(first_result, Transcript)
    assert isinstance(second_result, Transcript)
    assert first_result.text == "first request"
    assert second_result.text == "second request"
    assert recognizer.decode_calls == [first_stream, second_stream]


def test_cancel_releases_stream_and_ignores_later_events() -> None:
    recognizer = FakeRecognizer()
    session = make_provider(recognizer).create_session()
    start_session(session)
    assert session.handle_event(audio_chunk(b"\x01\x00")) is None

    session.cancel()

    assert session.stream is None
    assert session.audio_bytes == 0
    assert session.handle_event(AudioStop()) is None
    assert recognizer.decode_calls == []


def test_model_creation_failure_returns_error() -> None:
    session = make_provider(
        FakeRecognizer(create_error=RuntimeError("create failed"))
    ).create_session()

    result = session.handle_event(Transcribe())

    assert isinstance(result, Error)
    assert result.code == "model_error"
    assert session.stream is None


def test_model_audio_failure_returns_error_and_releases_stream() -> None:
    recognizer = FakeRecognizer(accept_error=RuntimeError("accept failed"))
    session = make_provider(recognizer).create_session()
    start_session(session)

    result = session.handle_event(audio_chunk(b"\x01\x00"))

    assert isinstance(result, Error)
    assert result.code == "model_error"
    assert session.stream is None
    assert session.audio_bytes == 0


def test_model_decode_failure_returns_error_and_releases_stream() -> None:
    recognizer = FakeRecognizer(decode_error=RuntimeError("decode failed"))
    session = make_provider(recognizer).create_session()
    start_session(session)
    assert session.handle_event(audio_chunk(b"\x01\x00")) is None

    result = session.handle_event(AudioStop())

    assert isinstance(result, Error)
    assert result.code == "model_error"
    assert session.stream is None


def test_model_timeout_returns_wyoming_error() -> None:
    recognizer = FakeRecognizer(decode_error=TimeoutError("decode timed out"))
    session = make_provider(recognizer).create_session()
    start_session(session)
    assert session.handle_event(audio_chunk(b"\x01\x00")) is None

    result = session.handle_event(AudioStop())

    assert isinstance(result, Error)
    assert result.code == "timeout"
    assert session.stream is None
