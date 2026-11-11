"""Host simulation of the production P5b3 TCP control stream parser."""

import os
import select
import socket
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.enable_socket

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_MAIN = ROOT / "esp32/firmware/main"
SIMULATOR_SOURCE = ROOT / "esp32/tests/p5b3_control_simulator/control_host.c"
CJSON_SOURCE = ROOT / "esp32/firmware/managed_components/espressif__cjson/cJSON/cJSON.c"
MAC = bytes.fromhex("11 75 58 97 49 98")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_connected(port: int) -> socket.socket:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=0.5)
        except OSError:
            time.sleep(0.02)
    raise AssertionError(f"control listener on {port} did not open")


def _tivoo_frame(payload: bytes) -> bytes:
    length = len(payload) + 2
    length_bytes = length.to_bytes(2, "little")
    checksum = (sum(length_bytes) + sum(payload)) & 0xFFFF
    return b"\x01" + length_bytes + payload + checksum.to_bytes(2, "little") + b"\x02"


class ControlSimulator:
    def __init__(self, binary: Path):
        self.control_port = _free_port()
        self.diagnostic_port = _free_port()
        while self.diagnostic_port == self.control_port:
            self.diagnostic_port = _free_port()
        self.process = subprocess.Popen(
            [str(binary), str(self.control_port), str(self.diagnostic_port)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            bufsize=0,
        )
        self.output: list[str] = []
        self.stdout_buffer = bytearray()

    def connect(self) -> socket.socket:
        return _wait_connected(self.control_port)

    def read_event(self, timeout: float = 2.0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if b"\n" in self.stdout_buffer:
                line, _, rest = self.stdout_buffer.partition(b"\n")
                self.stdout_buffer = bytearray(rest)
                value = line.decode().strip()
                self.output.append(value)
                return value
            readable, _, _ = select.select([self.process.stdout], [], [], 0.05)
            if readable:
                self.stdout_buffer.extend(os.read(self.process.stdout.fileno(), 4096))
        raise AssertionError(
            f"simulator event not received; output={self.output}; buffer={self.stdout_buffer!r}; exited={self.process.poll()}"
        )

    def expect_event(self, expected: str) -> None:
        actual = self.read_event()
        assert actual == expected

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.stdin.write(b"exit\n")
            self.process.stdin.flush()
            self.process.wait(timeout=3)
        self.process.stdin.close()
        self.process.stdout.close()
        self.process.stderr.close()


@pytest.fixture
def simulator_binary(tmp_path):
    binary = tmp_path / "p5b3-control-host"
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
            str(FIRMWARE_MAIN),
            "-I",
            str(CJSON_SOURCE.parent),
            str(FIRMWARE_MAIN / "network_listeners.c"),
            str(FIRMWARE_MAIN / "diagnostics.c"),
            str(FIRMWARE_MAIN / "tivoo_frame_stream.c"),
            str(FIRMWARE_MAIN / "control_bridge.c"),
            str(CJSON_SOURCE),
            str(SIMULATOR_SOURCE),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return binary


def test_split_control_commands_and_fragmented_frames_keep_stream_order(
    simulator_binary,
):
    simulator = ControlSimulator(simulator_binary)
    client = simulator.connect()
    first_frame = _tivoo_frame(bytes.fromhex("44 69 96 00"))
    second_frame = _tivoo_frame(bytes.fromhex("74 32"))
    try:
        client.sendall(b"\x69\x11\x75")
        time.sleep(0.02)
        client.sendall(MAC[2:])
        simulator.expect_event("CONNECT 11:75:58:97:49:98")

        client.sendall(first_frame[:3])
        time.sleep(0.02)
        client.sendall(first_frame[3:] + second_frame)
        simulator.expect_event("FRAME " + first_frame.hex().upper())
        simulator.expect_event("FRAME " + second_frame.hex().upper())

        client.sendall(b"\x96")
        time.sleep(0.02)
        client.sendall(MAC)
        simulator.expect_event("DISCONNECT 11:75:58:97:49:98")
    finally:
        client.close()
        simulator.stop()


def test_coalesced_commands_and_frames_are_dispatched_fifo(simulator_binary):
    simulator = ControlSimulator(simulator_binary)
    client = simulator.connect()
    frame_a = _tivoo_frame(bytes.fromhex("74 10"))
    frame_b = _tivoo_frame(bytes.fromhex("08 07"))
    try:
        client.sendall(b"\x69" + MAC + frame_a + frame_b + b"\x96" + MAC)
        expected = [
            "CONNECT 11:75:58:97:49:98",
            "FRAME " + frame_a.hex().upper(),
            "FRAME " + frame_b.hex().upper(),
            "DISCONNECT 11:75:58:97:49:98",
        ]
        for event in expected:
            simulator.expect_event(event)
    finally:
        client.close()
        simulator.stop()


def test_control_client_disconnect_discards_partial_command_only(simulator_binary):
    simulator = ControlSimulator(simulator_binary)
    first = simulator.connect()
    first.sendall(b"\x69\x11\x75")
    first.close()
    try:
        second = simulator.connect()
        second.sendall(MAC[2:])
        second.settimeout(2)
        try:
            assert second.recv(1) == b""
        except ConnectionResetError:
            pass
        second.close()

        third = simulator.connect()
        third.sendall(b"\x69" + MAC)
        simulator.expect_event("CONNECT 11:75:58:97:49:98")
        third.close()
    finally:
        if first.fileno() >= 0:
            first.close()
        simulator.stop()


def test_unknown_control_start_fails_closed(simulator_binary):
    simulator = ControlSimulator(simulator_binary)
    client = simulator.connect()
    try:
        client.sendall(b"\x55")
        client.settimeout(2)
        assert client.recv(1) == b""
        assert simulator.output == []
    finally:
        client.close()
        simulator.stop()


def test_invalid_checksum_frame_is_not_forwarded(simulator_binary):
    simulator = ControlSimulator(simulator_binary)
    client = simulator.connect()
    frame = bytearray(_tivoo_frame(bytes.fromhex("74 64")))
    frame[-3] ^= 0x01
    try:
        client.sendall(frame)
        client.settimeout(2)
        assert client.recv(1) == b""
        assert not any(event.startswith("FRAME ") for event in simulator.output)
    finally:
        client.close()
        simulator.stop()
