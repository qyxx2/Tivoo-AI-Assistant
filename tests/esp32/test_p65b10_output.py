import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "esp32/firmware/main"


def test_generation_stop_and_dma_completion(tmp_path):
    binary = tmp_path / "output"
    subprocess.run(
        [
            "gcc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(FIRMWARE),
            str(Path(__file__).with_name("p65b10_output_host.c")),
            str(FIRMWARE / "audio_output_manager.c"),
            "-o",
            str(binary),
        ],
        check=True,
    )
    subprocess.run([str(binary)], check=True)
