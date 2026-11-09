"""HA services exposed by the Tivoo integration."""

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall

from .commands import TivooCommand
from .const import (
    ATTR_VOLUME,
    DOMAIN,
    SERVICE_SET_VOLUME,
    SERVICE_STOP_COUNTDOWN,
)


def _validate_volume(value: object) -> int:
    """Accept only integer speaker volume values from 0 through 100."""
    if type(value) is not int:
        raise vol.Invalid("volume must be an integer")
    if not 0 <= value <= 100:
        raise vol.Invalid("volume must be between 0 and 100")
    return value


def register_services(hass: HomeAssistant, runtime: dict) -> None:
    """Register Tivoo services for the lifetime of a loaded config entry."""

    async def async_stop_countdown(call: ServiceCall) -> None:
        """Stop the current countdown without requiring its previous duration."""
        await runtime["command_adapter"].async_execute(
            TivooCommand(name=SERVICE_STOP_COUNTDOWN, data={})
        )

    async def async_set_volume(call: ServiceCall) -> None:
        """Set the speaker volume without treating zero as a default."""
        volume = call.data[ATTR_VOLUME]
        await runtime["command_adapter"].async_execute(
            TivooCommand(name=SERVICE_SET_VOLUME, data={ATTR_VOLUME: volume})
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_COUNTDOWN,
        async_stop_countdown,
        schema=vol.Schema({}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_VOLUME,
        async_set_volume,
        schema=vol.Schema({vol.Required(ATTR_VOLUME): _validate_volume}),
    )


def unregister_services(hass: HomeAssistant) -> None:
    """Remove Tivoo services when its only config entry is unloaded."""
    hass.services.async_remove(DOMAIN, SERVICE_STOP_COUNTDOWN)
    hass.services.async_remove(DOMAIN, SERVICE_SET_VOLUME)
