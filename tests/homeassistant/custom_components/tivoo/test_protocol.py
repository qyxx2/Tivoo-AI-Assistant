"""Tivoo frame encoding contract for the ESP32 raw control bridge."""

import pytest
from custom_components.tivoo.commands import TivooCommand
from custom_components.tivoo.protocol import (
    ANIMATION_CHUNK_SIZE,
    encode_command,
    encode_payload,
    encode_tivoo_frame,
)


def _frame(pixels):
    return [[pixels for _ in range(16)] for _ in range(16)]


def _payload(packet):
    assert packet[0] == 0x01 and packet[-1] == 0x02
    length = int.from_bytes(packet[1:3], "little")
    payload = packet[3:-3]
    assert length == len(payload) + 2
    assert (
        int.from_bytes(packet[-3:-1], "little")
        == (sum(packet[1:3]) + sum(payload)) & 0xFFFF
    )
    return payload


def test_brightness_packet_matches_upstream_golden_vector():
    assert encode_tivoo_frame(bytes.fromhex("74 64")) == bytes.fromhex(
        "01 04 00 74 64 DC 00 02"
    )


def test_payload_packet_uses_little_endian_length_and_checksum():
    payload = bytes.fromhex("45 00 01 01 01 00 00 00 FF FF FF")
    packet = encode_payload(payload)
    assert _payload(packet) == payload


def test_static_image_uses_upstream_palette_and_image_command():
    frame = _frame((0, 0, 0))
    frame[0][0] = (255, 0, 0)
    packets = encode_command(
        TivooCommand("show_image", {"frames": [frame], "delays": [0]})
    )
    assert len(packets) == 1
    payload = _payload(packets[0])
    assert payload[:5] == bytes.fromhex("44 00 0A 0A 04")
    assert payload[5] == 0xAA
    assert int.from_bytes(payload[6:8], "little") == len(payload[5:])


def test_animation_chunks_reuse_200_byte_upstream_limit_and_keep_frame_order():
    first = _frame((0, 0, 0))
    second = [
        [((x * 17) & 255, (y * 17) & 255, ((x + y) * 9) & 255) for x in range(16)]
        for y in range(16)
    ]
    packets = encode_command(
        TivooCommand("play_animation", {"frames": [first, second], "delays": [80, 120]})
    )
    assert len(packets) >= 2
    payloads = [_payload(packet) for packet in packets]
    assert all(payload[0] == 0x49 for payload in payloads)
    total = int.from_bytes(payloads[0][1:3], "little")
    assert all(int.from_bytes(payload[1:3], "little") == total for payload in payloads)
    assert [payload[3] for payload in payloads] == list(range(len(payloads)))
    assert all(len(payload) - 4 <= ANIMATION_CHUNK_SIZE for payload in payloads)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (TivooCommand("set_brightness", {"value": 100}), bytes.fromhex("74 64")),
        (TivooCommand("set_volume", {"volume": 100}), bytes.fromhex("08 0F")),
        (TivooCommand("set_volume", {"volume": 50}), bytes.fromhex("08 07")),
        (
            TivooCommand("start_countdown", {"countdown": "01:30"}),
            bytes.fromhex("72 03 01 01 1E"),
        ),
        (TivooCommand("stop_countdown", {}), bytes.fromhex("72 03 00 00 00")),
    ],
)
def test_simple_services_map_to_upstream_payloads(command, expected):
    packets = encode_command(command)
    assert len(packets) == 1
    assert _payload(packets[0]) == expected


@pytest.mark.parametrize(
    "command",
    [
        TivooCommand("set_brightness", {"value": 101}),
        TivooCommand("set_volume", {"volume": -1}),
        TivooCommand("start_countdown", {"countdown": "1:30"}),
        TivooCommand("show_image", {"frames": [], "delays": []}),
        TivooCommand("show_text", {"frames": [_frame((256, 0, 0))], "delays": [100]}),
        TivooCommand("unknown", {}),
    ],
)
def test_invalid_or_unsupported_commands_are_rejected(command):
    with pytest.raises((TypeError, ValueError)):
        encode_command(command)


@pytest.mark.parametrize(
    "name",
    ["set_expression", "show_text", "play_animation", "show_image"],
)
def test_visual_services_encode_animation_frames_when_multiple_frames_are_supplied(
    name,
):
    first = _frame((0, 0, 0))
    second = _frame((255, 0, 0))
    packets = encode_command(
        TivooCommand(name, {"frames": [first, second], "delays": [100, 120]})
    )
    assert packets
    assert all(_payload(packet)[0] == 0x49 for packet in packets)


def test_static_image_service_uses_the_single_image_command():
    image = _frame((0, 0, 0))
    packet = encode_command(
        TivooCommand("show_image", {"frames": [image], "delays": [0]})
    )[0]
    assert _payload(packet)[:5] == bytes.fromhex("44 00 0A 0A 04")
    assert _payload(packet)[5] == 0xAA


