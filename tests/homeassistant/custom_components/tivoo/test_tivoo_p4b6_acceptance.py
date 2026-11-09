"""P4b6 acceptance tests for HA entity exposure boundaries."""

from contextlib import asynccontextmanager
from uuid import uuid4

import httpx2
import pytest
from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
from homeassistant.auth.models import TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.setup import async_setup_component
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pytest_homeassistant.common import MockConfigEntry

DOMAIN = "tivoo"


class MemoryCommandAdapter:
    def __init__(self):
        self.commands = []

    async def async_execute(self, command):
        self.commands.append(command)


@asynccontextmanager
async def _mcp_session(hass, aiohttp_client):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tivoo",
        data={"media_directory": "pixelart"},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    adapter = MemoryCommandAdapter()
    hass.data[DOMAIN][entry.entry_id]["command_adapter"] = adapter

    await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "llm", {})
    assert await async_setup_component(hass, "mcp_server", {})

    await hass.auth.async_create_user(
        f"p4b6-owner-{uuid4().hex[:8]}", group_ids=[GROUP_ID_ADMIN]
    )
    user = await hass.auth.async_create_user(
        f"p4b6-{uuid4().hex[:8]}", group_ids=[GROUP_ID_USER]
    )
    refresh_token = await hass.auth.async_create_refresh_token(
        user,
        client_name=f"p4b6-test-{uuid4().hex}",
        token_type=TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN,
    )
    access_token = hass.auth.async_create_access_token(refresh_token)

    web_client = await aiohttp_client(hass.http.app)
    url = str(web_client.make_url("/api/mcp/assist"))
    async with (
        httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {access_token}"}
        ) as http_client,
        streamable_http_client(url, http_client=http_client) as (
            read_stream,
            write_stream,
        ),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        yield session, adapter


@pytest.mark.enable_socket
async def test_assist_mcp_live_context_only_includes_exposed_entities(
    hass, enable_custom_integrations, aiohttp_client
):
    async with _mcp_session(hass, aiohttp_client) as (session, _adapter):
        exposed_entity = "sensor.p4b6_exposed"
        hidden_entity = "sensor.p4b6_hidden"
        hass.states.async_set(exposed_entity, "21.5", {"unit_of_measurement": "°C"})
        hass.states.async_set(hidden_entity, "99.0", {"unit_of_measurement": "°C"})
        async_expose_entity(hass, "conversation", exposed_entity, True)
        async_expose_entity(hass, "conversation", hidden_entity, False)

        result = await session.call_tool("homeassistant__GetLiveContext", {})
        assert result.is_error is not True
        returned_context = result.content[0].text
        assert "p4b6 exposed" in returned_context
        assert "21.5" in returned_context
        assert "p4b6 hidden" not in returned_context
        assert "99.0" not in returned_context


@pytest.mark.enable_socket
async def test_tivoo_actions_are_explicit_tools_and_do_not_accept_entity_targets(
    hass, enable_custom_integrations, aiohttp_client
):
    async with _mcp_session(hass, aiohttp_client) as (session, adapter):
        tools = await session.list_tools()
        tivoo_tools = {
            tool.name: tool for tool in tools.tools if tool.name.startswith("tivoo__")
        }
        assert set(tivoo_tools) == {
            "tivoo__SetExpression",
            "tivoo__ShowText",
            "tivoo__StartCountdown",
            "tivoo__StopCountdown",
            "tivoo__SetVolume",
            "tivoo__ShowImage",
            "tivoo__PlayAnimation",
        }
        assert "homeassistant__call_action" not in {tool.name for tool in tools.tools}

        result = await session.call_tool(
            "tivoo__SetVolume", {"volume": 55, "entity_id": "light.living_room"}
        )
        assert result.is_error is True
        await hass.async_block_till_done()
        assert adapter.commands == []
