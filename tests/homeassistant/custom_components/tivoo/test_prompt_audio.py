"""P6.7b1 prompt playback owner and physical-output arbitration."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from custom_components.tivoo.diagnostics import TYPE_AUDIO_STOP
from custom_components.tivoo.prompt_audio import (
    PROMPT_FILENAMES,
    PromptSoundPlayer,
    build_internal_prompt_url,
)
from homeassistant.exceptions import HomeAssistantError

INTERNAL_URL = "http://ha-internal.local:8123"


class _Adapter:
    def __init__(self):
        self.sent = []
        self.messages = []

    async def async_send_tts_play(
        self, playback_id, url, mime_type, *, suppress_vad=False
    ):
        self.sent.append(
            {
                "playback_id": playback_id,
                "url": url,
                "mime_type": mime_type,
                "suppress_vad": suppress_vad,
            }
        )

    async def async_send_message(self, message_type, payload):
        self.messages.append((message_type, json.loads(payload)))


@pytest.fixture(autouse=True)
def _set_internal_url(hass):
    hass.config.internal_url = INTERNAL_URL


@pytest.fixture(autouse=True)
def _clean_prompt_files(hass):
    root = Path(hass.config.path("www", "tivoo", "prompts"))
    for name in PROMPT_FILENAMES:
        (root / name).unlink(missing_ok=True)
    yield
    for name in PROMPT_FILENAMES:
        (root / name).unlink(missing_ok=True)


def _install(hass, *names):
    root = Path(hass.config.path("www", "tivoo", "prompts"))
    root.mkdir(parents=True, exist_ok=True)
    for name in names or PROMPT_FILENAMES:
        (root / name).write_bytes(b"prompt")
    return root


async def test_prompt_url_is_fixed_to_local_prompt_assets(hass):
    assert build_internal_prompt_url(hass, "ready_01.mp3") == (
        INTERNAL_URL + "/local/tivoo/prompts/ready_01.mp3"
    )

    for invalid in (
        "../ready_01.mp3",
        "/local/tivoo/prompts/ready_01.mp3",
        "ready_04.mp3",
        "https://example.invalid/ready_01.mp3",
    ):
        with pytest.raises(HomeAssistantError):
            build_internal_prompt_url(hass, invalid)


async def test_request_deduplicates_generation_and_never_repeats_adjacent_asset(
    hass, monkeypatch
):
    _install(hass)
    adapter = _Adapter()
    monkeypatch.setattr(
        "custom_components.tivoo.prompt_audio.random.choice", lambda values: values[0]
    )
    player = PromptSoundPlayer(hass, adapter)

    assert await player.async_request("g1") is True
    assert await player.async_request("g1") is False
    first = adapter.sent[-1]
    assert first["url"].endswith("/ready_01.mp3")
    assert first["mime_type"] == "audio/mpeg"
    assert first["suppress_vad"] is True

    player.on_playback(first["playback_id"], "completed")
    assert await player.async_request("g2") is True
    second = adapter.sent[-1]
    assert second["url"].endswith("/ready_02.mp3")
    assert second["playback_id"] != first["playback_id"]


async def test_missing_assets_and_prompt_send_failure_are_silent(hass):
    adapter = _Adapter()
    player = PromptSoundPlayer(hass, adapter)

    assert await player.async_request("missing") is False
    assert adapter.sent == []

    _install(hass, "ready_01.mp3")
    adapter.async_send_tts_play = AsyncMock(
        side_effect=HomeAssistantError("diagnostic disconnected")
    )
    assert await player.async_request("send-failed") is False
    assert player.playback_id is None


async def test_single_remaining_asset_is_not_repeated_on_adjacent_generation(
    hass, monkeypatch
):
    _install(hass, "ready_01.mp3")
    adapter = _Adapter()
    monkeypatch.setattr(
        "custom_components.tivoo.prompt_audio.random.choice", lambda values: values[0]
    )
    player = PromptSoundPlayer(hass, adapter)

    assert await player.async_request("g1") is True
    player.on_playback(adapter.sent[-1]["playback_id"], "completed")
    assert await player.async_request("g2") is False
    assert len(adapter.sent) == 1


async def test_new_generation_stops_old_prompt_and_stale_cancel_cannot_touch_new(
    hass, monkeypatch
):
    _install(hass)
    adapter = _Adapter()
    monkeypatch.setattr(
        "custom_components.tivoo.prompt_audio.random.choice", lambda values: values[0]
    )
    player = PromptSoundPlayer(hass, adapter, release_timeout=1)

    assert await player.async_request("g1") is True
    old_id = adapter.sent[-1]["playback_id"]

    next_request = asyncio.create_task(player.async_request("g2"))
    await asyncio.sleep(0)
    assert len(adapter.sent) == 1
    assert adapter.messages[-1][0] == TYPE_AUDIO_STOP
    assert adapter.messages[-1][1]["expected_audio_id"] == old_id

    assert player.on_playback(old_id, "stopped") is True
    assert await next_request is True
    new_id = adapter.sent[-1]["playback_id"]
    assert new_id != old_id

    before = list(adapter.messages)
    assert await player.async_cancel("g1") is False
    assert adapter.messages == before
    assert player.playback_id == new_id
    assert player.on_playback(old_id, "completed") is True
    assert player.playback_id == new_id


async def test_tts_prepare_stops_prompt_waits_for_release_and_blocks_new_prompt(hass):
    _install(hass)
    adapter = _Adapter()
    player = PromptSoundPlayer(hass, adapter, release_timeout=1)

    assert await player.async_request("g1") is True
    prompt_id = adapter.sent[-1]["playback_id"]
    tts_id = "11111111-1111-4111-8111-111111111111"

    prepare = asyncio.create_task(player.async_yield_to_tts(tts_id))
    await asyncio.sleep(0)
    assert not prepare.done()
    assert adapter.messages[-1][1]["expected_audio_id"] == prompt_id

    assert player.on_playback(prompt_id, "stopped") is True
    await prepare

    assert await player.async_request("g2") is False
    assert player.on_playback(tts_id, "playing") is False
    assert player.on_playback(tts_id, "completed") is False
    assert await player.async_request("g3") is True


async def test_existing_tts_owner_prevents_prompt_without_audio_busy_retry(hass):
    _install(hass)
    adapter = _Adapter()
    player = PromptSoundPlayer(hass, adapter)
    tts_id = "22222222-2222-4222-8222-222222222222"

    await player.async_yield_to_tts(tts_id)
    assert await player.async_request("g1") is False
    assert adapter.sent == []
    assert adapter.messages == []

    player.on_playback(tts_id, "failed")
    assert await player.async_request("g2") is True


async def test_prompt_release_timeout_is_quiet_and_does_not_block_real_tts(hass):
    _install(hass)
    adapter = _Adapter()
    player = PromptSoundPlayer(hass, adapter, release_timeout=0.01)

    assert await player.async_request("g1") is True
    await asyncio.wait_for(
        player.async_yield_to_tts("33333333-3333-4333-8333-333333333333"),
        timeout=0.2,
    )
    assert player.playback_id is None


async def test_missing_internal_url_skips_prompt_without_error(hass):
    hass.config.internal_url = None
    hass.config.external_url = "https://cloud.example.invalid:8123"
    hass.config.api = None
    _install(hass, "ready_01.mp3")
    adapter = _Adapter()
    player = PromptSoundPlayer(hass, adapter)

    assert await player.async_request("no-internal-url") is False
    assert adapter.sent == []
    assert player.playback_id is None


async def test_prompt_stop_send_failure_releases_owner_without_error(hass):
    _install(hass, "ready_01.mp3")
    adapter = _Adapter()
    player = PromptSoundPlayer(hass, adapter)

    assert await player.async_request("g1") is True
    adapter.async_send_message = AsyncMock(
        side_effect=HomeAssistantError("diagnostic disconnected")
    )

    assert await player.async_cancel("g1") is True
    assert player.playback_id is None
