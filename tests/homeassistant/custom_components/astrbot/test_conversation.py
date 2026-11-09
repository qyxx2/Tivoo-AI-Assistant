"""Tests for the AstrBot Home Assistant Conversation Agent."""

import asyncio
import json
from uuid import UUID

from aiohttp import web
from custom_components.astrbot.const import SESSION_STORE_KEY, SESSION_STORE_VERSION
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
