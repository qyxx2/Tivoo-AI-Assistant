from __future__ import annotations

import asyncio
import logging
import os
import platform
import time
import uuid
from collections.abc import AsyncIterator, Callable
from functools import partial
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error
from wyoming.event import Event
from wyoming.info import (
    AsrModel,
    AsrProgram,
    Attribution,
    Describe,
    Info,
    TtsProgram,
    TtsVoice,
    WakeModel,
    WakeProgram,
)
from wyoming.server import AsyncEventHandler, AsyncTcpServer
from wyoming.tts import Synthesize, SynthesizeStart, SynthesizeStop
from wyoming.wake import Detect, Detection

from .config import ServiceConfig, load_config
from .execution import BoundedExecutor, ExecutionQueueFull
from .model_utils import WAKE_WORD_ID, generate_kws_keywords
from .models import ModelBundle, load_models
from .providers.stt import STTProvider, STTSession
from .providers.tts import TTSProvider, TTSStreamSession
from .providers.wake import WakeWordProvider, WakeWordSession

_LOGGER = logging.getLogger("tivoo.sherpa_wyoming")
_ATTRIBUTION = Attribution(
    name="k2-fsa",
    url="https://github.com/k2-fsa/sherpa-onnx",
)


def build_wyoming_info(config: ServiceConfig) -> Info:
    """Describe the three installed Providers exposed by this single process."""

    return Info(
        wake=[
            WakeProgram(
                name="Sherpa ONNX Wake Word",
                attribution=_ATTRIBUTION,
                installed=True,
                description="Sherpa-ONNX keyword spotting",
                version="2.0.1",
                models=[
                    WakeModel(
                        name=WAKE_WORD_ID,
                        attribution=_ATTRIBUTION,
                        installed=True,
                        description="Configured Tivoo wake phrase",
                        version="2025-12-20",
                        languages=["zh-CN", "en-US"],
                        phrase=config.wake_word_phrase,
                    )
                ],
            )
        ],
        asr=[
            AsrProgram(
                name="Sherpa ONNX Paraformer",
                attribution=_ATTRIBUTION,
                installed=True,
                description="Offline Paraformer speech recognition",
                version="2.0.1",
                models=[
                    AsrModel(
                        name="paraformer-zh-small-2024-03-09",
                        attribution=_ATTRIBUTION,
                        installed=True,
                        description="Paraformer zh-small INT8",
                        version="2024-03-09",
                        languages=["zh-CN", "en-US"],
                    )
                ],
                supports_transcript_streaming=False,
                requires_external_vad=True,
            )
        ],
        tts=[
            TtsProgram(
                name="Sherpa ONNX Matcha Baker",
                attribution=_ATTRIBUTION,
                installed=True,
                description="Matcha Baker with Vocos 22.05 kHz",
                version="2.0.1",
                voices=[
                    TtsVoice(
                        name="0",
                        attribution=_ATTRIBUTION,
                        installed=True,
                        description="Matcha Baker speaker 0",
                        version=None,
                        languages=["zh-CN"],
                    )
                ],
                supports_synthesize_streaming=True,
            )
        ],
    )


class ModelExecutors:
    """Shared per-model execution limits across all TCP connections."""

    def __init__(self, config: ServiceConfig) -> None:
        pending = config.max_pending_per_model
        self.kws = BoundedExecutor(max_workers=1, max_pending=pending, name="kws")
        # The Sherpa recognizer itself uses two internal CPU threads. Keep one
        # request at a time until the shared model object is proven thread-safe.
        self.stt = BoundedExecutor(max_workers=1, max_pending=pending, name="stt")
        self.tts = BoundedExecutor(max_workers=1, max_pending=pending, name="tts")

    def shutdown(self) -> None:
        self.kws.shutdown()
        self.stt.shutdown()
        self.tts.shutdown()


