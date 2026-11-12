"""HA TTS Proxy URL creation and Assist Pipeline event dispatch for P6."""

import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from homeassistant.components.assist_pipeline.models import PipelineEvent
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .transport import Esp32ConnectionAdapter

_LOGGER = logging.getLogger(__name__)


def build_internal_tts_url(hass: HomeAssistant, relative_url: str) -> str:
    """Build an ESP32-reachable internal URL for one HA TTS Proxy resource."""
    if not isinstance(relative_url, str):
        raise HomeAssistantError("TTS Proxy URL must be a relative URL")

    resource = urlsplit(relative_url)
    if (
        resource.scheme
        or resource.netloc
        or resource.fragment
        or not resource.path.startswith("/api/tts_proxy/")
        or resource.path == "/api/tts_proxy/"
    ):
        raise HomeAssistantError("TTS resource must use a relative HA TTS Proxy URL")

    try:
        base_url = get_url(
            hass,
            allow_internal=True,
            allow_external=False,
            allow_cloud=False,
            allow_ip=True,
        )
    except NoURLAvailableError as err:
        raise HomeAssistantError(
            "No internal Home Assistant URL is available for the ESP32 TTS resource"
        ) from err

    base = urlsplit(base_url)
    if base.scheme not in {"http", "https"} or not base.netloc:
        raise HomeAssistantError(
            "Home Assistant did not provide a usable internal URL for the ESP32"
        )

    return f"{base_url.rstrip('/')}{relative_url}"


@dataclass(slots=True)
class _TtsResource:
    """TTS metadata associated with a single Pipeline run."""

    playback_id: str
    relative_url: str
    mime_type: str
    stream_response: bool
    sent: bool = False


class TtsResourceManager:
    """Translate one Assist Pipeline run's events into one TTS_PLAY message."""

    def __init__(self, hass: HomeAssistant, adapter: Esp32ConnectionAdapter) -> None:
        self.hass = hass
        self.adapter = adapter
        self._resource: _TtsResource | None = None

    @staticmethod
    def _output_fields(output: object) -> tuple[str, str] | None:
        if not isinstance(output, Mapping):
            return None
        url = output.get("url")
        mime_type = output.get("mime_type")
        if (
            not isinstance(url, str)
            or not url
            or not isinstance(mime_type, str)
            or not mime_type
        ):
            return None
        return url, mime_type

    async def _send_once(self, resource: _TtsResource) -> None:
        if resource.sent:
            return
        url = build_internal_tts_url(self.hass, resource.relative_url)
        resource.sent = True
        await self.adapter.async_send_tts_play(
            resource.playback_id,
            url,
            resource.mime_type,
        )

    async def async_handle_pipeline_event(self, event: PipelineEvent) -> None:
        """Handle one HA Pipeline event without retaining state across runs."""
        event_type = str(event.type)
        data = event.data if isinstance(event.data, dict) else {}

        if event_type == "run-start":
            self._resource = None
            fields = self._output_fields(data.get("tts_output"))
            if fields is not None:
                relative_url, mime_type = fields
                self._resource = _TtsResource(
                    playback_id=str(uuid.uuid4()),
                    relative_url=relative_url,
                    mime_type=mime_type,
                    stream_response=data["tts_output"].get("stream_response") is True,
                )
            return

        if event_type == "intent-progress":
            resource = self._resource
            if (
                resource is not None
                and resource.stream_response
                and data.get("tts_start_streaming") is True
            ):
                await self._send_once(resource)
            return

        if event_type == "tts-end":
            resource = self._resource
            fields = self._output_fields(data.get("tts_output"))
            if resource is None:
                if fields is None:
                    return
                relative_url, mime_type = fields
                resource = _TtsResource(
                    playback_id=str(uuid.uuid4()),
                    relative_url=relative_url,
                    mime_type=mime_type,
                    stream_response=False,
                )
                self._resource = resource
            elif not resource.sent and fields is not None:
                resource.relative_url, resource.mime_type = fields

            await self._send_once(resource)
            return

        if event_type == "run-end":
            self._resource = None


def create_pipeline_event_callback(
    hass: HomeAssistant, adapter: Esp32ConnectionAdapter
) -> Callable[[PipelineEvent], None]:
    """Create a sync HA Pipeline callback with state isolated to one run."""
    manager = TtsResourceManager(hass, adapter)

    async def async_handle_event(event: PipelineEvent) -> None:
        try:
            await manager.async_handle_pipeline_event(event)
        except HomeAssistantError:
            _LOGGER.warning(
                "Unable to send TTS resource to ESP32; check the internal URL "
                "and diagnostic connection"
            )

    def handle_event(event) -> None:
        hass.async_create_task(
            async_handle_event(event),
            "tivoo_tts_pipeline_event",
        )

    return handle_event
