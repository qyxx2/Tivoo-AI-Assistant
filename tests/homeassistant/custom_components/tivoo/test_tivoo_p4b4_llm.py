"""P4b4 tests for media Assist Tool discovery and service delegation."""

from pathlib import Path
from uuid import uuid4

import probatio
import pytest
from custom_components.tivoo.commands import TivooCommand
from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
from homeassistant.components.mcp_server.server import async_get_api_instance
from homeassistant.const import ATTR_DOMAIN, ATTR_SERVICE, EVENT_CALL_SERVICE
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm as llm_helpers
from homeassistant.setup import async_setup_component
from PIL import Image
from pytest_homeassistant.common import MockConfigEntry

DOMAIN = "tivoo"
MEDIA_TOOLS = {
    "tivoo__ShowImage": ("show_image", "still.png"),
    "tivoo__PlayAnimation": ("play_animation", "motion.gif"),
}


class MemoryCommandAdapter:
    def __init__(self):
        self.commands = []

    async def async_execute(self, command):
        self.commands.append(command)


async def _loaded_entry(hass):
    configured_directory = f"pixelart/{uuid4().hex}"
    media_directory = Path(hass.config.path(configured_directory))
    media_directory.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), (30, 120, 220)).save(
        media_directory / "still.png", format="PNG"
    )
    frames = [
        Image.new("RGB", (16, 16), (220, 30, 40)),
        Image.new("RGB", (16, 16), (20, 80, 210)),
    ]
    frames[0].save(
        media_directory / "motion.gif",
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=[40, 120],
        loop=0,
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tivoo",
        data={"media_directory": configured_directory},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    runtime = hass.data[DOMAIN][entry.entry_id]
    adapter = MemoryCommandAdapter()
    runtime["command_adapter"] = adapter
    return adapter


async def _assist_api(hass):
    await hass.auth.async_create_user("tivoo_p4b4_admin", group_ids=[GROUP_ID_ADMIN])
    user = await hass.auth.async_create_user(
        "tivoo_p4b4_user", group_ids=[GROUP_ID_USER]
    )
    assert not user.is_admin
    context = llm_helpers.LLMContext(
        platform="mcp_server",
        context=Context(user_id=user.id),
        language="en",
        assistant="mcp_server",
        device_id=None,
    )
    assert await async_setup_component(hass, "llm", {})
    await hass.async_block_till_done()
    return await async_get_api_instance(
        hass,
        llm_helpers.LLM_API_ASSIST,
        context,
        read_only=False,
    )


async def test_p4b4_media_tools_are_registered_for_assist(
    hass, enable_custom_integrations
):
    await _loaded_entry(hass)
    api = await _assist_api(hass)

    media_tools = {tool.name: tool for tool in api.tools if tool.integration == DOMAIN}
    assert set(media_tools) == {
        "tivoo__SetExpression",
        "tivoo__ShowText",
        "tivoo__StartCountdown",
        "tivoo__StopCountdown",
        "tivoo__SetVolume",
        "tivoo__ShowImage",
        "tivoo__PlayAnimation",
    }
    for name in MEDIA_TOOLS:
        tool = media_tools[name]
        assert tool.annotations.read_only is False
        assert tool.annotations.destructive is False
        assert tool.annotations.open_world is False
        assert tool.annotations.idempotent is False


@pytest.mark.parametrize(("tool_name", "service_and_file"), list(MEDIA_TOOLS.items()))
async def test_p4b4_media_tool_delegates_file_reference_to_ha_service(
    hass, enable_custom_integrations, tool_name, service_and_file
):
    adapter = await _loaded_entry(hass)
    api = await _assist_api(hass)
    service, file_reference = service_and_file
    events = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, events.append)

    result = await api.async_call_tool(
        llm_helpers.ToolInput(
            tool_name=tool_name,
            tool_args={"file": file_reference, "time": 55},
        )
    )
    await hass.async_block_till_done()

    assert result.error is False
    assert result.data == {"status": "service_completed"}
    service_events = [
        event
        for event in events
        if event.data.get(ATTR_DOMAIN) == DOMAIN
        and event.data.get(ATTR_SERVICE) == service
    ]
    assert len(service_events) == 1
    assert len(adapter.commands) == 1
    command = adapter.commands[0]
    assert isinstance(command, TivooCommand)
    assert command.name == service
    assert command.data["file"] == file_reference
    assert command.data["delays"] == ([55] if service == "show_image" else [55, 55])
    assert len(command.data["frames"]) == (1 if service == "show_image" else 2)
    assert set(command.data).issuperset({"file", "frames", "delays"})


async def test_p4b4_media_tool_schema_rejects_non_string_and_non_integer_inputs(
    hass, enable_custom_integrations
):
    await _loaded_entry(hass)
    api = await _assist_api(hass)
    tool = next(tool for tool in api.tools if tool.name == "tivoo__ShowImage")

    for invalid_args in (
        {"file": ["still.png"]},
        {"file": "still.png", "time": 1.5},
        {"file": "still.png", "time": True},
        {"file": "still.png", "frames": []},
        {"file": "still.png", "palette": {}},
    ):
        with pytest.raises(probatio.MultipleInvalid):
            tool.parameters(invalid_args)


async def test_p4b4_media_tool_propagates_service_error(
    hass, enable_custom_integrations
):
    await _loaded_entry(hass)
    api = await _assist_api(hass)

    with pytest.raises(HomeAssistantError, match="Media file"):
        await api.async_call_tool(
            llm_helpers.ToolInput(
                tool_name="tivoo__ShowImage",
                tool_args={"file": "missing.png"},
            )
        )
