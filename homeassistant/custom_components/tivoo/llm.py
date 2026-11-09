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

from .const import DOMAIN, SERVICE_STOP_COUNTDOWN


class StopCountdownTool(Tool):
    """Stop the current Tivoo countdown through its Home Assistant service."""

    name = "tivoo__StopCountdown"
    title = "Stop Tivoo countdown"
    description = (
        "Stops the current Tivoo countdown. A successful result confirms that "
        "the Home Assistant service completed, not that the device acknowledged it."
    )
    parameters = probatio.Schema({})
    annotations = ToolAnnotations(
        read_only=False,
        destructive=False,
        idempotent=True,
        open_world=False,
    )
    integration = DOMAIN

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: ToolInput,
        llm_context: LLMContext,
    ) -> ToolResult:
        """Call the existing Tivoo service without adding service parameters."""
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


@callback
def async_get_tools(
    hass: HomeAssistant, llm_context: LLMContext, api_id: str
) -> LLMTools | None:
    """Expose Tivoo tools only through Assist while the integration is loaded."""
    if api_id != LLM_API_ASSIST:
        return None
    if not hass.config_entries.async_loaded_entries(DOMAIN):
        return None
    return LLMTools(tools=[StopCountdownTool()])
