"""AstrBot Conversation Agent integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.storage import Store

from .const import (
    CONF_API_KEY_ID,
    CONF_BASE_URL,
    DOMAIN,
    SERVICE_NEW_CONVERSATION,
    SESSION_STORE_KEY,
    SESSION_STORE_VERSION,
)
from .session import AstrBotSessionManager

PLATFORMS = [Platform.CONVERSATION, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up an AstrBot config entry and restore its active session."""
    store = Store(hass, SESSION_STORE_VERSION, SESSION_STORE_KEY)
    session_manager = AstrBotSessionManager(
        store,
        entry.data[CONF_BASE_URL],
        entry.data[CONF_API_KEY_ID],
    )
    await session_manager.async_load()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "session_manager": session_manager
    }

    async def async_handle_new_conversation(_call: ServiceCall) -> None:
        """Discard the current AstrBot context for the next user turn."""
        await session_manager.async_start_new_conversation()

    hass.services.async_register(
        DOMAIN,
        SERVICE_NEW_CONVERSATION,
        async_handle_new_conversation,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload AstrBot platforms and remove its service."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    hass.services.async_remove(DOMAIN, SERVICE_NEW_CONVERSATION)

    domain_data = hass.data.get(DOMAIN)
    if domain_data is not None:
        domain_data.pop(entry.entry_id, None)
        if not domain_data:
            hass.data.pop(DOMAIN)
    return True
