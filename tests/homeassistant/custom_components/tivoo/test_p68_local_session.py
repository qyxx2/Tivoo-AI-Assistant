"""T05-C: local ingress has an explicit gate, ready and graceful input EOF."""
import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from custom_components.tivoo.audio_session import AudioSessionManager
from custom_components.tivoo import diagnostics as codec
from test_audio_session import SESSION_1, SESSION_2, _start_payload


def local_start(session_id=SESSION_1, uptime_ms=100):
    return _start_payload(session_id, trigger_source="local_wake", preroll_ms=0,
                          wake_word_phrase="嗨，乐鑫", uptime_ms=uptime_ms)


def gate(session_id=SESSION_1, prompt_result="skipped"):
    return dict(session_id=session_id, uptime_ms=1000, prompt_result=prompt_result)


def activity(state, session_id=SESSION_1, **kw):
    return dict(session_id=session_id, state=state, uptime_ms=1100, **kw)


@pytest.mark.parametrize("gate_first", [True, False])
@pytest.mark.parametrize("prompt_result", ["completed", "skipped", "failed"])
async def test_local_ready_and_gate_then_ordered_tail_eof(gate_first, prompt_result):
    stop, ready, started, gated, ended = AsyncMock(), AsyncMock(), Mock(), Mock(), Mock()
    manager = AudioSessionManager(stop)
    manager.on_local_start, manager.on_gate, manager.on_end = started, gated, ended
    await manager.async_start_session(local_start(), persistent=True, local_mode=True)
    started.assert_called_once_with(SESSION_1, "嗨，乐鑫")
    await manager.async_start_session(local_start(), persistent=True, local_mode=True)
    started.assert_called_once()
    if gate_first:
        await manager.async_handle_gate(gate(prompt_result=prompt_result))
    async with manager.audio_subscription(SESSION_1, start=0, on_pull=ready) as audio:
        first = asyncio.create_task(anext(audio))
        await asyncio.sleep(0)
        ready.assert_awaited_once()
        if not gate_first:
            await manager.async_handle_gate(gate(prompt_result=prompt_result))
        await manager.async_handle_gate(gate(prompt_result=prompt_result))
        gated.assert_called_once_with(SESSION_1)
        await manager.async_handle_activity(activity("speech_start"))
        frames = [bytes([i])*640 for i in range(3)]
        for frame in frames:
            await manager.async_push_pcm(SESSION_1, frame)
        await manager.async_handle_activity(activity("speech_end", pcm_samples=960))
        assert await first == frames[0]
        assert manager.local_input_finished(SESSION_1)
        assert not manager.local_input_drained(SESSION_1)
        assert [part async for part in audio] == frames[1:]
        assert manager.local_input_drained(SESSION_1)
        assert manager.active_session_id == SESSION_1
        ended.assert_not_called()
        stop.assert_not_awaited()


@pytest.mark.parametrize("fault", ["early_pcm", "pcm_size", "count", "early_end", "disconnect", "late_start"])
async def test_local_fault_never_returns_normal_eof(fault):
    stop = AsyncMock()
    manager = AudioSessionManager(stop)
    await manager.async_start_session(local_start(), persistent=True, local_mode=True)
    async with manager.audio_subscription(SESSION_1, start=0, on_pull=AsyncMock()) as audio:
        pending = asyncio.create_task(anext(audio))
        await asyncio.sleep(0)
        if fault != "early_pcm":
            await manager.async_handle_gate(gate())
            if fault != "early_end":
                payload = activity("speech_start")
                if fault == "late_start":
                    payload["uptime_ms"] = 4100
                await manager.async_handle_activity(payload)
        if fault == "early_pcm":
            await manager.async_push_pcm(SESSION_1, bytes(640))
        elif fault == "pcm_size":
            await manager.async_push_pcm(SESSION_1, bytes(638))
        elif fault in {"early_end", "count"}:
            await manager.async_handle_activity(activity("speech_end", pcm_samples=320))
        elif fault == "disconnect":
            await manager.async_disconnect()
        with pytest.raises(RuntimeError, match="aborted"):
            await asyncio.wait_for(pending, 1)
        assert manager.active_session_id is None


async def test_local_new_uuid_cancels_old_and_duplicate_cannot_reopen():
    manager = AudioSessionManager()
    await manager.async_start_session(local_start(), persistent=True, local_mode=True)
    async with manager.audio_subscription(SESSION_1, start=0, on_pull=AsyncMock()) as audio:
        pending = asyncio.create_task(anext(audio))
        await asyncio.sleep(0)
        await manager.async_start_session(local_start(SESSION_2, 101), persistent=True, local_mode=True)
        await manager.async_start_session(local_start(), persistent=True, local_mode=True)
        with pytest.raises(RuntimeError, match="aborted"):
            await pending
        assert manager.active_session_id == SESSION_2
        await manager.async_handle_gate(gate(SESSION_1))
        assert manager.active_session_id == SESSION_2


