"""Persistent Tivoo Satellite turns on the HA event loop."""

import asyncio
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from custom_components.tivoo.assist_satellite import TivooAssistSatellite
from custom_components.tivoo.audio_session import AudioSessionManager
from custom_components.tivoo.display_state import (
    DisplayState,
    ExpressionCoordinator,
    build_expression_command,
)
from homeassistant.components import tts
from homeassistant.components.assist_pipeline.models import (
    PipelineEvent,
    PipelineStage,
)
from homeassistant.components.assist_pipeline.models import (
    PipelineEventType as Event,
)
from homeassistant.components.assist_pipeline.vad import VoiceCommandSegmenter
from homeassistant.setup import async_setup_component
from mutagen.mp3 import MP3
from pytest_homeassistant.common import async_fire_time_changed
from test_audio_session import SESSION_1, SESSION_2, _start_payload
from test_display_state import RecordingAdapter


@pytest.fixture
async def satellite(hass):
    stop = AsyncMock()
    manager = AudioSessionManager(stop)
    adapter = SimpleNamespace(
        async_send_tts_play=AsyncMock(), register_playback_handler=Mock()
    )
    display = ExpressionCoordinator(RecordingAdapter())
    await display.async_start()
    entity = TivooAssistSatellite("test-entry", manager, adapter, display)
    entity.hass = hass
    entity.async_write_ha_state = Mock()
    await entity.async_added_to_hass()
    await manager.async_start_session(_start_payload(), persistent=True)
    yield entity, manager, stop
    await manager.async_shutdown()
    await entity.async_will_remove_from_hass()
    await display.async_shutdown()


async def activity(manager, state, session_id=SESSION_1):
    await manager.async_handle_activity(
        {"session_id": session_id, "state": state, "uptime_ms": 1}
    )


