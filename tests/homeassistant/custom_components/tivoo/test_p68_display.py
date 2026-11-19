"""T08: local display events are scoped to the physical command lifecycle."""
import asyncio

import pytest
from homeassistant.components.assist_pipeline.models import PipelineEvent, PipelineEventType as Event
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from custom_components.tivoo.display_state import DisplayState, ExpressionCoordinator, build_expression_command
from custom_components.tivoo.transport import Esp32ConnectionAdapter
from test_assist_satellite import satellite, advance_clock
from test_audio_session import SESSION_1, SESSION_2
from test_display_state import RecordingAdapter
from test_p68_lifecycle import followup
from test_p68_local_session import local_start, gate, activity
from test_services import _loaded_entry, MemoryCommandAdapter


async def start_local(hass, satellite, monkeypatch):
    entity, manager, stop = satellite
    await manager.async_end_session(SESSION_1, "test")
    monkeypatch.setattr(entity, "validate_local_pipeline", lambda: ("select.test", "local"))
    entered = asyncio.Queue()
    async def run(audio, stage, *, context, wake_word_phrase):
        entity.on_pipeline_event(PipelineEvent(Event.STT_START))
        entered.put_nowait(context)
        async for _ in audio:
            pass
        await asyncio.Future()
    monkeypatch.setattr(entity, "async_accept_pipeline_from_satellite", run)
    await manager.async_start_session(local_start(), persistent=True, local_mode=True)
    await asyncio.wait_for(entered.get(), 1)
    await hass.async_block_till_done()
    return entity, manager, entered


async def wait_ready(entity):
    for _ in range(100):
        if entity.adapter.async_send_message.await_count:
            return
        await asyncio.sleep(0)
    pytest.fail("STT was not ready")


async def speech(entity, manager, session=SESSION_1):
    await wait_ready(entity)
    await manager.async_handle_gate(gate(session))
    await manager.async_handle_activity(activity("speech_start", session))


async def endpoint(manager, session=SESSION_1):
    await manager.async_push_pcm(session, b"x"*640)
    await manager.async_handle_activity(activity("speech_end", session, pcm_samples=320))
    # A provider's STT_END is legal only after the consumer reaches EOF.
    # Wait for the real iterator, not just the wire speech_end.
    for _ in range(100):
        if manager.local_input_drained(session):
            return
        await asyncio.sleep(0)
    pytest.fail("local audio iterator did not drain")


@pytest.mark.parametrize("text", ["command", " "])
async def test_physical_wake_listen_endpoint_and_stt(hass, satellite, monkeypatch, text):
    entity, manager, _ = await start_local(hass, satellite, monkeypatch)
    display = entity.display
    explicit = build_expression_command("fish")
    await display.async_set_explicit(explicit)
    assert display.desired_state is DisplayState.WAKE_CONFIRMED
    await speech(entity, manager)
    await hass.async_block_till_done()
    assert display.desired_state is DisplayState.ACTIVE_LISTENING
    await endpoint(manager)
    await hass.async_block_till_done()
    assert display.desired_state is DisplayState.EXPLICIT_CONTENT
    entity.on_pipeline_event(PipelineEvent(Event.STT_END, {"stt_output":{"text":text}}))
    await hass.async_block_till_done()
    assert display.desired_state is (DisplayState.THINKING if text.strip() else DisplayState.EXPLICIT_CONTENT)
    await manager.async_disconnect()
    await hass.async_block_till_done()
    assert display.desired_command == explicit


