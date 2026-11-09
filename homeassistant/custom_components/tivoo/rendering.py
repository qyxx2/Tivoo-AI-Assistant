"""Pure rendering helpers reused from the Tivoo Python SDK.

This module contains only pixel-frame generation. It deliberately has no
Bluetooth, CLI, or device-connection dependencies.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SCREEN_SIZE = 16
FONT_NAMES = ("unifont",)

COLORS = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "yellow": (255, 255, 0),
    "purple": (128, 0, 255),
    "cyan": (0, 255, 255),
    "orange": (255, 165, 0),
    "pink": (255, 105, 180),
}

FONT_PATHS = {
    "unifont": Path(__file__).with_name("fonts") / "unifont.otf",
}


def parse_color(color):
    """Parse an SDK-supported color name or #RRGGBB string."""
    if not isinstance(color, str):
        raise TypeError("color must be a string")
    value = color.strip()
    if value.startswith("#") and len(value) == 7:
        try:
            return (
                int(value[1:3], 16),
                int(value[3:5], 16),
                int(value[5:7], 16),
            )
        except ValueError as exc:
            raise ValueError("color must use #RRGGBB hexadecimal format") from exc
    try:
        return COLORS[value.lower()]
    except KeyError as exc:
        raise ValueError(
            f"unsupported color; choose one of {', '.join(COLORS)} or #RRGGBB"
        ) from exc


def _load_font(size=16, name="unifont"):
    """Load an installed, bundled font by its public name."""
    try:
        path = FONT_PATHS[name]
    except KeyError as exc:
        raise ValueError(f"unsupported Tivoo font: {name}") from exc
    return ImageFont.truetype(str(path), size)


def _has_cjk(text):
    """Check if text contains CJK characters."""
    for ch in text:
        cp = ord(ch)
        if (
            0x4E00 <= cp <= 0x9FFF
            or 0x3400 <= cp <= 0x4DBF
            or 0x3000 <= cp <= 0x303F
            or 0x3040 <= cp <= 0x309F
            or 0x30A0 <= cp <= 0x30FF
            or 0xAC00 <= cp <= 0xD7AF
        ):
            return True
    return False


def _auto_font_size(text):
    """Use the SDK's existing CJK/Latin size selection."""
    return 12 if _has_cjk(text) else 9


def gen_text_frames(
    text,
    color="white",
    background="black",
    speed=100,
    step=2,
    font_size=None,
    font="unifont",
):
    """Generate scrolling 16x16 RGB frames using the SDK's renderer."""
    fg = parse_color(color)
    bg_rgb = parse_color(background)
    if font_size is None:
        font_size = _auto_font_size(text)
    loaded_font = _load_font(font_size, font)

    tmp = Image.new("1", (1, 1))
    bbox = ImageDraw.Draw(tmp).textbbox((0, 0), text, font=loaded_font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    img_width = text_width + SCREEN_SIZE * 2
    mask = Image.new("1", (img_width, SCREEN_SIZE), 0)
    draw = ImageDraw.Draw(mask)
    y_offset = max(0, (SCREEN_SIZE - text_height) // 2 - bbox[1])
    draw.text((SCREEN_SIZE, y_offset), text, fill=1, font=loaded_font)

    frames = []
    for x in range(0, img_width - SCREEN_SIZE, step):
        frame_pixels = []
        for row_y in range(SCREEN_SIZE):
            row = []
            for col_x in range(SCREEN_SIZE):
                row.append(fg if mask.getpixel((col_x + x, row_y)) else bg_rgb)
            frame_pixels.append(row)
        frames.append(frame_pixels)

    return frames, [speed] * len(frames)
