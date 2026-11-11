"""Tests for the Tivoo ESP32 connection lifecycle."""

import asyncio

import pytest
from custom_components.tivoo import transport
from custom_components.tivoo.const import DOMAIN
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant.common import MockConfigEntry


async def _wait_for_state(adapter, channel, expected):
    for _ in range(300):
        if adapter.states[channel] == expected:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"{channel} stayed {adapter.states[channel]!r}, expected {expected!r}"
    )


async def _close_clients(clients):
    for writer in clients:
        writer.close()
    if clients:
        await asyncio.gather(
            *(writer.wait_closed() for writer in clients),
            return_exceptions=True,
        )


async def test_connections_are_independent_and_reconnect_separately(
    monkeypatch, socket_enabled
):
    control_clients = []
    diagnostic_clients = []

    async def control_handler(reader, writer):
        control_clients.append(writer)
        await reader.read()

    async def diagnostic_handler(reader, writer):
        diagnostic_clients.append(writer)
        await reader.read()

    control_server = await asyncio.start_server(control_handler, "127.0.0.1", 0)
    diagnostic_server = await asyncio.start_server(diagnostic_handler, "127.0.0.1", 0)
    monkeypatch.setattr(
        transport, "CONTROL_PORT", control_server.sockets[0].getsockname()[1]
    )
    monkeypatch.setattr(
        transport, "DIAGNOSTIC_PORT", diagnostic_server.sockets[0].getsockname()[1]
    )

    adapter = transport.Esp32ConnectionAdapter("127.0.0.1", retry_interval=0.05)
    await adapter.async_start()
    try:
        await _wait_for_state(adapter, "control", "connected")
        await _wait_for_state(adapter, "diagnostic", "connected")

        diagnostic_server.close()
        await _close_clients(diagnostic_clients)
        await diagnostic_server.wait_closed()
        await _wait_for_state(adapter, "diagnostic", "disconnected")
        assert adapter.states["control"] == "connected"

        diagnostic_clients.clear()
        diagnostic_server = await asyncio.start_server(
            diagnostic_handler,
            "127.0.0.1",
            transport.DIAGNOSTIC_PORT,
        )
        await _wait_for_state(adapter, "diagnostic", "connected")
        assert adapter.states["control"] == "connected"
    finally:
        await adapter.async_stop()
        control_server.close()
        diagnostic_server.close()
        await _close_clients(control_clients + diagnostic_clients)
        await control_server.wait_closed()
        await diagnostic_server.wait_closed()


async def test_missing_host_keeps_both_channels_unavailable():
    adapter = transport.Esp32ConnectionAdapter(None)
    await adapter.async_start()

    assert adapter.states == {
        "control": "unavailable",
        "diagnostic": "unavailable",
    }

    await adapter.async_stop()


async def test_command_execution_remains_unavailable_in_p5b1():
    adapter = transport.Esp32ConnectionAdapter("127.0.0.1")

    with pytest.raises(HomeAssistantError, match="P5b1"):
        await adapter.async_execute(
            transport.TivooCommand(name="set_brightness", data={"value": 50})
        )


async def test_config_entry_starts_and_stops_both_connections(
    hass, socket_enabled, monkeypatch
):
    control_clients = []
    diagnostic_clients = []

    async def control_handler(reader, writer):
        control_clients.append(writer)
        await reader.read()

    async def diagnostic_handler(reader, writer):
        diagnostic_clients.append(writer)
        await reader.read()

    control_server = await asyncio.start_server(control_handler, "127.0.0.1", 0)
    diagnostic_server = await asyncio.start_server(diagnostic_handler, "127.0.0.1", 0)
    monkeypatch.setattr(
        transport, "CONTROL_PORT", control_server.sockets[0].getsockname()[1]
    )
    monkeypatch.setattr(
        transport, "DIAGNOSTIC_PORT", diagnostic_server.sockets[0].getsockname()[1]
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tivoo",
        data={
            "media_directory": "pixelart",
            "esp32_host": "127.0.0.1",
            "tivoo_bluetooth_mac": "11:75:58:97:49:98",
        },
        version=2,
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    adapter = None

    try:
        assert await hass.config_entries.async_setup(entry.entry_id)
        adapter = hass.data[DOMAIN][entry.entry_id]["connection_adapter"]
        await _wait_for_state(adapter, "control", "connected")
        await _wait_for_state(adapter, "diagnostic", "connected")

        assert await hass.config_entries.async_unload(entry.entry_id)
        assert adapter.states == {"control": "stopped", "diagnostic": "stopped"}
    finally:
        if adapter is not None:
            await adapter.async_stop()
        control_server.close()
        diagnostic_server.close()
        await _close_clients(control_clients + diagnostic_clients)
        await control_server.wait_closed()
        await diagnostic_server.wait_closed()
