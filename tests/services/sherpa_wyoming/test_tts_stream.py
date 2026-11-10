from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import numpy as np
from sherpa_wyoming.config import ServiceConfig
from sherpa_wyoming.providers.tts import TTSProvider
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error
from wyoming.tts import (
    Synthesize,
    SynthesizeChunk,
    SynthesizeStart,
    SynthesizeStop,
    SynthesizeStopped,
)


class FakeStreamingTts:
    def __init__(
        self,
        samples: np.ndarray | None = None,
        *,
        sample_rate: int = 22_050,
        error: Exception | None = None,
        callback_chunk_samples: int = 2048,
    ) -> None:
        self.samples = (
            np.asarray([0.0, 0.25, -0.5], dtype=np.float32)
            if samples is None
            else np.asarray(samples, dtype=np.float32)
        )
        self.sample_rate = sample_rate
        self.error = error
        self.callback_chunk_samples = callback_chunk_samples
        self.calls: list[tuple[str, int, float]] = []
        self.callback_returns: list[int] = []
        self.cancel_observed = threading.Event()

    def generate(
        self,
        text: str,
        *,
        sid: int,
        speed: float,
        callback,
    ):
        self.calls.append((text, sid, speed))
        if self.error is not None:
            raise self.error

        for offset in range(0, len(self.samples), self.callback_chunk_samples):
            chunk = self.samples[offset : offset + self.callback_chunk_samples]
            result = callback(chunk, (offset + len(chunk)) / max(1, len(self.samples)))
            self.callback_returns.append(result)
            if result == 0:
                self.cancel_observed.set()
                break

        return SimpleNamespace(samples=self.samples, sample_rate=self.sample_rate)


def make_provider(
    engine: FakeStreamingTts,
    *,
    max_sentence_chars: int = 80,
    queue_bytes: int = 131_072,
    chunk_bytes: int = 4_096,
) -> TTSProvider:
    return TTSProvider(
        ServiceConfig(
            wake_word_phrase="tivoo",
            tts_max_sentence_chars=max_sentence_chars,
            tts_queue_bytes=queue_bytes,
            tts_chunk_bytes=chunk_bytes,
        ),
        engine,
    )


async def incoming(events):
    for event in events:
        yield event
        await asyncio.sleep(0)


async def collect_stream(session, events, *, chunk_delay: float = 0.0):
    result = []
    async for event in session.stream(incoming(events)):
        result.append(event)
        if chunk_delay and isinstance(event, AudioChunk):
            await asyncio.sleep(chunk_delay)
    return result


def stream_events(text: str, chunks: list[str]):
    return [
        SynthesizeStart().event(),
        *(SynthesizeChunk(text=chunk).event() for chunk in chunks),
        Synthesize(text=text).event(),
        SynthesizeStop().event(),
    ]


def test_stream_deduplicates_compat_synthesize_and_emits_one_audio_stream() -> None:
    text = "你好，世界。How are you?"
    engine = FakeStreamingTts(np.asarray([0.0, 0.5, -0.5], dtype=np.float32))
    session = make_provider(engine).create_stream_session()

    events = asyncio.run(
        collect_stream(
            session,
            stream_events(text, ["你好，", "世界。How are ", "you?"]),
        )
    )

    assert engine.calls == [
        ("你好，世界。", 0, 1.0),
        ("How are you?", 0, 1.0),
    ]
    assert sum(isinstance(event, AudioStart) for event in events) == 1
    assert all(
        isinstance(event, AudioChunk)
        and (event.rate, event.width, event.channels) == (22_050, 2, 1)
        and len(event.audio) <= 4_096
        and len(event.audio) % 2 == 0
        for event in events
        if isinstance(event, AudioChunk)
    )
    assert isinstance(events[-1], SynthesizeStopped)
    assert not any(isinstance(event, AudioStop) for event in events)
    assert engine.callback_returns == [1, 1]


def test_stream_splits_chinese_english_punctuation_and_80_unicode_characters() -> None:
    long_text = "甲" * 81
    text = "你好。English!问号？" + long_text + "尾。"
    engine = FakeStreamingTts()
    session = make_provider(engine).create_stream_session()

    asyncio.run(
        collect_stream(
            session,
            stream_events(text, ["你好。English!问号？", long_text, "尾。"]),
        )
    )

    spoken_segments = [call[0] for call in engine.calls]
    assert spoken_segments == [
        "你好。",
        "English!",
        "问号？",
        "甲" * 80,
        "甲尾。",
    ]
    assert "".join(spoken_segments) == text


