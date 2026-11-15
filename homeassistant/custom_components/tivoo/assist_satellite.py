"""Assist Satellite backed by a persistent Tivoo microphone upload."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass

from homeassistant.components import wake_word
from homeassistant.components.assist_pipeline import async_get_pipeline
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
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .audio_resource import PipelineTtsEvents
from .audio_session import AudioSessionManager
from .const import DOMAIN
from .display_state import DisplayState, ExpressionCoordinator, build_expression_command
from .transport import Esp32ConnectionAdapter

_LOGGER = logging.getLogger(__name__)
_WAKE_WORD_ID = "tivoo-wake"


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
                runtime["display_coordinator"],
            )
        ]
    )


@dataclass(eq=False, slots=True)
class _Turn:
    """Identity and playback state for one Pipeline generation."""

    session_id: str
    context: Context
    tts: PipelineTtsEvents
    waiting_for_wake: bool
    task: asyncio.Task | None = None
    pipeline_id: str | None = None
    watcher: asyncio.Task | None = None
    watcher_consumer: object | None = None
    error: bool = False
    command_started: bool = False
    playback_completed: bool = False
    interrupted: bool = False


class AudioSessionCoordinator:
    """Own Pipeline turns and speech timers independently of network ingress."""

    def __init__(
        self,
        entity: TivooAssistSatellite,
        ingress: AudioSessionManager,
        display: ExpressionCoordinator,
    ) -> None:
        self.entity = entity
        self.ingress = ingress
        self.display = display
        self._session_id: str | None = None
        self._turn: _Turn | None = None
        self._timers: dict[str, Callable[[], None]] = {}
        self._followup = False
        self._closing: asyncio.Future | None = None
        self._event_turn: _Turn | None = None

    def _show(self, coroutine, name: str) -> None:
        self.entity.hass.async_create_task(coroutine, f"Tivoo display {name}")

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
                self.display.begin_candidate(self._turn.context.id)
            return

        turn = self._turn
        if session_id != self._session_id or turn is None:
            return
        if self._followup and state == "speech_start":
            self._start_turn(PipelineStage.STT)
        elif turn.waiting_for_wake:
            if state == "speech_start":
                self.display.begin_candidate(turn.context.id)
                self._cancel_timer("wake_miss")
            else:
                self.display.end_candidate(turn.context.id)
                if "wake_miss" not in self._timers:
                    self._arm(3, "wake_miss")

    def _start_turn(
        self,
        stage: PipelineStage,
        *,
        interrupted: _Turn | None = None,
        start: int | None = None,
        confirmed: bool = False,
    ) -> None:
        self._clear_timers()
        self._followup = False
        session_id = self._session_id
        assert session_id is not None
        # Capture the boundary synchronously, before transport dispatches any
        # PCM following the speech-start frame in the same TCP read.
        if start is None:
            start = self.ingress.ingress_offset(session_id)
        turn = _Turn(
            session_id,
            Context(),
            PipelineTtsEvents(self.entity.hass, self.entity.adapter),
            waiting_for_wake=stage == PipelineStage.WAKE_WORD,
        )
        previous = self._turn
        self._turn = turn
        self.display.begin_generation(turn.context.id)
        if confirmed:
            self._show(
                self.display.async_set_intent(
                    DisplayState.WAKE_CONFIRMED,
                    build_expression_command("question"),
                    generation=turn.context.id,
                ),
                "wake confirmed",
            )
        elif stage is PipelineStage.STT:
            self._show(
                self.display.async_set_intent(
                    DisplayState.ACTIVE_LISTENING,
                    build_expression_command("standby"),
                    generation=turn.context.id,
                ),
                "followup listening",
            )
        if turn.waiting_for_wake:
            self._arm(15, "wake_candidate_timeout")
        if previous is not None and interrupted is None:
            prior_task = asyncio.gather(
                *(
                    task
                    for task in (previous.task, previous.watcher)
                    if task is not None
                ),
                return_exceptions=True,
            )
        else:
            prior_task = self._closing
        if self._closing is not None and self._closing.done():
            self._closing = None
        turn.task = self.entity.hass.async_create_background_task(
            self._run_turn(turn, stage, start, prior_task, interrupted),
            "Tivoo satellite Pipeline",
        )

    async def _run_turn(
        self,
        turn: _Turn,
        stage: PipelineStage,
        start: int,
        prior: asyncio.Future | None,
        interrupted: _Turn | None,
    ) -> None:
        cleanup = (
            asyncio.create_task(self._interrupt_turn(interrupted))
            if interrupted
            else None
        )
        try:
            async with self.ingress.audio_subscription(
                turn.session_id, start=start, consumer=turn
            ) as audio:
                if cleanup is not None:
                    await asyncio.shield(cleanup)
                elif prior is not None and not prior.done():
                    # Reconnect/follow-up must not overtake the previous public
                    # caller, including its asynchronous cancellation cleanup.
                    await asyncio.shield(asyncio.gather(prior, return_exceptions=True))
                self._event_turn = turn
                try:
                    await turn.tts.async_run(
                        self.entity.async_accept_pipeline_from_satellite(
                            audio, stage, context=turn.context
                        )
                    )
                finally:
                    self._event_turn = None
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Tivoo satellite Pipeline or PCM handoff failed")
            turn.error = True
        finally:
            if cleanup is not None:
                await asyncio.gather(cleanup, return_exceptions=True)

        if self._turn is not turn:
            return
        if turn.error or not turn.command_started or turn.tts.send_failed:
            await self.ingress.async_stop_session(turn.session_id, "pipeline_failed")
        elif turn.tts.playback_id is None and not self._followup:
            self._open_followup()

    async def _interrupt_turn(self, turn: _Turn) -> None:
        """Join the interrupted caller and its audio owner before reusing Assist."""
        try:
            async with asyncio.timeout(5):
                await turn.tts.async_stop_playback()
        finally:
            if turn.task is not None and not turn.task.done():
                if not turn.task.cancelling():
                    turn.task.cancel()
                await asyncio.gather(turn.task, return_exceptions=True)
            # Also covers an already-returned caller and propagates a failed
            # Wyoming cleanup so the replacement cannot overtake it.
            await turn.tts.async_close()

    def _start_watcher(self, turn: _Turn) -> None:
        if turn.watcher is not None or turn.waiting_for_wake or self._followup:
            return
        start = self.ingress.ingress_offset(turn.session_id)
        turn.watcher_consumer = object()
        turn.watcher = self.entity.hass.async_create_background_task(
            self._watch_wake_word(turn, start, turn.watcher_consumer),
            "Tivoo side wake word",
        )

    def _stop_watcher(self, turn: _Turn) -> asyncio.Task | None:
        if turn.watcher_consumer is not None:
            # Wyoming waits for its pending read on cancellation. Releasing
            # the cursor wakes that read even when no new MIC_PCM is arriving.
            self.ingress.release_subscription(turn.session_id, turn.watcher_consumer)
        task = turn.watcher
        if task is not None and not task.done():
            if not task.cancelling():
                task.cancel()
            return task
        return None

    async def _watch_wake_word(self, turn: _Turn, start: int, consumer: object) -> None:
        try:
            selection = self.entity.wake_word_provider(turn.pipeline_id)
        except Exception:
            _LOGGER.exception("Tivoo could not resolve the selected wake-word provider")
            return
        if selection is None:
            return
        provider, wake_word_id = selection

        while self._turn is turn and not self._followup and not turn.error:
            last_offset = start

            async def indexed_audio(
                audio: AsyncIterator[bytes],
                offset: int,
            ) -> AsyncIterator[tuple[bytes, int]]:
                nonlocal last_offset
                async for chunk in audio:
                    last_offset = offset
                    # Sherpa echoes this value as an opaque ingress position.
                    yield chunk, offset
                    offset += len(chunk)

            try:
                async with (
                    self.ingress.audio_subscription(
                        turn.session_id, start=start, consumer=consumer
                    ) as audio,
                    aclosing(indexed_audio(audio, start)) as chunks,
                ):
                    detection = await provider.async_process_audio_stream(
                        chunks, wake_word_id
                    )
            except Exception:
                _LOGGER.exception("Tivoo side wake-word detection failed")
                detection = None

            if self._turn is not turn or self._followup or turn.error:
                return
            if detection is not None and detection.wake_word_id == wake_word_id:
                # Provider queued chunks already exist in ingress. Replay
                # their union with pre-roll and later PCM as one subscription.
                detection_offset = (
                    last_offset if detection.timestamp is None else detection.timestamp
                )
                start_offset = self.ingress.handoff_start(detection_offset)
                for _, offset in detection.queued_audio or ():
                    start_offset = min(start_offset, offset)

                turn.interrupted = True
                turn.tts.stop_dispatch()
                self._start_turn(
                    PipelineStage.STT,
                    interrupted=turn,
                    start=start_offset,
                    confirmed=True,
                )
                return

            # HA Wyoming returns None when its connection ends. Reopen while
            # the turn is active, with backoff for a busy or offline provider.
            await asyncio.sleep(1)
            start = self.ingress.ingress_offset(turn.session_id)

    @callback
    def on_pipeline_event(self, event: PipelineEvent) -> None:
        """Track command-start timers and route TTS through the run owner."""
        turn = self._event_turn
        if turn is None or turn is not self._turn:
            return
        turn.tts(event)
        match event.type:
            case PipelineEventType.RUN_START:
                turn.pipeline_id = (event.data or {}).get("pipeline")
            case PipelineEventType.WAKE_WORD_END:
                if turn.waiting_for_wake and (event.data or {}).get("wake_word_output"):
                    turn.waiting_for_wake = False
                    self.display.end_candidate(turn.context.id)
                    self._show(
                        self.display.async_set_intent(
                            DisplayState.WAKE_CONFIRMED,
                            build_expression_command("question"),
                            generation=turn.context.id,
                        ),
                        "wake confirmed",
                    )
                    self._clear_timers()
                    self._arm(5, "command_timeout")
            case PipelineEventType.STT_START:
                if "command_timeout" not in self._timers:
                    self._arm(5, "command_timeout")
                self._start_watcher(turn)
            case PipelineEventType.STT_VAD_START:
                turn.command_started = True
                self._cancel_timer("command_timeout")
            case PipelineEventType.STT_VAD_END | PipelineEventType.STT_END:
                self.ingress.release_subscription(turn.session_id, turn)
                if event.type is PipelineEventType.STT_END:
                    text = ((event.data or {}).get("stt_output") or {}).get("text")
                    if (
                        turn.command_started
                        and not turn.error
                        and isinstance(text, str)
                        and text.strip()
                    ):
                        self._show(
                            self.display.async_enter_thinking(turn.context.id),
                            "thinking",
                        )
                    else:
                        self.display.end_candidate(turn.context.id)
                        self._show(
                            self.display.async_clear_intent(
                                DisplayState.WAKE_CONFIRMED, generation=turn.context.id
                            ),
                            "empty STT",
                        )
            case PipelineEventType.ERROR:
                turn.error = True
                self._show(self.display.async_end_generation(turn.context.id), "error")

    @callback
    def on_playback(self, playback_id: str, state: str) -> None:
        """Use the matching physical playback terminal state."""
        turn = self._turn
        if turn is None or turn.tts.playback_id != playback_id or self._followup:
            return
        if state == "playing":
            self._show(
                self.display.async_set_intent(
                    DisplayState.SPEAKING,
                    build_expression_command("music"),
                    generation=turn.context.id,
                ),
                "speaking",
            )
        elif state == "completed":
            turn.playback_completed = True
            self._open_followup()
        elif state in ("stopped", "interrupted", "failed"):
            self._show(
                self.display.async_clear_intent(
                    DisplayState.SPEAKING, generation=turn.context.id
                ),
                "playback stopped",
            )
            self._arm(0, "playback_failed")

    def _open_followup(self) -> None:
        if self._turn is not None:
            self._stop_watcher(self._turn)
        self.entity.tts_response_finished()
        self._followup = True
        if self._turn is not None:
            self._show(
                self.display.async_enter_followup(self._turn.context.id),
                "followup wait",
            )
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
            self._show(
                self.display.async_end_generation(turn.context.id), "session end"
            )
            tasks = {turn.task, self._stop_watcher(turn)}
            event_turn = self._event_turn
            if event_turn is not None and not event_turn.interrupted:
                tasks.add(event_turn.task)
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
        display: ExpressionCoordinator,
    ) -> None:
        self._attr_unique_id = entry_id
        self._attr_tts_options = {
            "preferred_format": "mp3",
            "preferred_sample_rate": 32000,
            "preferred_sample_channels": 1,
        }
        self.adapter = adapter
        self.display = display
        self.coordinator = AudioSessionCoordinator(self, ingress, display)

    async def async_added_to_hass(self) -> None:
        """Bind transport callbacks after the entity is ready."""
        self.adapter.register_playback_handler(self.coordinator.on_playback)
        self.coordinator.ingress.on_activity = self.coordinator.on_activity
        self.coordinator.ingress.on_end = self.coordinator.on_end

    @callback
    def wake_word_provider(
        self,
        pipeline_id: str | None,
    ) -> tuple[wake_word.WakeWordDetectionEntity, str] | None:
        """Use the same pipeline selection and wake engine as HA Assist."""
        pipeline = async_get_pipeline(self.hass, pipeline_id)
        entity_id = pipeline.wake_word_entity or wake_word.async_default_entity(
            self.hass
        )
        if (
            entity_id is not None
            and (
                provider := wake_word.async_get_wake_word_detection_entity(
                    self.hass, entity_id
                )
            )
            is not None
        ):
            return provider, pipeline.wake_word_id or _WAKE_WORD_ID
        _LOGGER.warning("No wake word entity for Tivoo side detection")
        return None

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
