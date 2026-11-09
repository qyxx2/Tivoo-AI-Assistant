"""Tests for the AstrBot Home Assistant Conversation Agent."""

import asyncio
import json
from uuid import UUID

import pytest
from aiohttp import web
from custom_components.astrbot import conversation as astrbot_conversation
from custom_components.astrbot.api import (
    AstrBotHttpError,
    AstrBotSessionOwnerMismatchError,
)
from custom_components.astrbot.const import SESSION_STORE_KEY, SESSION_STORE_VERSION
from custom_components.astrbot.sse import AstrBotSseRemoteError
from homeassistant.components import conversation
from homeassistant.const import MATCH_ALL
from homeassistant.core import Context
from homeassistant.helpers import chat_session
from homeassistant.helpers.storage import Store
from pytest_homeassistant.common import MockConfigEntry
from pytest_socket import enable_socket

DOMAIN = "astrbot"
API_KEY = "test-secret-value"
API_KEY_ID = "key-123"
FIRST_MESSAGE = " 你好\n世界 "
SECOND_MESSAGE = "第二轮输入"


def _entry(base_url: str) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="AstrBot",
        data={
            "base_url": base_url,
            "api_key": API_KEY,
            "api_key_id": API_KEY_ID,
        },
        unique_id=DOMAIN,
    )


async def _setup_agent(hass, base_url: str):
    entry = _entry(base_url)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    agent = conversation.async_get_agent(hass, "conversation.astrbot")
    assert isinstance(agent, conversation.ConversationEntity)
    return entry, agent


async def _run_assist_conversation(hass, user_input, delta_listener, chat_logs):
    """Exercise the ChatSession/ChatLog/async_converse path used by Assist."""
    with (
        chat_session.async_get_chat_session(
            hass, user_input.conversation_id, context=user_input.context
        ) as session,
        conversation.async_get_chat_log(
            hass, session, user_input, chat_log_delta_listener=delta_listener
        ) as chat_log,
    ):
        chat_logs.append(chat_log)
        return await conversation.async_converse(
            hass=hass,
            text=user_input.text,
            conversation_id=user_input.conversation_id,
            context=user_input.context,
            language=user_input.language,
            agent_id=user_input.agent_id,
            device_id=user_input.device_id,
            satellite_id=user_input.satellite_id,
            extra_system_prompt=user_input.extra_system_prompt,
        )


async def test_config_entry_registers_and_unloads_conversation_agent(
    hass, enable_custom_integrations
):
    entry = _entry("http://astrbot.example:6185")
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    agent = conversation.async_get_agent(hass, "conversation.astrbot")
    assert isinstance(agent, conversation.ConversationEntity)
    assert agent.entity_id == "conversation.astrbot"
    assert agent.supports_streaming is True
    assert agent.supported_languages == MATCH_ALL
    assert agent._attr_supports_streaming is True

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert conversation.async_get_agent(hass, "conversation.astrbot") is None


