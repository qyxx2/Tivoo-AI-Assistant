"""T07: local follow-up handoff and monotonic session identity."""
from unittest.mock import AsyncMock, Mock
import pytest
from custom_components.tivoo.audio_session import AudioSessionManager
from custom_components.tivoo import diagnostics as codec
from test_p68_local_session import local_start, gate, activity
from test_audio_session import SESSION_1, SESSION_2

def followup(parent=SESSION_1):
    payload = local_start(SESSION_2)
    payload.update(trigger_source="local_followup", parent_session_id=parent, uptime_ms=200)
    payload.pop("wake_word_phrase")
    return payload

async def test_grant_consumed_once_and_four_second_gate():
    manager = AudioSessionManager(AsyncMock())
    manager.on_local_start = Mock()
    await manager.async_start_session(local_start(), persistent=True, local_mode=True)
    assert not manager.grant_followup(SESSION_1)
    await manager.async_handle_gate(gate())
    async with manager.audio_subscription(SESSION_1, start=0, on_pull=AsyncMock()) as audio:
        first = asyncio.create_task(anext(audio))
        await asyncio.sleep(0)
        await manager.async_handle_activity(activity("speech_start"))
        await manager.async_push_pcm(SESSION_1, b"x"*640)
        await manager.async_handle_activity(activity("speech_end", pcm_samples=320))
        assert await first == b"x"*640
    assert manager.grant_followup(SESSION_1)
    assert not manager.grant_followup(SESSION_1)
    await manager.async_start_session(followup(), persistent=True, local_mode=True)
    manager.on_local_start.assert_called_with(SESSION_2, None)
    await manager.async_start_session(followup(), persistent=True, local_mode=True)
    assert manager.on_local_start.call_count == 2
    await manager.async_handle_gate(gate(SESSION_2))
    async with manager.audio_subscription(SESSION_2, start=0, on_pull=AsyncMock()) as audio:
        first = asyncio.create_task(anext(audio))
        await asyncio.sleep(0)
        await manager.async_handle_activity(dict(activity("speech_start", SESSION_2), uptime_ms=5000))
        await manager.async_push_pcm(SESSION_2, b"x"*640)
        assert await first == b"x"*640
    assert manager.active_session_id == SESSION_2

async def test_stale_start_and_ungranted_followup_inert():
    stop = AsyncMock()
    manager = AudioSessionManager(stop)
    await manager.async_start_session(local_start(), persistent=True, local_mode=True)
    await manager.async_start_session(followup(), persistent=True, local_mode=True)
    assert manager.active_session_id == SESSION_1
    stop.assert_awaited_once_with(SESSION_2, "invalid_followup")
    await manager.async_start_session(local_start(SESSION_2), persistent=True, local_mode=True)
    assert manager.active_session_id == SESSION_1

def test_followup_direction():
    assert codec.TYPE_FOLLOWUP_OPEN == 0x27
    assert 0x27 in codec.HA_TO_ESP32_MESSAGE_TYPES
    assert 0x27 not in codec.ESP32_TO_HA_MESSAGE_TYPES

from test_assist_satellite import advance_clock, satellite
from homeassistant.components.assist_pipeline.models import PipelineEvent, PipelineEventType as Event
from uuid import uuid4
import asyncio

async def test_repeated_wake_serializes_public_caller(hass, satellite, monkeypatch):
    entity, manager, stop = satellite
    await manager.async_end_session(SESSION_1, "test")
    monkeypatch.setattr(entity,"validate_local_pipeline",lambda: ("select.test","local"))
    entered = asyncio.Queue()
    release = asyncio.Event()
    active = set()
    async def run(audio, stage, *, context, wake_word_phrase):
        assert not active
        active.add(context.id)
        entered.put_nowait(context.id)
        try:
            await asyncio.Future()
        finally:
            await release.wait()
            active.remove(context.id)
    monkeypatch.setattr(entity,"async_accept_pipeline_from_satellite",run)
    await manager.async_start_session(local_start(),persistent=True,local_mode=True)
    await asyncio.wait_for(entered.get(),1)
    await manager.async_start_session(local_start(SESSION_2,101),persistent=True,local_mode=True)
    third = str(uuid4())
    await manager.async_start_session(local_start(third,102),persistent=True,local_mode=True)
    await asyncio.sleep(0)
    assert manager.active_session_id == third and entered.empty()
    release.set()
    await asyncio.wait_for(entered.get(),1)
    assert entity.coordinator._turn.session_id == third
    assert len(active)==1

