"""Tests for P6 HA TTS Proxy URL generation and Pipeline event dispatch."""

import asyncio
from types import SimpleNamespace

import pytest
from custom_components.tivoo.audio_resource import (
    TtsResourceManager,
    build_internal_tts_url,
    create_pipeline_event_callback,
)
from homeassistant.components.assist_pipeline.models import (
    PipelineEvent,
    PipelineEventType,
)
from homeassistant.exceptions import HomeAssistantError

TTS_URL_1 = "/api/tts_proxy/opaque-fake-token-1"
TTS_URL_2 = "/api/tts_proxy/opaque-fake-token-2"
INTERNAL_URL = "http://ha-internal.local:8123"


@pytest.fixture(autouse=True)
def _set_default_internal_url(hass):
    hass.config.internal_url = INTERNAL_URL


class _TtsAdapter:
    def __init__(self):
        self.sent = []

    async def async_send_tts_play(self, playback_id, url, mime_type):
        self.sent.append(
            {"playback_id": playback_id, "url": url, "mime_type": mime_type}
        )


def _event(event_type, data=None):
    return PipelineEvent(event_type, data)


def _tts_output(url=TTS_URL_1, stream_response=False):
    return {
        "url": url,
        "mime_type": "audio/mpeg",
        "stream_response": stream_response,
    }


async def test_build_internal_tts_url_prefers_configured_internal_url(hass):
    hass.config.internal_url = INTERNAL_URL
    hass.config.external_url = "https://cloud.example.invalid:8123"

    assert build_internal_tts_url(hass, TTS_URL_1) == INTERNAL_URL + TTS_URL_1


async def test_build_internal_tts_url_falls_back_to_detected_lan_ip(hass):
    hass.config.internal_url = None
    hass.config.external_url = "https://cloud.example.invalid:8123"
    hass.config.api = SimpleNamespace(local_ip="192.168.3.94", port=8123, use_ssl=False)

    assert (
        build_internal_tts_url(hass, TTS_URL_1)
        == "http://192.168.3.94:8123" + TTS_URL_1
    )


async def test_build_internal_tts_url_fails_without_an_internal_address(hass):
    hass.config.internal_url = None
    hass.config.external_url = "https://cloud.example.invalid:8123"
    hass.config.api = None

    with pytest.raises(HomeAssistantError, match="internal Home Assistant URL"):
        build_internal_tts_url(hass, TTS_URL_1)


@pytest.mark.parametrize(
    "value",
    [
        "https://cloud.example.invalid/api/tts_proxy/fake-token",
        "//cloud.example.invalid/api/tts_proxy/fake-token",
        "/api/config/core",
        "/api/tts_proxy/",
    ],
)
async def test_build_internal_tts_url_rejects_non_proxy_or_absolute_urls(hass, value):
    hass.config.internal_url = INTERNAL_URL

    with pytest.raises(HomeAssistantError):
        build_internal_tts_url(hass, value)


async def test_streaming_pipeline_sends_before_tts_end_only_once(hass):
    adapter = _TtsAdapter()
    manager = TtsResourceManager(hass, adapter)

    await manager.async_handle_pipeline_event(
        _event(
            PipelineEventType.RUN_START,
            {"tts_output": _tts_output(stream_response=True)},
        )
    )
    assert adapter.sent == []

    await manager.async_handle_pipeline_event(
        _event(PipelineEventType.INTENT_PROGRESS, {"tts_start_streaming": True})
    )
    assert len(adapter.sent) == 1
    sent = adapter.sent[0]
    assert sent["url"] == INTERNAL_URL + TTS_URL_1
    assert sent["mime_type"] == "audio/mpeg"
    assert sent["playback_id"]

    await manager.async_handle_pipeline_event(
        _event(PipelineEventType.TTS_END, {"tts_output": _tts_output()})
    )
    assert adapter.sent == [sent]


async def test_non_streaming_pipeline_sends_only_at_tts_end(hass):
    adapter = _TtsAdapter()
    manager = TtsResourceManager(hass, adapter)

    await manager.async_handle_pipeline_event(
        _event(PipelineEventType.RUN_START, {"tts_output": _tts_output()})
    )
    await manager.async_handle_pipeline_event(
        _event(PipelineEventType.INTENT_PROGRESS, {"tts_start_streaming": True})
    )
    assert adapter.sent == []

    await manager.async_handle_pipeline_event(
        _event(PipelineEventType.TTS_END, {"tts_output": _tts_output()})
    )
    assert len(adapter.sent) == 1
    assert adapter.sent[0]["url"] == INTERNAL_URL + TTS_URL_1