async def tick(hass, seconds):
    from homeassistant.util import dt

    async_fire_time_changed(hass, dt.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


@pytest.fixture
def advance_clock(hass, monkeypatch):
    """Advance HA's actual timer handles on a cumulative monotonic timeline."""
    real_time = hass.loop.time
    offset = 0.0
    monkeypatch.setattr(hass.loop, "time", lambda: real_time() + offset)

    async def advance(seconds):
        nonlocal offset
        offset += seconds
        await asyncio.sleep(0)
        await hass.async_block_till_done()

    return advance


async def test_upload_survives_run_end_and_starts_followup_after_playback(
    hass, satellite, monkeypatch, advance_clock
):
    entity, manager, stop = satellite
    adapter = entity.adapter
    monkeypatch.setattr(
        "custom_components.tivoo.audio_resource.get_url",
        lambda *args, **kwargs: "http://ha",
    )
    turns = asyncio.Queue()
    first_done = asyncio.Event()

    watcher_closed = asyncio.Queue()

    async def detect(audio, wake_word_id):
        try:
            await anext(audio)
            await asyncio.Future()
        finally:
            watcher_closed.put_nowait(wake_word_id)

    monkeypatch.setattr(
        entity,
        "wake_word_provider",
        lambda _pipeline_id: (
            SimpleNamespace(async_process_audio_stream=detect),
            "tivoo-wake",
        ),
    )

    async def pipeline(audio, start_stage, *, context):
        await turns.put((start_stage, await anext(audio)))
        if start_stage == PipelineStage.WAKE_WORD:
            entity.on_pipeline_event(
                PipelineEvent(
                    Event.WAKE_WORD_END,
                    {"wake_word_output": {"wake_word_id": "tivoo-wake"}},
                )
            )
        entity.on_pipeline_event(PipelineEvent(Event.STT_START))
        entity.on_pipeline_event(PipelineEvent(Event.STT_VAD_START))
        entity.on_pipeline_event(PipelineEvent(Event.TTS_START))
        entity.on_pipeline_event(
            PipelineEvent(
                Event.TTS_END,
                {
                    "tts_output": {
                        "url": "/api/tts_proxy/test.mp3",
                        "mime_type": "audio/mpeg",
                    }
                },
            )
        )
        entity.on_pipeline_event(PipelineEvent(Event.RUN_END))
        first_done.set()

    monkeypatch.setattr(entity, "async_accept_pipeline_from_satellite", pipeline)
    await activity(manager, "speech_start")
    await manager.async_push_pcm(SESSION_1, b"one!")
    assert await asyncio.wait_for(turns.get(), 1) == (PipelineStage.WAKE_WORD, b"one!")
    await first_done.wait()
    await hass.async_block_till_done()
    first_id = adapter.async_send_tts_play.await_args.args[0]

    await tick(hass, 30)
    await activity(manager, "speech_end")
    await activity(manager, "speech_start")
    assert turns.empty()
    assert manager.active_session_id == SESSION_1
    stop.assert_not_awaited()

    entity.coordinator.on_playback(first_id, "resource_ready")
    await tick(hass, 30)
    stop.assert_not_awaited()
    entity.coordinator.on_playback(first_id, "completed")
    assert await asyncio.wait_for(watcher_closed.get(), 1) == "tivoo-wake"
    await advance_clock(7.9)
    stop.assert_not_awaited()
    await activity(manager, "speech_start")
    await manager.async_push_pcm(SESSION_1, b"two!")
    assert await asyncio.wait_for(turns.get(), 1) == (PipelineStage.STT, b"two!")
    await hass.async_block_till_done()
    second_id = adapter.async_send_tts_play.await_args.args[0]
    assert second_id != first_id
    entity.coordinator.on_playback(first_id, "completed")
    await tick(hass, 30)
    stop.assert_not_awaited()

    entity.coordinator.on_playback(second_id, "completed")
    assert await asyncio.wait_for(watcher_closed.get(), 1) == "tivoo-wake"
    await advance_clock(7.9)
    stop.assert_not_awaited()
    await advance_clock(0.2)
    stop.assert_awaited_once_with(SESSION_1, "followup_timeout")
    assert manager.active_session_id is None
    await manager.async_push_pcm(SESSION_1, b"old!")
    assert manager.queue_size == 0
    await manager.async_start_session(_start_payload(SESSION_2), persistent=True)
    await activity(manager, "speech_start", SESSION_2)
    await manager.async_push_pcm(SESSION_2, b"new!")
    assert await asyncio.wait_for(turns.get(), 1) == (PipelineStage.WAKE_WORD, b"new!")


@pytest.mark.parametrize(
    ("events", "reason"),
    [
        (
            [(1, "speech_end"), (2, "speech_start"), (1, "speech_end"), (2.9, None)],
            "wake_miss",
        ),
        (
            [(10, "speech_end"), (2, "speech_start"), (2.9, None)],
            "wake_candidate_timeout",
        ),
        (
            [(4, Event.WAKE_WORD_END), (2, Event.STT_START), (2.9, None)],
            "command_timeout",
        ),
    ],
    ids=["wake_miss", "wake_candidate_timeout", "command_timeout"],
)
async def test_stage_watchdogs(satellite, monkeypatch, advance_clock, events, reason):
    entity, manager, stop = satellite
    running = asyncio.Event()
    closed = asyncio.Event()

    async def pipeline(audio, start_stage, *, context):
        assert start_stage == PipelineStage.WAKE_WORD
        running.set()
        try:
            await asyncio.Future()
        finally:
            closed.set()

    monkeypatch.setattr(entity, "async_accept_pipeline_from_satellite", pipeline)
    await activity(manager, "speech_start")
    await asyncio.wait_for(running.wait(), 1)
    for seconds, event in events:
        await advance_clock(seconds)
        stop.assert_not_awaited()
        if event is Event.WAKE_WORD_END:
            entity.on_pipeline_event(
                PipelineEvent(
                    Event.WAKE_WORD_END,
                    {"wake_word_output": {"wake_word_id": "tivoo-wake"}},
                )
            )
        elif event is Event.STT_START:
            entity.on_pipeline_event(PipelineEvent(event))
        elif event is not None:
            await activity(manager, event)
    await advance_clock(0.2)
    await asyncio.wait_for(closed.wait(), 1)
    stop.assert_awaited_once_with(SESSION_1, reason)


async def test_production_entity_passes_mp3_to_ha_pipeline(
    hass, satellite, monkeypatch
):
    entity, manager, _ = satellite
    from pytest_homeassistant.common import MockConfigEntry

    entity.platform = SimpleNamespace(config_entry=MockConfigEntry(domain="tivoo"))
    entity.registry_entry = None
    entity.entity_id = "assist_satellite.tivoo"
    upstream = AsyncMock()
    monkeypatch.setattr(
        "homeassistant.components.assist_satellite.entity.async_pipeline_from_audio_stream",
        upstream,
    )
    async with manager.audio_subscription(SESSION_1) as audio:
        await entity.async_accept_pipeline_from_satellite(
            audio, PipelineStage.WAKE_WORD
        )
    assert upstream.await_args.kwargs["tts_audio_output"] == {
        "preferred_format": "mp3",
        "preferred_sample_rate": 32000,
        "preferred_sample_channels": 1,
    }
    assert upstream.await_args.kwargs["audio_settings"].silence_seconds == 0.7


async def test_production_tts_contract_real_ffmpeg_outputs_32k_mono_mp3(
    hass, satellite
):
    """The production Satellite options must drive HA's real FFmpeg conversion."""
    entity, _, _ = satellite
    assert await async_setup_component(hass, "ffmpeg", {})

    async def matcha_pcm():
        # Matcha/Wyoming production audio is 22.05 kHz, 16-bit, mono PCM.
        yield b"\x00\x00" * (22050 // 4)

    options = entity._attr_tts_options
    converted = tts._async_convert_audio(
        hass,
        None,
        matcha_pcm(),
        to_extension=options["preferred_format"],
        to_sample_rate=options["preferred_sample_rate"],
        to_sample_channels=options["preferred_sample_channels"],
        from_pcm_format=tts.PcmFormat(22050, 2, 1),
    )
    mp3 = b"".join([chunk async for chunk in converted])
    info = MP3(BytesIO(mp3)).info

    assert mp3
    assert info.sample_rate == 32000
    assert info.channels == 1


def test_ha_command_segmentation_defaults():
    segmenter = VoiceCommandSegmenter()
    assert (
        segmenter.speech_seconds,
        segmenter.command_seconds,
        segmenter.silence_seconds,
        segmenter.timeout_seconds,
    ) == (0.3, 1.0, 0.7, 15.0)


async def test_long_reply_does_not_pin_stt_cursor(hass, satellite, monkeypatch):
    entity, manager, stop = satellite
    processing = asyncio.Event()
    release = asyncio.Event()

    async def pipeline(audio, start_stage, *, context):
        await anext(audio)
        entity.on_pipeline_event(
            PipelineEvent(
                Event.WAKE_WORD_END,
                {"wake_word_output": {"wake_word_id": "tivoo-wake"}},
            )
        )
        entity.on_pipeline_event(PipelineEvent(Event.STT_START))
        entity.on_pipeline_event(PipelineEvent(Event.STT_VAD_START))
        entity.on_pipeline_event(PipelineEvent(Event.STT_VAD_END))
        processing.set()
        await release.wait()

    monkeypatch.setattr(entity, "async_accept_pipeline_from_satellite", pipeline)
    await activity(manager, "speech_start")
    await manager.async_push_pcm(SESSION_1, bytes(640))
    await asyncio.wait_for(processing.wait(), 1)
    for _ in range(800):
        await manager.async_push_pcm(SESSION_1, bytes(640))
    await tick(hass, 30)
    assert manager.active_session_id == SESSION_1
    assert manager.queue_size == 750
    stop.assert_not_awaited()
    release.set()


async def test_reconnect_waits_for_cancelled_pipeline_cleanup(satellite, monkeypatch):
    entity, manager, stop = satellite
    first_running = asyncio.Event()
    first_closing = asyncio.Event()
    release = asyncio.Event()
    received = asyncio.Queue()

    async def pipeline(audio, start_stage, *, context):
        if not first_running.is_set():
            first_running.set()
            try:
                await asyncio.Future()
            finally:
                first_closing.set()
                await release.wait()
        else:
            await received.put(await anext(audio))
            await asyncio.Future()

    monkeypatch.setattr(entity, "async_accept_pipeline_from_satellite", pipeline)
    await activity(manager, "speech_start")
    await asyncio.wait_for(first_running.wait(), 1)
    try:
        await manager.async_disconnect()
        await asyncio.wait_for(first_closing.wait(), 1)
        await manager.async_start_session(_start_payload(), persistent=True)
        await activity(manager, "speech_start")
        await manager.async_push_pcm(SESSION_1, b"new!")
        await asyncio.sleep(0)
        assert received.empty()
        await manager.async_disconnect()
        await manager.async_start_session(_start_payload(), persistent=True)
        await activity(manager, "speech_start")
        await manager.async_push_pcm(SESSION_1, b"next")
        for _ in range(5):
            await asyncio.sleep(0)
        assert received.empty()
    finally:
        release.set()

    assert await asyncio.wait_for(received.get(), 1) == b"next"
    stop.assert_not_awaited()


async def test_disconnect_closes_tts_after_pipeline_return(
    hass, satellite, monkeypatch
):
    entity, manager, stop = satellite
    sent = asyncio.Event()
    owner = SimpleNamespace(async_cancel=AsyncMock())
    monkeypatch.setattr(
        "custom_components.tivoo.audio_resource.PipelineTtsOwner.for_stream",
        lambda stream: owner,
    )
    monkeypatch.setattr(
        "custom_components.tivoo.audio_resource.tts.async_get_stream",
        lambda hass, token: object(),
    )
    monkeypatch.setattr(
        "custom_components.tivoo.audio_resource.get_url",
        lambda *args, **kwargs: "http://ha",
    )

    async def send(*args):
        sent.set()

    entity.adapter.async_send_tts_play.side_effect = send

    async def pipeline(audio, start_stage, *, context):
        entity.on_pipeline_event(
            PipelineEvent(
                Event.RUN_START,
                {
                    "tts_output": {
                        "token": "token",
                        "url": "/api/tts_proxy/test.mp3",
                        "mime_type": "audio/mpeg",
                    }
                },
            )
        )
        entity.on_pipeline_event(PipelineEvent(Event.STT_VAD_START))
        entity.on_pipeline_event(PipelineEvent(Event.TTS_END))
        entity.on_pipeline_event(PipelineEvent(Event.RUN_END))

    monkeypatch.setattr(entity, "async_accept_pipeline_from_satellite", pipeline)
    await activity(manager, "speech_start")
    await asyncio.wait_for(sent.wait(), 1)
    await hass.async_block_till_done(wait_background_tasks=True)
    owner.async_cancel.assert_not_awaited()
    await manager.async_disconnect()
    await entity.async_will_remove_from_hass()
    owner.async_cancel.assert_awaited_once()
    stop.assert_not_awaited()


@pytest.mark.parametrize(
    ("phase", "command_started"),
    [
        ("stt", True),
        ("before_plain", True),
        ("after_plain", True),
        ("tts_generation", True),
        ("playback", True),
        ("playback", False),
    ],
)
async def test_confirmed_wake_replaces_active_turn(
    hass, satellite, monkeypatch, advance_clock, phase, command_started
):
    from homeassistant.components.wake_word import DetectionResult

    entity, manager, stop = satellite
    events = asyncio.Queue()
    hit = asyncio.Event()
    cleanup = asyncio.Event()
    entity.adapter.async_send_message = AsyncMock()
    monkeypatch.setattr(
        "custom_components.tivoo.audio_resource.get_url",
        lambda *args, **kwargs: "http://ha",
    )

    async def detect(audio, wake_word_id):
        assert wake_word_id == "tivoo-wake"
        pre, first_offset = await anext(audio)
        command, timestamp = await anext(audio)
        assert timestamp - first_offset == len(pre)
        await events.put(("watcher", pre, command))
        await hit.wait()
        return DetectionResult(wake_word_id, "Tivoo", timestamp, [(command, timestamp)])

    pipeline_lookup = Mock(
        return_value=SimpleNamespace(
            wake_word_entity="wake_word.sherpa", wake_word_id="tivoo-wake"
        )
    )
    provider_lookup = Mock(
        return_value=SimpleNamespace(async_process_audio_stream=detect)
    )
    monkeypatch.setattr(
        "custom_components.tivoo.assist_satellite.async_get_pipeline", pipeline_lookup
    )
    monkeypatch.setattr(
        "homeassistant.components.wake_word.async_get_wake_word_detection_entity",
        provider_lookup,
    )

    async def pipeline(audio, stage, *, context):
        await events.put(stage)
        if stage == PipelineStage.STT:
            entity.on_pipeline_event(PipelineEvent(Event.STT_START))
            await events.put(tuple([await anext(audio) for _ in range(3)]))
            if command_started:
                entity.on_pipeline_event(PipelineEvent(Event.STT_VAD_START))
            await asyncio.Future()
        entity.on_pipeline_event(
            PipelineEvent(
                Event.RUN_START,
                {
                    "pipeline": "astrbot",
                    "tts_output": {
                        "url": "/api/tts_proxy/test.mp3",
                        "mime_type": "audio/mpeg",
                        "stream_response": True,
                    },
                },
            )
        )
        entity.on_pipeline_event(
            PipelineEvent(
                Event.WAKE_WORD_END,
                {
                    "wake_word_output": {"wake_word_id": "tivoo-wake"},
                },
            )
        )
        entity.on_pipeline_event(PipelineEvent(Event.STT_START))
        entity.on_pipeline_event(PipelineEvent(Event.STT_VAD_START))
        if phase != "stt":
            entity.on_pipeline_event(PipelineEvent(Event.STT_END))
            entity.on_pipeline_event(PipelineEvent(Event.INTENT_START))
        if phase in ("after_plain", "tts_generation", "playback"):
            entity.on_pipeline_event(
                PipelineEvent(
                    Event.INTENT_PROGRESS,
                    {
                        "chat_log_delta": {"content": "partial"},
                    },
                )
            )
        if phase in ("tts_generation", "playback"):
            entity.on_pipeline_event(PipelineEvent(Event.TTS_START))
        if phase == "playback":
            entity.on_pipeline_event(
                PipelineEvent(Event.INTENT_PROGRESS, {"tts_start_streaming": True})
            )
        try:
            await asyncio.Future()
        finally:
            await events.put("closing")
            await cleanup.wait()

    monkeypatch.setattr(entity, "async_accept_pipeline_from_satellite", pipeline)
    await activity(manager, "speech_start")
    try:
        assert await asyncio.wait_for(events.get(), 1) == PipelineStage.WAKE_WORD
        await hass.async_block_till_done()
        old_id = None
        if phase == "playback":
            entity.adapter.async_send_tts_play.assert_awaited_once()
            old_id = entity.adapter.async_send_tts_play.await_args.args[0]
            entity.coordinator.on_playback(old_id, "playing")
        else:
            entity.adapter.async_send_tts_play.assert_not_awaited()
        await manager.async_push_pcm(SESSION_1, b"pr" * 321)
        await activity(manager, "speech_end")
        await activity(manager, "speech_start")
        await manager.async_push_pcm(SESSION_1, b"go" * 320)
        assert await asyncio.wait_for(events.get(), 1) == (
            "watcher",
            b"pr" * 321,
            b"go" * 320,
        )
        assert events.empty()
        pipeline_lookup.assert_called_once_with(hass, "astrbot")
        provider_lookup.assert_called_once_with(hass, "wake_word.sherpa")
        await advance_clock(6)
        assert events.empty()
        stop.assert_not_awaited()
        entity.adapter.async_send_message.assert_not_awaited()
        hit.set()
        assert await asyncio.wait_for(events.get(), 1) == "closing"
        if old_id:
            import json

            from custom_components.tivoo.diagnostics import TYPE_AUDIO_STOP

            message_type, payload = entity.adapter.async_send_message.await_args.args
            assert message_type == TYPE_AUDIO_STOP
            assert json.loads(payload)["expected_audio_id"] == old_id
            entity.coordinator.on_playback(old_id, "failed")
        else:
            entity.adapter.async_send_message.assert_not_awaited()
        await manager.async_push_pcm(SESSION_1, b"on" * 320)
        await advance_clock(6)
        assert events.empty()
        stop.assert_not_awaited()
    finally:
        cleanup.set()

    assert await asyncio.wait_for(events.get(), 1) == PipelineStage.STT
    await hass.async_block_till_done()
    assert entity.display.desired_state is DisplayState.WAKE_CONFIRMED
    assert await asyncio.wait_for(events.get(), 1) == (
        b"pr" * 321,
        b"go" * 320,
        b"on" * 320,
    )
    await advance_clock(4.9)
    stop.assert_not_awaited()
    await advance_clock(0.2)
    if command_started:
        stop.assert_not_awaited()
    else:
        stop.assert_awaited_once_with(SESSION_1, "command_timeout")


async def test_watcher_lifetime_and_successive_interrupts(hass, satellite, monkeypatch):
    from homeassistant.components.wake_word import DetectionResult

    entity, manager, stop = satellite
    turns = asyncio.Queue()
    watchers = asyncio.Queue()
    hits = asyncio.Queue()

    async def detect(audio, wake_word_id):
        await watchers.put(audio)
        return await hits.get()

    monkeypatch.setattr(
        entity,
        "wake_word_provider",
        lambda _pipeline_id: (
            SimpleNamespace(async_process_audio_stream=detect),
            "tivoo-wake",
        ),
    )

    async def pipeline(audio, stage, *, context):
        await turns.put(stage)
        if stage == PipelineStage.WAKE_WORD:
            await anext(audio)
            entity.on_pipeline_event(
                PipelineEvent(
                    Event.WAKE_WORD_END,
                    {
                        "wake_word_output": {"wake_word_id": "tivoo-wake"},
                    },
                )
            )
        entity.on_pipeline_event(PipelineEvent(Event.STT_START))
        entity.on_pipeline_event(PipelineEvent(Event.STT_START))
        entity.on_pipeline_event(PipelineEvent(Event.STT_VAD_START))
        await asyncio.Future()

    monkeypatch.setattr(entity, "async_accept_pipeline_from_satellite", pipeline)
    await activity(manager, "speech_start")
    assert await asyncio.wait_for(turns.get(), 1) == PipelineStage.WAKE_WORD
    assert watchers.empty()
    await manager.async_push_pcm(SESSION_1, bytes(640))
    await asyncio.wait_for(watchers.get(), 1)

    for _ in range(2):
        await hits.put(DetectionResult("tivoo-wake", "Tivoo", None))
        assert await asyncio.wait_for(turns.get(), 1) == PipelineStage.STT
        await asyncio.wait_for(watchers.get(), 1)
        assert turns.empty()
        assert watchers.empty()

    await hits.put(None)
    await asyncio.wait_for(watchers.get(), 2)
    assert turns.empty()
    stop.assert_not_awaited()
    await hits.put(DetectionResult("tivoo-wake", "Tivoo", None))
    assert await asyncio.wait_for(turns.get(), 1) == PipelineStage.STT


async def test_voice_display_context_kws_stt_playback_and_followup(
    hass, satellite, monkeypatch
):
    entity, manager, stop = satellite
    display = entity.display
    turns = asyncio.Queue()
    first_released = asyncio.Event()

    async def pipeline(audio, stage, *, context):
        await turns.put((stage, context))
        if stage == PipelineStage.WAKE_WORD:
            await first_released.wait()
        else:
            await asyncio.Future()

    monkeypatch.setattr(entity, "async_accept_pipeline_from_satellite", pipeline)
    await activity(manager, "speech_start")
    stage, context = await asyncio.wait_for(turns.get(), 1)
    assert stage == PipelineStage.WAKE_WORD
    assert context.id == display.active_generation
    entity.on_pipeline_event(PipelineEvent(Event.STT_START))
    await hass.async_block_till_done()
    assert display.desired_state is DisplayState.IDLE
    entity.on_pipeline_event(
        PipelineEvent(
            Event.WAKE_WORD_END, {"wake_word_output": {"wake_word_id": "tivoo-wake"}}
        )
    )
    await hass.async_block_till_done()
    assert display.desired_state is DisplayState.WAKE_CONFIRMED
    entity.on_pipeline_event(PipelineEvent(Event.STT_VAD_START))
    entity.on_pipeline_event(PipelineEvent(Event.STT_END, {"stt_output": {"text": ""}}))
    await hass.async_block_till_done()
    assert display.desired_state is DisplayState.IDLE
    entity.on_pipeline_event(
        PipelineEvent(Event.STT_END, {"stt_output": {"text": "开灯"}})
    )
    await hass.async_block_till_done()
    assert display.desired_state is DisplayState.THINKING
    entity.on_pipeline_event(PipelineEvent(Event.TTS_START))
    entity.on_pipeline_event(PipelineEvent(Event.TTS_END))
    await hass.async_block_till_done()
    assert display.desired_state is DisplayState.THINKING

    # Simulate the playback ID generated by the real TTS resource owner.
    entity.coordinator._turn.tts._manager.playback_id = "current"
    entity.coordinator.on_playback("other", "playing")
    assert display.desired_state is DisplayState.THINKING
    entity.coordinator.on_playback("current", "playing")
    await hass.async_block_till_done()
    assert display.desired_state is DisplayState.SPEAKING
    entity.coordinator.on_playback("current", "completed")
    await hass.async_block_till_done()
    assert display.desired_state is DisplayState.FOLLOWUP_WAIT
    first_released.set()
    await hass.async_block_till_done()

    await activity(manager, "speech_start")
    stage2, context2 = await asyncio.wait_for(turns.get(), 1)
    assert stage2 == PipelineStage.STT
    assert context2.id != context.id
    assert display.active_generation == context2.id
    await hass.async_block_till_done()
    assert display.desired_state is DisplayState.ACTIVE_LISTENING
    entity.coordinator.on_playback("current", "playing")
    await hass.async_block_till_done()
    assert display.desired_state is DisplayState.ACTIVE_LISTENING
    await manager.async_disconnect()
    await hass.async_block_till_done()
    assert display.active_generation is None
    assert display.desired_state is DisplayState.IDLE
    stop.assert_not_awaited()


async def test_voice_display_failed_stt_error_and_old_generation_are_isolated(
    hass, satellite, monkeypatch
):
    entity, manager, _ = satellite
    display = entity.display
    turns = asyncio.Queue()

    async def pipeline(audio, stage, *, context):
        await turns.put((stage, context))
        await asyncio.Future()

    monkeypatch.setattr(entity, "async_accept_pipeline_from_satellite", pipeline)
    await activity(manager, "speech_start")
    _, old_context = await asyncio.wait_for(turns.get(), 1)
    entity.on_pipeline_event(PipelineEvent(Event.STT_VAD_START))
    entity.on_pipeline_event(
        PipelineEvent(Event.STT_END, {"stt_output": {"text": " "}})
    )
    await hass.async_block_till_done()
    assert display.desired_state is not DisplayState.THINKING
    # A superseding turn makes old callbacks ineffective even if queued.
    display.begin_generation("new-turn")
    await display.async_set_intent(
        DisplayState.SPEAKING, build_expression_command("music"), generation="new-turn"
    )
    await display.async_end_generation(old_context.id)
    await hass.async_block_till_done()
    assert display.desired_state is DisplayState.SPEAKING


async def test_satellite_platform_reuses_runtime_display(hass):
    from custom_components.tivoo.assist_satellite import async_setup_entry
    from custom_components.tivoo.const import DOMAIN

    display = ExpressionCoordinator(RecordingAdapter())
    ingress = AudioSessionManager(AsyncMock())
    adapter = SimpleNamespace()
    hass.data.setdefault(DOMAIN, {})["entry"] = {
        "display_coordinator": display,
        "audio_session_manager": ingress,
        "connection_adapter": adapter,
    }
    add = Mock()
    await async_setup_entry(hass, SimpleNamespace(entry_id="entry"), add)
    entity = add.call_args.args[0][0]
    assert entity.display is display
    assert entity.coordinator.display is display
    assert entity.coordinator.ingress is ingress
    hass.data[DOMAIN].pop("entry")
    if not hass.data[DOMAIN]:
        hass.data.pop(DOMAIN)


async def test_satellite_first_speech_candidate_uses_display_hold_and_cooldown(
    hass, satellite, monkeypatch
):
    import custom_components.tivoo.display_state as module

    entity, manager, _ = satellite
    monkeypatch.setattr(module.random, "random", lambda: 0.0)
    monkeypatch.setattr(module, "CANDIDATE_HOLD_SECONDS", 0.03)
    monkeypatch.setattr(module, "CANDIDATE_COOLDOWN_SECONDS", 0.2)
    started = asyncio.Event()

    async def pipeline(audio, stage, *, context):
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(entity, "async_accept_pipeline_from_satellite", pipeline)
    await activity(manager, "speech_start")
    await asyncio.wait_for(started.wait(), 1)
    await asyncio.sleep(0.015)
    assert entity.display.desired_state is DisplayState.IDLE
    await asyncio.sleep(0.045)
    assert entity.display.desired_state is DisplayState.ACTIVE_LISTENING
    await activity(manager, "speech_end")
    await hass.async_block_till_done()
    assert entity.display.desired_state is DisplayState.IDLE
    await activity(manager, "speech_start")
    await asyncio.sleep(0.045)
    assert entity.display.desired_state is DisplayState.IDLE
    entity.on_pipeline_event(
        PipelineEvent(
            Event.WAKE_WORD_END, {"wake_word_output": {"wake_word_id": "tivoo-wake"}}
        )
    )
    await hass.async_block_till_done()
    assert entity.display.desired_state is DisplayState.WAKE_CONFIRMED
    entity.on_pipeline_event(PipelineEvent(Event.ERROR))
    await hass.async_block_till_done()
    assert entity.display.active_generation is None
    assert entity.display.desired_state is DisplayState.IDLE


async def test_astrbot_tool_phase_matches_live_satellite_context_and_restores_thinking(
    hass, satellite, monkeypatch
):
    entity, manager, _ = satellite
    entity.entity_id = "assist_satellite.tivoo"
    turns = asyncio.Queue()

    async def pipeline(audio, stage, *, context):
        await turns.put(context)
        await asyncio.Future()

    monkeypatch.setattr(entity, "async_accept_pipeline_from_satellite", pipeline)
    await activity(manager, "speech_start")
    first = await asyncio.wait_for(turns.get(), 1)
    entity.on_pipeline_event(PipelineEvent(Event.STT_VAD_START))
    entity.on_pipeline_event(
        PipelineEvent(Event.STT_END, {"stt_output": {"text": "天气"}})
    )
    await hass.async_block_till_done()
    assert entity.display.desired_state is DisplayState.THINKING

    def phase(kind, satellite_id="assist_satellite.tivoo", context_id=None):
        hass.bus.async_fire(
            "astrbot_phase",
            {
                "satellite_id": satellite_id,
                "context_id": first.id if context_id is None else context_id,
                "phase": kind,
            },
        )

    phase("tool_call", satellite_id="assist_satellite.not_tivoo")
    phase("tool_call", context_id="old-context")
    await hass.async_block_till_done()
    assert entity.display.desired_state is DisplayState.THINKING
    phase("tool_call")
    await hass.async_block_till_done()
    assert entity.display.desired_state is DisplayState.TOOLUSE
    phase("tool_call_result")
    await hass.async_block_till_done()
    assert entity.display.desired_state is DisplayState.THINKING
    phase("tool_call")
    await hass.async_block_till_done()
    entity.coordinator._turn.tts._manager.playback_id = "playing"
    entity.coordinator.on_playback("playing", "playing")
    await hass.async_block_till_done()
    assert entity.display.desired_state is DisplayState.SPEAKING

    # Session ended: delayed phase cannot reintroduce a session intent.
    await manager.async_disconnect()
    await hass.async_block_till_done()
    phase("tool_call")
    await hass.async_block_till_done()
    assert entity.display.desired_state is DisplayState.IDLE
    assert entity.display.active_generation is None


async def test_astrbot_phase_old_context_cannot_modify_new_generation(
    hass, satellite, monkeypatch
):
    entity, manager, _ = satellite
    entity.entity_id = "assist_satellite.tivoo"
    started = asyncio.Event()

    async def pipeline(audio, stage, *, context):
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(entity, "async_accept_pipeline_from_satellite", pipeline)
    await activity(manager, "speech_start")
    await asyncio.wait_for(started.wait(), 1)
    old = entity.coordinator._turn.context.id
    entity.display.begin_generation("new-context")
    await entity.display.async_set_intent(
        DisplayState.THINKING,
        build_expression_command("thinking"),
        generation="new-context",
    )
    hass.bus.async_fire(
        "astrbot_phase",
        {
            "satellite_id": "assist_satellite.tivoo",
            "context_id": old,
            "phase": "tool_call",
        },
    )
    await hass.async_block_till_done()
    assert entity.display.desired_state is DisplayState.THINKING
    assert entity.display.active_generation == "new-context"
