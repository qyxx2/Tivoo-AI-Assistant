"""Config flow for the Tivoo integration."""

import re
from ipaddress import AddressValueError, IPv4Address
from pathlib import Path

import voluptuous as vol

from homeassistant import config_entries

from .const import (
    CONF_ESP32_HOST,
    CONF_MEDIA_DIRECTORY,
    CONF_TIVOO_BLUETOOTH_MAC,
    DEFAULT_MEDIA_DIRECTORY,
    DEFAULT_TIVOO_BLUETOOTH_MAC,
    DOMAIN,
)

_MAC_PATTERN = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def _valid_ipv4(value: str) -> bool:
    """Return whether value is a valid IPv4 literal."""
    try:
        IPv4Address(value)
    except AddressValueError:
        return False
    return True


def _valid_mac(value: str) -> bool:
    """Return whether value is a six-octet Bluetooth MAC address."""
    return bool(_MAC_PATTERN.fullmatch(value))


def _valid_media_directory(value: str) -> bool:
    """Keep media paths relative to the Home Assistant config directory."""
    path = Path(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


class TivooConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a single Tivoo integration config entry."""

    VERSION = 2

    @staticmethod
    def _schema() -> vol.Schema:
        return vol.Schema(
            {
                vol.Optional(
                    CONF_MEDIA_DIRECTORY, default=DEFAULT_MEDIA_DIRECTORY
                ): str,
                vol.Required(CONF_ESP32_HOST, default=""): str,
                vol.Optional(
                    CONF_TIVOO_BLUETOOTH_MAC,
                    default=DEFAULT_TIVOO_BLUETOOTH_MAC,
                ): str,
            }
        )

    def _validated_data(
        self, user_input: dict[str, str]
    ) -> tuple[dict[str, str] | None, dict[str, str]]:
        """Validate the entry fields shared by initial setup and reconfigure."""
        media_directory = user_input.get(
            CONF_MEDIA_DIRECTORY, DEFAULT_MEDIA_DIRECTORY
        ).strip()
        esp32_host = user_input.get(CONF_ESP32_HOST, "").strip()
        bluetooth_mac = user_input.get(
            CONF_TIVOO_BLUETOOTH_MAC, DEFAULT_TIVOO_BLUETOOTH_MAC
        ).strip()

        errors: dict[str, str] = {}
        if not _valid_ipv4(esp32_host):
            errors[CONF_ESP32_HOST] = "invalid_ipv4"
        if not _valid_mac(bluetooth_mac):
            errors[CONF_TIVOO_BLUETOOTH_MAC] = "invalid_mac"
        if not _valid_media_directory(media_directory):
            errors[CONF_MEDIA_DIRECTORY] = "invalid_path"

        if errors:
            return None, errors

        return (
            {
                CONF_MEDIA_DIRECTORY: media_directory,
                CONF_ESP32_HOST: str(IPv4Address(esp32_host)),
                CONF_TIVOO_BLUETOOTH_MAC: bluetooth_mac.upper(),
            },
            {},
        )

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure the media directory and ESP32 connection address."""
        if user_input is not None:
            data, errors = self._validated_data(user_input)
            if data is not None:
                return self.async_create_entry(title="Tivoo", data=data)
        else:
            errors = {}

        return self.async_show_form(
            step_id="user",
            data_schema=self._schema(),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, str] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Require an explicit ESP32 address for legacy or changed networks."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            data, errors = self._validated_data(user_input)
            if data is not None:
                return self.async_update_reload_and_abort(
                    entry,
                    title="Tivoo",
                    data=data,
                )
        else:
            errors = {}

        suggested = {
            CONF_MEDIA_DIRECTORY: entry.data.get(
                CONF_MEDIA_DIRECTORY, DEFAULT_MEDIA_DIRECTORY
            ),
            CONF_ESP32_HOST: entry.data.get(CONF_ESP32_HOST, ""),
            CONF_TIVOO_BLUETOOTH_MAC: entry.data.get(
                CONF_TIVOO_BLUETOOTH_MAC, DEFAULT_TIVOO_BLUETOOTH_MAC
            ),
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(self._schema(), suggested),
            errors=errors,
        )
