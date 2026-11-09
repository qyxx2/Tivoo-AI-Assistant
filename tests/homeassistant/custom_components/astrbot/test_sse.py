"""Tests for the incremental AstrBot SSE parser."""

import json

import pytest
from custom_components.astrbot.sse import (
    AstrBotSseEmptyResponseError,
    AstrBotSseEvent,
    AstrBotSseIncompleteStreamError,
    AstrBotSseProtocolError,
    AstrBotSseRemoteError,
    iter_astrbot_sse,
)

SESSION_ID = "8ea2a84e-3e71-4ca3-8d53-a4b5fdf0e671"


def _frame(payload):
    return f"data: {json.dumps(payload, ensure_ascii=False)}\r\n\r\n".encode()


async def _chunks(*parts):
    for part in parts:
        yield part


async def _parse(*parts):
    return [event async for event in iter_astrbot_sse(_chunks(*parts), SESSION_ID)]


async def test_parser_handles_arbitrary_byte_splits_crlf_and_heartbeat():
    stream = (
        _frame({"type": "session_id", "data": None, "session_id": SESSION_ID})
        + b": heartbeat\r\n\r\n"
        + _frame({"type": "plain", "data": "你好，世界。", "streaming": True})
        + _frame({"type": "end", "data": ""})
    )
    events = await _parse(*(stream[index : index + 1] for index in range(len(stream))))

    assert events == [
        AstrBotSseEvent(type="session_id", data=SESSION_ID),
        AstrBotSseEvent(type="plain", data="你好，世界。"),
        AstrBotSseEvent(type="end", data=""),
    ]


async def test_parser_yields_each_plain_chunk_before_consuming_the_rest():
    consumed = []

    async def source():
        consumed.append("session")
        yield _frame({"type": "session_id", "data": None, "session_id": SESSION_ID})
        consumed.append("first text")
        yield _frame({"type": "plain", "data": "第一段"})
        consumed.append("second text")
        yield _frame({"type": "plain", "data": "第二段"})
        consumed.append("end")
        yield _frame({"type": "end", "data": ""})

    events = iter_astrbot_sse(source(), SESSION_ID)

    assert await anext(events) == AstrBotSseEvent("session_id", SESSION_ID)
    assert consumed == ["session"]
    assert await anext(events) == AstrBotSseEvent("plain", "第一段")
    assert consumed == ["session", "first text"]


async def test_parser_preserves_visible_text_and_ignores_metadata_and_internal_chains():
    events = await _parse(
        _frame({"type": "session_id", "data": None, "session_id": SESSION_ID}),
        _frame({"type": "user_message_saved", "data": {"message_id": "m-1"}}),
        _frame({"type": "plain", "data": " A "}),
        _frame({"type": "plain", "data": "B", "chain_type": "normal"}),
        _frame({"type": "plain", "data": "C", "chain_type": None}),
        _frame({"type": "plain", "data": "D", "chain_type": ""}),
        _frame({"type": "plain", "data": "reason", "chain_type": "reasoning"}),
        _frame({"type": "plain", "data": "tool", "chain_type": "tool_call"}),
        _frame({"type": "plain", "data": "result", "chain_type": "tool_call_result"}),
        _frame({"type": "plain", "data": "stats", "chain_type": "agent_stats"}),
        _frame({"type": "message_saved", "data": {"id": 1}}),
        _frame({"type": "agent_stats", "data": {"tokens": 4}}),
        _frame({"type": "image", "data": "[IMAGE]image.png"}),
        _frame({"type": "record", "data": "[RECORD]voice.wav"}),
        _frame({"type": "video", "data": "[VIDEO]video.mp4"}),
        _frame({"type": "file", "data": "[FILE]document.pdf"}),
        _frame({"type": "actionrow", "data": {"buttons": []}}),
        _frame({"type": "end", "data": ""}),
    )

    assert events == [
        AstrBotSseEvent("session_id", SESSION_ID),
        AstrBotSseEvent("plain", " A "),
        AstrBotSseEvent("plain", "B"),
        AstrBotSseEvent("plain", "C"),
        AstrBotSseEvent("plain", "D"),
        AstrBotSseEvent("end", ""),
    ]


async def test_parser_requires_session_id_as_first_data_event():
    with pytest.raises(AstrBotSseProtocolError, match="first data event"):
        await _parse(
            _frame({"type": "plain", "data": "too early"}),
            _frame({"type": "end", "data": ""}),
        )


async def test_parser_rejects_missing_or_mismatched_session_id():
    with pytest.raises(AstrBotSseIncompleteStreamError, match="session_id"):
        await _parse()

    with pytest.raises(AstrBotSseProtocolError, match="does not match"):
        await _parse(
            _frame(
                {
                    "type": "session_id",
                    "data": None,
                    "session_id": "different-session",
                }
            )
        )


