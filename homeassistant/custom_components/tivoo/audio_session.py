"""Bounded microphone-session buffering for the P6 transport contract."""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

from .diagnostics import MAX_MIC_PCM_PAYLOAD

_LOGGER = logging.getLogger("custom_components.tivoo.audio_session")
PCM_QUEUE_DEPTH = 16


@dataclass(eq=False, slots=True)
class _MicSession:
    session_id: str
    queue: asyncio.Queue[bytes] = field(
        default_factory=lambda: asyncio.Queue(maxsize=PCM_QUEUE_DEPTH)
    )
    ended: asyncio.Event = field(default_factory=asyncio.Event)
    data_ready: asyncio.Event = field(default_factory=asyncio.Event)
    iterator_claimed: bool = False


StopSender = Callable[[str, str], Awaitable[None]]
InterruptedHandler = Callable[[dict], Awaitable[None]]


def _require_uuid(payload: dict, field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a UUID string")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as err:
        raise ValueError(f"{field_name} must be a UUID") from err
    if len(value) != 36 or str(parsed) != value.lower():
        raise ValueError(f"{field_name} must be a canonical UUID")
    return value


class AudioSessionManager:
    """Keep one active MIC session and at most 16 unconsumed PCM chunks."""

    def __init__(self, stop_sender: StopSender | None = None) -> None:
        self._stop_sender = stop_sender
        self._active_session: _MicSession | None = None
        self._iterators: set[_MicSession] = set()
        self._interrupted_handler: InterruptedHandler | None = None
        self._shutdown = False

    @property
    def active_session_id(self) -> str | None:
        """Return the currently receiving session ID, if any."""
        if self._active_session is None:
            return None
        return self._active_session.session_id

    @property
    def queue_size(self) -> int:
        """Return the queued chunk count for the active session."""
        if self._active_session is None:
            return 0
        return self._active_session.queue.qsize()

    async def async_start_session(self, payload: dict) -> None:
        """Validate and create the only active network microphone session."""
        if self._shutdown:
            raise ValueError("audio session manager is shut down")
        if not isinstance(payload, dict):
            raise TypeError("MIC_SESSION_START payload must be an object")

        session_id = _require_uuid(payload, "session_id")
        sample_rate = payload.get("sample_rate")
        channels = payload.get("channels")
        frame_duration_ms = payload.get("frame_duration_ms")
        if (
            type(sample_rate) is not int
            or sample_rate != 16000
            or type(channels) is not int
            or channels != 1
            or payload.get("sample_format") != "s16le"
            or type(frame_duration_ms) is not int
            or frame_duration_ms != 20
        ):
            raise ValueError("unsupported MIC session audio format")

        preroll_ms = payload.get("preroll_ms")
        if (
            not isinstance(preroll_ms, int)
            or isinstance(preroll_ms, bool)
            or preroll_ms < 0
        ):
            raise ValueError("preroll_ms must be a non-negative integer")

        trigger_source = payload.get("trigger_source")
        if trigger_source not in {"idle_vad", "barge_in"}:
            raise ValueError("unsupported MIC session trigger_source")
        if trigger_source == "barge_in":
            _require_uuid(payload, "interrupt_id")

        if self._active_session is not None:
            raise ValueError("a microphone session is already active")
        if any(not session.queue.empty() for session in self._iterators):
            raise ValueError("previous microphone session PCM is still draining")
        if any(session.session_id == session_id for session in self._iterators):
            raise ValueError("microphone session_id has already been used")

        self._active_session = _MicSession(session_id)

    async def async_push_pcm(self, session_id: str, data: bytes) -> None:
        """Queue one opaque binary PCM chunk for the matching active session."""
        _require_uuid({"session_id": session_id}, "session_id")
        if not isinstance(data, bytes):
            raise TypeError("MIC_PCM data must be bytes")
        if not data or len(data) % 2:
            raise ValueError("MIC_PCM data must contain complete S16LE samples")
        if len(data) > MAX_MIC_PCM_PAYLOAD:
            raise ValueError("MIC_PCM payload exceeds the 4 KiB protocol limit")

        session = self._active_session
        if session is None or session.session_id != session_id:
            return

        try:
            session.queue.put_nowait(data)
            session.data_ready.set()
        except asyncio.QueueFull:
            _LOGGER.warning("MIC session queue full; stopping session %s", session_id)
            await self._finish_session(
                session, "queue_full", notify_device=True, clear=True
            )

    async def async_end_session(self, session_id: str, reason: str) -> None:
        """End a matching session while allowing its queued PCM to drain."""
        _require_uuid({"session_id": session_id}, "session_id")
        if not isinstance(reason, str) or not reason or len(reason) > 64:
            raise ValueError(
                "reason must be a non-empty string of at most 64 characters"
            )
        session = self._active_session
        if session is None or session.session_id != session_id:
            return
        await self._finish_session(session, reason, notify_device=False, clear=False)

    async def async_stop_session(self, session_id: str, reason: str) -> None:
        """Stop only the matching upload session and notify the ESP32."""
        _require_uuid({"session_id": session_id}, "session_id")
        if not isinstance(reason, str) or not reason or len(reason) > 64:
            raise ValueError(
                "reason must be a non-empty string of at most 64 characters"
            )
        session = self._active_session
        if session is None or session.session_id != session_id:
            return
        await self._finish_session(session, reason, notify_device=True, clear=True)

    def async_audio_iterator(self, session_id: str) -> AsyncIterator[bytes]:
        """Return the single ordered PCM iterator for an active session."""
        session = self._active_session
        if session is None or session.session_id != session_id:
            raise ValueError("microphone session is not active")
        if session.iterator_claimed:
            raise ValueError("microphone session already has an audio iterator")
        session.iterator_claimed = True
        self._iterators.add(session)
        return self._iterate_session(session)

    async def async_shutdown(self) -> None:
        """Close active and already-created iterators during config-entry unload."""
        self._shutdown = True
        session = self._active_session
        if session is not None:
            await self._finish_session(
                session, "ha_unload", notify_device=True, clear=True
            )
        for iterator_session in tuple(self._iterators):
            while not iterator_session.queue.empty():
                try:
                    iterator_session.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            iterator_session.ended.set()
            iterator_session.data_ready.set()

    def register_audio_interrupted_handler(self, handler: InterruptedHandler) -> None:
        """Register the future P7/P8 owner for validated interruption events."""
        if not callable(handler):
            raise TypeError("handler must be callable")
        self._interrupted_handler = handler

    async def async_handle_audio_interrupted(self, payload: dict) -> None:
        """Validate AUDIO_INTERRUPTED and pass it to the registered owner."""
        if not isinstance(payload, dict):
            raise TypeError("AUDIO_INTERRUPTED payload must be an object")
        _require_uuid(payload, "interrupt_id")
        _require_uuid(payload, "audio_id")
        for name in ("source", "reason"):
            value = payload.get(name)
            if not isinstance(value, str) or not value or len(value) > 64:
                raise ValueError(f"{name} must be a non-empty string")
        if self._interrupted_handler is not None:
            await self._interrupted_handler(dict(payload))

    async def _finish_session(
        self,
        session: _MicSession,
        reason: str,
        *,
        notify_device: bool,
        clear: bool,
    ) -> None:
        if self._active_session is session:
            self._active_session = None
        if clear:
            while not session.queue.empty():
                try:
                    session.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
        session.ended.set()
        session.data_ready.set()

        if notify_device and self._stop_sender is not None:
            try:
                await self._stop_sender(session.session_id, reason)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — local session cleanup must still finish.
                _LOGGER.warning(
                    "Unable to send MIC_CAPTURE_STOP for session %s", session.session_id
                )

    async def _iterate_session(self, session: _MicSession) -> AsyncIterator[bytes]:
        try:
            while True:
                try:
                    chunk = session.queue.get_nowait()
                except asyncio.QueueEmpty:
                    if session.ended.is_set():
                        return
                    session.data_ready.clear()
                    if not session.queue.empty():
                        session.data_ready.set()
                        continue
                    if session.ended.is_set():
                        return
                    await session.data_ready.wait()
                    continue
                yield chunk
        finally:
            self._iterators.discard(session)
