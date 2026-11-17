"""Tests for run-scoped Tivoo TTS lifecycle cleanup."""

import asyncio
from types import SimpleNamespace

import pytest
from custom_components.tivoo import tts_lifecycle
from custom_components.tivoo.tts_lifecycle import PipelineTtsOwner, _OwnedCache
from homeassistant.exceptions import HomeAssistantError


async def test_cancel_timeout_joins_producer_before_returning_error(monkeypatch):
    """A timeout may report failure only after the producer has exited."""
    started = asyncio.Event()
    cleanup_started = asyncio.Event()
    cleanup_done = asyncio.Event()

    async def blocked_producer():
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cleanup_started.set()
            await asyncio.sleep(0.05)
            cleanup_done.set()
            raise

    producer = asyncio.create_task(blocked_producer())
    await started.wait()

    result_cache = asyncio.get_running_loop().create_future()
    stream = SimpleNamespace(
        _result_cache=result_cache,
        delete=lambda: None,
    )
    owner = object.__new__(PipelineTtsOwner)
    owner.stream = stream
    owner.cache = None
    owner.producer = producer
    owner._close_task = None
    owner._closed = False
    owner._client = object()
    owner._writer = object()

    async def finish_wyoming(_client):
        return None

    owner._finish_wyoming = finish_wyoming
    monkeypatch.setattr(tts_lifecycle, "_CONVERSION_CLOSE_TIMEOUT", 0.01)

    try:
        with pytest.raises(HomeAssistantError, match="HA TTS producer did not exit"):
            await owner.async_cancel()

        assert cleanup_started.is_set()
        assert cleanup_done.is_set()
        assert producer.done()
        assert producer.cancelled()

        # Reusing the failed close task must not expose a producer still cleaning up.
        with pytest.raises(HomeAssistantError, match="HA TTS producer did not exit"):
            await owner.async_cancel()
        assert producer.done()
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)


async def test_proxy_consumer_waits_for_cache_producer_start():
    """A Proxy GET racing the producer must not observe a false empty stream."""

    async def source():
        await asyncio.sleep(0)
        yield b"first"
        yield b"second"

    stream = SimpleNamespace(token="race-token", extension="mp3")
    cache = _OwnedCache(stream, source())

    async def consume() -> bytes:
        return b"".join([chunk async for chunk in cache.async_stream_data()])

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0)
    assert not consumer.done()

    producer = asyncio.create_task(cache.async_load_data())
    try:
        assert await consumer == b"firstsecond"
        assert await producer == b"firstsecond"
    finally:
        consumer.cancel()
        producer.cancel()
        await asyncio.gather(consumer, producer, return_exceptions=True)
