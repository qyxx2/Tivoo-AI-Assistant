"""Persistent Tivoo Satellite turns on the HA event loop."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from custom_components.tivoo.assist_satellite import TivooAssistSatellite
from custom_components.tivoo.audio_session import AudioSessionManager
from homeassistant.components.assist_pipeline.models import (
    PipelineEvent,
    PipelineStage,
)
from homeassistant.components.assist_pipeline.models import (
    PipelineEventType as Event,
)
from homeassistant.components.assist_pipeline.vad import VoiceCommandSegmenter
from pytest_homeassistant.common import async_fire_time_changed
from test_audio_session import SESSION_1, _start_payload


@pytest.fixture
async def satellite(hass):
    stop = AsyncMock()
    manager = AudioSessionManager(stop)
    adapter = SimpleNamespace(
        async_send_tts_play=AsyncMock(), register_playback_handler=Mock()
    )
    entity = TivooAssistSatellite("test-entry", manager, adapter)
    entity.hass = hass
    entity.async_write_ha_state = Mock()
    await entity.async_added_to_hass()
    await manager.async_start_session(_start_payload(), persistent=True)
    yield entity, manager, stop
    await manager.async_shutdown()
    await entity.async_will_remove_from_hass()


async def activity(manager, state):
    await manager.async_handle_activity(
        {"session_id": SESSION_1, "state": state, "uptime_ms": 1}
    )


async def tick(hass, seconds):
    from homeassistant.util import dt

    async_fire_time_changed(hass, dt.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def test_upload_survives_run_end_and_starts_followup_after_playback(
    hass, satellite, monkeypatch
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

    async def pipeline(audio, start_stage):
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
    await tick(hass, 9)
    stop.assert_awaited_once_with(SESSION_1, "followup_timeout")


@pytest.mark.parametrize(
    ("events", "seconds", "reason"),
    [
        (["speech_end"], 4, "wake_miss"),
        (["speech_end", "speech_start"], 16, "wake_candidate_timeout"),
        (["detected"], 6, "command_timeout"),
    ],
)
async def test_stage_watchdogs(hass, satellite, monkeypatch, events, seconds, reason):
    entity, manager, stop = satellite
    running = asyncio.Event()
    closed = asyncio.Event()

    async def pipeline(audio, start_stage):
        running.set()
        try:
            await asyncio.Future()
        finally:
            closed.set()

    monkeypatch.setattr(entity, "async_accept_pipeline_from_satellite", pipeline)
    await activity(manager, "speech_start")
    await asyncio.wait_for(running.wait(), 1)
    for event in events:
        if event == "detected":
            entity.on_pipeline_event(
                PipelineEvent(
                    Event.WAKE_WORD_END,
                    {"wake_word_output": {"wake_word_id": "tivoo-wake"}},
                )
            )
        else:
            await activity(manager, event)
    await tick(hass, seconds)
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

    async def pipeline(audio, start_stage):
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

    async def pipeline(audio, start_stage):
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

    async def pipeline(audio, start_stage):
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


@pytest.mark.parametrize("phase", ["stt", "before_plain", "after_plain", "playback"])
async def test_confirmed_wake_replaces_active_turn(hass, satellite, monkeypatch, phase):
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

    async def pipeline(audio, stage):
        await events.put(stage)
        if stage == PipelineStage.STT:
            entity.on_pipeline_event(PipelineEvent(Event.STT_START))
            await events.put(tuple([await anext(audio) for _ in range(3)]))
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
        if phase in ("after_plain", "playback"):
            entity.on_pipeline_event(
                PipelineEvent(
                    Event.INTENT_PROGRESS,
                    {
                        "chat_log_delta": {"content": "partial"},
                    },
                )
            )
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
        entity.adapter.async_send_message.assert_not_awaited()
        old_id = (
            entity.adapter.async_send_tts_play.await_args.args[0]
            if phase == "playback"
            else None
        )
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
        await tick(hass, 6)
        assert events.empty()
        stop.assert_not_awaited()
    finally:
        cleanup.set()

    assert await asyncio.wait_for(events.get(), 1) == PipelineStage.STT
    assert await asyncio.wait_for(events.get(), 1) == (
        b"pr" * 321,
        b"go" * 320,
        b"on" * 320,
    )


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

    async def pipeline(audio, stage):
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
