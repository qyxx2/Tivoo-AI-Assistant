"""Host verification for the production microphone DSP and upload producer."""

import subprocess
from pathlib import Path


def test_audio_capture_and_session(tmp_path):
    source = Path(__file__).resolve().parent
    firmware = source.parents[1] / "esp32/firmware/main"
    binary = tmp_path / "audio_host"
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(firmware),
            str(source / "p65b8_audio_host.c"),
            str(firmware / "audio_capture.c"),
            str(firmware / "audio_frontend.c"),
            "-o",
            str(binary),
        ],
        check=True,
    )
    subprocess.run([str(binary)], check=True)
