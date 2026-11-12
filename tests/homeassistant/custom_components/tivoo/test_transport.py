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
    control_mac_received = asyncio.Event()

    async def control_handler(reader, writer):
        control_clients.append(writer)
        control_macs.append(await reader.readexactly(7))
        control_mac_received.set()
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
        await asyncio.wait_for(control_mac_received.wait(), 1)
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


async def _read_tvio_frame(reader):
    import struct

    header = await reader.readexactly(16)
    magic, version, message_type, flags, payload_length, sequence = struct.unpack(
        "<4sBBHII", header
    )
    assert (magic, version, flags) == (b"TVIO", 1, 0)
    return message_type, sequence, await reader.readexactly(payload_length)


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
            "capabilities": [
                "spp_control",
                "spp_reverse",
                "remote_diagnostics",
                "device_status",
                "device_events",
                "audio_resource_http",
                "audio_control",
            ],
            "reset_reason": "ESP_RST_POWERON",
        }
        writer.write(_tvio_message(0x01, 0, json.dumps(hello).encode()))
        await writer.drain()
        acknowledgements.append(await _read_tvio_message(reader))
        status_request = await _read_tvio_message(reader)
        assert status_request[0:2] == (0x10, 1)
        assert status_request[2]["request_id"]
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
            "capabilities": [
                "spp_control",
                "spp_reverse",
                "remote_diagnostics",
                "device_status",
                "device_events",
                "audio_resource_http",
                "audio_control",
            ],
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
            "capabilities": [
                "spp_control",
                "spp_reverse",
                "remote_diagnostics",
                "device_status",
                "device_events",
                "audio_resource_http",
                "audio_control",
            ],
            "reset_reason": "ESP_RST_POWERON",
        }
        writer.write(_tvio_message(0x01, 0, json.dumps(hello).encode()))
        await writer.drain()
        acknowledgements.append(await _read_tvio_message(reader))
        status_request = await _read_tvio_message(reader)
        assert status_request[0:2] == (0x10, 1)
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


async def test_bidirectional_message_handler_and_outbound_sequence(
    monkeypatch, socket_enabled
):
    import json

    from custom_components.tivoo.diagnostics import (
        TYPE_DEVICE_STATUS,
        TYPE_GET_STATUS,
        TYPE_MIC_CAPTURE_STOP,
        DiagnosticMessage,
    )

    handled = asyncio.Event()
    received = []
    sent = []
    status_requests = []

    async def handler(message: DiagnosticMessage):
        received.append(message)
        handled.set()

    async def diagnostic_handler(reader, writer):
        hello = {
            "device_id": "tivoo-esp32",
            "firmware_version": "0.1.0+abcdef0",
            "protocol_version": 1,
            "capabilities": [
                "spp_control",
                "spp_reverse",
                "remote_diagnostics",
                "device_status",
                "device_events",
                "audio_resource_http",
                "audio_control",
            ],
            "reset_reason": "ESP_RST_POWERON",
        }
        writer.write(_tvio_message(0x01, 0, json.dumps(hello).encode()))
        await writer.drain()
        assert await _read_tvio_message(reader) == (0x02, 0, {"accepted": True})
        status_request = await _read_tvio_message(reader)
        assert status_request[0:2] == (TYPE_GET_STATUS, 1)
        status_requests.append(status_request)
        status_payload = {
            "request_id": status_request[2]["request_id"],
            "device_id": "tivoo-esp32",
            "firmware_version": "0.1.0+abcdef0",
            "uptime_ms": 10,
            "wifi": {"state": "disconnected"},
            "tcp": {"7777": "connected", "7778": "connected"},
            "spp": {"state": "disconnected"},
            "audio_resource": {"state": "idle", "playback_id": None},
        }
        writer.write(
            _tvio_message(TYPE_DEVICE_STATUS, 1, json.dumps(status_payload).encode())
        )
        await writer.drain()
        sent.append(await _read_tvio_message(reader))
        await reader.read()

    async def control_handler(reader, writer):
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
    adapter.register_message_handler(TYPE_DEVICE_STATUS, handler)
    with pytest.raises(HomeAssistantError, match="handshake"):
        await adapter.async_send_message(TYPE_MIC_CAPTURE_STOP, b"{}")

    await adapter.async_start()
    try:
        await asyncio.wait_for(handled.wait(), timeout=2)
        await adapter.async_send_message(TYPE_MIC_CAPTURE_STOP, b'{"session_id":"s1"}')
        for _ in range(100):
            if sent:
                break
            await asyncio.sleep(0.01)

        assert len(received) == 1
        assert received[0].message_type == TYPE_DEVICE_STATUS
        assert received[0].sequence == 1
        assert (
            json.loads(received[0].payload)["request_id"]
            == status_requests[0][2]["request_id"]
        )
        assert sent == [(TYPE_MIC_CAPTURE_STOP, 2, {"session_id": "s1"})]
        assert adapter.states["diagnostic"] == "connected"
    finally:
        await adapter.async_stop()
        control_server.close()
        diagnostic_server.close()
        await control_server.wait_closed()
        await diagnostic_server.wait_closed()


