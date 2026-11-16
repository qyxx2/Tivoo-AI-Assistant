"""Tests for Tivoo service schemas and semantic command dispatch."""

import pytest
from homeassistant.exceptions import HomeAssistantError
from probatio.error import MultipleInvalid
from pytest_homeassistant.common import MockConfigEntry

DOMAIN = "tivoo"


class MemoryCommandAdapter:
    """Capture semantic commands without a device transport."""

    def __init__(self):
        self.commands = []

    async def async_execute(self, command):
        self.commands.append(command)


async def _loaded_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tivoo",
        data={"media_directory": "pixelart"},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    return entry, hass.data[DOMAIN][entry.entry_id]


async def test_stop_countdown_dispatches_a_parameterless_semantic_command(
    hass, enable_custom_integrations
):
    _, runtime = await _loaded_entry(hass)
    adapter = MemoryCommandAdapter()
    runtime["command_adapter"] = adapter

    await hass.services.async_call(DOMAIN, "stop_countdown", {}, blocking=True)

    assert len(adapter.commands) == 1
    assert adapter.commands[0].name == "stop_countdown"
    assert adapter.commands[0].data == {}


async def test_stop_countdown_rejects_unexpected_parameters(
    hass, enable_custom_integrations
):
    await _loaded_entry(hass)

    with pytest.raises(MultipleInvalid):
        await hass.services.async_call(
            DOMAIN, "stop_countdown", {"countdown": "00:30"}, blocking=True
        )


@pytest.mark.parametrize("volume", [0, 100])
async def test_set_volume_preserves_integer_boundaries(
    hass, enable_custom_integrations, volume
):
    _, runtime = await _loaded_entry(hass)
    adapter = MemoryCommandAdapter()
    runtime["command_adapter"] = adapter

    await hass.services.async_call(
        DOMAIN, "set_volume", {"volume": volume}, blocking=True
    )

    assert len(adapter.commands) == 1
    assert adapter.commands[0].name == "set_volume"
    assert adapter.commands[0].data == {"volume": volume}


@pytest.mark.parametrize("volume", [-1, 101, 1.5, "25", True])
async def test_set_volume_rejects_out_of_range_or_non_integer_values(
    hass, enable_custom_integrations, volume
):
    _, runtime = await _loaded_entry(hass)
    adapter = MemoryCommandAdapter()
    runtime["command_adapter"] = adapter

    with pytest.raises(MultipleInvalid):
        await hass.services.async_call(
            DOMAIN, "set_volume", {"volume": volume}, blocking=True
        )

    assert adapter.commands == []


async def test_set_volume_requires_volume(hass, enable_custom_integrations):
    await _loaded_entry(hass)

    with pytest.raises(MultipleInvalid):
        await hass.services.async_call(DOMAIN, "set_volume", {}, blocking=True)


@pytest.mark.parametrize(
    ("service", "data"),
    [("stop_countdown", {}), ("set_volume", {"volume": 50})],
)
async def test_production_adapter_rejects_commands_without_control_connection(
    hass, enable_custom_integrations, service, data
):
    await _loaded_entry(hass)

    with pytest.raises(HomeAssistantError, match="control channel"):
        await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_unloaded_tivoo_service_is_not_callable(hass, enable_custom_integrations):
    entry, _ = await _loaded_entry(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "stop_countdown", {}, blocking=True)


async def test_b1_runtime_sets_up_and_shuts_down_single_display_coordinator(
    hass, enable_custom_integrations
):
    entry, runtime = await _loaded_entry(hass)
    coordinator = runtime["display_coordinator"]
    assert coordinator.desired_state.value == "idle"
    assert coordinator is hass.data[DOMAIN][entry.entry_id]["display_coordinator"]
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert coordinator._shutdown is True


MOOD_NAMES = (
    "happy",
    "sad",
    "angry",
    "love",
    "cool",
    "cry",
    "laugh",
    "sleepy",
    "shock",
    "wink",
    "sick",
    "party",
    "kiss",
    "oops",
)


@pytest.mark.parametrize("name", MOOD_NAMES)
async def test_b4_set_mood_accepts_only_current_mood_presets(
    hass, enable_custom_integrations, name
):
    _, runtime = await _loaded_entry(hass)
    adapter = MemoryCommandAdapter()
    runtime["command_adapter"] = adapter
    coordinator = runtime["display_coordinator"]
    coordinator.begin_generation("mood-turn")
    await hass.async_block_till_done()
    adapter.commands.clear()

    await hass.services.async_call(DOMAIN, "set_mood", {"name": name}, blocking=True)

    assert coordinator.desired_state.value == "ai_mood"
    assert coordinator.desired_command.name == "set_expression"
    assert coordinator.desired_command.data["name"] == name
    if adapter.commands:
        assert adapter.commands[-1].data["name"] == name
    else:
        # The visible idle preset may already be the requested mood (notably
        # sleepy). In that case the coordinator correctly deduplicates the
        # identical display payload while still changing the winning intent.
        assert coordinator.last_sent == coordinator.desired_command


