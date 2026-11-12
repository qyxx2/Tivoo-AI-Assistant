"""Tests for the Tivoo ESP32 connection lifecycle."""

import asyncio

import pytest
from custom_components.tivoo import transport
from custom_components.tivoo.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
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

    adapter = transport.Esp32ConnectionAdapter(
        "127.0.0.1", "11:75:58:97:49:98", retry_interval=0.05
    )
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


async def test_command_execution_requires_a_connected_control_channel():
    adapter = transport.Esp32ConnectionAdapter("127.0.0.1", "11:75:58:97:49:98")

    with pytest.raises(HomeAssistantError, match="control channel"):
        await adapter.async_execute(
            transport.TivooCommand(name="set_brightness", data={"value": 50})
        )


async def test_config_entry_starts_and_stops_both_connections(
    hass, socket_enabled, monkeypatch
):
    control_clients = []
    diagnostic_clients = []
    control_macs = []

    async def control_handler(reader, writer):
        control_clients.append(writer)
        control_macs.append(await reader.readexactly(7))
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
        assert control_macs == [bytes.fromhex("69 11 75 58 97 49 98")]

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


def _tvio_message(message_type, sequence, payload):
    """Build a test frame independently from the production codec."""
    import struct

    return (
        struct.pack("<4sBBHII", b"TVIO", 1, message_type, 0, len(payload), sequence)
        + payload
    )


async def _read_tvio_message(reader):
    import json
    import struct

    header = await reader.readexactly(16)
    magic, version, message_type, flags, payload_length, sequence = struct.unpack(
        "<4sBBHII", header
    )
    assert (magic, version, flags) == (b"TVIO", 1, 0)
    payload = await reader.readexactly(payload_length)
    return message_type, sequence, json.loads(payload)


async def _wait_for_log(caplog, expected):
    for _ in range(300):
        if expected in caplog.text:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"log {expected!r} was not emitted: {caplog.text}")


async def test_diagnostic_handshake_and_device_messages_use_standard_logger(
    monkeypatch, socket_enabled, caplog
):
    import json
    import logging

    caplog.set_level(logging.DEBUG)
    control_clients = []
    acknowledgements = []

    async def control_handler(reader, writer):
        control_clients.append(writer)
        await reader.read()

    async def diagnostic_handler(reader, writer):
        hello = {
            "device_id": "tivoo-esp32",
            "firmware_version": "0.1.0+abcdef0",
            "protocol_version": 1,
            "capabilities": ["spp_control", "remote_diagnostics"],
            "reset_reason": "ESP_RST_POWERON",
        }
        writer.write(_tvio_message(0x01, 0, json.dumps(hello).encode()))
        await writer.drain()
        acknowledgements.append(await _read_tvio_message(reader))
        events = [
            {
                "level": "WARNING",
                "module": "wifi_station",
                "message": "station_connected",
                "uptime_ms": 12345,
                "dropped_count": 2,
            },
            {
                "error_code": "spp_connect_failed",
                "module": "tivoo_spp",
                "message": "Classic SPP connection failed",
                "uptime_ms": 45678,
            },
            {
                "level": "DEBUG",
                "module": "wifi_station",
                "message": "verbose_internal_event",
                "uptime_ms": 45679,
            },
        ]
        writer.write(
            _tvio_message(0x42, 1, json.dumps(events[0]).encode())
            + _tvio_message(0x41, 2, json.dumps(events[1]).encode())
            + _tvio_message(0x42, 3, json.dumps(events[2]).encode())
        )
        await writer.drain()
        await reader.read()

    control_server = await asyncio.start_server(control_handler, "127.0.0.1", 0)
    diagnostic_server = await asyncio.start_server(diagnostic_handler, "127.0.0.1", 0)
    monkeypatch.setattr(
        transport, "CONTROL_PORT", control_server.sockets[0].getsockname()[1]
    )
    monkeypatch.setattr(
        transport, "DIAGNOSTIC_PORT", diagnostic_server.sockets[0].getsockname()[1]
    )

    adapter = transport.Esp32ConnectionAdapter(
        "127.0.0.1", "11:75:58:97:49:98", retry_interval=5
    )
    await adapter.async_start()
    try:
        await _wait_for_state(adapter, "control", "connected")
        await _wait_for_state(adapter, "diagnostic", "connected")
        await _wait_for_log(caplog, "station_connected")
        await _wait_for_log(caplog, "Classic SPP connection failed")
        await _wait_for_log(caplog, "verbose_internal_event")

        assert acknowledgements == [(0x02, 0, {"accepted": True})]
        assert any(
            record.levelno == logging.WARNING
            and "station_connected" in record.message
            and "dropped_count=2" in record.message
            for record in caplog.records
        )
        assert any(
            record.levelno == logging.ERROR and "spp_connect_failed" in record.message
            for record in caplog.records
        )
        assert any(
            record.levelno == logging.DEBUG
            and "verbose_internal_event" in record.message
            for record in caplog.records
        )
        assert adapter.states["control"] == "connected"
        assert len(control_clients) == 1
    finally:
        await adapter.async_stop()
        control_server.close()
        diagnostic_server.close()
        await _close_clients(control_clients)
        await control_server.wait_closed()
        await diagnostic_server.wait_closed()