@pytest.mark.parametrize(
    ("command", "expected_payloads"),
    [
        (
            TivooCommand("set_screen_power", {"value": True}),
            (bytes.fromhex("45 01 01 01 01 64 00 01 00 00 00"),),
        ),
        (
            TivooCommand("set_screen_power", {"value": False}),
            (bytes.fromhex("45 01 01 01 01 00 00 00 00 00 00"),),
        ),
        (
            TivooCommand("set_playstate", {"value": "pause"}),
            (bytes.fromhex("0A 00"),),
        ),
        (
            TivooCommand("set_playstate", {"value": "next"}),
            (bytes.fromhex("12 01"),),
        ),
        (
            TivooCommand(
                "show_clock",
                {
                    "clock": 3,
                    "twentyfour": True,
                    "weather": True,
                    "temp": True,
                    "calendar": True,
                    "color": "#0A141E",
                    "hot": True,
                },
            ),
            (
                bytes.fromhex("2D 01"),
                bytes.fromhex("45 00 01 03 01 01 01 01 0A 14 1E"),
                bytes.fromhex("26 01"),
            ),
        ),
        (
            TivooCommand("set_datetime", {"value": "2024-01-02T03:04:05"}),
            (bytes.fromhex("18 18 14 01 02 03 04 05"),),
        ),
        (
            TivooCommand(
                "set_weather",
                {"temperature": 22, "condition": 3, "unit": "C"},
            ),
            (bytes.fromhex("5F 16 03"), bytes.fromhex("2B 00")),
        ),
        (
            TivooCommand(
                "set_light",
                {
                    "brightness": 77,
                    "color": "#FF0080",
                    "effect": 0,
                    "power": True,
                },
            ),
            (bytes.fromhex("45 01 FF 00 80 4D 00 01 00 00 00"),),
        ),
        (
            TivooCommand("show_lyrics", {}),
            (bytes.fromhex("45 06 00 00 00"),),
        ),
        (
            TivooCommand(
                "show_scoreboard",
                {"player1": 12, "player2": 34},
            ),
            (bytes.fromhex("72 01 01 22 00 0C 00"),),
        ),
        (
            TivooCommand("set_timer", {"value": True}),
            (bytes.fromhex("72 00 01"),),
        ),
        (
            TivooCommand("set_noise_meter", {"value": False}),
            (bytes.fromhex("72 02 02"),),
        ),
        (
            TivooCommand("set_audio_source", {"value": "linein"}),
            (bytes.fromhex("05 02"),),
        ),
        (
            TivooCommand(
                "set_sleep_mode",
                {
                    "value": True,
                    "time": 45,
                    "mode": 1,
                    "frequency": 99.5,
                    "volume": 50,
                    "color": "#090909",
                    "brightness": 60,
                },
            ),
            (bytes.fromhex("40 2D 01 01 5F 09 32 09 09 09 3C"),),
        ),
        (
            TivooCommand("show_design", {"number": 2}),
            (bytes.fromhex("45 05"), bytes.fromhex("BD 17 02")),
        ),
        (
            TivooCommand("show_effects", {"number": 2}),
            (bytes.fromhex("45 03 02"),),
        ),
        (
            TivooCommand("show_visualization", {"number": 1}),
            (bytes.fromhex("45 04 01"),),
        ),
        (
            TivooCommand("show_game", {"index": 2}),
            (bytes.fromhex("A0 01 02"),),
        ),
        (
            TivooCommand("game_control", {"value": "left"}),
            (bytes.fromhex("17 01"), bytes.fromhex("21 01")),
        ),
    ],
)
def test_extended_spp_commands_match_pinned_upstream_vectors(
    command, expected_payloads
):
    packets = encode_command(command)
    assert tuple(_payload(packet) for packet in packets) == expected_payloads


def test_alarm_payload_keeps_the_constrained_upstream_fields():
    packet = encode_command(
        TivooCommand(
            "set_alarm",
            {
                "slot": 1,
                "time": "07:30",
                "weekdays": ["mon", "tue", "wed", "thu", "fri"],
                "frequency": 100.3,
                "volume": 80,
            },
        )
    )[0]
    assert _payload(packet) == bytes.fromhex("43 01 01 07 1E 3E 00 00 03 0A 50")


def test_memorial_payload_matches_esp32_divoom_utf16_golden_shape():
    packet = encode_command(
        TivooCommand(
            "set_memorial",
            {
                "slot": 2,
                "value": "2024-05-06T12:00:00",
                "text": "Test ",
            },
        )
    )[0]
    expected = bytes.fromhex(
        "54 02 01 05 06 0C 00 01 00 54 00 65 00 73 00 74 00 20 "
        "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
        "00 00 00 00 00 00"
    )
    assert _payload(packet) == expected
