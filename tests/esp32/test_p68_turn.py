import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "esp32/firmware/main"


def test_local_turn_host(tmp_path):
    exe = tmp_path / "turn"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-I", str(MAIN), str(Path(__file__).with_name("p68_turn_host.c")),
                    str(MAIN / "p68_local_turn.c"), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
