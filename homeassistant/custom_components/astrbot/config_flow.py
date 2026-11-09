"""Config flow for the AstrBot Conversation Agent integration."""

from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant.helpers import selector

from homeassistant import config_entries

from .const import CONF_API_KEY, CONF_API_KEY_ID, CONF_BASE_URL, DOMAIN


def _normalize_base_url(value: str) -> str | None:
    """Validate and normalize the AstrBot server base URL."""
    value = value.strip()
    if not value or any(char.isspace() for char in value):
        return None

    try:
        parsed = urlsplit(value)
        _ = parsed.port  # Validate the port when one is present.
    except ValueError:
        return None

    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or "?" in value
        or "#" in value
        or parsed.path.rstrip("/").endswith("/api/v1/chat")
    ):
        return None

    return value.rstrip("/")


class AstrBotConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AstrBot."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the user setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = _normalize_base_url(user_input[CONF_BASE_URL])
            api_key = user_input[CONF_API_KEY].strip()
            api_key_id = user_input[CONF_API_KEY_ID].strip()

            if base_url is None:
                errors[CONF_BASE_URL] = "invalid_url"
            if not api_key:
                errors[CONF_API_KEY] = "required"
            if not api_key_id:
                errors[CONF_API_KEY_ID] = "required"

            if not errors:
                return self.async_create_entry(
                    title="AstrBot",
                    data={
                        CONF_BASE_URL: base_url,
                        CONF_API_KEY: api_key,
                        CONF_API_KEY_ID: api_key_id,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BASE_URL): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                    ),
                    vol.Required(CONF_API_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                    vol.Required(CONF_API_KEY_ID): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    ),
                }
            ),
            errors=errors,
        )
