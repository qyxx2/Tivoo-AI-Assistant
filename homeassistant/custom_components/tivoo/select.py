"""Dedicated Assist pipeline selection for the local wake protocol."""
from homeassistant.components.assist_pipeline.select import AssistPipelineSelect
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([AssistPipelineSelect(hass, DOMAIN, entry.entry_id)])
