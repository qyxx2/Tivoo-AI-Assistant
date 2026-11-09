"""Tivoo media path validation and 16x16 image/GIF decoding."""

import os
from pathlib import PureWindowsPath
from urllib.parse import urlsplit

from homeassistant.exceptions import HomeAssistantError
from PIL import Image, UnidentifiedImageError

SCREEN_SIZE = 16
SUPPORTED_IMAGE_FORMATS = {"PNG", "JPEG", "GIF"}


def _has_url_scheme(filename: object) -> bool:
    if not isinstance(filename, str):
        return False
    try:
        return bool(urlsplit(filename).scheme)
    except ValueError:
        return True


def resolve_media_file(media_directory: str, filename: str) -> str:
    """Resolve a media reference and keep its real path inside the media root."""
    if (
        not isinstance(filename, str)
        or not filename.strip()
        or os.path.isabs(filename)
        or PureWindowsPath(filename).is_absolute()
        or PureWindowsPath(filename).root
        or PureWindowsPath(filename).drive
        or _has_url_scheme(filename)
        or "\x00" in filename
        or ".." in filename.replace("\\", "/").split("/")
    ):
        raise HomeAssistantError(
            "Media file must be a relative path inside the configured media directory"
        )

    real_base = os.path.realpath(media_directory)
    real_path = os.path.realpath(os.path.join(real_base, filename))
    try:
        if os.path.commonpath([real_path, real_base]) != real_base:
            raise HomeAssistantError(
                "Media file resolves outside the configured media directory"
            )
    except ValueError as err:
        raise HomeAssistantError(
            "Media file resolves outside the configured media directory"
        ) from err

    if not os.path.isfile(real_path) or not os.access(real_path, os.R_OK):
        raise HomeAssistantError(
            f"Media file does not exist, is not a file, or cannot be read: {filename}"
        )
    return real_path


def load_media_frames(
    media_directory: str,
    filename: str,
    *,
    time: int | None = None,
    gif_only: bool = False,
) -> tuple[list[list[list[tuple[int, int, int]]]], list[int]]:
    """Read an image as Tivoo 16x16 RGB frames and per-frame millisecond delays."""
    media_path = resolve_media_file(media_directory, filename)
    try:
        with Image.open(media_path) as source:
            image_format = source.format
            if image_format not in SUPPORTED_IMAGE_FORMATS:
                raise HomeAssistantError(
                    f"Unsupported media image format: {image_format or 'unknown'}"
                )
            if gif_only and image_format != "GIF":
                raise HomeAssistantError("PlayAnimation requires a GIF file")

            frame_count = source.n_frames if image_format == "GIF" else 1
            frames: list[list[list[tuple[int, int, int]]]] = []
            delays: list[int] = []
            for index in range(frame_count):
                source.seek(index)
                duration = (
                    source.info.get("duration", 0) if image_format == "GIF" else 0
                )
                rgba = source.convert("RGBA").resize(
                    (SCREEN_SIZE, SCREEN_SIZE), Image.Resampling.LANCZOS
                )
                pixels: list[list[tuple[int, int, int]]] = []
                for y in range(SCREEN_SIZE):
                    row: list[tuple[int, int, int]] = []
                    for x in range(SCREEN_SIZE):
                        red, green, blue, alpha = rgba.getpixel((x, y))
                        row.append((0, 0, 0) if alpha < 32 else (red, green, blue))
                    pixels.append(row)
                frames.append(pixels)
                delays.append(time if time is not None else int(duration or 0))

            if not frames:
                raise HomeAssistantError(f"Media image contains no frames: {filename}")
            return frames, delays
    except HomeAssistantError:
        raise
    except (OSError, UnidentifiedImageError, ValueError, EOFError) as err:
        raise HomeAssistantError(
            f"Unable to read media image '{filename}': {err}"
        ) from err
