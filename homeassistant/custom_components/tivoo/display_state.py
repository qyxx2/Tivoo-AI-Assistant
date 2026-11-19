"""P6.6 display intent arbitration, independent of HA service/transport wiring."""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from homeassistant.exceptions import HomeAssistantError

from .commands import TivooCommand
from .const import MOOD_PRESETS

_LOGGER = logging.getLogger(__name__)

IDLE_PRESETS = ("standby", "smiley", "sleepy", "sun", "fish")
IDLE_MIN_SECONDS = 30.0
IDLE_MAX_SECONDS = 90.0
CANDIDATE_HOLD_SECONDS = 0.7
CANDIDATE_PROBABILITY = 0.35
CANDIDATE_COOLDOWN_SECONDS = 10.0
MOOD_TTL_SECONDS = 5.0


class DisplayState(str, Enum):
    """Descending display precedence (declaration order is meaningful)."""

    WAKE_CONFIRMED = "wake_confirmed"
    SPEAKING = "speaking"
    TOOLUSE = "tooluse"
    THINKING = "thinking"
    ACTIVE_LISTENING = "active_listening"
    EXPLICIT_CONTENT = "explicit_content"
    AI_MOOD = "ai_mood"
    FOLLOWUP_WAIT = "followup_wait"
    IDLE = "idle"


SESSION_STATES = frozenset(DisplayState) - {
    DisplayState.EXPLICIT_CONTENT,
    DisplayState.IDLE,
}


class CommandAdapter(Protocol):
    async def async_execute(self, command: TivooCommand) -> None: ...


def build_expression_command(name: str) -> TivooCommand:
    """Build exactly the existing set_expression payload from the preset registry."""
    # Late import avoids a cycle when services imports this module in P6.6b1.
    from .services import PRESET_REGISTRY

    description, factory = PRESET_REGISTRY[name]
    frames, delays = factory()
    return TivooCommand(
        name="set_expression",
        data={
            "name": name,
            "description": description,
            "frames": frames,
            "delays": delays,
        },
    )


@dataclass(slots=True, eq=False)
class _Intent:
    command: TivooCommand
    generation: str | None
    expiry: asyncio.TimerHandle | None = None


class ScreenPowerGate:
    """Owner-based display inhibition with independently expiring temporary wakes."""

    def __init__(self, on_change: Callable[[bool], Awaitable[None]]) -> None:
        self._on_change = on_change
        self._inhibits: set[str] = set()
        self._wake_handles: dict[str, asyncio.TimerHandle] = {}
        self._shutdown = False

    @property
    def is_on(self) -> bool:
        return not self._inhibits or bool(self._wake_handles)

    @property
    def inhibit_owners(self) -> frozenset[str]:
        return frozenset(self._inhibits)

    async def async_acquire(self, owner: str) -> None:
        if self._shutdown or owner in self._inhibits:
            return
        was_on = self.is_on
        self._inhibits.add(owner)
        if was_on != self.is_on:
            await self._on_change(self.is_on)

    async def async_release(self, owner: str) -> None:
        if self._shutdown or owner not in self._inhibits:
            return
        was_on = self.is_on
        self._inhibits.remove(owner)
        if was_on != self.is_on:
            await self._on_change(self.is_on)

    async def async_temporary_wake(self, owner: str, ttl: float) -> None:
        if self._shutdown:
            return
        was_on = self.is_on
        old = self._wake_handles.pop(owner, None)
        if old is not None:
            old.cancel()
        loop = asyncio.get_running_loop()
        handle = loop.call_later(
            max(0.0, ttl),
            lambda: asyncio.create_task(self._async_expire_wake(owner, handle)),
        )
        self._wake_handles[owner] = handle
        if was_on != self.is_on:
            await self._on_change(self.is_on)

    async def _async_expire_wake(self, owner: str, handle: asyncio.TimerHandle) -> None:
        if self._shutdown or self._wake_handles.get(owner) is not handle:
            return
        was_on = self.is_on
        self._wake_handles.pop(owner)
        if was_on != self.is_on:
            await self._on_change(self.is_on)

    async def async_shutdown(self) -> None:
        self._shutdown = True
        for handle in self._wake_handles.values():
            handle.cancel()
        self._wake_handles.clear()