async def test_unsupported_hello_protocol_is_rejected_and_closes_only_diagnostic(
    monkeypatch, socket_enabled
):
    import json

    acknowledgements = []
    control_clients = []

    async def control_handler(reader, writer):
        control_clients.append(writer)
        await reader.read()

    async def diagnostic_handler(reader, writer):
        hello = {
            "device_id": "tivoo-esp32",
            "firmware_version": "0.1.0+abcdef0",
            "protocol_version": 2,
            "capabilities": ["spp_control", "remote_diagnostics"],
            "reset_reason": "ESP_RST_POWERON",
        }
        writer.write(_tvio_message(0x01, 0, json.dumps(hello).encode()))
        await writer.drain()
        acknowledgements.append(await _read_tvio_message(reader))
        await reader.read()

    control_server = await asyncio.start_server(control_handler, "127.0.0.1", 0)
    diagnostic_server = await asyncio.start_server(diagnostic_handler, "127.0.0.1", 0)
    monkeypatch.setattr(
        transport, "CONTROL_PORT", control_server.sockets[0].getsockname()[1]
    )
    monkeypatch.setattr(
        transport, "DIAGNOSTIC_PORT", diagnostic_server.sockets[0].getsockname()[1]
    )

    adapter = transport.Esp32ConnectionAdapter(
        "127.0.0.1", "11:75:58:97:49:98", retry_interval=10
    )
    await adapter.async_start()
    try:
        await _wait_for_state(adapter, "control", "connected")
        await _wait_for_state(adapter, "diagnostic", "disconnected")
        assert acknowledgements == [
            (
                0x02,
                0,
                {"accepted": False, "reason": "unsupported_protocol_version"},
            )
        ]
        assert adapter.states["control"] == "connected"
        assert len(control_clients) == 1
    finally:
        await adapter.async_stop()
        control_server.close()
        diagnostic_server.close()
        await _close_clients(control_clients)
        await control_server.wait_closed()
        await diagnostic_server.wait_closed()


async def test_invalid_diagnostic_json_is_ignored_without_losing_connection(
    monkeypatch, socket_enabled, caplog
):
    import json

    acknowledgements = []

    async def control_handler(reader, writer):
        await reader.read()

    async def diagnostic_handler(reader, writer):
        hello = {
            "device_id": "tivoo-esp32",
            "firmware_version": "0.1.0+abcdef0",
            "protocol_version": 1,
            "capabilities": ["spp_control", "remote_diagnostics"],
            "reset_reason": "ESP_RST_POWERON",
        }
        writer.write(_tvio_message(0x01, 0, json.dumps(hello).encode()))
        await writer.drain()
        acknowledgements.append(await _read_tvio_message(reader))
        valid = {
            "level": "INFO",
            "module": "wifi_station",
            "message": "still_connected",
            "uptime_ms": 987,
        }
        writer.write(
            _tvio_message(0x42, 1, b"{invalid-json")
            + _tvio_message(0x42, 2, json.dumps(valid).encode())
        )
        await writer.drain()
        await reader.read()

    control_server = await asyncio.start_server(control_handler, "127.0.0.1", 0)
    diagnostic_server = await asyncio.start_server(diagnostic_handler, "127.0.0.1", 0)
    monkeypatch.setattr(
        transport, "CONTROL_PORT", control_server.sockets[0].getsockname()[1]
    )
    monkeypatch.setattr(
        transport, "DIAGNOSTIC_PORT", diagnostic_server.sockets[0].getsockname()[1]
    )

    adapter = transport.Esp32ConnectionAdapter(
        "127.0.0.1", "11:75:58:97:49:98", retry_interval=5
    )
    await adapter.async_start()
    try:
        await _wait_for_log(caplog, "still_connected")
        assert acknowledgements == [(0x02, 0, {"accepted": True})]
        assert "invalid JSON" in caplog.text
        assert adapter.states["diagnostic"] == "connected"
    finally:
        await adapter.async_stop()
        control_server.close()
        diagnostic_server.close()
        await control_server.wait_closed()
        await diagnostic_server.wait_closed()


