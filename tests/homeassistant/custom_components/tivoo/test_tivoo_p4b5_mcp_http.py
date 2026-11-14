"""P4b5 end-to-end tests for HA Assist MCP over Streamable HTTP."""

import socket
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import httpx2
import probatio
import pytest
from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
from homeassistant.auth.models import TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from PIL import Image
from pytest_homeassistant.common import MockConfigEntry
from pytest_socket import SocketConnectBlockedError, socket_allow_hosts

DOMAIN = "tivoo"


@pytest.fixture(autouse=True)
def _restrict_enabled_mcp_test_sockets(request):
    if request.node.get_closest_marker("enable_socket"):
        socket_allow_hosts(["127.0.0.1"])


EXPECTED_TOOLS = {
    "tivoo__GameControl",
    "tivoo__PlayAnimation",
    "tivoo__SetAlarm",
    "tivoo__SetAudioSource",
    "tivoo__SetBrightness",
    "tivoo__SetDateTime",
    "tivoo__SetExpression",
    "tivoo__SetLight",
    "tivoo__SetMemorial",
    "tivoo__SetNoiseMeter",
    "tivoo__SetPlayState",
    "tivoo__SetScreenPower",
    "tivoo__SetSleepMode",
    "tivoo__SetTimer",
    "tivoo__SetVolume",
    "tivoo__SetWeather",
    "tivoo__ShowClock",
    "tivoo__ShowDesign",
    "tivoo__ShowEffects",
    "tivoo__ShowGame",
    "tivoo__ShowImage",
    "tivoo__ShowLyrics",
    "tivoo__ShowScoreboard",
    "tivoo__ShowText",
    "tivoo__ShowVisualization",
    "tivoo__StartCountdown",
    "tivoo__StopCountdown",
}


class MemoryCommandAdapter:
    def __init__(self):
        self.commands = []

    async def async_execute(self, command):
        self.commands.append(command)


class FailingCommandAdapter:
    async def async_execute(self, command):
        raise HomeAssistantError("P4b5 test adapter unavailable")