def test_local_wire_direction():
    assert codec.TYPE_STT_READY == 0x25
    assert codec.TYPE_COMMAND_GATE == 0x26
    assert 0x25 in codec.HA_TO_ESP32_MESSAGE_TYPES
    assert 0x26 in codec.ESP32_TO_HA_MESSAGE_TYPES
    assert 0x25 not in codec.ESP32_TO_HA_MESSAGE_TYPES
    assert 0x26 not in codec.HA_TO_ESP32_MESSAGE_TYPES


async def test_stale_activity_ignored_before_payload_validation():
    manager = AudioSessionManager(AsyncMock())
    manager.on_activity = Mock()
    await manager.async_start_session(local_start(), persistent=True, local_mode=True)
    await manager.async_start_session(local_start(SESSION_2, 101), persistent=True, local_mode=True)
    await manager.async_handle_activity(dict(session_id=SESSION_1, state='bad', uptime_ms=-1))
    await manager.async_handle_gate(dict(session_id=SESSION_1, uptime_ms=-1))
    await manager.async_start_session(local_start(SESSION_1, 102), persistent=True, local_mode=True)
    await manager.async_handle_gate(gate(SESSION_2))
    async with manager.audio_subscription(SESSION_2, start=0, on_pull=AsyncMock()) as audio:
        pending = asyncio.create_task(anext(audio))
        await asyncio.sleep(0)
        await manager.async_handle_activity(activity('speech_start', SESSION_2))
        await manager.async_push_pcm(SESSION_2, bytes(640))
        assert await pending == bytes(640)
    manager.on_activity.assert_called_once_with(SESSION_2, 'speech_start')


@pytest.mark.parametrize('field,value', [('uptime_ms', 1001), ('prompt_result', 'completed')])
async def test_conflicting_current_gate_stops_only_current(field, value):
    stop, gated = AsyncMock(), Mock()
    manager = AudioSessionManager(stop)
    manager.on_gate = gated
    await manager.async_start_session(local_start(), persistent=True, local_mode=True)
    await manager.async_handle_gate(gate())
    await manager.async_handle_gate(gate())
    gated.assert_called_once_with(SESSION_1)
    stop.assert_not_awaited()
    await manager.async_handle_gate(dict(gate(), **{field: value}))
    assert manager.active_session_id is None
    stop.assert_awaited_once_with(SESSION_1, 'invalid_command_gate')


@pytest.mark.parametrize('phase', ['speech_start', 'speech_end'])
async def test_conflicting_current_activity_rejected(phase):
    stop, observed = AsyncMock(), Mock()
    manager = AudioSessionManager(stop)
    manager.on_activity = observed
    await manager.async_start_session(local_start(), persistent=True, local_mode=True)
    await manager.async_handle_gate(gate())
    async with manager.audio_subscription(SESSION_1, start=0, on_pull=AsyncMock()) as audio:
        pending = asyncio.create_task(anext(audio))
        await asyncio.sleep(0)
        await manager.async_handle_activity(activity('speech_start'))
        await manager.async_push_pcm(SESSION_1, bytes(640))
        await pending
        if phase == 'speech_end':
            await manager.async_handle_activity(activity('speech_end', pcm_samples=320))
        payload = activity(phase, **({'pcm_samples': 320} if phase == 'speech_end' else {}))
        await manager.async_handle_activity(payload)
        assert observed.call_count == (2 if phase == 'speech_end' else 1)
        await manager.async_handle_activity(dict(payload, uptime_ms=1101))
        assert manager.active_session_id is None
        stop.assert_awaited_once()


@pytest.mark.parametrize('patch', [dict(state='invalid'), dict(uptime_ms=-1), dict(uptime_ms=True)])
async def test_current_invalid_activity_is_not_ignored(patch):
    stop = AsyncMock()
    manager = AudioSessionManager(stop)
    await manager.async_start_session(local_start(), persistent=True, local_mode=True)
    await manager.async_handle_activity(dict(activity('speech_start'), **patch))
    assert manager.active_session_id is None
    stop.assert_awaited_once_with(SESSION_1, 'invalid_local_activity')
    await manager.async_start_session(local_start(SESSION_2, 101), persistent=True, local_mode=True)
    await manager.async_handle_activity(dict(activity('speech_start'), **patch))
    assert manager.active_session_id == SESSION_2


async def test_local_mode_accepts_batched_wire_pcm_without_changing_payload():
    manager = AudioSessionManager(AsyncMock())
    await manager.async_start_session(local_start(), persistent=True, local_mode=True)
    await manager.async_handle_gate(gate())
    async with manager.audio_subscription(SESSION_1, start=0, on_pull=AsyncMock()) as audio:
        first = asyncio.create_task(anext(audio))
        await asyncio.sleep(0)
        await manager.async_handle_activity(activity("speech_start"))
        frames = [bytes([i]) * 640 for i in range(6)]
        await manager.async_push_pcm(SESSION_1, b"".join(frames))
        assert await first == b"".join(frames)
        assert manager.active_session_id == SESSION_1
        await manager.async_handle_activity(activity("speech_end", pcm_samples=1920))
        assert [part async for part in audio] == []
