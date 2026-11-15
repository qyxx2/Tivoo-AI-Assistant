"""Tests for AstrBot's explicit new-conversation controls."""

import pytest
from custom_components.astrbot.const import (
    DOMAIN,
    SERVICE_NEW_CONVERSATION,
    SESSION_STORE_KEY,
    SESSION_STORE_VERSION,
)
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.components.mcp_server.server import async_get_api_instance
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import llm as llm_helpers
from homeassistant.helpers.storage import Store
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry

TOOL_NAME = "astrbot__NewConversation"


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="AstrBot",
        data={
            "base_url": "http://astrbot.example:6185",
            "api_key": "test-secret-value",
            "api_key_id": "key-123",
        },
        unique_id=DOMAIN,
    )


async def _loaded_entry(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry, hass.data[DOMAIN][entry.entry_id]["session_manager"]


async def _regular_user(hass):
    return await hass.auth.async_create_user(
        "astrbot_member", group_ids=[GROUP_ID_USER]
    )


def _llm_context(user):
    return llm_helpers.LLMContext(
        platform="mcp_server",
        context=Context(user_id=user.id),
        language="zh-CN",
        assistant="mcp_server",
        device_id=None,
    )


async def _assist_api(hass, user):
    return await async_get_api_instance(
        hass,
        llm_helpers.LLM_API_ASSIST,
        _llm_context(user),
        read_only=False,
    )


async def test_new_conversation_service_discards_persisted_session(
    hass, enable_custom_integrations
):
    entry, manager = await _loaded_entry(hass)
    old_session_id = manager.get_session_id()
    await manager.async_confirm_session(old_session_id)

    stored = await Store(hass, SESSION_STORE_VERSION, SESSION_STORE_KEY).async_load()
    assert stored["session_id"] == old_session_id

    await hass.services.async_call(
        DOMAIN,
        SERVICE_NEW_CONVERSATION,
        {},
        blocking=True,
    )

    assert (
        await Store(hass, SESSION_STORE_VERSION, SESSION_STORE_KEY).async_load() is None
    )
    new_session_id = manager.get_session_id()
    assert new_session_id != old_session_id

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service(DOMAIN, SERVICE_NEW_CONVERSATION)


async def test_config_button_starts_a_fresh_session(hass, enable_custom_integrations):
    entry, manager = await _loaded_entry(hass)
    old_session_id = manager.get_session_id()
    await manager.async_confirm_session(old_session_id)

    registry = er.async_get(hass)
    button_entry = next(
        item
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.domain == "button"
    )
    assert button_entry.entity_id == "button.astrbot_new_conversation"

    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: button_entry.entity_id},
        blocking=True,
    )

    new_session_id = manager.get_session_id()
    assert new_session_id != old_session_id
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_assist_exposes_new_conversation_tool_and_tool_rotates_session(
    hass, enable_custom_integrations
):
    assert await async_setup_component(hass, "llm", {})
    await hass.async_block_till_done()
    user = await _regular_user(hass)

    before = await _assist_api(hass, user)
    assert TOOL_NAME not in {tool.name for tool in before.tools}

    entry, manager = await _loaded_entry(hass)
    old_session_id = manager.get_session_id()
    await manager.async_confirm_session(old_session_id)

    api = await _assist_api(hass, user)
    tool = next(tool for tool in api.tools if tool.name == TOOL_NAME)
    assert tool.integration == DOMAIN
    assert tool.annotations.read_only is False
    assert tool.annotations.destructive is True
    assert tool.annotations.idempotent is True
    assert tool.annotations.open_world is False

    result = await api.async_call_tool(
        llm_helpers.ToolInput(tool_name=TOOL_NAME, tool_args={})
    )
    assert result.data == {"status": "new_conversation_ready"}
    assert result.error is False

    new_session_id = manager.get_session_id()
    assert new_session_id != old_session_id

    assert await hass.config_entries.async_unload(entry.entry_id)
    after = await _assist_api(hass, user)
    assert TOOL_NAME not in {tool.name for tool in after.tools}


async def test_new_conversation_tool_rejects_arguments(
    hass, enable_custom_integrations
):
    assert await async_setup_component(hass, "llm", {})
    await hass.async_block_till_done()
    user = await _regular_user(hass)
    entry, _manager = await _loaded_entry(hass)

    api = await _assist_api(hass, user)
    with pytest.raises(HomeAssistantError, match="does not accept parameters"):
        await api.async_call_tool(
            llm_helpers.ToolInput(
                tool_name=TOOL_NAME,
                tool_args={"reason": "new topic"},
            )
        )

    assert await hass.config_entries.async_unload(entry.entry_id)
