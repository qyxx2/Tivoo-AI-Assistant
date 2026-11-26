"""LLM tools exposed by the Tivoo integration."""

import probatio
from homeassistant.components.llm import LLMTools
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.llm import (
    LLM_API_ASSIST,
    LLMContext,
    Tool,
    ToolAnnotations,
    ToolInput,
    ToolResult,
)

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
from .rendering import FONT_NAMES
from .services import COUNTDOWN_PATTERN, PLAYSTATES, VISIBLE_PRESETS, WEEKDAYS


def _annotations(*, idempotent: bool) -> ToolAnnotations:
    return ToolAnnotations(
        read_only=False,
        destructive=False,
        idempotent=idempotent,
        open_world=False,
    )


def _strict_integer(value: object) -> int:
    if type(value) is not int:
        raise probatio.Invalid("value must be an integer")
    return value


def _integer_range(minimum: int, maximum: int):
    return probatio.All(
        _strict_integer,
        probatio.Range(min=minimum, max=maximum),
    )


DEVICE_ALIAS_DESCRIPTION = "Tivoo and 瓦力 refer to the same Tivoo device."


class _ServiceTool(Tool):
    """Tool that delegates to a single validated Home Assistant service."""

    def __init__(
        self,
        *,
        name: str,
        title: str,
        description: str,
        service: str,
        parameters: probatio.Schema,
        idempotent: bool,
    ) -> None:
        self.name = name
        self.title = title
        self.description = f"{description} {DEVICE_ALIAS_DESCRIPTION}"
        self.service = service
        self.parameters = parameters
        self.annotations = _annotations(idempotent=idempotent)
        self.integration = DOMAIN

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: ToolInput,
        llm_context: LLMContext,
    ) -> ToolResult:
        await hass.services.async_call(
            DOMAIN,
            self.service,
            dict(tool_input.tool_args),
            blocking=True,
            context=llm_context.context,
        )
        return ToolResult(data={"status": "service_completed"})


class StopCountdownTool(Tool):
    """Keep the explicit parameterless contract used by existing clients."""

    name = "tivoo__StopCountdown"
    title = "Stop Tivoo countdown"
    description = f"Stop the current Tivoo countdown. {DEVICE_ALIAS_DESCRIPTION}"
    parameters = probatio.Schema({}, extra=probatio.PREVENT_EXTRA)
    annotations = _annotations(idempotent=True)
    integration = DOMAIN

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: ToolInput,
        llm_context: LLMContext,
    ) -> ToolResult:
        if tool_input.tool_args:
            raise HomeAssistantError("StopCountdown does not accept parameters")
        await hass.services.async_call(
            DOMAIN,
            SERVICE_STOP_COUNTDOWN,
            {},
            blocking=True,
            context=llm_context.context,
        )
        return ToolResult(data={"status": "service_completed"})


def _schema(fields: dict) -> probatio.Schema:
    return probatio.Schema(fields, extra=probatio.PREVENT_EXTRA)


