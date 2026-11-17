"""P6.7b0: versioned prompt MP3s and the real HA /local static route."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from homeassistant.setup import async_setup_component

ASSETS = Path(__file__).resolve().parents[4] / "homeassistant" / "prompt_assets"
NAMES = tuple(f"ready_{number:02d}.mp3" for number in range(1, 4)) + (
    "followup_01.mp3",
)


def _check_asset(path: Path) -> None:
    assert path.is_file(), f"missing prompt asset: {path.name}"
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,sample_rate,channels:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    probe = json.loads(result.stdout)
    audio = probe["streams"][0]
    assert audio["codec_name"] == "mp3"
    assert audio["sample_rate"] == "32000"
    assert audio["channels"] == 1
    assert 0.08 < float(probe["format"]["duration"]) <= 0.9
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        check=True,
    )


@pytest.mark.parametrize("name", NAMES)
def test_versioned_prompt_asset_is_short_mono_mp3(name):
    _check_asset(ASSETS / name)


@pytest.mark.parametrize("name", NAMES)
def test_versioned_prompt_asset_keeps_leading_and_trailing_silence(name):
    path = ASSETS / name
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    duration = float(probe.stdout.strip())
    detected = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            "silencedetect=noise=-45dB:d=0.03",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stderr
    starts = [
        float(value) for value in re.findall(r"silence_start: ([0-9.]+)", detected)
    ]
    ends = [float(value) for value in re.findall(r"silence_end: ([0-9.]+)", detected)]
    assert starts and ends
    assert starts[0] <= 0.01
    assert ends[0] >= 0.10
    assert duration - starts[-1] >= 0.15
    assert abs(ends[-1] - duration) <= 0.03


def test_missing_asset_is_rejected(tmp_path):
    with pytest.raises(AssertionError, match="missing prompt asset"):
        _check_asset(tmp_path / "missing.mp3")


def test_wrong_codec_is_rejected(tmp_path):
    path = tmp_path / "wrong.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.4:sample_rate=32000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            str(path),
        ],
        check=True,
    )
    with pytest.raises(AssertionError, match="mp3"):
        _check_asset(path)


def test_too_long_asset_is_rejected(tmp_path):
    path = tmp_path / "long.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.2:sample_rate=32000",
            "-ac",
            "1",
            "-c:a",
            "libmp3lame",
            str(path),
        ],
        check=True,
    )
    with pytest.raises(AssertionError):
        _check_asset(path)


@pytest.mark.enable_socket
async def test_ha_frontend_serves_each_prompt_without_auth(hass, aiohttp_client):
    www = Path(hass.config.path("www")) / "tivoo" / "prompts"
    www.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        shutil.copyfile(ASSETS / name, www / name)
    try:
        assert await async_setup_component(hass, "frontend", {})
        client = await aiohttp_client(hass.http.app)
        for name in NAMES:
            response = await client.get(f"/local/tivoo/prompts/{name}")
            assert response.status == 200
            assert not response.history  # no login or authentication redirects
            assert response.content_type == "audio/mpeg"
            assert await response.read() == (ASSETS / name).read_bytes()
    finally:
        for name in NAMES:
            (www / name).unlink(missing_ok=True)
        for directory in (www, www.parent, www.parent.parent):
            try:
                directory.rmdir()
            except OSError:
                pass  # Preserve other tests' files.