@pytest.mark.parametrize("intent, response, tts_attempt, authorized", [
    (True, "action_done", False, True),
    (True, "error", False, False),
    (False, "action_done", False, False),
    ("true", "action_done", False, False),
    (None, "action_done", False, False),
    (True, "action_done", True, False),
])
async def test_followup_requires_normal_run_return(hass, satellite, monkeypatch, intent, response, tts_attempt, authorized):
    entity, manager, stop = satellite
    await manager.async_end_session(SESSION_1,"test")
    monkeypatch.setattr(entity,"validate_local_pipeline",lambda: ("select.test","local"))
    ready = asyncio.Event()
    reply = asyncio.Event()
    release = asyncio.Event()
    entity.adapter.async_send_message.side_effect = lambda *a: ready.set()
    async def run(audio, stage, *, context, wake_word_phrase):
        entity.on_pipeline_event(PipelineEvent(Event.STT_START))
        async for _ in audio:
            pass
        entity.on_pipeline_event(PipelineEvent(Event.STT_END, {"stt_output":{"text":"command"}}))
        output = {"response": {"response_type": response}}
        if intent is not None:
            output["continue_conversation"] = intent
        entity.on_pipeline_event(PipelineEvent(Event.INTENT_END, {"intent_output": output}))
        if tts_attempt:
            entity.on_pipeline_event(PipelineEvent(Event.TTS_START))
        entity.on_pipeline_event(PipelineEvent(Event.RUN_END))
        reply.set()
        await release.wait()
    monkeypatch.setattr(entity,"async_accept_pipeline_from_satellite",run)
    await manager.async_start_session(local_start(),persistent=True,local_mode=True)
    await manager.async_handle_gate(gate())
    await asyncio.wait_for(ready.wait(),1)
    await manager.async_handle_activity(activity("speech_start"))
    await manager.async_push_pcm(SESSION_1,b"x"*640)
    await manager.async_handle_activity(activity("speech_end",pcm_samples=320))
    await asyncio.wait_for(reply.wait(),1)
    assert all(call.args[0]!=0x27 for call in entity.adapter.async_send_message.await_args_list)
    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    grants=[call for call in entity.adapter.async_send_message.await_args_list if call.args[0]==0x27]
    assert len(grants)==int(authorized)
    if authorized:
        stop.assert_not_awaited()
    else:
        stop.assert_awaited_once_with(SESSION_1,"tts_missing" if tts_attempt else "conversation_complete")

