"""Home Assistant Conversation Agent bridge for AstrBot."""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Literal, override

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import (
    AstrBotApiClient,
    AstrBotApiError,
    AstrBotSessionOwnerMismatchError,
    AstrBotTransportError,
)
from .const import CONF_API_KEY, CONF_BASE_URL, DOMAIN
from .session import AstrBotSessionManager
from .sse import AstrBotSseProtocolError, iter_astrbot_sse

_LOGGER = logging.getLogger(__name__)
_STOP_TIMEOUT = 10


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the AstrBot Conversation Agent."""
    async_add_entities([AstrBotConversationEntity(hass, entry)])


class AstrBotConversationEntity(conversation.ConversationEntity):
    """Expose AstrBot as a streaming Home Assistant Conversation Agent."""

    _attr_name = "AstrBot"
    _attr_supports_streaming = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the agent with the entry's shared session state."""
        self._session_manager: AstrBotSessionManager = hass.data[DOMAIN][
            entry.entry_id
        ]["session_manager"]
        self._api_client = AstrBotApiClient(
            hass,
            entry.data[CONF_BASE_URL],
            entry.data[CONF_API_KEY],
        )
        self._attr_unique_id = entry.entry_id
        self._conversation_lock = asyncio.Lock()

    @property
    @override
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Delegate language understanding to AstrBot."""
        return MATCH_ALL

    @override
    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        """Send the user's text to AstrBot and stream visible text into ChatLog."""

        async def async_stop_session(session_id: str, reason: str) -> None:
            """Best-effort stop without changing the original failure/cancellation."""
            try:
                await asyncio.wait_for(
                    self._api_client.async_stop_session(session_id),
                    timeout=_STOP_TIMEOUT,
                )
            except (AstrBotApiError, TimeoutError) as err:
                _LOGGER.warning(
                    "AstrBot session stop failed after %s (%s)",
                    reason,
                    type(err).__name__,
                )

        async def async_deltas(
            stream_state: dict[str, str | bool],
        ) -> AsyncIterator[dict[str, str]]:
            """Translate the serialized AstrBot stream into HA deltas."""
            session_id = str(stream_state["session_id"])
            assistant_started = False

            for attempt in range(2):
                try:
                    async with self._api_client.async_chat(
                        self._session_manager.username,
                        session_id,
                        user_input.text,
                    ) as response:
                        stream_state["response_accepted"] = True
                        async for event in iter_astrbot_sse(
                            response.content, session_id
                        ):
                            if event.type == "session_id":
                                await self._session_manager.async_confirm_session(
                                    event.data
                                )
                            elif event.type == "plain":
                                if not assistant_started:
                                    yield {"role": "assistant"}
                                    assistant_started = True
                                yield {"content": event.data}
                            elif event.type == "end":
                                stream_state["stream_completed"] = True
                                return
                        return
                except AstrBotSessionOwnerMismatchError:
                    await self._session_manager.async_invalidate_session(session_id)
                    if attempt:
                        raise
                    session_id = self._session_manager.get_session_id()
                    stream_state["session_id"] = session_id
                    stream_state["response_accepted"] = False
                    assistant_started = False

        async with self._conversation_lock:
            stream_state: dict[str, str | bool] = {
                "session_id": self._session_manager.get_session_id(),
                "response_accepted": False,
                "stream_completed": False,
            }
            deltas = async_deltas(stream_state)
            try:
                async for _ in chat_log.async_add_delta_content_stream(
                    user_input.agent_id, deltas
                ):
                    pass
            except asyncio.CancelledError:
                # HA's ChatLog async-for does not close its input generator when
                # its consumer is cancelled; close it before requesting session stop.
                await deltas.aclose()
                if (
                    stream_state["response_accepted"]
                    and not stream_state["stream_completed"]
                ):
                    await async_stop_session(
                        str(stream_state["session_id"]), "cancellation"
                    )
                raise
            except (AstrBotSseProtocolError, AstrBotTransportError):
                await deltas.aclose()
                if (
                    stream_state["response_accepted"]
                    and not stream_state["stream_completed"]
                ):
                    await async_stop_session(
                        str(stream_state["session_id"]), "stream failure"
                    )
                raise
            finally:
                await deltas.aclose()

        return conversation.async_get_result_from_chat_log(user_input, chat_log)
