"""HA services exposed by the Tivoo integration."""

import re
from datetime import datetime
from functools import partial

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall

from .commands import TivooCommand
from .const import (
    ATTR_BACKGROUND,
    ATTR_BRIGHTNESS,
    ATTR_CALENDAR,
    ATTR_CLOCK,
    ATTR_COLOR,
    ATTR_CONDITION,
    ATTR_COUNTDOWN,
    ATTR_EFFECT,
    ATTR_FILE,
    ATTR_FONT,
    ATTR_FONT_SIZE,
    ATTR_FREQUENCY,
    ATTR_HOT,
    ATTR_INDEX,
    ATTR_MODE,
    ATTR_NAME,
    ATTR_NUMBER,
    ATTR_PLAYER1,
    ATTR_PLAYER2,
    ATTR_POWER,
    ATTR_SLOT,
    ATTR_SPEED,
    ATTR_STEP,
    ATTR_TEMP,
    ATTR_TEMPERATURE,
    ATTR_TIME,
    ATTR_TWENTYFOUR,
    ATTR_UNIT,
    ATTR_VALUE,
    ATTR_VOLUME,
    ATTR_WEATHER,
    ATTR_WEEKDAYS,
    DOMAIN,
    MOOD_PRESETS,
    SERVICE_GAME_CONTROL,
    SERVICE_PLAY_ANIMATION,
    SERVICE_SET_ALARM,
    SERVICE_SET_AUDIO_SOURCE,
    SERVICE_SET_BRIGHTNESS,
    SERVICE_SET_DATETIME,
    SERVICE_SET_EXPRESSION,
    SERVICE_SET_LIGHT,
    SERVICE_SET_MEMORIAL,
    SERVICE_SET_MOOD,
    SERVICE_SET_NOISE_METER,
    SERVICE_SET_PLAYSTATE,
    SERVICE_SET_SCREEN_POWER,
    SERVICE_SET_SLEEP_MODE,
    SERVICE_SET_TIMER,
    SERVICE_SET_VOLUME,
    SERVICE_SET_WEATHER,
    SERVICE_SHOW_CLOCK,
    SERVICE_SHOW_DESIGN,
    SERVICE_SHOW_EFFECTS,
    SERVICE_SHOW_GAME,
    SERVICE_SHOW_IMAGE,
    SERVICE_SHOW_LYRICS,
    SERVICE_SHOW_SCOREBOARD,
    SERVICE_SHOW_TEXT,
    SERVICE_SHOW_VISUALIZATION,
    SERVICE_START_COUNTDOWN,
    SERVICE_STOP_COUNTDOWN,
)
from .device_commands import AUDIO_SOURCES, GAME_CONTROLS, WEATHER_CODES
from .display_state import build_expression_command
from .media import load_media_frames
from .presets.emotion_presets import EMOTION_PRESETS
from .presets.presets import PRESETS
from .rendering import FONT_NAMES, gen_text_frames, parse_color

COUNTDOWN_PATTERN = re.compile(r"^[0-9]{2}:[0-5][0-9]$")
TIME_PATTERN = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
WEEKDAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
PLAYSTATES = ("previous", "pause", "play", "next")
PRESET_REGISTRY = {**PRESETS, **EMOTION_PRESETS}
VISIBLE_PRESETS = frozenset(PRESET_REGISTRY)

REPLAYABLE_DISPLAY_SERVICES = frozenset(
    {
        SERVICE_SET_EXPRESSION,
        SERVICE_SHOW_TEXT,
        SERVICE_SHOW_IMAGE,
        SERVICE_PLAY_ANIMATION,
        SERVICE_SHOW_CLOCK,
        SERVICE_SET_LIGHT,
        SERVICE_SHOW_LYRICS,
        SERVICE_SHOW_SCOREBOARD,
        SERVICE_SHOW_DESIGN,
        SERVICE_SHOW_EFFECTS,
        SERVICE_SHOW_VISUALIZATION,
        SERVICE_SHOW_GAME,
    }
)
SCREEN_ACTION_SERVICES = frozenset(
    {
        SERVICE_START_COUNTDOWN,
        SERVICE_STOP_COUNTDOWN,
        SERVICE_SET_TIMER,
        SERVICE_SET_NOISE_METER,
        SERVICE_SET_SLEEP_MODE,
        SERVICE_GAME_CONTROL,
    }
)


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
    except (TypeError, ValueError) as exc:
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


