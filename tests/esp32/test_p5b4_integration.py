"""Joint POSIX integration tests for production P5 TCP 7777 and 7778 paths."""

import json
import os
import select
import socket
import struct
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.enable_socket

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "esp32/firmware/main"
SIMULATOR = ROOT / "esp32/tests/p5b4_integration_simulator"
CJSON = ROOT / "esp32/firmware/managed_components/espressif__cjson/cJSON/cJSON.c"
MAC = bytes.fromhex("11 75 58 97 49 98")


def _read_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise AssertionError(f"socket closed after {len(data)} of {size} bytes")
        data.extend(chunk)
    return bytes(data)


def _read_tvio_message(sock: socket.socket) -> tuple[int, int, dict]:
    header = _read_exact(sock, 16)
    magic, version, message_type, flags, payload_length, sequence = struct.unpack(
        "<4sBBHII", header
    )
    assert (magic, version, flags) == (b"TVIO", 1, 0)
    assert payload_length <= 16 * 1024
    payload = json.loads(_read_exact(sock, payload_length))
    return message_type, sequence, payload


def _send_ack(sock: socket.socket) -> None:
    payload = b'{"accepted":true}'
    sock.sendall(
        struct.pack("<4sBBHII", b"TVIO", 1, 0x02, 0, len(payload), 0) + payload
    )


def _tivoo_frame(payload: bytes) -> bytes:
    length = len(payload) + 2
    length_bytes = length.to_bytes(2, "little")
    checksum = (sum(length_bytes) + sum(payload)) & 0xFFFF
    return b"\x01" + length_bytes + payload + checksum.to_bytes(2, "little") + b"\x02"


def _connect(port: int, timeout: float = 3.0) -> socket.socket:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=0.5)
        except OSError as err:
            last_error = err
            time.sleep(0.02)
    raise AssertionError(f"TCP listener {port} did not open: {last_error}")


def _connect_diagnostic(port: int) -> tuple[socket.socket, dict]:
    deadline = time.monotonic() + 4
    last_error = None
    while time.monotonic() < deadline:
        client = None
        try:
            client = _connect(port, timeout=0.4)
            client.settimeout(0.5)
            message_type, sequence, payload = _read_tvio_message(client)
            assert (message_type, sequence) == (0x01, 0)
            return client, payload
        except (OSError, AssertionError) as err:
            last_error = err
            if client is not None:
                client.close()
            time.sleep(0.05)
    raise AssertionError(f"diagnostics HELLO was not received: {last_error}")


def _assert_closed(sock: socket.socket) -> None:
    sock.settimeout(3)
    assert sock.recv(1) == b""


