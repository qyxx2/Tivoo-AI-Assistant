"""B8.8 local turns: Sherpa STT precedes any Qwen fallback."""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import custom_components.tivoo.assist_satellite as assist_satellite_module
from custom_components.tivoo.assist_satellite import (
    AudioSessionCoordinator,
    LocalRouteResult,
    TivooAssistSatellite,
)
from custom_components.tivoo.audio_session import AudioSessionManager
from custom_components.tivoo.diagnostics import TYPE_STT_READY
from custom_components.tivoo.display_state import ExpressionCoordinator
from homeassistant.components import conversation
from homeassistant.components.assist_pipeline.models import (
    PipelineEvent,
    PipelineEventType as Event,
    PipelineStage,
)
from homeassistant.core import Context
from homeassistant.helpers import chat_session, intent
from homeassistant.setup import async_setup_component
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
    entity.coordinator._async_route_local_transcript = AsyncMock(
        return_value=LocalRouteResult(False, "", False)
    )
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



def _route_turn(text):
    return SimpleNamespace(
        transcript=text,
        context=Context(),
        local_pipeline_id="pipeline-local",
    )


def _install_route_context(monkeypatch):
    pipeline = SimpleNamespace(
        id="pipeline-local",
        language="zh-CN",
        conversation_language="zh-CN",
        conversation_engine="conversation.qwen",
        prefer_local_intents=True,
    )
    monkeypatch.setattr(
        "custom_components.tivoo.assist_satellite.async_get_pipeline",
        lambda _hass, _pipeline_id: pipeline,
    )

    @contextmanager
    def session_cm(*_args, **_kwargs):
        yield SimpleNamespace(conversation_id="local-route")

    @contextmanager
    def log_cm(*_args, **_kwargs):
        yield SimpleNamespace()

    monkeypatch.setattr(chat_session, "async_get_chat_session", session_cm)
    monkeypatch.setattr(conversation, "async_get_chat_log", log_cm)
    prepare = AsyncMock()
    sentence = AsyncMock(return_value=None)
    local = AsyncMock(return_value=None)
    monkeypatch.setattr(conversation, "async_prepare_intents", prepare)
    monkeypatch.setattr(conversation, "async_handle_sentence_triggers", sentence)
    monkeypatch.setattr(conversation, "async_handle_intents", local)
    return pipeline, prepare, sentence, local


async def test_b88_sentence_trigger_hit_precedes_local_intent(
    qwen_satellite, monkeypatch
):
    entity, _manager, _stop, bridge = qwen_satellite
    _pipeline, prepare, sentence, local = _install_route_context(monkeypatch)
    sentence.return_value = "已执行场景"

    result = await AudioSessionCoordinator._async_route_local_transcript(
        entity.coordinator,
        _route_turn("晚安")
    )

    assert result.handled is True
    assert result.speech == "已执行场景"
    assert result.continue_conversation is False
    prepare.assert_awaited_once_with(entity.hass, "zh-CN")
    sentence.assert_awaited_once()
    local.assert_not_awaited()
    assert not bridge.create_calls and not bridge.text_calls


async def test_b88_local_intent_hit_after_sentence_miss(qwen_satellite, monkeypatch):
    entity, _manager, _stop, bridge = qwen_satellite
    _pipeline, _prepare, sentence, local = _install_route_context(monkeypatch)
    response = intent.IntentResponse("zh-CN")
    response.async_set_speech("客厅灯已打开")
    local.return_value = response

    result = await AudioSessionCoordinator._async_route_local_transcript(
        entity.coordinator,
        _route_turn("打开客厅灯")
    )

    assert result.handled is True
    assert result.speech == "客厅灯已打开"
    assert result.continue_conversation is False
    sentence.assert_awaited_once()
    local.assert_awaited_once()
    assert not bridge.create_calls and not bridge.text_calls


async def test_b88_local_miss_returns_unhandled(qwen_satellite, monkeypatch):
    entity, _manager, _stop, bridge = qwen_satellite
    _pipeline, _prepare, sentence, local = _install_route_context(monkeypatch)

    result = await AudioSessionCoordinator._async_route_local_transcript(
        entity.coordinator,
        _route_turn("讲一个火星故事")
    )

    assert result.handled is False
    assert result.speech == ""
    assert result.continue_conversation is False
    sentence.assert_awaited_once()
    local.assert_awaited_once()
    assert not bridge.create_calls and not bridge.text_calls


async def test_b88_local_intent_failure_is_still_handled(qwen_satellite, monkeypatch):
    entity, _manager, _stop, bridge = qwen_satellite
    _pipeline, _prepare, _sentence, local = _install_route_context(monkeypatch)
    response = intent.IntentResponse("zh-CN")
    response.response_type = intent.IntentResponseType.ERROR
    response.async_set_speech("找不到可控制的设备")
    local.return_value = response

    result = await AudioSessionCoordinator._async_route_local_transcript(
        entity.coordinator,
        _route_turn("打开不存在的灯")
    )

    assert result.handled is True
    assert result.speech == "找不到可控制的设备"
    assert result.continue_conversation is False
    local.assert_awaited_once()
    assert not bridge.create_calls and not bridge.text_calls


@pytest.mark.parametrize("text", [None, "", "   "])
async def test_b88_local_router_ignores_empty_transcript(
    qwen_satellite, monkeypatch, text
):
    entity, _manager, _stop, bridge = qwen_satellite
    _pipeline, prepare, sentence, local = _install_route_context(monkeypatch)

    result = await AudioSessionCoordinator._async_route_local_transcript(
        entity.coordinator,
        _route_turn(text)
    )

    assert result.handled is False
    assert result.speech == ""
    assert result.continue_conversation is False
    prepare.assert_not_awaited()
    sentence.assert_not_awaited()
    local.assert_not_awaited()
    assert not bridge.create_calls and not bridge.text_calls



