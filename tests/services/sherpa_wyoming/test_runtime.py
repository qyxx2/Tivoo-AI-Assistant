from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import numpy as np
import pytest
from sherpa_wyoming.config import ServiceConfig
from sherpa_wyoming.execution import BoundedExecutor, ExecutionQueueFull
from sherpa_wyoming.models import ModelBundle, ModelLoadError
from sherpa_wyoming.providers.tts import TTSProvider
from sherpa_wyoming.run import build_wyoming_info, run_server


def test_info_advertises_exactly_one_installed_wake_asr_and_tts_provider() -> None:
    config = ServiceConfig(wake_word_phrase="你好 Tivoo")

    info = build_wyoming_info(config)

    assert len(info.wake) == len(info.asr) == len(info.tts) == 1
    wake = info.wake[0]
    assert wake.installed is True
    assert len(wake.models) == 1
    assert wake.models[0].name == "tivoo-wake"
    assert wake.models[0].installed is True
    assert wake.models[0].phrase == "你好 Tivoo"
    assert wake.models[0].version == "2025-12-20"
    assert wake.models[0].languages == ["zh-CN", "en-US"]

    asr = info.asr[0]
    assert asr.installed is True
    assert len(asr.models) == 1
    assert asr.models[0].languages == ["zh-CN", "en-US"]
    assert asr.requires_external_vad is True
    assert asr.supports_transcript_streaming is False

    tts = info.tts[0]
    assert tts.installed is True
    assert len(tts.voices) == 1
    assert tts.voices[0].installed is True
    assert tts.voices[0].name == "0"
    assert tts.voices[0].languages == ["zh-CN"]
    assert tts.supports_synthesize_streaming is True


def test_bounded_executor_rejects_work_beyond_one_running_and_one_pending() -> None:
    async def scenario() -> None:
        executor = BoundedExecutor(max_workers=1, max_pending=1)
        started = threading.Event()
        release = threading.Event()
        second_started = threading.Event()

        def first_job() -> None:
            started.set()
            assert release.wait(2)

        def second_job() -> None:
            second_started.set()

        first = asyncio.create_task(executor.run(first_job))
        assert await asyncio.to_thread(started.wait, 1)

        second = asyncio.create_task(executor.run(second_job))
        await asyncio.sleep(0.02)
        with pytest.raises(ExecutionQueueFull):
            await executor.run(lambda: None)

        release.set()
        await asyncio.gather(first, second)
        assert second_started.is_set()
        executor.shutdown()

    asyncio.run(scenario())


def test_cancelled_waiter_does_not_release_model_slot_while_worker_runs() -> None:
    async def scenario() -> None:
        executor = BoundedExecutor(max_workers=1, max_pending=1)
        started = threading.Event()
        release = threading.Event()

        def blocked_job() -> None:
            started.set()
            assert release.wait(2)

        first = asyncio.create_task(executor.run(blocked_job))
        assert await asyncio.to_thread(started.wait, 1)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

        second_started = threading.Event()
        second = asyncio.create_task(executor.run(lambda: second_started.set()))
        await asyncio.sleep(0.02)
        with pytest.raises(ExecutionQueueFull):
            await executor.run(lambda: None)

        release.set()
        await second
        assert second_started.is_set()
        executor.shutdown()

    asyncio.run(scenario())


def test_model_load_failure_does_not_construct_or_start_server() -> None:
    async def scenario() -> None:
        config = ServiceConfig(wake_word_phrase="你好 Tivoo")
        factory_calls: list[tuple[str, int]] = []

        def fail_model_load(_config: ServiceConfig) -> ModelBundle:
            raise ModelLoadError("TTS model unavailable")

        def server_factory(host: str, port: int):
            factory_calls.append((host, port))
            raise AssertionError("server must not be created before models load")

        with pytest.raises(ModelLoadError, match="TTS model unavailable"):
            await run_server(
                config,
                keyword_generator=lambda *_args: None,
                model_loader=fail_model_load,
                server_factory=server_factory,
            )

        assert factory_calls == []

    asyncio.run(scenario())


