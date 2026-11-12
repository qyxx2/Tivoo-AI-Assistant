import json
import socket
import struct
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "esp32/firmware/main"
CJSON = ROOT / "esp32/firmware/managed_components/espressif__cjson/cJSON/cJSON.c"
SIMULATOR = ROOT / "esp32/tests/p6_device_status_simulator/device_status_host.c"
CONTROL_STUB = ROOT / "esp32/tests/p5b3_control_simulator/control_bridge_host_stub.c"
STATUS_STUB = ROOT / "esp32/tests/p6_device_status_simulator/device_status_host_stub.c"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


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


def _read_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise AssertionError(f"socket closed after {len(chunks)} of {size} bytes")
        chunks.extend(chunk)
    return bytes(chunks)


def _send_frame(sock: socket.socket, message_type: int, sequence: int, payload: bytes):
    sock.sendall(
        struct.pack("<4sBBHII", b"TVIO", 1, message_type, 0, len(payload), sequence)
        + payload
    )


def _read_frame(sock: socket.socket) -> tuple[int, int, dict]:
    header = _read_exact(sock, 16)
    magic, version, message_type, flags, payload_length, sequence = struct.unpack(
        "<4sBBHII", header
    )
    assert (magic, version, flags) == (b"TVIO", 1, 0)
    payload = _read_exact(sock, payload_length)
    return message_type, sequence, json.loads(payload) if payload else {}


