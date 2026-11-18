from __future__ import annotations

import asyncio
import logging
import socket
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
from sherpa_wyoming.config import ServiceConfig
from sherpa_wyoming.models import ModelBundle
from sherpa_wyoming.run import WyomingEventHandler, run_server
from wyoming.asr import Transcribe
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import async_read_event, async_write_event
from wyoming.info import Describe
from wyoming.server import AsyncTcpServer
from wyoming.tts import Synthesize, SynthesizeChunk, SynthesizeStart, SynthesizeStop
from wyoming.wake import Detect


class FakeKwsStream:
    def __init__(self) -> None:
        self.ready = False

    def accept_waveform(self, _rate: int, _samples: np.ndarray) -> None:
        self.ready = True


class FakeKeywordSpotter:
    def __init__(self) -> None:
        self.streams: list[FakeKwsStream] = []

    def create_stream(self) -> FakeKwsStream:
        stream = FakeKwsStream()
        self.streams.append(stream)
        return stream

    def is_ready(self, stream: FakeKwsStream) -> bool:
        return stream.ready

    def decode_stream(self, stream: FakeKwsStream) -> None:
        stream.ready = False

    def get_result(self, _stream: FakeKwsStream) -> str:
        return "matched"


class FakeSttStream:
    def __init__(self) -> None:
        self.result = SimpleNamespace(text="识别结果")
        self.audio: list[tuple[int, np.ndarray]] = []

    def accept_waveform(self, rate: int, samples: np.ndarray) -> None:
        self.audio.append((rate, samples.copy()))


class FakeRecognizer:
    def create_stream(self) -> FakeSttStream:
        return FakeSttStream()

    def decode_stream(self, _stream: FakeSttStream) -> None:
        return None


class FakeTts:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.calls: list[str] = []

    def generate(self, text: str, *, sid: int, speed: float, callback=None):
        self.calls.append(text)
        samples = np.asarray([0.0, 0.25, -0.25, 0.5], dtype=np.float32)
        if callback is not None:
            self.started.set()
            if self.block:
                self.release.wait(2)
            callback(samples, 1.0)
        return SimpleNamespace(samples=samples, sample_rate=22_050)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _wait_for_server(port: int) -> None:
    for _ in range(100):
        try:
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.01)
    raise AssertionError("Wyoming server did not bind its configured port")


async def _send(writer, event) -> None:
    await async_write_event(event.event(), writer)


async def _receive(reader, expected_type: str):
    event = await asyncio.wait_for(async_read_event(reader), timeout=2)
    assert event is not None
    assert event.type == expected_type, event.data
    return event


async def _connect(port: int):
    return await asyncio.open_connection("127.0.0.1", port)


