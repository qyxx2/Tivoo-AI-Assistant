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
async def test_unavailable_production_adapter_fails_instead_of_reporting_success(
    hass, enable_custom_integrations, service, data
):
    await _loaded_entry(hass)

    with pytest.raises(HomeAssistantError, match="unavailable"):
        await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_unloaded_tivoo_service_is_not_callable(hass, enable_custom_integrations):
    entry, _ = await _loaded_entry(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "stop_countdown", {}, blocking=True
        )
