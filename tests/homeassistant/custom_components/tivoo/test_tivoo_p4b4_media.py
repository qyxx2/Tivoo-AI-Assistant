"""P4b4 tests for media file parsing and shared path validation."""

from pathlib import Path
from uuid import uuid4

import pytest
import voluptuous as vol
from custom_components.tivoo.commands import TivooCommand
from homeassistant.exceptions import HomeAssistantError
from PIL import Image
from pytest_homeassistant.common import MockConfigEntry

DOMAIN = "tivoo"


class MemoryCommandAdapter:
    def __init__(self):
        self.commands = []

    async def async_execute(self, command):
        self.commands.append(command)


async def _loaded_entry(hass):
    configured_directory = f"pixelart/{uuid4().hex}"
    media_directory = Path(hass.config.path(configured_directory))
    media_directory.mkdir(parents=True, exist_ok=True)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tivoo",
        data={"media_directory": configured_directory},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    runtime = hass.data[DOMAIN][entry.entry_id]
    adapter = MemoryCommandAdapter()
    runtime["command_adapter"] = adapter
    return media_directory, adapter


def _save_static_image(path: Path, image_format: str = "PNG"):
    Image.new("RGB", (16, 16), (220, 30, 40)).save(path, format=image_format)


def _save_animated_gif(path: Path):
    frames = [
        Image.new("RGB", (16, 16), (220, 30, 40)),
        Image.new("RGB", (16, 16), (20, 80, 210)),
    ]
    frames[0].save(
        path,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=[40, 120],
        loop=0,
        disposal=2,
    )


async def _call_service(hass, service: str, data: dict):
    await hass.services.async_call(DOMAIN, service, data, blocking=True)


@pytest.mark.parametrize(
    ("extension", "image_format"), [("png", "PNG"), ("jpg", "JPEG")]
)
async def test_show_image_converts_static_png_and_jpeg_to_tivoo_pixels(
    hass, enable_custom_integrations, extension, image_format
):
    media_directory, adapter = await _loaded_entry(hass)
    _save_static_image(media_directory / f"still.{extension}", image_format)

    await _call_service(hass, "show_image", {"file": f"still.{extension}"})

    assert len(adapter.commands) == 1
    command = adapter.commands[0]
    assert isinstance(command, TivooCommand)
    assert command.name == "show_image"
    assert command.data["file"] == f"still.{extension}"
    assert len(command.data["frames"]) == 1
    assert len(command.data["frames"][0]) == 16
    assert len(command.data["frames"][0][0]) == 16
    red, green, blue = command.data["frames"][0][0][0]
    assert abs(red - 220) <= 3
    assert abs(green - 30) <= 3
    assert abs(blue - 40) <= 3
    assert command.data["delays"] == [0]


async def test_show_image_preserves_each_embedded_gif_frame_duration(
    hass, enable_custom_integrations
):
    media_directory, adapter = await _loaded_entry(hass)
    _save_animated_gif(media_directory / "animated.gif")

    await _call_service(hass, "show_image", {"file": "animated.gif"})

    command = adapter.commands[0]
    assert command.data["delays"] == [40, 120]
    assert len(command.data["frames"]) == 2
    assert command.data["frames"][0][0][0] == (220, 30, 40)
    assert command.data["frames"][1][0][0] == (20, 80, 210)


@pytest.mark.parametrize("service", ["show_image", "play_animation"])
async def test_explicit_time_overrides_all_gif_frame_durations(
    hass, enable_custom_integrations, service
):
    media_directory, adapter = await _loaded_entry(hass)
    _save_animated_gif(media_directory / "animated.gif")

    await _call_service(hass, service, {"file": "animated.gif", "time": 75})

    assert adapter.commands[0].data["delays"] == [75, 75]


@pytest.mark.parametrize("time_value", [0, 65535])
async def test_media_services_accept_time_boundaries(
    hass, enable_custom_integrations, time_value
):
    media_directory, adapter = await _loaded_entry(hass)
    _save_animated_gif(media_directory / "animated.gif")

    await _call_service(
        hass, "play_animation", {"file": "animated.gif", "time": time_value}
    )

    assert adapter.commands[0].data["delays"] == [time_value, time_value]