async def _load_tivoo(hass):
    media_directory = f"pixelart/{uuid4().hex}"
    media_path = Path(hass.config.path(media_directory))
    media_path.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), (30, 120, 220)).save(media_path / "still.png")
    frames = [
        Image.new("RGB", (16, 16), (220, 30, 40)),
        Image.new("RGB", (16, 16), (20, 80, 210)),
    ]
    frames[0].save(
        media_path / "motion.gif",
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=[40, 120],
        loop=0,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tivoo",
        data={"media_directory": media_directory},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    adapter = MemoryCommandAdapter()
    hass.data[DOMAIN][entry.entry_id]["command_adapter"] = adapter
    return entry, adapter


@asynccontextmanager
async def _assist_mcp_session(hass, aiohttp_client, adapter=None):
    """Open the real HA Assist MCP endpoint with a temporary normal-user token."""
    entry, default_adapter = await _load_tivoo(hass)
    active_adapter = adapter or default_adapter
    if adapter is not None:
        hass.data[DOMAIN][entry.entry_id]["command_adapter"] = active_adapter

    assert await async_setup_component(hass, "llm", {})
    assert await async_setup_component(hass, "mcp_server", {})

    await hass.auth.async_create_user(
        f"p4b5-owner-{uuid4().hex[:8]}", group_ids=[GROUP_ID_ADMIN]
    )
    user = await hass.auth.async_create_user(
        f"p4b5-{uuid4().hex[:8]}",
        group_ids=[GROUP_ID_USER],
    )
    assert not user.is_admin
    refresh_token = await hass.auth.async_create_refresh_token(
        user,
        client_name=f"p4b5-test-{uuid4().hex}",
        token_type=TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN,
    )
    access_token = hass.auth.async_create_access_token(refresh_token)

    web_client = await aiohttp_client(hass.http.app)
    url = str(web_client.make_url("/api/mcp/assist"))

    async with (
        httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {access_token}"},
        ) as http_client,
        streamable_http_client(url, http_client=http_client) as (
            read_stream,
            write_stream,
        ),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        yield session, active_adapter, user


@pytest.mark.enable_socket
def test_p4b5_mcp_http_tests_block_non_loopback_targets():
    with pytest.raises(SocketConnectBlockedError):
        socket.create_connection(("192.0.2.1", 12345), timeout=0.1)


@pytest.mark.enable_socket
async def test_p4b5_assist_mcp_discovers_all_tivoo_tools_for_normal_user(
    hass, enable_custom_integrations, aiohttp_client
):
    async with _assist_mcp_session(hass, aiohttp_client) as (session, _, user):
        assert not user.is_admin
        result = await session.list_tools()
        tivoo_tools = {
            tool.name for tool in result.tools if tool.name.startswith("tivoo__")
        }
        assert tivoo_tools == EXPECTED_TOOLS


@pytest.mark.enable_socket
async def test_p4b5_streamable_http_calls_all_tivoo_tools(
    hass, enable_custom_integrations, aiohttp_client
):
    cases = [
        ("tivoo__SetExpression", {"name": "heart"}, "set_expression"),
        ("tivoo__ShowText", {"value": "Hello"}, "show_text"),
        ("tivoo__SetBrightness", {"value": 42}, "set_brightness"),
        ("tivoo__SetScreenPower", {"value": True}, "set_screen_power"),
        ("tivoo__SetVolume", {"volume": 50}, "set_volume"),
        ("tivoo__SetPlayState", {"value": "pause"}, "set_playstate"),
        ("tivoo__ShowClock", {"clock": 1, "color": "red"}, "show_clock"),
        (
            "tivoo__SetDateTime",
            {"value": "2026-11-14T18:30:00"},
            "set_datetime",
        ),
        (
            "tivoo__SetWeather",
            {"temperature": 25, "condition": 6, "unit": "C"},
            "set_weather",
        ),
        (
            "tivoo__SetLight",
            {"brightness": 75, "color": "red", "effect": 0},
            "set_light",
        ),
        ("tivoo__StartCountdown", {"countdown": "01:30"}, "start_countdown"),
        ("tivoo__StopCountdown", {}, "stop_countdown"),
        ("tivoo__ShowLyrics", {}, "show_lyrics"),
        (
            "tivoo__ShowScoreboard",
            {"player1": 2, "player2": 1},
            "show_scoreboard",
        ),
        ("tivoo__SetTimer", {"value": True}, "set_timer"),
        ("tivoo__SetNoiseMeter", {"value": True}, "set_noise_meter"),
        (
            "tivoo__SetAlarm",
            {
                "slot": 1,
                "time": "07:30",
                "weekdays": ["mon", "tue", "wed", "thu", "fri"],
                "frequency": 100.3,
                "volume": 80,
            },
            "set_alarm",
        ),
        (
            "tivoo__SetMemorial",
            {
                "slot": 2,
                "value": "2026-12-31T00:00:00",
                "text": "New Year",
            },
            "set_memorial",
        ),
        ("tivoo__SetAudioSource", {"value": "linein"}, "set_audio_source"),
        ("tivoo__SetSleepMode", {"value": False}, "set_sleep_mode"),
        ("tivoo__ShowDesign", {"number": 2}, "show_design"),
        ("tivoo__ShowEffects", {"number": 2}, "show_effects"),
        ("tivoo__ShowVisualization", {"number": 1}, "show_visualization"),
        ("tivoo__ShowGame", {"index": 2}, "show_game"),
        ("tivoo__GameControl", {"value": "go"}, "game_control"),
        ("tivoo__ShowImage", {"file": "still.png", "time": 55}, "show_image"),
        ("tivoo__PlayAnimation", {"file": "motion.gif", "time": 55}, "play_animation"),
    ]

    async with _assist_mcp_session(hass, aiohttp_client) as (
        session,
        adapter,
        _user,
    ):
        for tool_name, arguments, service_name in cases:
            result = await session.call_tool(tool_name, arguments)
            assert result.is_error is not True

        await hass.async_block_till_done()
        assert [command.name for command in adapter.commands] == [
            service_name for _, _, service_name in cases
        ]
        for command, (_, arguments, _) in zip(adapter.commands, cases, strict=True):
            for key, value in arguments.items():
                assert command.data[key] == value


@pytest.mark.enable_socket
async def test_p4b5_service_failure_is_returned_as_mcp_tool_error(
    hass, enable_custom_integrations, aiohttp_client
):
    async with _assist_mcp_session(
        hass, aiohttp_client, adapter=FailingCommandAdapter()
    ) as (session, _, _user):
        result = await session.call_tool("tivoo__SetVolume", {"volume": 100})
        assert result.is_error is True
        assert "P4b5 test adapter unavailable" in result.content[0].text


@pytest.mark.enable_socket
async def test_p4b5_assist_mcp_rejects_invalid_bearer_token(
    hass, enable_custom_integrations, aiohttp_client
):
    assert await async_setup_component(hass, "llm", {})
    assert await async_setup_component(hass, "mcp_server", {})
    web_client = await aiohttp_client(hass.http.app)

    response = await web_client.post(
        "/api/mcp/assist",
        headers={
            "Authorization": "Bearer p4b5-invalid-token",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "p4b5-test", "version": "1.0"},
            },
        },
    )
    assert response.status == 401


async def test_p4b5_brightness_service_accepts_zero_and_one_hundred_and_rejects_out_of_range(
    hass, enable_custom_integrations
):
    _, adapter = await _load_tivoo(hass)
    for value in (0, 100):
        await hass.services.async_call(
            DOMAIN,
            "set_brightness",
            {"value": value},
            blocking=True,
            context=Context(),
        )
    assert [command.data["value"] for command in adapter.commands] == [0, 100]

    with pytest.raises(probatio.MultipleInvalid):
        await hass.services.async_call(
            DOMAIN,
            "set_brightness",
            {"value": 101},
            blocking=True,
            context=Context(),
        )
