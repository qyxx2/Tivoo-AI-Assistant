"""Tests for the bounded P6 microphone session interface."""

import asyncio

import pytest
from custom_components.tivoo.audio_session import AudioSessionManager

SESSION_1 = "11111111-1111-4111-8111-111111111111"
SESSION_2 = "22222222-2222-4222-8222-222222222222"
INTERRUPT_ID = "33333333-3333-4333-8333-333333333333"
AUDIO_ID = "44444444-4444-4444-8444-444444444444"


def _start_payload(session_id=SESSION_1, **overrides):
    payload = {
        "session_id": session_id,
        "sample_rate": 16000,
        "channels": 1,
        "sample_format": "s16le",
        "frame_duration_ms": 20,
        "preroll_ms": 500,
        "trigger_source": "idle_vad",
    }
    payload.update(overrides)
    return payload


async def _collect(iterator):
    return [chunk async for chunk in iterator]


async def test_session_iterator_preserves_binary_pcm_order_and_finishes():
    manager = AudioSessionManager()
    await manager.async_start_session(_start_payload())
    iterator = manager.async_audio_iterator(SESSION_1)
    chunks = [bytes([value]) * 640 for value in (1, 2, 3)]

    for chunk in chunks:
        await manager.async_push_pcm(SESSION_1, chunk)
    await manager.async_end_session(SESSION_1, "completed")

    assert await _collect(iterator) == chunks


async def test_repeated_or_overlapping_start_does_not_replace_active_session():
    manager = AudioSessionManager()
    await manager.async_start_session(_start_payload())

    with pytest.raises(ValueError, match="already active"):
        await manager.async_start_session(_start_payload(SESSION_2))
    with pytest.raises(ValueError, match="already active"):
        await manager.async_start_session(_start_payload())

    assert manager.active_session_id == SESSION_1


async def test_late_old_session_messages_cannot_affect_new_session():
    stopped = []

    async def send_stop(session_id, reason):
        stopped.append((session_id, reason))

    manager = AudioSessionManager(send_stop)
    await manager.async_start_session(_start_payload())
    old_iterator = manager.async_audio_iterator(SESSION_1)
    await manager.async_end_session(SESSION_1, "completed")

    await manager.async_start_session(_start_payload(SESSION_2))
    new_iterator = manager.async_audio_iterator(SESSION_2)
    await manager.async_push_pcm(SESSION_1, b"old!")
    await manager.async_end_session(SESSION_1, "late_end")
    await manager.async_stop_session(SESSION_1, "late_stop")
    await manager.async_push_pcm(SESSION_2, b"new!")
    await manager.async_end_session(SESSION_2, "completed")

    assert await _collect(old_iterator) == []
    assert await _collect(new_iterator) == [b"new!"]
    assert manager.active_session_id is None
    assert stopped == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"sample_rate": 8000},
        {"sample_rate": 16000.0},
        {"channels": 2},
        {"channels": 1.0},
        {"sample_format": "s24le"},
        {"frame_duration_ms": 10},
        {"trigger_source": "button"},
        {"trigger_source": "barge_in"},
        {"preroll_ms": -1},
        {"session_id": "not-a-uuid"},
    ],
)
async def test_invalid_session_schema_is_rejected(overrides):
    manager = AudioSessionManager()
    with pytest.raises((TypeError, ValueError)):
        await manager.async_start_session(_start_payload(**overrides))
    assert manager.active_session_id is None


async def test_valid_barge_in_requires_and_accepts_interrupt_id():
    manager = AudioSessionManager()
    await manager.async_start_session(
        _start_payload(
            trigger_source="barge_in",
            interrupt_id=INTERRUPT_ID,
        )
    )
    assert manager.active_session_id == SESSION_1


async def test_pcm_payload_is_binary_and_limited_to_four_kibibytes():
    manager = AudioSessionManager()
    await manager.async_start_session(_start_payload())
    iterator = manager.async_audio_iterator(SESSION_1)

    with pytest.raises(TypeError, match="bytes"):
        await manager.async_push_pcm(SESSION_1, bytearray(b"not bytes"))
    with pytest.raises(ValueError, match="S16LE"):
        await manager.async_push_pcm(SESSION_1, b"x")
    with pytest.raises(ValueError, match="4 KiB"):
        await manager.async_push_pcm(SESSION_1, b"x" * 4098)

    frame = bytes(range(256)) * 2 + bytes(range(128))  # 640 bytes / 20 ms
    await manager.async_push_pcm(SESSION_1, frame)
    await manager.async_end_session(SESSION_1, "completed")

    assert await _collect(iterator) == [frame]


