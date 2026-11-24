"""The real-log acceptance CLI must not pass a stream that later fails."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/verify-p68-afe-boot.py"
BOOT = ("s3_afe: feed=1024 x4 fetch=512 x1\n"
        "main_task: Returned from app_main()\nstation_connected\n")
GOOD = ("I (10000) s3_afe: feed=100 fetch=200 feed_errors=0 fetch_errors=0 rx_gaps=1 resets=1\n"
        "I (20000) s3_afe: feed=200 fetch=400 feed_errors=0 fetch_errors=0 rx_gaps=1 resets=1\n")


@pytest.mark.parametrize("tail,expected", [
    ("", 0),
    (("s3_afe: AFE reset failed: reset_buffer failed\n"
      "s3_afe: AFE unavailable: reset_buffer failed\n"), 1),
    ("s3_afe: feed=300 fetch=600 feed_errors=0 fetch_errors=0 rx_gaps=3 resets=2\n", 1),
])
def test_runtime_log_rejects_late_failure_and_growing_gaps(tmp_path, tail, expected):
    log = tmp_path / "boot.txt"
    log.write_text(BOOT + GOOD + tail)
    result = subprocess.run([sys.executable, str(SCRIPT), str(log)], check=False,
                            capture_output=True, text=True)
    assert result.returncode == expected, result.stdout + result.stderr


@pytest.mark.parametrize("counter", ["overruns", "missed_eof", "capture_overruns"])
def test_runtime_log_rejects_drops_before_gap_packet_is_consumed(tmp_path, counter):
    # A busy feed can still be processing old queued PCM when capture drops.
    # Unchanged rx_gaps/resets must not hide physical or task-queue losses.
    log = tmp_path / "boot.txt"
    rows = GOOD.splitlines()
    log.write_text(BOOT + rows[0] + f" {counter}=0\n" + rows[1] + f" {counter}=4\n")
    result = subprocess.run([sys.executable, str(SCRIPT), str(log)], check=False,
                            capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr


@pytest.mark.parametrize("tail", [
    "I (330000) uart_bridge: heartbeat ok\n",
    "I (30000) s3_afe: feed=200 fetch=400 feed_errors=0 fetch_errors=0 rx_gaps=1 resets=1\n",
    "I (330000) s3_afe: feed=300 fetch=600 feed_errors=0 fetch_errors=0 rx_gaps=1 resets=1\n",
])
def test_runtime_log_rejects_silent_stall_or_missing_telemetry(tmp_path, tail):
    log = tmp_path / "boot.txt"
    log.write_text(BOOT + GOOD + tail)
    result = subprocess.run([sys.executable, str(SCRIPT), str(log)], check=False,
                            capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr


def test_minimum_observation_rejects_capture_that_stopped_early(tmp_path):
    log = tmp_path / "boot.txt"
    log.write_text(BOOT + GOOD)
    result = subprocess.run([sys.executable, str(SCRIPT), str(log),
                             "--min-runtime-seconds", "300"], check=False,
                            capture_output=True, text=True)
    assert result.returncode == 1 and "observation" in result.stdout, result.stdout + result.stderr


def test_minimum_observation_accepts_continuous_timestamped_progress(tmp_path):
    log = tmp_path / "boot.txt"
    rows = [f"I ({i*10000}) s3_afe: feed={i*156} fetch={i*312} "
            "feed_errors=0 fetch_errors=0 rx_gaps=1 resets=0\n" for i in range(1, 32)]
    log.write_text(BOOT + "".join(rows))
    result = subprocess.run([sys.executable, str(SCRIPT), str(log),
                             "--min-runtime-seconds", "300"], check=False,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
