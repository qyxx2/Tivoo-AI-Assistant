from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from sherpa_wyoming.config import ServiceConfig
from sherpa_wyoming.providers.tts import TTSProvider
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error
from wyoming.event import Event
from wyoming.tts import Synthesize, SynthesizeTextFormat, SynthesizeVoice


class FakeOfflineTts:
    def __init__(
        self,
        samples: np.ndarray | None = None,
        *,
        sample_rate: int = 22_050,
        error: Exception | None = None,
    ) -> None:
        self.samples = (
            np.asarray([0.0, 0.25, -0.5], dtype=np.float32)
            if samples is None
            else samples
        )
        self.sample_rate = sample_rate
        self.error = error
        self.calls: list[tuple[str, int, float]] = []

    def generate(self, text: str, *, sid: int, speed: float):
        self.calls.append((text, sid, speed))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(samples=self.samples, sample_rate=self.sample_rate)


def make_provider(
    engine: FakeOfflineTts,
    *,
    chunk_bytes: int = 4_096,
) -> TTSProvider:
    return TTSProvider(
        ServiceConfig(
            wake_word_phrase="tivoo",
            tts_chunk_bytes=chunk_bytes,
        ),
        engine,
    )


def test_synthesizes_voice_zero_as_22050_hz_mono_s16le_events() -> None:
    engine = FakeOfflineTts(np.asarray([-1.0, 0.0, 1.0], dtype=np.float32))
    provider = make_provider(engine, chunk_bytes=4)

    response = provider.synthesize(
        Synthesize(text="你好。", voice=SynthesizeVoice(name="0"))
    )

    assert isinstance(response[0], AudioStart)
    assert (response[0].rate, response[0].width, response[0].channels) == (
        22_050,
        2,
        1,
    )
    chunks = response[1:-1]
    assert len(chunks) == 2
    assert all(isinstance(chunk, AudioChunk) for chunk in chunks)
    assert all(
        (chunk.rate, chunk.width, chunk.channels) == (22_050, 2, 1)
        and len(chunk.audio) <= 4
        and len(chunk.audio) % 2 == 0
        for chunk in chunks
    )
    assert (
        b"".join(chunk.audio for chunk in chunks)
        == np.asarray([-32_768, 0, 32_767], dtype="<i2").tobytes()
    )
    assert isinstance(response[-1], AudioStop)
    assert engine.calls == [("你好。", 0, 1.0)]


def test_uses_the_only_voice_when_request_omits_voice() -> None:
    engine = FakeOfflineTts()
    response = make_provider(engine).synthesize(Synthesize(text="你好"))

    assert isinstance(response[0], AudioStart)
    assert isinstance(response[-1], AudioStop)
    assert engine.calls == [("你好", 0, 1.0)]


@pytest.mark.parametrize(
    "voice",
    [
        SynthesizeVoice(name="1"),
        SynthesizeVoice(language="en-US"),
        SynthesizeVoice(name="0", speaker="1"),
        SynthesizeVoice(language="zh-CN", speaker="1"),
    ],
)
def test_rejects_unsupported_voice_without_running_model(
    voice: SynthesizeVoice,
) -> None:
    engine = FakeOfflineTts()

    response = make_provider(engine).synthesize(Synthesize(text="你好", voice=voice))

    assert isinstance(response, Error)
    assert response.code == "unsupported_voice"
    assert engine.calls == []


def test_accepts_zh_cn_language_selection() -> None:
    engine = FakeOfflineTts()

    response = make_provider(engine).synthesize(
        Synthesize(text="你好", voice=SynthesizeVoice(language="zh-CN"))
    )

    assert isinstance(response[0], AudioStart)
    assert isinstance(response[-1], AudioStop)
    assert engine.calls == [("你好", 0, 1.0)]


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_rejects_empty_text_without_running_model(text: str) -> None:
    engine = FakeOfflineTts()

    response = make_provider(engine).synthesize(Synthesize(text=text))

    assert isinstance(response, Error)
    assert response.code == "empty_text"
    assert engine.calls == []


def test_rejects_ssml_instead_of_sending_markup_to_matcha() -> None:
    engine = FakeOfflineTts()

    response = make_provider(engine).synthesize(
        Synthesize(text="<speak>你好</speak>", text_format=SynthesizeTextFormat.SSML)
    )

    assert isinstance(response, Error)
    assert response.code == "unsupported_text_format"
    assert engine.calls == []


def test_model_failure_returns_error_without_audio_stop() -> None:
    engine = FakeOfflineTts(error=RuntimeError("inference failed"))

    response = make_provider(engine).synthesize(Synthesize(text="你好"))

    assert isinstance(response, Error)
    assert response.code == "model_error"
    assert engine.calls == [("你好", 0, 1.0)]


def test_rejects_wrong_sample_rate_without_audio_events() -> None:
    engine = FakeOfflineTts(sample_rate=24_000)

    response = make_provider(engine).synthesize(Synthesize(text="你好"))

    assert isinstance(response, Error)
    assert response.code == "audio_format"


def test_rejects_empty_or_non_finite_model_audio() -> None:
    empty_engine = FakeOfflineTts(np.asarray([], dtype=np.float32))
    empty_response = make_provider(empty_engine).synthesize(Synthesize(text="你好"))
    assert isinstance(empty_response, Error)
    assert empty_response.code == "empty_audio"

    invalid_engine = FakeOfflineTts(np.asarray([np.nan], dtype=np.float32))
    invalid_response = make_provider(invalid_engine).synthesize(Synthesize(text="你好"))
    assert isinstance(invalid_response, Error)
    assert invalid_response.code == "audio_format"


def test_handles_wire_synthesize_event_and_returns_eventable_response() -> None:
    engine = FakeOfflineTts()
    provider = make_provider(engine)

    response = provider.handle_event(
        Synthesize(text="事件输入", voice=SynthesizeVoice(name="0")).event()
    )

    assert isinstance(response, list)
    wire_events = [item.event() for item in response]
    assert [event.type for event in wire_events] == [
        "audio-start",
        "audio-chunk",
        "audio-stop",
    ]
    assert engine.calls == [("事件输入", 0, 1.0)]


def test_rejects_non_synthesize_event() -> None:
    engine = FakeOfflineTts()

    response = make_provider(engine).handle_event(Event(type="audio-start"))

    assert isinstance(response, Error)
    assert response.code == "invalid_event"
    assert engine.calls == []
