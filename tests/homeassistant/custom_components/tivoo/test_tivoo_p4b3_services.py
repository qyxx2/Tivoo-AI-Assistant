"""P4b3 tests for Tivoo expression, text, countdown and brightness services."""

import pytest
from homeassistant.exceptions import HomeAssistantError
from probatio.error import MultipleInvalid
from pytest_homeassistant.common import MockConfigEntry

DOMAIN = "tivoo"


class MemoryCommandAdapter:
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


async def _adapter_for(hass):
    _, runtime = await _loaded_entry(hass)
    adapter = MemoryCommandAdapter()
    runtime["command_adapter"] = adapter
    return adapter


async def test_set_expression_renders_a_real_builtin_preset(
    hass, enable_custom_integrations
):
    adapter = await _adapter_for(hass)

    await hass.services.async_call(
        DOMAIN, "set_expression", {"name": "heart"}, blocking=True
    )

    command = adapter.commands[0]
    assert command.name == "set_expression"
    assert command.data["name"] == "heart"
    assert len(command.data["frames"]) == 4
    assert command.data["delays"] == [400, 300, 400, 300]
    assert all(
        len(frame) == 16 and all(len(row) == 16 for row in frame)
        for frame in command.data["frames"]
    )


@pytest.mark.parametrize("name", ["unknown-preset", "haiku", "../heart", ""])
async def test_set_expression_rejects_unknown_or_non_exposed_presets(
    hass, enable_custom_integrations, name
):
    adapter = await _adapter_for(hass)
    with pytest.raises(MultipleInvalid):
        await hass.services.async_call(
            DOMAIN, "set_expression", {"name": name}, blocking=True
        )
    assert adapter.commands == []


async def test_show_text_uses_packaged_renderer_and_default_style(
    hass, enable_custom_integrations
):
    adapter = await _adapter_for(hass)

    await hass.services.async_call(DOMAIN, "show_text", {"value": "Hi"}, blocking=True)

    command = adapter.commands[0]
    assert command.name == "show_text"
    assert command.data["value"] == "Hi"
    assert command.data["font"] == "unifont"
    assert command.data["speed"] == 100
    assert command.data["step"] == 2
    assert command.data["font_size"] is None
    assert len(command.data["frames"]) == len(command.data["delays"])
    assert command.data["delays"] and set(command.data["delays"]) == {100}
    assert all(
        len(frame) == 16 and all(len(row) == 16 for row in frame)
        for frame in command.data["frames"]
    )


@pytest.mark.parametrize(("step", "font_size"), [(1, 8), (8, 16)])
async def test_show_text_accepts_style_boundaries(
    hass, enable_custom_integrations, step, font_size
):
    adapter = await _adapter_for(hass)
    await hass.services.async_call(
        DOMAIN,
        "show_text",
        {"value": "A", "step": step, "font_size": font_size},
        blocking=True,
    )
    assert adapter.commands[0].data["step"] == step
    assert adapter.commands[0].data["font_size"] == font_size


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"value": "A", "step": 0},
        {"value": "A", "step": 9},
        {"value": "A", "step": True},
        {"value": "A", "font_size": 7},
        {"value": "A", "font_size": 17},
        {"value": "A", "font_size": True},
        {"value": "A", "font": "not-installed"},
        {"value": "A", "font_file": "/etc/passwd"},
        {"value": "A", "color": "not-a-color"},
        {"value": "A", "background": "#GGGGGG"},
        {"value": "A", "speed": 0},
    ],
)
async def test_show_text_rejects_invalid_styles_and_local_font_paths(
    hass, enable_custom_integrations, data
):
    adapter = await _adapter_for(hass)
    with pytest.raises(MultipleInvalid):
        await hass.services.async_call(DOMAIN, "show_text", data, blocking=True)
    assert adapter.commands == []


async def test_show_text_renders_cjk_using_packaged_unifont(
    hass, enable_custom_integrations
):
    adapter = await _adapter_for(hass)
    await hass.services.async_call(
        DOMAIN, "show_text", {"value": "你好"}, blocking=True
    )
    command = adapter.commands[0]
    assert command.data["font_size"] is None
    assert command.data["font"] == "unifont"
    assert command.data["frames"]


@pytest.mark.parametrize("countdown", ["00:00", "00:01", "99:59"])
async def test_start_countdown_accepts_strict_mm_ss_boundaries(
    hass, enable_custom_integrations, countdown
):
    adapter = await _adapter_for(hass)
    await hass.services.async_call(
        DOMAIN, "start_countdown", {"countdown": countdown}, blocking=True
    )
    assert adapter.commands[0].name == "start_countdown"
    assert adapter.commands[0].data == {"countdown": countdown}


@pytest.mark.parametrize(
    "countdown",
    ["0:30", "1:2", "100:00", "00:60", "01:99", "1:30:00", "01:30x", "", " 01:30"],
)
async def test_start_countdown_rejects_non_mm_ss_values(
    hass, enable_custom_integrations, countdown
):
    adapter = await _adapter_for(hass)
    with pytest.raises(MultipleInvalid):
        await hass.services.async_call(
            DOMAIN, "start_countdown", {"countdown": countdown}, blocking=True
        )
    assert adapter.commands == []


async def test_start_countdown_requires_countdown(hass, enable_custom_integrations):
    adapter = await _adapter_for(hass)
    with pytest.raises(MultipleInvalid):
        await hass.services.async_call(DOMAIN, "start_countdown", {}, blocking=True)
    assert adapter.commands == []


@pytest.mark.parametrize("value", [0, 100])
async def test_set_brightness_preserves_integer_boundaries(
    hass, enable_custom_integrations, value
):
    adapter = await _adapter_for(hass)
    await hass.services.async_call(
        DOMAIN, "set_brightness", {"value": value}, blocking=True
    )
    assert adapter.commands[0].name == "set_brightness"
    assert adapter.commands[0].data == {"value": value}


@pytest.mark.parametrize("value", [-1, 101, 1.5, "50", True])
async def test_set_brightness_rejects_out_of_range_or_non_integer_values(
    hass, enable_custom_integrations, value
):
    adapter = await _adapter_for(hass)
    with pytest.raises(MultipleInvalid):
        await hass.services.async_call(
            DOMAIN, "set_brightness", {"value": value}, blocking=True
        )
    assert adapter.commands == []


async def test_new_services_propagate_unavailable_adapter_errors(
    hass, enable_custom_integrations
):
    await _loaded_entry(hass)
    cases = [
        ("set_expression", {"name": "heart"}),
        ("show_text", {"value": "Hi"}),
        ("start_countdown", {"countdown": "00:30"}),
        ("set_brightness", {"value": 50}),
    ]
    for service, data in cases:
        with pytest.raises(HomeAssistantError, match="unavailable"):
            await hass.services.async_call(DOMAIN, service, data, blocking=True)