def _validate_time(value: object) -> str:
    if not isinstance(value, str) or not TIME_PATTERN.fullmatch(value):
        raise vol.Invalid("time must use strict HH:MM format")
    return value


def _validate_datetime(value: object) -> str:
    if not isinstance(value, str):
        raise vol.Invalid("value must be an ISO datetime string")
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise vol.Invalid("value must be an ISO datetime string") from exc
    return value


def _validate_expression(value: object) -> str:
    if not isinstance(value, str) or value not in VISIBLE_PRESETS:
        raise vol.Invalid("name must be a visible built-in Tivoo preset")
    return value


def _validate_file(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise vol.Invalid("file must be a non-empty relative path")
    return value


def _validate_frequency(value: object) -> float:
    if isinstance(value, bool):
        raise vol.Invalid("frequency must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise vol.Invalid("frequency must be a number") from exc
    if not 64 <= result <= 108:
        raise vol.Invalid("frequency must be between 64 and 108 MHz")
    return result


def _validate_temperature(value: object) -> float:
    if isinstance(value, bool):
        raise vol.Invalid("temperature must be a number")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise vol.Invalid("temperature must be a number") from exc


def _validate_memorial_text(value: object) -> str:
    if not isinstance(value, str):
        raise vol.Invalid("text must be a string")
    if len(value.encode("utf-16-be")) > 32:
        raise vol.Invalid("text must fit within 16 UTF-16 code units")
    return value


def _simple_handler(runtime: dict, service: str):
    async def handler(call: ServiceCall) -> None:
        command = TivooCommand(name=service, data=dict(call.data))
        display = runtime["display_coordinator"]
        if service == SERVICE_SET_SCREEN_POWER:
            await display.async_set_screen_power(call.data[ATTR_VALUE])
        elif service in REPLAYABLE_DISPLAY_SERVICES:
            await display.async_set_explicit(command)
        elif service in SCREEN_ACTION_SERVICES:
            await display.async_execute_screen_action(command)
        else:
            await runtime["command_adapter"].async_execute(command)

    return handler


def register_services(hass: HomeAssistant, runtime: dict) -> None:
    """Register Tivoo services for the lifetime of a loaded config entry."""

    async def async_set_mood(call: ServiceCall) -> None:
        await runtime["display_coordinator"].async_set_mood(call.data[ATTR_NAME])

    async def async_set_expression(call: ServiceCall) -> None:
        name = call.data[ATTR_NAME]
        await runtime["display_coordinator"].async_set_explicit(
            build_expression_command(name)
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
        await runtime["display_coordinator"].async_set_explicit(
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

    async def async_show_image(call: ServiceCall) -> None:
        file = call.data[ATTR_FILE]
        time = call.data.get(ATTR_TIME)
        frames, delays = await hass.async_add_executor_job(
            partial(load_media_frames, runtime["media_directory"], file, time=time)
        )
        data = {ATTR_FILE: file, "frames": frames, "delays": delays}
        if time is not None:
            data[ATTR_TIME] = time
        await runtime["display_coordinator"].async_set_explicit(
            TivooCommand(name=SERVICE_SHOW_IMAGE, data=data)
        )

    async def async_play_animation(call: ServiceCall) -> None:
        file = call.data[ATTR_FILE]
        time = call.data.get(ATTR_TIME)
        frames, delays = await hass.async_add_executor_job(
            partial(
                load_media_frames,
                runtime["media_directory"],
                file,
                time=time,
                gif_only=True,
            )
        )
        data = {ATTR_FILE: file, "frames": frames, "delays": delays}
        if time is not None:
            data[ATTR_TIME] = time
        await runtime["display_coordinator"].async_set_explicit(
            TivooCommand(name=SERVICE_PLAY_ANIMATION, data=data)
        )

    simple_schemas = {
        SERVICE_STOP_COUNTDOWN: vol.Schema({}, extra=vol.PREVENT_EXTRA),
        SERVICE_SET_VOLUME: vol.Schema(
            {
                vol.Required(ATTR_VOLUME): lambda value: _integer_between(
                    value, ATTR_VOLUME, 0, 100
                )
            },
            extra=vol.PREVENT_EXTRA,
        ),
        SERVICE_START_COUNTDOWN: vol.Schema(
            {vol.Required(ATTR_COUNTDOWN): _validate_countdown},
            extra=vol.PREVENT_EXTRA,
        ),
        SERVICE_SET_BRIGHTNESS: vol.Schema(
            {
                vol.Required(ATTR_VALUE): lambda value: _integer_between(
                    value, ATTR_VALUE, 0, 100
                )
            },
            extra=vol.PREVENT_EXTRA,
        ),
        SERVICE_SET_SCREEN_POWER: vol.Schema(
            {vol.Required(ATTR_VALUE): bool}, extra=vol.PREVENT_EXTRA
        ),
        SERVICE_SET_PLAYSTATE: vol.Schema(
            {vol.Required(ATTR_VALUE): vol.In(PLAYSTATES)}, extra=vol.PREVENT_EXTRA
        ),
        SERVICE_SHOW_CLOCK: vol.Schema(
            {
                vol.Required(ATTR_CLOCK): lambda value: _integer_between(
                    value, ATTR_CLOCK, 0, 6
                ),
                vol.Optional(ATTR_TWENTYFOUR, default=True): bool,
                vol.Optional(ATTR_WEATHER, default=False): bool,
                vol.Optional(ATTR_TEMP, default=False): bool,
                vol.Optional(ATTR_CALENDAR, default=False): bool,
                vol.Optional(ATTR_COLOR): _validate_color,
                vol.Optional(ATTR_HOT): bool,
            },
            extra=vol.PREVENT_EXTRA,
        ),
        SERVICE_SET_DATETIME: vol.Schema(
            {vol.Optional(ATTR_VALUE): _validate_datetime}, extra=vol.PREVENT_EXTRA
        ),
        SERVICE_SET_WEATHER: vol.Schema(
            {
                vol.Required(ATTR_TEMPERATURE): _validate_temperature,
                vol.Required(ATTR_CONDITION): vol.In(WEATHER_CODES),
                vol.Optional(ATTR_UNIT, default="C"): vol.In(("C", "F")),
            },
            extra=vol.PREVENT_EXTRA,
        ),
        SERVICE_SET_LIGHT: vol.Schema(
            {
                vol.Required(ATTR_BRIGHTNESS): lambda value: _integer_between(
                    value, ATTR_BRIGHTNESS, 0, 100
                ),
                vol.Optional(ATTR_COLOR): _validate_color,
                vol.Optional(ATTR_EFFECT): lambda value: _integer_between(
                    value, ATTR_EFFECT, 0, 4
                ),
                vol.Optional(ATTR_POWER, default=True): bool,
            },
            extra=vol.PREVENT_EXTRA,
        ),
        SERVICE_SHOW_LYRICS: vol.Schema({}, extra=vol.PREVENT_EXTRA),
        SERVICE_SHOW_SCOREBOARD: vol.Schema(
            {
                vol.Optional(ATTR_PLAYER1, default=0): lambda value: _integer_between(
                    value, ATTR_PLAYER1, 0, 65535
                ),
                vol.Optional(ATTR_PLAYER2, default=0): lambda value: _integer_between(
                    value, ATTR_PLAYER2, 0, 65535
                ),
            },
            extra=vol.PREVENT_EXTRA,
        ),
        SERVICE_SET_TIMER: vol.Schema(
            {vol.Required(ATTR_VALUE): bool}, extra=vol.PREVENT_EXTRA
        ),
        SERVICE_SET_NOISE_METER: vol.Schema(
            {vol.Required(ATTR_VALUE): bool}, extra=vol.PREVENT_EXTRA
        ),
        SERVICE_SET_ALARM: vol.Schema(
            {
                vol.Optional(ATTR_SLOT, default=0): lambda value: _integer_between(
                    value, ATTR_SLOT, 0, 255
                ),
                vol.Optional(ATTR_TIME): _validate_time,
                vol.Optional(ATTR_WEEKDAYS): [vol.In(WEEKDAYS)],
                vol.Optional(ATTR_FREQUENCY): _validate_frequency,
                vol.Optional(ATTR_VOLUME, default=100): lambda value: _integer_between(
                    value, ATTR_VOLUME, 0, 100
                ),
            },
            extra=vol.PREVENT_EXTRA,
        ),
        SERVICE_SET_MEMORIAL: vol.Schema(
            {
                vol.Optional(ATTR_SLOT, default=0): lambda value: _integer_between(
                    value, ATTR_SLOT, 0, 255
                ),
                vol.Optional(ATTR_VALUE): _validate_datetime,
                vol.Optional("text", default="Home Assistant"): _validate_memorial_text,
            },
            extra=vol.PREVENT_EXTRA,
        ),
        SERVICE_SET_AUDIO_SOURCE: vol.Schema(
            {
                vol.Required(ATTR_VALUE): vol.In(tuple(AUDIO_SOURCES)),
                vol.Optional(ATTR_FREQUENCY): _validate_frequency,
            },
            extra=vol.PREVENT_EXTRA,
        ),
        SERVICE_SET_SLEEP_MODE: vol.Schema(
            {
                vol.Required(ATTR_VALUE): bool,
                vol.Optional(ATTR_TIME, default=120): lambda value: _integer_between(
                    value, ATTR_TIME, 0, 255
                ),
                vol.Optional(ATTR_MODE, default=0): lambda value: _integer_between(
                    value, ATTR_MODE, 0, 255
                ),
                vol.Optional(ATTR_FREQUENCY): _validate_frequency,
                vol.Optional(ATTR_VOLUME, default=100): lambda value: _integer_between(
                    value, ATTR_VOLUME, 0, 100
                ),
                vol.Optional(ATTR_COLOR, default="black"): _validate_color,
                vol.Optional(ATTR_BRIGHTNESS, default=100): lambda value: (
                    _integer_between(value, ATTR_BRIGHTNESS, 0, 100)
                ),
            },
            extra=vol.PREVENT_EXTRA,
        ),
        SERVICE_SHOW_DESIGN: vol.Schema(
            {
                vol.Required(ATTR_NUMBER): lambda value: _integer_between(
                    value, ATTR_NUMBER, 0, 3
                )
            },
            extra=vol.PREVENT_EXTRA,
        ),
        SERVICE_SHOW_EFFECTS: vol.Schema(
            {
                vol.Required(ATTR_NUMBER): lambda value: _integer_between(
                    value, ATTR_NUMBER, 0, 255
                )
            },
            extra=vol.PREVENT_EXTRA,
        ),
        SERVICE_SHOW_VISUALIZATION: vol.Schema(
            {
                vol.Required(ATTR_NUMBER): lambda value: _integer_between(
                    value, ATTR_NUMBER, 0, 255
                )
            },
            extra=vol.PREVENT_EXTRA,
        ),
        SERVICE_SHOW_GAME: vol.Schema(
            {
                vol.Optional(ATTR_INDEX): lambda value: _integer_between(
                    value, ATTR_INDEX, 0, 127
                )
            },
            extra=vol.PREVENT_EXTRA,
        ),
        SERVICE_GAME_CONTROL: vol.Schema(
            {vol.Required(ATTR_VALUE): vol.In(tuple(GAME_CONTROLS))},
            extra=vol.PREVENT_EXTRA,
        ),
    }

    for service, schema in simple_schemas.items():
        hass.services.async_register(
            DOMAIN,
            service,
            _simple_handler(runtime, service),
            schema=schema,
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MOOD,
        async_set_mood,
        schema=vol.Schema(
            {vol.Required(ATTR_NAME): vol.In(MOOD_PRESETS)},
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
    for service, handler in (
        (SERVICE_SHOW_IMAGE, async_show_image),
        (SERVICE_PLAY_ANIMATION, async_play_animation),
    ):
        hass.services.async_register(
            DOMAIN,
            service,
            handler,
            schema=vol.Schema(
                {
                    vol.Required(ATTR_FILE): _validate_file,
                    vol.Optional(ATTR_TIME): lambda value: _integer_between(
                        value, ATTR_TIME, 0, 65535
                    ),
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
        SERVICE_SET_MOOD,
        SERVICE_SHOW_TEXT,
        SERVICE_START_COUNTDOWN,
        SERVICE_SET_BRIGHTNESS,
        SERVICE_SHOW_IMAGE,
        SERVICE_PLAY_ANIMATION,
        SERVICE_SET_SCREEN_POWER,
        SERVICE_SET_PLAYSTATE,
        SERVICE_SHOW_CLOCK,
        SERVICE_SET_DATETIME,
        SERVICE_SET_WEATHER,
        SERVICE_SET_LIGHT,
        SERVICE_SHOW_LYRICS,
        SERVICE_SHOW_SCOREBOARD,
        SERVICE_SET_TIMER,
        SERVICE_SET_NOISE_METER,
        SERVICE_SET_ALARM,
        SERVICE_SET_MEMORIAL,
        SERVICE_SET_AUDIO_SOURCE,
        SERVICE_SET_SLEEP_MODE,
        SERVICE_SHOW_DESIGN,
        SERVICE_SHOW_EFFECTS,
        SERVICE_SHOW_VISUALIZATION,
        SERVICE_SHOW_GAME,
        SERVICE_GAME_CONTROL,
    ):
        hass.services.async_remove(DOMAIN, service)