async def test_followup_wait_only_at_gate_and_terminal_removes_speaking(hass, satellite, monkeypatch):
    entity, manager, entered = await start_local(hass, satellite, monkeypatch)
    display = entity.display
    await speech(entity, manager)
    await endpoint(manager)
    entity.on_pipeline_event(PipelineEvent(Event.STT_END, {"stt_output":{"text":"command"}}))
    entity.coordinator._turn.tts._manager.playback_id = "reply"
    entity.coordinator.on_playback("reply","buffering")
    await hass.async_block_till_done()
    assert display.desired_state is DisplayState.THINKING
    entity.coordinator.on_playback("reply","playing")
    await hass.async_block_till_done()
    assert display.desired_state is DisplayState.SPEAKING
    entity.coordinator.on_playback("reply","completed")
    entity.coordinator.on_playback("reply","playing")
    await hass.async_block_till_done()
    assert display.desired_state is not DisplayState.SPEAKING
    assert manager.grant_followup(SESSION_1)
    await manager.async_start_session(followup(), persistent=True, local_mode=True)
    await asyncio.wait_for(entered.get(),1)
    await hass.async_block_till_done()
    assert display.desired_state is DisplayState.IDLE
    await manager.async_handle_gate(gate(SESSION_2))
    await hass.async_block_till_done()
    assert display.desired_state is DisplayState.FOLLOWUP_WAIT
    await manager.async_handle_activity(activity("speech_start",SESSION_2))
    await hass.async_block_till_done()
    assert display.desired_state is DisplayState.ACTIVE_LISTENING


async def test_mood_rejects_known_old_context_but_preserves_manual_schema(hass, enable_custom_integrations):
    _, runtime = await _loaded_entry(hass)
    runtime["command_adapter"] = MemoryCommandAdapter()
    display = runtime["display_coordinator"]
    old, current = Context(), Context()
    display.begin_generation(old.id)
    display.begin_generation(current.id)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("tivoo","set_mood",{"name":"happy"},blocking=True,context=old)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("tivoo","set_mood",{"name":"happy"},blocking=True,context=Context(parent_id=old.id))
    await hass.services.async_call("tivoo","set_mood",{"name":"happy"},blocking=True,context=current)
    assert display.desired_state is DisplayState.AI_MOOD


async def test_local_mood_requires_valid_stt_reply(hass, satellite, monkeypatch):
    entity, manager, _ = await start_local(hass, satellite, monkeypatch)
    with pytest.raises(HomeAssistantError):
        await entity.display.async_set_mood("happy")
    await speech(entity, manager)
    await endpoint(manager)
    entity.on_pipeline_event(PipelineEvent(Event.STT_END, {"stt_output":{"text":"command"}}))
    await hass.async_block_till_done()
    await entity.display.async_set_mood("happy")


async def test_spp_reconnect_does_not_wait_for_slow_screen_write():
    from unittest.mock import Mock

    adapter = Esp32ConnectionAdapter("127.0.0.1", "11:75:58:97:49:98")
    adapter.states["control"] = "connected"
    adapter._writers["control"] = Mock(is_closing=Mock(return_value=False))
    output = RecordingAdapter()
    display = ExpressionCoordinator(output)
    await display.async_start()
    await display.async_on_spp_state("spp_disconnected")
    entered, release = asyncio.Event(), asyncio.Event()
    async def slow(command):
        entered.set()
        await release.wait()
    output.async_execute = slow
    adapter.register_spp_state_handler(display.async_on_spp_state)
    notification = asyncio.create_task(adapter._notify_spp_state("spp_connected","11:75:58:97:49:98"))
    try:
        await asyncio.wait_for(entered.wait(),1)
        assert notification.done(), "display I/O blocked diagnostic RX"
    finally:
        release.set()
        await notification
        adapter._writers.clear()
        await adapter.async_stop()
        await display.async_shutdown()


async def test_tool_phase_ends_at_intent_end_and_old_context_cannot_change_winner(hass, satellite, monkeypatch):
    entity, manager, entered = await start_local(hass, satellite, monkeypatch)
    entity.entity_id = "assist_satellite.tivoo"
    old = entity.coordinator._turn.context.id
    def phase(kind, ctx=old, satellite_id=entity.entity_id):
        hass.bus.async_fire("astrbot_phase", {
            "phase": kind, "context_id": ctx, "satellite_id": satellite_id,
        })
    phase("tool_call")
    await hass.async_block_till_done()
    assert entity.display.desired_state is DisplayState.WAKE_CONFIRMED
    await speech(entity, manager)
    await endpoint(manager)
    entity.on_pipeline_event(PipelineEvent(Event.STT_END, {"stt_output":{"text":"command"}}))
    phase("tool_call", satellite_id="assist_satellite.other")
    phase("tool_call", ctx="old")
    await hass.async_block_till_done()
    assert entity.display.desired_state is DisplayState.THINKING
    phase("tool_call")
    await hass.async_block_till_done()
    assert entity.display.desired_state is DisplayState.TOOLUSE
    entity.on_pipeline_event(PipelineEvent(Event.INTENT_END, {"intent_output":{"response":{"response_type":"action_done"}}}))
    await hass.async_block_till_done()
    assert entity.display.desired_state is DisplayState.THINKING
    phase("tool_call")  # Late tool event for same Context after intent completion.
    await hass.async_block_till_done()
    assert entity.display.desired_state is DisplayState.THINKING
    await manager.async_start_session(local_start(SESSION_2,101), persistent=True, local_mode=True)
    await asyncio.wait_for(entered.get(),1)
    phase("tool_call_result")
    entity.coordinator.on_playback("old","playing")
    await hass.async_block_till_done()
    assert entity.display.desired_state is DisplayState.WAKE_CONFIRMED


