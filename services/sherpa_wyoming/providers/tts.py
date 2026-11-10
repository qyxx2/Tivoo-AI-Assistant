from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

import numpy as np
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error
from wyoming.event import Event, Eventable
from wyoming.tts import (
    Synthesize,
    SynthesizeChunk,
    SynthesizeStart,
    SynthesizeStop,
    SynthesizeStopped,
    SynthesizeTextFormat,
)

from ..config import ServiceConfig
from ..execution import BoundedExecutor, ExecutionQueueFull

_SAMPLE_RATE = 22_050
_SAMPLE_WIDTH = 2
_CHANNELS = 1
_VOICE_NAME = "0"
_LANGUAGE = "zh-CN"
_SENTENCE_ENDINGS = "。！？.!?"
_QUEUE_END = object()
_SENTENCE_END = object()


class TTSProvider:
    """Generate Wyoming audio using the loaded Matcha model."""

    def __init__(self, config: ServiceConfig, tts_engine: Any) -> None:
        self.config = config
        self.tts_engine = tts_engine

    def create_stream_session(
        self, *, execution: BoundedExecutor | None = None
    ) -> TTSStreamSession:
        """Create isolated state and a bounded PCM queue for one request."""

        return TTSStreamSession(self.config, self.tts_engine, execution=execution)

    def synthesize(self, request: Synthesize) -> list[Eventable] | Error:
        """Synthesize plain text using the only configured voice (speaker 0)."""

        voice_error = self._validate_voice(request)
        if voice_error is not None:
            return voice_error

        format_error = self._validate_text_format(request.text_format)
        if format_error is not None:
            return format_error

        if not request.text.strip():
            return Error(text="TTS text cannot be empty", code="empty_text")

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

        pcm_bytes = self._to_pcm_bytes(samples)
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
    def _to_pcm_bytes(samples: np.ndarray) -> bytes:
        clipped = np.clip(samples, -1.0, 1.0)
        quantized = np.clip(np.rint(clipped * 32_768.0), -32_768, 32_767)
        return quantized.astype("<i2").tobytes()

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

    @staticmethod
    def _validate_text_format(
        text_format: str | SynthesizeTextFormat | None,
    ) -> Error | None:
        if text_format not in (None, SynthesizeTextFormat.TEXT, "text"):
            return Error(
                text="Only plain text synthesis is supported",
                code="unsupported_text_format",
            )
        return None

    def handle_event(self, event: Event) -> list[Eventable] | Error:
        """Handle the non-streaming Wyoming request used by P7Ab4."""

        if not Synthesize.is_type(event.type):
            return Error(
                text=f"Unsupported non-streaming TTS event: {event.type}",
                code="invalid_event",
            )
        return self.synthesize(Synthesize.from_event(event))