async def _stop_server(task: asyncio.Task[None]) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_one_tcp_server_routes_describe_wake_stt_and_both_tts_modes(caplog) -> None:
    caplog.set_level(logging.INFO, logger="tivoo.sherpa_wyoming")

    async def scenario() -> None:
        port = _free_port()
        engine = FakeTts()
        spotter = FakeKeywordSpotter()
        bundle = ModelBundle(
            keyword_spotter=spotter,
            stt_recognizer=FakeRecognizer(),
            tts_engine=engine,
        )
        servers = []

        def server_factory(host: str, configured_port: int):
            from wyoming.server import AsyncTcpServer

            server = AsyncTcpServer(host, configured_port)
            servers.append(server)
            return server

        config = ServiceConfig(
            wake_word_phrase="你好 Tivoo",
            host="127.0.0.1",
            port=port,
        )
        server_task = asyncio.create_task(
            run_server(
                config,
                keyword_generator=lambda *_args: None,
                model_loader=lambda _config: bundle,
                server_factory=server_factory,
            )
        )
        await _wait_for_server(port)
        try:
            reader, writer = await _connect(port)
            await _send(writer, Describe())
            info = await _receive(reader, "info")
            assert (
                len(info.data["asr"])
                == len(info.data["tts"])
                == len(info.data["wake"])
                == 1
            )
            writer.close()
            await writer.wait_closed()

            # Keep two Wake connections open simultaneously and interleave
            # their audio to prove their Sherpa streams remain request-local.
            first_wake_reader, first_wake_writer = await _connect(port)
            await _send(first_wake_writer, Detect(names=["tivoo-wake"]))
            await _send(first_wake_writer, AudioStart(rate=16_000, width=2, channels=1))

            second_wake_reader, second_wake_writer = await _connect(port)
            await _send(second_wake_writer, Detect(names=["tivoo-wake"]))
            await _send(
                second_wake_writer, AudioStart(rate=16_000, width=2, channels=1)
            )

            for _ in range(100):
                if len(spotter.streams) == 2:
                    break
                await asyncio.sleep(0.01)
            assert len(spotter.streams) == 2
            assert spotter.streams[0] is not spotter.streams[1]

            await _send(
                second_wake_writer,
                AudioChunk(
                    rate=16_000,
                    width=2,
                    channels=1,
                    audio=np.asarray([3, 4], dtype="<i2").tobytes(),
                    timestamp=29,
                ),
            )
            second_detection = await _receive(second_wake_reader, "detection")
            assert second_detection.data["timestamp"] == 29

            await _send(
                first_wake_writer,
                AudioChunk(
                    rate=16_000,
                    width=2,
                    channels=1,
                    audio=np.asarray([1, 2], dtype="<i2").tobytes(),
                    timestamp=17,
                ),
            )
            first_detection = await _receive(first_wake_reader, "detection")
            assert first_detection.data["name"] == "tivoo-wake"
            assert first_detection.data["timestamp"] == 17

            for wake_writer in (first_wake_writer, second_wake_writer):
                wake_writer.close()
                await wake_writer.wait_closed()

            reader, writer = await _connect(port)
            await _send(writer, Detect(names=["tivoo-wake"]))
            await _send(writer, AudioStart(rate=16_000, width=2, channels=1))
            writer.write_eof()
            not_detected = await _receive(reader, "not-detected")
            assert not_detected.data == {}
            writer.close()
            await writer.wait_closed()

            reader, writer = await _connect(port)
            await _send(writer, Transcribe(language="zh-CN"))
            await _send(writer, AudioStart(rate=16_000, width=2, channels=1))
            await _send(
                writer,
                AudioChunk(
                    rate=16_000,
                    width=2,
                    channels=1,
                    audio=np.asarray([0, 1], dtype="<i2").tobytes(),
                ),
            )
            await _send(writer, AudioStop())
            transcript = await _receive(reader, "transcript")
            assert transcript.data["text"] == "识别结果"
            writer.close()
            await writer.wait_closed()

            reader, writer = await _connect(port)
            await _send(writer, Synthesize(text="非流式"))
            assert (await _receive(reader, "audio-start")).data["rate"] == 22_050
            await _receive(reader, "audio-chunk")
            await _receive(reader, "audio-stop")
            writer.close()
            await writer.wait_closed()

            reader, writer = await _connect(port)
            await _send(writer, SynthesizeStart())
            await _send(writer, SynthesizeChunk(text="流式回答。"))
            await _send(writer, Synthesize(text="流式回答。"))
            await _send(writer, SynthesizeStop())
            assert (await _receive(reader, "audio-start")).data["rate"] == 22_050
            await _receive(reader, "audio-chunk")
            await _receive(reader, "synthesize-stopped")
            writer.close()
            await writer.wait_closed()

            assert len(servers) == 1
            assert engine.calls == ["非流式", "流式回答。"]
            assert "识别结果" not in caplog.text
            assert "流式回答" not in caplog.text
            assert "非流式" not in caplog.text
            assert "provider=stt" in caplog.text
            assert "provider=tts_stream" in caplog.text
            assert "rss_kib=" in caplog.text
            assert "decode_seconds=" in caplog.text
            assert "first_pcm_seconds=" in caplog.text
            assert "queue_peak_bytes=" in caplog.text
        finally:
            await _stop_server(server_task)

    asyncio.run(scenario())


