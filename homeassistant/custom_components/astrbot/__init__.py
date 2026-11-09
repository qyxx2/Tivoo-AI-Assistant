"""AstrBot Conversation Agent integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    CONF_API_KEY_ID,
    CONF_BASE_URL,
    DOMAIN,
    SESSION_STORE_KEY,
    SESSION_STORE_VERSION,
)
from .session import AstrBotSessionManager


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
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the session manager without deleting its persisted session."""
    domain_data = hass.data.get(DOMAIN)
    if domain_data is not None:
        domain_data.pop(entry.entry_id, None)
        if not domain_data:
            hass.data.pop(DOMAIN)
    return True
