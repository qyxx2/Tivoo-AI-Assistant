"""P6.7 local ready-prompt playback owner."""

import asyncio
import json
import logging
import random
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .diagnostics import TYPE_AUDIO_STOP
from .transport import Esp32ConnectionAdapter

_LOGGER = logging.getLogger(__name__)

READY_PROMPT_FILENAMES = ("ready_01.mp3", "ready_02.mp3", "ready_03.mp3")
FOLLOWUP_PROMPT_FILENAMES = ("followup_01.mp3",)
PROMPT_FILENAMES = READY_PROMPT_FILENAMES + FOLLOWUP_PROMPT_FILENAMES
_READY_PHASES = frozenset({"ready", "wake", "confirmed"})
_TERMINAL_STATES = frozenset({"completed", "stopped", "failed"})


def _filenames_for_phase(phase: str) -> tuple[str, ...]:
    if phase in _READY_PHASES:
        return READY_PROMPT_FILENAMES
    if phase == "followup":
        return FOLLOWUP_PROMPT_FILENAMES
    raise ValueError(f"unsupported prompt phase: {phase}")


def build_internal_prompt_url(hass: HomeAssistant, filename: str) -> str:
    """Build the LAN-only HA /local URL for one fixed prompt asset."""
    if filename not in PROMPT_FILENAMES:
        raise HomeAssistantError("Prompt asset must be one of the fixed prompt files")

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
            "No internal Home Assistant URL is available for the ESP32 prompt"
        ) from err

    base = urlsplit(base_url)
    if base.scheme not in {"http", "https"} or not base.netloc:
        raise HomeAssistantError(
            "Home Assistant did not provide a usable internal URL for the ESP32"
        )
    return f"{base_url.rstrip('/')}/local/tivoo/prompts/{filename}"


@dataclass(slots=True)
class _PromptPlayback:
    generation: str
    playback_id: str
    released: asyncio.Event
    stop_sent: bool = False


class PromptSoundPlayer:
    """Own ready-prompt selection, IDs and the shared physical playback slot."""

    def __init__(
        self,
        hass: HomeAssistant,
        adapter: Esp32ConnectionAdapter,
        *,
        release_timeout: float = 1.0,
    ) -> None:
        self._hass = hass
        self._adapter = adapter
        self._release_timeout = release_timeout
        self._lock = asyncio.Lock()
        self._generation: str | None = None
        self._active: _PromptPlayback | None = None
        self._tts_playback_id: str | None = None
        self._last_filename: str | None = None
        self._owned_ids: deque[str] = deque(maxlen=32)

    @property
    def playback_id(self) -> str | None:
        """Return the currently active prompt playback ID."""
        active = self._active
        return active.playback_id if active is not None else None

    def _available_assets(self, phase: str) -> list[str]:
        root = Path(self._hass.config.path("www", "tivoo", "prompts"))
        available = [
            name for name in _filenames_for_phase(phase) if (root / name).is_file()
        ]
        if phase != "followup" and self._last_filename in available:
            available = [name for name in available if name != self._last_filename]
        return available

    def has_available_assets(self, phase: str) -> bool:
        """Whether this wait can play one of the installed prompt assets."""
        return bool(self._available_assets(phase))

    async def async_wait_completed(self, generation: str) -> None:
        """Wait for the short prompt, with bounded failure fallback."""
        active = self._active
        if active is None or active.generation != generation:
            return
        try:
            async with asyncio.timeout(5):
                await active.released.wait()
        except TimeoutError:
            await self.async_cancel(generation)

    async def async_request(self, generation: str, phase: str) -> bool:
        """Play at most one prompt from the phase-specific asset pool."""
        async with self._lock:
            if generation == self._generation:
                return False
            if self._active is not None:
                await self._stop_active("superseded_prompt")

            self._generation = generation
            if self._tts_playback_id is not None:
                return False

            available = self._available_assets(phase)
            if not available:
                return False
            filename = random.choice(available)
            try:
                url = build_internal_prompt_url(self._hass, filename)
            except HomeAssistantError:
                _LOGGER.debug("Skipping ready prompt because no LAN URL is available")
                return False

            playback_id = str(uuid.uuid4())
            active = _PromptPlayback(generation, playback_id, asyncio.Event())
            self._active = active
            self._owned_ids.append(playback_id)
            try:
                await self._adapter.async_send_tts_play(
                    playback_id, url, "audio/mpeg", suppress_vad=True
                )
            except HomeAssistantError:
                if self._active is active:
                    self._active = None
                active.released.set()
                _LOGGER.debug("Skipping ready prompt because playback send failed")
                return False

            self._last_filename = filename
            return True

    async def async_cancel(self, generation: str) -> bool:
        """Cancel only the prompt owned by the matching generation."""
        async with self._lock:
            if generation != self._generation:
                return False
            active = self._active
            if active is not None and active.generation == generation:
                await self._stop_active("prompt_cancelled")
            return True

    async def async_yield_to_tts(self, playback_id: str) -> None:
        """Release any prompt before reserving the physical slot for real TTS."""
        async with self._lock:
            if self._active is not None:
                await self._stop_active("tts_priority")
            self._tts_playback_id = playback_id

    def release_tts(self, playback_id: str | None) -> None:
        """Release a reservation whose transport or send has failed."""
        if playback_id == self._tts_playback_id:
            self._tts_playback_id = None

    def on_playback(self, playback_id: str, state: str) -> bool:
        """Consume prompt states and observe real-TTS terminal states."""
        if playback_id == self._tts_playback_id:
            if state in _TERMINAL_STATES:
                self._tts_playback_id = None
            return False

        if playback_id not in self._owned_ids:
            return False

        active = self._active
        if (
            active is not None
            and active.playback_id == playback_id
            and state in _TERMINAL_STATES
        ):
            self._active = None
            active.released.set()
        return True

    async def _stop_active(self, reason: str) -> None:
        active = self._active
        if active is None:
            return
        if not active.stop_sent:
            active.stop_sent = True
            payload = json.dumps(
                {
                    "request_id": str(uuid.uuid4()),
                    "expected_audio_id": active.playback_id,
                    "reason": reason,
                },
                separators=(",", ":"),
            ).encode("utf-8")
            try:
                await self._adapter.async_send_message(TYPE_AUDIO_STOP, payload)
            except HomeAssistantError:
                if self._active is active:
                    self._active = None
                active.released.set()
                _LOGGER.debug("Ready-prompt stop could not be sent")
                return

        try:
            async with asyncio.timeout(self._release_timeout):
                await active.released.wait()
        except TimeoutError:
            _LOGGER.debug("Ready-prompt release timed out")
        finally:
            if self._active is active:
                self._active = None
            active.released.set()