async def test_assist_conversation_streams_chatlog_deltas_and_returns_native_result(
    hass, enable_custom_integrations, aiohttp_client
):
    enable_socket()
    first_delta_seen = asyncio.Event()
    allow_first_response_to_finish = asyncio.Event()
    request_bodies = []

    async def send_event(response, payload):
        data = json.dumps(payload, ensure_ascii=False)
        await response.write(f"data: {data}\n\n".encode())

    async def handle_chat(request):
        body = await request.json()
        request_bodies.append(body)
        response = web.StreamResponse(
            status=200, headers={"Content-Type": "text/event-stream"}
        )
        await response.prepare(request)

        await send_event(
            response,
            {
                "type": "session_id",
                "data": None,
                "session_id": body["session_id"],
            },
        )
        if len(request_bodies) == 1:
            await send_event(response, {"type": "plain", "data": "第一段"})
            await allow_first_response_to_finish.wait()
            await send_event(response, {"type": "plain", "data": "第二段"})
        else:
            await send_event(response, {"type": "plain", "data": "第二轮回答"})
        await send_event(response, {"type": "end", "data": ""})
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_post("/api/v1/chat", handle_chat)
    client = await aiohttp_client(app)
    base_url = str(client.make_url("/")).rstrip("/")
    entry, agent = await _setup_agent(hass, base_url)

    delta_events = []
    chat_logs = []

    def on_delta(chat_log, delta):
        delta_events.append(dict(delta))
        if delta.get("content") == "第一段":
            first_delta_seen.set()

    first_input = conversation.ConversationInput(
        text=FIRST_MESSAGE,
        context=Context(user_id="ha-user-id"),
        conversation_id="ha-conversation-one",
        device_id="device-1",
        satellite_id="satellite-1",
        language="zh-CN",
        agent_id="conversation.astrbot",
        extra_system_prompt="must not be forwarded",
    )
    first_task = hass.async_create_task(
        _run_assist_conversation(hass, first_input, on_delta, chat_logs)
    )

    try:
        await asyncio.wait_for(first_delta_seen.wait(), timeout=5)
        assert delta_events == [{"role": "assistant"}, {"content": "第一段"}]
        assert not first_task.done()
    finally:
        allow_first_response_to_finish.set()
        await asyncio.wait_for(
            asyncio.gather(first_task, return_exceptions=True), timeout=5
        )

    first_result = first_task.result()

    assert isinstance(first_result, conversation.ConversationResult)
    assert first_result.conversation_id == "ha-conversation-one"
    assert (
        first_result.response.as_dict()["speech"]["plain"]["speech"] == "第一段第二段"
    )
    first_messages = [
        item for item in chat_logs[0].content if item.role in {"user", "assistant"}
    ]
    assert [item.role for item in first_messages] == ["user", "assistant"]
    assert first_messages[0].content == FIRST_MESSAGE
    assert first_messages[1].content == "第一段第二段"

    persisted_session = await Store(
        hass, SESSION_STORE_VERSION, SESSION_STORE_KEY
    ).async_load()
    assert persisted_session is not None
    assert persisted_session["session_id"] == request_bodies[0]["session_id"]

    second_input = conversation.ConversationInput(
        text=SECOND_MESSAGE,
        context=Context(user_id="ha-user-id"),
        conversation_id="ha-conversation-two",
        device_id="another-device",
        satellite_id="another-satellite",
        language="en-US",
        agent_id="conversation.astrbot",
        extra_system_prompt="also must not be forwarded",
    )
    second_result = await _run_assist_conversation(
        hass, second_input, on_delta, chat_logs
    )

    assert second_result.conversation_id == "ha-conversation-two"
    assert second_result.response.as_dict()["speech"]["plain"]["speech"] == "第二轮回答"
    second_messages = [
        item for item in chat_logs[1].content if item.role in {"user", "assistant"}
    ]
    assert [item.role for item in second_messages] == ["user", "assistant"]
    assert second_messages[0].content == SECOND_MESSAGE
    assert second_messages[1].content == "第二轮回答"

    assert len(request_bodies) == 2
    for body, message in zip(
        request_bodies, (FIRST_MESSAGE, SECOND_MESSAGE), strict=True
    ):
        assert set(body) == {"username", "session_id", "message", "enable_streaming"}
        assert body["username"] == "api_key:key-123"
        assert UUID(body["session_id"]).version == 4
        assert body["message"] == message
        assert body["enable_streaming"] is True
    assert request_bodies[0]["session_id"] == request_bodies[1]["session_id"]
    assert agent.supports_streaming is True

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_two_requests_on_one_session_are_serialized(
    hass, enable_custom_integrations, aiohttp_client
):
    enable_socket()
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    release_first = asyncio.Event()
    release_second = asyncio.Event()
    request_bodies = []
    active_requests = 0
    max_active_requests = 0

    async def send_event(response, payload):
        data = json.dumps(payload, ensure_ascii=False)
        await response.write(f"data: {data}\n\n".encode())

    async def handle_chat(request):
        nonlocal active_requests, max_active_requests
        body = await request.json()
        request_bodies.append(body)
        index = len(request_bodies)
        active_requests += 1
        max_active_requests = max(max_active_requests, active_requests)
        response = web.StreamResponse(
            status=200, headers={"Content-Type": "text/event-stream"}
        )
        await response.prepare(request)
        if index == 1:
            first_started.set()
            await release_first.wait()
        else:
            second_started.set()
            await release_second.wait()
        await send_event(
            response,
            {"type": "session_id", "data": None, "session_id": body["session_id"]},
        )
        await send_event(response, {"type": "plain", "data": f"回答{index}"})
        await send_event(response, {"type": "end", "data": ""})
        await response.write_eof()
        active_requests -= 1
        return response

    app = web.Application()
    app.router.add_post("/api/v1/chat", handle_chat)
    client = await aiohttp_client(app)
    base_url = str(client.make_url("/")).rstrip("/")
    entry, _ = await _setup_agent(hass, base_url)
    chat_logs = []
    context = Context(user_id="ha-user-id")

    def make_input(text, conversation_id):
        return conversation.ConversationInput(
            text=text,
            context=context,
            conversation_id=conversation_id,
            device_id=None,
            satellite_id=None,
            language="zh-CN",
            agent_id="conversation.astrbot",
            extra_system_prompt=None,
        )

    first_task = hass.async_create_task(
        _run_assist_conversation(
            hass, make_input("第一条", "conversation-one"), None, chat_logs
        )
    )
    second_task = None
    try:
        await asyncio.wait_for(first_started.wait(), timeout=5)
        second_task = hass.async_create_task(
            _run_assist_conversation(
                hass, make_input("第二条", "conversation-two"), None, chat_logs
            )
        )
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(second_started.wait(), timeout=0.1)
        assert len(request_bodies) == 1

        release_first.set()
        await asyncio.wait_for(second_started.wait(), timeout=5)
        release_second.set()
        await asyncio.gather(first_task, second_task)
    finally:
        release_first.set()
        release_second.set()
        if not first_task.done():
            first_task.cancel()
        if second_task is not None and not second_task.done():
            second_task.cancel()
        await asyncio.gather(
            first_task,
            *([second_task] if second_task is not None else []),
            return_exceptions=True,
        )

    assert max_active_requests == 1
    assert len(request_bodies) == 2
    assert request_bodies[0]["session_id"] == request_bodies[1]["session_id"]
    assert request_bodies[0]["username"] == "api_key:key-123"
    assert request_bodies[1]["username"] == "api_key:key-123"
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("stop_status", "expect_warning"),
    [(200, False), (403, True), ("timeout", True)],
)
async def test_cancellation_closes_reader_stops_same_owned_session_and_propagates(
    hass,
    enable_custom_integrations,
    aiohttp_client,
    caplog,
    monkeypatch,
    stop_status,
    expect_warning,
):
    enable_socket()
    if stop_status == "timeout":
        monkeypatch.setattr(astrbot_conversation, "_STOP_TIMEOUT", 0.01)
    first_delta_seen = asyncio.Event()
    release_chat = asyncio.Event()
    chat_transport = []
    chat_bodies = []
    stop_calls = []

    async def send_event(response, payload):
        data = json.dumps(payload, ensure_ascii=False)
        await response.write(f"data: {data}\n\n".encode())

    async def handle_chat(request):
        body = await request.json()
        chat_bodies.append(body)
        response = web.StreamResponse(
            status=200, headers={"Content-Type": "text/event-stream"}
        )
        await response.prepare(request)
        chat_transport.append(request.transport)
        await send_event(
            response,
            {"type": "session_id", "data": None, "session_id": body["session_id"]},
        )
        if len(chat_bodies) == 1:
            await send_event(response, {"type": "plain", "data": "尚未完成"})
            await release_chat.wait()
            try:
                await send_event(response, {"type": "plain", "data": "不应出现"})
                await send_event(response, {"type": "end", "data": ""})
                await response.write_eof()
            except (ConnectionResetError, ConnectionAbortedError):
                pass
        else:
            await send_event(response, {"type": "plain", "data": "后续请求正常"})
            await send_event(response, {"type": "end", "data": ""})
            await response.write_eof()
        return response

    async def handle_stop(request):
        stop_calls.append(
            {
                "session_id": request.match_info["session_id"],
                "authorization": request.headers.get("Authorization"),
                "chat_reader_closed": chat_transport[-1].is_closing(),
            }
        )
        if stop_status == "timeout":
            await asyncio.Event().wait()
        if stop_status == 403:
            return web.json_response(
                {"status": "error", "message": f"stop rejected {API_KEY}"},
                status=403,
            )
        return web.json_response({"status": "ok", "message": None, "data": {}})

    app = web.Application()
    app.router.add_post("/api/v1/chat", handle_chat)
    app.router.add_post("/api/v1/chat/sessions/{session_id}/stop", handle_stop)
    client = await aiohttp_client(app)
    base_url = str(client.make_url("/")).rstrip("/")
    entry, _ = await _setup_agent(hass, base_url)
    chat_logs = []
    user_input = conversation.ConversationInput(
        text="请取消我",
        context=Context(user_id="ha-user-id"),
        conversation_id="cancelled-conversation",
        device_id=None,
        satellite_id=None,
        language="zh-CN",
        agent_id="conversation.astrbot",
        extra_system_prompt=None,
    )
    task = hass.async_create_task(
        _run_assist_conversation(
            hass,
            user_input,
            lambda _log, delta: (
                first_delta_seen.set() if delta.get("content") == "尚未完成" else None
            ),
            chat_logs,
        )
    )

    try:
        await asyncio.wait_for(first_delta_seen.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)
    finally:
        release_chat.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert len(chat_bodies) == 1
    assert chat_bodies[0]["username"] == "api_key:key-123"
    assert len(stop_calls) == 1
    assert stop_calls[0] == {
        "session_id": chat_bodies[0]["session_id"],
        "authorization": f"Bearer {API_KEY}",
        "chat_reader_closed": True,
    }
    assert ("AstrBot session stop failed" in caplog.text) is expect_warning
    assert API_KEY not in caplog.text

    # The entity lock is released after cancellation, even if stop failed.
    release_chat.set()
    follow_up = conversation.ConversationInput(
        text="继续",
        context=Context(user_id="ha-user-id"),
        conversation_id="follow-up-conversation",
        device_id=None,
        satellite_id=None,
        language="zh-CN",
        agent_id="conversation.astrbot",
        extra_system_prompt=None,
    )
    result = await _run_assist_conversation(hass, follow_up, None, chat_logs)
    assert result.response.as_dict()["speech"]["plain"]["speech"] == "后续请求正常"
    assert chat_bodies[1]["session_id"] == chat_bodies[0]["session_id"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_owner_mismatch_retries_once_with_a_fresh_session_id(
    hass, enable_custom_integrations, aiohttp_client
):
    enable_socket()
    request_bodies = []
    stop_calls = []

    async def send_event(response, payload):
        data = json.dumps(payload, ensure_ascii=False)
        await response.write(f"data: {data}\n\n".encode())

    async def handle_chat(request):
        body = await request.json()
        request_bodies.append(body)
        if len(request_bodies) == 1:
            return web.json_response(
                {
                    "status": "error",
                    "message": "session_id belongs to another username",
                }
            )
        response = web.StreamResponse(
            status=200, headers={"Content-Type": "text/event-stream"}
        )
        await response.prepare(request)
        await send_event(
            response,
            {"type": "session_id", "data": None, "session_id": body["session_id"]},
        )
        await send_event(response, {"type": "plain", "data": "已恢复"})
        await send_event(response, {"type": "end", "data": ""})
        await response.write_eof()
        return response

    async def handle_stop(request):
        stop_calls.append(request.match_info["session_id"])
        return web.json_response({"status": "ok", "data": {}})

    app = web.Application()
    app.router.add_post("/api/v1/chat", handle_chat)
    app.router.add_post("/api/v1/chat/sessions/{session_id}/stop", handle_stop)
    client = await aiohttp_client(app)
    base_url = str(client.make_url("/")).rstrip("/")
    entry, _ = await _setup_agent(hass, base_url)
    user_input = conversation.ConversationInput(
        text="新一轮",
        context=Context(user_id="ha-user-id"),
        conversation_id="owner-mismatch-conversation",
        device_id=None,
        satellite_id=None,
        language="zh-CN",
        agent_id="conversation.astrbot",
        extra_system_prompt=None,
    )
    result = await _run_assist_conversation(hass, user_input, None, [])

    assert result.response.as_dict()["speech"]["plain"]["speech"] == "已恢复"
    assert len(request_bodies) == 2
    old_session_id, new_session_id = (body["session_id"] for body in request_bodies)
    assert old_session_id != new_session_id
    assert UUID(old_session_id).version == 4
    assert UUID(new_session_id).version == 4
    assert all(body["username"] == "api_key:key-123" for body in request_bodies)
    assert stop_calls == []

    stored = await Store(hass, SESSION_STORE_VERSION, SESSION_STORE_KEY).async_load()
    assert stored["session_id"] == new_session_id
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_second_owner_mismatch_fails_after_one_retry_and_clears_mapping(
    hass, enable_custom_integrations, aiohttp_client
):
    enable_socket()
    request_bodies = []

    async def handle_chat(request):
        body = await request.json()
        request_bodies.append(body)
        return web.json_response(
            {
                "status": "error",
                "message": "session_id belongs to another username",
            }
        )

    app = web.Application()
    app.router.add_post("/api/v1/chat", handle_chat)
    client = await aiohttp_client(app)
    base_url = str(client.make_url("/")).rstrip("/")
    entry, agent = await _setup_agent(hass, base_url)
    user_input = conversation.ConversationInput(
        text="冲突重试边界",
        context=Context(user_id="ha-user-id"),
        conversation_id="repeated-owner-mismatch",
        device_id=None,
        satellite_id=None,
        language="zh-CN",
        agent_id="conversation.astrbot",
        extra_system_prompt=None,
    )

    with pytest.raises(AstrBotSessionOwnerMismatchError):
        await _run_assist_conversation(hass, user_input, None, [])

    assert len(request_bodies) == 2
    first_id, second_id = (body["session_id"] for body in request_bodies)
    assert first_id != second_id
    assert all(body["username"] == "api_key:key-123" for body in request_bodies)
    assert (
        await Store(hass, SESSION_STORE_VERSION, SESSION_STORE_KEY).async_load() is None
    )
    next_session_id = agent._session_manager.get_session_id()
    assert next_session_id not in {first_id, second_id}
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_generic_chat_http_failure_is_not_retried(
    hass, enable_custom_integrations, aiohttp_client
):
    enable_socket()
    request_bodies = []

    async def handle_chat(request):
        request_bodies.append(await request.json())
        return web.json_response(
            {"status": "error", "message": "temporary server error"},
            status=500,
        )

    app = web.Application()
    app.router.add_post("/api/v1/chat", handle_chat)
    client = await aiohttp_client(app)
    base_url = str(client.make_url("/")).rstrip("/")
    entry, agent = await _setup_agent(hass, base_url)
    user_input = conversation.ConversationInput(
        text="普通服务端错误",
        context=Context(user_id="ha-user-id"),
        conversation_id="generic-http-error",
        device_id=None,
        satellite_id=None,
        language="zh-CN",
        agent_id="conversation.astrbot",
        extra_system_prompt=None,
    )

    with pytest.raises(AstrBotHttpError) as error:
        await _run_assist_conversation(hass, user_input, None, [])

    assert error.value.status_code == 500
    assert len(request_bodies) == 1
    assert not agent._conversation_lock.locked()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_sse_error_event_fails_the_turn_without_a_success_result_or_stop(
    hass, enable_custom_integrations, aiohttp_client
):
    enable_socket()
    stop_calls = []

    async def send_event(response, payload):
        data = json.dumps(payload, ensure_ascii=False)
        await response.write(f"data: {data}\n\n".encode())

    async def handle_chat(request):
        body = await request.json()
        response = web.StreamResponse(
            status=200, headers={"Content-Type": "text/event-stream"}
        )
        await response.prepare(request)
        await send_event(
            response,
            {"type": "session_id", "data": None, "session_id": body["session_id"]},
        )
        await send_event(response, {"type": "plain", "data": "尚未完成"})
        await send_event(response, {"type": "error", "data": "模型内部错误"})
        await response.write_eof()
        return response

    async def handle_stop(request):
        stop_calls.append(request.match_info["session_id"])
        return web.json_response({"status": "ok", "data": {}})

    app = web.Application()
    app.router.add_post("/api/v1/chat", handle_chat)
    app.router.add_post("/api/v1/chat/sessions/{session_id}/stop", handle_stop)
    client = await aiohttp_client(app)
    base_url = str(client.make_url("/")).rstrip("/")
    entry, _ = await _setup_agent(hass, base_url)
    chat_logs = []
    user_input = conversation.ConversationInput(
        text="测试 SSE error",
        context=Context(user_id="ha-user-id"),
        conversation_id="sse-error-conversation",
        device_id=None,
        satellite_id=None,
        language="zh-CN",
        agent_id="conversation.astrbot",
        extra_system_prompt=None,
    )

    with pytest.raises(AstrBotSseRemoteError):
        await _run_assist_conversation(hass, user_input, None, chat_logs)

    assert stop_calls == []
    assert all(
        getattr(content, "content", None) != "模型内部错误"
        for content in chat_logs[0].content
    )
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_incomplete_sse_stream_is_stopped_and_never_returns_success(
    hass, enable_custom_integrations, aiohttp_client
):
    enable_socket()
    stop_calls = []
    chat_transport = []

    async def send_event(response, payload):
        data = json.dumps(payload, ensure_ascii=False)
        await response.write(f"data: {data}\n\n".encode())

    async def handle_chat(request):
        body = await request.json()
        response = web.StreamResponse(
            status=200, headers={"Content-Type": "text/event-stream"}
        )
        await response.prepare(request)
        chat_transport.append(request.transport)
        await send_event(
            response,
            {"type": "session_id", "data": None, "session_id": body["session_id"]},
        )
        await send_event(response, {"type": "plain", "data": "不完整回答"})
        await response.write_eof()
        return response

    async def handle_stop(request):
        stop_calls.append(
            {
                "session_id": request.match_info["session_id"],
                "reader_closed": chat_transport[-1].is_closing(),
                "authorization": request.headers.get("Authorization"),
            }
        )
        return web.json_response({"status": "ok", "data": {}})

    app = web.Application()
    app.router.add_post("/api/v1/chat", handle_chat)
    app.router.add_post("/api/v1/chat/sessions/{session_id}/stop", handle_stop)
    client = await aiohttp_client(app)
    base_url = str(client.make_url("/")).rstrip("/")
    entry, _ = await _setup_agent(hass, base_url)
    user_input = conversation.ConversationInput(
        text="请求中断",
        context=Context(user_id="ha-user-id"),
        conversation_id="incomplete-conversation",
        device_id=None,
        satellite_id=None,
        language="zh-CN",
        agent_id="conversation.astrbot",
        extra_system_prompt=None,
    )

    with pytest.raises(Exception, match="normal end event"):
        await _run_assist_conversation(hass, user_input, None, [])

    assert len(stop_calls) == 1
    assert stop_calls[0]["session_id"]
    assert stop_calls[0]["authorization"] == f"Bearer {API_KEY}"
    assert await hass.config_entries.async_unload(entry.entry_id)
