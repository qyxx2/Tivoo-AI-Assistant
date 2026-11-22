"""B8.5 protocol, raw PCM and resource ownership boundaries."""

import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer
from custom_components.tivoo import qwen_realtime as qwen


class Socket:
    def __init__(self, *, capabilities=None, rate=16000, reverse=False, session_id="entry"):
        self.session_id = session_id
        self.incoming = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.capabilities = capabilities
        self.rate = rate
        self.reverse = reverse

    async def send_json(self, event):
        self.sent.append(event)
        if event["type"] == "session.hello":
            ready = {
                "type": "session.ready",
                "request_event_id": event["event_id"],
                "session_id": self.session_id,
                "protocol_version": "7.0.0",
                "capabilities": event["capabilities"]
                if self.capabilities is None
                else self.capabilities,
            }
            voice = {"type": "voice.ready", "inputSampleRate": self.rate}
            self.feed(*([voice, ready] if self.reverse else [ready, voice]))

    def feed(self, *events):
        for event in events:
            self.incoming.put_nowait(
                SimpleNamespace(type=WSMsgType.TEXT, data=json.dumps(event))
            )

    async def receive(self):
        return await self.incoming.get()

    async def close(self):
        self.closed = True


async def pcm():
    yield b"\x01\x00" * 320


async def spin_until(condition):
    async with asyncio.timeout(2):
        while not condition():
            await asyncio.sleep(0)


@pytest.fixture
def setup_bridge(hass, monkeypatch):
    ws = Socket()
    client = SimpleNamespace(ws_connect=AsyncMock(return_value=ws))
    monkeypatch.setattr(qwen, "async_get_clientsession", lambda _: client)
    monkeypatch.setattr(qwen, "get_url", lambda *a, **k: "http://ha:8123")
    monkeypatch.setattr(qwen, "TAIL_FRAME_SECONDS", 0)
    adapter = SimpleNamespace(
        async_send_tts_play=AsyncMock(), async_send_message=AsyncMock()
    )
    streams = {}
    bridge = qwen.QwenRealtimeBridge(
        hass, adapter, streams, "entry", gateway_token="fixture-token"
    )
    owner = bridge.create_turn(
        "11111111-1111-1111-1111-111111111111", "generation", current=lambda: True
    )
    return bridge, owner, ws, adapter, streams, client


async def response(
    ws, *, status="completed", rate=24000, final=True, tool=False, rid="r1", tid="t1"
):
    await spin_until(
        lambda: any(e["type"] == "input_audio_buffer.append" for e in ws.sent)
    )
    ws.feed(
        {"type": "turn.started", "turnId": tid},
        {"type": "transcript.final", "role": "user", "content": "你好", "turnId": tid},
        {"type": "response.started", "responseId": rid, "turnId": tid},
        {
            "type": "audio.delta",
            "responseId": rid,
            "turnId": tid,
            "sampleRate": rate,
            "audio": base64.b64encode(b"\x02\x00" * 40).decode(),
        },
    )
    if final:
        ws.feed(
            {
                "type": "transcript.final",
                "role": "assistant",
                "content": "需要帮助吗？  ",
                "responseId": rid,
                "turnId": tid,
            }
        )
    ws.feed(
        {
            "type": "audio.done",
            "responseId": rid,
            "turnId": tid,
            "responseStatus": status,
            "hasFunctionCall": tool,
            "awaitsToolFollowUp": tool,
        }
    )


async def consume(owner):
    stream = owner.stream
    stream.claim()
    chunks = [chunk async for chunk in stream.chunks()]
    stream.http_finished.set()
    owner.changed.set()
    return b"".join(chunks)


