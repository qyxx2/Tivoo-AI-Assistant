"""Assist Satellite backed by a persistent Tivoo microphone upload."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.assist_pipeline.models import (
    PipelineEvent,
    PipelineEventType,
    PipelineStage,
)
from homeassistant.components.assist_satellite import (
    AssistSatelliteConfiguration,
    AssistSatelliteEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .audio_resource import PipelineTtsEvents
from .audio_session import AudioSessionManager
from .const import DOMAIN
from .transport import Esp32ConnectionAdapter

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Register a satellite for the configured ESP32."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            TivooAssistSatellite(
                entry.entry_id,
                runtime["audio_session_manager"],
                runtime["connection_adapter"],
            )
        ]
    )


@dataclass(eq=False, slots=True)
class _Turn:
    """Identity and playback state for one Pipeline generation."""

    session_id: str
    tts: PipelineTtsEvents
    waiting_for_wake: bool
    task: asyncio.Task | None = None
    error: bool = False
    command_started: bool = False
    playback_completed: bool = False


class AudioSessionCoordinator:
    """Own Pipeline turns and speech timers independently of network ingress."""

    def __init__(
        self, entity: TivooAssistSatellite, ingress: AudioSessionManager
    ) -> None:
        self.entity = entity
        self.ingress = ingress
        self._session_id: str | None = None
        self._turn: _Turn | None = None
        self._timers: dict[str, Callable[[], None]] = {}
        self._followup = False
        self._closing: asyncio.Future | None = None
        self._event_turn: _Turn | None = None

    def _cancel_timer(self, reason: str) -> None:
        if cancel := self._timers.pop(reason, None):
            cancel()

    def _clear_timers(self) -> None:
        for reason in tuple(self._timers):
            self._cancel_timer(reason)

    def _arm(self, seconds: float, reason: str) -> None:
        self._cancel_timer(reason)
        turn = self._turn

        @callback
        def expired(_now) -> None:
            if turn is not None:
                self.entity.hass.async_create_task(
                    self._expire_timer(turn, reason, cancel), f"Tivoo {reason}"
                )

        cancel = async_call_later(self.entity.hass, seconds, expired)
        self._timers[reason] = cancel

    async def _expire_timer(
        self, turn: _Turn, reason: str, cancel: Callable[[], None]
    ) -> None:
        if self._turn is turn and self._timers.get(reason) is cancel:
            await self.ingress.async_stop_session(turn.session_id, reason)

    @callback
    def on_activity(self, session_id: str, state: str) -> None:
        """Gate wake and follow-up on speech transitions."""
        if self._session_id is None:
            if state == "speech_start":
                self._session_id = session_id
                self._start_turn(PipelineStage.WAKE_WORD)
            return

        turn = self._turn
        if session_id != self._session_id or turn is None:
            return
        if self._followup and state == "speech_start":
            self._start_turn(PipelineStage.STT)
        elif turn.waiting_for_wake:
            if state == "speech_start":
                self._cancel_timer("wake_miss")
            elif "wake_miss" not in self._timers:
                self._arm(3, "wake_miss")

    def _start_turn(self, stage: PipelineStage) -> None:
        self._clear_timers()
        self._followup = False
        session_id = self._session_id
        assert session_id is not None
        # Capture the boundary synchronously, before transport dispatches any
        # PCM following the speech-start frame in the same TCP read.
        start = self.ingress.ingress_offset(session_id)
        turn = _Turn(
            session_id,
            PipelineTtsEvents(self.entity.hass, self.entity.adapter),
            waiting_for_wake=stage == PipelineStage.WAKE_WORD,
        )
        previous = self._turn
        self._turn = turn
        if turn.waiting_for_wake:
            self._arm(15, "wake_candidate_timeout")
        prior_task = previous.task if previous is not None else self._closing
        if self._closing is not None and self._closing.done():
            self._closing = None
        turn.task = self.entity.hass.async_create_background_task(
            self._run_turn(turn, stage, start, prior_task), "Tivoo satellite Pipeline"
        )

    async def _run_turn(
        self,
        turn: _Turn,
        stage: PipelineStage,
        start: int,
        prior: asyncio.Future | None,
    ) -> None:
        try:
            async with self.ingress.audio_subscription(
                turn.session_id, start=start, consumer=turn
            ) as audio:
                if prior is not None and not prior.done():
                    # Reconnect/follow-up must not overtake the previous public
                    # caller, including its asynchronous cancellation cleanup.
                    await asyncio.shield(asyncio.gather(prior, return_exceptions=True))
                self._event_turn = turn
                try:
                    await turn.tts.async_run(
                        self.entity.async_accept_pipeline_from_satellite(audio, stage)
                    )
                finally:
                    self._event_turn = None
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Tivoo satellite Pipeline failed")
            turn.error = True

        if self._turn is not turn:
            return
        if turn.error or not turn.command_started or turn.tts.send_failed:
            await self.ingress.async_stop_session(turn.session_id, "pipeline_failed")
        elif turn.tts.playback_id is None and not self._followup:
            self._open_followup()

    @callback
    def on_pipeline_event(self, event: PipelineEvent) -> None:
        """Track command-start timers and route TTS through the run owner."""
        turn = self._event_turn
        if turn is None or turn is not self._turn:
            return
        turn.tts(event)
        match event.type:
            case PipelineEventType.WAKE_WORD_END:
                if turn.waiting_for_wake and (event.data or {}).get("wake_word_output"):
                    turn.waiting_for_wake = False
                    self._clear_timers()
                    self._arm(5, "command_timeout")
            case PipelineEventType.STT_START:
                if "command_timeout" not in self._timers:
                    self._arm(5, "command_timeout")
            case PipelineEventType.STT_VAD_START:
                turn.command_started = True
                self._cancel_timer("command_timeout")
            case PipelineEventType.STT_VAD_END | PipelineEventType.STT_END:
                self.ingress.release_subscription(turn.session_id, turn)
            case PipelineEventType.ERROR:
                turn.error = True

    @callback
    def on_playback(self, playback_id: str, state: str) -> None:
        """Use the matching physical playback terminal state."""
        turn = self._turn
        if turn is None or turn.tts.playback_id != playback_id or self._followup:
            return
        if state == "completed":
            turn.playback_completed = True
            self._open_followup()
        elif state in ("stopped", "interrupted", "failed"):
            self._arm(0, "playback_failed")

    def _open_followup(self) -> None:
        self.entity.tts_response_finished()
        self._followup = True
        self._arm(8, "followup_timeout")

    @callback
    def on_end(self, session_id: str, _reason: str) -> None:
        """Cancel the owning turn when its upload goes away."""
        if self._session_id != session_id:
            return
        self._session_id = None
        self._followup = False
        self._clear_timers()
        turn, self._turn = self._turn, None
        if turn is not None:
            tasks = {self._event_turn.task} if self._event_turn is not None else set()
            tasks.add(turn.task)
            pending: list[asyncio.Future] = []
            for task in tasks:
                if task is None or task.done():
                    continue
                pending.append(task)
                if task is not asyncio.current_task() and not task.cancelling():
                    task.cancel()
            if (
                not turn.playback_completed
                and turn.task is not None
                and (turn.task.done() or turn.task is asyncio.current_task())
            ):
                pending.append(
                    self.entity.hass.async_create_background_task(
                        self._close_tts(turn), "Tivoo close TTS"
                    )
                )
            if pending:
                if self._closing is not None and not self._closing.done():
                    pending.append(self._closing)
                self._closing = asyncio.gather(*pending, return_exceptions=True)
        self.entity.tts_response_finished()

    async def _close_tts(self, turn: _Turn) -> None:
        try:
            await turn.tts.async_close()
        except Exception:
            _LOGGER.exception("Tivoo could not close the active TTS stream")

    async def async_shutdown(self) -> None:
        """Join the Pipeline and its owned TTS resources on unload."""
        await self.ingress.async_shutdown()
        if self._closing is not None:
            await asyncio.gather(self._closing, return_exceptions=True)


class TivooAssistSatellite(AssistSatelliteEntity):
    """Home Assistant Assist entrypoint for Tivoo speech sessions."""

    _attr_name = "Tivoo"

    def __init__(
        self,
        entry_id: str,
        ingress: AudioSessionManager,
        adapter: Esp32ConnectionAdapter,
    ) -> None:
        self._attr_unique_id = entry_id
        self._attr_tts_options = {"preferred_format": "mp3"}
        self.adapter = adapter
        self.coordinator = AudioSessionCoordinator(self, ingress)

    async def async_added_to_hass(self) -> None:
        """Bind transport callbacks after the entity is ready."""
        self.adapter.register_playback_handler(self.coordinator.on_playback)
        self.coordinator.ingress.on_activity = self.coordinator.on_activity
        self.coordinator.ingress.on_end = self.coordinator.on_end

    @callback
    def async_get_configuration(self) -> AssistSatelliteConfiguration:
        """Wake words are configured in the selected HA pipeline."""
        return AssistSatelliteConfiguration([], [], 0)

    async def async_set_configuration(
        self, config: AssistSatelliteConfiguration
    ) -> None:
        """There is no device-local wake word configuration."""

    @callback
    def on_pipeline_event(self, event: PipelineEvent) -> None:
        """Forward HA Pipeline events to the owning turn."""
        self.coordinator.on_pipeline_event(event)

    async def async_will_remove_from_hass(self) -> None:
        """Close the upload and wait for its Pipeline before transport unload."""
        await self.coordinator.async_shutdown()
        self.coordinator.ingress.on_activity = None
        self.coordinator.ingress.on_end = None
