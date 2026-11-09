"""HA services exposed by the Tivoo integration."""

import re

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall

from .commands import TivooCommand
from .const import (
    ATTR_BACKGROUND,
    ATTR_COLOR,
    ATTR_COUNTDOWN,
    ATTR_FONT,
    ATTR_FONT_SIZE,
    ATTR_NAME,
    ATTR_SPEED,
    ATTR_STEP,
    ATTR_VALUE,
    ATTR_VOLUME,
    DOMAIN,
    SERVICE_SET_BRIGHTNESS,
    SERVICE_SET_EXPRESSION,
    SERVICE_SET_VOLUME,
    SERVICE_SHOW_TEXT,
    SERVICE_START_COUNTDOWN,
    SERVICE_STOP_COUNTDOWN,
)
from .presets.emotion_presets import EMOTION_PRESETS
from .presets.presets import PRESETS
from .rendering import FONT_NAMES, gen_text_frames, parse_color

COUNTDOWN_PATTERN = re.compile(r"^[0-9]{2}:[0-5][0-9]$")
PRESET_REGISTRY = {**PRESETS, **EMOTION_PRESETS}
VISIBLE_PRESETS = frozenset(PRESET_REGISTRY)


def _integer_between(value: object, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int:
        raise vol.Invalid(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise vol.Invalid(f"{name} must be between {minimum} and {maximum}")
    return value


def _positive_speed(value: object) -> int:
    return _integer_between(value, ATTR_SPEED, 1, 65535)


def _validate_color(value: object) -> str:
    if not isinstance(value, str):
        raise vol.Invalid("color must be a string")
    try:
        parse_color(value)
    except ValueError as exc:
        raise vol.Invalid(str(exc)) from exc
    return value


def _validate_font(value: object) -> str:
    if not isinstance(value, str) or value not in FONT_NAMES:
        raise vol.Invalid(f"font must be one of: {', '.join(FONT_NAMES)}")
    return value


def _validate_countdown(value: object) -> str:
    if not isinstance(value, str) or not COUNTDOWN_PATTERN.fullmatch(value):
        raise vol.Invalid("countdown must use strict MM:SS format (00:00–99:59)")
    return value


def _validate_expression(value: object) -> str:
    if not isinstance(value, str) or value not in VISIBLE_PRESETS:
        raise vol.Invalid("name must be a visible built-in Tivoo preset")
    return value


def register_services(hass: HomeAssistant, runtime: dict) -> None:
    """Register Tivoo services for the lifetime of a loaded config entry."""

    async def async_stop_countdown(call: ServiceCall) -> None:
        await runtime["command_adapter"].async_execute(
            TivooCommand(name=SERVICE_STOP_COUNTDOWN, data={})
        )

    async def async_set_volume(call: ServiceCall) -> None:
        volume = call.data[ATTR_VOLUME]
        await runtime["command_adapter"].async_execute(
            TivooCommand(name=SERVICE_SET_VOLUME, data={ATTR_VOLUME: volume})
        )

    async def async_set_expression(call: ServiceCall) -> None:
        name = call.data[ATTR_NAME]
        description, factory = PRESET_REGISTRY[name]
        frames, delays = factory()
        await runtime["command_adapter"].async_execute(
            TivooCommand(
                name=SERVICE_SET_EXPRESSION,
                data={
                    ATTR_NAME: name,
                    "description": description,
                    "frames": frames,
                    "delays": delays,
                },
            )
        )

    async def async_show_text(call: ServiceCall) -> None:
        value = call.data[ATTR_VALUE]
        options = {
            ATTR_COLOR: call.data.get(ATTR_COLOR, "white"),
            ATTR_BACKGROUND: call.data.get(ATTR_BACKGROUND, "black"),
            ATTR_SPEED: call.data.get(ATTR_SPEED, 100),
            ATTR_STEP: call.data.get(ATTR_STEP, 2),
            ATTR_FONT_SIZE: call.data.get(ATTR_FONT_SIZE),
            ATTR_FONT: call.data.get(ATTR_FONT, "unifont"),
        }
        frames, delays = gen_text_frames(
            value,
            color=options[ATTR_COLOR],
            background=options[ATTR_BACKGROUND],
            speed=options[ATTR_SPEED],
            step=options[ATTR_STEP],
            font_size=options[ATTR_FONT_SIZE],
            font=options[ATTR_FONT],
        )
        await runtime["command_adapter"].async_execute(
            TivooCommand(
                name=SERVICE_SHOW_TEXT,
                data={
                    ATTR_VALUE: value,
                    **options,
                    "frames": frames,
                    "delays": delays,
                },
            )
        )

    async def async_start_countdown(call: ServiceCall) -> None:
        countdown = call.data[ATTR_COUNTDOWN]
        await runtime["command_adapter"].async_execute(
            TivooCommand(
                name=SERVICE_START_COUNTDOWN,
                data={ATTR_COUNTDOWN: countdown},
            )
        )

    async def async_set_brightness(call: ServiceCall) -> None:
        value = call.data[ATTR_VALUE]
        await runtime["command_adapter"].async_execute(
            TivooCommand(
                name=SERVICE_SET_BRIGHTNESS,
                data={ATTR_VALUE: value},
            )
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_COUNTDOWN,
        async_stop_countdown,
        schema=vol.Schema({}, extra=vol.PREVENT_EXTRA),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_VOLUME,
        async_set_volume,
        schema=vol.Schema(
            {
                vol.Required(ATTR_VOLUME): lambda value: _integer_between(
                    value, ATTR_VOLUME, 0, 100
                )
            },
            extra=vol.PREVENT_EXTRA,
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_EXPRESSION,
        async_set_expression,
        schema=vol.Schema(
            {vol.Required(ATTR_NAME): _validate_expression},
            extra=vol.PREVENT_EXTRA,
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SHOW_TEXT,
        async_show_text,
        schema=vol.Schema(
            {
                vol.Required(ATTR_VALUE): vol.All(str, vol.Length(min=1)),
                vol.Optional(ATTR_COLOR, default="white"): _validate_color,
                vol.Optional(ATTR_BACKGROUND, default="black"): _validate_color,
                vol.Optional(ATTR_SPEED, default=100): _positive_speed,
                vol.Optional(ATTR_STEP, default=2): lambda value: _integer_between(
                    value, ATTR_STEP, 1, 8
                ),
                vol.Optional(ATTR_FONT_SIZE): lambda value: _integer_between(
                    value, ATTR_FONT_SIZE, 8, 16
                ),
                vol.Optional(ATTR_FONT, default="unifont"): _validate_font,
            },
            extra=vol.PREVENT_EXTRA,
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_COUNTDOWN,
        async_start_countdown,
        schema=vol.Schema(
            {vol.Required(ATTR_COUNTDOWN): _validate_countdown},
            extra=vol.PREVENT_EXTRA,
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_BRIGHTNESS,
        async_set_brightness,
        schema=vol.Schema(
            {
                vol.Required(ATTR_VALUE): lambda value: _integer_between(
                    value, ATTR_VALUE, 0, 100
                )
            },
            extra=vol.PREVENT_EXTRA,
        ),
    )


def unregister_services(hass: HomeAssistant) -> None:
    """Remove services when the only config entry is unloaded."""
    for service in (
        SERVICE_STOP_COUNTDOWN,
        SERVICE_SET_VOLUME,
        SERVICE_SET_EXPRESSION,
        SERVICE_SHOW_TEXT,
        SERVICE_START_COUNTDOWN,
        SERVICE_SET_BRIGHTNESS,
    ):
        hass.services.async_remove(DOMAIN, service)
