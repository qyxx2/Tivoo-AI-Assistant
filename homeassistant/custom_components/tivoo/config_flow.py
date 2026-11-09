"""Config flow for the Tivoo integration."""

from pathlib import Path

import voluptuous as vol

from homeassistant import config_entries

from .const import CONF_MEDIA_DIRECTORY, DEFAULT_MEDIA_DIRECTORY, DOMAIN


class TivooConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a single Tivoo integration config entry."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure the HA-relative media directory."""
        errors: dict[str, str] = {}
        if user_input is not None:
            media_directory = user_input.get(
                CONF_MEDIA_DIRECTORY, DEFAULT_MEDIA_DIRECTORY
            ).strip()
            directory_path = Path(media_directory)
            if (
                not media_directory
                or directory_path.is_absolute()
                or ".." in directory_path.parts
            ):
                errors[CONF_MEDIA_DIRECTORY] = "invalid_path"
            else:
                return self.async_create_entry(
                    title="Tivoo",
                    data={CONF_MEDIA_DIRECTORY: media_directory},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_MEDIA_DIRECTORY, default=DEFAULT_MEDIA_DIRECTORY
                    ): str
                }
            ),
            errors=errors,
        )
