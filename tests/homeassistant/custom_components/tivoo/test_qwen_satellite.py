"""Qwen local turns retain the existing ingress and cleanup owner boundaries."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from custom_components.tivoo.assist_satellite import TivooAssistSatellite
from custom_components.tivoo.audio_session import AudioSessionManager
from custom_components.tivoo.diagnostics import TYPE_STT_READY
from custom_components.tivoo.display_state import ExpressionCoordinator
from custom_components.tivoo.qwen_realtime import QwenResult
from test_audio_session import SESSION_1, SESSION_2
from test_display_state import RecordingAdapter
from test_p68_local_session import activity, gate, local_start


class Bridge:
    def __init__(self):
        self.started = asyncio.Event()
        self.finish = asyncio.Event()
        self.closed = asyncio.Event()
        self.owner = SimpleNamespace(
            playback_id="qwen-playback",
            send_failed=False,
            stop_dispatch=Mock(),
            async_stop_playback=AsyncMock(),
            async_close=AsyncMock(side_effect=self.closed.set),
        )
        self.frames = []
        self.error = None
        self.on_event = None
        self.current = None
        self.playback = []

    def create_turn(self, session_id, generation, *, current, prompt_player=None, parent_session_id=None):
        self.session_id, self.generation = session_id, generation
        self.current = current
        return self.owner

    async def async_run(self, owner, audio, on_event, *, on_result=None):
        assert owner is self.owner
        self.on_event = on_event
        self.started.set()
        async for chunk in audio:
            self.frames.append(chunk)
        on_event({"type": "transcript.final", "role": "user", "content": "开灯"})
        await self.finish.wait()
        if self.error:
            raise self.error
        result = QwenResult("好了。", "t1", "r1")
        if on_result:
            on_result(result)
        return result

    async def async_release_parent(self, session_id):
        pass

    def on_playback(self, playback_id, state):
        self.playback.append((playback_id, state))
        if playback_id == self.owner.playback_id and state == "completed":
            self.finish.set()


@pytest.fixture
async def qwen_satellite(hass):
    stop = AsyncMock()
    manager = AudioSessionManager(stop)
    bridge = Bridge()
    adapter = SimpleNamespace(
        async_send_tts_play=AsyncMock(),
        async_send_message=AsyncMock(),
        register_playback_handler=Mock(),
    )
    display = ExpressionCoordinator(RecordingAdapter())
    await display.async_start()
    entity = TivooAssistSatellite(
        "entry", manager, adapter, display, qwen_bridge=bridge
    )
    entity.hass = hass
    entity.async_write_ha_state = Mock()
    entity.async_accept_pipeline_from_satellite = AsyncMock(
        side_effect=AssertionError("legacy pipeline")
    )
    entity.validate_local_pipeline = Mock(side_effect=AssertionError("legacy STT"))
    entity.tts_response_finished = Mock()
    await entity.async_added_to_hass()
    yield entity, manager, stop, bridge
    await entity.async_will_remove_from_hass()
    await display.async_shutdown()


async def feed_turn(entity, manager, bridge):
    await manager.async_start_session(local_start(), persistent=True, local_mode=True)
    await asyncio.wait_for(bridge.started.wait(), 1)
    await manager.async_handle_gate(gate())
    await manager.async_handle_activity(activity("speech_start"))
    await manager.async_push_pcm(SESSION_1, b"a" * 640)
    await manager.async_handle_activity(activity("speech_end", pcm_samples=320))
    await asyncio.sleep(0)


async def test_qwen_local_pcm_eof_waits_for_physical_completion(
    qwen_satellite, hass, monkeypatch
):
    entity, manager, stop, bridge = qwen_satellite
    monkeypatch.setattr(
        "custom_components.tivoo.assist_satellite.PipelineTtsEvents",
        Mock(side_effect=AssertionError("legacy TTS owner")),
    )
    await feed_turn(entity, manager, bridge)
    turn = entity.coordinator._turn
    assert bridge.frames == [b"a" * 640]
    assert manager.local_input_drained(SESSION_1)
    assert turn.valid_stt and turn.stt_started
    assert bridge.session_id == SESSION_1 and bridge.generation == turn.context.id
    assert bridge.current()
    entity.adapter.async_send_message.assert_awaited_once()
    assert entity.adapter.async_send_message.call_args.args[0] == TYPE_STT_READY
    stop.assert_not_awaited()
    entity.coordinator.on_playback("wrong-playback", "completed")
    await asyncio.sleep(0)
    assert not turn.playback_completed
    stop.assert_not_awaited()
    entity.coordinator.on_playback("qwen-playback", "completed")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert turn.run_end and turn.intent_finished and turn.run_returned
    assert turn.response_finished
    # An ordinary final answer closes without follow-up.
    assert not turn.continue_conversation
    stop.assert_awaited_once_with(SESSION_1, "conversation_complete")
    assert bridge.closed.is_set()
    entity.validate_local_pipeline.assert_not_called()
    entity.async_accept_pipeline_from_satellite.assert_not_awaited()
    entity.adapter.async_send_tts_play.assert_not_awaited()


async def test_qwen_failure_retires_current_owner(qwen_satellite, hass):
    entity, manager, stop, bridge = qwen_satellite
    await feed_turn(entity, manager, bridge)
    bridge.error = RuntimeError("Gateway failed")
    bridge.finish.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    stop.assert_awaited_once_with(SESSION_1, "pipeline_failed")
    assert bridge.closed.is_set()
    bridge.owner.stop_dispatch.assert_called_once()
    bridge.owner.async_stop_playback.assert_awaited_once()
    assert manager.active_session_id is None


async def test_user_transcript_cancels_stt_deadline_while_playback_pending(
    qwen_satellite, hass
):
    from datetime import timedelta

    from homeassistant.util import dt
    from pytest_homeassistant.common import async_fire_time_changed

    entity, manager, stop, bridge = qwen_satellite
    await feed_turn(entity, manager, bridge)
    turn = entity.coordinator._turn
    assert turn.valid_stt and not turn.run_returned
    assert "stt_finalize_timeout" not in entity.coordinator._timers
    async_fire_time_changed(hass, dt.utcnow() + timedelta(seconds=46))
    await hass.async_block_till_done()
    stop.assert_not_awaited()
    assert manager.active_session_id == SESSION_1 and not turn.task.done()


async def test_qwen_shutdown_fences_late_transcript_and_joins_owner(qwen_satellite):
    entity, manager, _stop, bridge = qwen_satellite
    await manager.async_start_session(local_start(), persistent=True, local_mode=True)
    await asyncio.wait_for(bridge.started.wait(), 1)
    turn = entity.coordinator._turn
    await entity.coordinator.async_shutdown()
    bridge.on_event({"type": "transcript.final", "role": "user", "content": "late"})
    assert not bridge.current()
    assert not turn.valid_stt
    assert bridge.closed.is_set()
    assert turn.task.done()
    bridge.owner.async_stop_playback.assert_awaited_once()


async def test_qwen_new_wake_waits_for_old_owner_and_rejects_late_events(
    qwen_satellite,
):
    entity, manager, _stop, bridge = qwen_satellite
    await manager.async_start_session(local_start(), persistent=True, local_mode=True)
    await asyncio.wait_for(bridge.started.wait(), 1)
    old_turn = entity.coordinator._turn
    old_current, late_event = bridge.current, bridge.on_event
    closing, release = asyncio.Event(), asyncio.Event()

    async def close_old():
        closing.set()
        await release.wait()

    bridge.owner.async_close.side_effect = close_old
    bridge.started.clear()
    try:
        await manager.async_start_session(
            local_start(SESSION_2, 101), persistent=True, local_mode=True
        )
        await asyncio.wait_for(closing.wait(), 1)
        current = entity.coordinator._turn
        assert current is not old_turn
        assert not old_current()
        assert not bridge.started.is_set()
        late_event({"type": "transcript.final", "role": "user", "content": "stale"})
        assert not old_turn.valid_stt and not current.valid_stt
        release.set()
        await asyncio.wait_for(bridge.started.wait(), 1)
        assert manager.active_session_id == SESSION_2
    finally:
        release.set()


async def test_entry_reload_reuses_global_pcm_view_and_closes_bridge(
    hass, enable_custom_integrations, monkeypatch
):
    from custom_components.tivoo.const import DOMAIN
    from pytest_homeassistant.common import MockConfigEntry

    entry = MockConfigEntry(domain=DOMAIN, title="Tivoo", data={}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    runtime = hass.data[DOMAIN][entry.entry_id]
    bridge = runtime["qwen_bridge"]
    streams = hass.data["tivoo_qwen_streams"]
    close = AsyncMock(wraps=bridge.async_close)
    monkeypatch.setattr(bridge, "async_close", close)
    register_view = Mock(wraps=hass.http.register_view)
    monkeypatch.setattr(hass.http, "register_view", register_view)
    assert await hass.config_entries.async_unload(entry.entry_id)
    close.assert_awaited_once()
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert hass.data["tivoo_qwen_streams"] is streams
    assert hass.data[DOMAIN][entry.entry_id]["qwen_bridge"] is not bridge
    assert list(hass.data[DOMAIN]) == [entry.entry_id]
    register_view.assert_not_called()
    assert await hass.config_entries.async_unload(entry.entry_id)