async def test_handshake_pcm_tail_and_physical_completion(setup_bridge):
    bridge, owner, ws, adapter, streams, client = setup_bridge
    seen = []
    task = asyncio.create_task(bridge.async_run(owner, pcm(), seen.append))
    await spin_until(
        lambda: (
            len([e for e in ws.sent if e["type"] == "input_audio_buffer.append"]) == 51
        )
    )
    hello = ws.sent[0]
    assert hello["protocol"] == {"min": "7.0.0", "max": "7.0.0"}
    assert hello["client"]["instance_id"] == "tivoo-entry"
    assert hello["locale"] == "zh-CN"
    assert set(hello["capabilities"]) >= {
        "input.audio",
        "session.heartbeat",
        "response.terminal-status",
    }
    assert client.ws_connect.call_args.kwargs["headers"] == {
        "Authorization": "Bearer fixture-token"
    }
    assert "sessionId=entry" in client.ws_connect.call_args.args[0]
    frames = [
        base64.b64decode(e["audio"])
        for e in ws.sent
        if e["type"] == "input_audio_buffer.append"
    ]
    assert frames == [b"\x01\x00" * 320] + [bytes(640)] * 50
    await response(ws)
    await spin_until(lambda: owner.playback_id is not None)
    consumer = asyncio.create_task(consume(owner))
    await consumer
    assert not task.done()
    bridge.on_playback("wrong-id", "completed")
    assert not task.done()
    bridge.on_playback(owner.playback_id, "completed")
    result = await task
    assert result.transcript == "需要帮助吗？  "
    assert result.response_id == "r1" and result.turn_id == "t1"
    adapter.async_send_tts_play.assert_awaited_once()
    args = adapter.async_send_tts_play.call_args
    assert args.kwargs["session_id"] == owner.session_id
    assert args.args[2] == "audio/x-tivoo-pcm-s16le-24000-mono"
    assert consumer.result() == b"\x02\x00" * 40
    assert ws.closed and not streams
    assert any(e.get("role") == "user" for e in seen)
    assert owner.stream.session_id == owner.session_id
    assert owner.stream.generation == owner.generation
    assert owner.stream.response_ids == {"r1"}
    assert set(owner.timings) >= {
        "voice_ready",
        "input_eof",
        "first_output",
        "tts_play",
        "playback_completed",
    }


@pytest.mark.parametrize(
    "case", ["capability", "ordering", "rate", "gateway-error", "bad-json"]
)
async def test_invalid_handshake_fails_closed(setup_bridge, case):
    bridge, owner, ws, adapter, streams, _ = setup_bridge
    if case == "capability":
        ws.capabilities = ["input.audio"]
    if case == "ordering":
        ws.reverse = True
    if case == "rate":
        ws.rate = 24000
    if case == "gateway-error":
        ws.feed({"type": "error", "message": "secret-url-must-not-escape"})
    if case == "bad-json":
        ws.incoming.put_nowait(SimpleNamespace(type=WSMsgType.TEXT, data="{"))
    with pytest.raises((ValueError, RuntimeError, ConnectionError)):
        await bridge.async_run(owner, pcm(), lambda _: None)
    assert ws.closed and not streams
    adapter.async_send_tts_play.assert_not_awaited()


@pytest.mark.parametrize(
    "status", ["cancelled", "incomplete", "failed", "unknown", None]
)
async def test_abnormal_terminal_never_succeeds(setup_bridge, status):
    bridge, owner, ws, _, streams, _ = setup_bridge
    task = asyncio.create_task(bridge.async_run(owner, pcm(), lambda _: None))
    await response(ws, status=status)
    with pytest.raises(RuntimeError):
        await task
    assert ws.closed and not streams


async def test_early_output_waits_for_local_eof(setup_bridge):
    bridge, owner, ws, adapter, _, _ = setup_bridge
    eof = asyncio.Event()

    async def audio():
        yield b"\0\0" * 320
        await eof.wait()

    task = asyncio.create_task(bridge.async_run(owner, audio(), lambda _: None))
    await response(ws)
    await spin_until(lambda: owner.stream is not None)
    adapter.async_send_tts_play.assert_not_awaited()
    eof.set()
    await spin_until(lambda: owner.playback_id is not None)
    data = await consume(owner)
    bridge.on_playback(owner.playback_id, "completed")
    await task
    assert data == b"\x02\x00" * 40


