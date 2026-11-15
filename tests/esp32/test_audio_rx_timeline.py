"""Host regression test for RX DMA EOF gap accounting."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "esp32/firmware/main"
HARNESS = ROOT / "tests/esp32/audio_rx_timeline_host.c"


def test_rx_dma_tracker_counts_skipped_eofs(tmp_path):
    binary = tmp_path / "audio-rx-timeline"
    subprocess.run(
        [
            "gcc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(FIRMWARE),
            str(HARNESS),
            str(FIRMWARE / "audio_capture.c"),
            "-o",
            str(binary),
        ],
        check=True,
    )
    subprocess.run([str(binary)], check=True)
