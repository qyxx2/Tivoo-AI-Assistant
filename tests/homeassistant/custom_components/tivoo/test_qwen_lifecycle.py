"""B8.6 real bridge + ingress + Satellite lifecycle, with only wire I/O faked."""

# ruff: noqa: F811

import asyncio
import json

import pytest
from custom_components.tivoo import qwen_realtime as qwen
from custom_components.tivoo.diagnostics import TYPE_FOLLOWUP_OPEN
from custom_components.tivoo.display_state import DisplayState
from test_audio_session import SESSION_1, SESSION_2
from test_p68_local_session import activity, gate, local_start
from test_qwen_realtime import (
    consume,
    response,
    setup_bridge,  # noqa: F401
    spin_until,
)
from test_qwen_satellite import qwen_satellite  # noqa: F401


@pytest.fixture
async def live(qwen_satellite, setup_bridge):
    entity, manager, stop, _ = qwen_satellite
    bridge, _, ws, _, streams, client = setup_bridge
    entity.qwen_bridge = bridge
    bridge.adapter = entity.adapter
    yield entity, manager, stop, bridge, ws, streams, client
    await bridge.async_close()


async def start(live, session=SESSION_1, parent=None):
    entity, manager, _, bridge, *_ = live
    payload = local_start(session, 100 if session == SESSION_1 else 101)
    if parent:
        payload.pop("wake_word_phrase")
        payload.update(trigger_source="local_followup", parent_session_id=parent)
    await manager.async_start_session(payload, persistent=True, local_mode=True)
    await spin_until(
        lambda: bridge._owner is not None and bridge._owner.session_id == session
    )
    owner = bridge._owner
    await spin_until(lambda: manager._active_session.ready)
    await manager.async_handle_gate(gate(session))
    await manager.async_handle_activity(activity("speech_start", session))
    await manager.async_push_pcm(session, b"a" * 640)
    await manager.async_handle_activity(
        activity("speech_end", session, pcm_samples=320)
    )
    await spin_until(lambda: owner.input_drained)
    return entity.coordinator._turn, owner


def opens(entity):
    return [
        c
        for c in entity.adapter.async_send_message.await_args_list
        if c.args[0] == TYPE_FOLLOWUP_OPEN
    ]


async def finish(live, owner, turn, text="继续？", tid="t1", rid="r1"):
    entity, _, _, _bridge, ws, *_ = live
    await response(ws, final=False, tid=tid, rid=rid)
    ws.feed(
        {
            "type": "transcript.final",
            "role": "assistant",
            "content": text,
            "turnId": tid,
            "responseId": rid,
        }
    )
    await spin_until(lambda: owner.playback_id is not None)
    await consume(owner)
    entity.coordinator.on_playback(owner.playback_id, "completed")
    await turn.task


@pytest.mark.parametrize(
    "text,want",
    [("继续？  \n", True), ("Next?", True), ("完成。", False), ("好!", False)],
)
async def test_question_policy_and_physical_completion(live, text, want):
    entity, manager, stop, _bridge, ws, streams, _ = live
    turn, owner = await start(live)
    await response(ws, final=False)
    ws.feed(
        {
            "type": "transcript.delta",
            "role": "assistant",
            "content": "假的？",
            "turnId": "t1",
            "responseId": "r1",
        }
    )
    ws.feed(
        {
            "type": "transcript.final",
            "role": "assistant",
            "content": text,
            "turnId": "t1",
            "responseId": "r1",
        }
    )
    await spin_until(lambda: owner.playback_id is not None)
    await consume(owner)
    assert not opens(entity)
    entity.coordinator.on_playback("wrong", "completed")
    assert not opens(entity)
    entity.coordinator.on_playback(owner.playback_id, "completed")
    await turn.task
    entity.coordinator.on_playback(owner.playback_id, "completed")
    await asyncio.sleep(0)
    assert bool(turn.continue_conversation) is want
    assert len(opens(entity)) == int(want)
    if want:
        assert json.loads(opens(entity)[0].args[1]) == {"session_id": SESSION_1}
        assert manager.active_session_id == SESSION_1
        assert not ws.closed and not streams
        stop.assert_not_awaited()
    else:
        assert ws.closed
        assert manager.active_session_id is None