class FirmwareSimulator:
    def __init__(self, binary: Path):
        self.process = subprocess.Popen(
            [str(binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            bufsize=0,
        )
        self.output_buffer = bytearray()
        self.output: list[str] = []

    def command(self, value: str) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(value.encode() + b"\n")
        self.process.stdin.flush()

    def event(self, timeout: float = 3) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if b"\n" in self.output_buffer:
                line, _, remainder = self.output_buffer.partition(b"\n")
                self.output_buffer = bytearray(remainder)
                value = line.decode().strip()
                self.output.append(value)
                return value
            assert self.process.stdout is not None
            readable, _, _ = select.select([self.process.stdout], [], [], 0.05)
            if readable:
                chunk = os.read(self.process.stdout.fileno(), 4096)
                if not chunk:
                    break
                self.output_buffer.extend(chunk)
        raise AssertionError(
            f"simulator event missing; output={self.output}; "
            f"buffer={self.output_buffer!r}; exit={self.process.poll()}"
        )

    def expect_event(self, expected: str) -> None:
        actual = self.event()
        assert actual == expected

    def stop(self) -> None:
        if self.process.poll() is None:
            self.command("exit")
            self.process.wait(timeout=4)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()


@pytest.fixture
def firmware_binary(tmp_path: Path) -> Path:
    binary = tmp_path / "p5b4-firmware-host"
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
            str(FIRMWARE / "control_bridge.c"),
            str(FIRMWARE / "tivoo_frame_stream.c"),
            str(FIRMWARE / "diagnostics.c"),
            str(CJSON),
            str(SIMULATOR / "tivoo_spp_host_stub.c"),
            str(SIMULATOR / "firmware_host.c"),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return binary


def _start(firmware_binary: Path) -> FirmwareSimulator:
    return FirmwareSimulator(firmware_binary)


def test_control_and_diagnostics_run_together_and_reconnect_independently(
    firmware_binary: Path,
):
    firmware = _start(firmware_binary)
    control = diagnostic = replacement_diagnostic = None
    try:
        control = _connect(7777)
        diagnostic, hello = _connect_diagnostic(7778)
        assert hello["device_id"] == "tivoo-esp32"
        _send_ack(diagnostic)

        frame = _tivoo_frame(bytes.fromhex("44 69 96 00"))
        control.sendall(b"\x69" + MAC + frame)
        firmware.expect_event("CONNECT 11:75:58:97:49:98")
        firmware.expect_event("FRAME " + frame.hex().upper())

        diagnostic.close()
        diagnostic = None
        replacement_diagnostic, _ = _connect_diagnostic(7778)
        _send_ack(replacement_diagnostic)

        next_frame = _tivoo_frame(bytes.fromhex("74 32"))
        control.sendall(next_frame)
        firmware.expect_event("FRAME " + next_frame.hex().upper())

        firmware.command("log")
        message_type, sequence, payload = _read_tvio_message(replacement_diagnostic)
        assert (message_type, sequence) == (0x42, 1)
        assert payload["message"] == "integration_log"
    finally:
        for client in (control, diagnostic, replacement_diagnostic):
            if client is not None:
                client.close()
        firmware.stop()


def test_spp_queue_failure_is_reported_on_7778_without_blocking_diagnostics(
    firmware_binary: Path,
):
    firmware = _start(firmware_binary)
    control = diagnostic = None
    try:
        control = _connect(7777)
        diagnostic, _ = _connect_diagnostic(7778)
        _send_ack(diagnostic)

        firmware.command("fail_next_frame")
        frame = _tivoo_frame(bytes.fromhex("44 69 96 00"))
        control.sendall(frame)
        _assert_closed(control)
        message_type, sequence, payload = _read_tvio_message(diagnostic)
        assert (message_type, sequence) == (0x41, 1)
        assert payload["error_code"] == "spp_tx_queue_full"
        assert payload["module"] == "control_bridge"

        firmware.command("log")
        message_type, sequence, payload = _read_tvio_message(diagnostic)
        assert (message_type, sequence) == (0x42, 2)
        assert payload["message"] == "integration_log"
    finally:
        for client in (control, diagnostic):
            if client is not None:
                client.close()
        firmware.stop()


def test_wifi_ip_loss_closes_both_ports_and_new_sessions_recover(
    firmware_binary: Path,
):
    firmware = _start(firmware_binary)
    control = diagnostic = new_control = new_diagnostic = None
    try:
        control = _connect(7777)
        diagnostic, _ = _connect_diagnostic(7778)
        _send_ack(diagnostic)

        control.sendall(b"\x69" + MAC)
        firmware.expect_event("CONNECT 11:75:58:97:49:98")
        firmware.command("down")
        _assert_closed(control)
        _assert_closed(diagnostic)
        control.close()
        diagnostic.close()
        control = diagnostic = None

        firmware.command("up")
        new_diagnostic, _ = _connect_diagnostic(7778)
        _send_ack(new_diagnostic)
        new_control = _connect(7777)
        frame = _tivoo_frame(bytes.fromhex("74 33"))
        new_control.sendall(b"\x69" + MAC + frame)
        firmware.expect_event("CONNECT 11:75:58:97:49:98")
        firmware.expect_event("FRAME " + frame.hex().upper())
    finally:
        for client in (control, diagnostic, new_control, new_diagnostic):
            if client is not None:
                client.close()
        firmware.stop()
