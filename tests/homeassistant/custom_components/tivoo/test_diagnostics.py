"""Tests for the ESP32 TVIO diagnostics stream codec."""

import pytest
from custom_components.tivoo.diagnostics import (
    DiagnosticFrameStream,
    DiagnosticMessage,
    encode_message,
)


def _frame(message_type: int, sequence: int, payload: bytes) -> bytes:
    return (
        b"TVIO"
        + bytes((1, message_type))
        + b"\x00\x00"
        + len(payload).to_bytes(4, "little")
        + sequence.to_bytes(4, "little")
        + payload
    )


def test_encode_message_uses_the_fixed_little_endian_16_byte_header():
    payload = b'{"accepted":true}'

    encoded = encode_message(0x02, payload, 0)

    assert encoded == (
        b"TVIO"
        + b"\x01\x02"
        + b"\x00\x00"
        + len(payload).to_bytes(4, "little")
        + b"\x00\x00\x00\x00"
        + payload
    )


def test_stream_keeps_partial_header_and_payload_until_complete():
    payload = b'{"device_id":"tivoo-esp32"}'
    encoded = _frame(0x01, 0, payload)
    stream = DiagnosticFrameStream()

    assert stream.feed(encoded[:9]) == []
    assert stream.feed(encoded[9:16]) == []
    assert stream.feed(encoded[16:]) == [DiagnosticMessage(0x01, 0, 0, payload)]


def test_stream_returns_multiple_coalesced_messages_in_sequence_order():
    first = _frame(0x01, 0, b'{"hello":1}')
    second = _frame(0x42, 1, b'{"level":"INFO"}')
    stream = DiagnosticFrameStream()

    assert stream.feed(first + second) == [
        DiagnosticMessage(0x01, 0, 0, b'{"hello":1}'),
        DiagnosticMessage(0x42, 0, 1, b'{"level":"INFO"}'),
    ]


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        (b"NOPE" + b"\x01\x01" + bytes(10), "magic"),
        (_frame(0x01, 0, b"")[:4] + b"\x02" + _frame(0x01, 0, b"")[5:], "version"),
        (_frame(0x01, 0, b"")[:6] + b"\x01\x00" + _frame(0x01, 0, b"")[8:], "flags"),
        (
            b"TVIO\x01\x01\x00\x00" + (16 * 1024 + 1).to_bytes(4, "little") + bytes(4),
            "length",
        ),
    ],
)
def test_stream_rejects_invalid_headers_and_payload_lengths(frame, message):
    with pytest.raises(ValueError, match=message):
        DiagnosticFrameStream().feed(frame)


def test_stream_rejects_messages_outside_the_expected_sequence():
    stream = DiagnosticFrameStream()

    with pytest.raises(ValueError, match="sequence"):
        stream.feed(_frame(0x01, 1, b"{}"))


def test_encoder_rejects_payload_over_the_protocol_limit():
    with pytest.raises(ValueError, match="payload"):
        encode_message(0x42, b"x" * (16 * 1024 + 1), 0)


def test_stream_rejects_a_diagnostic_record_larger_than_one_kibibyte():
    oversized_log = _frame(0x42, 0, b"x" * 1025)

    with pytest.raises(ValueError, match="1 KiB"):
        DiagnosticFrameStream().feed(oversized_log)