def _tools() -> list[Tool]:
    """Build the Tivoo-specific SPP capability surface exposed to Assist."""
    return [
        _ServiceTool(
            name="tivoo__SetExpression",
            title="Set Tivoo expression",
            description="Display a built-in Tivoo preset only when the user explicitly requests that visual; do not use it for assistant listening, thinking, tool use, or speaking state.",
            service=SERVICE_SET_EXPRESSION,
            parameters=_schema(
                {probatio.Required(ATTR_NAME): probatio.In(VISIBLE_PRESETS)}
            ),
            idempotent=False,
        ),
        _ServiceTool(
            name="tivoo__SetMood",
            title="Set Tivoo reply mood",
            description=(
                "Use only during an active Tivoo voice reply when the response has "
                "clear non-language emotional value. Do not use for neutral replies "
                "or to signal listening, thinking, tool use, or speaking state. "
                "In local voice mode the mood replaces the default speaking image "
                "during actual TTS playback; it does not display after the reply."
            ),
            service=SERVICE_SET_MOOD,
            parameters=_schema(
                {probatio.Required(ATTR_NAME): probatio.In(MOOD_PRESETS)}
            ),
            idempotent=False,
        ),
        _ServiceTool(
            name="tivoo__ShowText",
            title="Show Tivoo text",
            description="Display scrolling text with optional colors, speed and font.",
            service=SERVICE_SHOW_TEXT,
            parameters=_schema(
                {
                    probatio.Required(ATTR_VALUE): probatio.NonEmpty(),
                    probatio.Optional(ATTR_COLOR): str,
                    probatio.Optional(ATTR_BACKGROUND): str,
                    probatio.Optional(ATTR_SPEED): _integer_range(1, 65535),
                    probatio.Optional(ATTR_STEP): _integer_range(1, 8),
                    probatio.Optional(ATTR_FONT_SIZE): _integer_range(8, 16),
                    probatio.Optional(ATTR_FONT): probatio.In(FONT_NAMES),
                }
            ),
            idempotent=False,
        ),
        _ServiceTool(
            name="tivoo__SetBrightness",
            title="Set Tivoo brightness",
            description="Set the Tivoo screen brightness from 0 to 100.",
            service=SERVICE_SET_BRIGHTNESS,
            parameters=_schema({probatio.Required(ATTR_VALUE): _integer_range(0, 100)}),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__SetScreenPower",
            title="Set Tivoo screen power",
            description="Turn the Tivoo display on or off.",
            service=SERVICE_SET_SCREEN_POWER,
            parameters=_schema({probatio.Required(ATTR_VALUE): bool}),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__SetVolume",
            title="Set Tivoo speaker volume",
            description="Set speaker volume from 0 to 100.",
            service=SERVICE_SET_VOLUME,
            parameters=_schema(
                {probatio.Required(ATTR_VOLUME): _integer_range(0, 100)}
            ),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__SetPlayState",
            title="Control Tivoo playback",
            description="Play, pause, or select the previous or next audio track.",
            service=SERVICE_SET_PLAYSTATE,
            parameters=_schema(
                {probatio.Required(ATTR_VALUE): probatio.In(PLAYSTATES)}
            ),
            idempotent=False,
        ),
        _ServiceTool(
            name="tivoo__ShowClock",
            title="Show Tivoo clock",
            description="Show Tivoo clock style 0-6 with optional calendar/weather fields.",
            service=SERVICE_SHOW_CLOCK,
            parameters=_schema(
                {
                    probatio.Required(ATTR_CLOCK): _integer_range(0, 6),
                    probatio.Optional(ATTR_TWENTYFOUR): bool,
                    probatio.Optional(ATTR_WEATHER): bool,
                    probatio.Optional(ATTR_TEMP): bool,
                    probatio.Optional(ATTR_CALENDAR): bool,
                    probatio.Optional(ATTR_COLOR): str,
                    probatio.Optional(ATTR_HOT): bool,
                }
            ),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__SetDateTime",
            title="Set Tivoo date and time",
            description="Synchronize Tivoo date/time; omit value to use the HA host time.",
            service=SERVICE_SET_DATETIME,
            parameters=_schema({probatio.Optional(ATTR_VALUE): str}),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__SetWeather",
            title="Set Tivoo weather",
            description="Set temperature and Tivoo condition code 1, 3, 5, 6, 8 or 9.",
            service=SERVICE_SET_WEATHER,
            parameters=_schema(
                {
                    probatio.Required(ATTR_TEMPERATURE): probatio.Number(),
                    probatio.Required(ATTR_CONDITION): probatio.In(WEATHER_CODES),
                    probatio.Optional(ATTR_UNIT): probatio.In(("C", "F")),
                }
            ),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__SetLight",
            title="Show Tivoo light mode",
            description="Show the 16x16 light mode with brightness, color and effect 0-4.",
            service=SERVICE_SET_LIGHT,
            parameters=_schema(
                {
                    probatio.Required(ATTR_BRIGHTNESS): _integer_range(0, 100),
                    probatio.Optional(ATTR_COLOR): str,
                    probatio.Optional(ATTR_EFFECT): _integer_range(0, 4),
                    probatio.Optional(ATTR_POWER): bool,
                }
            ),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__StartCountdown",
            title="Start Tivoo countdown",
            description="Start the countdown using strict MM:SS format.",
            service=SERVICE_START_COUNTDOWN,
            parameters=_schema(
                {
                    probatio.Required(ATTR_COUNTDOWN): probatio.Match(
                        COUNTDOWN_PATTERN,
                        msg="countdown must use strict MM:SS format",
                    )
                }
            ),
            idempotent=False,
        ),
        StopCountdownTool(),
        _ServiceTool(
            name="tivoo__ShowLyrics",
            title="Show Tivoo lyrics",
            description="Open the Tivoo-specific lyrics view.",
            service=SERVICE_SHOW_LYRICS,
            parameters=_schema({}),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__ShowScoreboard",
            title="Show Tivoo scoreboard",
            description="Open the Tivoo-specific scoreboard and set both scores.",
            service=SERVICE_SHOW_SCOREBOARD,
            parameters=_schema(
                {
                    probatio.Optional(ATTR_PLAYER1): _integer_range(0, 65535),
                    probatio.Optional(ATTR_PLAYER2): _integer_range(0, 65535),
                }
            ),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__SetTimer",
            title="Set Tivoo timer",
            description="Start or stop the Tivoo built-in timer.",
            service=SERVICE_SET_TIMER,
            parameters=_schema({probatio.Required(ATTR_VALUE): bool}),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__SetNoiseMeter",
            title="Set Tivoo noise meter",
            description="Start or stop the Tivoo noise-meter view.",
            service=SERVICE_SET_NOISE_METER,
            parameters=_schema({probatio.Required(ATTR_VALUE): bool}),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__SetAlarm",
            title="Set Tivoo alarm",
            description="Set or clear a Tivoo alarm slot.",
            service=SERVICE_SET_ALARM,
            parameters=_schema(
                {
                    probatio.Optional(ATTR_SLOT): _integer_range(0, 255),
                    probatio.Optional(ATTR_TIME): str,
                    probatio.Optional(ATTR_WEEKDAYS): [probatio.In(WEEKDAYS)],
                    probatio.Optional(ATTR_FREQUENCY): probatio.Number(),
                    probatio.Optional(ATTR_VOLUME): _integer_range(0, 100),
                }
            ),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__SetMemorial",
            title="Set Tivoo memorial",
            description="Set or clear a Tivoo memorial/reminder slot.",
            service=SERVICE_SET_MEMORIAL,
            parameters=_schema(
                {
                    probatio.Optional(ATTR_SLOT): _integer_range(0, 255),
                    probatio.Optional(ATTR_VALUE): str,
                    probatio.Optional("text"): str,
                }
            ),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__SetAudioSource",
            title="Set Tivoo audio source",
            description="Select bluetooth, FM, line-in, SD card or USB; FM may include a frequency.",
            service=SERVICE_SET_AUDIO_SOURCE,
            parameters=_schema(
                {
                    probatio.Required(ATTR_VALUE): probatio.In(tuple(AUDIO_SOURCES)),
                    probatio.Optional(ATTR_FREQUENCY): probatio.Number(),
                }
            ),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__SetSleepMode",
            title="Set Tivoo sleep mode",
            description="Configure or stop Tivoo sleep mode.",
            service=SERVICE_SET_SLEEP_MODE,
            parameters=_schema(
                {
                    probatio.Required(ATTR_VALUE): bool,
                    probatio.Optional(ATTR_TIME): _integer_range(0, 255),
                    probatio.Optional(ATTR_MODE): _integer_range(0, 255),
                    probatio.Optional(ATTR_FREQUENCY): probatio.Number(),
                    probatio.Optional(ATTR_VOLUME): _integer_range(0, 100),
                    probatio.Optional(ATTR_COLOR): str,
                    probatio.Optional(ATTR_BRIGHTNESS): _integer_range(0, 100),
                }
            ),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__ShowDesign",
            title="Show Tivoo design",
            description="Show Tivoo design channel 0-3.",
            service=SERVICE_SHOW_DESIGN,
            parameters=_schema({probatio.Required(ATTR_NUMBER): _integer_range(0, 3)}),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__ShowEffects",
            title="Show Tivoo effects",
            description="Show a Tivoo effects-channel index. Available indices depend on device firmware.",
            service=SERVICE_SHOW_EFFECTS,
            parameters=_schema(
                {probatio.Required(ATTR_NUMBER): _integer_range(0, 255)}
            ),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__ShowVisualization",
            title="Show Tivoo visualization",
            description="Show a Tivoo visualization index. Available indices depend on device firmware.",
            service=SERVICE_SHOW_VISUALIZATION,
            parameters=_schema(
                {probatio.Required(ATTR_NUMBER): _integer_range(0, 255)}
            ),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__ShowGame",
            title="Show Tivoo game",
            description="Open Tivoo game mode, optionally selecting a game index.",
            service=SERVICE_SHOW_GAME,
            parameters=_schema({probatio.Optional(ATTR_INDEX): _integer_range(0, 127)}),
            idempotent=True,
        ),
        _ServiceTool(
            name="tivoo__GameControl",
            title="Control Tivoo game",
            description="Send go, left, right, up, down or ok to the active game.",
            service=SERVICE_GAME_CONTROL,
            parameters=_schema(
                {probatio.Required(ATTR_VALUE): probatio.In(tuple(GAME_CONTROLS))}
            ),
            idempotent=False,
        ),
        _ServiceTool(
            name="tivoo__ShowImage",
            title="Show an image on Tivoo",
            description="Display a PNG, JPEG or GIF file from the configured media directory.",
            service=SERVICE_SHOW_IMAGE,
            parameters=_schema(
                {
                    probatio.Required(ATTR_FILE): probatio.All(
                        str, probatio.NonEmpty()
                    ),
                    probatio.Optional(ATTR_TIME): _integer_range(0, 65535),
                }
            ),
            idempotent=False,
        ),
        _ServiceTool(
            name="tivoo__PlayAnimation",
            title="Play an animation on Tivoo",
            description="Play a GIF file from the configured media directory.",
            service=SERVICE_PLAY_ANIMATION,
            parameters=_schema(
                {
                    probatio.Required(ATTR_FILE): probatio.All(
                        str, probatio.NonEmpty()
                    ),
                    probatio.Optional(ATTR_TIME): _integer_range(0, 65535),
                }
            ),
            idempotent=False,
        ),
    ]


@callback
def async_get_tools(
    hass: HomeAssistant, llm_context: LLMContext, api_id: str
) -> LLMTools | None:
    """Expose Tivoo tools only through Assist while the integration is loaded."""
    if api_id != LLM_API_ASSIST:
        return None
    if not hass.config_entries.async_loaded_entries(DOMAIN):
        return None
    return LLMTools(tools=_tools())
