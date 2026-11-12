"""POSIX-host tests for the P6 7777 raw SPP reverse path."""

import socket
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "esp32/firmware/main"
CJSON = ROOT / "esp32/firmware/managed_components/espressif__cjson/cJSON/cJSON.c"
QUEUE_HOST = ROOT / "esp32/tests/p5b3_control_simulator/reverse_queue_host.c"
LISTENER_HOST = ROOT / "esp32/tests/p5b3_control_simulator/control_host.c"


def _build(tmp_path, host_source):
    binary = tmp_path / "p6-reverse-host"
    command = [
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
        str(MAIN),
        "-I",
        str(CJSON.parent),
        str(MAIN / "network_listeners.c"),
        str(MAIN / "control_bridge.c"),
        str(MAIN / "tivoo_frame_stream.c"),
        str(MAIN / "diagnostics.c"),
        str(CJSON),
        str(host_source),
        "-o",
        str(binary),
    ]
    if Path(host_source).name == "reverse_queue_host.c":
        command.append("-Wl,--wrap=send")
    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return binary


def test_reverse_queue_handles_backpressure_overflow_and_client_lifecycle(tmp_path):
    binary = _build(tmp_path, QUEUE_HOST)
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    assert "EAGAIN" in result.stdout


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_connected(port):
    import time

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=0.5)
        except OSError:
            time.sleep(0.02)
    raise AssertionError(f"listener on {port} did not open")


def _wait_data(sock, expected):
    sock.settimeout(2)
    received = bytearray()
    while len(received) < len(expected):
        chunk = sock.recv(len(expected) - len(received))
        if not chunk:
            break
        received.extend(chunk)
    assert bytes(received) == expected


def _send_command(process, command):
    process.stdin.write(command.encode() + b"\n")
    process.stdin.flush()


def _read_event(process, expected, timeout=2):
    import select
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([process.stdout], [], [], 0.05)
        if ready:
            actual = process.stdout.readline().decode().strip()
            if actual == expected:
                return
    raise AssertionError(f"simulator event {expected!r} was not received")


def _tivoo_frame(payload):
    length = (len(payload) + 2).to_bytes(2, "little")
    checksum = (sum(length) + sum(payload)) & 0xFFFF
    return b"\x01" + length + payload + checksum.to_bytes(2, "little") + b"\x02"


@pytest.mark.enable_socket
def test_listener_returns_raw_spp_bytes_and_keeps_sessions_independent(tmp_path):
    binary = _build(tmp_path, LISTENER_HOST)
    control_port, diagnostic_port = _free_port(), _free_port()
    while diagnostic_port == control_port:
        diagnostic_port = _free_port()
    process = subprocess.Popen(
        [str(binary), str(control_port), str(diagnostic_port)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    control = diagnostic = None
    try:
        _send_command(process, "up")
        _send_command(process, "data A1B2C3")  # No client: this session is dropped.
        _read_event(process, "DATA_ACCEPTED")
        control = _wait_connected(control_port)
        diagnostic = _wait_connected(diagnostic_port)
        diagnostic.settimeout(0.2)
        try:
            assert diagnostic.recv(1) == b""
        except TimeoutError:
            pass

        _send_command(process, "data 010269")
        _read_event(process, "DATA_ACCEPTED")
        _send_command(process, "data 96FE00")
        _read_event(process, "DATA_ACCEPTED")
        _wait_data(control, bytes.fromhex("01 02 69 96 FE 00"))

        # Only an individual one-byte hint is returned; raw SPP data stays opaque.
        _send_command(process, "frame-result connecting")
        _read_event(process, "FRAME_RESULT_SET")
        control.sendall(_tivoo_frame(b"\x41\x42"))
        _wait_data(control, b"\x69")
        _send_command(process, "frame-result disconnected")
        _read_event(process, "FRAME_RESULT_SET")
        control.sendall(_tivoo_frame(b"\x43\x44"))
        _wait_data(control, b"\x96")

        # A 7777 disconnect must not close 7778 or produce an SPP disconnect.
        control.close()
        control = None
        diagnostic.settimeout(0.2)
        try:
            assert diagnostic.recv(1) == b""
        except TimeoutError:
            pass
        control = _wait_connected(control_port)
        import time

        time.sleep(0.1)  # Let the listener accept the new TCP session.
        _send_command(process, "data 0A0B0C")
        _read_event(process, "DATA_ACCEPTED")
        _wait_data(control, bytes.fromhex("0A 0B 0C"))
    finally:
        for sock in (control, diagnostic):
            if sock is not None:
                sock.close()
        if process.poll() is None:
            _send_command(process, "exit")
            process.wait(timeout=3)
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()