class WyomingEventHandler(AsyncEventHandler):
    """One connection-scoped dispatcher; all request state stays connection-local."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        info: Info,
        wake_provider: WakeWordProvider,
        stt_provider: STTProvider,
        tts_provider: TTSProvider,
        executors: ModelExecutors,
    ) -> None:
        super().__init__(reader, writer)
        self.info = info
        self.wake_provider = wake_provider
        self.stt_provider = stt_provider
        self.tts_provider = tts_provider
        self.executors = executors

        self._request_id: str | None = None
        self._provider: str | None = None
        self._wake_session: WakeWordSession | None = None
        self._stt_session: STTSession | None = None
        self._tts_session: TTSStreamSession | None = None
        self._tts_input: asyncio.Queue[Event] | None = None
        self._tts_task: asyncio.Task[None] | None = None
        self._request_started = 0.0
        self._model_seconds = 0.0
        self._audio_bytes = 0
        self._tts_first_chunk_seconds: float | None = None

    async def handle_event(self, event: Event) -> bool:
        if Describe.is_type(event.type):
            await self.write_event(self.info.event())
            return True

        if self._provider is None:
            if Detect.is_type(event.type):
                self._begin_request("kws")
                self._wake_session = self.wake_provider.create_session()
                return await self._handle_wake(event)
            if Transcribe.is_type(event.type):
                self._begin_request("stt")
                self._stt_session = self.stt_provider.create_session()
                return await self._handle_stt(event)
            if Synthesize.is_type(event.type):
                self._begin_request("tts")
                return await self._handle_nonstream_tts(event)
            if SynthesizeStart.is_type(event.type):
                self._begin_request("tts_stream")
                return await self._start_streaming_tts(event)
            await self._send_error(
                "request must start with a supported Wyoming event", "invalid_event"
            )
            return True

        if self._provider == "kws":
            return await self._handle_wake(event)
        if self._provider == "stt":
            return await self._handle_stt(event)
        if self._provider == "tts":
            return await self._handle_nonstream_tts(event)
        if self._provider == "tts_stream":
            return await self._handle_streaming_tts(event)

        await self._send_error(
            "connection has an invalid request state", "invalid_state"
        )
        self._reset_request()
        return True

    def _begin_request(self, provider: str) -> None:
        self._request_id = uuid.uuid4().hex[:12]
        self._provider = provider
        self._request_started = time.perf_counter()
        self._model_seconds = 0.0
        self._audio_bytes = 0
        self._tts_first_chunk_seconds = None
        _LOGGER.debug(
            "request_started request_id=%s provider=%s", self._request_id, provider
        )

    async def _handle_wake(self, event: Event) -> bool:
        assert self._wake_session is not None
        typed_event = _provider_event(event)
        if isinstance(typed_event, AudioChunk):
            self._audio_bytes += len(typed_event.audio)
        started = time.perf_counter()
        try:
            result = await self.executors.kws.run(
                self._wake_session.handle_event, typed_event
            )
        except ExecutionQueueFull:
            self._wake_session.cancel()
            await self._send_error("KWS request capacity is full", "server_busy")
            self._finish_request("busy", "kws")
            return True
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "provider_request_failed request_id=%s provider=kws error_type=%s",
                self._request_id,
                type(exc).__name__,
            )
            self._wake_session.cancel()
            await self._send_error("KWS inference failed", "model_error")
            self._finish_request("error", "kws", error_code="model_error")
            return True
        self._model_seconds += time.perf_counter() - started

        if result is not None:
            await self.write_event(result.event())
            outcome = "detected" if isinstance(result, Detection) else "error"
            self._finish_request(
                outcome,
                "kws",
                audio_seconds=self._audio_bytes / 32_000,
                error_code=getattr(result, "code", None),
            )
        return True

    async def _handle_stt(self, event: Event) -> bool:
        assert self._stt_session is not None
        typed_event = _provider_event(event)
        if isinstance(typed_event, AudioChunk):
            self._audio_bytes += len(typed_event.audio)
        started = time.perf_counter()
        try:
            result = await self.executors.stt.run(
                self._stt_session.handle_event, typed_event
            )
        except ExecutionQueueFull:
            self._stt_session.cancel()
            await self._send_error("STT request capacity is full", "server_busy")
            self._finish_request("busy", "stt")
            return True
        self._model_seconds += time.perf_counter() - started

        if isinstance(typed_event, AudioStop):
            duration = self._audio_bytes / 32_000
            decode_seconds = self._stt_session.decode_seconds
            rtf = decode_seconds / duration if duration else None
            if result is not None:
                await self.write_event(result.event())
            self._finish_request(
                (
                    "error"
                    if isinstance(result, Error) or result is None
                    else "empty_transcript"
                    if isinstance(result, Transcript) and not result.text
                    else "transcribed"
                ),
                "stt",
                audio_seconds=duration,
                decode_seconds=decode_seconds,
                rtf=rtf,
                error_code=getattr(result, "code", None),
            )
        elif isinstance(result, Error):
            await self.write_event(result.event())
            self._finish_request("error", "stt", error_code=result.code)
        return True

    async def _handle_nonstream_tts(self, event: Event) -> bool:
        started = time.perf_counter()
        try:
            response = await self.executors.tts.run(
                self.tts_provider.handle_event,
                event,
            )
        except ExecutionQueueFull:
            await self._send_error("TTS request capacity is full", "server_busy")
            self._finish_request("busy", "tts")
            return True

        if isinstance(response, Error):
            await self.write_event(response.event())
            self._finish_request("error", "tts", error_code=response.code)
            return True

        duration = time.perf_counter() - started
        self._model_seconds += duration
        for item in response:
            await self.write_event(item.event())
        self._finish_request(
            "synthesized",
            "tts",
            generate_seconds=duration,
            text_chars=len(Synthesize.from_event(event).text),
            audio_bytes=sum(
                len(item.audio) for item in response if isinstance(item, AudioChunk)
            ),
        )
        return True

    async def _start_streaming_tts(self, event: Event) -> bool:
        self._tts_session = self.tts_provider.create_stream_session(
            execution=self.executors.tts
        )
        self._tts_input = asyncio.Queue(maxsize=2)
        self._tts_task = asyncio.create_task(self._forward_streaming_tts())
        await self._tts_input.put(event)
        return True

    async def _handle_streaming_tts(self, event: Event) -> bool:
        assert self._tts_input is not None
        assert self._tts_task is not None
        if self._tts_task.done():
            # The streaming task already emitted its terminal Error.
            await self._collect_stream_task()
            self._reset_request()
            return True

        await self._tts_input.put(event)
        if SynthesizeStop.is_type(event.type):
            await self._collect_stream_task()
            self._reset_request()
        return True

    async def _forward_streaming_tts(self) -> None:
        assert self._tts_session is not None
        assert self._tts_input is not None
        first_chunk_at: float | None = None
        audio_bytes = 0
        outcome = "finished"
        error_code: str | None = None
        try:
            async for item in self._tts_session.stream(self._iter_tts_input()):
                if isinstance(item, Error):
                    outcome = "error"
                    error_code = item.code
                if isinstance(item, AudioChunk):
                    audio_bytes += len(item.audio)
                    if first_chunk_at is None:
                        first_chunk_at = time.perf_counter()
                        self._tts_first_chunk_seconds = (
                            first_chunk_at - self._request_started
                        )
                await self.write_event(item.event())
        except (ConnectionError, BrokenPipeError):
            outcome = "disconnected"
            raise
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            error_code = "stream_error"
            _LOGGER.warning(
                "tts_stream_failed request_id=%s error_type=%s",
                self._request_id,
                type(exc).__name__,
            )
            if not self.writer.is_closing():
                await self._send_error("TTS stream failed", "stream_error")
        finally:
            _LOGGER.info(
                "request_complete request_id=%s provider=tts_stream outcome=%s "
                "error_code=%s duration_seconds=%.3f text_chars=%d first_pcm_seconds=%s "
                "queue_peak_bytes=%d audio_bytes=%d rss_kib=%d rss_peak_kib=%d",
                self._request_id,
                outcome,
                error_code or "none",
                time.perf_counter() - self._request_started,
                self._tts_session.text_char_count,
                (
                    f"{self._tts_first_chunk_seconds:.3f}"
                    if self._tts_first_chunk_seconds is not None
                    else "none"
                ),
                self._tts_session.max_queued_pcm_bytes,
                audio_bytes,
                *_rss_metrics(),
            )

    async def _iter_tts_input(self) -> AsyncIterator[Event]:
        assert self._tts_input is not None
        while True:
            yield await self._tts_input.get()

    async def _collect_stream_task(self) -> None:
        if self._tts_task is None:
            return
        try:
            await self._tts_task
        except asyncio.CancelledError:
            raise
        except (ConnectionError, BrokenPipeError) as exc:
            _LOGGER.debug(
                "tts_stream_connection_closed request_id=%s error_type=%s",
                self._request_id,
                type(exc).__name__,
            )
        self._tts_task = None

    async def _send_error(self, message: str, code: str) -> None:
        if not self.writer.is_closing():
            await self.write_event(Error(text=message, code=code).event())

    def _finish_request(
        self,
        outcome: str,
        provider: str,
        *,
        error_code: str | None = None,
        **metrics: Any,
    ) -> None:
        duration = time.perf_counter() - self._request_started
        audio_seconds = metrics.get("audio_seconds")
        processing_lag = (
            self._model_seconds - audio_seconds if audio_seconds is not None else None
        )
        details = " ".join(
            f"{key}={value:.3f}" if isinstance(value, float) else f"{key}={value}"
            for key, value in metrics.items()
            if key != "audio_seconds"
        )
        _LOGGER.info(
            "request_complete request_id=%s provider=%s outcome=%s duration_seconds=%.3f "
            "model_seconds=%.3f error_code=%s audio_seconds=%s processing_lag_seconds=%s "
            "rss_kib=%d rss_peak_kib=%d %s",
            self._request_id,
            provider,
            outcome,
            duration,
            self._model_seconds,
            error_code or "none",
            f"{audio_seconds:.3f}" if audio_seconds is not None else "none",
            f"{processing_lag:.3f}" if processing_lag is not None else "none",
            *_rss_metrics(),
            details,
        )
        self._reset_request()

    def _reset_request(self) -> None:
        self._provider = None
        self._request_id = None
        self._wake_session = None
        self._stt_session = None
        self._tts_session = None
        self._tts_input = None
        self._tts_task = None

    async def disconnect(self) -> None:
        if self._provider == "kws" and self._wake_session is not None:
            result = self._wake_session.on_eof()
            if result is not None and not self.writer.is_closing():
                try:
                    await self.write_event(result.event())
                except (ConnectionError, BrokenPipeError):
                    pass
            self._finish_request(
                "not_detected" if result is not None else "disconnected",
                "kws",
                audio_seconds=self._audio_bytes / 32_000,
            )
        elif self._provider == "stt" and self._stt_session is not None:
            self._stt_session.cancel()
            self._finish_request("cancelled", "stt")
        elif self._provider == "tts_stream":
            if self._tts_task is not None:
                self._tts_task.cancel()
                await asyncio.gather(self._tts_task, return_exceptions=True)
            self._reset_request()


def create_handler_factory(
    config: ServiceConfig,
    models: ModelBundle,
    info: Info,
    *,
    executors: ModelExecutors,
) -> Callable[..., WyomingEventHandler]:
    """Build the one connection handler factory passed to AsyncTcpServer."""

    wake_provider = WakeWordProvider(config, models.keyword_spotter)
    stt_provider = STTProvider(config, models.stt_recognizer)
    tts_provider = TTSProvider(config, models.tts_engine)
    return partial(
        WyomingEventHandler,
        info=info,
        wake_provider=wake_provider,
        stt_provider=stt_provider,
        tts_provider=tts_provider,
        executors=executors,
    )


async def run_server(
    config: ServiceConfig | None = None,
    *,
    keyword_generator: Callable[[Any, str], Any] | None = None,
    model_loader: Callable[[ServiceConfig], ModelBundle] | None = None,
    server_factory: Callable[[str, int], AsyncTcpServer] | None = None,
) -> None:
    """Load the full model bundle and then start the single Wyoming TCP server."""

    service_config = config or load_config()
    generate_keywords = keyword_generator or generate_kws_keywords
    load_bundle = model_loader or load_models
    create_server = server_factory or AsyncTcpServer

    startup_started = time.perf_counter()
    try:
        generate_keywords(service_config.models_dir, service_config.wake_word_phrase)
    except Exception as exc:
        _LOGGER.error(
            "startup_failed stage=keyword_generation error_type=%s",
            type(exc).__name__,
        )
        raise

    try:
        models = load_bundle(service_config)
    except Exception as exc:
        _LOGGER.error(
            "startup_failed stage=model_loading error_type=%s",
            type(exc).__name__,
        )
        raise
    load_seconds = time.perf_counter() - startup_started
    info = build_wyoming_info(service_config)
    executors = ModelExecutors(service_config)
    handler_factory = create_handler_factory(
        service_config,
        models,
        info,
        executors=executors,
    )
    server = create_server(service_config.host, service_config.port)

    _LOGGER.info(
        "service_starting host=%s port=%d python=%s sherpa_onnx=%s wyoming=%s "
        "provider=cpu model_load_seconds=%.3f kws_threads=%d stt_threads=%d "
        "tts_threads=%d workers_per_model=1 max_pending_per_model=%d "
        "rss_kib=%d rss_peak_kib=%d",
        service_config.host,
        service_config.port,
        platform.python_version(),
        _package_version("sherpa-onnx"),
        _package_version("wyoming"),
        load_seconds,
        service_config.kws_num_threads,
        service_config.stt_num_threads,
        service_config.tts_num_threads,
        service_config.max_pending_per_model,
        *_rss_metrics(),
    )
    try:
        await server.run(handler_factory)
    except Exception as exc:
        _LOGGER.error(
            "server_run_failed host=%s port=%d error_type=%s",
            service_config.host,
            service_config.port,
            type(exc).__name__,
        )
        raise
    finally:
        await server.stop()
        executors.shutdown()


def _provider_event(event: Event) -> Event:
    """Decode Wyoming wire events into the typed objects provider sessions expect."""

    for event_type in (Detect, Transcribe, AudioStart, AudioChunk, AudioStop):
        if event_type.is_type(event.type):
            return event_type.from_event(event)
    return event


def _package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


def _rss_metrics() -> tuple[int, int]:
    """Return current and peak resident memory in KiB on Linux."""

    current_kib = 0
    try:
        resident_pages = int(Path("/proc/self/statm").read_text().split()[1])
        current_kib = resident_pages * os.sysconf("SC_PAGE_SIZE") // 1024
    except (OSError, ValueError, IndexError):
        pass

    try:
        import resource

        peak_kib = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (ImportError, AttributeError, OSError):
        peak_kib = 0
    return current_kib, peak_kib


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
