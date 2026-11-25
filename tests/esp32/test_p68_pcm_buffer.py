"""Actual SPSC receive-buffer logic, including wrap and short EOF."""
import subprocess
from pathlib import Path


def test_pcm_receive_buffer(tmp_path):
    root = Path(__file__).resolve().parents[2]
    exe = tmp_path / "pcm-buffer"
    subprocess.run([
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
        "-I", str(root / "esp32/firmware/main"),
        str(Path(__file__).with_name("p68_pcm_buffer_host.c")),
        "-o", str(exe),
    ], check=True)
    subprocess.run([str(exe)], check=True)
