"""HA TTS Proxy URL creation and Assist Pipeline event dispatch for P6."""

import asyncio
import logging
import uuid
from collections.abc import Coroutine, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from homeassistant.components import tts
from homeassistant.components.assist_pipeline.models import PipelineEvent
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .transport import Esp32ConnectionAdapter
from .tts_lifecycle import PipelineTtsOwner

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


class PipelineTtsEvents:
    """Bind the public Satellite caller and its TTS events to one run."""

    def __init__(self, hass: HomeAssistant, adapter: Esp32ConnectionAdapter) -> None:
        self._manager = TtsResourceManager(hass, adapter)
        self._hass = hass
        self._owner: PipelineTtsOwner | None = None
        self._caller: asyncio.Task | None = None
        self._events: set[asyncio.Task] = set()
        self._playback_id: str | None = None
        self._cancelled = False
        self._error_cleanup: asyncio.Task | None = None

    async def async_run(self, pipeline: Coroutine) -> None:
        """Run and join the public Satellite caller, including TTS on cancellation."""
        self._caller = asyncio.create_task(pipeline)
        try:
            await asyncio.shield(self._caller)
            if self._error_cleanup is not None:
                await asyncio.shield(self._error_cleanup)
        except BaseException as err:
            caller = self._caller
            if not caller.done() and not self._cancelled:
                caller.cancel()
            try:
                await self._stop_audio()
            except HomeAssistantError as cleanup_error:
                _LOGGER.error("Tivoo could not confirm Wyoming TTS cancellation")
                raise err from cleanup_error
            finally:
                await asyncio.gather(caller, return_exceptions=True)
            raise
        finally:
            self._caller = None

    async def async_cancel(self, playback_id: str) -> bool:
        """Cancel and join only the run associated with this playback ID."""
        if self._playback_id is None or playback_id != self._playback_id:
            return False
        caller = self._caller
        if caller is not None and not caller.done() and not self._cancelled:
            caller.cancel()
        try:
            await self._stop_audio()
        finally:
            if caller is not None:
                await asyncio.gather(caller, return_exceptions=True)
        return True

    async def _stop_audio(self) -> None:
        self._cancelled = True
        pending = tuple(self._events)
        for task in pending:
            task.cancel()
        try:
            if self._owner is not None:
                await self._owner.async_cancel()
        finally:
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    async def _handle_event(self, event: PipelineEvent) -> None:
        try:
            await self._manager.async_handle_pipeline_event(event)
        except HomeAssistantError:
            _LOGGER.warning(
                "Unable to send TTS resource to ESP32; check the internal URL "
                "and diagnostic connection"
            )
        if self._manager._resource is not None:
            self._playback_id = self._manager._resource.playback_id

    @callback
    def __call__(self, event: PipelineEvent) -> None:
        if self._cancelled:
            return
        event_type = str(event.type)
        if self._caller is not None and event_type == "run-start":
            output = (event.data or {}).get("tts_output")
            if (
                isinstance(output, Mapping)
                and isinstance(token := output.get("token"), str)
                and (stream := tts.async_get_stream(self._hass, token)) is not None
            ):
                self._owner = PipelineTtsOwner.for_stream(stream)
        elif self._owner is not None and event_type == "error":
            task = self._hass.async_create_task(
                self._stop_audio(), "Tivoo TTS error cleanup"
            )
            # The wrapper waits for this path after HA returns from a PipelineError.
            self._error_cleanup = task
            return
        task = self._hass.async_create_task(
            self._handle_event(event), "tivoo_tts_pipeline_event"
        )
        if not task.done():
            self._events.add(task)
            task.add_done_callback(self._events.discard)


def create_pipeline_event_callback(
    hass: HomeAssistant, adapter: Esp32ConnectionAdapter
) -> PipelineTtsEvents:
    """Create a per-run HA event callback and TTS lifecycle owner."""
    return PipelineTtsEvents(hass, adapter)