def test_startup_generates_keywords_and_loads_all_models_before_binding() -> None:
    async def scenario() -> None:
        calls: list[str] = []
        config = ServiceConfig(wake_word_phrase="配置唤醒词")

        class FakeServer:
            def __init__(self, host: str, port: int) -> None:
                assert (host, port) == ("0.0.0.0", 10400)
                calls.append("bind")

            async def run(self, handler_factory) -> None:
                assert handler_factory is not None
                calls.append("serve")

            async def stop(self) -> None:
                calls.append("stop")

        bundle = ModelBundle(
            keyword_spotter=object(),
            stt_recognizer=object(),
            tts_engine=object(),
        )

        def generate(models_dir, phrase: str) -> None:
            assert models_dir == config.models_dir
            assert phrase == "配置唤醒词"
            calls.append("keywords")

        def load(_config: ServiceConfig) -> ModelBundle:
            calls.append("models")
            return bundle

        def make_server(host: str, port: int) -> FakeServer:
            return FakeServer(host, port)

        await run_server(
            config,
            keyword_generator=generate,
            model_loader=load,
            server_factory=make_server,
        )

        assert calls == ["keywords", "models", "bind", "serve", "stop"]

    asyncio.run(scenario())


def test_cancelled_pending_work_is_removed_from_executor_queue() -> None:
    async def scenario() -> None:
        executor = BoundedExecutor(max_workers=1, max_pending=1)
        running = threading.Event()
        release = threading.Event()
        pending_ran = threading.Event()
        next_ran = threading.Event()

        def blocked_job() -> None:
            running.set()
            assert release.wait(2)

        first = asyncio.create_task(executor.run(blocked_job))
        assert await asyncio.to_thread(running.wait, 1)

        second = asyncio.create_task(executor.run(pending_ran.set))
        await asyncio.sleep(0.02)
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second

        release.set()
        await first
        await executor.run(next_ran.set)

        assert next_ran.is_set()
        assert not pending_ran.is_set()
        executor.shutdown()

    asyncio.run(scenario())


def test_streaming_tts_sessions_share_the_bounded_model_executor() -> None:
    async def scenario() -> None:
        config = ServiceConfig(wake_word_phrase="你好 Tivoo")
        executor = BoundedExecutor(max_workers=1, max_pending=1, name="tts-test")

        class BlockingTts:
            def __init__(self) -> None:
                self.started = threading.Event()
                self.release = threading.Event()

            def generate(self, _text, *, sid, speed, callback=None):
                samples = np.asarray([0.0, 0.25, -0.25, 0.5], dtype=np.float32)
                if callback is not None:
                    self.started.set()
                    assert self.release.wait(2)
                    callback(samples, 1.0)
                return SimpleNamespace(samples=samples, sample_rate=22_050)

        engine = BlockingTts()
        provider = TTSProvider(config, engine)

        async def input_events():
            from wyoming.tts import (
                Synthesize,
                SynthesizeChunk,
                SynthesizeStart,
                SynthesizeStop,
            )

            yield SynthesizeStart().event()
            yield SynthesizeChunk(text="排队测试。").event()
            yield Synthesize(text="排队测试。").event()
            yield SynthesizeStop().event()

        async def collect():
            session = provider.create_stream_session(execution=executor)
            return [event async for event in session.stream(input_events())]

        first = asyncio.create_task(collect())
        assert await asyncio.to_thread(engine.started.wait, 1)

        second = asyncio.create_task(collect())
        await asyncio.sleep(0.03)
        third = await asyncio.wait_for(collect(), timeout=1)

        from wyoming.error import Error

        assert any(
            isinstance(event, Error) and event.code == "server_busy" for event in third
        )

        engine.release.set()
        first_events, second_events = await asyncio.gather(first, second)
        assert first_events[-1].event().type == "synthesize-stopped"
        assert second_events[-1].event().type == "synthesize-stopped"
        executor.shutdown()

    asyncio.run(scenario())
