"""LLM tool exposed by the AstrBot integration."""

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

from .const import DOMAIN, SERVICE_NEW_CONVERSATION


class NewConversationTool(Tool):
    """Start a fresh AstrBot context for the next user turn."""

    name = "astrbot__NewConversation"
    title = "Start a new AstrBot conversation"
    description = (
        "Discard the current short-term AstrBot conversation context so the next "
        "user turn starts a fresh conversation. Use only when the user explicitly "
        "asks to start a new, clean, or separate conversation. This does not erase "
        "Home Assistant configuration or long-term learned preferences."
    )
    parameters = probatio.Schema({}, extra=probatio.PREVENT_EXTRA)
    annotations = ToolAnnotations(
        read_only=False,
        destructive=True,
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
        if tool_input.tool_args:
            raise HomeAssistantError("NewConversation does not accept parameters")
        await hass.services.async_call(
            DOMAIN,
            SERVICE_NEW_CONVERSATION,
            {},
            blocking=True,
            context=llm_context.context,
        )
        return ToolResult(data={"status": "new_conversation_ready"})


@callback
def async_get_tools(
    hass: HomeAssistant, llm_context: LLMContext, api_id: str
) -> LLMTools | None:
    """Expose the new-conversation tool through Assist while AstrBot is loaded."""
    if api_id != LLM_API_ASSIST:
        return None
    if not hass.config_entries.async_loaded_entries(DOMAIN):
        return None
    return LLMTools(tools=[NewConversationTool()])
