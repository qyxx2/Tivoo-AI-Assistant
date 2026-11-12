"""TVIO v1 framing for the ESP32 diagnostic TCP channel."""

import struct
from dataclasses import dataclass

MAGIC = b"TVIO"
PROTOCOL_VERSION = 1
HEADER = struct.Struct("<4sBBHII")
HEADER_SIZE = HEADER.size
MAX_JSON_PAYLOAD = 16 * 1024
MAX_MIC_PCM_PAYLOAD = 4 * 1024
MAX_DIAGNOSTIC_PAYLOAD = 1024

TYPE_HELLO = 0x01
TYPE_HELLO_ACK = 0x02
TYPE_PING = 0x03
TYPE_PONG = 0x04
TYPE_GET_STATUS = 0x10
TYPE_DEVICE_STATUS = 0x11
TYPE_MIC_SESSION_START = 0x20
TYPE_MIC_PCM = 0x21
TYPE_MIC_SESSION_END = 0x22
TYPE_MIC_CAPTURE_STOP = 0x23
TYPE_TTS_PLAY = 0x30
TYPE_AUDIO_STOP = 0x31
TYPE_AUDIO_STATE = 0x32
TYPE_AUDIO_INTERRUPTED = 0x33
TYPE_DEVICE_EVENT = 0x40
TYPE_ERROR = 0x41
TYPE_DIAGNOSTIC_LOG = 0x42

SUPPORTED_MESSAGE_TYPES = frozenset(
    {
        TYPE_HELLO,
        TYPE_HELLO_ACK,
        TYPE_PING,
        TYPE_PONG,
        TYPE_GET_STATUS,
        TYPE_DEVICE_STATUS,
        TYPE_MIC_SESSION_START,
        TYPE_MIC_PCM,
        TYPE_MIC_SESSION_END,
        TYPE_MIC_CAPTURE_STOP,
        TYPE_TTS_PLAY,
        TYPE_AUDIO_STOP,
        TYPE_AUDIO_STATE,
        TYPE_AUDIO_INTERRUPTED,
        TYPE_DEVICE_EVENT,
        TYPE_ERROR,
        TYPE_DIAGNOSTIC_LOG,
    }
)


HA_TO_ESP32_MESSAGE_TYPES = frozenset(
    {
        TYPE_PING,
        TYPE_GET_STATUS,
        TYPE_MIC_CAPTURE_STOP,
        TYPE_TTS_PLAY,
        TYPE_AUDIO_STOP,
        TYPE_ERROR,
    }
)
ESP32_TO_HA_MESSAGE_TYPES = frozenset(
    {
        TYPE_PONG,
        TYPE_DEVICE_STATUS,
        TYPE_MIC_SESSION_START,
        TYPE_MIC_PCM,
        TYPE_MIC_SESSION_END,
        TYPE_AUDIO_STATE,
        TYPE_AUDIO_INTERRUPTED,
        TYPE_DEVICE_EVENT,
        TYPE_ERROR,
        TYPE_DIAGNOSTIC_LOG,
    }
)


@dataclass(frozen=True, slots=True)
class DiagnosticMessage:
    """One complete TVIO message."""

    message_type: int
    flags: int
    sequence: int
    payload: bytes


def _validate_payload(message_type: int, payload_size: int) -> None:
    if payload_size > MAX_JSON_PAYLOAD:
        raise ValueError("payload exceeds the 16 KiB protocol limit")
    if message_type == TYPE_MIC_PCM and payload_size > MAX_MIC_PCM_PAYLOAD:
        raise ValueError("MIC_PCM payload exceeds the 4 KiB protocol limit")
    if message_type == TYPE_DIAGNOSTIC_LOG and payload_size > MAX_DIAGNOSTIC_PAYLOAD:
        raise ValueError("diagnostic payload exceeds 1 KiB limit")


def encode_message(message_type: int, payload: bytes, sequence: int) -> bytes:
    """Encode a single TVIO v1 message with the fixed P5 header."""
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    if not 0 <= message_type <= 0xFF:
        raise ValueError("message type must fit in one byte")
    if not 0 <= sequence <= 0xFFFFFFFF:
        raise ValueError("sequence must fit in an unsigned 32-bit integer")
    _validate_payload(message_type, len(payload))
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
            _validate_payload(message_type, payload_length)
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
