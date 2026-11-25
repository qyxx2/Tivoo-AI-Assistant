"""Tivoo Home Assistant integration."""

import json
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .audio_resource import create_pipeline_event_callback
from .audio_session import AudioSessionManager
from .const import (
    CONF_ESP32_HOST,
    CONF_MEDIA_DIRECTORY,
    CONF_TIVOO_BLUETOOTH_MAC,
    DEFAULT_MEDIA_DIRECTORY,
    DEFAULT_TIVOO_BLUETOOTH_MAC,
    DOMAIN,
)
from .diagnostics import TYPE_MIC_CAPTURE_STOP
from .display_state import ExpressionCoordinator
from .qwen_realtime import QwenRealtimeBridge, TivooQwenPcmView
from .services import register_services, unregister_services
from .transport import Esp32ConnectionAdapter

_LOGGER = logging.getLogger(__name__)


class _RuntimeDisplayAdapter:
    """Use the current semantic adapter, including HA test adapter substitutions."""

    def __init__(self, runtime: dict) -> None:
        self._runtime = runtime

    async def async_execute(self, command) -> None:
        await self._runtime["command_adapter"].async_execute(command)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tivoo services and the shared runtime for one config entry."""
    media_directory = entry.data.get(CONF_MEDIA_DIRECTORY, DEFAULT_MEDIA_DIRECTORY)
    adapter = Esp32ConnectionAdapter(
        entry.data.get(CONF_ESP32_HOST),
        entry.data.get(CONF_TIVOO_BLUETOOTH_MAC, DEFAULT_TIVOO_BLUETOOTH_MAC),
    )

    async def send_mic_capture_stop(session_id: str, reason: str) -> None:
        payload = json.dumps(
            {"session_id": session_id, "reason": reason}, separators=(",", ":")
        ).encode("utf-8")
        await adapter.async_send_message(TYPE_MIC_CAPTURE_STOP, payload)

    audio_session_manager = AudioSessionManager(send_mic_capture_stop)
    adapter.register_audio_session_manager(audio_session_manager)

    streams = hass.data.get("tivoo_qwen_streams")
    if streams is None:
        streams = hass.data["tivoo_qwen_streams"] = {}
        hass.http.register_view(TivooQwenPcmView(streams))
    qwen_bridge = QwenRealtimeBridge(hass, adapter, streams, entry.entry_id)

    runtime = {
        "command_adapter": adapter,
        "connection_adapter": adapter,
        "audio_session_manager": audio_session_manager,
        "qwen_bridge": qwen_bridge,
        "pipeline_event_callback_factory": lambda: create_pipeline_event_callback(
            hass, adapter
        ),
        "media_directory": hass.config.path(media_directory),
        "tivoo_bluetooth_mac": entry.data.get(
            CONF_TIVOO_BLUETOOTH_MAC, DEFAULT_TIVOO_BLUETOOTH_MAC
        ),
    }
    display = ExpressionCoordinator(
        _RuntimeDisplayAdapter(runtime), spp_connected=not bool(adapter.host)
    )
    runtime["display_coordinator"] = display
    adapter.register_spp_state_handler(display.async_on_spp_state)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform.ASSIST_SATELLITE, Platform.SELECT]
    )
    await adapter.async_start()
    try:
        await display.async_start()
    except HomeAssistantError as err:
        # The runtime may load before 7777 becomes available. Keep desired
        # and retry it on a validated SPP reconnect or a later command.
        _LOGGER.debug("Tivoo initial idle is pending transport: %s", err)
    register_services(hass, runtime)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop TCP connections and remove services/runtime state."""
    if not await hass.config_entries.async_unload_platforms(
        entry, [Platform.ASSIST_SATELLITE, Platform.SELECT]
    ):
        return False
    domain_data = hass.data.get(DOMAIN)
    if domain_data is not None:
        runtime = domain_data.get(entry.entry_id)
        if runtime is not None:
            await runtime["display_coordinator"].async_shutdown()
            await runtime["audio_session_manager"].async_shutdown()
            await runtime["qwen_bridge"].async_close()
            await runtime["connection_adapter"].async_stop()

    unregister_services(hass)
    if domain_data is not None:
        domain_data.pop(entry.entry_id, None)
        if not domain_data:
            hass.data.pop(DOMAIN)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate the P4 entry while requiring the user to configure ESP32 IPv4."""
    if entry.version == 1:
        data = dict(entry.data)
        data.setdefault(CONF_TIVOO_BLUETOOTH_MAC, DEFAULT_TIVOO_BLUETOOTH_MAC)
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            version=2,
        )
        return True

    return entry.version == 2
