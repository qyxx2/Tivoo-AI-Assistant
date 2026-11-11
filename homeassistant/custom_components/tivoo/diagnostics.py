"""TVIO v1 framing for the ESP32 diagnostic TCP channel."""

import struct
from dataclasses import dataclass

MAGIC = b"TVIO"
PROTOCOL_VERSION = 1
HEADER = struct.Struct("<4sBBHII")
HEADER_SIZE = HEADER.size
MAX_JSON_PAYLOAD = 16 * 1024
MAX_DIAGNOSTIC_PAYLOAD = 1024

TYPE_HELLO = 0x01
TYPE_HELLO_ACK = 0x02
TYPE_ERROR = 0x41
TYPE_DIAGNOSTIC_LOG = 0x42


@dataclass(frozen=True, slots=True)
class DiagnosticMessage:
    """One complete TVIO message."""

    message_type: int
    flags: int
    sequence: int
    payload: bytes


def encode_message(message_type: int, payload: bytes, sequence: int) -> bytes:
    """Encode a single TVIO v1 message with the fixed P5 header."""
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    if len(payload) > MAX_JSON_PAYLOAD:
        raise ValueError("payload exceeds the 16 KiB protocol limit")
    if not 0 <= message_type <= 0xFF:
        raise ValueError("message type must fit in one byte")
    if not 0 <= sequence <= 0xFFFFFFFF:
        raise ValueError("sequence must fit in an unsigned 32-bit integer")
    return (
        HEADER.pack(MAGIC, PROTOCOL_VERSION, message_type, 0, len(payload), sequence)
        + payload
    )


class DiagnosticFrameStream:
    """Incrementally decode one direction of a TVIO TCP byte stream."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._expected_sequence = 0

    def feed(self, data: bytes) -> list[DiagnosticMessage]:
        """Return complete messages and retain any incomplete trailing bytes."""
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        self._buffer.extend(data)
        messages: list[DiagnosticMessage] = []

        while len(self._buffer) >= HEADER_SIZE:
            magic, version, message_type, flags, payload_length, sequence = (
                HEADER.unpack_from(self._buffer)
            )
            if magic != MAGIC:
                raise ValueError("invalid TVIO magic")
            if version != PROTOCOL_VERSION:
                raise ValueError("unsupported TVIO version")
            if flags != 0:
                raise ValueError("unsupported TVIO flags")
            if payload_length > MAX_JSON_PAYLOAD:
                raise ValueError("invalid TVIO payload length")
            if message_type == TYPE_DIAGNOSTIC_LOG and (
                payload_length > MAX_DIAGNOSTIC_PAYLOAD
            ):
                raise ValueError("diagnostic payload exceeds 1 KiB limit")
            if sequence != self._expected_sequence:
                raise ValueError(
                    f"invalid TVIO sequence: expected {self._expected_sequence}, "
                    f"received {sequence}"
                )
            frame_size = HEADER_SIZE + payload_length
            if len(self._buffer) < frame_size:
                break

            payload = bytes(self._buffer[HEADER_SIZE:frame_size])
            del self._buffer[:frame_size]
            messages.append(DiagnosticMessage(message_type, flags, sequence, payload))
            self._expected_sequence = (self._expected_sequence + 1) & 0xFFFFFFFF

        return messages
