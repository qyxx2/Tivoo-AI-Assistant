"""Host-compiled tests for the production SPP worker session policy."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_MAIN = ROOT / "esp32/firmware/main"
SESSION_HOST = ROOT / "esp32/tests/p5b3_security_simulator/session_host.c"


def test_spp_worker_fifo_switch_chunking_and_write_completion_gate(tmp_path):
    binary = tmp_path / "p5b3-spp-session-host"
    subprocess.run(
        [
            "gcc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(FIRMWARE_MAIN),
            str(FIRMWARE_MAIN / "tivoo_spp_session.c"),
            str(SESSION_HOST),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    assert result.stdout.strip() == "P5b3 SPP session ordering checks passed"