def test_describe_remains_responsive_while_tts_inference_is_blocked() -> None:
    async def scenario() -> None:
        port = _free_port()
        engine = FakeTts()
        engine.block = True
        bundle = ModelBundle(
            keyword_spotter=FakeKeywordSpotter(),
            stt_recognizer=FakeRecognizer(),
            tts_engine=engine,
        )
        config = ServiceConfig(
            wake_word_phrase="你好 Tivoo",
            host="127.0.0.1",
            port=port,
        )
        server_task = asyncio.create_task(
            run_server(
                config,
                keyword_generator=lambda *_args: None,
                model_loader=lambda _config: bundle,
            )
        )
        await _wait_for_server(port)
        try:
            tts_reader, tts_writer = await _connect(port)
            await _send(tts_writer, SynthesizeStart())
            await _send(tts_writer, SynthesizeChunk(text="阻塞推理。"))
            await _send(tts_writer, Synthesize(text="阻塞推理。"))
            await _send(tts_writer, SynthesizeStop())
            assert await asyncio.to_thread(engine.started.wait, 1)

            describe_reader, describe_writer = await _connect(port)
            started = time.monotonic()
            await _send(
                describe_writer,
                __import__("wyoming.info", fromlist=["Describe"]).Describe(),
            )
            info = await _receive(describe_reader, "info")
            assert time.monotonic() - started < 0.5
            assert info.data["wake"]

            engine.release.set()
            await _receive(tts_reader, "audio-start")
            await _receive(tts_reader, "audio-chunk")
            await _receive(tts_reader, "synthesize-stopped")
            tts_writer.close()
            describe_writer.close()
            await tts_writer.wait_closed()
            await describe_writer.wait_closed()
        finally:
            engine.release.set()
            await _stop_server(server_task)

    asyncio.run(scenario())


def test_slow_streaming_tts_backpressure_does_not_disconnect_client() -> None:
    """Normal model backpressure must not be treated as a TCP disconnect."""

    async def scenario() -> None:
        class SlowFirstTts(FakeTts):
            def generate(self, text, *, sid, speed, callback=None):
                self.calls.append(text)
                samples = np.zeros(256, dtype=np.float32)
                if not self.started.is_set():
                    self.started.set()
                    self.release.wait(2)
                callback(samples, 1.0)
                return SimpleNamespace(samples=samples, sample_rate=22_050)

        engine = SlowFirstTts()
        port = _free_port()
        config = ServiceConfig(wake_word_phrase="tivoo", host="127.0.0.1", port=port)
        bundle = ModelBundle(
            keyword_spotter=FakeKeywordSpotter(),
            stt_recognizer=FakeRecognizer(),
            tts_engine=engine,
        )
        task = asyncio.create_task(
            run_server(
                config,
                keyword_generator=lambda *_: None,
                model_loader=lambda _: bundle,
            )
        )
        await _wait_for_server(port)
        try:
            reader, writer = await _connect(port)
            sentence = "这是正常的句子。"
            chunks = [sentence] * 10
            await _send(writer, SynthesizeStart())
            for chunk in chunks:
                await _send(writer, SynthesizeChunk(text=chunk))
            await _send(writer, Synthesize(text="".join(chunks)))
            await _send(writer, SynthesizeStop())

            await _receive(reader, "audio-start")
            assert await asyncio.to_thread(engine.started.wait, 1)
            await asyncio.sleep(1.2)
            engine.release.set()

            for _ in chunks:
                await _receive(reader, "audio-chunk")
            await _receive(reader, "synthesize-stopped")
            assert engine.calls == chunks

            writer.close()
            await writer.wait_closed()
        finally:
            engine.release.set()
            await _stop_server(task)

    asyncio.run(scenario())


