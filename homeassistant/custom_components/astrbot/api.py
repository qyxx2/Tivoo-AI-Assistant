"""AstrBot HTTP OpenAPI client."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession


class AstrBotApiError(Exception):
    """Base error for AstrBot HTTP API failures."""


class AstrBotAuthenticationError(AstrBotApiError):
    """The configured API Key was not accepted."""


class AstrBotAuthorizationError(AstrBotApiError):
    """The API Key does not have the required scope."""


class AstrBotHttpError(AstrBotApiError):
    """AstrBot returned an unsuccessful HTTP status."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(message)


class AstrBotResponseError(AstrBotApiError):
    """AstrBot returned an unexpected successful response."""


class AstrBotTransportError(AstrBotApiError):
    """The HTTP request could not be completed."""


class AstrBotApiClient:
    """Call AstrBot OpenAPI using Home Assistant's shared HTTP session."""

    def __init__(self, hass: HomeAssistant, base_url: str, api_key: str) -> None:
        """Initialize the client without creating a dedicated HTTP session."""
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._session = async_get_clientsession(hass)

    @property
    def _auth_headers(self) -> dict[str, str]:
        """Return the API Key authentication header."""
        return {"Authorization": f"Bearer {self._api_key}"}

    @property
    def _chat_headers(self) -> dict[str, str]:
        """Return the fixed streaming Chat request headers."""
        return {
            **self._auth_headers,
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        }

    @asynccontextmanager
    async def async_chat(
        self, username: str, session_id: str, message: str
    ) -> AsyncIterator[aiohttp.ClientResponse]:
        """Open a validated streaming Chat response for incremental reading."""
        url = f"{self._base_url}/api/v1/chat"
        body = {
            "username": username,
            "session_id": session_id,
            "message": message,
            "enable_streaming": True,
        }
        try:
            async with self._session.post(
                url, headers=self._chat_headers, json=body
            ) as response:
                await self._raise_for_http_error(response)
                if response.content_type.lower() != "text/event-stream":
                    raise AstrBotResponseError(
                        "AstrBot returned a successful response that is not text/event-stream"
                    )
                yield response
        except (TimeoutError, aiohttp.ClientError):
            raise AstrBotTransportError("AstrBot HTTP request failed") from None

    async def async_stop_session(self, session_id: str) -> None:
        """Request AstrBot to stop the specified WebChat session."""
        url = f"{self._base_url}/api/v1/chat/sessions/{session_id}/stop"
        try:
            async with self._session.post(url, headers=self._auth_headers) as response:
                await self._raise_for_http_error(response)
        except (TimeoutError, aiohttp.ClientError):
            raise AstrBotTransportError("AstrBot session stop request failed") from None

    async def _raise_for_http_error(self, response: aiohttp.ClientResponse) -> None:
        """Raise a typed error for HTTP failures and JSON error envelopes."""
        error_message = await self._json_error_message(response)

        if response.status == 401:
            raise AstrBotAuthenticationError(
                "AstrBot authentication failed (HTTP 401); check the API Key"
            )
        if response.status == 403:
            raise AstrBotAuthorizationError(
                "AstrBot authorization failed (HTTP 403); check the chat scope"
            )
        if not 200 <= response.status < 300:
            message = error_message or f"AstrBot returned HTTP {response.status}"
            raise AstrBotHttpError(response.status, message)
        if error_message is not None:
            raise AstrBotApiError(error_message)

    async def _json_error_message(self, response: aiohttp.ClientResponse) -> str | None:
        """Read only a JSON error envelope and redact any echoed API Key."""
        content_type = response.content_type.lower()
        if content_type != "application/json" and not content_type.endswith("+json"):
            return None

        try:
            payload = await response.json(content_type=None)
        except (TypeError, ValueError):
            return None

        if (
            isinstance(payload, dict)
            and payload.get("status") == "error"
            and isinstance(payload.get("message"), str)
            and payload["message"]
        ):
            return payload["message"].replace(self._api_key, "[redacted]")

        return None