async def test_parser_rejects_duplicate_session_id():
    with pytest.raises(AstrBotSseProtocolError, match="duplicate"):
        await _parse(
            _frame({"type": "session_id", "data": None, "session_id": SESSION_ID}),
            _frame({"type": "session_id", "data": None, "session_id": SESSION_ID}),
        )


async def test_parser_rejects_invalid_session_id_field_types():
    with pytest.raises(AstrBotSseProtocolError, match="session_id"):
        await _parse(_frame({"type": "session_id", "data": None, "session_id": 17}))


async def test_parser_requires_null_data_on_session_id_event():
    with pytest.raises(AstrBotSseProtocolError, match="session_id event data"):
        await _parse(_frame({"type": "session_id", "session_id": SESSION_ID}))


async def test_parser_rejects_invalid_json_and_non_object_payloads():
    with pytest.raises(AstrBotSseProtocolError, match="JSON"):
        await _parse(b"data: {not-json}\n\n")

    with pytest.raises(AstrBotSseProtocolError, match="object"):
        await _parse(b"data: []\n\n")


async def test_parser_rejects_missing_or_non_string_event_type():
    for payload in ({"data": "x"}, {"type": 3, "data": "x"}, {"type": "", "data": "x"}):
        with pytest.raises(AstrBotSseProtocolError, match="type"):
            await _parse(_frame(payload))


async def test_parser_rejects_non_string_plain_data_and_invalid_chain_type():
    session_frame = _frame(
        {"type": "session_id", "data": None, "session_id": SESSION_ID}
    )
    with pytest.raises(AstrBotSseProtocolError, match="data"):
        await _parse(
            session_frame,
            _frame({"type": "plain", "data": {"text": "not a string"}}),
        )

    for chain_type in (17, "future-internal-mode"):
        with pytest.raises(AstrBotSseProtocolError, match="chain_type"):
            await _parse(
                session_frame,
                _frame(
                    {"type": "plain", "data": "not visible", "chain_type": chain_type}
                ),
            )


async def test_parser_rejects_invalid_streaming_flag_type():
    with pytest.raises(AstrBotSseProtocolError, match="streaming"):
        await _parse(
            _frame({"type": "session_id", "data": None, "session_id": SESSION_ID}),
            _frame({"type": "plain", "data": "hello", "streaming": "yes"}),
        )


async def test_parser_requires_end_and_never_treats_eof_as_success():
    with pytest.raises(AstrBotSseIncompleteStreamError, match="end"):
        await _parse(
            _frame({"type": "session_id", "data": None, "session_id": SESSION_ID}),
            _frame({"type": "plain", "data": "partial answer"}),
        )


async def test_parser_rejects_an_unterminated_final_frame():
    with pytest.raises(AstrBotSseProtocolError, match="unterminated"):
        await _parse(
            _frame({"type": "session_id", "data": None, "session_id": SESSION_ID}),
            b'data: {"type":"end","data":""}',
        )


async def test_parser_rejects_end_without_visible_text():
    with pytest.raises(AstrBotSseEmptyResponseError, match="visible text"):
        await _parse(
            _frame({"type": "session_id", "data": None, "session_id": SESSION_ID}),
            _frame({"type": "agent_stats", "data": {"tokens": 2}}),
            _frame({"type": "end", "data": ""}),
        )


async def test_parser_requires_string_data_on_end_event():
    with pytest.raises(AstrBotSseProtocolError, match="end event data"):
        await _parse(
            _frame({"type": "session_id", "data": None, "session_id": SESSION_ID}),
            _frame({"type": "plain", "data": "visible"}),
            _frame({"type": "end"}),
        )


async def test_parser_rejects_sse_error_event():
    with pytest.raises(AstrBotSseRemoteError, match="error event"):
        await _parse(
            _frame({"type": "session_id", "data": None, "session_id": SESSION_ID}),
            _frame({"type": "plain", "data": "partial"}),
            _frame({"type": "error", "data": "upstream failed"}),
        )


async def test_parser_rejects_unknown_events_and_sse_utf8_errors():
    with pytest.raises(AstrBotSseProtocolError, match="unknown"):
        await _parse(
            _frame({"type": "session_id", "data": None, "session_id": SESSION_ID}),
            _frame({"type": "future_event", "data": {}}),
        )

    with pytest.raises(AstrBotSseProtocolError, match="UTF-8"):
        await _parse(b"\xff\xfe")


async def test_parser_ignores_standard_sse_control_fields():
    payload = (
        b"event: ignored-name\n"
        b"id: ignored-id\n"
        b"retry: 5000\n"
        + _frame({"type": "session_id", "data": None, "session_id": SESSION_ID})
        + _frame({"type": "plain", "data": "visible"})
        + _frame({"type": "end", "data": ""})
    )
    assert await _parse(payload) == [
        AstrBotSseEvent("session_id", SESSION_ID),
        AstrBotSseEvent("plain", "visible"),
        AstrBotSseEvent("end", ""),
    ]
