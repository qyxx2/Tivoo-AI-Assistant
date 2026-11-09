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
    SERVICE_SET_EXPRESSION,
    SERVICE_SET_VOLUME,
    SERVICE_SHOW_TEXT,
    SERVICE_START_COUNTDOWN,
    SERVICE_STOP_COUNTDOWN,
)
from .rendering import FONT_NAMES
from .services import COUNTDOWN_PATTERN, VISIBLE_PRESETS


def _annotations(*, idempotent: bool) -> ToolAnnotations:
    return ToolAnnotations(
        read_only=False,
        destructive=False,
        idempotent=idempotent,
        open_world=False,
    )


class _ServiceTool(Tool):
    """Base class for Tivoo tools that delegate to the matching HA service."""

    service = ""

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
    """Stop the currently active Tivoo countdown."""

    name = "tivoo__StopCountdown"
    title = "Stop Tivoo countdown"
    description = (
        "Stops the current Tivoo countdown without requiring its previous duration."
    )
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


class SetExpressionTool(_ServiceTool):
    name = "tivoo__SetExpression"
    title = "Set Tivoo expression"
    description = "Display one of the built-in Tivoo expression presets."
    service = SERVICE_SET_EXPRESSION
    annotations = _annotations(idempotent=False)
    integration = DOMAIN
    parameters = probatio.Schema(
        {
            probatio.Required(ATTR_NAME): probatio.In(VISIBLE_PRESETS),
        },
        extra=probatio.PREVENT_EXTRA,
    )


class ShowTextTool(_ServiceTool):
    name = "tivoo__ShowText"
    title = "Show Tivoo text"
    description = (
        "Display scrolling text with optional color, background, speed and font style."
    )
    service = SERVICE_SHOW_TEXT
    annotations = _annotations(idempotent=False)
    integration = DOMAIN
    parameters = probatio.Schema(
        {
            probatio.Required(ATTR_VALUE): probatio.NonEmpty(),
            probatio.Optional(ATTR_COLOR): str,
            probatio.Optional(ATTR_BACKGROUND): str,
            probatio.Optional(ATTR_SPEED): probatio.Range(min=1, max=65535),
            probatio.Optional(ATTR_STEP): probatio.Range(min=1, max=8),
            probatio.Optional(ATTR_FONT_SIZE): probatio.Range(min=8, max=16),
            probatio.Optional(ATTR_FONT): probatio.In(FONT_NAMES),
        },
        extra=probatio.PREVENT_EXTRA,
    )


class StartCountdownTool(_ServiceTool):
    name = "tivoo__StartCountdown"
    title = "Start Tivoo countdown"
    description = "Start the Tivoo countdown using strict MM:SS format."
    service = SERVICE_START_COUNTDOWN
    annotations = _annotations(idempotent=False)
    integration = DOMAIN
    parameters = probatio.Schema(
        {
            probatio.Required(ATTR_COUNTDOWN): probatio.Match(
                COUNTDOWN_PATTERN, msg="countdown must use strict MM:SS format"
            ),
        },
        extra=probatio.PREVENT_EXTRA,
    )


class SetVolumeTool(_ServiceTool):
    name = "tivoo__SetVolume"
    title = "Set Tivoo speaker volume"
    description = "Set Tivoo speaker volume from 0 (mute) to 100 (maximum)."
    service = SERVICE_SET_VOLUME
    annotations = _annotations(idempotent=True)
    integration = DOMAIN
    parameters = probatio.Schema(
        {probatio.Required(ATTR_VOLUME): probatio.Range(min=0, max=100)},
        extra=probatio.PREVENT_EXTRA,
    )


@callback
def async_get_tools(
    hass: HomeAssistant, llm_context: LLMContext, api_id: str
) -> LLMTools | None:
    """Expose Tivoo tools only through Assist while the integration is loaded."""
    if api_id != LLM_API_ASSIST:
        return None
    if not hass.config_entries.async_loaded_entries(DOMAIN):
        return None
    return LLMTools(
        tools=[
            SetExpressionTool(),
            ShowTextTool(),
            StartCountdownTool(),
            StopCountdownTool(),
            SetVolumeTool(),
        ]
    )
