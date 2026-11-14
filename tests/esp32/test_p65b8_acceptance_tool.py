"""Exercise the same TVIO verifier used on the board with a known peer."""

import json
import socket
import uuid
from concurrent.futures import ThreadPoolExecutor

from p65b8_device_acceptance import HEADER, verify


def test_acceptance_reads_fragmented_wire_and_checks_stop(capsys):
    session_id = str(uuid.uuid4())

    def device(sock):
        with sock, sock.makefile("rb") as reader:
            sequence = 0

            def send(kind, data):
                nonlocal sequence
                payload = data if isinstance(data, bytes) else json.dumps(data).encode()
                frame = (
                    HEADER.pack(b"TVIO", 1, kind, 0, len(payload), sequence) + payload
                )
                sequence += 1
                sock.sendall(frame[:7])
                sock.sendall(frame[7:])

            def receive(kind, sequence):
                magic, version, actual, flags, size, index = HEADER.unpack(
                    reader.read(HEADER.size)
                )
                assert (magic, version, actual, flags, index) == (
                    b"TVIO",
                    1,
                    kind,
                    0,
                    sequence,
                )
                return json.loads(reader.read(size))

            def telemetry(frames, state, uptime):
                send(
                    0x42,
                    {
                        "module": "audio_frontend",
                        "message": f"AFE frames={frames} vad={state} overruns=0",
                        "uptime_ms": uptime,
                    },
                )

            send(
                0x01,
                {
                    "capabilities": ["mic_activity_events"],
                    "firmware_version": "fixture",
                    "reset_reason": "fixture",
                },
            )
            assert receive(0x02, 0) == {"accepted": True}
            request = receive(0x10, 1)
            send(
                0x11,
                {
                    **request,
                    "wifi": {"state": "connected"},
                    "spp": {"state": "connected"},
                },
            )
            telemetry(50, "silence", 1000)
            send(
                0x20,
                {
                    "session_id": session_id,
                    "sample_rate": 16000,
                    "channels": 1,
                    "sample_format": "s16le",
                    "frame_duration_ms": 20,
                    "preroll_ms": 20,
                    "trigger_source": "idle_vad",
                },
            )
            send(0x24, {"session_id": session_id, "state": "speech_start"})
            send(0x21, bytes([32, 0]) * 320)
            send(0x24, {"session_id": session_id, "state": "speech_end"})
            for _ in range(10):
                send(0x21, bytes(640))
            assert receive(0x23, 2)["session_id"] != session_id
            send(0x21, bytes(640))
            assert receive(0x23, 3)["session_id"] == session_id
            send(0x22, {"session_id": session_id})
            telemetry(100, "silence", 2000)

    client, peer = socket.socketpair()
    with client, ThreadPoolExecutor(max_workers=1) as pool:
        client.settimeout(2)
        peer.settimeout(2)
        result = pool.submit(device, peer)
        verify(client)
        result.result(timeout=3)
    output = capsys.readouterr().out
    assert "BEFORE START AFE frames=50" in output
    assert "AFTER STOP AFE frames=100" in output
