"""POSIX simulation of the production ESP32 TVIO diagnostics module."""

import json
import socket
import struct
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "esp32/firmware/main"
SIMULATOR = ROOT / "esp32/tests/p5b2_diagnostics_simulator/diagnostics_host.c"
CJSON = ROOT / "esp32/firmware/managed_components/espressif__cjson/cJSON/cJSON.c"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _read_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise AssertionError(f"socket closed after {len(chunks)} of {size} bytes")
        chunks.extend(chunk)
    return bytes(chunks)


def _wait_closed(sock: socket.socket) -> None:
    sock.settimeout(2)
    assert sock.recv(1) == b""


def _connect(port: int) -> socket.socket:
    deadline = time.monotonic() + 3
    last_error = None
    while time.monotonic() < deadline:
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=1)
        except OSError as err:
            last_error = err
            time.sleep(0.02)
    raise AssertionError(f"TCP listener {port} did not open: {last_error}")


def _read_frame(sock: socket.socket) -> tuple[int, int, dict]:
    header = _read_exact(sock, 16)
    magic, version, message_type, flags, payload_length, sequence = struct.unpack(
        "<4sBBHII", header
    )
    assert (magic, version, flags) == (b"TVIO", 1, 0)
    payload = json.loads(_read_exact(sock, payload_length))
    return message_type, sequence, payload


def _send_ack(sock: socket.socket, accepted: bool = True) -> None:
    payload = json.dumps({"accepted": accepted}, separators=(",", ":")).encode()
    sock.sendall(
        struct.pack("<4sBBHII", b"TVIO", 1, 0x02, 0, len(payload), 0) + payload
    )


def _send_ack_fragmented(sock: socket.socket) -> None:
    payload = b'{"accepted":true}'
    frame = struct.pack("<4sBBHII", b"TVIO", 1, 0x02, 0, len(payload), 0) + payload
    for boundary in (1, 5, 13, 18):
        if not frame:
            break
        chunk, frame = frame[:boundary], frame[boundary:]
        sock.sendall(chunk)
        time.sleep(0.12)
    if frame:
        sock.sendall(frame)


def _handshake(sock: socket.socket) -> dict:
    message_type, sequence, hello = _read_frame(sock)
    assert (message_type, sequence) == (0x01, 0)
    assert hello["device_id"] == "tivoo-esp32"
    assert hello["protocol_version"] == 1
    assert hello["capabilities"] == ["spp_control", "remote_diagnostics"]
    assert hello["firmware_version"].startswith("0.1.0+")
    assert hello["reset_reason"] == "ESP_RST_POWERON"
    _send_ack(sock)
    return hello