@pytest.mark.parametrize("time_value", [-1, 65536, 1.5, True, "100"])
async def test_media_services_reject_non_integer_or_out_of_range_time(
    hass, enable_custom_integrations, time_value
):
    media_directory, _adapter = await _loaded_entry(hass)
    _save_animated_gif(media_directory / "animated.gif")

    with pytest.raises(vol.Invalid):
        await _call_service(
            hass, "show_image", {"file": "animated.gif", "time": time_value}
        )


@pytest.mark.parametrize(
    "file_reference",
    [
        "../outside.png",
        "/etc/passwd",
        "https://example.invalid/image.png",
        "https://example.invalid/image.gif",
        "https://[",
    ],
)
async def test_media_services_reject_traversal_absolute_paths_and_urls(
    hass, enable_custom_integrations, file_reference
):
    await _loaded_entry(hass)
    with pytest.raises(HomeAssistantError, match="Media file"):
        await _call_service(hass, "show_image", {"file": file_reference})


async def test_media_services_reject_windows_absolute_paths(
    hass, enable_custom_integrations
):
    await _loaded_entry(hass)
    with pytest.raises(HomeAssistantError, match="Media file"):
        await _call_service(hass, "show_image", {"file": r"C:\Windows\win.ini"})


async def test_media_services_reject_windows_rooted_path_without_drive(
    hass, enable_custom_integrations
):
    media_directory, _adapter = await _loaded_entry(hass)
    _save_static_image(media_directory / r"\escape.png")

    with pytest.raises(HomeAssistantError, match="relative path"):
        await _call_service(hass, "show_image", {"file": r"\escape.png"})


async def test_media_services_reject_symlink_that_escapes_media_directory(
    hass, enable_custom_integrations, tmp_path
):
    media_directory, _adapter = await _loaded_entry(hass)
    outside = tmp_path / "outside.png"
    _save_static_image(outside)
    (media_directory / "escape.png").symlink_to(outside)

    with pytest.raises(HomeAssistantError, match="Media file"):
        await _call_service(hass, "show_image", {"file": "escape.png"})


async def test_media_services_reject_directory_and_missing_files(
    hass, enable_custom_integrations
):
    media_directory, _adapter = await _loaded_entry(hass)
    (media_directory / "folder").mkdir()

    for file_reference in ("folder", "missing.png"):
        with pytest.raises(HomeAssistantError, match="Media file"):
            await _call_service(hass, "show_image", {"file": file_reference})


async def test_media_services_reject_unsupported_and_corrupt_images(
    hass, enable_custom_integrations
):
    media_directory, _adapter = await _loaded_entry(hass)
    (media_directory / "notes.txt").write_text("not an image")
    (media_directory / "broken.png").write_bytes(b"not a png")

    for file_reference in ("notes.txt", "broken.png"):
        with pytest.raises(HomeAssistantError, match="media image"):
            await _call_service(hass, "show_image", {"file": file_reference})


async def test_play_animation_accepts_only_gif_files(hass, enable_custom_integrations):
    media_directory, _adapter = await _loaded_entry(hass)
    _save_static_image(media_directory / "still.png")

    with pytest.raises(HomeAssistantError, match="GIF"):
        await _call_service(hass, "play_animation", {"file": "still.png"})


async def test_show_image_keeps_transparent_sdk_pixels_black(
    hass, enable_custom_integrations
):
    media_directory, adapter = await _loaded_entry(hass)
    image = Image.new("RGBA", (16, 16), (240, 120, 40, 0))
    image.putpixel((0, 0), (240, 120, 40, 255))
    image.save(media_directory / "transparent.png")

    await _call_service(hass, "show_image", {"file": "transparent.png"})

    pixels = adapter.commands[0].data["frames"][0]
    assert pixels[0][0] == (240, 120, 40)
    assert pixels[0][1] == (0, 0, 0)