async def test_slow_power_write_does_not_send_before_latest_power():
    output = RecordingAdapter()
    display = ExpressionCoordinator(output)
    await display.async_start()
    started, release = asyncio.Event(), asyncio.Event()
    send = output.async_execute
    async def slow(command):
        if command.name == "set_screen_power" and command.data["value"] is False:
            started.set()
            await release.wait()
        await send(command)
    output.async_execute = slow
    output.commands.clear()
    off = asyncio.create_task(display.async_acquire_screen_off("night"))
    await asyncio.wait_for(started.wait(),1)
    on = asyncio.create_task(display.async_release_screen_off("night"))
    await asyncio.sleep(0)
    display.begin_generation("new", wake=True)
    release.set()
    await asyncio.gather(off, on)
    try:
        assert [cmd.name for cmd in output.commands[:2]] == ["set_screen_power","set_screen_power"]
        assert output.powers == [False, True]
        assert all(cmd.data["name"] == "question" for cmd in output.displays)
    finally:
        await display.async_shutdown()


async def test_pending_recompute_cannot_write_after_unload():
    output = RecordingAdapter()
    display = ExpressionCoordinator(output)
    await display.async_start()
    started, release = asyncio.Event(), asyncio.Event()
    send = output.async_execute
    async def slow(command):
        started.set()
        await release.wait()
        await send(command)
    output.async_execute = slow
    display.begin_generation("one", wake=True)
    await asyncio.wait_for(started.wait(),1)
    display.begin_generation("two")
    queued = asyncio.create_task(display.async_force_recompute())
    await asyncio.sleep(0)
    await display.async_shutdown()
    release.set()
    await queued
    assert len(output.commands) == 2  # Initial idle + already in-flight question only.


async def test_local_off_survives_wake_replacement_reconnect_and_expiry(
    hass, satellite, monkeypatch, advance_clock
):
    entity, manager, entered = await start_local(hass, satellite, monkeypatch)
    display = entity.display
    output = display._adapter
    await display.async_set_explicit(build_expression_command("fish"))
    await display.async_acquire_screen_off("night")
    await display.async_set_screen_power(False)
    output.commands.clear()
    await speech(entity, manager)
    await endpoint(manager)
    entity.on_pipeline_event(PipelineEvent(Event.STT_END, {"stt_output":{"text":"command"}}))
    await hass.async_block_till_done()
    old = display.active_generation
    await display.async_set_mood("happy", context_id=old)
    await manager.async_start_session(local_start(SESSION_2,101), persistent=True, local_mode=True)
    await asyncio.wait_for(entered.get(),1)
    await display.async_on_spp_state("spp_disconnected")
    await display.async_on_spp_state("spp_connected")
    assert output.powers == [False]
    assert output.displays == []
    assert display.desired_state is DisplayState.WAKE_CONFIRMED
    await advance_clock(5.1)
    assert display.desired_state is DisplayState.WAKE_CONFIRMED
    await display.async_set_screen_power(True)  # Does not release night owner.
    assert output.displays == []
    await display.async_temporary_wake("preview", .5)
    assert output.powers[-1] is True
    assert output.displays[-1].data["name"] == "question"
    await advance_clock(.6)
    # Timer callback creates a separate task; allow that task to run.
    for _ in range(20):
        if output.powers[-1] is False:
            break
        await asyncio.sleep(0)
    assert output.powers[-1] is False
    await manager.async_disconnect()
    await hass.async_block_till_done()
    await display.async_release_screen_off("night")
    assert output.displays[-1].data["name"] == "fish"


