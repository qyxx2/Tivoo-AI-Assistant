"""Verify B8 on an ESP32 with an INMP441. Requires speech near the microphone."""

import argparse
import json
import socket
import struct
import sys
import time
import uuid
from array import array
from contextlib import ExitStack

HEADER = struct.Struct("<4sBBHII")


def verify(sock):
    reader = sock.makefile("rb")
    rx_seq = 0
    tx_seq = 0

    def receive():
        nonlocal rx_seq
        magic, version, kind, flags, length, sequence = HEADER.unpack(
            reader.read(HEADER.size)
        )
        assert (magic, version, flags, sequence) == (b"TVIO", 1, 0, rx_seq)
        rx_seq += 1
        data = reader.read(length)
        assert len(data) == length
        if kind == 0x21:
            assert length == 640
            return kind, data
        return kind, json.loads(data)

    def send(kind, body):
        nonlocal tx_seq
        data = json.dumps(body).encode()
        sock.sendall(HEADER.pack(b"TVIO", 1, kind, 0, len(data), tx_seq) + data)
        tx_seq += 1

    def wait_for(kind, predicate=lambda _: True):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            message, data = receive()
            assert message != 0x33, "VAD emitted AUDIO_INTERRUPTED"
            if message == kind and predicate(data):
                return data
        raise TimeoutError(f"Timed out waiting for TVIO {kind:#x}")

    kind, hello = receive()
    assert kind == 0x01 and "mic_activity_events" in hello["capabilities"], hello
    print("HELLO", hello["firmware_version"], hello["reset_reason"])
    send(0x02, {"accepted": True})
    request_id = str(uuid.uuid4())
    send(0x10, {"request_id": request_id})
    status = wait_for(0x11, lambda body: body["request_id"] == request_id)
    print("CONNECTED", status["wifi"]["state"], "SPP", status["spp"]["state"])
    print("READY: speak for 2–3 seconds and then pause.")
    session = wait_for(0x20)
    sid = session["session_id"]
    assert uuid.UUID(sid).version == 4
    assert (
        session["sample_rate"],
        session["channels"],
        session["sample_format"],
        session["frame_duration_ms"],
        session["trigger_source"],
    ) == (16000, 1, "s16le", 20, "idle_vad")
    assert 0 < session["preroll_ms"] <= 500
    print("START", sid, "preroll_ms", session["preroll_ms"])
    activity_seen = False
    frames = 0
    peak = 0
    speech_end = False
    trailing = 0
    last_afe_frames = 0
    deadline = time.monotonic() + 25
    while trailing < 10:
        assert time.monotonic() < deadline, "Speech did not return to silence"
        kind, data = receive()
        assert kind not in (0x20, 0x22, 0x33)
        if kind == 0x24:
            assert data["session_id"] == sid
            if not activity_seen:
                assert data["state"] == "speech_start"
                activity_seen = True
            if data["state"] == "speech_end":
                speech_end = True
        elif kind == 0x42 and data["module"] == "audio_frontend":
            message = data["message"]
            if message.startswith("AFE frames="):
                last_afe_frames = int(message.split()[1].split("=")[1])
        elif kind == 0x21:
            assert activity_seen, "PCM arrived before speech_start"
            frames += 1
            if speech_end:
                trailing += 1
            samples = array("h", data)
            if sys.byteorder != "little":
                samples.byteswap()
            peak = max(peak, max(abs(value) for value in samples))
    assert peak > 0 and frames >= session["preroll_ms"] // 20 + 10
    print("PCM", frames, "frames; peak", peak, "; frames after speech_end", trailing)

    send(0x23, {"session_id": str(uuid.uuid4()), "reason": "stale_test"})
    wait_for(0x21)
    send(0x23, {"session_id": sid, "reason": "b8_acceptance"})
    end = wait_for(0x22)
    assert end["session_id"] == sid
    print("STOP", end)
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        kind, data = receive()
        assert kind not in (0x20, 0x21, 0x22, 0x33), kind
        if kind == 0x42 and data["module"] == "audio_frontend":
            message = data["message"]
            if message.startswith("AFE frames="):
                afe_frames = int(message.split()[1].split("=")[1])
                assert afe_frames > last_afe_frames
                print("AFTER STOP", message)
                return
    raise TimeoutError("No AFE telemetry after STOP")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device_ip")
    parser.add_argument("--spp-peer", help="Optional already paired Tivoo MAC")
    args = parser.parse_args()
    with ExitStack() as connections:
        if args.spp_peer:
            peer = bytes.fromhex(args.spp_peer.replace(":", ""))
            assert len(peer) == 6
            control = connections.enter_context(
                socket.create_connection((args.device_ip, 7777), timeout=8)
            )
            control.sendall(b"\x69" + peer)
            time.sleep(3)
        diagnostic = connections.enter_context(
            socket.create_connection((args.device_ip, 7778), timeout=48)
        )
        verify(diagnostic)


if __name__ == "__main__":
    main()
