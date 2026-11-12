"""Host contract tests for the production P6 audio-resource payload parser."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CJSON = ROOT / "esp32/firmware/managed_components/espressif__cjson/cJSON/cJSON.c"
HARNESS = ROOT / "tests/esp32/p6_audio_resource_protocol_host.c"
FIRMWARE = ROOT / "esp32/firmware/main"


def test_tts_and_stop_payload_validation(tmp_path):
    binary = tmp_path / "p6-audio-resource-protocol"
    subprocess.run(
        [
            "gcc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(FIRMWARE),
            "-I",
            str(CJSON.parent),
            str(HARNESS),
            str(CJSON),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    assert "P6 audio resource protocol tests passed" in result.stdout


def test_controlled_http_fixture_covers_stream_and_failure_responses(tmp_path):
    import http.client
    import socket
    import subprocess
    import sys
    import time
    import urllib.error
    import urllib.request

    fixture = ROOT / "tests/esp32/p6_audio_http_fixture.py"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    server = subprocess.Popen(
        [sys.executable, str(fixture), "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = "http://127.0.0.1:" + str(port)
    try:
        deadline = time.monotonic() + 3
        while True:
            try:
                urllib.request.urlopen(base_url + "/audio/status", timeout=0.2)
            except urllib.error.HTTPError as err:
                assert err.code == 503
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)

        with urllib.request.urlopen(base_url + "/audio/ok", timeout=3) as response:
            assert response.status == 200
            assert response.headers.get_content_type() == "audio/mpeg"
            assert len(response.read()) == 256 * 1024

        with urllib.request.urlopen(base_url + "/audio/chunked", timeout=3) as response:
            assert response.status == 200
            assert response.headers.get("Content-Length") is None
            assert response.headers.get("Transfer-Encoding") == "chunked"
            assert len(response.read()) == 256 * 1024

        with urllib.request.urlopen(base_url + "/audio/large", timeout=5) as response:
            assert len(response.read()) == 2 * 1024 * 1024

        with urllib.request.urlopen(base_url + "/audio/mime", timeout=3) as response:
            assert response.headers.get_content_type() == "text/plain"

        with pytest.raises(urllib.error.HTTPError) as status_error:
            urllib.request.urlopen(base_url + "/audio/status", timeout=3)
        assert status_error.value.code == 503

        with urllib.request.urlopen(
            base_url + "/audio/disconnect", timeout=3
        ) as response:
            assert response.status == 200
            with pytest.raises(http.client.IncompleteRead):
                response.read()
    finally:
        server.terminate()
        server.wait(timeout=3)
