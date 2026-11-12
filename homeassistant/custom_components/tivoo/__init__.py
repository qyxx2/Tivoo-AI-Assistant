"""Tivoo Home Assistant integration."""

import json

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

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
from .services import register_services, unregister_services
from .transport import Esp32ConnectionAdapter


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
    await adapter.async_start()

    runtime = {
        "command_adapter": adapter,
        "connection_adapter": adapter,
        "audio_session_manager": audio_session_manager,
        "pipeline_event_callback_factory": lambda: create_pipeline_event_callback(
            hass, adapter
        ),
        "media_directory": hass.config.path(media_directory),
        "tivoo_bluetooth_mac": entry.data.get(
            CONF_TIVOO_BLUETOOTH_MAC, DEFAULT_TIVOO_BLUETOOTH_MAC
        ),
    }
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    register_services(hass, runtime)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop TCP connections and remove services/runtime state."""
    domain_data = hass.data.get(DOMAIN)
    if domain_data is not None:
        runtime = domain_data.get(entry.entry_id)
        if runtime is not None:
            await runtime["audio_session_manager"].async_shutdown()
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