async def test_tool_audio_done_and_late_final_text(setup_bridge):
    bridge, owner, ws, _, _, _ = setup_bridge
    task = asyncio.create_task(bridge.async_run(owner, pcm(), lambda _: None))
    await response(ws, tool=True)
    await spin_until(lambda: owner.playback_id is not None)
    consumer = asyncio.create_task(consume(owner))
    await asyncio.sleep(0)
    assert not consumer.done() and not task.done()
    ws.feed(
        {"type": "response.started", "turnId": "t1", "responseId": "r2"},
        {
            "type": "audio.delta",
            "turnId": "t1",
            "responseId": "r2",
            "sampleRate": 24000,
            "audio": "AAA=",
        },
        {
            "type": "audio.done",
            "turnId": "t1",
            "responseId": "r2",
            "responseStatus": "completed",
            "hasFunctionCall": False,
            "awaitsToolFollowUp": False,
        },
    )
    await consumer
    bridge.on_playback(owner.playback_id, "completed")
    await asyncio.sleep(0)
    assert not task.done()
    ws.feed(
        {
            "type": "transcript.final",
            "role": "assistant",
            "turnId": "t1",
            "responseId": "r2",
            "content": "好了。",
        }
    )
    result = await task
    assert result.transcript == "好了。" and result.response_id == "r2"


@pytest.mark.parametrize(
    "event",
    [
        {"type": "playback.clear"},
        {"type": "input.suspend"},
        {"type": "voice.deactivated"},
        {"type": "turn.started", "turnId": "second"},
    ],
)
async def test_clear_suspend_and_second_turn_abort_owned_playback(setup_bridge, event):
    bridge, owner, ws, adapter, streams, _ = setup_bridge
    task = asyncio.create_task(bridge.async_run(owner, pcm(), lambda _: None))
    await response(ws, final=False)
    await spin_until(lambda: owner.playback_id is not None)
    ws.feed(event)
    with pytest.raises(RuntimeError):
        await task
    stops = [
        json.loads(call.args[1]) for call in adapter.async_send_message.await_args_list
    ]
    assert stops[-1]["expected_audio_id"] == owner.playback_id
    assert stops[-1]["session_id"] == owner.session_id
    assert not streams and ws.closed


async def test_byte_bound_finish_abort_never_wait_for_queue_space():
    stream = qwen.QwenPcmStream("test", 24000, max_bytes=8)
    stream.push(b"12345678")
    with pytest.raises(RuntimeError):
        stream.push(b"90")
    stream.finish()
    stream.abort()
    assert stream.buffered_bytes == 0
    stream.claim()
    assert [chunk async for chunk in stream.chunks()] == []


async def test_pcm_http_is_one_shot_and_delivers_unchanged(socket_enabled):
    stream = qwen.QwenPcmStream("opaque", 32000)
    streams = {"opaque": stream}
    view = qwen.TivooQwenPcmView(streams)
    app = web.Application()

    async def get(req):
        return await view.get(req, req.match_info["stream_id"])

    app.router.add_get("/audio/{stream_id}", get)
    async with TestClient(TestServer(app)) as client:
        stream.push(b"\x00\x01" * 320)
        stream.finish()
        res = await client.get("/audio/opaque")
        assert res.status == 200
        assert res.headers["Content-Type"] == "audio/x-tivoo-pcm-s16le-32000-mono"
        assert await res.read() == b"\x00\x01" * 320
        assert (await client.get("/audio/opaque")).status in (404, 409)
        assert (await client.get("/audio/missing")).status == 404
    assert stream.http_finished.is_set() and not streams


async def test_cancel_closes_and_joins_sender_once(setup_bridge):
    bridge, owner, ws, _adapter, streams, _ = setup_bridge
    stopped = asyncio.Event()

    async def audio():
        try:
            yield b"\0\0"
            await asyncio.Future()
        finally:
            stopped.set()

    task = asyncio.create_task(bridge.async_run(owner, audio(), lambda _: None))
    await response(ws)
    await spin_until(lambda: owner.stream is not None)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await owner.async_close()
    assert stopped.is_set() and ws.closed and not streams
    assert len([e for e in ws.sent if e["type"] == "response.cancel"]) == 1