async def test_followup_handoff_new_identity_same_socket(live):
    entity, manager, _, _bridge, ws, _, client = live
    turn, owner = await start(live)
    await finish(live, owner, turn)
    assert len(opens(entity)) == 1
    next_turn, next_owner = await start(live, SESSION_2, SESSION_1)
    assert next_turn.context.id != turn.context.id
    assert next_owner.parent_session_id == SESSION_1
    await finish(live, next_owner, next_turn, text="完成。", tid="t2", rid="r2")
    assert client.ws_connect.await_count == 1
    assert ws.closed and manager.active_session_id is None


@pytest.mark.parametrize(
    "event",
    [
        {"type": "playback.clear"},
        {"type": "input.suspend"},
        {"type": "voice.deactivated"},
    ],
)
async def test_retained_connection_revocation_closes_device_grant(live, event):
    entity, manager, _, _, ws, _, _ = live
    turn, owner = await start(live)
    await finish(live, owner, turn)
    assert len(opens(entity)) == 1
    ws.feed(event)
    await spin_until(lambda: manager.active_session_id is None)
    assert ws.closed
    assert manager._followup_grant is None


async def test_gate_timeout_closes_retained_socket(live):
    entity, manager, _, _, ws, _, _ = live
    turn, owner = await start(live)
    await finish(live, owner, turn)
    reason = "followup_handoff_timeout"
    await entity.coordinator._expire_timer(
        turn, reason, entity.coordinator._timers[reason]
    )
    await spin_until(lambda: ws.closed)
    assert manager.active_session_id is None


async def test_qwen_transcript_and_tool_display(live):
    entity, _, _, _, ws, _, _ = live
    turn, owner = await start(live)
    await response(ws, tool=True)
    await spin_until(lambda: turn.valid_stt)
    assert DisplayState.THINKING in entity.coordinator.display._intents
    ws.feed(
        {
            "type": "tool.call",
            "turnId": "t1",
            "responseId": "r1",
            "callId": "c1",
            "status": "running",
        }
    )
    await spin_until(lambda: owner.tools.get("c1") == ("r1", "running"))
    assert DisplayState.TOOLUSE in entity.coordinator.display._intents


@pytest.mark.parametrize("phase", ["generation", "tool", "playback"])
async def test_new_wake_cancels_and_joins_only_old_generation(live, phase):
    from test_qwen_realtime import Socket

    entity, manager, _, bridge, ws, streams, client = live
    turn, owner = await start(live)
    if phase != "generation":
        await response(ws, tool=phase == "tool")
        await spin_until(lambda: owner.playback_id is not None)
        if phase == "tool":
            ws.feed(
                {
                    "type": "tool.call",
                    "turnId": "t1",
                    "responseId": "r1",
                    "callId": "c1",
                    "status": "running",
                }
            )
            await spin_until(lambda: bool(owner.tools))
        else:
            entity.coordinator.on_playback(owner.playback_id, "playing")
    replacement = Socket()
    client.ws_connect.return_value = replacement
    await manager.async_start_session(
        local_start(SESSION_2, 101), persistent=True, local_mode=True
    )
    await spin_until(
        lambda: bridge._owner is not None and bridge._owner.session_id == SESSION_2
    )
    assert ws.closed and turn.task.done() and not streams
    assert any(e["type"] == "response.cancel" for e in ws.sent)
    assert not owner.current()
    old_id = owner.playback_id or "old-unstarted-playback"
    entity.coordinator.on_playback(old_id, "completed")
    new_turn = entity.coordinator._turn
    assert new_turn.context.id != turn.context.id and not new_turn.playback_completed
    assert not opens(entity)