def test_stream_queue_applies_backpressure_without_dropping_or_reordering_pcm() -> None:
    samples = np.linspace(-0.9, 0.9, 128, dtype=np.float32)
    engine = FakeStreamingTts(samples, callback_chunk_samples=128)
    session = make_provider(
        engine,
        queue_bytes=16,
        chunk_bytes=4,
    ).create_stream_session()

    events = asyncio.run(
        collect_stream(
            session,
            stream_events("一句。", ["一句。"]),
            chunk_delay=0.002,
        )
    )

    audio = b"".join(event.audio for event in events if isinstance(event, AudioChunk))
    expected = (
        np.clip(
            np.rint(np.clip(samples, -1.0, 1.0) * 32_768.0),
            -32_768,
            32_767,
        )
        .astype("<i2")
        .tobytes()
    )
    assert audio == expected
    assert session.max_queued_pcm_bytes <= 16
    assert session.max_queued_pcm_bytes == 16
    assert (
        max(
            (len(event.audio) for event in events if isinstance(event, AudioChunk)),
            default=0,
        )
        <= 4
    )


def test_stream_cancellation_stops_callback_and_does_not_send_terminal_event() -> None:
    samples = np.linspace(-0.5, 0.5, 512_000, dtype=np.float32)
    engine = FakeStreamingTts(samples, callback_chunk_samples=512_000)
    session = make_provider(
        engine,
        queue_bytes=16,
        chunk_bytes=4,
    ).create_stream_session()
    generator = session.stream(incoming(stream_events("一句。", ["一句。"])))

    async def consume_then_cancel():
        first = await anext(generator)
        second = await anext(generator)
        assert isinstance(first, AudioStart)
        assert isinstance(second, AudioChunk)
        await generator.aclose()
        return first, second

    first, second = asyncio.run(consume_then_cancel())

    assert isinstance(first, AudioStart)
    assert isinstance(second, AudioChunk)
    assert engine.cancel_observed.is_set()
    assert all(value == 0 for value in engine.callback_returns[-1:])
    assert not isinstance(second, SynthesizeStopped)


def test_stream_model_failure_returns_error_without_normal_end_marker() -> None:
    engine = FakeStreamingTts(error=RuntimeError("model failed"))
    session = make_provider(engine).create_stream_session()

    events = asyncio.run(collect_stream(session, stream_events("你好。", ["你好。"])))

    assert isinstance(events[0], AudioStart)
    assert isinstance(events[-1], Error)
    assert events[-1].code == "model_error"
    assert not any(isinstance(event, SynthesizeStopped) for event in events)
    assert engine.calls == [("你好。", 0, 1.0)]


def test_stream_rejects_mismatched_compatibility_text_without_second_synthesis() -> (
    None
):
    engine = FakeStreamingTts()
    session = make_provider(engine).create_stream_session()
    events = [
        SynthesizeStart().event(),
        SynthesizeChunk(text="分块文本。").event(),
        Synthesize(text="不同的完整文本。").event(),
        SynthesizeStop().event(),
    ]

    response = asyncio.run(collect_stream(session, events))

    assert isinstance(response[-1], Error)
    assert response[-1].code == "compat_text_mismatch"
    # The completed sentence may already have started before HA sends the
    # compatibility copy; the mismatch must not trigger a second synthesis.
    assert engine.calls == [("分块文本。", 0, 1.0)]
    assert not any(isinstance(event, SynthesizeStopped) for event in response)


def test_stream_flushes_unterminated_final_text_on_stop() -> None:
    engine = FakeStreamingTts()
    session = make_provider(engine).create_stream_session()
    text = "最后一句没有结束标点"
    events = stream_events(text, [text])

    response = asyncio.run(collect_stream(session, events))

    assert engine.calls == [(text, 0, 1.0)]
    assert isinstance(response[-1], SynthesizeStopped)


def test_disconnect_before_synthesize_stop_does_not_complete_stream() -> None:
    engine = FakeStreamingTts()
    session = make_provider(engine).create_stream_session()
    events = [
        SynthesizeStart().event(),
        SynthesizeChunk(text="尚未结束").event(),
        Synthesize(text="尚未结束").event(),
    ]

    response = asyncio.run(collect_stream(session, events))

    assert not any(isinstance(event, AudioChunk) for event in response)
    assert not any(isinstance(event, SynthesizeStopped) for event in response)
    assert not any(isinstance(event, AudioStop) for event in response)
    assert engine.calls == []


def test_invalid_callback_pcm_returns_audio_format_error() -> None:
    engine = FakeStreamingTts(np.asarray([np.nan, 0.0], dtype=np.float32))
    session = make_provider(engine).create_stream_session()

    response = asyncio.run(
        collect_stream(session, stream_events("坏音频。", ["坏音频。"]))
    )

    assert isinstance(response[-1], Error)
    assert response[-1].code == "audio_format"
    assert not any(isinstance(event, AudioChunk) for event in response)
    assert not any(isinstance(event, SynthesizeStopped) for event in response)
    assert engine.callback_returns == [0]
