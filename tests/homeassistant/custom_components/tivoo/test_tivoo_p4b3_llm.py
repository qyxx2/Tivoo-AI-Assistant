"""P4b3 tests for Assist tool registration and HA service delegation."""

import pytest
from custom_components.tivoo.commands import TivooCommand, UnavailableCommandAdapter
from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
from homeassistant.components.mcp_server.server import async_get_api_instance
from homeassistant.const import ATTR_DOMAIN, ATTR_SERVICE, EVENT_CALL_SERVICE
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm as llm_helpers
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry

DOMAIN = "tivoo"
EXPECTED_TOOLS = {
    "tivoo__SetExpression": ({"name": "heart"}, "set_expression", False),
    "tivoo__ShowText": ({"value": "Hi"}, "show_text", False),
    "tivoo__StartCountdown": ({"countdown": "01:30"}, "start_countdown", False),
    "tivoo__SetVolume": ({"volume": 0}, "set_volume", True),
}


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
    runtime = hass.data[DOMAIN][entry.entry_id]
    runtime["command_adapter"] = MemoryCommandAdapter()
    return entry, runtime


async def _assist_api(hass):
    await hass.auth.async_create_user("tivoo_p4b3_admin", group_ids=[GROUP_ID_ADMIN])
    user = await hass.auth.async_create_user(
        "tivoo_p4b3_user", group_ids=[GROUP_ID_USER]
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


@pytest.mark.parametrize(("tool_name", "case"), list(EXPECTED_TOOLS.items()))
async def test_p4b3_tool_calls_its_service_and_preserves_input(
    hass, enable_custom_integrations, tool_name, case
):
    args, service, _idempotent = case
    _, runtime = await _loaded_entry(hass)
    api = await _assist_api(hass)
    tool = next(tool for tool in api.tools if tool.name == tool_name)
    assert tool.integration == DOMAIN
    assert tool.annotations.read_only is False
    assert tool.annotations.destructive is False
    assert tool.annotations.open_world is False
    assert tool.annotations.idempotent is _idempotent

    events = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, events.append)
    result = await api.async_call_tool(
        llm_helpers.ToolInput(tool_name=tool_name, tool_args=args)
    )
    await hass.async_block_till_done()

    assert result.data == {"status": "service_completed"}
    assert result.error is False
    service_events = [
        event
        for event in events
        if event.data.get(ATTR_DOMAIN) == DOMAIN
        and event.data.get(ATTR_SERVICE) == service
    ]
    assert len(service_events) == 1
    assert len(runtime["command_adapter"].commands) == 1
    command = runtime["command_adapter"].commands[0]
    assert isinstance(command, TivooCommand)
    assert command.name == service
    for key, value in args.items():
        assert command.data[key] == value


async def test_p4b3_tools_are_available_with_stop_countdown_only_on_assist(
    hass, enable_custom_integrations
):
    await _loaded_entry(hass)
    api = await _assist_api(hass)
    names = {tool.name for tool in api.tools if tool.integration == DOMAIN}
    assert names == {
        "tivoo__SetExpression",
        "tivoo__ShowText",
        "tivoo__StartCountdown",
        "tivoo__StopCountdown",
        "tivoo__SetVolume",
    }


async def test_p4b3_tool_propagates_service_adapter_error(
    hass, enable_custom_integrations
):
    _, runtime = await _loaded_entry(hass)
    runtime["command_adapter"] = UnavailableCommandAdapter()
    api = await _assist_api(hass)
    with pytest.raises(HomeAssistantError, match="unavailable"):
        await api.async_call_tool(
            llm_helpers.ToolInput(
                tool_name="tivoo__SetVolume",
                tool_args={"volume": 100},
            )
        )