def _start_simulator(tmp_path: Path):
    binary = tmp_path / "p6-device-status-host"
    subprocess.run(
        [
            "gcc",
            "-std=c11",
            "-D_POSIX_C_SOURCE=200809L",
            "-DNETWORK_LISTENERS_HOST",
            "-DTIVOO_DIAGNOSTICS_HOST_TEST",
            '-DTIVOO_FIRMWARE_VERSION="0.1.0+host-test"',
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pthread",
            "-I",
            str(FIRMWARE),
            "-I",
            str(CJSON.parent),
            str(FIRMWARE / "network_listeners.c"),
            str(FIRMWARE / "control_bridge.c"),
            str(FIRMWARE / "tivoo_frame_stream.c"),
            str(FIRMWARE / "diagnostics.c"),
            str(FIRMWARE / "device_status.c"),
            str(CJSON),
            str(CONTROL_STUB),
            str(STATUS_STUB),
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
def test_device_status_ping_events_and_p6_error_codes(tmp_path):
    process, control_port, diagnostic_port = _start_simulator(tmp_path)
    control = diagnostic = None
    try:
        _command(process, "ready")
        control = _connect(control_port)
        diagnostic = _connect(diagnostic_port)

        message_type, sequence, hello = _read_frame(diagnostic)
        assert (message_type, sequence) == (0x01, 0)
        assert hello["device_id"] == "tivoo-esp32"
        ack = json.dumps({"accepted": True}, separators=(",", ":")).encode()
        _send_frame(diagnostic, 0x02, 0, ack)
        _send_frame(diagnostic, 0x03, 1, b"")
        assert _read_frame(diagnostic) == (0x04, 1, {})
        _command(process, "wifi connected")

        message_type, sequence, wifi_event = _read_frame(diagnostic)
        assert (message_type, sequence) == (0x40, 2)
        assert wifi_event["event"] == "wifi_connected"
        diagnostic.settimeout(0.2)
        _command(process, "wifi connected")
        with pytest.raises(TimeoutError):
            diagnostic.recv(1)
        diagnostic.settimeout(2)

        _send_frame(
            diagnostic,
            0x10,
            2,
            json.dumps({"request_id": "p6-status-1"}).encode(),
        )
        message_type, sequence, status = _read_frame(diagnostic)
        assert (message_type, sequence) == (0x11, 3)
        assert status == {
            "request_id": "p6-status-1",
            "device_id": "tivoo-esp32",
            "firmware_version": "0.1.0+host-test",
            "uptime_ms": status["uptime_ms"],
            "wifi": {
                "state": "connected",
                "ip": "192.168.3.28",
                "rssi_dbm": -55,
            },
            "tcp": {"7777": "connected", "7778": "connected"},
            "spp": {"state": "disconnected"},
            "audio_resource": {"state": "idle", "playback_id": None},
        }
        assert isinstance(status["uptime_ms"], int) and status["uptime_ms"] >= 0

        _command(process, "audio fetching playback-42")
        _send_frame(
            diagnostic,
            0x10,
            3,
            json.dumps({"request_id": "p6-status-fetching"}).encode(),
        )
        message_type, sequence, status = _read_frame(diagnostic)
        assert (message_type, sequence) == (0x11, 4)
        assert status["audio_resource"] == {
            "state": "fetching",
            "playback_id": "playback-42",
        }

        _command(process, "audio idle")
        _send_frame(
            diagnostic,
            0x10,
            4,
            json.dumps({"request_id": "p6-status-idle"}).encode(),
        )
        message_type, sequence, status = _read_frame(diagnostic)
        assert (message_type, sequence) == (0x11, 5)
        assert status["audio_resource"] == {"state": "idle", "playback_id": None}

        mac = "11:75:58:97:49:98"
        _command(process, "spp connecting")
        message_type, sequence, event = _read_frame(diagnostic)
        assert (message_type, sequence) == (0x40, 6)
        assert event["event"] == "spp_connecting"

        diagnostic.settimeout(0.2)
        _command(process, "spp connecting")
        with pytest.raises(TimeoutError):
            diagnostic.recv(1)
        diagnostic.settimeout(2)

        _command(process, f"spp connected {mac}")
        message_type, sequence, event = _read_frame(diagnostic)
        assert (message_type, sequence) == (0x40, 7)
        assert event["event"] == "spp_connected"
        assert event["data"]["mac"] == mac

        diagnostic.settimeout(0.2)
        _command(process, f"spp connected {mac}")
        with pytest.raises(TimeoutError):
            diagnostic.recv(1)
        diagnostic.settimeout(2)

        _command(process, f"spp disconnected {mac}")
        message_type, sequence, event = _read_frame(diagnostic)
        assert (message_type, sequence) == (0x40, 8)
        assert event["event"] == "spp_disconnected"

        p6_error_codes = (
            "reverse_queue_full",
            "audio_busy",
            "audio_http_failed",
            "audio_http_status",
            "audio_content_type_mismatch",
            "operation_cancelled",
        )
        for sequence, error_code in enumerate(p6_error_codes, start=9):
            _command(process, f"error {error_code} audio_resource operation_failed")
            message_type, actual_sequence, error = _read_frame(diagnostic)
            assert (message_type, actual_sequence) == (0x41, sequence)
            assert error["error_code"] == error_code
        assert error["module"] == "audio_resource"
    finally:
        if control is not None:
            control.close()
        if diagnostic is not None:
            diagnostic.close()
        _stop(process)


@pytest.mark.enable_socket
def test_invalid_get_status_request_id_reports_error_without_dropping_client(tmp_path):
    process, _, diagnostic_port = _start_simulator(tmp_path)
    diagnostic = None
    try:
        _command(process, "ready")
        diagnostic = _connect(diagnostic_port)
        assert _read_frame(diagnostic)[:2] == (0x01, 0)
        ack = json.dumps({"accepted": True}, separators=(",", ":")).encode()
        _send_frame(diagnostic, 0x02, 0, ack)
        _send_frame(diagnostic, 0x03, 1, b"")
        assert _read_frame(diagnostic) == (0x04, 1, {})

        _send_frame(diagnostic, 0x10, 2, b"{}")
        message_type, sequence, payload = _read_frame(diagnostic)
        assert (message_type, sequence) == (0x41, 2)
        assert payload["error_code"] == "protocol_invalid_payload"

        _send_frame(diagnostic, 0x10, 3, b'{"request_id":"after-invalid-request"}')
        message_type, sequence, payload = _read_frame(diagnostic)
        assert (message_type, sequence) == (0x11, 3)
        assert payload["request_id"] == "after-invalid-request"
    finally:
        if diagnostic is not None:
            diagnostic.close()
        _stop(process)
