"""Incremental parser for AstrBot's public Chat SSE stream."""

import codecs
import json
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from typing import Literal


class AstrBotSseError(Exception):
    """Base error for AstrBot SSE failures."""


class AstrBotSseProtocolError(AstrBotSseError):
    """The response does not follow the expected SSE protocol."""


class AstrBotSseIncompleteStreamError(AstrBotSseProtocolError):
    """The stream ended before AstrBot sent its normal end event."""


class AstrBotSseEmptyResponseError(AstrBotSseError):
    """AstrBot ended normally without producing visible text."""


class AstrBotSseRemoteError(AstrBotSseError):
    """AstrBot terminated the response with an error event."""


@dataclass(frozen=True, slots=True)
class AstrBotSseEvent:
    """A validated event exposed to the Conversation layer."""

    type: Literal["session_id", "plain", "end"]
    data: str


_IGNORED_TYPES = frozenset({"user_message_saved", "message_saved", "agent_stats"})
_IGNORED_CHAIN_TYPES = frozenset(
    {"reasoning", "tool_call", "tool_call_result", "agent_stats"}
)
_VISIBLE_CHAIN_TYPES = {None, "", "normal"}
_NON_TEXT_TYPES = frozenset(
    {
        "image",
        "record",
        "audio",
        "video",
        "file",
        "actionrow",
        "button",
        "buttoninteraction",
        "button_interaction",
        "at",
        "face",
        "node",
        "nodes",
        "poke",
        "reply",
        "forward",
        "rps",
        "dice",
        "shake",
        "share",
        "contact",
        "location",
        "music",
        "json",
    }
)


