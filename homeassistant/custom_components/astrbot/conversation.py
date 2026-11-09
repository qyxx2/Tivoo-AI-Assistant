"""Home Assistant Conversation Agent bridge for AstrBot."""

from collections.abc import AsyncIterator
from typing import Literal, override

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import AstrBotApiClient
from .const import CONF_API_KEY, CONF_BASE_URL, DOMAIN
from .session import AstrBotSessionManager
from .sse import iter_astrbot_sse


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
        session_id = self._session_manager.get_session_id()

        async def async_deltas() -> AsyncIterator[dict[str, str]]:
            """Translate validated AstrBot text events into HA deltas."""
            assistant_started = False
            async with self._api_client.async_chat(
                self._session_manager.username,
                session_id,
                user_input.text,
            ) as response:
                async for event in iter_astrbot_sse(response.content, session_id):
                    if event.type == "session_id":
                        await self._session_manager.async_confirm_session(event.data)
                    elif event.type == "plain":
                        if not assistant_started:
                            yield {"role": "assistant"}
                            assistant_started = True
                        yield {"content": event.data}

        async for _ in chat_log.async_add_delta_content_stream(
            user_input.agent_id, async_deltas()
        ):
            pass

        return conversation.async_get_result_from_chat_log(user_input, chat_log)
