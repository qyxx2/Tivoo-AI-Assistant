"""POSIX simulation of the production ESP32 TVIO diagnostics module."""

import json
import select
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
    try:
        assert sock.recv(1) == b""
    except ConnectionResetError:
        pass


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
    assert hello["capabilities"] == [
        "spp_control",
        "spp_reverse",
        "remote_diagnostics",
        "device_status",
        "device_events",
        "audio_resource_http",
        "audio_control",
    ]
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
            str(FIRMWARE / "control_bridge.c"),
            str(FIRMWARE / "tivoo_frame_stream.c"),
            str(FIRMWARE / "diagnostics.c"),
            str(CJSON),
            str(ROOT / "esp32/tests/p5b3_control_simulator/control_bridge_host_stub.c"),
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
        stdout=subprocess.PIPE,
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
    if process.stdout is not None:
        process.stdout.close()


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
        time.sleep(0.2)  # Wait for the listener to release its one-client slot.

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


def _read_raw_frame(sock: socket.socket) -> tuple[int, int, bytes]:
    header = _read_exact(sock, 16)
    magic, version, message_type, flags, payload_length, sequence = struct.unpack(
        "<4sBBHII", header
    )
    assert (magic, version, flags) == (b"TVIO", 1, 0)
    return message_type, sequence, _read_exact(sock, payload_length)


def _send_frame(sock: socket.socket, message_type: int, sequence: int, payload: bytes):
    sock.sendall(
        struct.pack("<4sBBHII", b"TVIO", 1, message_type, 0, len(payload), sequence)
        + payload
    )


@pytest.mark.enable_socket
def test_realtime_outbound_message_uses_common_sequence_and_header(tmp_path):
    process, _, diagnostic_port = _start_simulator(tmp_path)
    client = None
    try:
        _command(process, "up")
        client = _connect(diagnostic_port)
        _handshake(client)
        time.sleep(0.1)  # Let the listener consume HELLO_ACK before queueing.
        _command(process, "send 0x04 7b7d")

        message_type, sequence, payload = _read_raw_frame(client)
        assert (message_type, sequence, payload) == (0x04, 1, b"{}")
    finally:
        if client is not None:
            client.close()
        _stop(process)


@pytest.mark.enable_socket
def test_inbound_message_dispatch_echoes_fragmented_and_coalesced_frames(tmp_path):
    process, _, diagnostic_port = _start_simulator(tmp_path)
    client = None
    try:
        _command(process, "up")
        client = _connect(diagnostic_port)
        _handshake(client)

        first = struct.pack("<4sBBHII", b"TVIO", 1, 0x10, 0, 2, 1) + b"{}"
        second_payload = b'{"request_id":"second"}'
        second = (
            struct.pack("<4sBBHII", b"TVIO", 1, 0x10, 0, len(second_payload), 2)
            + second_payload
        )
        client.sendall(first[:7])
        client.sendall(first[7:] + second)

        assert _read_raw_frame(client) == (0x11, 1, b"{}")
        assert _read_raw_frame(client) == (0x11, 2, second_payload)
    finally:
        if client is not None:
            client.close()
        _stop(process)


@pytest.mark.enable_socket
def test_mic_pcm_binary_boundary_accepts_four_kibibytes_and_rejects_more(tmp_path):
    process, _, diagnostic_port = _start_simulator(tmp_path)
    client = None
    try:
        _command(process, "up")
        client = _connect(diagnostic_port)
        _handshake(client)
        time.sleep(0.1)
        payload = bytes(range(256)) * 16
        _command(process, f"send 0x21 {payload.hex()}")
        assert _read_raw_frame(client) == (0x21, 1, payload)

        oversized = payload + b"x"
        _command(process, f"send 0x21 {oversized.hex()}")
        _command(process, "send 0x04 7b7d")
        assert _read_raw_frame(client) == (0x04, 2, b"{}")
    finally:
        if client is not None:
            client.close()
        _stop(process)