async def iter_astrbot_sse(
    chunks: AsyncIterable[bytes], expected_session_id: str
) -> AsyncIterator[AstrBotSseEvent]:
    """Yield validated session, visible-text and end events as bytes arrive.

    Only complete SSE frames are dispatched. A final frame without its blank-line
    separator is rejected so an incomplete response cannot be mistaken for end.
    """
    if not isinstance(expected_session_id, str) or not expected_session_id:
        raise ValueError("expected_session_id must be a non-empty string")

    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    line_buffer = ""
    data_lines: list[str] = []
    session_id_seen = False
    visible_text_seen = False
    first_text = True

    def process_line(line: str) -> AstrBotSseEvent | None:
        nonlocal session_id_seen, visible_text_seen

        if not line:
            if not data_lines:
                return None
            raw_data = "\n".join(data_lines)
            data_lines.clear()
            try:
                payload = json.loads(raw_data)
            except (json.JSONDecodeError, UnicodeError):
                raise AstrBotSseProtocolError(
                    "AstrBot SSE contains invalid JSON"
                ) from None

            if not isinstance(payload, dict):
                raise AstrBotSseProtocolError("AstrBot SSE data must be a JSON object")

            event_type = payload.get("type")
            if not isinstance(event_type, str) or not event_type:
                raise AstrBotSseProtocolError(
                    "AstrBot SSE event type must be a non-empty string"
                )

            if not session_id_seen and event_type != "session_id":
                raise AstrBotSseProtocolError(
                    "AstrBot's first data event must be session_id"
                )
            if session_id_seen and event_type == "session_id":
                raise AstrBotSseProtocolError(
                    "AstrBot sent a duplicate session_id event"
                )

            if event_type == "session_id":
                session_id = payload.get("session_id")
                if not isinstance(session_id, str) or not session_id:
                    raise AstrBotSseProtocolError(
                        "AstrBot session_id event must contain a string session_id"
                    )
                if "data" not in payload or payload["data"] is not None:
                    raise AstrBotSseProtocolError(
                        "AstrBot session_id event data must be null"
                    )
                if session_id != expected_session_id:
                    raise AstrBotSseProtocolError(
                        "AstrBot response session_id does not match the request"
                    )
                session_id_seen = True
                return AstrBotSseEvent("session_id", session_id)

            if event_type == "plain":
                data = payload.get("data")
                if not isinstance(data, str):
                    raise AstrBotSseProtocolError(
                        "AstrBot plain event data must be a string"
                    )
                chain_type = payload.get("chain_type")
                if chain_type is not None and not isinstance(chain_type, str):
                    raise AstrBotSseProtocolError(
                        "AstrBot plain chain_type must be a string or null"
                    )
                if "streaming" in payload and not isinstance(
                    payload["streaming"], bool
                ):
                    raise AstrBotSseProtocolError(
                        "AstrBot plain streaming flag must be a boolean"
                    )
                if chain_type in _IGNORED_CHAIN_TYPES:
                    return None
                if chain_type not in _VISIBLE_CHAIN_TYPES:
                    raise AstrBotSseProtocolError(
                        f"AstrBot sent an unknown plain chain_type: {chain_type}"
                    )
                if data:
                    if data.strip():
                        visible_text_seen = True
                    return AstrBotSseEvent("plain", data)
                return None

            if event_type in _IGNORED_TYPES or event_type in _NON_TEXT_TYPES:
                return None

            if event_type == "end":
                data = payload.get("data")
                if not isinstance(data, str):
                    raise AstrBotSseProtocolError(
                        "AstrBot end event data must be a string"
                    )
                if not visible_text_seen:
                    raise AstrBotSseEmptyResponseError(
                        "AstrBot ended without visible text"
                    )
                return AstrBotSseEvent("end", data)

            if event_type == "error":
                raise AstrBotSseRemoteError("AstrBot returned an SSE error event")

            raise AstrBotSseProtocolError(
                f"AstrBot sent an unknown SSE event type: {event_type}"
            )

        if line.startswith(":"):
            return None

        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if field == "data":
            data_lines.append(value)
        # event, id, retry and extension fields do not affect AstrBot's JSON
        # event contract. The server identifies events inside the JSON payload.
        return None

    def extract_lines(text: str, *, final: bool = False) -> list[str]:
        nonlocal line_buffer
        line_buffer += text
        lines: list[str] = []
        start = 0
        index = 0

        while index < len(line_buffer):
            char = line_buffer[index]
            if char == "\n":
                lines.append(line_buffer[start:index])
                index += 1
                start = index
                continue
            if char == "\r":
                if index + 1 == len(line_buffer) and not final:
                    break
                lines.append(line_buffer[start:index])
                if index + 1 < len(line_buffer) and line_buffer[index + 1] == "\n":
                    index += 2
                else:
                    index += 1
                start = index
                continue
            index += 1

        line_buffer = line_buffer[start:]
        if final and line_buffer:
            lines.append(line_buffer)
            line_buffer = ""
        return lines

    async for chunk in chunks:
        if not isinstance(chunk, bytes):
            raise AstrBotSseProtocolError("AstrBot SSE stream chunks must be bytes")
        try:
            decoded = decoder.decode(chunk)
        except UnicodeDecodeError:
            raise AstrBotSseProtocolError(
                "AstrBot SSE stream is not valid UTF-8"
            ) from None
        if first_text and decoded:
            decoded = decoded.removeprefix("\ufeff")
            first_text = False
        for line in extract_lines(decoded):
            event = process_line(line)
            if event is not None:
                yield event
                if event.type == "end":
                    return

    try:
        final_text = decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        raise AstrBotSseProtocolError("AstrBot SSE stream is not valid UTF-8") from None

    for line in extract_lines(final_text, final=True):
        event = process_line(line)
        if event is not None:
            yield event
            if event.type == "end":
                return

    if data_lines:
        raise AstrBotSseProtocolError("AstrBot SSE ended with an unterminated frame")
    if not session_id_seen:
        raise AstrBotSseIncompleteStreamError(
            "AstrBot SSE ended before the session_id event"
        )
    raise AstrBotSseIncompleteStreamError(
        "AstrBot SSE ended before the normal end event"
    )
