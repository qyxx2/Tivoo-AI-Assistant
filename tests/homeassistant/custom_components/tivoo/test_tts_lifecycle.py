"""Tests for run-scoped Tivoo TTS lifecycle cleanup."""

import asyncio
from types import SimpleNamespace

import pytest
from custom_components.tivoo import tts_lifecycle
from custom_components.tivoo.tts_lifecycle import PipelineTtsOwner
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