async def test_sender_failure_is_not_hidden_until_receive_timeout(setup_bridge):
    bridge, owner, ws, _, streams, _ = setup_bridge

    async def invalid():
        yield b"\x00"

    with pytest.raises(ValueError):
        await bridge.async_run(owner, invalid(), lambda _: None)
    assert ws.closed and not streams


async def test_no_http_get_has_bounded_cleanup(setup_bridge, monkeypatch):
    bridge, owner, ws, adapter, streams, _ = setup_bridge
    monkeypatch.setattr(qwen, "GET_TIMEOUT", 0.02)
    task = asyncio.create_task(bridge.async_run(owner, pcm(), lambda _: None))
    await response(ws)
    with pytest.raises(TimeoutError):
        await task
    assert ws.closed and not streams
    assert adapter.async_send_message.await_count == 1


async def test_stop_send_failure_still_closes_socket(setup_bridge):
    bridge, owner, ws, adapter, streams, _ = setup_bridge
    adapter.async_send_message.side_effect = ConnectionError("device disappeared")
    task = asyncio.create_task(bridge.async_run(owner, pcm(), lambda _: None))
    await response(ws, final=False)
    await spin_until(lambda: owner.playback_id is not None)
    ws.feed({"type": "playback.clear"})
    with pytest.raises((RuntimeError, ConnectionError)):
        await task
    assert ws.closed and not streams


async def test_explicit_retention_reuses_socket_after_old_owner_retired(setup_bridge):
    bridge, owner, ws, _, streams, client = setup_bridge
    owner.keep_socket = True
    task = asyncio.create_task(bridge.async_run(owner, pcm(), lambda _: None))
    await response(ws)
    await spin_until(lambda: owner.playback_id is not None)
    await consume(owner)
    bridge.on_playback(owner.playback_id, "completed")
    await task
    assert not ws.closed and not streams
    # Old Satellite on_end/retire must leave the retained socket available.
    owner.stop_dispatch()
    await owner.async_close()
    assert not ws.closed
    next_owner = bridge.create_turn(
        "22222222-2222-2222-2222-222222222222",
        "next",
        current=lambda: True,
        parent_session_id=owner.session_id,
    )
    second = asyncio.create_task(bridge.async_run(next_owner, pcm(), lambda _: None))
    await spin_until(
        lambda: (
            len([e for e in ws.sent if e["type"] == "input_audio_buffer.append"]) == 102
        )
    )
    # Late old-generation traffic on the SAME socket cannot be handed to MIC 2.
    ws.feed(
        {
            "type": "audio.delta",
            "turnId": "t1",
            "responseId": "r1",
            "sampleRate": 24000,
            "audio": "AAA=",
        }
    )
    await response(ws, tid="t2", rid="r2", rate=32000)
    await spin_until(lambda: next_owner.playback_id is not None)
    assert next_owner.playback_id != owner.playback_id
    assert await consume(next_owner) == b"\x02\x00" * 40
    bridge.on_playback(next_owner.playback_id, "completed")
    assert (await second).turn_id == "t2"
    assert client.ws_connect.await_count == 1 and ws.closed


async def test_missing_parent_socket_never_reconnects_as_followup(setup_bridge):
    bridge, _, _ws, _, streams, client = setup_bridge
    owner = bridge.create_turn(
        "mic", "next", current=lambda: True, parent_session_id="missing"
    )
    with pytest.raises(RuntimeError):
        await bridge.async_run(owner, pcm(), lambda _: None)
    client.ws_connect.assert_not_awaited()
    assert not streams