@pytest.mark.parametrize(
    "failure",
    ["cancelled", "incomplete", "failed", "playback", "missing_text", "disconnect"],
)
async def test_question_response_failure_never_grants(live, monkeypatch, failure):
    entity, manager, _, _bridge, ws, streams, _ = live
    turn, owner = await start(live)
    if failure == "disconnect":
        from types import SimpleNamespace

        from aiohttp import WSMsgType

        ws.incoming.put_nowait(SimpleNamespace(type=WSMsgType.CLOSED, data=None))
    elif failure in {"cancelled", "incomplete", "failed"}:
        await response(ws, status=failure)
    else:
        await response(ws, final=failure != "missing_text")
        await spin_until(lambda: owner.playback_id is not None)
        await consume(owner)
        if failure == "playback":
            entity.coordinator.on_playback(owner.playback_id, "failed")
        else:
            monkeypatch.setattr(qwen, "EVENT_TIMEOUT", 0.01)
            entity.coordinator.on_playback(owner.playback_id, "completed")
    await asyncio.gather(turn.task, return_exceptions=True)
    await spin_until(lambda: manager.active_session_id is None)
    assert not opens(entity) and ws.closed and not streams
    assert manager.active_session_id is None


async def test_tool_intermediate_question_only_final_response_decides(live):
    entity, _, _, _, ws, _, _ = live
    turn, owner = await start(live)
    await response(ws, tool=True)
    ws.feed(
        {
            "type": "tool.call",
            "turnId": "t1",
            "responseId": "r1",
            "callId": "c1",
            "status": "completed",
        }
    )
    await spin_until(lambda: owner.tools.get("c1") == ("r1", "completed"))
    assert not opens(entity)
    await response(ws, final=False, rid="r2")
    ws.feed(
        {
            "type": "transcript.final",
            "role": "assistant",
            "content": "最终还需要确认？",
            "turnId": "t1",
            "responseId": "r2",
        }
    )
    await spin_until(lambda: owner.final_response == "r2")
    await consume(owner)
    entity.coordinator.on_playback(owner.playback_id, "completed")
    await turn.task
    assert len(opens(entity)) == 1 and not ws.closed


async def test_late_final_after_physical_completion_can_authorize(live):
    entity, _, _, _, ws, _, _ = live
    turn, owner = await start(live)
    await response(ws, final=False)
    await spin_until(lambda: owner.playback_id is not None)
    await consume(owner)
    entity.coordinator.on_playback(owner.playback_id, "completed")
    await asyncio.sleep(0)
    assert not opens(entity)
    ws.feed(
        {
            "type": "transcript.final",
            "role": "assistant",
            "content": "继续？",
            "turnId": "t1",
            "responseId": "r1",
        }
    )
    await turn.task
    assert len(opens(entity)) == 1


async def test_followup_send_failure_closes_retained_socket(live):
    entity, manager, _, _, ws, _, _ = live
    turn, owner = await start(live)
    entity.adapter.async_send_message.side_effect = ConnectionError("device lost")
    await finish(live, owner, turn)
    await spin_until(lambda: ws.closed)
    assert manager.active_session_id is None


async def test_shutdown_during_followup_joins_retained_reader(live):
    entity, manager, _, bridge, ws, streams, _ = live
    turn, owner = await start(live)
    await finish(live, owner, turn)
    reader = bridge._retained_task
    await entity.coordinator.async_shutdown()
    assert ws.closed and reader.done() and not streams
    assert manager.active_session_id is None


async def test_independent_wakes_reconnect_with_stable_partition_and_instance(live):
    from test_qwen_realtime import Socket

    _, _, _, _, first, _, client = live
    turn, owner = await start(live)
    await finish(live, owner, turn, text="完成。")
    second = Socket()
    client.ws_connect.return_value = second
    live = (*live[:4], second, *live[5:])
    turn, owner = await start(live, SESSION_2)
    await finish(live, owner, turn, text="完成。", tid="t2", rid="r2")
    assert client.ws_connect.await_count == 2
    assert all(
        "sessionId=entry" in c.args[0] for c in client.ws_connect.await_args_list
    )
    assert first.sent[0]["client"]["instance_id"] == "tivoo-entry"
    assert second.sent[0]["client"]["instance_id"] == "tivoo-entry"
    assert first.closed and second.closed


