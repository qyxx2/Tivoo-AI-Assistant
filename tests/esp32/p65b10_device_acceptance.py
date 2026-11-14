"""Exercise b10 with a real MP3 or 32 kHz mono S16LE PCM, a DAC-enabled ESP32 and a free TVIO port."""

import argparse
import json
import socket
import threading
import time
import uuid
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from p65b8_device_acceptance import HEADER

PCM_MIME = "audio/x-tivoo-pcm-s16le-32000-mono"


def serve(audio, address, port, media_type, chunk_size):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        def do_GET(self):
            if self.path == "/status":
                self.send_error(503)
                return
            body = audio
            if self.path == "/invalid":
                body = b"\x00" if media_type == PCM_MIME else b"broken MP3" * 200
            self.send_response(200)
            mime = "audio/wav" if self.path == "/mime" else media_type
            self.send_header("Content-Type", mime)
            if self.path == "/chunked":
                self.send_header("Transfer-Encoding", "chunked")
            else:
                length = len(body) + (4096 if self.path == "/truncated" else 0)
                self.send_header("Content-Length", str(length))
            self.end_headers()
            try:
                if self.path == "/chunked":
                    for offset in range(0, len(body), chunk_size):
                        chunk = body[offset : offset + chunk_size]
                        self.wfile.write(
                            f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n"
                        )
                    self.wfile.write(b"0\r\n\r\n")
                elif self.path == "/stall":
                    self.wfile.write(body[:16384])
                    time.sleep(5)
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    return ThreadingHTTPServer((address, port), Handler)


def verify_spp_control(host):
    # Divoom 0x46 queries status without changing the display or volume.
    with socket.create_connection((host, 7777), timeout=2) as control:
        control.sendall(bytes.fromhex("01 03 00 46 49 00 02"))
        data = bytearray()
        while b"\x04\x46\x55" not in data:
            chunk = control.recv(512)
            assert chunk and len(data) < 2048, bytes(data).hex()
            data.extend(chunk)
        print("SPP status response during playback", data.hex())


def verify(host, base, require_spp=False, media_type="audio/mpeg"):
    sock = socket.create_connection((host, 7778), timeout=20)
    with closing(sock) as connection, sock.makefile("rb") as reader:
        receive = 0
        sent = 0
        afe = 0
        states = {}

        def send(kind, data):
            nonlocal sent
            payload = json.dumps(data).encode()
            connection.sendall(
                HEADER.pack(b"TVIO", 1, kind, 0, len(payload), sent) + payload
            )
            sent += 1

        def read():
            nonlocal receive, afe
            header = reader.read(HEADER.size)
            magic, version, kind, flags, size, seq = HEADER.unpack(header)
            assert (magic, version, flags, seq) == (b"TVIO", 1, 0, receive)
            receive += 1
            payload = reader.read(size)
            assert len(payload) == size
            if kind == 0x21:
                return kind, payload
            body = json.loads(payload)
            if kind == 0x42 and body.get("module") == "audio_frontend":
                message = body["message"]
                if message.startswith("AFE frames="):
                    afe = int(message.split()[1].split("=")[1])
                    print(message)
            if kind == 0x32:
                ident, state = body["audio_id"], body["state"]
                previous = states.setdefault(ident, [])
                assert not any(
                    s in previous for s in ("completed", "failed", "stopped")
                ), body
                previous.append(state)
                print(body)
            return kind, body

        def wait(kind, predicate):
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                message, body = read()
                if message == kind and predicate(body):
                    return body
            raise TimeoutError(f"TVIO {kind:#04x}")

        def play(path, mime=media_type, ident=None):
            ident = ident or str(uuid.uuid4())
            send(0x30, {"playback_id": ident, "mime_type": mime, "url": base + path})
            return ident

        def stop(ident):
            send(
                0x31,
                {
                    "request_id": str(uuid.uuid4()),
                    "expected_audio_id": ident,
                    "reason": "b10_acceptance",
                },
            )

        def state(ident, expected, error=None):
            terminals = ("completed", "failed", "stopped")
            body = wait(
                0x32,
                lambda obj: (
                    obj["audio_id"] == ident
                    and (obj["state"] == expected or obj["state"] in terminals)
                ),
            )
            assert body["state"] == expected, body
            assert body.get("error_code") == error, body

        kind, hello = read()
        assert kind == 1
        print("HELLO", hello["firmware_version"])
        send(2, {"accepted": True})
        wait(0x42, lambda _: afe > 0)
        initial_afe = afe

        start = time.monotonic()
        first = play("/chunked")
        state(first, "playing")
        if require_spp:
            verify_spp_control(host)
        stop(str(uuid.uuid4()))
        state(first, "completed")
        print(f"First completion {1000 * (time.monotonic() - start):.1f} ms")
        assert time.monotonic() - start >= 2.5, "completed ahead of PCM"
        play("/chunked", ident=first)

        stalled = play("/stall")
        state(stalled, "playing")
        start = time.monotonic()
        stop(stalled)
        next_id = play("/chunked")
        state(stalled, "stopped")
        print(f"STOP terminal latency {1000 * (time.monotonic() - start):.1f} ms")
        assert time.monotonic() - start < 1
        state(next_id, "playing")
        stop(stalled)
        state(next_id, "completed")

        invalid_error = (
            "audio_pcm_invalid" if media_type == PCM_MIME else "audio_decode_failed"
        )
        state(play("/invalid"), "failed", invalid_error)
        state(play("/truncated"), "failed", "audio_http_failed")
        state(play("/status"), "failed", "audio_http_status")
        state(play("/mime"), "failed", "audio_content_type_mismatch")
        state(play("/chunked", "audio/wav"), "failed", "audio_format_unsupported")

        req = str(uuid.uuid4())
        send(0x10, {"request_id": req})
        status = wait(0x11, lambda body: body["request_id"] == req)
        print("SPP", status["spp"]["state"])
        if require_spp:
            assert status["spp"]["state"] == "connected", status["spp"]
        wait(0x42, lambda _: afe > initial_afe)
        print("PASS: b10 playback protocol and continuous AFE")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("esp32_ip")
    parser.add_argument(
        "audio",
        type=Path,
        help="MP3 or raw 32 kHz mono S16LE fixture, at least 3 seconds",
    )
    parser.add_argument(
        "--http-host", required=True, help="Fixture address reachable by the ESP32"
    )
    parser.add_argument("--http-port", type=int, default=18765)
    parser.add_argument("--require-spp", action="store_true")
    parser.add_argument("--pcm", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=317)
    args = parser.parse_args()
    media_type = PCM_MIME if args.pcm else "audio/mpeg"
    with serve(
        args.audio.read_bytes(),
        args.http_host,
        args.http_port,
        media_type,
        args.chunk_size,
    ) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            verify(
                args.esp32_ip,
                f"http://{args.http_host}:{args.http_port}",
                args.require_spp,
                media_type,
            )
        finally:
            server.shutdown()
            thread.join()


if __name__ == "__main__":
    main()