async def test_queue_saturation_stops_session_and_notifies_esp32():
    stop_requests = []

    async def send_stop(session_id, reason):
        stop_requests.append((session_id, reason))

    manager = AudioSessionManager(send_stop)
    await manager.async_start_session(_start_payload())
    iterator = manager.async_audio_iterator(SESSION_1)

    for value in range(16):
        await manager.async_push_pcm(SESSION_1, bytes([value]) * 4096)

    assert manager.queue_size == 16
    await manager.async_push_pcm(SESSION_1, b"overflow")

    assert manager.active_session_id is None
    assert manager.queue_size == 0
    assert stop_requests == [(SESSION_1, "queue_full")]
    assert await _collect(iterator) == []


async def test_matching_stop_clears_queue_and_sends_capture_stop():
    stop_requests = []

    async def send_stop(session_id, reason):
        stop_requests.append((session_id, reason))

    manager = AudioSessionManager(send_stop)
    await manager.async_start_session(_start_payload())
    iterator = manager.async_audio_iterator(SESSION_1)
    await manager.async_push_pcm(SESSION_1, b"pending!")

    await manager.async_stop_session(SESSION_1, "pipeline_finished")

    assert manager.active_session_id is None
    assert manager.queue_size == 0
    assert stop_requests == [(SESSION_1, "pipeline_finished")]
    assert await _collect(iterator) == []


async def test_shutdown_closes_active_iterators_and_clears_queue():
    stop_requests = []

    async def send_stop(session_id, reason):
        stop_requests.append((session_id, reason))

    manager = AudioSessionManager(send_stop)
    await manager.async_start_session(_start_payload())
    iterator = manager.async_audio_iterator(SESSION_1)
    await manager.async_push_pcm(SESSION_1, b"pending!")

    await manager.async_shutdown()

    assert manager.active_session_id is None
    assert manager.queue_size == 0
    assert stop_requests == [(SESSION_1, "ha_unload")]
    assert await _collect(iterator) == []


async def test_audio_interrupted_is_validated_and_dispatched_to_registered_handler():
    handled = []

    async def on_interrupted(payload):
        handled.append(payload)

    manager = AudioSessionManager()
    manager.register_audio_interrupted_handler(on_interrupted)
    payload = {
        "interrupt_id": INTERRUPT_ID,
        "audio_id": AUDIO_ID,
        "source": "tts_http",
        "reason": "near_end_vad",
    }

    await manager.async_handle_audio_interrupted(payload)
    assert handled == [payload]

    with pytest.raises((TypeError, ValueError), match="interrupt_id"):
        await manager.async_handle_audio_interrupted(
            {"audio_id": AUDIO_ID, "source": "tts_http", "reason": "near_end_vad"}
        )
    assert handled == [payload]


async def test_async_iterator_waits_for_pcm_and_ends_when_session_ends():
    manager = AudioSessionManager()
    await manager.async_start_session(_start_payload())
    iterator = manager.async_audio_iterator(SESSION_1)

    async def produce():
        await asyncio.sleep(0)
        await manager.async_push_pcm(SESSION_1, b"first!")
        await asyncio.sleep(0)
        await manager.async_end_session(SESSION_1, "completed")

    producer = asyncio.create_task(produce())
    assert await _collect(iterator) == [b"first!"]
    await producer


async def test_new_session_waits_for_ended_session_pcm_to_drain():
    manager = AudioSessionManager()
    await manager.async_start_session(_start_payload())
    old_iterator = manager.async_audio_iterator(SESSION_1)
    await manager.async_push_pcm(SESSION_1, b"pending-old-frame!")
    await manager.async_end_session(SESSION_1, "completed")

    with pytest.raises(ValueError, match="still draining"):
        await manager.async_start_session(_start_payload(SESSION_2))

    assert await _collect(old_iterator) == [b"pending-old-frame!"]
    await manager.async_start_session(_start_payload(SESSION_2))
    assert manager.active_session_id == SESSION_2