async def test_new_runtime_waits_for_validated_spp_and_reasserts_off():
    from unittest.mock import Mock
    adapter = Esp32ConnectionAdapter("127.0.0.1", "11:75:58:97:49:98")
    adapter.states["control"] = "connected"
    output = RecordingAdapter()
    display = ExpressionCoordinator(output, spp_connected=False)
    adapter.register_spp_state_handler(display.async_on_spp_state)
    async def join_notifications():
        await asyncio.gather(*adapter._spp_state_tasks)
    try:
        await display.async_start()
        assert output.commands == []
        await adapter._notify_spp_state("spp_connected", "00:11:22:33:44:55")
        await join_notifications()
        assert output.commands == []
        # Connected state alone is not sufficient without an active writer.
        await adapter._notify_spp_state("spp_connected", "11:75:58:97:49:98")
        await join_notifications()
        assert output.commands == []
        writer = Mock()
        writer.is_closing.return_value = True
        adapter._writers["control"] = writer
        await adapter._notify_spp_state("spp_connected", "11:75:58:97:49:98")
        await join_notifications()
        assert output.commands == []
        writer.is_closing.return_value = False
        await adapter._notify_spp_state("spp_connected", "11:75:58:97:49:98")
        await join_notifications()
        assert len(output.displays) == 1
        await display.async_set_screen_power(False)
        await adapter._notify_spp_state("spp_disconnected")
        await adapter._notify_spp_state("spp_connected", "11:75:58:97:49:98")
        await join_notifications()
        assert output.powers == [False, False]
        assert len(output.displays) == 1
    finally:
        adapter._writers.clear()
        await adapter.async_stop()
        await display.async_shutdown()


async def test_mood_is_not_accepted_after_physical_reply_terminal(hass, satellite, monkeypatch):
    entity, manager, _ = await start_local(hass, satellite, monkeypatch)
    await speech(entity, manager)
    await endpoint(manager)
    entity.on_pipeline_event(PipelineEvent(Event.STT_END, {"stt_output":{"text":"command"}}))
    turn = entity.coordinator._turn
    turn.tts._manager.playback_id = "reply"
    entity.coordinator.on_playback("reply","playing")
    entity.coordinator.on_playback("reply","completed")
    with pytest.raises(HomeAssistantError):
        await entity.display.async_set_mood("happy", context_id=turn.context.id)


async def test_ha_reload_initial_sync_uses_new_runtime_default_gate(
    hass, enable_custom_integrations, monkeypatch
):
    from unittest.mock import AsyncMock, Mock
    from pytest_homeassistant.common import MockConfigEntry

    # Exercise real HA platform/runtime load and reload without real network.
    monkeypatch.setattr(Esp32ConnectionAdapter, "async_start", AsyncMock())
    entry = MockConfigEntry(
        domain="tivoo", title="Tivoo", unique_id="tivoo",
        data={"esp32_host":"127.0.0.1","tivoo_bluetooth_mac":"11:75:58:97:49:98"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)

    async def sync_runtime():
        runtime = hass.data["tivoo"][entry.entry_id]
        display = runtime["display_coordinator"]
        output = MemoryCommandAdapter()
        runtime["command_adapter"] = output
        connection = runtime["connection_adapter"]
        assert display.last_sent is None
        connection.states["control"] = "connected"
        connection._writers["control"] = Mock(
            is_closing=Mock(return_value=False), wait_closed=AsyncMock()
        )
        await connection._notify_spp_state("spp_connected","11:75:58:97:49:98")
        await asyncio.gather(*connection._spp_state_tasks)
        return display, output

    try:
        old, output = await sync_runtime()
        await old.async_set_screen_power(False)
        assert output.commands[-1].name == "set_screen_power"
        assert output.commands[-1].data["value"] is False
        old.begin_generation("old", wake=True)
        assert await hass.config_entries.async_reload(entry.entry_id)
        new, output = await sync_runtime()
        assert old._shutdown and new is not old
        assert new.active_generation is None
        assert new.desired_state is DisplayState.IDLE
        assert output.commands[-1].name == "set_expression"
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