async def test_retained_socket_timeout_closes_and_cannot_be_reused(
    setup_bridge, monkeypatch
):
    bridge, owner, ws, _, _, _ = setup_bridge
    monkeypatch.setattr(qwen, "RETAIN_SECONDS", 0.02)
    owner.keep_socket = True
    task = asyncio.create_task(bridge.async_run(owner, pcm(), lambda _: None))
    await response(ws)
    await spin_until(lambda: owner.playback_id is not None)
    await consume(owner)
    bridge.on_playback(owner.playback_id, "completed")
    await task
    await asyncio.sleep(0.04)
    assert ws.closed


@pytest.mark.parametrize(
    "mutation",
    [
        "changed-rate",
        "unsupported-rate",
        "bad-base64",
        "odd-pcm",
        "overflow",
        "missing-metadata",
    ],
)
async def test_invalid_output_fails_and_removes_registry(setup_bridge, mutation):
    bridge, owner, ws, _, streams, _ = setup_bridge
    task = asyncio.create_task(bridge.async_run(owner, pcm(), lambda _: None))
    await response(ws, tool=True)
    await spin_until(lambda: owner.playback_id is not None)
    event = {
        "type": "audio.delta",
        "turnId": "t1",
        "responseId": "r1",
        "sampleRate": 24000,
        "audio": "AAA=",
    }
    if mutation == "changed-rate":
        event["sampleRate"] = 32000
    if mutation == "unsupported-rate":
        event["sampleRate"] = 22050
    if mutation == "bad-base64":
        event["audio"] = "?"
    if mutation == "odd-pcm":
        event["audio"] = "AA=="
    if mutation == "overflow":
        event["audio"] = base64.b64encode(bytes(qwen.MAX_PCM_BYTES)).decode()
    if mutation == "missing-metadata":
        event = {
            "type": "audio.done",
            "turnId": "t1",
            "responseId": "r1",
            "responseStatus": "completed",
        }
    ws.feed(event)
    with pytest.raises((ValueError, RuntimeError)):
        await task
    assert not streams and ws.closed


async def test_heartbeat_pong_correlates_exact_server_ping(setup_bridge):
    bridge, owner, ws, _, _, _ = setup_bridge
    task = asyncio.create_task(bridge.async_run(owner, pcm(), lambda _: None))
    await response(ws)
    ws.feed({"type": "session.ping", "event_id": "ping-fixture"})
    await spin_until(lambda: any(e["type"] == "session.pong" for e in ws.sent))
    pong = next(e for e in ws.sent if e["type"] == "session.pong")
    assert (
        pong["request_event_id"] == "ping-fixture"
        and pong["event_id"] != "ping-fixture"
    )
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_http_disconnect_revokes_owner(setup_bridge):
    bridge, owner, ws, _, streams, _ = setup_bridge
    task = asyncio.create_task(bridge.async_run(owner, pcm(), lambda _: None))
    await response(ws, tool=True)
    await spin_until(lambda: owner.playback_id is not None)
    owner.stream.claim()
    owner.stream.disconnected = True
    owner.stream.abort()
    with pytest.raises(RuntimeError):
        await task
    assert not streams and ws.closed


@pytest.mark.parametrize("no_text", [True, False])
async def test_missing_text_or_physical_completion_times_out(
    setup_bridge, monkeypatch, no_text
):
    bridge, owner, ws, _, streams, _ = setup_bridge
    monkeypatch.setattr(qwen, "EVENT_TIMEOUT", 0.02)
    task = asyncio.create_task(bridge.async_run(owner, pcm(), lambda _: None))
    await response(ws, final=not no_text)
    await spin_until(lambda: owner.playback_id is not None)
    await consume(owner)
    if no_text:
        bridge.on_playback(owner.playback_id, "completed")
    with pytest.raises(TimeoutError):
        await task
    assert not streams and ws.closed