async def test_each_pipeline_run_gets_a_new_playback_id_and_url(hass):
    adapter = _TtsAdapter()
    manager = TtsResourceManager(hass, adapter)

    await manager.async_handle_pipeline_event(
        _event(
            PipelineEventType.RUN_START,
            {"tts_output": _tts_output(stream_response=True)},
        )
    )
    await manager.async_handle_pipeline_event(
        _event(PipelineEventType.INTENT_PROGRESS, {"tts_start_streaming": True})
    )
    first = adapter.sent[0]

    await manager.async_handle_pipeline_event(
        _event(
            PipelineEventType.RUN_START, {"tts_output": _tts_output(TTS_URL_2, True)}
        )
    )
    await manager.async_handle_pipeline_event(
        _event(PipelineEventType.INTENT_PROGRESS, {"tts_start_streaming": True})
    )

    second = adapter.sent[1]
    assert second["playback_id"] != first["playback_id"]
    assert second["url"] == INTERNAL_URL + TTS_URL_2


async def test_tts_end_can_send_when_run_start_has_no_audio_metadata(hass):
    adapter = _TtsAdapter()
    manager = TtsResourceManager(hass, adapter)

    await manager.async_handle_pipeline_event(
        _event(PipelineEventType.RUN_START, {"conversation_id": "run-with-late-tts"})
    )
    await manager.async_handle_pipeline_event(
        _event(PipelineEventType.TTS_END, {"tts_output": _tts_output()})
    )

    assert len(adapter.sent) == 1
    assert adapter.sent[0]["url"] == INTERNAL_URL + TTS_URL_1


async def test_pipeline_callback_factory_schedules_the_per_run_manager(hass):
    adapter = _TtsAdapter()
    callback = create_pipeline_event_callback(hass, adapter)

    callback(
        _event(
            PipelineEventType.RUN_START,
            {"tts_output": _tts_output(stream_response=True)},
        )
    )
    callback(_event(PipelineEventType.INTENT_PROGRESS, {"tts_start_streaming": True}))
    await hass.async_block_till_done()

    assert len(adapter.sent) == 1
    assert adapter.sent[0]["url"] == INTERNAL_URL + TTS_URL_1


async def test_stream_start_and_tts_end_race_still_send_only_once(hass):
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowAdapter(_TtsAdapter):
        async def async_send_tts_play(self, playback_id, url, mime_type):
            self.sent.append(
                {"playback_id": playback_id, "url": url, "mime_type": mime_type}
            )
            if len(self.sent) == 1:
                started.set()
                await release.wait()

    adapter = SlowAdapter()
    manager = TtsResourceManager(hass, adapter)
    await manager.async_handle_pipeline_event(
        _event(
            PipelineEventType.RUN_START,
            {"tts_output": _tts_output(stream_response=True)},
        )
    )

    first_send = asyncio.create_task(
        manager.async_handle_pipeline_event(
            _event(PipelineEventType.INTENT_PROGRESS, {"tts_start_streaming": True})
        )
    )
    await started.wait()
    await manager.async_handle_pipeline_event(
        _event(PipelineEventType.TTS_END, {"tts_output": _tts_output()})
    )
    release.set()
    await first_send

    assert len(adapter.sent) == 1


async def test_missing_internal_url_does_not_send_tts_play(hass):
    hass.config.internal_url = None
    hass.config.api = None
    adapter = _TtsAdapter()
    manager = TtsResourceManager(hass, adapter)
    await manager.async_handle_pipeline_event(
        _event(PipelineEventType.RUN_START, {"tts_output": _tts_output()})
    )

    with pytest.raises(HomeAssistantError, match="internal Home Assistant URL"):
        await manager.async_handle_pipeline_event(
            _event(PipelineEventType.TTS_END, {"tts_output": _tts_output()})
        )

    assert adapter.sent == []


async def test_pipeline_callback_logs_tts_failure_without_proxy_token(hass, caplog):
    hass.config.internal_url = None
    hass.config.api = None
    adapter = _TtsAdapter()
    callback = create_pipeline_event_callback(hass, adapter)

    callback(_event(PipelineEventType.RUN_START, {"tts_output": _tts_output()}))
    callback(_event(PipelineEventType.TTS_END, {"tts_output": _tts_output()}))
    await hass.async_block_till_done()

    assert "Unable to send TTS resource to ESP32" in caplog.text
    assert "opaque-fake-token-1" not in caplog.text
    assert adapter.sent == []
