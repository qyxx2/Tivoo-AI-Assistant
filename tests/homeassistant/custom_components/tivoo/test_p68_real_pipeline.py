"""P6.8: real HA Satellite/Core/Wyoming with a loopback-only ASR endpoint."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from custom_components.tivoo.assist_satellite import TivooAssistSatellite
from custom_components.tivoo.audio_session import AudioSessionManager
from custom_components.tivoo.display_state import ExpressionCoordinator
from homeassistant.components.assist_pipeline.models import PipelineStage, PipelineEventType
from homeassistant.components.assist_pipeline.runtime import KEY_ASSIST_PIPELINE
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry
from test_display_state import RecordingAdapter
from test_p68_local_session import local_start, gate, activity
from test_audio_session import SESSION_1, SESSION_2
from test_assist_satellite import advance_clock
from custom_components.tivoo.diagnostics import TYPE_STT_READY
from wyoming.event import async_read_event, async_write_event
from wyoming.info import Info, AsrProgram, AsrModel, Attribution
from wyoming.asr import Transcript

@pytest.mark.enable_socket
@pytest.mark.parametrize("fault", [None, "early", "queued_end", "vad_start", "vad_end", "disconnect", "cancel", "silent", "slow", "superseded", "provider_error"])
async def test_public_satellite_stt_device_endpoint_preserves_tail(hass, monkeypatch, aiohttp_client, fault, advance_clock):
    attribution = Attribution(name="test", url="https://example.invalid")
    info = Info(asr=[AsrProgram(
        name="Sherpa ONNX Paraformer Device Endpoint",
        attribution=attribution, installed=True, description=None, version=None,
        models=[AsrModel(name="paraformer-zh-small-2024-03-09",
                         attribution=attribution, installed=True,
                         description=None, version=None, languages=["en-US"])],
        requires_external_vad=False, supports_transcript_streaming=False,
    )])
    wire = []
    transcript = "what time is it"
    chats = []
    async def handle_chat(request):
        body = await request.json()
        chats.append(body)
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        for event in ({"type": "session_id", "data": None, "session_id": body["session_id"]}, {"type": "plain", "data": "Test AstrBot reply"}, {"type": "end", "data": ""}):
            await response.write(f"data: {json.dumps(event)}\n\n".encode())
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_post("/api/v1/chat", handle_chat)
    client = await aiohttp_client(app)
    astrbot = MockConfigEntry(domain="astrbot", title="AstrBot", unique_id="astrbot", data={"base_url": str(client.make_url("/")).rstrip("/"), "api_key": "test-secret-value", "api_key_id": "p68-test-key"})
    astrbot.add_to_hass(hass)
    assert await hass.config_entries.async_setup(astrbot.entry_id)
    await hass.async_block_till_done()

    got_pcm = asyncio.Event()
    got_stop = asyncio.Event()
    allow_reply = asyncio.Event()
    peer_closed = asyncio.Event()
    peer_fault = fault
    async def connection(reader, writer):
        mode = peer_fault
        early_sent = False
        try:
            while (event := await async_read_event(reader)) is not None:
                if event.type == "describe":
                    await async_write_event(info.event(), writer)
                else:
                    wire.append(event)
                    if event.type == "audio-chunk":
                        got_pcm.set()
                        if mode in {"early", "queued_end"} and not early_sent:
                            await allow_reply.wait()
                            await async_write_event(Transcript(text=transcript).event(), writer)
                            early_sent = True
                    if event.type == "audio-stop":
                        got_stop.set()
                        if mode in {"silent", "superseded"}:
                            continue
                        if mode in {"slow", "provider_error"}:
                            await allow_reply.wait()
                        if mode == "provider_error":
                            from wyoming.error import Error
                            await async_write_event(Error(text="test STT failure", code="model_error").event(), writer)
                        else:
                            await async_write_event(Transcript(text=transcript).event(), writer)
        finally:
            peer_closed.set()
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(connection, "127.0.0.1", 0)
    entry = MockConfigEntry(domain="wyoming", data={"host": "127.0.0.1", "port": server.sockets[0].getsockname()[1]})
    entry.add_to_hass(hass)
    entity = display = manager = None
    try:
        assert await async_setup_component(hass, "wyoming", {})
        await hass.async_block_till_done()
        from homeassistant.helpers import entity_registry as er
        stt_id = er.async_get(hass).async_get_entity_id("stt", "wyoming", f"{entry.entry_id}-stt")
        assert stt_id
        store = hass.data[KEY_ASSIST_PIPELINE].pipeline_store
        pipeline = await store.async_create_item(dict(
            name="Tivoo local test", language="en", conversation_engine="conversation.astrbot",
            conversation_language="en", stt_engine=stt_id, stt_language="en-US",
            tts_engine=None, tts_language=None, tts_voice=None,
            wake_word_entity=None, wake_word_id=None, prefer_local_intents=True,
        ))
        stop = AsyncMock()
        manager = AudioSessionManager(stop)
        ready = asyncio.Event()
        adapter = SimpleNamespace(
            async_send_message=AsyncMock(side_effect=lambda *args: ready.set()),
            async_send_tts_play=AsyncMock(), register_playback_handler=Mock(),
        )
        display = ExpressionCoordinator(RecordingAdapter())
        await display.async_start()
        entity = TivooAssistSatellite("test-entry", manager, adapter, display)
        entity.hass = hass
        entity.entity_id = "assist_satellite.tivoo"
        entity.platform = SimpleNamespace(config_entry=MockConfigEntry(domain="tivoo"))
        entity.registry_entry = None
        entity.async_write_ha_state = Mock()
        registry = er.async_get(hass)
        select = registry.async_get_or_create("select", "tivoo", "test-entry-pipeline", suggested_object_id="tivoo_test")
        assert entity.pipeline_entity_id is None  # legacy keeps preferred
        hass.states.async_set(select.entity_id, pipeline.name)
        assert entity.validate_local_pipeline() == (select.entity_id, pipeline.id)
        hass.states.async_set(select.entity_id, "Preferred")
        with pytest.raises(ValueError):
            entity.validate_local_pipeline()
        hass.states.async_set(select.entity_id, "gone")
        with pytest.raises(ValueError):
            entity.validate_local_pipeline()
        hass.states.async_set(select.entity_id, pipeline.name)
        from dataclasses import replace
        from custom_components.tivoo import assist_satellite as integration
        with monkeypatch.context() as patch:
            patch.setattr(integration, "async_get_pipelines", lambda _: [pipeline, replace(pipeline, id="duplicate")])
            with pytest.raises(ValueError, match="ambiguous"):
                entity.validate_local_pipeline()
        from homeassistant.components import stt
        provider = stt.async_get_speech_to_text_entity(hass, stt_id)
        provider.service.info.asr[0].requires_external_vad = True
        with pytest.raises(ValueError, match="device-endpoint"):
            entity.validate_local_pipeline()
        provider.service.info.asr[0].requires_external_vad = False

        await entity.async_added_to_hass()
        events = []
        original = entity.on_pipeline_event
        def event_received(event):
            events.append(event)
            original(event)
        monkeypatch.setattr(entity, "on_pipeline_event", event_received)
        # Real HA intercept consumes confirmed wake without starting STT.
        intercept = asyncio.create_task(entity.async_intercept_wake_word())
        await asyncio.sleep(0)
        await manager.async_start_session(local_start(), persistent=True, local_mode=True)
        assert await asyncio.wait_for(intercept, 2) == "嗨，乐鑫"
        await hass.async_block_till_done(wait_background_tasks=True)
        stop.assert_awaited_once_with(SESSION_1, "wake_intercepted")
        assert not wire and not ready.is_set()
        stop.reset_mock()
        events.clear()

        if fault is not None:
            from uuid import uuid4
            from homeassistant.components.assist_pipeline import default_pipeline as core
            from homeassistant.components.assist_pipeline.const import WAKE_WORD_COOLDOWN
            from homeassistant.components.wyoming.stt import AsyncTcpClient

            # Keep the entire real public Pipeline through Intent. Deliberately
            # delay the first actual socket write completion, not the provider
            # result, so a legal queued end is provably not a drained iterator.
            public_run = entity.async_accept_pipeline_from_satellite

            async def through_intent(audio, stage, **kwargs):
                return await public_run(audio, stage, end_stage=PipelineStage.INTENT, **kwargs)

            monkeypatch.setattr(entity, "async_accept_pipeline_from_satellite", through_intent)
            if fault == "queued_end":
                write = AsyncTcpClient.write_event

                async def stalled_write(self, event):
                    await write(self, event)
                    if event.type == "audio-chunk":
                        await asyncio.Future()

                monkeypatch.setattr(AsyncTcpClient, "write_event", stalled_write)
            if fault in {"vad_start", "vad_end"}:
                # Change processing after local pipeline validation. Real Core
                # emits its VAD event from the segmenter; no fake Pipeline.
                class UnexpectedSegmenter:
                    def __init__(self, **kwargs):
                        self.in_command = True

                    def process(self, seconds, probability):
                        return fault == "vad_start"

                monkeypatch.setattr(core, "VoiceCommandSegmenter", UnexpectedSegmenter)
                def event_with_vad(event):
                    event_received(event)
                    if event.type == PipelineEventType.STT_START:
                        provider._audio_processing.requires_external_vad = True
                monkeypatch.setattr(entity, "on_pipeline_event", event_with_vad)

            transcript = "tell me a story about Mars"
            peer_closed.clear()
            clock = advance_clock
            sid = str(uuid4())
            await manager.async_start_session(local_start(sid, 101), persistent=True, local_mode=True)
            await manager.async_handle_gate(gate(sid))
            await asyncio.wait_for(ready.wait(), 3)
            await manager.async_handle_activity(activity("speech_start", sid))
            await manager.async_push_pcm(sid, b"x" * 640)
            if fault in {"early", "queued_end", "disconnect", "cancel"}:
                await asyncio.wait_for(got_pcm.wait(), 3)
                if fault == "queued_end":
                    await manager.async_push_pcm(sid, b"y" * 640)
                    await manager.async_handle_activity(activity("speech_end", sid, pcm_samples=640))
                if fault in {"early", "queued_end"}:
                    allow_reply.set()
                elif fault == "disconnect":
                    await manager.async_disconnect()
                else:
                    await manager.async_stop_session(sid, "test_cancelled")
            elif fault in {"slow", "silent", "superseded", "provider_error"}:
                await manager.async_handle_activity(activity("speech_end", sid, pcm_samples=320))
                await asyncio.wait_for(got_stop.wait(), 3)
                await clock(20)
                assert manager.active_session_id == sid
                if fault in {"slow", "provider_error"}:
                    allow_reply.set()
                elif fault == "silent":
                    await clock(26)
                    assert manager.active_session_id is None, "STT result watchdog did not release owner"
                    stop.assert_awaited_once_with(sid, "stt_finalize_timeout")
                else:
                    # Supersede the old result wait before its deadline.
                    # The replacement has its own full finalization window.
                    # Core uses real time.monotonic for duplicate wakes,
                    # distinct from the fake HA event-loop watchdog clock.
                    await asyncio.sleep(WAKE_WORD_COOLDOWN + 0.05)
                    new_sid = str(uuid4())
                    peer_fault = "slow"
                    ready.clear()
                    got_stop.clear()
                    await manager.async_start_session(local_start(new_sid, 102), persistent=True, local_mode=True)
                    await manager.async_handle_gate(gate(new_sid))
                    await asyncio.wait_for(ready.wait(), 3)
                    await manager.async_handle_activity(activity("speech_start", new_sid))
                    await manager.async_push_pcm(new_sid, b"y" * 640)
                    await manager.async_handle_activity(activity("speech_end", new_sid, pcm_samples=320))
                    await asyncio.wait_for(got_stop.wait(), 3)
                    await clock(26)
                    assert manager.active_session_id == new_sid
                    assert not any(c.args == (new_sid, "stt_finalize_timeout") for c in stop.await_args_list)
                    allow_reply.set()

            await asyncio.wait_for(hass.async_block_till_done(wait_background_tasks=True), 5)
            types = [e.type for e in events]
            print(f"R06 {fault}: events={types!r} wire={[e.type for e in wire]} chats={len(chats)}")
            assert manager.active_session_id is None
            if fault in {"slow", "superseded"}:
                assert types.count(PipelineEventType.INTENT_END) == 1
                assert len(chats) == 1
                assert [e.type for e in wire].count("audio-stop") == (2 if fault == "superseded" else 1)
            else:
                assert PipelineEventType.INTENT_START not in types
                assert not chats
                if fault in {"silent", "provider_error"}:
                    assert [e.type for e in wire].count("audio-stop") == 1
                else:
                    assert "audio-stop" not in [e.type for e in wire]
                if fault in {"early", "queued_end"}:
                    assert PipelineEventType.STT_END in types
                if fault in {"vad_start", "vad_end"}:
                    assert (PipelineEventType.STT_VAD_START if fault == "vad_start" else PipelineEventType.STT_VAD_END) in types
            if fault in {"silent", "provider_error"}:
                assert "stt_finalize_timeout" not in entity.coordinator._timers
                await asyncio.wait_for(peer_closed.wait(), 3)
                await asyncio.sleep(WAKE_WORD_COOLDOWN + 0.05)
                peer_fault = None
                ready.clear()
                events.clear()
                wire.clear()
                new_sid = str(uuid4())
                await manager.async_start_session(local_start(new_sid, 102), persistent=True, local_mode=True)
                await manager.async_handle_gate(gate(new_sid))
                await asyncio.wait_for(ready.wait(), 3)
                await manager.async_handle_activity(activity("speech_start", new_sid))
                await manager.async_push_pcm(new_sid, b"z" * 640)
                await manager.async_handle_activity(activity("speech_end", new_sid, pcm_samples=320))
                await asyncio.wait_for(hass.async_block_till_done(wait_background_tasks=True), 5)
                assert manager.active_session_id is None
                assert PipelineEventType.INTENT_END in [e.type for e in events]
                assert len(chats) == 1
                print(f"R06 {fault} recovery: events={[e.type for e in events]!r} wire={[e.type for e in wire]} chats={len(chats)}")
            return

        # Simulate the Core's already pending ask_question caller (announcement
        # is outside b5); the actual public run automatically stops at STT.
        entity._ask_question_future = hass.loop.create_future()
        await manager.async_start_session(local_start(SESSION_2, 101), persistent=True, local_mode=True)
        await manager.async_handle_gate(gate(SESSION_2, "completed"))
        await asyncio.wait_for(ready.wait(), 2)
        assert adapter.async_send_message.call_args.args[0] == TYPE_STT_READY
        assert events[0].data["pipeline"] == pipeline.id
        expected = b"".join(i.to_bytes(2, "little") * 320 for i in range(100))
        await manager.async_handle_activity(activity("speech_start", SESSION_2))
        for i in range(0, len(expected), 640):
            await manager.async_push_pcm(SESSION_2, expected[i:i+640])
        await manager.async_handle_activity(activity("speech_end", SESSION_2, pcm_samples=32000))
        # Count is wire samples, not bytes.
        assert await asyncio.wait_for(entity._ask_question_future, 5) == "what time is it"
        entity._ask_question_future = None
        await hass.async_block_till_done(wait_background_tasks=True)
        assert [e.type for e in wire[:2]] == ["transcribe", "audio-start"]
        assert b"".join(e.payload for e in wire if e.type == "audio-chunk") == expected
        assert [e.type for e in wire].count("audio-stop") == 1
        assert PipelineEventType.STT_END in [e.type for e in events]
        assert PipelineEventType.STT_VAD_START not in [e.type for e in events]
        assert PipelineEventType.STT_VAD_END not in [e.type for e in events]
        stop.assert_awaited_once_with(SESSION_2,"conversation_complete")
        adapter.async_send_tts_play.assert_not_awaited()
        assert entity.pipeline_entity_id is None

        # Actual Core cancellation after a partial upload must never emit
        # AudioStop or an actionable Transcript from the incomplete command.
        from uuid import uuid4
        from homeassistant.components.assist_pipeline.const import WAKE_WORD_COOLDOWN
        await asyncio.sleep(WAKE_WORD_COOLDOWN + 0.05)
        cancelled = str(uuid4())
        wire.clear(); ready.clear(); got_pcm.clear(); events.clear()
        entity._ask_question_future = hass.loop.create_future()
        await manager.async_start_session(local_start(cancelled, 102), persistent=True, local_mode=True)
        await manager.async_handle_gate(gate(cancelled))
        await asyncio.wait_for(ready.wait(), 2)
        await manager.async_handle_activity(activity("speech_start", cancelled))
        await manager.async_push_pcm(cancelled,b"x"*640)
        await asyncio.wait_for(got_pcm.wait(),2)
        await manager.async_disconnect()
        await hass.async_block_till_done(wait_background_tasks=True)
        assert "audio-stop" not in [e.type for e in wire]
        assert PipelineEventType.STT_END not in [e.type for e in events]
        assert PipelineEventType.INTENT_START not in [e.type for e in events]
        entity._ask_question_future.cancel()
        entity._ask_question_future = None

        # Use the real public API through intent (no TTS provider needed for
        # this fixture), preserving actual HA prefer-local and AstrBot SSE.
        public_run = entity.async_accept_pipeline_from_satellite
        async def through_intent(audio, stage, **kwargs):
            return await public_run(audio, stage, end_stage=PipelineStage.INTENT, **kwargs)
        monkeypatch.setattr(entity, "async_accept_pipeline_from_satellite", through_intent)
        for text, expected_chats in (("what time is it", 0), ("tell me a story about Mars", 1), ("tell me another story about Mars", 2), ("tell me a story about Venus", 3)):
            if expected_chats == 3:
                await hass.services.async_call("astrbot", "new_conversation", blocking=True)
            await asyncio.sleep(WAKE_WORD_COOLDOWN + 0.05)
            transcript = text
            ready.clear()
            events.clear()
            sid = str(uuid4())
            await manager.async_start_session(local_start(sid, 100 + expected_chats), persistent=True, local_mode=True)
            await manager.async_handle_gate(gate(sid))
            await asyncio.wait_for(ready.wait(), 3)
            await manager.async_handle_activity(activity("speech_start", sid))
            await manager.async_push_pcm(sid, b"x"*640)
            await manager.async_handle_activity(activity("speech_end", sid, pcm_samples=320))
            await hass.async_block_till_done(wait_background_tasks=True)
            assert PipelineEventType.INTENT_END in [e.type for e in events], events
            assert not any(e.type == PipelineEventType.ERROR for e in events), events
            assert len(chats) == expected_chats, chats
        assert chats[0]["session_id"] == chats[1]["session_id"]
        assert chats[1]["session_id"] != chats[2]["session_id"]
    finally:
        if manager is not None:
            await manager.async_disconnect()
        if entity is not None:
            await entity.async_will_remove_from_hass()
        if display is not None:
            await display.async_shutdown()
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.config_entries.async_unload(astrbot.entry_id)
        server.close()
        await server.wait_closed()