@pytest.mark.parametrize(
    "name", ["thinking", "tooluse", "question", "standby", "music", "fish", "unknown"]
)
async def test_b4_set_mood_rejects_system_and_unknown_presets(
    hass, enable_custom_integrations, name
):
    _, runtime = await _loaded_entry(hass)
    runtime["display_coordinator"].begin_generation("mood-turn")
    with pytest.raises(MultipleInvalid):
        await hass.services.async_call(
            DOMAIN, "set_mood", {"name": name}, blocking=True
        )


async def test_b4_set_mood_requires_active_generation(hass, enable_custom_integrations):
    _, runtime = await _loaded_entry(hass)
    adapter = MemoryCommandAdapter()
    runtime["command_adapter"] = adapter
    adapter.commands.clear()

    with pytest.raises(HomeAssistantError, match="active voice generation"):
        await hass.services.async_call(
            DOMAIN, "set_mood", {"name": "happy"}, blocking=True
        )
    assert adapter.commands == []


async def test_b1_replayable_service_is_gated_and_restored(
    hass, enable_custom_integrations
):
    _, runtime = await _loaded_entry(hass)
    adapter = MemoryCommandAdapter()
    runtime["command_adapter"] = adapter
    coordinator = runtime["display_coordinator"]
    await hass.services.async_call(
        DOMAIN, "set_screen_power", {"value": False}, blocking=True
    )
    await hass.services.async_call(DOMAIN, "show_text", {"value": "old"}, blocking=True)
    await hass.services.async_call(DOMAIN, "show_text", {"value": "new"}, blocking=True)
    assert [cmd.name for cmd in adapter.commands] == ["set_screen_power"]
    assert coordinator.desired_command.data["value"] == "new"
    await hass.services.async_call(
        DOMAIN, "set_screen_power", {"value": True}, blocking=True
    )
    assert [cmd.name for cmd in adapter.commands] == [
        "set_screen_power",
        "set_screen_power",
        "show_text",
    ]
    assert adapter.commands[-1].data["value"] == "new"


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("set_expression", {"name": "fish"}),
        ("show_clock", {"clock": 0}),
        ("set_light", {"brightness": 50}),
        ("show_lyrics", {}),
        ("show_scoreboard", {}),
        ("show_design", {"number": 0}),
        ("show_effects", {"number": 0}),
        ("show_visualization", {"number": 0}),
        ("show_game", {}),
    ],
)
async def test_b1_replayable_services_are_queued_while_off(
    hass, enable_custom_integrations, service, data
):
    _, runtime = await _loaded_entry(hass)
    adapter = MemoryCommandAdapter()
    runtime["command_adapter"] = adapter
    coordinator = runtime["display_coordinator"]
    await coordinator.async_acquire_screen_off("night")
    adapter.commands.clear()
    await hass.services.async_call(DOMAIN, service, data, blocking=True)
    assert adapter.commands == []
    assert coordinator.desired_command.name == service
    await coordinator.async_release_screen_off("night")
    assert [cmd.name for cmd in adapter.commands] == ["set_screen_power", service]


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("start_countdown", {"countdown": "00:30"}),
        ("stop_countdown", {}),
        ("set_timer", {"value": True}),
        ("set_noise_meter", {"value": True}),
        ("set_sleep_mode", {"value": True}),
        ("game_control", {"value": "up"}),
    ],
)
async def test_b1_screen_actions_are_rejected_while_off_not_deferred(
    hass, enable_custom_integrations, service, data
):
    _, runtime = await _loaded_entry(hass)
    adapter = MemoryCommandAdapter()
    runtime["command_adapter"] = adapter
    coordinator = runtime["display_coordinator"]
    await coordinator.async_acquire_screen_off("night")
    adapter.commands.clear()
    with pytest.raises(HomeAssistantError, match="screen is off"):
        await hass.services.async_call(DOMAIN, service, data, blocking=True)
    assert adapter.commands == []
    await coordinator.async_release_screen_off("night")
    assert not any(cmd.name == service for cmd in adapter.commands)


@pytest.mark.parametrize("service", ["show_image", "play_animation"])
async def test_b1_media_content_is_cached_off_and_replayed_on(
    hass, enable_custom_integrations, service
):
    from pathlib import Path

    from PIL import Image

    _, runtime = await _loaded_entry(hass)
    media_directory = Path(runtime["media_directory"])
    media_directory.mkdir(parents=True, exist_ok=True)
    image_path = media_directory / "b1.gif"
    Image.new("RGB", (16, 16), (110, 140, 180)).save(image_path, format="GIF")
    adapter = MemoryCommandAdapter()
    runtime["command_adapter"] = adapter
    coordinator = runtime["display_coordinator"]
    await coordinator.async_acquire_screen_off("night")
    adapter.commands.clear()
    await hass.services.async_call(DOMAIN, service, {"file": "b1.gif"}, blocking=True)
    assert adapter.commands == []
    assert coordinator.desired_command.name == service
    await coordinator.async_release_screen_off("night")
    assert [cmd.name for cmd in adapter.commands] == ["set_screen_power", service]