async def test_unknown_message_is_reported_once_and_next_frame_is_processed(
    monkeypatch, socket_enabled, caplog
):
    import json
    import logging

    caplog.set_level(logging.INFO)

    async def control_handler(reader, writer):
        await reader.read()

    async def diagnostic_handler(reader, writer):
        hello = {
            "device_id": "tivoo-esp32",
            "firmware_version": "0.1.0+abcdef0",
            "protocol_version": 1,
            "capabilities": [
                "spp_control",
                "spp_reverse",
                "remote_diagnostics",
                "device_status",
                "device_events",
                "audio_resource_http",
                "audio_control",
            ],
            "reset_reason": "ESP_RST_POWERON",
        }
        writer.write(_tvio_message(0x01, 0, json.dumps(hello).encode()))
        await writer.drain()
        await _read_tvio_message(reader)
        valid = {
            "level": "INFO",
            "module": "wifi_station",
            "message": "after_unknown_type",
            "uptime_ms": 99,
        }
        writer.write(
            _tvio_message(0x7F, 1, b"future-message")
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
        await _wait_for_log(caplog, "after_unknown_type")
        assert caplog.text.count("protocol_unsupported_message") == 1
        assert adapter.states["diagnostic"] == "connected"
    finally:
        await adapter.async_stop()
        control_server.close()
        diagnostic_server.close()
        await control_server.wait_closed()
        await diagnostic_server.wait_closed()


async def test_control_reverse_consumer_receives_raw_bytes_unchanged():
    adapter = transport.Esp32ConnectionAdapter("127.0.0.1", "11:75:58:97:49:98")
    received = asyncio.Queue()
    adapter.register_spp_reverse_handler(received.put)
    adapter.spp_hint = "unknown"

    await adapter._handle_control_data(b"\x01\x69\x96\x02")

    assert await received.get() == b"\x01\x69\x96\x02"
    assert adapter.spp_hint == "unknown"


async def test_control_single_byte_status_hints_are_not_raw_payloads():
    adapter = transport.Esp32ConnectionAdapter("127.0.0.1", "11:75:58:97:49:98")
    received = asyncio.Queue()
    adapter.register_spp_reverse_handler(received.put)
    adapter.spp_hint = "unknown"

    await adapter._handle_control_data(b"\x69")
    assert adapter.spp_hint == "connecting"
    await adapter._handle_control_data(b"\x96")
    assert adapter.spp_hint == "disconnected"
    assert received.empty()

    await adapter._handle_control_data(b"\x69\x96")
    assert await received.get() == b"\x69\x96"
    assert adapter.spp_hint == "disconnected"


async def test_reverse_queue_full_error_code_is_accepted(caplog):
    import logging

    adapter = transport.Esp32ConnectionAdapter("127.0.0.1", "11:75:58:97:49:98")
    caplog.set_level(logging.ERROR)
    adapter._log_error(
        {
            "error_code": "reverse_queue_full",
            "module": "control_bridge",
            "message": "SPP reverse queue full",
            "uptime_ms": 123,
        }
    )

    assert "reverse_queue_full" in caplog.text


async def test_control_tcp_reader_forwards_raw_spp_data_to_registered_consumer(
    monkeypatch, socket_enabled
):
    received = asyncio.Queue()

    async def control_handler(reader, writer):
        await reader.readexactly(7)
        writer.write(bytes.fromhex("10 69 96 00 FE"))
        await writer.drain()
        await reader.read()

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
    adapter.register_spp_reverse_handler(received.put)
    try:
        await adapter.async_start()
        await _wait_for_state(adapter, "control", "connected")
        assert await asyncio.wait_for(received.get(), 1) == bytes.fromhex(
            "10 69 96 00 FE"
        )
        assert adapter.spp_hint == "unknown"
    finally:
        await adapter.async_stop()
        control_server.close()
        diagnostic_server.close()
        await control_server.wait_closed()
        await diagnostic_server.wait_closed()


class _FakeHeartbeatClock:
    def __init__(self):
        self.now = 0.0
        self.waiters = []

    def time(self):
        return self.now

    async def sleep(self, delay):
        if delay <= 0:
            await asyncio.sleep(0)
            return
        future = asyncio.get_running_loop().create_future()
        self.waiters.append((self.now + delay, future))
        await future

    def advance(self, seconds):
        self.now += seconds
        remaining = []
        for deadline, future in self.waiters:
            if deadline <= self.now and not future.done():
                future.set_result(None)
            else:
                remaining.append((deadline, future))
        self.waiters = remaining


async def _flush_asyncio():
    for _ in range(8):
        await asyncio.sleep(0)


async def test_diagnostic_heartbeat_sends_get_status_and_reconnects_only_7778(
    monkeypatch, socket_enabled
):
    import json

    from custom_components.tivoo.diagnostics import TYPE_GET_STATUS, TYPE_PING

    clock = _FakeHeartbeatClock()
    control_clients = []
    diagnostic_clients = []
    pings = asyncio.Queue()
    status_requests = []
    diagnostic_disconnected = asyncio.Event()

    async def control_handler(reader, writer):
        control_clients.append(writer)
        await reader.read()

    async def diagnostic_handler(reader, writer):
        diagnostic_clients.append(writer)
        hello = {
            "device_id": "tivoo-esp32",
            "firmware_version": "0.1.0+abcdef0",
            "protocol_version": 1,
            "capabilities": [
                "spp_control",
                "spp_reverse",
                "remote_diagnostics",
                "device_status",
                "device_events",
                "audio_resource_http",
                "audio_control",
            ],
            "reset_reason": "ESP_RST_POWERON",
        }
        writer.write(_tvio_message(0x01, 0, json.dumps(hello).encode()))
        await writer.drain()
        assert await _read_tvio_message(reader) == (0x02, 0, {"accepted": True})
        status_requests.append(await _read_tvio_message(reader))
        try:
            while True:
                message = await _read_tvio_frame(reader)
                if message[0] == TYPE_PING:
                    await pings.put(message)
        except (asyncio.IncompleteReadError, ConnectionError):
            diagnostic_disconnected.set()

    control_server = await asyncio.start_server(control_handler, "127.0.0.1", 0)
    diagnostic_server = await asyncio.start_server(diagnostic_handler, "127.0.0.1", 0)
    monkeypatch.setattr(
        transport, "CONTROL_PORT", control_server.sockets[0].getsockname()[1]
    )
    monkeypatch.setattr(
        transport, "DIAGNOSTIC_PORT", diagnostic_server.sockets[0].getsockname()[1]
    )

    adapter = transport.Esp32ConnectionAdapter(
        "127.0.0.1",
        "11:75:58:97:49:98",
        retry_interval=5,
        clock=clock.time,
        heartbeat_sleep=clock.sleep,
    )
    await adapter.async_start()
    try:
        await _wait_for_state(adapter, "control", "connected")
        await _wait_for_state(adapter, "diagnostic", "connected")
        for _ in range(100):
            if status_requests:
                break
            await asyncio.sleep(0.01)
        assert len(status_requests) == 1
        status_type, status_sequence, request = status_requests[0]
        assert status_type == TYPE_GET_STATUS
        assert status_sequence == 1
        assert isinstance(request["request_id"], str) and request["request_id"]

        clock.advance(15)
        await _flush_asyncio()
        assert await asyncio.wait_for(pings.get(), 1) == (TYPE_PING, 2, b"")
        diagnostic_clients[0].write(_tvio_message(0x04, 1, b""))
        await diagnostic_clients[0].drain()
        await _flush_asyncio()
        assert adapter._diagnostic_last_pong_at == 15.0

        clock.advance(14)
        await _flush_asyncio()
        assert pings.empty()
        clock.advance(1)
        await _flush_asyncio()
        assert await asyncio.wait_for(pings.get(), 1) == (TYPE_PING, 3, b"")

        clock.advance(29)  # 44 seconds since the valid PONG.
        await _flush_asyncio()
        assert adapter.states["diagnostic"] == "connected"
        clock.advance(1)  # 45 seconds since the valid PONG.
        await asyncio.wait_for(diagnostic_disconnected.wait(), 1)
        await _wait_for_state(adapter, "diagnostic", "disconnected")
        assert adapter.states["control"] == "connected"
        assert len(control_clients) == 1
        for _ in range(700):
            if len(status_requests) >= 2:
                break
            await asyncio.sleep(0.01)
        assert (
            len(status_requests) == 2
        )  # 7778 reconnected and requested a fresh snapshot.
        assert len(control_clients) == 1
    finally:
        await adapter.async_stop()
        control_server.close()
        diagnostic_server.close()
        await _close_clients(control_clients + diagnostic_clients)
        await control_server.wait_closed()
        await diagnostic_server.wait_closed()


async def test_invalid_pong_does_not_refresh_diagnostic_liveness(
    monkeypatch, socket_enabled
):
    import json

    from custom_components.tivoo.diagnostics import TYPE_PING

    clock = _FakeHeartbeatClock()
    diagnostic_clients = []
    pings = asyncio.Queue()
    closed = asyncio.Event()
    initial_status_received = asyncio.Event()

    async def control_handler(reader, writer):
        await reader.read()

    async def diagnostic_handler(reader, writer):
        diagnostic_clients.append(writer)
        hello = {
            "device_id": "tivoo-esp32",
            "firmware_version": "0.1.0+abcdef0",
            "protocol_version": 1,
            "capabilities": [
                "spp_control",
                "spp_reverse",
                "remote_diagnostics",
                "device_status",
                "device_events",
                "audio_resource_http",
                "audio_control",
            ],
            "reset_reason": "ESP_RST_POWERON",
        }
        writer.write(_tvio_message(0x01, 0, json.dumps(hello).encode()))
        await writer.drain()
        await _read_tvio_message(reader)
        await _read_tvio_message(reader)  # Initial GET_STATUS.
        initial_status_received.set()
        try:
            while True:
                message = await _read_tvio_frame(reader)
                if message[0] == TYPE_PING:
                    await pings.put(message)
        except (asyncio.IncompleteReadError, ConnectionError):
            closed.set()

    control_server = await asyncio.start_server(control_handler, "127.0.0.1", 0)
    diagnostic_server = await asyncio.start_server(diagnostic_handler, "127.0.0.1", 0)
    monkeypatch.setattr(
        transport, "CONTROL_PORT", control_server.sockets[0].getsockname()[1]
    )
    monkeypatch.setattr(
        transport, "DIAGNOSTIC_PORT", diagnostic_server.sockets[0].getsockname()[1]
    )
    adapter = transport.Esp32ConnectionAdapter(
        "127.0.0.1",
        "11:75:58:97:49:98",
        retry_interval=5,
        clock=clock.time,
        heartbeat_sleep=clock.sleep,
    )
    await adapter.async_start()
    try:
        await _wait_for_state(adapter, "diagnostic", "connected")
        await asyncio.wait_for(initial_status_received.wait(), 1)
        clock.advance(15)
        await _flush_asyncio()
        assert await asyncio.wait_for(pings.get(), 1) == (TYPE_PING, 2, b"")
        diagnostic_clients[0].write(_tvio_message(0x04, 1, b"not-empty"))
        await diagnostic_clients[0].drain()
        clock.advance(30)
        await _flush_asyncio()
        await asyncio.wait_for(closed.wait(), 1)
        await _wait_for_state(adapter, "diagnostic", "disconnected")
    finally:
        await adapter.async_stop()
        control_server.close()
        diagnostic_server.close()
        await _close_clients(diagnostic_clients)
        await control_server.wait_closed()
        await diagnostic_server.wait_closed()


async def test_device_status_and_event_validation_updates_only_known_state(
    monkeypatch, socket_enabled
):
    import json

    from custom_components.tivoo.diagnostics import (
        TYPE_DEVICE_EVENT,
        TYPE_DEVICE_STATUS,
    )

    handled = []
    status_requests = []

    async def handler(message):
        handled.append(message)

    async def control_handler(reader, writer):
        await reader.read()

    async def diagnostic_handler(reader, writer):
        hello = {
            "device_id": "tivoo-esp32",
            "firmware_version": "0.1.0+abcdef0",
            "protocol_version": 1,
            "capabilities": [
                "spp_control",
                "spp_reverse",
                "remote_diagnostics",
                "device_status",
                "device_events",
                "audio_resource_http",
                "audio_control",
            ],
            "reset_reason": "ESP_RST_POWERON",
        }
        writer.write(_tvio_message(0x01, 0, json.dumps(hello).encode()))
        await writer.drain()
        await _read_tvio_message(reader)
        status_request = await _read_tvio_message(reader)  # Initial GET_STATUS.
        status_requests.append(status_request)
        request_id = status_request[2]["request_id"]
        messages = [
            (TYPE_DEVICE_STATUS, {"request_id": "bad", "uptime_ms": True}),
            (
                TYPE_DEVICE_STATUS,
                {
                    "request_id": request_id,
                    "device_id": "tivoo-esp32",
                    "firmware_version": "0.1.0+abcdef0",
                    "uptime_ms": 10,
                    "wifi": {
                        "state": "connected",
                        "ip": "192.168.3.28",
                        "unknown": "drop",
                    },
                    "tcp": {"7777": "connected", "7778": "connected"},
                    "spp": {"state": "connected", "mac": "11:75:58:97:49:98"},
                    "audio_resource": {"state": "idle", "playback_id": None},
                    "unknown": "drop",
                },
            ),
            (
                TYPE_DEVICE_EVENT,
                {"event": "not_a_contract_event", "uptime_ms": 11, "data": {}},
            ),
            (TYPE_DEVICE_EVENT, {"event": "spp_connected", "uptime_ms": 11}),
            (
                TYPE_DEVICE_EVENT,
                {"event": "spp_disconnected", "uptime_ms": 12, "data": {}},
            ),
        ]
        for sequence, (message_type, payload) in enumerate(messages, start=1):
            writer.write(
                _tvio_message(message_type, sequence, json.dumps(payload).encode())
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
    adapter.register_message_handler(TYPE_DEVICE_STATUS, handler)
    adapter.register_message_handler(TYPE_DEVICE_EVENT, handler)
    await adapter.async_start()
    try:
        for _ in range(100):
            if len(handled) == 2:
                break
            await asyncio.sleep(0.01)
        assert [message.message_type for message in handled] == [
            TYPE_DEVICE_STATUS,
            TYPE_DEVICE_EVENT,
        ]
        assert (
            adapter.device_status["request_id"] == status_requests[0][2]["request_id"]
        )
        assert "unknown" not in adapter.device_status
        assert "unknown" not in adapter.device_status["wifi"]
        assert adapter.device_status["spp"]["state"] == "disconnected"
        assert adapter.last_device_event["event"] == "spp_disconnected"
    finally:
        await adapter.async_stop()
        control_server.close()
        diagnostic_server.close()
        await control_server.wait_closed()
        await diagnostic_server.wait_closed()


async def test_p6_error_codes_are_accepted_and_sensitive_diagnostic_text_is_redacted(
    caplog,
):
    import logging

    adapter = transport.Esp32ConnectionAdapter("127.0.0.1", "11:75:58:97:49:98")
    caplog.set_level(logging.DEBUG)
    for code in (
        "protocol_invalid_header",
        "protocol_invalid_payload",
        "audio_busy",
        "audio_http_failed",
        "audio_http_status",
        "audio_content_type_mismatch",
        "operation_cancelled",
    ):
        adapter._log_error(
            {
                "error_code": code,
                "module": "audio_resource",
                "message": "request failed",
                "uptime_ms": 1,
            }
        )
    adapter._log_error(
        {
            "error_code": "audio_http_failed",
            "module": "audio_resource",
            "message": (
                "GET https://nas.local/audio?token=url-secret "
                "Bearer bearer-secret password=wifi-secret pcm=01020304"
            ),
            "uptime_ms": 2,
        }
    )
    adapter._log_diagnostic(
        {
            "level": "INFO",
            "module": "audio_resource",
            "message": "resource https://nas.local/audio?token=log-secret",
            "uptime_ms": 3,
        }
    )

    for secret in (
        "url-secret",
        "bearer-secret",
        "wifi-secret",
        "01020304",
        "log-secret",
    ):
        assert secret not in caplog.text
    assert caplog.text.count("audio_http_failed") >= 2


async def test_audio_session_messages_dispatch_binary_pcm_and_interruption(
    monkeypatch, socket_enabled
):
    import json

    from custom_components.tivoo.audio_session import AudioSessionManager
    from custom_components.tivoo.diagnostics import (
        TYPE_AUDIO_INTERRUPTED,
        TYPE_GET_STATUS,
        TYPE_MIC_PCM,
        TYPE_MIC_SESSION_END,
        TYPE_MIC_SESSION_START,
    )

    session_id = "11111111-1111-4111-8111-111111111111"
    interrupt_id = "33333333-3333-4333-8333-333333333333"
    audio_id = "44444444-4444-4444-8444-444444444444"
    pcm = bytes(range(256)) * 2 + bytes(range(128))
    iterator_ready = asyncio.Event()
    handled_interrupts = []

    async def control_handler(reader, writer):
        await reader.read()

    async def diagnostic_handler(reader, writer):
        hello = {
            "device_id": "tivoo-esp32",
            "firmware_version": "0.1.0+abcdef0",
            "protocol_version": 1,
            "capabilities": [
                "spp_control",
                "spp_reverse",
                "remote_diagnostics",
                "device_status",
                "device_events",
                "audio_resource_http",
                "audio_control",
            ],
            "reset_reason": "ESP_RST_POWERON",
        }
        writer.write(_tvio_message(0x01, 0, json.dumps(hello).encode()))
        await writer.drain()
        assert (await _read_tvio_message(reader))[0:2] == (0x02, 0)
        status_request = await _read_tvio_message(reader)
        assert status_request[0:2] == (TYPE_GET_STATUS, 1)

        invalid_start = {
            "session_id": session_id,
            "sample_rate": 8000,
            "channels": 1,
            "sample_format": "s16le",
            "frame_duration_ms": 20,
            "preroll_ms": 500,
            "trigger_source": "idle_vad",
        }
        invalid_frame = _tvio_message(
            TYPE_MIC_SESSION_START, 1, json.dumps(invalid_start).encode()
        )
        writer.write(invalid_frame[:7])
        await writer.drain()

        valid_start = dict(invalid_start, sample_rate=16000)
        valid_frame = _tvio_message(
            TYPE_MIC_SESSION_START, 2, json.dumps(valid_start).encode()
        )
        writer.write(invalid_frame[7:] + valid_frame)
        await writer.drain()
        await iterator_ready.wait()

        stale_end = _tvio_message(
            TYPE_MIC_SESSION_END,
            3,
            json.dumps(
                {"session_id": "22222222-2222-4222-8222-222222222222", "reason": "late"}
            ).encode(),
        )
        writer.write(
            stale_end
            + _tvio_message(TYPE_MIC_PCM, 4, pcm)
            + _tvio_message(
                TYPE_MIC_SESSION_END,
                5,
                json.dumps({"session_id": session_id, "reason": "completed"}).encode(),
            )
            + _tvio_message(
                TYPE_AUDIO_INTERRUPTED,
                6,
                json.dumps(
                    {
                        "interrupt_id": interrupt_id,
                        "audio_id": audio_id,
                        "source": "tts_http",
                        "reason": "near_end_vad",
                    }
                ).encode(),
            )
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

    manager = AudioSessionManager()

    async def on_interrupted(payload):
        handled_interrupts.append(payload)

    manager.register_audio_interrupted_handler(on_interrupted)
    adapter = transport.Esp32ConnectionAdapter(
        "127.0.0.1", "11:75:58:97:49:98", retry_interval=5
    )
    adapter.register_audio_session_manager(manager)
    await adapter.async_start()
    try:
        for _ in range(200):
            if manager.active_session_id == session_id:
                break
            await asyncio.sleep(0.01)
        assert manager.active_session_id == session_id
        iterator = manager.async_audio_iterator(session_id)
        iterator_ready.set()

        received = await asyncio.wait_for(_collect_audio(iterator), timeout=2)
        for _ in range(200):
            if handled_interrupts:
                break
            await asyncio.sleep(0.01)
        assert received == [pcm]
        assert handled_interrupts == [
            {
                "interrupt_id": interrupt_id,
                "audio_id": audio_id,
                "source": "tts_http",
                "reason": "near_end_vad",
            }
        ]
        assert adapter.states["diagnostic"] == "connected"
    finally:
        await manager.async_shutdown()
        await adapter.async_stop()
        control_server.close()
        diagnostic_server.close()
        await control_server.wait_closed()
        await diagnostic_server.wait_closed()


async def _collect_audio(iterator):
    return [chunk async for chunk in iterator]