async def test_control_connection_sends_authoritative_mac_and_encoded_commands(
    monkeypatch, socket_enabled
):
    from custom_components.tivoo.protocol import encode_command

    received = []

    async def control_handler(reader, writer):
        received.append(await reader.readexactly(7))
        received.append(await reader.readexactly(8))
        await reader.read()
        writer.close()
        await writer.wait_closed()

    async def diagnostic_handler(reader, writer):
        await reader.read()

    control_server = await asyncio.start_server(control_handler, "127.0.0.1", 0)
    diagnostic_server = await asyncio.start_server(diagnostic_handler, "127.0.0.1", 0)
    monkeypatch.setattr(
        transport, "CONTROL_PORT", control_server.sockets[0].getsockname()[1]
    )
    monkeypatch.setattr(
        transport, "DIAGNOSTIC_PORT", diagnostic_server.sockets[0].getsockname()[1]
    )
    adapter = transport.Esp32ConnectionAdapter(
        "127.0.0.1", "11:75:58:97:49:98", retry_interval=5
    )
    try:
        await adapter.async_start()
        await _wait_for_state(adapter, "control", "connected")
        command = transport.TivooCommand("set_brightness", {"value": 100})
        await adapter.async_execute(command)
        for _ in range(100):
            if len(received) == 2:
                break
            await asyncio.sleep(0.01)
        assert received[0] == bytes.fromhex("69 11 75 58 97 49 98")
        assert received[1] == encode_command(command)[0]
    finally:
        await adapter.async_stop()
        control_server.close()
        diagnostic_server.close()
        await control_server.wait_closed()
        await diagnostic_server.wait_closed()


async def test_new_config_entry_mac_is_sent_after_adapter_replacement(
    monkeypatch, socket_enabled
):
    received = []

    async def control_handler(reader, writer):
        received.append(await reader.readexactly(7))
        await reader.read()
        writer.close()
        await writer.wait_closed()

    async def diagnostic_handler(reader, writer):
        await reader.read()

    control_server = await asyncio.start_server(control_handler, "127.0.0.1", 0)
    diagnostic_server = await asyncio.start_server(diagnostic_handler, "127.0.0.1", 0)
    monkeypatch.setattr(
        transport, "CONTROL_PORT", control_server.sockets[0].getsockname()[1]
    )
    monkeypatch.setattr(
        transport, "DIAGNOSTIC_PORT", diagnostic_server.sockets[0].getsockname()[1]
    )
    adapters = [
        transport.Esp32ConnectionAdapter(
            "127.0.0.1", "11:75:58:97:49:98", retry_interval=5
        ),
        transport.Esp32ConnectionAdapter(
            "127.0.0.1", "AA:BB:CC:DD:EE:FF", retry_interval=5
        ),
    ]
    try:
        for adapter in adapters:
            await adapter.async_start()
            await _wait_for_state(adapter, "control", "connected")
            await asyncio.sleep(0.03)
            await adapter.async_stop()
        assert received[:2] == [
            bytes.fromhex("69 11 75 58 97 49 98"),
            bytes.fromhex("69 AA BB CC DD EE FF"),
        ]
    finally:
        for adapter in adapters:
            await adapter.async_stop()
        control_server.close()
        diagnostic_server.close()
        await control_server.wait_closed()
        await diagnostic_server.wait_closed()


async def test_config_entry_mac_change_reload_connects_the_new_peer(
    hass, socket_enabled, monkeypatch
):
    control_clients = []
    diagnostic_clients = []
    control_macs = []

    async def control_handler(reader, writer):
        control_clients.append(writer)
        control_macs.append(await reader.readexactly(7))
        await reader.read()
        writer.close()
        await writer.wait_closed()

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
        for _ in range(100):
            if len(control_macs) == 1:
                break
            await asyncio.sleep(0.01)
        assert control_macs == [bytes.fromhex("69 11 75 58 97 49 98")]

        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                "tivoo_bluetooth_mac": "AA:BB:CC:DD:EE:FF",
            },
        )
        assert await hass.config_entries.async_reload(entry.entry_id)

        reloaded_adapter = hass.data[DOMAIN][entry.entry_id]["connection_adapter"]
        assert reloaded_adapter is not adapter
        await _wait_for_state(reloaded_adapter, "control", "connected")
        await _wait_for_state(reloaded_adapter, "diagnostic", "connected")
        for _ in range(100):
            if len(control_macs) == 2:
                break
            await asyncio.sleep(0.01)
        assert control_macs == [
            bytes.fromhex("69 11 75 58 97 49 98"),
            bytes.fromhex("69 AA BB CC DD EE FF"),
        ]
        adapter = reloaded_adapter
    finally:
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
        if adapter is not None:
            await adapter.async_stop()
        control_server.close()
        diagnostic_server.close()
        await _close_clients(control_clients + diagnostic_clients)
        await control_server.wait_closed()
        await diagnostic_server.wait_closed()