async def test_real_http_disconnect_releases_handler_without_logging_capability(
    socket_enabled, monkeypatch, caplog
):
    monkeypatch.setattr(qwen, "IO_TIMEOUT", 0.02)
    stream = qwen.QwenPcmStream("opaque-capability-never-log", 24000)
    streams = {stream.stream_id: stream}
    view = qwen.TivooQwenPcmView(streams)
    app = web.Application()

    async def get(req):
        return await view.get(req, req.match_info["stream_id"])

    app.router.add_get("/audio/{stream_id}", get)
    async with TestClient(TestServer(app)) as client:
        stream.push(b"\0\0" * 320)
        res = await client.get(f"/audio/{stream.stream_id}")
        assert await res.content.readexactly(640) == bytes(640)
        res.close()
        await asyncio.wait_for(stream.http_finished.wait(), 0.5)
    assert stream.disconnected and not streams
    assert "opaque-capability-never-log" not in caplog.text


async def test_cancel_joins_active_http_handler(
    setup_bridge, socket_enabled, monkeypatch
):
    bridge, owner, ws, _, streams, _ = setup_bridge
    task = asyncio.create_task(bridge.async_run(owner, pcm(), lambda _: None))
    await response(ws, tool=True)
    await spin_until(lambda: owner.playback_id is not None)
    # Hold a response write to exercise cleanup during consumer backpressure.
    entered = asyncio.Event()

    async def blocked_write(self, data):
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(web.StreamResponse, "write", blocked_write)
    view = qwen.TivooQwenPcmView(streams)
    app = web.Application()

    async def get(req):
        return await view.get(req, req.match_info["stream_id"])

    app.router.add_get("/audio/{stream_id}", get)
    async with TestClient(TestServer(app)) as client:
        await client.get(f"/audio/{owner.playback_id}")
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert owner.stream.http_finished.is_set()
    assert not streams and ws.closed


@pytest.mark.parametrize("tool_status", ["completed", "failed"])
async def test_tool_acceptance_without_second_response_finishes_delivery_only(
    setup_bridge, monkeypatch, tool_status
):
    bridge, owner, ws, _, streams, _ = setup_bridge
    monkeypatch.setattr(qwen, "EVENT_TIMEOUT", 0.1)
    owner.keep_socket = True
    seen = []

    def observe(event):
        seen.append(event)
        if event["type"] == "transcript.final":
            owner.keep_socket = True

    task = asyncio.create_task(bridge.async_run(owner, pcm(), observe))
    await spin_until(
        lambda: any(e["type"] == "input_audio_buffer.append" for e in ws.sent)
    )
    ws.feed(
        {"type": "turn.started", "turnId": "t1"},
        {"type": "response.started", "turnId": "t1", "responseId": "r1"},
        {
            "type": "audio.delta",
            "turnId": "t1",
            "responseId": "r1",
            "sampleRate": 24000,
            "audio": "AAA=",
        },
        {
            "type": "tool.call",
            "turnId": "t1",
            "responseId": "r1",
            "callId": "call1",
            "status": "received",
        },
        {
            "type": "audio.done",
            "turnId": "t1",
            "responseId": "r1",
            "responseStatus": "completed",
            "hasFunctionCall": True,
            "awaitsToolFollowUp": False,
        },
    )
    await spin_until(lambda: owner.playback_id is not None)
    consumer = asyncio.create_task(consume(owner))
    try:
        await asyncio.wait_for(asyncio.shield(consumer), 0.05)
        bridge.on_playback(owner.playback_id, "completed")
        await asyncio.sleep(0)
        assert not task.done(), "must join the pending tool before closing its socket"
        ws.feed(
            {
                "type": "transcript.final",
                "role": "assistant",
                "turnId": "t1",
                "responseId": "r1",
                "content": "已受理。",
            },
            {
                "type": "tool.call",
                "turnId": "t1",
                "responseId": "r1",
                "callId": "call1",
                "status": tool_status,
            },
        )
        if tool_status == "failed":
            with pytest.raises(RuntimeError):
                await task
        else:
            result = await task
            assert result.transcript == "已受理。" and not result.followup_eligible
    finally:
        task.cancel()
        consumer.cancel()
        await asyncio.gather(task, consumer, return_exceptions=True)
    assert ws.closed and not streams