class TTSStreamSession:
    """Request-local streaming text and bounded callback PCM output."""

    def __init__(
        self,
        config: ServiceConfig,
        tts_engine: Any,
        *,
        execution: BoundedExecutor | None = None,
    ) -> None:
        self.config = config
        self.tts_engine = tts_engine
        self.execution = execution

        self._chunk_bytes = min(config.tts_chunk_bytes, config.tts_queue_bytes)
        self._chunk_bytes -= self._chunk_bytes % _SAMPLE_WIDTH
        self._queue_capacity = (
            config.tts_queue_bytes // self._chunk_bytes
            if self._chunk_bytes >= _SAMPLE_WIDTH
            else 0
        )
        self._config_error = self._queue_capacity < 1
        self._pcm_queue: queue.Queue[bytes | object] = queue.Queue(
            maxsize=max(1, self._queue_capacity)
        )
        self._queue_lock = threading.Lock()
        self._queued_pcm_bytes = 0
        self.max_queued_pcm_bytes = 0

        self._cancelled = threading.Event()
        self._callback_error: Exception | None = None
        self._callback_sample_count = 0
        self._failure: Error | None = None
        self._start_received = False
        self._compat_received = False
        self._input_stopped = False
        self._all_text = ""
        self._buffer = ""

        self._sentences: asyncio.Queue[str | object] | None = None
        self._started: asyncio.Event | None = None
        self._input_task: asyncio.Task[None] | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._used = False

    @property
    def text_char_count(self) -> int:
        return len(self._all_text)

    async def stream(
        self,
        events: AsyncIterable[Event],
    ) -> AsyncIterator[Eventable]:
        """Read one HA Wyoming stream and yield the corresponding audio events."""

        if self._used:
            yield Error(
                text="TTS stream session cannot be reused", code="invalid_state"
            )
            return
        self._used = True

        if self._config_error:
            yield Error(
                text="TTS queue/chunk settings must allow an aligned PCM sample",
                code="invalid_config",
            )
            return

        self._sentences = asyncio.Queue(maxsize=1)
        self._started = asyncio.Event()
        self._input_task = asyncio.create_task(self._read_input(events))
        self._worker_task = asyncio.create_task(self._generate_pcm())

        try:
            await self._started.wait()
            if self._failure is not None:
                yield self._failure
                return
            if not self._start_received or self._cancelled.is_set():
                return

            yield AudioStart(
                rate=_SAMPLE_RATE,
                width=_SAMPLE_WIDTH,
                channels=_CHANNELS,
            )

            while True:
                item = await self._next_pcm()
                if item is None:
                    continue
                if item is _QUEUE_END:
                    if self._failure is not None:
                        yield self._failure
                    elif not self._cancelled.is_set() and self._input_stopped:
                        yield SynthesizeStopped()
                    return
                if self._cancelled.is_set():
                    return

                yield AudioChunk(
                    rate=_SAMPLE_RATE,
                    width=_SAMPLE_WIDTH,
                    channels=_CHANNELS,
                    audio=item,
                )
        finally:
            await self._cleanup()

    async def _read_input(self, events: AsyncIterable[Event]) -> None:
        assert self._started is not None
        try:
            async for raw_event in events:
                if self._cancelled.is_set():
                    return

                if SynthesizeStart.is_type(raw_event.type):
                    if self._start_received:
                        self._fail("duplicate SynthesizeStart event", "invalid_state")
                        return
                    start = SynthesizeStart.from_event(raw_event)
                    voice_error = TTSProvider._validate_voice(
                        Synthesize(text="", voice=start.voice)
                    )
                    format_error = TTSProvider._validate_text_format(start.text_format)
                    if voice_error is not None:
                        self._fail(voice_error.text, voice_error.code)
                        return
                    if format_error is not None:
                        self._fail(format_error.text, format_error.code)
                        return
                    self._start_received = True
                    self._started.set()
                    continue

                if SynthesizeChunk.is_type(raw_event.type):
                    if not self._start_received:
                        self._fail(
                            "SynthesizeChunk received before SynthesizeStart",
                            "invalid_state",
                        )
                        return
                    if self._input_stopped or self._compat_received:
                        self._fail(
                            "text received after compatibility Synthesize",
                            "invalid_state",
                        )
                        return
                    chunk = SynthesizeChunk.from_event(raw_event)
                    self._all_text += chunk.text
                    self._buffer += chunk.text
                    while (sentence := self._take_next_sentence()) is not None:
                        if not await self._queue_sentence(sentence):
                            return
                    continue

                if Synthesize.is_type(raw_event.type):
                    if (
                        not self._start_received
                        or self._input_stopped
                        or self._compat_received
                    ):
                        self._fail(
                            "compatibility Synthesize received outside a stream",
                            "invalid_state",
                        )
                        return
                    synthesize = Synthesize.from_event(raw_event)
                    self._compat_received = True
                    voice_error = TTSProvider._validate_voice(synthesize)
                    format_error = TTSProvider._validate_text_format(
                        synthesize.text_format
                    )
                    if voice_error is not None:
                        self._fail(voice_error.text, voice_error.code)
                        return
                    if format_error is not None:
                        self._fail(format_error.text, format_error.code)
                        return
                    if synthesize.text != self._all_text:
                        self._fail(
                            "compatibility Synthesize text does not match streamed chunks",
                            "compat_text_mismatch",
                        )
                        return
                    continue

                if SynthesizeStop.is_type(raw_event.type):
                    if not self._start_received or not self._compat_received:
                        self._fail(
                            "SynthesizeStop received before compatibility Synthesize",
                            "invalid_state",
                        )
                        return
                    SynthesizeStop.from_event(raw_event)
                    if not self._all_text.strip():
                        self._fail("TTS text cannot be empty", "empty_text")
                        return
                    if self._buffer:
                        if not await self._queue_sentence(self._buffer):
                            return
                        self._buffer = ""
                    if not await self._queue_sentence_end():
                        return
                    self._input_stopped = True
                    return

                self._fail(
                    f"unsupported streaming TTS event: {raw_event.type}",
                    "invalid_event",
                )
                return

            # A TCP EOF without SynthesizeStop represents disconnect/cancel.
            if not self._input_stopped:
                if not self._start_received:
                    self._fail("stream ended before SynthesizeStart", "invalid_state")
                else:
                    self._cancelled.set()
        except asyncio.CancelledError:
            self._cancelled.set()
            raise
        except Exception as exc:  # noqa: BLE001
            self._fail(f"TTS stream input failed: {exc}", "stream_error")
        finally:
            self._started.set()

    def _take_next_sentence(self) -> str | None:
        """Pop one complete segment so a large incoming chunk cannot queue a list."""

        max_chars = self.config.tts_max_sentence_chars
        if not self._buffer:
            return None

        punctuation = min(
            (
                index
                for ending in _SENTENCE_ENDINGS
                if (index := self._buffer.find(ending)) >= 0
            ),
            default=-1,
        )
        if 0 <= punctuation < max_chars:
            boundary = punctuation + 1
        elif len(self._buffer) >= max_chars:
            boundary = max_chars
        else:
            return None

        sentence = self._buffer[:boundary]
        self._buffer = self._buffer[boundary:]
        return sentence

    async def _queue_sentence(self, sentence: str) -> bool:
        assert self._sentences is not None
        while not self._cancelled.is_set():
            try:
                self._sentences.put_nowait(sentence)
                return True
            except asyncio.QueueFull:
                await asyncio.sleep(0.01)
        return False

    async def _queue_sentence_end(self) -> bool:
        assert self._sentences is not None
        while not self._cancelled.is_set():
            try:
                self._sentences.put_nowait(_SENTENCE_END)
                return True
            except asyncio.QueueFull:
                await asyncio.sleep(0.01)
        return False

    async def _generate_pcm(self) -> None:
        assert self._sentences is not None
        try:
            while not self._cancelled.is_set():
                try:
                    sentence = await asyncio.wait_for(
                        self._sentences.get(),
                        timeout=0.05,
                    )
                except TimeoutError:
                    continue
                if sentence is _SENTENCE_END:
                    break
                if isinstance(sentence, str) and sentence.strip():
                    if self.execution is None:
                        await asyncio.to_thread(self._generate_sentence, sentence)
                    else:
                        await self.execution.run(self._generate_sentence, sentence)
        except asyncio.CancelledError:
            self._cancelled.set()
            raise
        except ExecutionQueueFull:
            self._fail("TTS model execution capacity is full", "server_busy")
        except TimeoutError:
            self._fail("TTS generation timed out", "timeout")
        except ValueError as exc:
            self._fail(f"TTS returned invalid PCM audio: {exc}", "audio_format")
        except Exception as exc:  # noqa: BLE001
            if not self._cancelled.is_set() or self._failure is None:
                self._fail(f"TTS generation failed: {exc}", "model_error")
        finally:
            if self._cancelled.is_set():
                self._clear_pcm_queue()
            await asyncio.to_thread(self._queue_end)

    def _generate_sentence(self, sentence: str) -> None:
        self._callback_error = None
        self._callback_sample_count = 0
        generated = self.tts_engine.generate(
            sentence,
            sid=0,
            speed=1.0,
            callback=self._audio_callback,
        )
        if self._callback_error is not None:
            raise ValueError(f"invalid TTS callback audio: {self._callback_error}")
        if self._cancelled.is_set():
            return

        sample_rate = int(generated.sample_rate)
        samples = np.asarray(generated.samples, dtype=np.float32)
        if sample_rate != _SAMPLE_RATE:
            raise ValueError(
                f"TTS audio must be {_SAMPLE_RATE} Hz, got {sample_rate} Hz"
            )
        if samples.ndim != 1 or not np.isfinite(samples).all():
            raise ValueError("TTS audio must be finite mono PCM samples")
        if samples.size == 0 or self._callback_sample_count == 0:
            raise ValueError("TTS callback generated no audio samples")

    def _audio_callback(self, samples: Any, progress: float) -> int:
        del progress
        if self._cancelled.is_set():
            return 0
        try:
            copied = np.array(samples, dtype=np.float32, copy=True)
            if copied.ndim != 1 or not np.isfinite(copied).all():
                raise ValueError("callback samples must be finite mono float32")
            if copied.size == 0:
                return 1

            pcm = TTSProvider._to_pcm_bytes(copied)
            for offset in range(0, len(pcm), self._chunk_bytes):
                if self._cancelled.is_set():
                    return 0
                chunk = pcm[offset : offset + self._chunk_bytes]
                if not self._put_pcm(chunk):
                    return 0
                self._callback_sample_count += len(chunk) // _SAMPLE_WIDTH
        except Exception as exc:  # noqa: BLE001
            self._callback_error = exc
            self._cancelled.set()
            return 0
        return 1

    def _put_pcm(self, chunk: bytes) -> bool:
        while not self._cancelled.is_set():
            with self._queue_lock:
                if self._cancelled.is_set():
                    return False
                try:
                    self._pcm_queue.put_nowait(chunk)
                except queue.Full:
                    pass
                else:
                    self._queued_pcm_bytes += len(chunk)
                    self.max_queued_pcm_bytes = max(
                        self.max_queued_pcm_bytes,
                        self._queued_pcm_bytes,
                    )
                    return True
            if self._cancelled.wait(0.05):
                return False
        return False

    async def _next_pcm(self) -> bytes | object | None:
        try:
            item = await asyncio.to_thread(self._pcm_queue.get, True, 0.05)
        except queue.Empty:
            return None

        if isinstance(item, bytes):
            with self._queue_lock:
                self._queued_pcm_bytes = max(
                    0,
                    self._queued_pcm_bytes - len(item),
                )
        return item

    def _queue_end(self) -> None:
        if self._cancelled.is_set():
            self._clear_pcm_queue()
        while True:
            try:
                self._pcm_queue.put(_QUEUE_END, timeout=0.05)
                return
            except queue.Full:
                if self._cancelled.is_set():
                    self._clear_pcm_queue()

    def _clear_pcm_queue(self) -> None:
        with self._queue_lock:
            while True:
                try:
                    item = self._pcm_queue.get_nowait()
                except queue.Empty:
                    break
                if isinstance(item, bytes):
                    self._queued_pcm_bytes -= len(item)
            self._queued_pcm_bytes = max(0, self._queued_pcm_bytes)

    def _fail(self, message: str, code: str) -> None:
        if self._failure is None:
            self._failure = Error(text=message, code=code)
        self._cancelled.set()

    async def _cleanup(self) -> None:
        self._cancelled.set()
        if self._input_task is not None and not self._input_task.done():
            self._input_task.cancel()
        # Do not cancel a thread-backed model call. The callback sees the
        # cancellation event and returns 0, then this task can finish normally.
        if self._worker_task is not None:
            await asyncio.gather(self._worker_task, return_exceptions=True)
        if self._input_task is not None:
            await asyncio.gather(self._input_task, return_exceptions=True)
        self._clear_pcm_queue()