@pytest.mark.parametrize("input_complete", [True, False])
def test_tcp_eof_cancels_active_tts_with_finished_or_backlogged_input(
    input_complete,
) -> None:
    """A finished text upload still has a cancellable audio response."""

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        rejected = asyncio.Event()
        handlers = []

        class CallbackEngine(FakeTts):
            def generate(self, text, *, sid, speed, callback=None):
                self.started.set()
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not self.release.wait(0.01):
                    if callback(np.zeros(256, dtype=np.float32), 0.5) == 0:
                        loop.call_soon_threadsafe(rejected.set)
                        break
                return SimpleNamespace(samples=np.zeros(256), sample_rate=22_050)

        class TrackingServer(AsyncTcpServer):
            async def _handler_callback(self, factory, reader, writer):
                def track(reader, writer):
                    handler = factory(reader, writer)
                    assert isinstance(handler, WyomingEventHandler)
                    handlers.append(handler)
                    return handler

                await super()._handler_callback(track, reader, writer)

        engine = CallbackEngine()
        port = _free_port()
        config = ServiceConfig(wake_word_phrase="tivoo", host="127.0.0.1", port=port)
        bundle = ModelBundle(
            keyword_spotter=FakeKeywordSpotter(),
            stt_recognizer=FakeRecognizer(),
            tts_engine=engine,
        )
        task = asyncio.create_task(
            run_server(
                config,
                keyword_generator=lambda *_: None,
                model_loader=lambda _: bundle,
                server_factory=TrackingServer,
            )
        )
        await _wait_for_server(port)
        try:
            reader, writer = await _connect(port)
            await _send(writer, SynthesizeStart())
            await _send(writer, SynthesizeChunk(text="停止合成。"))
            if input_complete:
                await _send(writer, Synthesize(text="停止合成。"))
                await _send(writer, SynthesizeStop())
            await _receive(reader, "audio-start")
            assert await asyncio.to_thread(engine.started.wait, 1)
            handler = handlers[-1]
            session = handler._tts_session
            request = handler._tts_task

            async def wait_until(predicate):
                async with asyncio.timeout(1):
                    while not predicate():
                        await asyncio.sleep(0.01)

            if input_complete:
                await wait_until(lambda: session._input_stopped)
            else:
                for _ in range(10):
                    await _send(writer, SynthesizeChunk(text="积压。"))
            writer.write_eof()
            await asyncio.wait_for(rejected.wait(), 1.8)
            await wait_until(request.done)
            await wait_until(
                lambda: handler._tts_session is None and handler.writer.is_closing()
            )
            assert request.cancelled()
            assert session._input_task.done()
            assert session._worker_task.done()
            while event := await asyncio.wait_for(async_read_event(reader), 1):
                assert event.type != "synthesize-stopped"
            writer.close()
            await writer.wait_closed()
        finally:
            engine.release.set()
            await _stop_server(task)

    asyncio.run(scenario())


def test_device_endpoint_shares_models_and_rejects_other_providers():
    async def scenario():
        legacy, device = _free_port(), _free_port()
        assert legacy != device
        calls, handlers = [], []
        bundle = ModelBundle(FakeKeywordSpotter(), FakeRecognizer(), FakeTts())

        class RecordingServer(AsyncTcpServer):
            def record(self, factory):
                def create(*args):
                    handler = factory(*args)
                    handlers.append(handler)
                    return handler
                return create

            async def start(self, factory):
                await super().start(self.record(factory))

            async def run(self, factory):
                await super().run(self.record(factory))

        def load(config):
            calls.append(config)
            return bundle

        config = ServiceConfig(wake_word_phrase="test", host="127.0.0.1",
                               port=legacy, device_stt_port=device)
        task = asyncio.create_task(run_server(
            config, keyword_generator=lambda *_: None, model_loader=load,
            server_factory=RecordingServer,
        ))
        try:
            await _wait_for_server(legacy)
            await _wait_for_server(device)
            readers_writers = [await _connect(p) for p in (legacy, device)]
            for reader, writer in readers_writers:
                await _send(writer, Describe())
            old, new = [await _receive(reader, "info") for reader, _ in readers_writers]
            assert old.data["asr"][0]["requires_external_vad"] is True
            assert len(old.data["tts"]) == len(old.data["wake"]) == 1
            assert new.data["asr"][0]["requires_external_vad"] is False
            assert new.data["asr"][0]["name"] != old.data["asr"][0]["name"]
            assert not new.data.get("tts") and not new.data.get("wake")
            assert len(calls) == 1
            assert handlers[-1].executors is handlers[-2].executors
            assert handlers[-1].stt_provider is handlers[-2].stt_provider
            reader, writer = readers_writers[1]
            for event in (Detect(names=["tivoo-wake"]), Synthesize(text="test"), SynthesizeStart()):
                await _send(writer, event)
                await _receive(reader, "error")
            for reader, writer in readers_writers:
                await _send(writer, Transcribe(language="zh-CN"))
                await _send(writer, AudioStart(rate=16000, width=2, channels=1))
                await _send(writer, AudioChunk(rate=16000, width=2, channels=1, audio=b"\\0" * 640))
                await _send(writer, AudioStop())
                await _receive(reader, "transcript")
                writer.close()
                await writer.wait_closed()
        finally:
            if task.done():
                task.result()
            else:
                await _stop_server(task)
        for p in (legacy, device):
            try:
                _, writer = await _connect(p)
            except OSError:
                continue
            writer.close()
            await writer.wait_closed()
            raise AssertionError("listener not closed")
    asyncio.run(scenario())