class ExpressionCoordinator:
    """Choose the highest valid intent and emit only necessary device commands."""

    def __init__(self, command_adapter: CommandAdapter, *, spp_connected: bool = True) -> None:
        self._adapter = command_adapter
        self._gate = ScreenPowerGate(self._async_power_changed)
        self._intents: dict[DisplayState, _Intent] = {}
        self._idle_command: TivooCommand | None = None
        self._idle_timer: asyncio.TimerHandle | None = None
        self._candidate_timer: asyncio.TimerHandle | None = None
        self._candidate_generation: str | None = None
        self._candidate_cooldown_until = 0.0
        self._lock = asyncio.Lock()
        self._power_dirty = False
        self._spp_connected = spp_connected
        self._spp_revision = 0
        self._started = False
        self._shutdown = False
        self._active_generation: str | None = None
        self._voice_contexts: set[str] = set()
        self._reply_active = False
        self._mood_during_speech = False
        self._speaking_mood: TivooCommand | None = None
        self._desired_state: DisplayState = DisplayState.IDLE
        self._desired_command: TivooCommand | None = None
        self._last_sent: TivooCommand | None = None

    @property
    def active_generation(self) -> str | None:
        return self._active_generation

    @property
    def desired_state(self) -> DisplayState:
        return self._desired_state

    @property
    def desired_command(self) -> TivooCommand | None:
        return self._desired_command

    @property
    def last_sent(self) -> TivooCommand | None:
        """Last successfully transported display command, not verified physical pixels."""
        return self._last_sent

    async def async_start(self) -> None:
        if self._started or self._shutdown:
            return
        self._started = True
        self._idle_command = build_expression_command(random.choice(IDLE_PRESETS))
        await self._async_recompute()

    async def async_shutdown(self) -> None:
        self._shutdown = True
        self._cancel_idle_timer()
        self._cancel_candidate()
        for state in tuple(self._intents):
            self._remove_intent(state)
        self._active_generation = None
        self._speaking_mood = None
        await self._gate.async_shutdown()

    def begin_generation(
        self, generation: str, *, reply_active: bool = True, wake: bool = False,
        mood_during_speech: bool = False,
    ) -> None:
        """Set a new turn as authoritative; a late event from an old turn is inert."""
        if self._shutdown or generation == self._active_generation:
            return
        self._cancel_candidate()
        self._active_generation = generation
        self._voice_contexts.add(generation)
        self._reply_active = reply_active
        self._mood_during_speech = mood_during_speech
        self._clear_session_intents()
        if wake:
            self._intents[DisplayState.WAKE_CONFIRMED] = _Intent(
                build_expression_command("question"), generation
            )
        self._schedule_recompute()

    def _schedule_recompute(self) -> None:
        if self._started and not self._shutdown:
            task = asyncio.create_task(self._async_recompute())
            task.add_done_callback(self._log_background_failure)

    def update_voice(
        self,
        generation: str,
        *,
        clear: tuple[DisplayState, ...] = (),
        state: DisplayState | None = None,
        preset: str | None = None,
        reply_active: bool | None = None,
    ) -> None:
        """Apply one physical voice transition before any asynchronous display I/O."""
        if self._shutdown or generation != self._active_generation:
            return
        for old in clear:
            self._remove_intent(old)
        if reply_active is not None:
            self._reply_active = reply_active
            if not reply_active:
                self._speaking_mood = None
        if state is not None:
            assert state in SESSION_STATES and preset is not None
            self._remove_intent(state)
            self._intents[state] = _Intent(build_expression_command(preset), generation)
        self._schedule_recompute()

    def end_generation(self, generation: str) -> None:
        """Invalidate local voice identity synchronously at the ingress boundary."""
        if self._invalidate_generation(generation):
            self._schedule_recompute()

    @staticmethod
    def _log_background_failure(task: asyncio.Task) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            _LOGGER.warning("Tivoo background display recompute failed: %s", error)

    def _invalidate_generation(self, generation: str) -> bool:
        if generation != self._active_generation or self._shutdown:
            return False
        self._cancel_candidate()
        self._active_generation = None
        self._reply_active = False
        self._clear_session_intents()
        return True

    async def async_end_generation(self, generation: str) -> None:
        if self._invalidate_generation(generation):
            await self._async_recompute()

    def _cancel_candidate(self) -> None:
        if self._candidate_timer is not None:
            self._candidate_timer.cancel()
            self._candidate_timer = None
        self._candidate_generation = None

    def begin_candidate(self, generation: str) -> None:
        """A first wake-word candidate earns a display chance after sustained speech."""
        if self._shutdown or generation != self._active_generation:
            return
        self._cancel_candidate()
        self._candidate_generation = generation
        loop = asyncio.get_running_loop()
        if loop.time() < self._candidate_cooldown_until:
            return
        self._candidate_timer = loop.call_later(
            CANDIDATE_HOLD_SECONDS, self._activate_candidate, generation
        )

    def _activate_candidate(self, generation: str) -> None:
        self._candidate_timer = None
        if (
            self._shutdown
            or generation != self._active_generation
            or generation != self._candidate_generation
        ):
            return
        loop = asyncio.get_running_loop()
        if (
            loop.time() < self._candidate_cooldown_until
            or random.random() >= CANDIDATE_PROBABILITY
        ):
            return
        self._candidate_cooldown_until = loop.time() + CANDIDATE_COOLDOWN_SECONDS
        task = asyncio.create_task(
            self.async_set_intent(
                DisplayState.ACTIVE_LISTENING,
                build_expression_command("standby"),
                generation=generation,
            )
        )
        task.add_done_callback(self._log_background_failure)

    def end_candidate(self, generation: str) -> None:
        """Speech end or wake confirmation cancels only the matching candidate."""
        if generation != self._active_generation:
            return
        if self._candidate_generation == generation:
            self._cancel_candidate()
        task = asyncio.create_task(
            self.async_clear_intent(
                DisplayState.ACTIVE_LISTENING, generation=generation
            )
        )
        task.add_done_callback(self._log_background_failure)

    async def async_enter_thinking(self, generation: str) -> None:
        if self._shutdown or generation != self._active_generation:
            return
        for state in (
            DisplayState.WAKE_CONFIRMED,
            DisplayState.ACTIVE_LISTENING,
            DisplayState.FOLLOWUP_WAIT,
        ):
            self._remove_intent(state)
        await self.async_set_intent(
            DisplayState.THINKING,
            build_expression_command("thinking"),
            generation=generation,
        )

    async def async_enter_followup(self, generation: str) -> None:
        if self._shutdown or generation != self._active_generation:
            return
        self._cancel_candidate()
        self._clear_session_intents()
        await self.async_set_intent(
            DisplayState.FOLLOWUP_WAIT,
            build_expression_command("standby"),
            generation=generation,
        )

    async def async_set_intent(
        self,
        state: DisplayState,
        command: TivooCommand,
        *,
        generation: str | None = None,
        ttl: float | None = None,
    ) -> None:
        if self._shutdown or state is DisplayState.IDLE:
            return
        if state in SESSION_STATES:
            if self._active_generation is None or (
                generation is not None and generation != self._active_generation
            ):
                return
            generation = self._active_generation
        else:
            generation = None
        self._remove_intent(state)
        intent = _Intent(command, generation)
        self._intents[state] = intent
        if ttl is not None:
            loop = asyncio.get_running_loop()
            intent.expiry = loop.call_later(
                max(0.0, ttl),
                lambda: asyncio.create_task(self._async_expire_intent(state, intent)),
            )
        await self._async_recompute()

    async def async_clear_intent(
        self, state: DisplayState, *, generation: str | None = None
    ) -> None:
        if self._shutdown or state is DisplayState.IDLE:
            return
        if state in SESSION_STATES and (
            self._active_generation is None
            or generation is not None
            and generation != self._active_generation
        ):
            return
        if state in self._intents:
            self._remove_intent(state)
            await self._async_recompute()

    async def _async_expire_intent(self, state: DisplayState, intent: _Intent) -> None:
        # Identity and generation guards also protect against queued, cancelled callbacks.
        if self._shutdown or self._intents.get(state) is not intent:
            return
        if (
            intent.generation is not None
            and intent.generation != self._active_generation
        ):
            return
        self._remove_intent(state)
        await self._async_recompute()

    def _remove_intent(self, state: DisplayState) -> None:
        intent = self._intents.pop(state, None)
        if intent is not None and intent.expiry is not None:
            intent.expiry.cancel()

    def _clear_session_intents(self) -> None:
        self._speaking_mood = None
        for state in tuple(self._intents):
            if state in SESSION_STATES:
                self._remove_intent(state)

    async def async_acquire_screen_off(self, owner: str) -> None:
        await self._gate.async_acquire(owner)

    async def async_release_screen_off(self, owner: str) -> None:
        await self._gate.async_release(owner)

    async def async_temporary_wake(self, owner: str, ttl: float) -> None:
        await self._gate.async_temporary_wake(owner, ttl)

    async def async_set_screen_power(self, value: bool) -> None:
        """Map the original bool service to one fixed compatibility owner."""
        if not value:
            await self.async_acquire_screen_off("compatibility")
            return
        was_on = self._gate.is_on
        await self.async_release_screen_off("compatibility")
        if was_on and self._gate.is_on:
            # Explicit ON is a real screen-on request, even when already ON.
            self._power_dirty = True
            await self._async_recompute(force_display=True)

    async def async_set_mood(
        self, name: str, *, context_id: str | None = None, parent_id: str | None = None
    ) -> None:
        """Known voice contexts must match; unassociated calls use the live reply."""
        if name not in MOOD_PRESETS:
            raise HomeAssistantError(f"Unsupported Tivoo mood preset: {name}")
        generation = self._active_generation
        if generation is None or not self._reply_active:
            raise HomeAssistantError("Tivoo mood requires an active voice generation with a reply")
        for context in (context_id, parent_id):
            if context in self._voice_contexts and context != generation:
                raise HomeAssistantError("Tivoo mood belongs to an expired voice generation")
        command = build_expression_command(name)
        if self._mood_during_speech:
            # The generation owns this content until terminal/replacement.
            # It never competes as a separate display intent or blocks voice on SPP.
            self._speaking_mood = command
            if DisplayState.SPEAKING in self._intents:
                self._schedule_recompute()
            return
        await self.async_set_intent(
            DisplayState.AI_MOOD,
            command,
            generation=generation,
            ttl=MOOD_TTL_SECONDS,
        )

    async def async_set_explicit(self, command: TivooCommand) -> None:
        """Retain explicit content; repeated user requests restart the same visual."""
        repeated_visible = (
            self._desired_state is DisplayState.EXPLICIT_CONTENT
            and self._desired_command == command
            and self._last_sent == command
        )
        await self.async_set_intent(DisplayState.EXPLICIT_CONTENT, command)
        if repeated_visible and self._gate.is_on:
            await self.async_force_recompute()

    async def async_execute_screen_action(self, command: TivooCommand) -> None:
        """Do not enqueue time-sensitive device actions while the screen is off."""
        if not self._gate.is_on:
            raise HomeAssistantError(
                f"Tivoo screen is off; {command.name} was not sent"
            )
        await self._adapter.async_execute(command)
        self._last_sent = None

    async def async_on_spp_state(self, state: str) -> None:
        """React to control loss or validated diagnostic display eligibility."""
        if self._shutdown:
            return
        self._spp_revision += 1
        if state in {"spp_disconnected", "spp_unavailable"}:
            self._spp_connected = False
            self._last_sent = None
            self._cancel_idle_timer()
        elif state == "spp_connected":
            self._spp_connected = True
            self._last_sent = None
            await self.async_force_recompute()

    async def _async_power_changed(self, is_on: bool) -> None:
        self._power_dirty = True
        await self._async_recompute(force_display=is_on)

    async def async_force_recompute(self) -> None:
        """Reassert the winner when connected, or OFF while inhibited."""
        await self._async_recompute(force_display=True)

    async def _async_recompute(self, *, force_display: bool = False) -> None:
        if not self._started or self._shutdown:
            return
        async with self._lock:
            if self._shutdown:
                return
            self._update_desired()

            if not self._spp_connected:
                self._cancel_idle_timer()
                return

            if self._power_dirty or (force_display and not self._gate.is_on):
                power = self._gate.is_on
                revision = self._spp_revision
                await self._adapter.async_execute(
                    TivooCommand(name="set_screen_power", data={"value": power})
                )
                if self._shutdown or revision != self._spp_revision:
                    return
                if power != self._gate.is_on:
                    return  # A newer gate transition owns the next power write.
                self._power_dirty = False
                if power:
                    force_display = True
                self._update_desired()

            command = self._desired_command
            if (
                self._gate.is_on
                and command is not None
                and (force_display or command != self._last_sent)
            ):
                revision = self._spp_revision
                await self._adapter.async_execute(command)
                if self._shutdown or revision != self._spp_revision:
                    return
                self._last_sent = command

            if (
                self._gate.is_on
                and DisplayState.EXPLICIT_CONTENT not in self._intents
            ):
                self._ensure_idle_timer()
            else:
                self._cancel_idle_timer()

    def _update_desired(self) -> None:
        winner = next(
            (state for state in DisplayState if state in self._intents),
            DisplayState.IDLE,
        )
        self._desired_state = winner
        self._desired_command = (
            self._idle_command if winner is DisplayState.IDLE else self._intents[winner].command
        )
        if winner is DisplayState.SPEAKING and self._speaking_mood is not None:
            self._desired_command = self._speaking_mood

    def _ensure_idle_timer(self) -> None:
        if self._idle_timer is None:
            self._idle_timer = asyncio.get_running_loop().call_later(
                random.uniform(IDLE_MIN_SECONDS, IDLE_MAX_SECONDS),
                lambda: asyncio.create_task(self._async_rotate_idle()),
            )

    def _cancel_idle_timer(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

    async def _async_rotate_idle(self) -> None:
        self._idle_timer = None
        if (
            self._shutdown
            or not self._spp_connected
            or not self._gate.is_on
            or DisplayState.EXPLICIT_CONTENT in self._intents
        ):
            return
        if self._desired_state is not DisplayState.IDLE:
            self._ensure_idle_timer()
            return
        previous = self._idle_command.data["name"] if self._idle_command else None
        alternatives = tuple(name for name in IDLE_PRESETS if name != previous)
        self._idle_command = build_expression_command(random.choice(alternatives))
        await self._async_recompute()
