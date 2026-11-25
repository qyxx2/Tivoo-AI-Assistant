"""B8.8 local turns: Sherpa STT precedes any Qwen fallback."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from custom_components.tivoo.assist_satellite import TivooAssistSatellite
from custom_components.tivoo.audio_session import AudioSessionManager
from custom_components.tivoo.diagnostics import TYPE_STT_READY
from custom_components.tivoo.display_state import ExpressionCoordinator
from homeassistant.components.assist_pipeline.models import (
    PipelineEvent,
    PipelineEventType as Event,
    PipelineStage,
)
from test_audio_session import SESSION_1, SESSION_2
from test_display_state import RecordingAdapter
from test_p68_local_session import activity, gate, local_start


class Bridge:
    """Record Qwen admission without making Qwen part of STT tests."""

    def __init__(self):
        self.pipeline_started = asyncio.Event()
        self.frames = []
        self.pipeline_calls = []
        self.create_calls = []
        self.audio_calls = 0
        self.text_calls = []
        self.released = []
        self.playback = []
        self.stt_text = "打开客厅灯"
        self.provider_error = False
        self.inject_vad = False
        self.input_drained_at_stt_end = False

    def create_turn(
        self,
        session_id,
        generation,
        *,
        current,
        prompt_player=None,
        parent_session_id=None,
    ):
        self.create_calls.append((session_id, generation, parent_session_id))
        return SimpleNamespace(
            session_id=session_id,
            generation=generation,
            parent_session_id=parent_session_id,
            playback_id=None,
            send_failed=False,
            keep_socket=False,
            tools={},
            stop_dispatch=Mock(),
            async_stop_playback=AsyncMock(),
            async_close=AsyncMock(),
            on_connection_lost=None,
        )

    async def async_run(self, owner, audio, on_event, *, on_result=None):
        self.audio_calls += 1
        raise AssertionError("B8.8 local STT must not send PCM to Qwen")

    async def async_run_text(self, owner, text, on_event, *, on_result=None):
        self.text_calls.append(text)
        raise AssertionError("Task 3 must not submit Qwen text yet")

    async def async_release_parent(self, session_id):
        self.released.append(session_id)

    def on_playback(self, playback_id, state):
        self.playback.append((playback_id, state))


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
    entity.tts_response_finished = Mock()
    entity.validate_local_pipeline = Mock(
        return_value=("select.tivoo_pipeline", "pipeline-local")
    )

    async def pipeline(audio, stage, **kwargs):
        bridge.pipeline_calls.append((stage, kwargs))
        assert stage is PipelineStage.STT
        assert kwargs["end_stage"] is PipelineStage.STT
        entity.on_pipeline_event(
            PipelineEvent(Event.RUN_START, {"pipeline": "pipeline-local"})
        )
        entity.on_pipeline_event(PipelineEvent(Event.STT_START))
        bridge.pipeline_started.set()
        if bridge.inject_vad:
            entity.on_pipeline_event(PipelineEvent(Event.STT_VAD_START))
        async for chunk in audio:
            bridge.frames.append(chunk)
        bridge.input_drained_at_stt_end = manager.local_input_drained(
            manager.active_session_id
        )
        if bridge.provider_error:
            entity.on_pipeline_event(
                PipelineEvent(
                    Event.ERROR,
                    {"code": "stt-provider", "message": "fixture provider error"},
                )
            )
            return
        entity.on_pipeline_event(
            PipelineEvent(Event.STT_END, {"stt_output": {"text": bridge.stt_text}})
        )
        entity.on_pipeline_event(PipelineEvent(Event.RUN_END))

    entity.async_accept_pipeline_from_satellite = AsyncMock(side_effect=pipeline)
    await entity.async_added_to_hass()
    yield entity, manager, stop, bridge
    await entity.async_will_remove_from_hass()
    await display.async_shutdown()


async def begin_turn(entity, manager, bridge, session_id=SESSION_1, sequence=100):
    bridge.pipeline_started.clear()
    await manager.async_start_session(
        local_start(session_id, sequence), persistent=True, local_mode=True
    )
    turn = entity.coordinator._turn
    assert turn is not None
    await asyncio.wait_for(bridge.pipeline_started.wait(), 1)
    await manager.async_handle_gate(gate(session_id))
    await manager.async_handle_activity(activity("speech_start", session_id))
    return turn


async def finish_turn(manager, turn, *, pcm=b"a" * 640):
    await manager.async_push_pcm(turn.session_id, pcm)
    await manager.async_handle_activity(
        activity("speech_end", turn.session_id, pcm_samples=len(pcm) // 2)
    )
    await asyncio.wait_for(turn.task, 2)


async def test_b88_qwen_present_still_runs_sherpa_before_fallback(qwen_satellite):
    entity, manager, stop, bridge = qwen_satellite
    turn = await begin_turn(entity, manager, bridge)
    await finish_turn(manager, turn)

    assert turn.transcript == "打开客厅灯"
    assert turn.valid_stt and turn.stt_started
    assert bridge.frames == [b"a" * 640]
    assert bridge.input_drained_at_stt_end
    assert len(bridge.pipeline_calls) == 1
    _, kwargs = bridge.pipeline_calls[0]
    assert kwargs["context"] is turn.context
    assert kwargs["wake_word_phrase"] == "嗨，乐鑫"
    entity.validate_local_pipeline.assert_called_once()
    assert not bridge.create_calls
    assert bridge.audio_calls == 0
    assert not bridge.text_calls
    entity.adapter.async_send_message.assert_awaited_once()
    assert entity.adapter.async_send_message.call_args.args[0] == TYPE_STT_READY
    entity.adapter.async_send_tts_play.assert_not_awaited()
    stop.assert_awaited_once_with(SESSION_1, "conversation_complete")


@pytest.mark.parametrize("text", ["", "   "])
async def test_b88_empty_sherpa_transcript_never_reaches_qwen(
    qwen_satellite, text
):
    entity, manager, _stop, bridge = qwen_satellite
    bridge.stt_text = text
    turn = await begin_turn(entity, manager, bridge)
    await finish_turn(manager, turn)

    assert turn.transcript is None
    assert not turn.valid_stt
    assert not bridge.create_calls
    assert not bridge.text_calls


async def test_b88_provider_error_never_reaches_qwen(qwen_satellite):
    entity, manager, stop, bridge = qwen_satellite
    bridge.provider_error = True
    turn = await begin_turn(entity, manager, bridge)
    await finish_turn(manager, turn)

    assert turn.transcript is None
    assert turn.error
    assert not bridge.create_calls
    assert not bridge.text_calls
    stop.assert_awaited_once_with(SESSION_1, "pipeline_failed")


async def test_b88_unexpected_ha_vad_never_reaches_qwen(qwen_satellite):
    entity, manager, stop, bridge = qwen_satellite
    bridge.inject_vad = True
    await manager.async_start_session(
        local_start(), persistent=True, local_mode=True
    )
    turn = entity.coordinator._turn
    assert turn is not None
    await asyncio.wait_for(bridge.pipeline_started.wait(), 1)
    await asyncio.gather(turn.task, return_exceptions=True)

    assert turn.transcript is None
    assert turn.error
    assert not bridge.create_calls
    assert not bridge.text_calls
    stop.assert_awaited_once_with(SESSION_1, "pipeline_failed")


async def test_b88_disconnect_before_normal_eof_has_no_transcript_or_qwen(
    qwen_satellite,
):
    entity, manager, _stop, bridge = qwen_satellite
    turn = await begin_turn(entity, manager, bridge)
    await manager.async_push_pcm(SESSION_1, b"x" * 640)
    await manager.async_disconnect()
    await asyncio.gather(turn.task, return_exceptions=True)

    assert turn.transcript is None
    assert not turn.valid_stt
    assert not bridge.create_calls
    assert not bridge.text_calls


async def test_b88_superseded_stt_cannot_publish_old_transcript(qwen_satellite):
    entity, manager, _stop, bridge = qwen_satellite
    old = await begin_turn(entity, manager, bridge)
    await manager.async_push_pcm(SESSION_1, b"x" * 640)

    bridge.pipeline_started.clear()
    await manager.async_start_session(
        local_start(SESSION_2, 101), persistent=True, local_mode=True
    )
    new = entity.coordinator._turn
    assert new is not old
    await asyncio.wait_for(bridge.pipeline_started.wait(), 1)
    await asyncio.gather(old.task, return_exceptions=True)

    assert old.transcript is None
    assert not old.valid_stt
    assert not bridge.create_calls
    assert not bridge.text_calls


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
