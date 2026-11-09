"""Tests for Tivoo's native Home Assistant LLM Tools platform."""

import pytest
from custom_components.tivoo.commands import TivooCommand
from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
from homeassistant.components.mcp_server.server import async_get_api_instance
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DOMAIN, ATTR_SERVICE, EVENT_CALL_SERVICE
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.helpers import llm as llm_helpers
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry

DOMAIN = "tivoo"
TOOL_NAME = "tivoo__StopCountdown"


class MemoryCommandAdapter:
    """Capture real service dispatch at the existing semantic adapter seam."""

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


async def _create_users(hass):
    """Create both API roles, avoiding first-user owner promotion ambiguity."""
    admin = await hass.auth.async_create_user("tivoo_admin", group_ids=[GROUP_ID_ADMIN])
    regular = await hass.auth.async_create_user(
        "tivoo_member", group_ids=[GROUP_ID_USER]
    )
    assert admin.is_admin
    assert not regular.is_admin
    return admin, regular


def _llm_context(user):
    return llm_helpers.LLMContext(
        platform="mcp_server",
        context=Context(user_id=user.id),
        language="en",
        assistant="mcp_server",
        device_id=None,
    )


async def _setup_llm(hass):
    assert await async_setup_component(hass, "llm", {})
    await hass.async_block_till_done()


async def _assist_api(hass, user):
    return await async_get_api_instance(
        hass,
        llm_helpers.LLM_API_ASSIST,
        _llm_context(user),
        read_only=False,
    )


async def test_assist_platform_discovers_tool_only_while_tivoo_entry_is_loaded(
    hass, enable_custom_integrations
):
    await _setup_llm(hass)
    _, regular = await _create_users(hass)

    before_setup = await _assist_api(hass, regular)
    assert TOOL_NAME not in {tool.name for tool in before_setup.tools}

    entry, _ = await _loaded_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    after_setup = await _assist_api(hass, regular)
    assert TOOL_NAME in {tool.name for tool in after_setup.tools}

    assert await hass.config_entries.async_unload(entry.entry_id)
    after_unload = await _assist_api(hass, regular)
    assert TOOL_NAME not in {tool.name for tool in after_unload.tools}


async def test_stop_countdown_tool_is_limited_to_assist_api_for_regular_users(
    hass, enable_custom_integrations
):
    await _setup_llm(hass)
    await _loaded_entry(hass)
    admin, regular = await _create_users(hass)

    assist_api = await _assist_api(hass, regular)
    tool = next(tool for tool in assist_api.tools if tool.name == TOOL_NAME)
    assert tool.integration == DOMAIN
    assert tool.annotations.read_only is False
    assert tool.annotations.destructive is False
    assert tool.annotations.idempotent is True
    assert tool.annotations.open_world is False

    management_api = await async_get_api_instance(
        hass,
        llm_helpers.LLM_API_HOME_ASSISTANT,
        _llm_context(admin),
        read_only=False,
    )
    assert TOOL_NAME not in {tool.name for tool in management_api.tools}

    with pytest.raises(Unauthorized):
        await async_get_api_instance(
            hass,
            llm_helpers.LLM_API_HOME_ASSISTANT,
            _llm_context(regular),
            read_only=False,
        )


async def test_stop_countdown_tool_calls_the_existing_service_with_empty_data_and_context(
    hass, enable_custom_integrations
):
    await _setup_llm(hass)
    entry, runtime = await _loaded_entry(hass)
    adapter = MemoryCommandAdapter()
    runtime["command_adapter"] = adapter
    _, regular = await _create_users(hass)

    service_events = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, service_events.append)

    api = await _assist_api(hass, regular)
    result = await api.async_call_tool(
        llm_helpers.ToolInput(tool_name=TOOL_NAME, tool_args={})
    )
    await hass.async_block_till_done()

    assert result.data == {"status": "service_completed"}
    assert result.error is False
    assert len(adapter.commands) == 1
    assert isinstance(adapter.commands[0], TivooCommand)
    assert adapter.commands[0].name == "stop_countdown"
    assert adapter.commands[0].data == {}

    matching_events = [
        event
        for event in service_events
        if event.data.get(ATTR_DOMAIN) == DOMAIN
        and event.data.get(ATTR_SERVICE) == "stop_countdown"
    ]
    assert len(matching_events) == 1
    assert matching_events[0].context.user_id == regular.id

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_stop_countdown_tool_propagates_unavailable_adapter_error(
    hass, enable_custom_integrations
):
    await _setup_llm(hass)
    await _loaded_entry(hass)
    _, regular = await _create_users(hass)

    api = await _assist_api(hass, regular)
    with pytest.raises(HomeAssistantError, match="unavailable"):
        await api.async_call_tool(
            llm_helpers.ToolInput(tool_name=TOOL_NAME, tool_args={})
        )


async def test_stop_countdown_tool_rejects_unexpected_arguments(
    hass, enable_custom_integrations
):
    await _setup_llm(hass)
    await _loaded_entry(hass)
    _, regular = await _create_users(hass)

    api = await _assist_api(hass, regular)
    with pytest.raises(HomeAssistantError, match="does not accept parameters"):
        await api.async_call_tool(
            llm_helpers.ToolInput(
                tool_name=TOOL_NAME,
                tool_args={"countdown": "00:30"},
            )
        )
