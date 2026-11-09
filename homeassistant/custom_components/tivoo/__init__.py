"""Tivoo Home Assistant integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .commands import UnavailableCommandAdapter
from .const import CONF_MEDIA_DIRECTORY, DEFAULT_MEDIA_DIRECTORY, DOMAIN
from .services import register_services, unregister_services


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tivoo services and the shared runtime for one config entry."""
    media_directory = entry.data.get(
        CONF_MEDIA_DIRECTORY, DEFAULT_MEDIA_DIRECTORY
    )
    runtime = {
        "command_adapter": UnavailableCommandAdapter(),
        "media_directory": hass.config.path(media_directory),
    }
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    register_services(hass, runtime)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove services and runtime state when the config entry is unloaded."""
    unregister_services(hass)
    domain_data = hass.data.get(DOMAIN)
    if domain_data is not None:
        domain_data.pop(entry.entry_id, None)
        if not domain_data:
            hass.data.pop(DOMAIN)
    return True