async def test_b88_local_intent_hit_stays_ha_owned(qwen_satellite):
    entity, manager, stop, bridge = qwen_satellite
    route = entity.coordinator._async_route_local_transcript
    route.return_value = LocalRouteResult(True, "客厅灯已打开", False)
    local_tts = AsyncMock()
    entity.coordinator._async_run_local_tts = local_tts

    turn = await begin_turn(entity, manager, bridge)
    await finish_turn(manager, turn)

    route.assert_awaited_once_with(turn)
    local_tts.assert_awaited_once_with(turn, "客厅灯已打开")
    assert turn.tts.__class__.__name__ == "PipelineTtsEvents"
    assert not bridge.create_calls and not bridge.text_calls
    assert bridge.audio_calls == 0
    stop.assert_awaited_once_with(SESSION_1, "conversation_complete")


async def test_b88_local_hit_without_speech_completes_without_playback(qwen_satellite):
    entity, manager, stop, bridge = qwen_satellite
    route = entity.coordinator._async_route_local_transcript
    route.return_value = LocalRouteResult(True, "", False)
    local_tts = AsyncMock()
    entity.coordinator._async_run_local_tts = local_tts

    turn = await begin_turn(entity, manager, bridge)
    await finish_turn(manager, turn)

    route.assert_awaited_once_with(turn)
    local_tts.assert_not_awaited()
    entity.adapter.async_send_tts_play.assert_not_awaited()
    assert not bridge.create_calls and not bridge.text_calls
    stop.assert_awaited_once_with(SESSION_1, "conversation_complete")


async def test_b88_local_miss_has_no_ha_tts_or_qwen_in_task4(qwen_satellite):
    entity, manager, stop, bridge = qwen_satellite
    route = entity.coordinator._async_route_local_transcript
    route.return_value = LocalRouteResult(False, "", False)
    local_tts = AsyncMock()
    entity.coordinator._async_run_local_tts = local_tts

    turn = await begin_turn(entity, manager, bridge)
    await finish_turn(manager, turn)

    route.assert_awaited_once_with(turn)
    local_tts.assert_not_awaited()
    assert not bridge.create_calls and not bridge.text_calls
    assert bridge.audio_calls == 0
    stop.assert_awaited_once_with(SESSION_1, "conversation_complete")


async def test_b88_local_tts_uses_dedicated_pipeline_tts_only(
    qwen_satellite, monkeypatch
):
    entity, _manager, _stop, _bridge = qwen_satellite
    pipeline = SimpleNamespace(id="pipeline-local")
    monkeypatch.setattr(
        assist_satellite_module,
        "async_get_pipeline",
        lambda _hass, _pipeline_id: pipeline,
    )

    captured = {}

    class FakeRun:
        def __init__(self, **kwargs):
            captured["run"] = kwargs

    class FakeInput:
        def __init__(self, **kwargs):
            captured["input"] = kwargs

        async def execute(self):
            captured["executed"] = True

    monkeypatch.setattr(
        assist_satellite_module, "PipelineRun", FakeRun, raising=False
    )
    monkeypatch.setattr(
        assist_satellite_module, "PipelineInput", FakeInput, raising=False
    )

    @contextmanager
    def session_cm(*_args, **_kwargs):
        yield SimpleNamespace(conversation_id="tts-only")

    monkeypatch.setattr(chat_session, "async_get_chat_session", session_cm)

    async def run_owner(coroutine):
        await coroutine

    owner = SimpleNamespace(async_run=AsyncMock(side_effect=run_owner))
    turn = SimpleNamespace(
        local_pipeline_id="pipeline-local",
        context=Context(),
        tts=owner,
    )

    await entity.coordinator._async_run_local_tts(turn, "本地回答")

    run = captured["run"]
    assert run["pipeline"] is pipeline
    assert run["start_stage"] is PipelineStage.TTS
    assert run["end_stage"] is PipelineStage.TTS
    assert run["event_callback"] == entity._internal_on_pipeline_event
    assert run["tts_audio_output"] == entity.tts_options
    pipeline_input = captured["input"]
    assert pipeline_input["run"].__class__ is FakeRun
    assert pipeline_input["tts_input"] == "本地回答"
    assert pipeline_input["satellite_id"] == entity.entity_id
    assert captured["executed"] is True
    owner.async_run.assert_awaited_once()



async def test_b88_real_ha_local_intent_matches_before_fallback(
    qwen_satellite, monkeypatch
):
    entity, _manager, _stop, bridge = qwen_satellite
    assert await async_setup_component(entity.hass, "conversation", {})
    pipeline = SimpleNamespace(
        id="pipeline-local",
        language="en",
        conversation_language="en",
        conversation_engine=conversation.HOME_ASSISTANT_AGENT,
        prefer_local_intents=True,
    )
    monkeypatch.setattr(
        assist_satellite_module,
        "async_get_pipeline",
        lambda _hass, _pipeline_id: pipeline,
    )

    result = await AudioSessionCoordinator._async_route_local_transcript(
        entity.coordinator,
        _route_turn("what time is it"),
    )

    assert result.handled is True
    assert result.speech
    assert result.continue_conversation is False
    assert not bridge.create_calls and not bridge.text_calls