@pytest.mark.enable_socket
def test_unknown_message_reports_protocol_error_and_preserves_next_frame(tmp_path):
    process, _, diagnostic_port = _start_simulator(tmp_path)
    client = None
    try:
        _command(process, "up")
        client = _connect(diagnostic_port)
        _handshake(client)
        time.sleep(0.1)
        _send_frame(client, 0x7F, 1, b"future")
        _send_frame(client, 0x10, 2, b'{"request_id":"ok"}')

        frames = [_read_raw_frame(client), _read_raw_frame(client)]
        assert {frame[0] for frame in frames} == {0x11, 0x41}
        status = next(frame for frame in frames if frame[0] == 0x11)
        error = next(frame for frame in frames if frame[0] == 0x41)
        assert status[2] == b'{"request_id":"ok"}'
        error_payload = json.loads(error[2])
        assert error_payload["error_code"] == "protocol_unsupported_message"
        assert error_payload["module"] == "diagnostics"
    finally:
        if client is not None:
            client.close()
        _stop(process)


@pytest.mark.enable_socket
def test_c_dispatches_every_ha_to_esp32_message_type(tmp_path):
    process, _, diagnostic_port = _start_simulator(tmp_path)
    client = None
    try:
        _command(process, "up")
        client = _connect(diagnostic_port)
        _handshake(client)
        time.sleep(0.1)

        incoming = [
            (0x03, 0x04, b"{}"),
            (0x10, 0x11, b'{"request_id":"status-1"}'),
            (
                0x23,
                0x32,
                (
                    b'{"session_id":"11111111-1111-4111-8111-111111111111",'
                    b'"reason":"pipeline_finished"}'
                ),
            ),
            (0x30, 0x32, b"{}"),
            (0x31, 0x32, b"{}"),
            (0x41, 0x41, b"{}"),
        ]
        frames = []
        for sequence, (message_type, _, payload) in enumerate(incoming, start=1):
            frames.append(
                struct.pack(
                    "<4sBBHII",
                    b"TVIO",
                    1,
                    message_type,
                    0,
                    len(payload),
                    sequence,
                )
                + payload
            )

        client.sendall(frames[0][:9])
        client.sendall(frames[0][9:] + b"".join(frames[1:4]))
        responses = [_read_raw_frame(client) for _ in range(4)]
        client.sendall(b"".join(frames[4:]))
        responses.extend(_read_raw_frame(client) for _ in range(2))
        assert [
            (message_type, sequence) for message_type, sequence, _ in responses
        ] == [
            (response_type, sequence)
            for sequence, (_, response_type, _) in enumerate(incoming, start=1)
        ]
        assert [payload for _, _, payload in responses] == [
            payload for _, _, payload in incoming
        ]
    finally:
        if client is not None:
            client.close()
        _stop(process)


@pytest.mark.enable_socket
def test_c_outbound_api_covers_all_esp32_to_ha_message_types(tmp_path):
    process, _, diagnostic_port = _start_simulator(tmp_path)
    client = None
    try:
        _command(process, "up")
        client = _connect(diagnostic_port)
        _handshake(client)
        time.sleep(0.1)

        outgoing = [0x04, 0x11, 0x20, 0x22, 0x32, 0x33, 0x40, 0x41]
        frames = []
        for message_type in outgoing:
            _command(process, f"send {message_type:#x} 7b7d")
            frames.append(_read_raw_frame(client))
        assert [(message_type, sequence) for message_type, sequence, _ in frames] == [
            (message_type, sequence)
            for sequence, message_type in enumerate(outgoing, start=1)
        ]
        assert all(payload == b"{}" for _, _, payload in frames)
    finally:
        if client is not None:
            client.close()
        _stop(process)


@pytest.mark.enable_socket
@pytest.mark.parametrize(
    "bad_header",
    [
        struct.pack("<4sBBHII", b"NOPE", 1, 0x10, 0, 2, 1) + b"{}",
        struct.pack("<4sBBHII", b"TVIO", 2, 0x10, 0, 2, 1) + b"{}",
        struct.pack("<4sBBHII", b"TVIO", 1, 0x10, 1, 2, 1) + b"{}",
    ],
)
def test_malformed_header_closes_only_the_diagnostic_connection(tmp_path, bad_header):
    process, control_port, diagnostic_port = _start_simulator(tmp_path)
    control = diagnostic = None
    try:
        _command(process, "up")
        control = _connect(control_port)
        diagnostic = _connect(diagnostic_port)
        _handshake(diagnostic)
        time.sleep(0.1)
        diagnostic.sendall(bad_header)
        _wait_closed(diagnostic)
        control.settimeout(0.2)
        with pytest.raises(TimeoutError):
            control.recv(1)
    finally:
        for client in (control, diagnostic):
            if client is not None:
                client.close()
        _stop(process)