@pytest.mark.parametrize("completed_first", [True, False])
async def test_local_grant_waits_for_both_playback_and_run(hass, satellite, monkeypatch, completed_first):
    entity, manager, stop = satellite
    await manager.async_end_session(SESSION_1,"test")
    hass.config.internal_url = "http://ha-internal.local:8123"
    monkeypatch.setattr(entity,"validate_local_pipeline",lambda: ("select.test","local"))
    ready, sent, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    entity.adapter.async_send_message.side_effect = lambda *a: ready.set()
    entity.adapter.async_send_tts_play.side_effect = lambda *a, **kw: sent.set()

    async def run(audio, stage, *, context, wake_word_phrase):
        entity.on_pipeline_event(PipelineEvent(Event.STT_START))
        async for _ in audio:
            pass
        entity.on_pipeline_event(PipelineEvent(Event.STT_END, {"stt_output":{"text":"command"}}))
        entity.on_pipeline_event(PipelineEvent(Event.INTENT_END, {"intent_output":{"continue_conversation":True,"response":{"response_type":"query_answer"}}}))
        entity.on_pipeline_event(PipelineEvent(Event.TTS_START))
        entity.on_pipeline_event(PipelineEvent(Event.TTS_END, {"tts_output":{"url":"/api/tts_proxy/test.mp3","mime_type":"audio/mpeg"}}))
        entity.on_pipeline_event(PipelineEvent(Event.RUN_END))
        await release.wait()

    def grants():
        return [call for call in entity.adapter.async_send_message.await_args_list if call.args[0]==0x27]

    monkeypatch.setattr(entity,"async_accept_pipeline_from_satellite",run)
    await manager.async_start_session(local_start(),persistent=True,local_mode=True)
    await manager.async_handle_gate(gate())
    await asyncio.wait_for(ready.wait(),1)
    await manager.async_handle_activity(activity("speech_start"))
    await manager.async_push_pcm(SESSION_1,b"x"*640)
    await manager.async_handle_activity(activity("speech_end",pcm_samples=320))
    await asyncio.wait_for(sent.wait(),1)
    playback = entity.adapter.async_send_tts_play.await_args.args[0]
    if completed_first:
        entity.coordinator.on_playback(playback,"completed")
        await hass.async_block_till_done()
        assert not grants()
        release.set()
    else:
        release.set()
        await hass.async_block_till_done(wait_background_tasks=True)
        assert not grants()
        entity.coordinator.on_playback(playback,"completed")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(grants()) == 1
    entity.coordinator.on_playback(playback,"completed")
    await hass.async_block_till_done()
    assert len(grants()) == 1
    stop.assert_not_awaited()

async def test_failed_cleanup_rejects_replacement(hass, satellite, monkeypatch):
    entity, manager, stop = satellite
    await manager.async_end_session(SESSION_1,"test")
    monkeypatch.setattr(entity,"validate_local_pipeline",lambda: ("select.test","local"))
    entered = asyncio.Queue()
    async def run(audio, stage, *, context, wake_word_phrase):
        entered.put_nowait(context.id)
        await asyncio.Future()
    monkeypatch.setattr(entity,"async_accept_pipeline_from_satellite",run)
    await manager.async_start_session(local_start(),persistent=True,local_mode=True)
    await asyncio.wait_for(entered.get(),1)
    old = entity.coordinator._turn
    old.tts.async_close = AsyncMock(side_effect=RuntimeError("peer EOF unconfirmed"))
    await manager.async_start_session(local_start(SESSION_2,101),persistent=True,local_mode=True)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entered.empty()
    stop.assert_awaited_once_with(SESSION_2,"pipeline_failed")
    assert manager.active_session_id is None

@pytest.mark.parametrize("grant_send_failed",[False,True])
async def test_followup_grant_timeout_and_late_start(hass, satellite, monkeypatch, advance_clock, grant_send_failed):
    entity, manager, stop = satellite
    await manager.async_end_session(SESSION_1,"test")
    monkeypatch.setattr(entity,"validate_local_pipeline",lambda: ("select.test","local"))
    ready = asyncio.Event()
    async def send(kind, payload):
        if kind == 0x25:
            ready.set()
        elif grant_send_failed:
            raise RuntimeError("grant transport failed")
    entity.adapter.async_send_message.side_effect = send
    async def run(audio, stage, *, context, wake_word_phrase):
        entity.on_pipeline_event(PipelineEvent(Event.STT_START))
        async for _ in audio:
            pass
        entity.on_pipeline_event(PipelineEvent(Event.STT_END, {"stt_output":{"text":"command"}}))
        entity.on_pipeline_event(PipelineEvent(Event.INTENT_END, {"intent_output":{"continue_conversation":True,"response":{"response_type":"action_done"}}}))
        entity.on_pipeline_event(PipelineEvent(Event.RUN_END))
    monkeypatch.setattr(entity,"async_accept_pipeline_from_satellite",run)
    await manager.async_start_session(local_start(),persistent=True,local_mode=True)
    await manager.async_handle_gate(gate())
    await asyncio.wait_for(ready.wait(),1)
    await manager.async_handle_activity(activity("speech_start"))
    await manager.async_push_pcm(SESSION_1,b"x"*640)
    await manager.async_handle_activity(activity("speech_end",pcm_samples=320))
    await hass.async_block_till_done(wait_background_tasks=True)
    if not grant_send_failed:
        assert manager.active_session_id == SESSION_1
        await advance_clock(4.9)
        stop.assert_not_awaited()
        await advance_clock(.2)
    assert manager.active_session_id is None
    stop.assert_awaited_once_with(SESSION_1,"followup_send_failed" if grant_send_failed else "followup_handoff_timeout")
    await manager.async_start_session(followup(),persistent=True,local_mode=True)
    assert manager.active_session_id is None
    assert stop.await_args.args == (SESSION_2,"invalid_followup")

