"""Small semantic command interface for Tivoo services."""

from dataclasses import dataclass

from homeassistant.exceptions import HomeAssistantError


@dataclass(frozen=True, slots=True)
class TivooCommand:
    """A validated high-level Tivoo action, independent of device transport."""

    name: str
    data: dict[str, object]


class UnavailableCommandAdapter:
    """Default adapter until the device transport is implemented in P6."""

    async def async_execute(self, command: TivooCommand) -> None:
        """Fail explicitly when no production device adapter is configured."""
        raise HomeAssistantError(
            "Tivoo command adapter is unavailable until device transport is configured"
        )
