"""Controlled LAN HTTP resources for ESP32 P6b5 acceptance.

Run on the development machine: python3 tests/esp32/p6_audio_http_fixture.py
The server binds all interfaces by default so the board can fetch the fixture.
"""

from __future__ import annotations

import argparse
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class AudioFixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "TivooP6Fixture/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        # Avoid logging opaque URLs or tokens copied from test clients.
        return

    def _send_chunked(self, total: int, pause: float = 0.0) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        chunk = b"\x55" * 4096
        remaining = total
        try:
            while remaining:
                data = chunk[: min(len(chunk), remaining)]
                self.wfile.write(f"{len(data):X}\r\n".encode("ascii"))
                self.wfile.write(data + b"\r\n")
                self.wfile.flush()
                remaining -= len(data)
                if pause:
                    time.sleep(pause)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # Expected when AUDIO_STOP cancels an in-progress GET.
            pass

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/audio/status":
            body = b"fixture unavailable"
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/audio/mime":
            body = b"not audio"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/audio/disconnect":
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(128 * 1024))
            self.end_headers()
            self.wfile.write(b"\x55" * 1024)
            self.wfile.flush()
            self.close_connection = True
        elif path == "/audio/large":
            self._send_chunked(2 * 1024 * 1024)
        elif path == "/audio/slow":
            self._send_chunked(2 * 1024 * 1024, pause=0.12)
        elif path == "/audio/chunked":
            self._send_chunked(256 * 1024)
        elif path == "/audio/ok":
            body = b"\x55" * (256 * 1024)
            self.send_response(200)
            self.send_header("Content-Type", "Audio/MPEG; charset=binary")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            for offset in range(0, len(body), 4096):
                self.wfile.write(body[offset : offset + 4096])
                self.wfile.flush()
        else:
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), AudioFixtureHandler)
    print(f"P6b5 HTTP fixture listening on {args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
