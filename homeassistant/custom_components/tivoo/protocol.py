"""Tivoo RFCOMM framing and payload encoding reused by the ESP32 bridge.

The packet checksum, RGB palette packing, image frame and animation chunk
formats are adapted from solar2ain/tivoo-control (MIT), pinned in UPSTREAM.md.
"""

from collections.abc import Sequence

ANIMATION_CHUNK_SIZE = 200
SCREEN_SIZE = 16
MAX_TIVOO_PACKET_SIZE = 4608


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def encode_tivoo_frame(payload: bytes | bytearray | Sequence[int]) -> bytes:
    """Wrap one Divoom command payload in its checksummed 0x01...0x02 frame."""
    payload = bytes(payload)
    length = len(payload) + 2
    if length > 0xFFFF:
        raise ValueError("Tivoo payload exceeds the 16-bit frame length")
    length_bytes = length.to_bytes(2, "little")
    checksum = (sum(length_bytes) + sum(payload)) & 0xFFFF
    packet = b"\x01" + length_bytes + payload + checksum.to_bytes(2, "little") + b"\x02"
    if len(packet) > MAX_TIVOO_PACKET_SIZE:
        raise ValueError("Tivoo packet exceeds the ESP32 frame-stream buffer")
    return packet


def encode_payload(payload: bytes | bytearray | Sequence[int]) -> bytes:
    """Public alias used by tests and command serialization."""
    return encode_tivoo_frame(payload)


def encode_image_frame(
    pixels: Sequence[Sequence[Sequence[int]]], timecode: int = 0
) -> bytes:
    """Encode a 16x16 RGB array using the upstream Divoom palette format."""
    timecode = _integer(timecode, "timecode", 0, 65535)
    if len(pixels) != SCREEN_SIZE or any(len(row) != SCREEN_SIZE for row in pixels):
        raise ValueError("Tivoo image must be a 16x16 RGB pixel array")

    palette: list[tuple[int, int, int]] = []
    color_indexes: dict[tuple[int, int, int], int] = {}
    indexes: list[int] = []
    for row in pixels:
        for pixel in row:
            if len(pixel) != 3:
                raise ValueError("each Tivoo pixel must contain three RGB channels")
            color = tuple(_integer(channel, "RGB channel", 0, 255) for channel in pixel)
            index = color_indexes.get(color)
            if index is None:
                index = len(palette)
                color_indexes[color] = index
                palette.append(color)
            indexes.append(index)

    color_count = len(palette)
    if not color_count:
        raise ValueError("Tivoo image must contain at least one color")
    palette_bytes = bytes(channel for color in palette for channel in color)
    if color_count == 1:
        pixel_bytes = bytes(32)
    else:
        bits_per_pixel = (color_count - 1).bit_length()
        bit_string = "".join(
            format(index, "08b")[::-1][:bits_per_pixel] for index in indexes
        )
        bit_string += "0" * (-len(bit_string) % 8)
        pixel_bytes = bytes(
            int(bit_string[index : index + 8][::-1], 2)
            for index in range(0, len(bit_string), 8)
        )

    frame_content = (
        timecode.to_bytes(2, "little")
        + b"\x00"
        + bytes((color_count & 0xFF,))
        + palette_bytes
        + pixel_bytes
    )
    frame_size = len(frame_content) + 3
    return b"\xaa" + frame_size.to_bytes(2, "little") + frame_content


def _animation_payloads(
    frames: Sequence[Sequence[Sequence[Sequence[int]]]],
    delays: Sequence[int],
) -> list[bytes]:
    if not frames:
        raise ValueError("animation must contain at least one frame")
    if len(frames) != len(delays):
        raise ValueError("animation delays must match the frame count")

    data = bytearray()
    for frame, delay in zip(frames, delays):
        duration = _integer(delay, "frame delay", 0, 65535)
        data.extend(encode_image_frame(frame, timecode=duration))

    total_size = len(data)
    if total_size > 65535:
        raise ValueError("Tivoo animation data exceeds 65535 bytes")
    chunks = [
        bytes((0x49, total_size & 0xFF, total_size >> 8, index))
        + data[offset : offset + ANIMATION_CHUNK_SIZE]
        for index, offset in enumerate(range(0, total_size, ANIMATION_CHUNK_SIZE))
    ]
    if len(chunks) > 256:
        raise ValueError("Tivoo animation exceeds the one-byte chunk-index limit")
    return chunks


def encode_command(command) -> tuple[bytes, ...]:
    """Convert one HA semantic command to one or more complete Tivoo frames."""
    data = command.data
    name = command.name

    if name == "set_brightness":
        payloads = [bytes((0x74, _integer(data["value"], "brightness", 0, 100)))]
    elif name == "set_volume":
        volume = _integer(data["volume"], "volume", 0, 100)
        payloads = [bytes((0x08, volume * 15 // 100))]
    elif name == "start_countdown":
        countdown = data["countdown"]
        if (
            not isinstance(countdown, str)
            or len(countdown) != 5
            or countdown[2] != ":"
            or not countdown[:2].isdigit()
            or not countdown[3:].isdigit()
        ):
            raise ValueError("countdown must use strict MM:SS format")
        minutes, seconds = int(countdown[:2]), int(countdown[3:])
        if seconds > 59:
            raise ValueError("countdown seconds must be between 00 and 59")
        payloads = [bytes((0x72, 0x03, 0x01, minutes, seconds))]
    elif name == "stop_countdown":
        payloads = [bytes((0x72, 0x03, 0x00, 0x00, 0x00))]
    elif name == "show_image" and len(data.get("frames", [])) == 1:
        image = encode_image_frame(data["frames"][0], timecode=0)
        payloads = [bytes.fromhex("44 00 0A 0A 04") + image]
    elif name in {
        "set_expression",
        "show_text",
        "show_image",
        "play_animation",
    }:
        frames = data.get("frames")
        delays = data.get("delays")
        if not isinstance(frames, Sequence) or isinstance(frames, (str, bytes)):
            raise ValueError("command frames must be a sequence")
        if not isinstance(delays, Sequence) or isinstance(delays, (str, bytes)):
            raise ValueError("command delays must be a sequence")
        payloads = _animation_payloads(frames, delays)
    else:
        raise ValueError(f"unsupported Tivoo command: {name}")

    return tuple(encode_tivoo_frame(payload) for payload in payloads)