@pytest.mark.parametrize("phase", ["before_ready", "stt", "intent", "synthesis", "playing", "followup"])
async def test_true_wake_retires_each_local_phase(hass, satellite, monkeypatch, phase):
    entity, manager, stop = satellite
    await manager.async_end_session(SESSION_1,"test")
    hass.config.internal_url = "http://ha-internal.local:8123"
    monkeypatch.setattr(entity,"validate_local_pipeline",lambda: ("select.test","local"))
    ready, reached, next_entered, sent = (asyncio.Event() for _ in range(4))
    trace = []
    runs = 0
    async def send(kind, payload):
        if kind == 0x25:
            ready.set()
        elif kind == 0x31:
            trace.append("stop")
        elif kind == 0x27:
            reached.set()
    entity.adapter.async_send_message.side_effect = send
    entity.adapter.async_send_tts_play.side_effect = lambda *args, **kwargs: sent.set()

    async def run(audio, stage, *, context, wake_word_phrase):
        nonlocal runs
        runs += 1
        if runs == 2:
            assert trace[-1] == "old_finally"
            next_entered.set()
            await asyncio.Future()
        try:
            entity.on_pipeline_event(PipelineEvent(Event.STT_START))
            if phase == "before_ready":
                reached.set()
                await asyncio.Future()
            async for _ in audio:
                if phase == "stt":
                    reached.set()
                    await asyncio.Future()
            entity.on_pipeline_event(PipelineEvent(Event.STT_END, {"stt_output": {"text": "command"}}))
            if phase == "intent":
                reached.set()
                await asyncio.Future()
            entity.on_pipeline_event(PipelineEvent(Event.INTENT_END, {"intent_output": {
                "continue_conversation": True, "response": {"response_type": "query_answer"}
            }}))
            if phase == "followup":
                entity.on_pipeline_event(PipelineEvent(Event.RUN_END))
                return
            entity.on_pipeline_event(PipelineEvent(Event.TTS_START))
            if phase == "synthesis":
                reached.set()
                await asyncio.Future()
            entity.on_pipeline_event(PipelineEvent(Event.TTS_END, {"tts_output": {
                "url": "/api/tts_proxy/test.mp3", "mime_type": "audio/mpeg"
            }}))
            await sent.wait()
            entity.coordinator.on_playback(entity.adapter.async_send_tts_play.await_args.args[0], "playing")
            reached.set()
            await asyncio.Future()
        finally:
            trace.append("old_finally")

    monkeypatch.setattr(entity,"async_accept_pipeline_from_satellite",run)
    await manager.async_start_session(local_start(),persistent=True,local_mode=True)
    if phase != "before_ready":
        await manager.async_handle_gate(gate())
        await asyncio.wait_for(ready.wait(),1)
        await manager.async_handle_activity(activity("speech_start"))
        await manager.async_push_pcm(SESSION_1,b"x"*640)
        if phase != "stt":
            await manager.async_handle_activity(activity("speech_end",pcm_samples=320))
    await asyncio.wait_for(reached.wait(),1)
    await manager.async_start_session(local_start(SESSION_2,101),persistent=True,local_mode=True)
    await asyncio.wait_for(next_entered.wait(),1)
    assert manager.active_session_id == SESSION_2
    assert trace == (["stop","old_finally"] if phase == "playing" else ["old_finally"])
    await manager.async_end_session(SESSION_1,"late_old_end")
    assert manager.active_session_id == SESSION_2
