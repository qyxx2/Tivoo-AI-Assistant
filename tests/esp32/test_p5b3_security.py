"""Host-compiled tests for production P5b3 GAP security policy."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_MAIN = ROOT / "esp32/firmware/main"
SECURITY_HOST = ROOT / "esp32/tests/p5b3_security_simulator/security_host.c"


def test_gap_security_policy_callbacks_and_bond_matching(tmp_path):
    binary = tmp_path / "p5b3-security-host"
    subprocess.run(
        [
            "gcc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(FIRMWARE_MAIN),
            str(FIRMWARE_MAIN / "bt_security_policy.c"),
            str(SECURITY_HOST),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    assert result.stdout.strip() == "P5b3 GAP policy checks passed"