@pytest.mark.enable_socket
def test_incoming_sequence_mismatch_closes_diagnostic_connection(tmp_path):
    process, _, diagnostic_port = _start_simulator(tmp_path)
    client = None
    try:
        _command(process, "up")
        client = _connect(diagnostic_port)
        _handshake(client)
        time.sleep(0.1)
        _send_frame(client, 0x10, 2, b"{}")
        _wait_closed(client)
    finally:
        if client is not None:
            client.close()
        _stop(process)


@pytest.mark.enable_socket
def test_realtime_messages_and_p5_logs_share_sequence_without_starvation(tmp_path):
    process, _, diagnostic_port = _start_simulator(tmp_path)
    client = None
    try:
        _command(process, "up")
        client = _connect(diagnostic_port)
        _handshake(client)
        time.sleep(0.1)

        _command(process, "log INFO first_record")
        _command(process, "send 0x04 7b7d")
        _command(process, "log WARNING second_record")
        _command(process, "send 0x11 7b7d")

        frames = [_read_raw_frame(client) for _ in range(4)]
        assert [sequence for _, sequence, _ in frames] == [1, 2, 3, 4]
        assert [message_type for message_type, _, _ in frames].count(0x42) == 2
        assert {message_type for message_type, _, _ in frames} >= {0x04, 0x11, 0x42}
    finally:
        if client is not None:
            client.close()
        _stop(process)


@pytest.mark.enable_socket
def test_c_json_payload_accepts_sixteen_kibibytes(tmp_path):
    process, _, diagnostic_port = _start_simulator(tmp_path)
    client = None
    try:
        _command(process, "up")
        client = _connect(diagnostic_port)
        _handshake(client)
        time.sleep(0.1)
        payload = b'{"data":"' + b"a" * (16 * 1024 - len(b'{"data":""}')) + b'"}'
        assert len(payload) == 16 * 1024
        _send_frame(client, 0x10, 1, payload)
        assert _read_raw_frame(client) == (0x11, 1, payload)
    finally:
        if client is not None:
            client.close()
        _stop(process)


@pytest.mark.enable_socket
def test_mic_capture_stop_validates_payload_and_dispatches_registered_callback(
    tmp_path,
):
    process, _, diagnostic_port = _start_simulator(tmp_path)
    client = None
    session_id = "11111111-1111-4111-8111-111111111111"
    try:
        _command(process, "up")
        client = _connect(diagnostic_port)
        _handshake(client)

        _send_frame(
            client,
            0x23,
            1,
            b'{"session_id":"11111111-1111-4111-8111-111111111111"}',
        )
        assert process.stdout is not None
        assert not select.select([process.stdout], [], [], 0.2)[0]

        _send_frame(
            client,
            0x23,
            2,
            json.dumps(
                {"session_id": session_id, "reason": "pipeline_finished"},
                separators=(",", ":"),
            ).encode(),
        )
        ready, _, _ = select.select([process.stdout], [], [], 2)
        assert ready
        assert process.stdout.readline().strip() == (
            f"mic_capture_stop {session_id} pipeline_finished"
        )

    finally:
        if client is not None:
            client.close()
        _stop(process)


@pytest.mark.enable_socket
def test_mic_capture_stop_without_registered_producer_is_an_idempotent_noop(tmp_path):
    process, _, diagnostic_port = _start_simulator(tmp_path)
    client = None
    try:
        _command(process, "up")
        client = _connect(diagnostic_port)
        _handshake(client)
        _command(process, "mic_stop_off")
        time.sleep(0.05)

        session_id = "11111111-1111-4111-8111-111111111111"
        _send_frame(
            client,
            0x23,
            1,
            json.dumps(
                {"session_id": session_id, "reason": "pipeline_finished"},
                separators=(",", ":"),
            ).encode(),
        )
        assert process.stdout is not None
        assert not select.select([process.stdout], [], [], 0.2)[0]

        assert _read_raw_frame(client) == (
            0x32,
            1,
            json.dumps(
                {"session_id": session_id, "reason": "pipeline_finished"},
                separators=(",", ":"),
            ).encode(),
        )
        _send_frame(client, 0x03, 2, b"")
        assert _read_raw_frame(client) == (0x04, 2, b"")
    finally:
        if client is not None:
            client.close()
        _stop(process)
