"""POSIX-host simulation of the production ESP32 TCP listener manager."""

import socket
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LISTENER_SOURCE = ROOT / "esp32/firmware/main/network_listeners.c"
LISTENER_HEADER = ROOT / "esp32/firmware/main/network_listeners.h"
SIMULATOR_SOURCE = ROOT / "esp32/tests/p5b1_network_simulator/listener_host.c"
DIAGNOSTICS_SOURCE = ROOT / "esp32/firmware/main/diagnostics.c"
CJSON_SOURCE = ROOT / "esp32/firmware/managed_components/espressif__cjson/cJSON/cJSON.c"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_connected(port: int) -> socket.socket:
    deadline = time.monotonic() + 3
    last_error = None
    while time.monotonic() < deadline:
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=0.5)
        except OSError as err:
            last_error = err
            time.sleep(0.02)
    raise AssertionError(f"listener on {port} did not open: {last_error}")


def _wait_closed(sock: socket.socket) -> None:
    sock.settimeout(2)
    assert sock.recv(1) == b""


def _drain_until_closed(sock: socket.socket) -> None:
    sock.settimeout(2)
    while sock.recv(4096):
        pass


def _assert_refused(port: int) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                time.sleep(0.02)
        except OSError:
            return
    raise AssertionError(f"listener on {port} remained open")


@pytest.mark.enable_socket
def test_ip_events_manage_both_tcp_listeners_and_enforce_one_client(tmp_path):
    binary = tmp_path / "p5b1-listener-host"
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
            str(LISTENER_HEADER.parent),
            "-I",
            str(CJSON_SOURCE.parent),
            str(LISTENER_SOURCE),
            str(DIAGNOSTICS_SOURCE),
            str(CJSON_SOURCE),
            str(SIMULATOR_SOURCE),
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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    control_client = diagnostic_client = None
    second_control = second_diagnostic = None
    try:
        _assert_refused(control_port)
        _assert_refused(diagnostic_port)

        process.stdin.write("up\n")
        process.stdin.flush()
        control_client = _wait_connected(control_port)
        diagnostic_client = _wait_connected(diagnostic_port)

        second_control = _wait_connected(control_port)
        second_control.settimeout(2)
        _wait_closed(second_control)
        second_control.close()
        second_control = None

        second_diagnostic = _wait_connected(diagnostic_port)
        second_diagnostic.settimeout(2)
        _wait_closed(second_diagnostic)
        second_diagnostic.close()
        second_diagnostic = None

        process.stdin.write("down\n")
        process.stdin.flush()
        _wait_closed(control_client)
        _drain_until_closed(diagnostic_client)
        _assert_refused(control_port)
        _assert_refused(diagnostic_port)
        control_client.close()
        diagnostic_client.close()
        control_client = diagnostic_client = None

        process.stdin.write("up\n")
        process.stdin.flush()
        control_client = _wait_connected(control_port)
        diagnostic_client = _wait_connected(diagnostic_port)
    finally:
        for client in (
            control_client,
            diagnostic_client,
            second_control,
            second_diagnostic,
        ):
            if client is not None:
                client.close()
        if process.poll() is None:
            process.stdin.write("exit\n")
            process.stdin.flush()
            process.wait(timeout=3)
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()
