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
from wyoming.info import Info, AsrProgram, AsrModel, Attribution, TtsProgram, TtsVoice
from wyoming.audio import AudioStart, AudioChunk, AudioStop
from wyoming.tts import SynthesizeStopped
from wyoming.asr import Transcript

@pytest.mark.enable_socket
@pytest.mark.parametrize("fault", [None, "early", "queued_end", "vad_start", "vad_end", "disconnect", "cancel", "silent", "slow", "superseded", "provider_error", "full", "no_tts", "send_failure", "lost_terminal", "cancel_owner", "stop_unconfirmed", "unload", "eof_unconfirmed", "display_wire_on", "display_wire_off"])
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
    baseline_only = fault == "b88_pcm"
    transcript = "tell me a story about Mars" if baseline_only else "what time is it"
    chats = []
    display_wire = fault in {"display_wire_on", "display_wire_off"}
    full = display_wire or fault in {"full", "no_tts", "send_failure", "lost_terminal", "cancel_owner", "stop_unconfirmed", "unload", "eof_unconfirmed"}
    held_tts = fault in {"cancel_owner", "stop_unconfirmed", "unload", "eof_unconfirmed"}
    hold_chat = fault == "stop_unconfirmed"
    chat_waiting, chat_release = asyncio.Event(), asyncio.Event()
    stop_waiting, stop_release = asyncio.Event(), asyncio.Event()
    remote_stops = []
    tts_wire = []
    tts_receiving, tts_fin, tts_release, tts_closed = (asyncio.Event() for _ in range(4))
    reply = ("A story about Mars. " * 100 + "Would you like another story?") if hold_chat else ("Would you like another story?" if full else "Test AstrBot reply")
    async def handle_chat(request):
        body = await request.json()
        chats.append(body)
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        for event in ({"type": "session_id", "data": None, "session_id": body["session_id"]}, {"type": "plain", "data": reply}):
            await response.write(f"data: {json.dumps(event)}\n\n".encode())
        if hold_chat:
            chat_waiting.set()
            await chat_release.wait()
        else:
            await response.write(b'data: {"type":"end","data":""}\n\n')
            await response.write_eof()
        return response

    async def handle_stop(request):
        remote_stops.append(request.match_info["session_id"])
        stop_waiting.set()
        await stop_release.wait()
        return web.json_response({"status": "error"}, status=500)


    app = web.Application()
    app.router.add_post("/api/v1/chat", handle_chat)
    app.router.add_post("/api/v1/chat/sessions/{session_id}/stop", handle_stop)
    client = await aiohttp_client(app)
    astrbot = MockConfigEntry(domain="astrbot", title="AstrBot", unique_id="astrbot", data={"base_url": str(client.make_url("/")).rstrip("/"), "api_key": "test-secret-value", "api_key_id": "p68-test-key"})
    astrbot.add_to_hass(hass)
    assert await hass.config_entries.async_setup(astrbot.entry_id)
    await hass.async_block_till_done()

    got_pcm = asyncio.Event()
    got_stop = asyncio.Event()
    allow_reply = asyncio.Event()
    peer_closed = asyncio.Event()
    peer_fault = None if baseline_only else fault
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
    tts_server = tts_entry = diagnostic_server = None
    diagnostic_peers = []
    control_server = None
    control_peers = []
    release_display = asyncio.Event()
    services_registered = False
    if full:
        tts_info = Info(tts=[TtsProgram(
            name="R09 loopback TTS", attribution=attribution, installed=True,
            description=None, version=None, supports_synthesize_streaming=True,
            voices=[TtsVoice(name="test", attribution=attribution, installed=True,
                             description=None, version=None, languages=["en-US"])],
        )])

        async def tts_connection(reader, writer):
            active = False
            try:
                while (event := await async_read_event(reader)) is not None:
                    if event.type == "describe":
                        await async_write_event(tts_info.event(), writer)
                        continue
                    tts_wire.append(event)
                    if event.type == "synthesize-start":
                        active = True
                        await async_write_event(AudioStart(rate=16000, width=2, channels=1).event(), writer)
                        await async_write_event(AudioChunk(rate=16000, width=2, channels=1, audio=b"\x01\x02"*16000).event(), writer)
                        tts_receiving.set()
                    if event.type == "synthesize-stop" and not held_tts:
                        await async_write_event(AudioStop().event(), writer)
                        await async_write_event(SynthesizeStopped().event(), writer)
                        break
                if active and held_tts:
                    tts_fin.set()
                    await tts_release.wait()
            finally:
                writer.close()
                await writer.wait_closed()
                if active:
                    tts_closed.set()

        tts_server = await asyncio.start_server(tts_connection, "127.0.0.1", 0)
        tts_entry = MockConfigEntry(domain="wyoming", title="R09 TTS",
            data={"host": "127.0.0.1", "port": tts_server.sockets[0].getsockname()[1]})
        tts_entry.add_to_hass(hass)

    try:
        assert await async_setup_component(hass, "wyoming", {})
        await hass.async_block_till_done()
        from homeassistant.helpers import entity_registry as er
        stt_id = er.async_get(hass).async_get_entity_id("stt", "wyoming", f"{entry.entry_id}-stt")
        assert stt_id
        tts_id = None
        if tts_entry is not None:
            await hass.async_block_till_done()
            tts_id = er.async_get(hass).async_get_entity_id("tts", "wyoming", f"{tts_entry.entry_id}-tts")
            assert tts_id
            assert await async_setup_component(hass, "ffmpeg", {})
            hass.config.internal_url = "http://ha.local:8123"
        store = hass.data[KEY_ASSIST_PIPELINE].pipeline_store
        pipeline = await store.async_create_item(dict(
            name="Tivoo local test", language="en", conversation_engine="conversation.astrbot",
            conversation_language="en", stt_engine=stt_id, stt_language="en-US",
            tts_engine=tts_id, tts_language="en-US" if tts_id else None, tts_voice="test" if tts_id else None,
            wake_word_entity=None, wake_word_id=None, prefer_local_intents=True,
        ))
        stop = AsyncMock()
        manager = AudioSessionManager(stop)
        ready = asyncio.Event()
        adapter = SimpleNamespace(
            async_send_message=AsyncMock(side_effect=lambda *args: ready.set()),
            async_send_tts_play=AsyncMock(), register_playback_handler=Mock(),
        )
        if full:
            from custom_components.tivoo import diagnostics as codec
            from custom_components.tivoo.transport import Esp32ConnectionAdapter, LOCAL_WAKE_CAPABILITY
            from homeassistant.exceptions import HomeAssistantError
            frames = []
            frame_stream = codec.DiagnosticFrameStream()
            sent = asyncio.Event()

            class DeviceWriter:
                def is_closing(self):
                    return False

                def write(self, data):
                    for frame in frame_stream.feed(data):
                        payload = json.loads(frame.payload)
                        frames.append((frame.message_type, payload))
                        if frame.message_type == codec.TYPE_STT_READY:
                            ready.set()
                        elif frame.message_type == codec.TYPE_TTS_PLAY:
                            sent.set()

                async def drain(self):
                    if fault == "send_failure" and frames[-1][0] == codec.TYPE_TTS_PLAY:
                        raise OSError("simulated diagnostic send failure")

            if fault == "lost_terminal" or display_wire:
                # Use the actual TCP connection loop for the R08 epoch-loss
                # scenario. No control channel or hardware is needed here.
                from custom_components.tivoo import transport
                from test_transport import _read_tvio_message, _tvio_message
                negotiated = asyncio.Queue()
                diagnostic_messages = []
                diagnostic_rx_sequence = 1

                async def diagnostic_peer(reader, writer):
                    epoch = len(diagnostic_peers)
                    diagnostic_peers.append(writer)
                    hello = dict(device_id="tivoo-esp32", firmware_version="0.1.0+abcdef0",
                        protocol_version=1, capabilities=[*transport._BASE_CAPABILITIES,
                            LOCAL_WAKE_CAPABILITY, "audio_control", "audio_resource_http"],
                        reset_reason="ESP_RST_POWERON")
                    writer.write(_tvio_message(codec.TYPE_HELLO, 0, json.dumps(hello).encode()))
                    await writer.drain()
                    try:
                        ack = await _read_tvio_message(reader)
                        status = await _read_tvio_message(reader)
                        assert ack == (codec.TYPE_HELLO_ACK, 0, {"accepted": True, "capabilities": [LOCAL_WAKE_CAPABILITY]})
                        assert status[0:2] == (codec.TYPE_GET_STATUS, 1)
                        negotiated.put_nowait((epoch, writer, status[2]["request_id"]))
                        while True:
                            kind, seq, payload = await _read_tvio_message(reader)
                            diagnostic_messages.append((epoch, kind, seq, payload))
                            frames.append((kind, payload))
                            if kind == codec.TYPE_STT_READY:
                                ready.set()
                            elif kind == codec.TYPE_TTS_PLAY:
                                sent.set()
                    except (asyncio.IncompleteReadError, ConnectionError):
                        pass
                    finally:
                        writer.close()
                        await writer.wait_closed()

                diagnostic_server = await asyncio.start_server(diagnostic_peer, "127.0.0.1", 0)
                adapter = Esp32ConnectionAdapter("127.0.0.1", "11:75:58:97:49:98", retry_interval=.05)
                adapter.register_audio_session_manager(manager)
                adapter._tasks["diagnostic"] = asyncio.create_task(adapter._connection_loop(
                    "diagnostic", diagnostic_server.sockets[0].getsockname()[1]))
                epoch, diagnostic_writer, status_request_id = await asyncio.wait_for(negotiated.get(), 3)
                assert epoch == 0
                if display_wire:
                    from custom_components.tivoo.protocol import encode_command
                    from custom_components.tivoo.display_state import build_expression_command, DisplayState
                    from custom_components.tivoo.commands import TivooCommand
                    control_connected = asyncio.Event()
                    control_received = asyncio.Queue()
                    async def control_peer(reader, writer):
                        control_peers.append(writer)
                        try:
                            assert await reader.readexactly(7) == bytes.fromhex("69 11 75 58 97 49 98")
                            control_connected.set()
                            while data := await reader.read(65536):
                                control_received.put_nowait(data)
                        finally:
                            writer.close()
                            await writer.wait_closed()
                    control_server = await asyncio.start_server(control_peer, "127.0.0.1", 0)
                    adapter._tasks["control"] = asyncio.create_task(adapter._connection_loop(
                        "control", control_server.sockets[0].getsockname()[1]))
                    await asyncio.wait_for(control_connected.wait(), 3)
                    async with asyncio.timeout(3):
                        while adapter.states["control"] != "connected":
                            await asyncio.sleep(0)
                    actual_writer = adapter._writers["control"]
                    actual_drain = actual_writer.drain
                    started_display = asyncio.Event()
                    block_display = False

                    async def slow_drain():
                        await actual_drain()
                        if block_display:
                            started_display.set()
                            await release_display.wait()

                    monkeypatch.setattr(actual_writer, "drain", slow_drain)

                    control_buffer = bytearray()

                    async def assert_control(command):
                        expected = b"".join(encode_command(command))
                        async with asyncio.timeout(3):
                            while len(control_buffer) < len(expected):
                                control_buffer.extend(await control_received.get())
                        assert control_buffer[:len(expected)] == expected
                        del control_buffer[:len(expected)]

                    async def assert_no_control():
                        assert not control_buffer
                        with pytest.raises(TimeoutError):
                            await asyncio.wait_for(control_received.get(), .05)

                    async def send_wire(kind, data):
                        nonlocal diagnostic_rx_sequence
                        payload = data if isinstance(data, bytes) else json.dumps(data).encode()
                        diagnostic_writer.write(codec.encode_message(kind, payload, diagnostic_rx_sequence))
                        diagnostic_rx_sequence += 1
                        await diagnostic_writer.drain()

                    async def status(state, mac, uptime):
                        await send_wire(codec.TYPE_DEVICE_STATUS, {
                            "request_id": status_request_id, "device_id": "tivoo-esp32",
                            "firmware_version": "test", "uptime_ms": uptime,
                            "wifi": {"state": "connected"},
                            "tcp": {"7777": "connected", "7778": "connected"},
                            "spp": {"state": state, "mac": mac},
                            "audio_resource": {"state": "idle"},
                        })
                        async with asyncio.timeout(3):
                            while adapter.device_status is None or adapter.device_status["uptime_ms"] != uptime:
                                await asyncio.sleep(0)
                        await asyncio.gather(*adapter._spp_state_tasks)
            else:
                adapter = Esp32ConnectionAdapter(None)
                adapter._diagnostic_handshaken = True
                adapter._diagnostic_capabilities = {LOCAL_WAKE_CAPABILITY, "audio_control", "audio_resource_http"}
                adapter._writers["diagnostic"] = DeviceWriter()
                adapter.register_audio_session_manager(manager)
        output = RecordingAdapter()
        display = ExpressionCoordinator(adapter if display_wire else output, spp_connected=not display_wire)
        if display_wire:
            adapter.register_spp_state_handler(display.async_on_spp_state)
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

        if full:
            from uuid import uuid4
            from urllib.parse import urlsplit
            from homeassistant.components import tts
            from homeassistant.components.assist_pipeline.const import WAKE_WORD_COOLDOWN
            from test_p68_lifecycle import followup
            from homeassistant.core import Context
            from custom_components.tivoo.tts_lifecycle import PipelineTtsOwner

            from homeassistant.components import conversation
            agent = conversation.async_get_agent(hass, "conversation.astrbot")
            original_handle = agent._async_handle_message
            intent_contexts = []

            from custom_components.tivoo.services import register_services, unregister_services
            from custom_components.tivoo.llm import _tools
            from homeassistant.helpers.llm import ToolInput
            from homeassistant.exceptions import HomeAssistantError
            from custom_components.tivoo.display_state import DisplayState, build_expression_command
            if fault in {"full", "no_tts"} or display_wire:
                register_services(hass, {"display_coordinator": display, "command_adapter": display._adapter})
                services_registered = True
            mood_tool = next(tool for tool in _tools() if tool.name == "tivoo__SetMood")
            async def mood(context, name="happy"):
                result = await mood_tool.async_call(hass, ToolInput(tool_name=mood_tool.name,
                    tool_args={"name": name}), SimpleNamespace(context=context))
                assert result.data == {"status": "service_completed"}

            async def observed_intent(user_input, chat_log):
                intent_contexts.append((user_input.satellite_id, user_input.context.id))
                if (fault == "full" or display_wire) and len(intent_contexts) == 1:
                    await mood(user_input.context)
                return await original_handle(user_input, chat_log)

            monkeypatch.setattr(agent, "_async_handle_message", observed_intent)
            if fault == "no_tts":
                # A provider may return a valid successful response with no
                # spoken text. Keep TTS configured and the public run unmodified;
                # only substitute the conversation provider's result.
                from homeassistant.helpers import intent
                async def silent_result(user_input, chat_log):
                    intent_contexts.append((user_input.satellite_id, user_input.context.id))
                    await mood(user_input.context)
                    response = intent.IntentResponse(language=user_input.language)
                    return conversation.ConversationResult(response=response,
                        conversation_id=chat_log.conversation_id)
                monkeypatch.setattr(agent, "_async_handle_message", silent_result)
            transcript = "tell me a story about Mars"
            peer_fault = None
            sid = str(uuid4())
            if display_wire:
                await status("connected", "11:75:58:97:49:98", 10)
                await assert_control(display.desired_command)
                block_display = True
                await send_wire(codec.TYPE_MIC_SESSION_START, local_start(sid, 101))
                await asyncio.wait_for(started_display.wait(), 3)
                await assert_control(build_expression_command("question"))
                await send_wire(codec.TYPE_COMMAND_GATE, gate(sid))
            else:
                await manager.async_start_session(local_start(sid, 101), persistent=True, local_mode=True)
                await manager.async_handle_gate(gate(sid))
            await asyncio.wait_for(ready.wait(), 3)
            turn = entity.coordinator._turn
            assert isinstance(turn.context, Context)
            if display_wire:
                await send_wire(codec.TYPE_MIC_ACTIVITY, activity("speech_start", sid))
                await send_wire(codec.TYPE_MIC_PCM, b"x"*640)
                await send_wire(codec.TYPE_MIC_ACTIVITY, activity("speech_end", sid, pcm_samples=320))
            else:
                await manager.async_handle_activity(activity("speech_start", sid))
                await manager.async_push_pcm(sid, b"x"*640)
                await manager.async_handle_activity(activity("speech_end", sid, pcm_samples=320))
            await asyncio.wait_for(got_stop.wait(), 3)
            def grants():
                return [p for kind, p in frames if kind == codec.TYPE_FOLLOWUP_OPEN]
            async def terminal(session_id, playback_id, state="completed", source="tts_http"):
                nonlocal diagnostic_rx_sequence
                data = json.dumps(dict(session_id=session_id, audio_id=playback_id, state=state, source=source)).encode()
                handler = adapter._message_handlers[codec.TYPE_AUDIO_STATE]
                if fault == "lost_terminal" or display_wire:
                    handled = asyncio.Event()
                    async def observed(message):
                        await handler(message)
                        handled.set()
                    adapter._message_handlers[codec.TYPE_AUDIO_STATE] = observed
                    try:
                        diagnostic_writer.write(codec.encode_message(codec.TYPE_AUDIO_STATE, data, diagnostic_rx_sequence))
                        diagnostic_rx_sequence += 1
                        await diagnostic_writer.drain()
                        await asyncio.wait_for(handled.wait(), 3)
                    finally:
                        adapter._message_handlers[codec.TYPE_AUDIO_STATE] = handler
                else:
                    await handler(codec.DiagnosticMessage(codec.TYPE_AUDIO_STATE, 0, 0, data))
            async def idle():
                await asyncio.wait_for(hass.async_block_till_done(wait_background_tasks=True), 8)

            if fault == "no_tts":
                await idle()
                types = [e.type for e in events]
                assert PipelineEventType.INTENT_END in types and PipelineEventType.RUN_END in types
                assert PipelineEventType.ERROR not in types and PipelineEventType.TTS_START not in types
                assert not grants() and not any(kind == codec.TYPE_TTS_PLAY for kind, p in frames)
                assert not turn.tts_attempted and turn.run_returned and not turn.tts.send_failed
                assert turn.context.id != sid and manager.active_session_id is None
                assert intent_contexts == [(entity.entity_id, turn.context.id)]
                stop.assert_awaited_once_with(sid, "conversation_complete")
                assert all(cmd.data["name"] != "happy" for cmd in output.displays)
                assert display.active_generation is None
                return

            await asyncio.wait_for(sent.wait(), 5)
            play, = [p for kind, p in frames if kind == codec.TYPE_TTS_PLAY]
            assert play["session_id"] == sid and play["playback_id"] == turn.tts.playback_id
            assert intent_contexts == [(entity.entity_id, turn.context.id)]
            assert play["mime_type"] == "audio/mpeg"
            path = urlsplit(play["url"]).path
            assert play["url"].startswith("http://ha.local:8123/api/tts_proxy/")
            start_event = next(e for e in events if e.type == PipelineEventType.RUN_START)
            token = start_event.data["tts_output"]["token"]
            assert path == urlsplit(start_event.data["tts_output"]["url"]).path
            owner = turn.tts._owner
            assert isinstance(owner, PipelineTtsOwner)
            assert owner.stream is tts.async_get_stream(hass, token)
            assert not grants()
            if fault == "send_failure":
                await idle()
                assert turn.tts.send_failed and manager.active_session_id is None
                assert not grants()
                stop.assert_awaited_once_with(sid, "pipeline_failed")
                return

            web_client = await aiohttp_client(hass.http.app)
            get = asyncio.create_task(web_client.get(path))
            await asyncio.wait_for(tts_receiving.wait(), 5)
            if held_tts:
                if hold_chat:
                    await asyncio.wait_for(chat_waiting.wait(), 3)
                await terminal(sid, play["playback_id"], "playing")
                old_caller = turn.task
                old_context = turn.context.id
                await asyncio.sleep(WAKE_WORD_COOLDOWN + 0.05)
                ready.clear()
                new_sid = str(uuid4())
                if fault == "eof_unconfirmed":
                    from custom_components.tivoo import tts_lifecycle
                    monkeypatch.setattr(tts_lifecycle, "_WYOMING_CLOSE_TIMEOUT", .5)
                if fault == "unload":
                    closing = asyncio.create_task(entity.async_will_remove_from_hass())
                else:
                    await manager.async_start_session(local_start(new_sid, 102), persistent=True, local_mode=True)
                    await manager.async_handle_gate(gate(new_sid))
                await asyncio.wait_for(tts_fin.wait(), 5)
                assert not ready.is_set() and not owner._close_task.done()
                if hold_chat:
                    assert not old_caller.done()
                assert len([e for e in events if e.type == PipelineEventType.RUN_START]) == 1
                assert not grants()
                if hold_chat:
                    await asyncio.wait_for(stop_waiting.wait(), 5)
                    assert not ready.is_set()
                    stop_release.set()
                    chat_release.set()
                if fault == "eof_unconfirmed":
                    await idle()
                    assert not ready.is_set() and manager.active_session_id is None
                    assert isinstance(owner._close_task.exception(), HomeAssistantError)
                    assert not grants()
                tts_release.set()
                await asyncio.wait_for(tts_closed.wait(), 5)
                response = await asyncio.wait_for(get, 5)
                await response.read()
                assert owner._close_task is not None
                if fault == "unload":
                    await asyncio.wait_for(closing, 5)
                    assert manager.active_session_id is None
                elif fault == "eof_unconfirmed":
                    stop.assert_awaited_once_with(new_sid, "pipeline_failed")
                elif hold_chat:
                    await idle()
                    assert turn.stop_unconfirmed and remote_stops == [chats[0]["session_id"]]
                    assert manager.active_session_id is None and not ready.is_set()
                    assert not grants()
                    # A subsequent real local turn may enter STT, but the
                    # quarantined AstrBot session must never reach /chat.
                    await asyncio.sleep(WAKE_WORD_COOLDOWN + 0.05)
                    ready.clear()
                    rejected_sid = str(uuid4())
                    await manager.async_start_session(local_start(rejected_sid, 103), persistent=True, local_mode=True)
                    await manager.async_handle_gate(gate(rejected_sid))
                    await asyncio.wait_for(ready.wait(), 5)
                    await manager.async_handle_activity(activity("speech_start", rejected_sid))
                    await manager.async_push_pcm(rejected_sid,b"q"*640)
                    await manager.async_handle_activity(activity("speech_end", rejected_sid,pcm_samples=320))
                    await idle()
                    assert len(chats) == 1 and not grants() and manager.active_session_id is None
                    await hass.services.async_call("astrbot", "new_conversation", blocking=True)
                    hold_chat = False
                    held_tts = False
                    reply = "Recovered."
                    ready.clear()
                    sent.clear()
                    await asyncio.sleep(WAKE_WORD_COOLDOWN + 0.05)
                    new_sid = str(uuid4())
                    await manager.async_start_session(local_start(new_sid, 104), persistent=True, local_mode=True)
                    await manager.async_handle_gate(gate(new_sid))
                    await asyncio.wait_for(ready.wait(), 5)
                    await manager.async_handle_activity(activity("speech_start", new_sid))
                    await manager.async_push_pcm(new_sid,b"y"*640)
                    await manager.async_handle_activity(activity("speech_end", new_sid,pcm_samples=320))
                    await asyncio.wait_for(sent.wait(), 5)
                    recovery = [p for kind,p in frames if kind == codec.TYPE_TTS_PLAY][-1]
                    assert recovery["session_id"] == new_sid
                    result = await web_client.get(urlsplit(recovery["url"]).path)
                    assert result.status == 200 and len(await result.read()) > 44
                    await terminal(new_sid, recovery["playback_id"])
                    await idle()
                    assert manager.active_session_id is None and not grants()
                    assert len(chats) == 2 and chats[0]["session_id"] != chats[1]["session_id"]
                else:
                    await asyncio.wait_for(ready.wait(), 5)
                    assert manager.active_session_id == new_sid
                    assert entity.coordinator._turn.context.id != old_context
                    await terminal(sid, play["playback_id"])
                    assert manager.active_session_id == new_sid and not grants()
                    await manager.async_disconnect()
                    await idle()
                assert old_caller.done() and owner._close_task.done()
                targets = [p for kind,p in frames if kind == codec.TYPE_AUDIO_STOP]
                assert any(p["session_id"] == sid and p["expected_audio_id"] == play["playback_id"] for p in targets)
                return

            response = await asyncio.wait_for(get, 5)
            assert response.status == 200 and response.content_type == "audio/mpeg"
            data = await asyncio.wait_for(response.read(), 5)
            assert data.startswith(b"ID3") and len(data) > 44
            await idle()
            types = [e.type for e in events]
            for event_type in (PipelineEventType.STT_END, PipelineEventType.INTENT_END, PipelineEventType.TTS_END, PipelineEventType.RUN_END):
                assert types.count(event_type) == 1
            assert PipelineEventType.ERROR not in types
            assert next(e for e in events if e.type == PipelineEventType.INTENT_END).data["intent_output"]["continue_conversation"] is True
            assert turn.run_returned and not grants() and manager.active_session_id == sid
            assert owner.producer.done()
            await terminal(str(uuid4()), play["playback_id"])
            await terminal(sid, str(uuid4()))
            await terminal(sid, play["playback_id"], source="prompt")
            assert not grants() and not turn.playback_completed
            if display_wire:
                await terminal(sid, play["playback_id"], "playing")
                assert not release_display.is_set() and turn.valid_stt
                assert display._intents[DisplayState.SPEAKING].generation == turn.context.id
                assert not turn.playback_completed and not grants()
                # Releasing the in-flight wake must skip all queued listening,
                # thinking and tool images and send only the current TTS mood.
                block_display = False
                release_display.set()
                async with display._lock:
                    pass
                await assert_control(build_expression_command("happy"))
                await assert_no_control()
                assert display.desired_state is DisplayState.SPEAKING
                await terminal(str(uuid4()), play["playback_id"])
                await terminal(sid, str(uuid4()))
                await terminal(sid, play["playback_id"], source="prompt")
                assert display.desired_command.data["name"] == "happy"
                assert not turn.playback_completed
                await display.async_set_explicit(build_expression_command("fish"))
                await terminal(sid, play["playback_id"])
                await idle()
                async with display._lock:
                    pass
                assert display.desired_command.data["name"] == "fish"
                await assert_control(build_expression_command("fish"))
                await assert_no_control()
                if fault == "display_wire_off":
                    await display.async_acquire_screen_off("night")
                    await assert_control(TivooCommand("set_screen_power", {"value": False}))
                diagnostic_writer.close()
                await diagnostic_writer.wait_closed()
                epoch, diagnostic_writer, status_request_id = await asyncio.wait_for(negotiated.get(), 3)
                assert epoch == 1 and adapter._writers["control"] is actual_writer
                diagnostic_rx_sequence = 1
                await status("connecting", "11:75:58:97:49:98", 20)
                await display.async_set_explicit(build_expression_command("sad"))
                await status("connected", "00:11:22:33:44:55", 21)
                await display.async_set_explicit(build_expression_command("music"))
                await assert_no_control()
                await send_wire(codec.TYPE_DEVICE_EVENT, {"event": "spp_connected", "uptime_ms": 22,
                    "data": {"mac": "11:75:58:97:49:98"}})
                await assert_control(TivooCommand("set_screen_power", {"value": False})
                    if fault == "display_wire_off" else build_expression_command("music"))
                await assert_no_control()
                return
            await terminal(sid, play["playback_id"], "playing")
            if fault == "full":
                await idle()
                assert display.desired_state is DisplayState.SPEAKING
                assert output.displays[-1].data["name"] == "happy"
            if fault == "lost_terminal":
                # R08 retires the diagnostic epoch, without inventing a
                # completed terminal. Wait for the actual new HELLO/ACK.
                old_writer = diagnostic_writer
                old_writer.close()
                await old_writer.wait_closed()
                epoch, diagnostic_writer, status_request_id = await asyncio.wait_for(negotiated.get(), 3)
                await idle()
                assert epoch == 1 and diagnostic_writer is not old_writer
                diagnostic_rx_sequence = 1
                assert not grants() and manager.active_session_id is None
                await asyncio.sleep(WAKE_WORD_COOLDOWN + 0.05)
                ready.clear()
                await manager.async_start_session(local_start(SESSION_2, 1), persistent=True, local_mode=True)
                await manager.async_handle_gate(gate(SESSION_2))
                await asyncio.wait_for(ready.wait(), 3)
                assert diagnostic_messages[-1][:3] == (1, codec.TYPE_STT_READY, 2)
                await terminal(sid, play["playback_id"])
                assert manager.active_session_id == SESSION_2 and not grants()
                print(f"R09 actual diagnostic epochs: {diagnostic_messages!r}")
                return
            await terminal(sid, play["playback_id"])
            await idle()
            assert grants() == [{"session_id": sid}]
            if fault == "full":
                assert display.desired_command.data["name"] != "happy"
            await terminal(sid, play["playback_id"])
            await idle()
            assert len(grants()) == 1
            await asyncio.sleep(WAKE_WORD_COOLDOWN + 0.05)
            ready.clear()
            payload = followup(sid)
            await manager.async_start_session(payload, persistent=True, local_mode=True)
            await manager.async_handle_gate(gate(SESSION_2))
            await asyncio.wait_for(ready.wait(), 3)
            assert manager.active_session_id == SESSION_2
            followup_turn = entity.coordinator._turn
            assert followup_turn.context.id != turn.context.id
            await terminal(sid, play["playback_id"])
            assert manager.active_session_id == SESSION_2 and len(grants()) == 1
            # Consume the grant once and complete the follow-up with a new
            # actual STT/Intent/TTS run (not just a START handshake).
            sent.clear()
            reply = "That is all."
            await manager.async_handle_activity(activity("speech_start", SESSION_2))
            await manager.async_push_pcm(SESSION_2,b"y"*640)
            await manager.async_handle_activity(activity("speech_end", SESSION_2,pcm_samples=320))
            await asyncio.wait_for(sent.wait(), 5)
            second = [p for kind,p in frames if kind == codec.TYPE_TTS_PLAY][-1]
            assert second["session_id"] == SESSION_2 and second["playback_id"] != play["playback_id"]
            second_get = await web_client.get(urlsplit(second["url"]).path)
            assert second_get.status == 200 and len(await second_get.read()) > 44
            if fault == "full":
                with pytest.raises(HomeAssistantError):
                    await mood(turn.context)
                await terminal(SESSION_2, second["playback_id"], "playing")
                await idle()
                assert output.displays[-1].data["name"] == "music"
            await terminal(SESSION_2, second["playback_id"])
            await idle()
            assert manager.active_session_id is None and len(grants()) == 1
            assert len(chats) == 2 and chats[0]["session_id"] == chats[1]["session_id"]
            assert intent_contexts == [(entity.entity_id, turn.context.id), (entity.entity_id, followup_turn.context.id)]
            assert [e.type for e in wire].count("audio-stop") == 2
            print(f"R09 {fault}: events={types!r} playback={play} context={turn.context.id} device={frames!r}")
            return

        if fault is not None and not baseline_only:
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
        assert await asyncio.wait_for(entity._ask_question_future, 5) == transcript
        entity._ask_question_future = None
        await hass.async_block_till_done(wait_background_tasks=True)
        assert [e.type for e in wire[:2]] == ["transcribe", "audio-start"]
        assert tuple(wire[1].data[key] for key in ("rate", "width", "channels")) == (16000, 2, 1)
        assert b"".join(e.payload for e in wire if e.type == "audio-chunk") == expected
        assert [e.type for e in wire].count("audio-stop") == 1
        assert PipelineEventType.STT_END in [e.type for e in events]
        assert PipelineEventType.STT_VAD_START not in [e.type for e in events]
        assert PipelineEventType.STT_VAD_END not in [e.type for e in events]
        stop.assert_awaited_once_with(SESSION_2,"conversation_complete")
        adapter.async_send_tts_play.assert_not_awaited()
        assert entity.pipeline_entity_id is None
        if baseline_only:
            return

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
        release_display.set()
        if services_registered:
            unregister_services(hass)
        chat_release.set()
        stop_release.set()
        tts_release.set()
        if manager is not None:
            await manager.async_disconnect()
        if entity is not None:
            await entity.async_will_remove_from_hass()
        if display is not None:
            await display.async_shutdown()
        if diagnostic_server is not None:
            await adapter.async_stop()
            for writer in diagnostic_peers:
                writer.close()
                await writer.wait_closed()
            diagnostic_server.close()
            await diagnostic_server.wait_closed()
        if control_server is not None:
            for writer in control_peers:
                writer.close()
                await writer.wait_closed()
            control_server.close()
            await control_server.wait_closed()
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.config_entries.async_unload(astrbot.entry_id)
        if tts_entry is not None:
            await hass.config_entries.async_unload(tts_entry.entry_id)
        if tts_server is not None:
            tts_server.close()
            await tts_server.wait_closed()
        server.close()
        await server.wait_closed()


@pytest.mark.enable_socket
async def test_b88_s3_pcm_reaches_device_endpoint_byte_exact(
    hass, monkeypatch, aiohttp_client, advance_clock
):
    """B8.8 keeps the existing S3 PCM -> HA -> Wyoming path byte exact."""
    await test_public_satellite_stt_device_endpoint_preserves_tail(
        hass, monkeypatch, aiohttp_client, "b88_pcm", advance_clock
    )
