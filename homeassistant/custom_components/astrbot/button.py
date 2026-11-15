"""Button entity for starting a fresh AstrBot conversation."""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .session import AstrBotSessionManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the AstrBot new-conversation button."""
    manager: AstrBotSessionManager = hass.data[DOMAIN][entry.entry_id][
        "session_manager"
    ]
    async_add_entities([AstrBotNewConversationButton(manager, entry.entry_id)])


class AstrBotNewConversationButton(ButtonEntity):
    """Start a fresh AstrBot context on the next user turn."""

    _attr_name = "AstrBot new conversation"
    _attr_icon = "mdi:message-plus-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, manager: AstrBotSessionManager, entry_id: str) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry_id}_new_conversation"

    async def async_press(self) -> None:
        """Discard the active AstrBot context."""
        await self._manager.async_start_new_conversation()
