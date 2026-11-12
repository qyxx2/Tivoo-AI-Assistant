"""P6b5 ESP32 HTTP/STOP acceptance. Run on NAS: python3 p6b5_device_acceptance.py."""

import argparse
import json
import socket
import struct
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEVICE_IP = "192.168.3.28"
SERVER_IP = "192.168.3.94"
SERVER_PORT = 8765
CHUNK_SIZE = 4096
CHUNKED_SIZE = 256 * 1024
LARGE_SIZE = 10 * 1024 * 1024
slow_bytes_sent = 0

hits = {}
hit_events = {}


class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "P6b5Fixture/1.0"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _mark(self, path: str) -> None:
        hits[path] = hits.get(path, 0) + 1
        hit_events.setdefault(path, threading.Event()).set()

    def _send_chunked(self, size: int, pause: float = 0.0, progress_label=None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        chunk = b"\x55" * CHUNK_SIZE
        remaining = size
        sent = 0
        try:
            while remaining > 0:
                data = chunk[: min(len(chunk), remaining)]
                self.wfile.write(f"{len(data):X}\r\n".encode("ascii"))
                self.wfile.write(data + b"\r\n")
                self.wfile.flush()
                remaining -= len(data)
                sent += len(data)
                if progress_label and sent % (1024 * 1024) == 0:
                    print(f"HTTP_SEND {progress_label} {sent}", flush=True)
                if pause:
                    time.sleep(pause)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            print(
                f"HTTP_CLIENT_CLOSED {progress_label or 'stream'} after {sent}",
                flush=True,
            )

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        self._mark(path)
        if path == "/audio/chunked":
            self._send_chunked(CHUNKED_SIZE)
        elif path == "/audio/large":
            self._send_chunked(LARGE_SIZE, progress_label="large")
        elif path == "/audio/slow":
            global slow_bytes_sent
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(16 * 1024 * 1024))
            self.end_headers()
            chunk = b"\x55" * CHUNK_SIZE
            try:
                for _ in range(16 * 1024 * 1024 // CHUNK_SIZE):
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    slow_bytes_sent += len(chunk)
                    time.sleep(0.04)
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif path == "/audio/mime":
            body = b"not audio"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/audio/status":
            body = b"unavailable"
            self.send_response(503)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


def encode_frame(message_type: int, sequence: int, payload: dict) -> bytes:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return (
        struct.pack("<4sBBHII", b"TVIO", 1, message_type, 0, len(body), sequence) + body
    )


def read_exact(sock: socket.socket, size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        part = sock.recv(size - len(result))
        if not part:
            raise RuntimeError("ESP32 closed diagnostic connection")
        result.extend(part)
    return bytes(result)


def read_frame(sock: socket.socket):
    header = read_exact(sock, 16)
    magic, version, message_type, flags, size, sequence = struct.unpack(
        "<4sBBHII", header
    )
    if (magic, version, flags) != (b"TVIO", 1, 0):
        raise RuntimeError("Invalid TVIO header")
    payload = read_exact(sock, size)
    return message_type, sequence, json.loads(payload) if payload else {}


def wait_state(sock: socket.socket, expected: str, timeout: float = 8.0) -> dict:
    deadline = time.monotonic() + timeout
    seen = []
    while time.monotonic() < deadline:
        sock.settimeout(max(0.2, deadline - time.monotonic()))
        message_type, sequence, payload = read_frame(sock)
        if message_type == 0x32:
            seen.append(payload)
            if payload.get("state") == expected:
                print(
                    "AUDIO_STATE", json.dumps(payload, ensure_ascii=False), flush=True
                )
                return payload
        elif message_type == 0x41:
            print("ERROR", json.dumps(payload, ensure_ascii=False), flush=True)
        elif message_type == 0x03:
            # Device heartbeat: answer PONG on the same inbound sequence stream.
            pass
        else:
            print("FRAME", message_type, sequence, json.dumps(payload), flush=True)
    raise TimeoutError(f"Expected state {expected!r}; observed {seen!r}")


def wait_error(sock: socket.socket, expected: str, timeout: float = 8.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        sock.settimeout(max(0.2, deadline - time.monotonic()))
        message_type, sequence, payload = read_frame(sock)
        if message_type == 0x41:
            print("ERROR", json.dumps(payload, ensure_ascii=False), flush=True)
            if payload.get("error_code") == expected:
                return payload
        elif message_type == 0x32:
            print("AUDIO_STATE", json.dumps(payload, ensure_ascii=False), flush=True)
        else:
            print("FRAME", message_type, sequence, json.dumps(payload), flush=True)
    raise TimeoutError(f"Expected ERROR {expected!r}")


def wait_http_hit(path: str, timeout: float = 5.0) -> None:
    event = hit_events.setdefault(path, threading.Event())
    if not event.wait(timeout):
        raise TimeoutError("ESP32 never issued HTTP GET for " + path)


def send_message(
    sock: socket.socket, message_type: int, sequence: int, payload: dict
) -> None:
    sock.sendall(encode_frame(message_type, sequence, payload))


def main() -> None:
    global DEVICE_IP, SERVER_IP, SERVER_PORT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-ip", default=DEVICE_IP)
    parser.add_argument("--server-ip", default=SERVER_IP)
    parser.add_argument("--port", type=int, default=SERVER_PORT)
    args = parser.parse_args()
    DEVICE_IP = args.device_ip
    SERVER_IP = args.server_ip
    SERVER_PORT = args.port

    server = ThreadingHTTPServer((SERVER_IP, SERVER_PORT), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    sock = socket.create_connection((DEVICE_IP, 7778), timeout=8)
    sock.settimeout(8)
    try:
        message_type, _hello_sequence, hello = read_frame(sock)
        if message_type != 0x01:
            raise RuntimeError(f"Expected HELLO; got {message_type}")
        print("HELLO", json.dumps(hello, ensure_ascii=False), flush=True)
        if "audio_resource_http" not in hello.get("capabilities", []):
            raise RuntimeError("Firmware did not advertise audio_resource_http")
        send_message(sock, 0x02, 0, {"accepted": True})

        # Unknown Content-Length/chunked transfer: 256 KiB must reach the reader.
        audio_id = str(uuid.uuid4())
        send_message(
            sock,
            0x30,
            1,
            {
                "playback_id": audio_id,
                "url": f"http://{SERVER_IP}:{SERVER_PORT}/audio/chunked",
                "mime_type": "audio/mpeg",
            },
        )
        state = wait_state(sock, "resource_ready")
        if state.get("bytes_received") != CHUNKED_SIZE:
            raise AssertionError(
                f"chunked bytes_received={state.get('bytes_received')!r}"
            )
        wait_http_hit("/audio/chunked")
        print(f"PASS chunked_get bytes={state['bytes_received']}", flush=True)

        large_id = str(uuid.uuid4())
        send_message(
            sock,
            0x30,
            2,
            {
                "playback_id": large_id,
                "url": f"http://{SERVER_IP}:{SERVER_PORT}/audio/large",
                "mime_type": "audio/mpeg",
            },
        )
        wait_state(sock, "buffering")
        large_state = wait_state(sock, "resource_ready", timeout=90)
        if large_state.get("bytes_received") != LARGE_SIZE:
            raise AssertionError(
                f"large bytes_received={large_state.get('bytes_received')!r}"
            )
        wait_http_hit("/audio/large")
        print(
            f"PASS large_chunked_get bytes={large_state['bytes_received']}", flush=True
        )

        # Hold a long GET open. A stale stop must be ignored; busy must be reported;
        # matching stop must terminate the active HTTP request.
        slow_id = str(uuid.uuid4())
        send_message(
            sock,
            0x30,
            3,
            {
                "playback_id": slow_id,
                "url": f"http://{SERVER_IP}:{SERVER_PORT}/audio/slow",
                "mime_type": "audio/mpeg",
            },
        )
        wait_state(sock, "buffering")
        wait_http_hit("/audio/slow")
        time.sleep(0.4)

        busy_id = str(uuid.uuid4())
        send_message(
            sock,
            0x30,
            4,
            {
                "playback_id": busy_id,
                "url": f"http://{SERVER_IP}:{SERVER_PORT}/audio/chunked",
                "mime_type": "audio/mpeg",
            },
        )
        wait_error(sock, "audio_busy")
        send_message(
            sock,
            0x31,
            5,
            {
                "request_id": str(uuid.uuid4()),
                "expected_audio_id": str(uuid.uuid4()),
                "reason": "stale_stop",
            },
        )
        bytes_before_stale_stop = slow_bytes_sent
        time.sleep(0.25)
        if slow_bytes_sent <= bytes_before_stale_stop:
            raise AssertionError("stale AUDIO_STOP interrupted the active GET")
        print("PASS stale_stop_ignored", flush=True)

        matching_stop_request_id = str(uuid.uuid4())
        send_message(
            sock,
            0x31,
            6,
            {
                "request_id": matching_stop_request_id,
                "expected_audio_id": slow_id,
                "reason": "user_stop",
            },
        )
        stopped = wait_state(sock, "stopped", timeout=8)
        if not (0 < stopped.get("bytes_received", 0) < 16 * 1024 * 1024):
            raise AssertionError(
                f"stop bytes_received={stopped.get('bytes_received')!r}"
            )
        print(f"PASS matching_stop bytes={stopped['bytes_received']}", flush=True)

        send_message(
            sock,
            0x31,
            7,
            {
                "request_id": matching_stop_request_id,
                "expected_audio_id": slow_id,
                "reason": "repeated_stop",
            },
        )
        sock.settimeout(0.35)
        try:
            unexpected_type, unexpected_sequence, unexpected_payload = read_frame(sock)
        except OSError as error:
            if not isinstance(error, socket.timeout):
                raise
        else:
            raise AssertionError(
                "repeated AUDIO_STOP produced a frame: "
                f"{unexpected_type}/{unexpected_sequence}/{unexpected_payload!r}"
            )
        print("PASS repeated_stop_noop", flush=True)

        # Wrong response MIME must fail before bytes reach the reader.
        mime_id = str(uuid.uuid4())
        send_message(
            sock,
            0x30,
            8,
            {
                "playback_id": mime_id,
                "url": f"http://{SERVER_IP}:{SERVER_PORT}/audio/mime",
                "mime_type": "audio/mpeg",
            },
        )
        wait_state(sock, "buffering")
        mime_state = wait_state(sock, "failed")
        if (
            mime_state.get("error_code") != "audio_content_type_mismatch"
            or mime_state.get("bytes_received") != 0
        ):
            raise AssertionError(f"MIME mismatch state={mime_state!r}")
        print("PASS mime_mismatch", flush=True)

        # Non-2xx must report the status error, not pass the body to the reader.
        status_id = str(uuid.uuid4())
        send_message(
            sock,
            0x30,
            9,
            {
                "playback_id": status_id,
                "url": f"http://{SERVER_IP}:{SERVER_PORT}/audio/status",
                "mime_type": "audio/mpeg",
            },
        )
        wait_state(sock, "buffering")
        status_state = wait_state(sock, "failed")
        if (
            status_state.get("error_code") != "audio_http_status"
            or status_state.get("bytes_received") != 0
        ):
            raise AssertionError(f"HTTP status state={status_state!r}")
        print("PASS http_status", flush=True)

        print("RESULT PASS", flush=True)
    finally:
        sock.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