def _start_simulator(tmp_path: Path):
    binary = tmp_path / "p5b2-diagnostics-host"
    subprocess.run(
        [
            "gcc",
            "-std=c11",
            "-D_POSIX_C_SOURCE=200809L",
            "-DNETWORK_LISTENERS_HOST",
            "-DTIVOO_DIAGNOSTICS_HOST_TEST",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pthread",
            "-I",
            str(FIRMWARE),
            "-I",
            str(CJSON.parent),
            str(FIRMWARE / "network_listeners.c"),
            str(FIRMWARE / "diagnostics.c"),
            str(CJSON),
            str(SIMULATOR),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    control_port = _free_port()
    diagnostic_port = _free_port()
    while diagnostic_port == control_port:
        diagnostic_port = _free_port()
    process = subprocess.Popen(
        [str(binary), str(control_port), str(diagnostic_port)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return process, control_port, diagnostic_port


def _command(process: subprocess.Popen, value: str) -> None:
    assert process.stdin is not None
    process.stdin.write(value + "\n")
    process.stdin.flush()


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        _command(process, "exit")
        process.wait(timeout=3)
    if process.stdin is not None:
        process.stdin.close()


@pytest.mark.enable_socket
def test_hello_handshake_and_diagnostic_log_delivery(tmp_path):
    process, _, diagnostic_port = _start_simulator(tmp_path)
    client = None
    try:
        _command(process, "up")
        client = _connect(diagnostic_port)
        message_type, sequence, hello = _read_frame(client)
        assert (message_type, sequence) == (0x01, 0)
        assert hello["device_id"] == "tivoo-esp32"
        _send_ack_fragmented(client)

        _command(process, "log INFO wifi_station station_connected")
        message_type, sequence, payload = _read_frame(client)
        assert (message_type, sequence) == (0x42, 1)
        assert payload == {
            "level": "INFO",
            "module": "wifi_station",
            "message": "station_connected",
            "uptime_ms": payload["uptime_ms"],
        }
        assert isinstance(payload["uptime_ms"], int)
    finally:
        if client is not None:
            client.close()
        _stop(process)


@pytest.mark.enable_socket
def test_queued_records_survive_disconnect_and_replay_after_new_handshake(
    tmp_path,
):
    process, _, diagnostic_port = _start_simulator(tmp_path)
    first = second = None
    try:
        _command(process, "up")
        first = _connect(diagnostic_port)
        _handshake(first)

        _command(process, "down")
        _wait_closed(first)
        first.close()
        first = None

        _command(process, "log WARNING wifi_station queued_while_offline")
        _command(process, "up")
        second = _connect(diagnostic_port)
        _handshake(second)
        message_type, sequence, payload = _read_frame(second)

        assert (message_type, sequence) == (0x42, 1)
        assert payload["message"] == "queued_while_offline"
        assert payload["level"] == "WARNING"
    finally:
        if first is not None:
            first.close()
        if second is not None:
            second.close()
        _stop(process)


@pytest.mark.enable_socket
def test_queue_saturation_drops_new_records_and_reports_dropped_count(tmp_path):
    process, _, diagnostic_port = _start_simulator(tmp_path)
    client = None
    try:
        _command(process, "burst 20")
        _command(process, "up")
        client = _connect(diagnostic_port)
        _handshake(client)

        records = [_read_frame(client) for _ in range(16)]
        assert [item[0] for item in records] == [0x42] * 16
        assert [item[1] for item in records] == list(range(1, 17))
        assert [item[2]["message"] for item in records] == [
            f"burst-{index:03d}" for index in range(16)
        ]
        assert records[0][2]["dropped_count"] == 4
        assert all("dropped_count" not in item[2] for item in records[1:])
    finally:
        if client is not None:
            client.close()
        _stop(process)


@pytest.mark.enable_socket
def test_partial_tcp_record_failure_replays_whole_record_after_reconnect(tmp_path):
    process, _, diagnostic_port = _start_simulator(tmp_path)
    first = second = None
    try:
        _command(process, "up")
        first = _connect(diagnostic_port)
        _handshake(first)

        _command(process, "fail_after 8")
        _command(process, "log ERROR tivoo_spp retry_complete_record")
        partial_header = _read_exact(first, 8)
        assert partial_header == b"TVIO\x01\x42\x00\x00"
        _wait_closed(first)
        first.close()
        first = None
        # The listener polls client sockets every 100 ms; let it release the old slot.
        time.sleep(0.2)

        second = _connect(diagnostic_port)
        _handshake(second)
        message_type, sequence, payload = _read_frame(second)
        assert (message_type, sequence) == (0x42, 1)
        assert payload["message"] == "retry_complete_record"
        assert payload["level"] == "ERROR"
    finally:
        if first is not None:
            first.close()
        if second is not None:
            second.close()
        _stop(process)


@pytest.mark.enable_socket
def test_diagnostic_reconnect_does_not_close_control_connection(tmp_path):
    process, control_port, diagnostic_port = _start_simulator(tmp_path)
    control = diagnostic = replacement = None
    try:
        _command(process, "up")
        control = _connect(control_port)
        diagnostic = _connect(diagnostic_port)
        _handshake(diagnostic)

        diagnostic.shutdown(socket.SHUT_WR)
        _wait_closed(diagnostic)
        diagnostic.close()
        diagnostic = None
        control.settimeout(0.2)
        with pytest.raises(TimeoutError):
            control.recv(1)

        time.sleep(0.15)
        replacement = _connect(diagnostic_port)
        _handshake(replacement)
        control.settimeout(0.2)
        with pytest.raises(TimeoutError):
            control.recv(1)
    finally:
        for client in (control, diagnostic, replacement):
            if client is not None:
                client.close()
        _stop(process)


@pytest.mark.enable_socket
def test_error_records_use_the_p5_closed_error_code_and_json_schema(tmp_path):
    process, _, diagnostic_port = _start_simulator(tmp_path)
    client = None
    try:
        _command(process, "up")
        client = _connect(diagnostic_port)
        _handshake(client)

        _command(
            process,
            "error spp_connect_failed tivoo_spp classic_spp_connection_failed",
        )
        message_type, sequence, payload = _read_frame(client)
        assert (message_type, sequence) == (0x41, 1)
        assert payload["error_code"] == "spp_connect_failed"
        assert payload["module"] == "tivoo_spp"
        assert payload["message"] == "classic_spp_connection_failed"
        assert isinstance(payload["uptime_ms"], int)
    finally:
        if client is not None:
            client.close()
        _stop(process)


@pytest.mark.enable_socket
def test_rejected_hello_ack_does_not_unlock_queue_and_reconnects(tmp_path):
    process, _, diagnostic_port = _start_simulator(tmp_path)
    rejected = accepted = None
    try:
        _command(process, "log INFO wifi_station retained_until_accept")
        _command(process, "up")

        rejected = _connect(diagnostic_port)
        message_type, sequence, hello = _read_frame(rejected)
        assert (message_type, sequence) == (0x01, 0)
        assert hello["device_id"] == "tivoo-esp32"
        _send_ack(rejected, accepted=False)
        _wait_closed(rejected)
        rejected.close()
        rejected = None

        accepted = _connect(diagnostic_port)
        _handshake(accepted)
        message_type, sequence, payload = _read_frame(accepted)
        assert (message_type, sequence) == (0x42, 1)
        assert payload["message"] == "retained_until_accept"
    finally:
        for client in (rejected, accepted):
            if client is not None:
                client.close()
        _stop(process)