async def test_different_entry_uses_separate_gateway_partition(setup_bridge):
    from test_qwen_realtime import Socket, pcm

    old_bridge, _, _, adapter, streams, client = setup_bridge
    ws = Socket(session_id="other-entry")
    client.ws_connect.return_value = ws
    bridge = qwen.QwenRealtimeBridge(old_bridge.hass, adapter, streams, "other-entry")
    owner = bridge.create_turn(SESSION_1, "fresh-context", current=lambda: True)
    task = asyncio.create_task(bridge.async_run(owner, pcm(), lambda _: None))
    await response(ws)
    await spin_until(lambda: owner.playback_id is not None)
    await consume(owner)
    bridge.on_playback(owner.playback_id, "completed")
    await task
    assert "sessionId=other-entry" in client.ws_connect.call_args.args[0]
    assert ws.sent[0]["client"]["instance_id"] == "tivoo-other-entry"


async def test_occupied_owner_never_uploads_audio(setup_bridge):
    from test_qwen_realtime import Socket, pcm

    bridge, owner, _, _, streams, client = setup_bridge

    class Occupied(Socket):
        async def send_json(self, event):
            self.sent.append(event)
            if event["type"] == "session.hello":
                self.feed({"type": "error", "code": "client_occupied"})

    ws = Occupied()
    client.ws_connect.return_value = ws
    with pytest.raises(RuntimeError):
        await bridge.async_run(owner, pcm(), lambda _: None)
    assert not any(e["type"] == "input_audio_buffer.append" for e in ws.sent)
    assert client.ws_connect.await_count == 1 and ws.closed and not streams


async def test_parallel_tools_keep_tool_display_until_all_complete(live):
    entity, _, _, _, ws, _, _ = live
    _, owner = await start(live)
    await response(ws, tool=True)
    for call_id in ("c1", "c2"):
        ws.feed(
            {
                "type": "tool.call",
                "turnId": "t1",
                "responseId": "r1",
                "callId": call_id,
                "status": "running",
            }
        )
    await spin_until(lambda: len(owner.tools) == 2)
    ws.feed(
        {
            "type": "tool.call",
            "turnId": "t1",
            "responseId": "r1",
            "callId": "c1",
            "status": "completed",
        }
    )
    await spin_until(lambda: owner.tools["c1"][1] == "completed")
    assert DisplayState.TOOLUSE in entity.coordinator.display._intents
    ws.feed(
        {
            "type": "tool.call",
            "turnId": "t1",
            "responseId": "r1",
            "callId": "c2",
            "status": "completed",
        }
    )
    await spin_until(lambda: owner.tools["c2"][1] == "completed")
    assert DisplayState.TOOLUSE not in entity.coordinator.display._intents


@pytest.mark.parametrize("speech_uptime,accepted", [(5000, True), (5001, False)])
async def test_followup_speech_uses_existing_four_second_gate(
    live, speech_uptime, accepted
):
    _entity, manager, _, _bridge, ws, _, client = live
    turn, owner = await start(live)
    await finish(live, owner, turn)
    payload = local_start(SESSION_2, 101)
    payload.pop("wake_word_phrase")
    payload.update(trigger_source="local_followup", parent_session_id=SESSION_1)
    await manager.async_start_session(payload, persistent=True, local_mode=True)
    await spin_until(lambda: manager._active_session.ready)
    await manager.async_handle_gate(gate(SESSION_2))
    await manager.async_handle_activity(
        {**activity("speech_start", SESSION_2), "uptime_ms": speech_uptime}
    )
    assert (manager.active_session_id == SESSION_2) is accepted
    if not accepted:
        await spin_until(lambda: ws.closed)
    assert client.ws_connect.await_count == 1


async def test_retained_network_disconnect_revokes_grant(live):
    from types import SimpleNamespace

    from aiohttp import WSMsgType

    _, manager, _, _, ws, _, _ = live
    turn, owner = await start(live)
    await finish(live, owner, turn)
    ws.incoming.put_nowait(SimpleNamespace(type=WSMsgType.CLOSED, data=None))
    await spin_until(lambda: manager.active_session_id is None)
    assert ws.closed and manager._followup_grant is None
