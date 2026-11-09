"""Tests for the AstrBot HTTP OpenAPI client."""

import aiohttp
import pytest
from custom_components.astrbot import api as api_module
from custom_components.astrbot.api import (
    AstrBotApiError,
    AstrBotAuthenticationError,
    AstrBotAuthorizationError,
    AstrBotHttpError,
    AstrBotResponseError,
    AstrBotTransportError,
)

BASE_URL = "http://astrbot.example:6185"
API_KEY = "test-secret-value"
USERNAME = "api_key:key-123"
SESSION_ID = "8ea2a84e-3e71-4ca3-8d53-a4b5fdf0e671"
MESSAGE = "  你好，保留原始空格。  "


class FakeResponse:
    def __init__(self, status=200, content_type="text/event-stream", payload=None):
        self.status = status
        self.content_type = content_type
        self.payload = payload
        self.exited = False

    async def json(self, content_type=None):
        return self.payload


class FakeRequestContext:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    async def __aenter__(self):
        if self.error:
            raise self.error
        return self.response

    async def __aexit__(self, exc_type, exc, traceback):
        self.response.exited = True


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response or FakeResponse()
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return FakeRequestContext(self.response, self.error)


@pytest.fixture
def client_setup(hass, monkeypatch):
    response = FakeResponse()
    session = FakeSession(response)
    shared_sessions = []

    def get_shared_session(current_hass):
        shared_sessions.append(current_hass)
        return session

    monkeypatch.setattr(api_module, "async_get_clientsession", get_shared_session)
    client = api_module.AstrBotApiClient(hass, BASE_URL, API_KEY)
    return client, session, response, shared_sessions


async def test_chat_uses_fixed_route_headers_and_exact_request_body(client_setup):
    client, session, response, _ = client_setup

    async with client.async_chat(USERNAME, SESSION_ID, MESSAGE) as stream:
        assert stream is response
        assert response.exited is False

    assert response.exited is True
    assert session.calls == [
        {
            "url": f"{BASE_URL}/api/v1/chat",
            "headers": {
                "Authorization": f"Bearer {API_KEY}",
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
            },
            "json": {
                "username": USERNAME,
                "session_id": SESSION_ID,
                "message": MESSAGE,
                "enable_streaming": True,
            },
        }
    ]


async def test_chat_reuses_the_home_assistant_shared_session(hass, client_setup):
    client, session, _, shared_sessions = client_setup

    async with client.async_chat(USERNAME, SESSION_ID, MESSAGE):
        pass
    await client.async_stop_session(SESSION_ID)

    assert shared_sessions == [hass]
    assert len(session.calls) == 2
    assert session.calls[0]["url"].endswith("/api/v1/chat")
    assert session.calls[1]["url"].endswith(f"/api/v1/chat/sessions/{SESSION_ID}/stop")
    assert session.calls[1]["headers"] == {"Authorization": f"Bearer {API_KEY}"}
    assert "json" not in session.calls[1]


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, AstrBotAuthenticationError),
        (403, AstrBotAuthorizationError),
        (500, AstrBotHttpError),
    ],
)
async def test_chat_maps_http_status_errors_to_distinct_failures(
    hass, monkeypatch, status, error_type
):
    session = FakeSession(FakeResponse(status=status, content_type="application/json"))
    monkeypatch.setattr(api_module, "async_get_clientsession", lambda _: session)
    client = api_module.AstrBotApiClient(hass, BASE_URL, API_KEY)

    with pytest.raises(error_type):
        async with client.async_chat(USERNAME, SESSION_ID, MESSAGE):
            pytest.fail("non-success HTTP response must not reach the SSE consumer")

    assert len(session.calls) == 1


async def test_http_200_json_error_envelope_is_rejected(hass, monkeypatch):
    session = FakeSession(
        FakeResponse(
            content_type="application/json",
            payload={"status": "error", "message": "模型服务暂不可用"},
        )
    )
    monkeypatch.setattr(api_module, "async_get_clientsession", lambda _: session)
    client = api_module.AstrBotApiClient(hass, BASE_URL, API_KEY)

    with pytest.raises(AstrBotApiError, match="模型服务暂不可用"):
        async with client.async_chat(USERNAME, SESSION_ID, MESSAGE):
            pytest.fail("JSON error envelope must not reach the SSE consumer")

    assert len(session.calls) == 1


async def test_non_sse_success_response_is_rejected(hass, monkeypatch):
    session = FakeSession(
        FakeResponse(
            content_type="application/json",
            payload={"status": "ok", "data": "not an SSE stream"},
        )
    )
    monkeypatch.setattr(api_module, "async_get_clientsession", lambda _: session)
    client = api_module.AstrBotApiClient(hass, BASE_URL, API_KEY)

    with pytest.raises(AstrBotResponseError):
        async with client.async_chat(USERNAME, SESSION_ID, MESSAGE):
            pytest.fail("unexpected content type must not reach the SSE consumer")


async def test_transport_failure_is_not_retried_or_leaked(hass, monkeypatch):
    session = FakeSession(error=aiohttp.ClientConnectionError(f"failed: {API_KEY}"))
    monkeypatch.setattr(api_module, "async_get_clientsession", lambda _: session)
    client = api_module.AstrBotApiClient(hass, BASE_URL, API_KEY)

    with pytest.raises(AstrBotTransportError) as error:
        async with client.async_chat(USERNAME, SESSION_ID, MESSAGE):
            pytest.fail("transport failure must not reach the SSE consumer")

    assert len(session.calls) == 1
    assert API_KEY not in session.calls[0]["url"]
    assert "?" not in session.calls[0]["url"]
    assert API_KEY not in str(error.value)


async def test_json_error_message_is_redacted_before_exposing_it(hass, monkeypatch):
    session = FakeSession(
        FakeResponse(
            content_type="application/json",
            payload={"status": "error", "message": f"bad credential {API_KEY}"},
        )
    )
    monkeypatch.setattr(api_module, "async_get_clientsession", lambda _: session)
    client = api_module.AstrBotApiClient(hass, BASE_URL, API_KEY)

    with pytest.raises(AstrBotApiError) as error:
        async with client.async_chat(USERNAME, SESSION_ID, MESSAGE):
            pytest.fail("JSON error envelope must be rejected")

    assert API_KEY not in str(error.value)
    assert "[redacted]" in str(error.value)


async def test_stop_http_error_is_reported_without_a_retry(hass, monkeypatch):
    session = FakeSession(
        FakeResponse(
            status=403,
            content_type="application/json",
            payload={"status": "error", "message": "scope denied"},
        )
    )
    monkeypatch.setattr(api_module, "async_get_clientsession", lambda _: session)
    client = api_module.AstrBotApiClient(hass, BASE_URL, API_KEY)

    with pytest.raises(AstrBotAuthorizationError):
        await client.async_stop_session(SESSION_ID)

    assert len(session.calls) == 1
    assert session.calls[0]["url"] == (
        f"{BASE_URL}/api/v1/chat/sessions/{SESSION_ID}/stop"
    )
