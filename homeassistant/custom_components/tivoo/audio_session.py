"""Bounded microphone ingress and PCM subscriptions."""

import asyncio
import logging
import uuid
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field

from .diagnostics import MAX_MIC_PCM_PAYLOAD

_LOGGER = logging.getLogger("custom_components.tivoo.audio_session")
PCM_QUEUE_DEPTH = 16
PREROLL_BYTES = 32_000
HANDOFF_BYTES = 480_000
STOP_SEND_TIMEOUT = 5  # Existing lifecycle stop-send budget.


@dataclass(eq=False, slots=True)
class _MicSession:
    session_id: str
    queue: asyncio.Queue[bytes] = field(
        default_factory=lambda: asyncio.Queue(maxsize=PCM_QUEUE_DEPTH)
    )
    ended: asyncio.Event = field(default_factory=asyncio.Event)
    data_ready: asyncio.Event = field(default_factory=asyncio.Event)
    persistent: bool = False
    history: deque[tuple[int, bytes]] = field(default_factory=deque)
    tail: int = 0
    cursors: dict[object, int] = field(default_factory=dict)
    local_mode: bool = False
    wake_uptime: int = 0
    followup: bool = False
    gate_uptime: int | None = None
    gate_result: str | None = None
    speech_uptime: int | None = None
    end_uptime: int | None = None
    ready: bool = False
    input_finished: bool = False
    input_drained: bool = False
    aborted: bool = False


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
    """Manage one upload with a bounded history or the legacy P6 queue."""

    def __init__(self, stop_sender: StopSender | None = None) -> None:
        self._stop_sender = stop_sender
        self._rejected_stops: set[asyncio.Task] = set()
        self._active_session: _MicSession | None = None
        self._iterators: set[_MicSession] = set()
        self._interrupted_handler: InterruptedHandler | None = None
        self._shutdown = False
        self.overflow_count = 0
        self._local_seen: set[str] = set()
        self._local_uptime = -1
        self._followup_grant: str | None = None
        self.on_local_start: Callable[[str, str | None], None] | None = None
        self.on_gate: Callable[[str], None] | None = None
        self.on_activity: Callable[[str, str], None] | None = None
        self.on_end: Callable[[str, str], None] | None = None

    def grant_followup(self, session_id: str) -> bool:
        session = self._active_session
        if (session is None or session.session_id != session_id or not session.local_mode
            or not session.input_finished or self._followup_grant is not None):
            return False
        self._followup_grant = session_id
        return True

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
        if self._active_session.persistent:
            return len(self._active_session.history)
        return self._active_session.queue.qsize()

    async def async_start_session(
        self, payload: dict, *, persistent: bool = False, local_mode: bool = False
    ) -> None:
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
        if local_mode:
            phrase = payload.get("wake_word_phrase")
            uptime = payload.get("uptime_ms")
            followup = trigger_source == "local_followup"
            if (
                trigger_source not in {"local_wake", "local_followup"} or not persistent or preroll_ms != 0
                or type(uptime) is not int or uptime < 0
                or (not followup and (not isinstance(phrase, str) or not phrase.strip() or len(phrase) > 128))
                or (followup and "wake_word_phrase" in payload)
            ):
                raise ValueError("invalid local wake start")
            if session_id in self._local_seen:
                return
            if followup:
                parent = _require_uuid(payload, "parent_session_id")
                if parent != self._followup_grant or parent != self.active_session_id:
                    # A rejected UUID never owns ingress. Its best-effort stop
                    # must not wait for the diagnostic writer in the RX task.
                    self._local_seen.add(session_id)
                    if self._stop_sender is not None:
                        task = asyncio.create_task(self._send_stop(session_id, "invalid_followup"))
                        self._rejected_stops.add(task)
                        task.add_done_callback(self._rejected_stops.discard)
                    return
            if uptime <= self._local_uptime:
                return
            self._followup_grant = None
            if self._active_session is not None:
                await self._finish_session(self._active_session, "followup" if followup else "superseded",
                                           notify_device=False, clear=True)
            self._local_seen.add(session_id)
            self._local_uptime = uptime
            self._active_session = _MicSession(
                session_id, persistent=True, local_mode=True, wake_uptime=uptime, followup=followup,
            )
            if self.on_local_start is not None:
                self.on_local_start(session_id, phrase)
            return
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

        self._active_session = _MicSession(session_id, persistent=persistent)

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

        if session.local_mode and (
            len(data) % 640 != 0 or not session.ready or session.gate_uptime is None
            or session.speech_uptime is None or session.input_finished
        ):
            await self.async_stop_session(session_id, "invalid_local_pcm")
            return
        if session.persistent:
            await self._push_ingress(session, data)
            return

        try:
            session.queue.put_nowait(data)
            session.data_ready.set()
        except asyncio.QueueFull:
            self.overflow_count += 1
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
        await self._finish_session(session, reason, notify_device=False, clear=session.local_mode)

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
        if session in self._iterators:
            raise ValueError("microphone session already has an audio iterator")
        if session.persistent:
            raise ValueError("persistent MIC requires an audio subscription")
        self._iterators.add(session)
        return self._iterate_session(session)

    def _ingress(self, session_id: str) -> _MicSession:
        session = self._active_session
        if (
            session is None
            or session.session_id != session_id
            or not session.persistent
        ):
            raise ValueError("persistent microphone session is not active")
        return session

    def ingress_offset(self, session_id: str) -> int:
        """Return the next PCM byte offset on the local ingress timeline."""
        return self._ingress(session_id).tail

    def is_local_session(self, session_id: str) -> bool:
        session = self._active_session
        return bool(session and session.session_id == session_id and session.local_mode)

    def local_input_finished(self, session_id: str) -> bool:
        session = self._active_session
        return bool(session and session.session_id == session_id and session.local_mode and session.input_finished)

    def local_input_drained(self, session_id: str) -> bool:
        """True only after the matching local consumer exhausted the PCM stream."""
        session = self._active_session
        return bool(session and session.session_id == session_id and session.local_mode
                    and session.input_drained and not session.aborted)

    async def async_handle_gate(self, payload: dict) -> None:
        session_id = _require_uuid(payload, "session_id")
        session = self._active_session
        if session is None or session.session_id != session_id or not session.local_mode:
            return
        uptime = payload.get("uptime_ms")
        if (
            type(uptime) is not int or not session.wake_uptime <= uptime <= session.wake_uptime + 5000
            or payload.get("prompt_result") not in ("completed", "skipped", "failed")
        ):
            await self.async_stop_session(session_id, "invalid_command_gate")
            return
        if session.gate_uptime is not None:
            if (uptime, payload["prompt_result"]) != (session.gate_uptime, session.gate_result):
                await self.async_stop_session(session_id, "invalid_command_gate")
            return
        session.gate_uptime = uptime
        session.gate_result = payload["prompt_result"]
        if self.on_gate is not None:
            self.on_gate(session_id)

    async def async_handle_activity(self, payload: dict) -> None:
        """Validate and route speech transitions on the matching ingress."""
        session_id = _require_uuid(payload, "session_id")
        session = self._active_session
        if session is None or session.session_id != session_id:
            return
        state = payload.get("state")
        uptime_ms = payload.get("uptime_ms")
        if state not in ("speech_start", "speech_end") or type(uptime_ms) is not int or uptime_ms < 0:
            if session.local_mode:
                await self.async_stop_session(session_id, "invalid_local_activity")
                return
            raise ValueError("invalid MIC_ACTIVITY state or uptime_ms")
        if session.local_mode:
            if state == "speech_start" and session.speech_uptime is not None:
                if uptime_ms != session.speech_uptime:
                    await self.async_stop_session(session_id, "invalid_local_start_time")
                return
            if state == "speech_end" and session.input_finished:
                count = payload.get("pcm_samples")
                if uptime_ms != session.end_uptime or type(count) is not int or count * 2 != session.tail:
                    await self.async_stop_session(session_id, "invalid_local_endpoint")
                return
            if not session.ready or session.gate_uptime is None:
                await self.async_stop_session(session_id, "invalid_local_activity")
                return
            if state == "speech_start":
                if not session.gate_uptime <= uptime_ms <= session.gate_uptime + (4000 if session.followup else 3000):
                    await self.async_stop_session(session_id, "invalid_local_start_time")
                    return
                session.speech_uptime = uptime_ms
            else:
                count = payload.get("pcm_samples")
                if (
                    session.speech_uptime is None
                    or not session.speech_uptime <= uptime_ms <= session.speech_uptime + 15000
                    or type(count) is not int or count <= 0 or count * 2 != session.tail
                ):
                    await self.async_stop_session(session_id, "invalid_local_endpoint")
                    return
                session.end_uptime = uptime_ms
                session.input_finished = True
                session.data_ready.set()
        if (
            session is not None
            and session.persistent
            and session.session_id == session_id
            and self.on_activity is not None
        ):
            self.on_activity(session_id, state)

    async def async_disconnect(self) -> None:
        """Release the upload owned by the disconnected diagnostic socket."""
        self._cancel_rejected_stops()
        self._local_seen.clear()
        self._local_uptime = -1
        self._followup_grant = None
        if (session := self._active_session) is not None:
            await self._finish_session(
                session, "disconnected", notify_device=False, clear=True
            )

    async def _push_ingress(self, session: _MicSession, data: bytes) -> None:
        new_tail = session.tail + len(data)
        if (
            new_tail - min(session.cursors.values(), default=0 if session.local_mode else session.tail)
            > HANDOFF_BYTES
        ):
            self.overflow_count += 1
            _LOGGER.warning(
                "MIC ingress overflow; stopping session %s", session.session_id
            )
            await self._finish_session(
                session, "handoff_overflow", notify_device=True, clear=True
            )
            return
        session.history.append((session.tail, data))
        session.tail = new_tail
        self._trim_ingress(session)
        session.data_ready.set()

    @staticmethod
    def _trim_ingress(session: _MicSession) -> None:
        # Retain the full bounded window for delayed Detection. A pinned
        # subscription explicitly fails before unread data can be evicted.
        cutoff = max(0, session.tail - HANDOFF_BYTES)
        while session.history:
            offset, data = session.history[0]
            if offset >= cutoff:
                break
            session.history.popleft()
            if offset + len(data) > cutoff:
                session.history.appendleft((cutoff, data[cutoff - offset :]))

    @staticmethod
    def handoff_start(detection_offset: int) -> int:
        """Return the ingress offset one second before the detection chunk."""
        return max(0, detection_offset - PREROLL_BYTES)

    def handoff(
        self, session_id: str, detection_offset: int
    ) -> AbstractAsyncContextManager[AsyncIterator[bytes]]:
        """Pin pre-roll and subsequent PCM at its ingress offsets."""
        session = self._ingress(session_id)
        if not 0 <= detection_offset <= session.tail or detection_offset % 2:
            raise ValueError("invalid MIC detection offset")
        return self.audio_subscription(
            session_id, start=self.handoff_start(detection_offset)
        )

    @asynccontextmanager
    async def audio_subscription(
        self,
        session_id: str,
        *,
        start: int | None = None,
        consumer: object | None = None,
        on_pull: Callable[[], Awaitable[None]] | None = None,
        on_eof: Callable[[], None] | None = None,
    ) -> AsyncIterator[AsyncIterator[bytes]]:
        """Open an independently closable PCM cursor."""
        session = self._ingress(session_id)
        offset = session.tail if start is None else start
        if (
            not max(0, session.tail - HANDOFF_BYTES) <= offset <= session.tail
            or offset % 2
        ):
            raise ValueError("MIC ingress offset outside the retained window")
        cursor = object() if consumer is None else consumer
        session.cursors[cursor] = offset
        stream = self._iterate_ingress(session, cursor, on_pull, on_eof)
        try:
            yield stream
        finally:
            await stream.aclose()
            session.cursors.pop(cursor, None)

    def release_subscription(self, session_id: str, consumer: object) -> None:
        """Stop retaining unread PCM once the consumer leaves its audio stage."""
        session = self._active_session
        if session is not None and session.session_id == session_id:
            session.cursors.pop(consumer, None)
            session.data_ready.set()

    @staticmethod
    async def _iterate_ingress(
        session: _MicSession, cursor: object,
        on_pull: Callable[[], Awaitable[None]] | None,
        on_eof: Callable[[], None] | None,
    ) -> AsyncIterator[bytes]:
        if session.local_mode:
            if session.aborted or on_pull is None or session.ready:
                raise RuntimeError("local microphone input aborted or duplicate consumer")
            session.ready = True
            await on_pull()
        while cursor in session.cursors:
            if session.aborted:
                raise RuntimeError("local microphone input aborted")
            offset = session.cursors[cursor]
            for start, data in session.history:
                if start + len(data) > offset:
                    session.cursors[cursor] = start + len(data)
                    yield data[offset - start :]
                    break
            else:
                if session.input_finished or session.ended.is_set():
                    if session.local_mode and session.input_finished and offset == session.tail:
                        # Only the natural exhaustion path counts. Receiving
                        # speech_end or closing a partially read cursor does not.
                        session.input_drained = True
                        if on_eof is not None:
                            on_eof()
                    return
                session.data_ready.clear()
                await session.data_ready.wait()

    async def async_shutdown(self) -> None:
        """Close active and already-created iterators during config-entry unload."""
        self._shutdown = True
        self._cancel_rejected_stops()
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
            self._followup_grant = None
        if session.local_mode:
            session.aborted = True
        if clear:
            session.history.clear()
            while not session.queue.empty():
                try:
                    session.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
        session.ended.set()
        session.data_ready.set()
        if session.persistent and self.on_end is not None:
            self.on_end(session.session_id, reason)

        if notify_device:
            await self._send_stop(session.session_id, reason)

    def _cancel_rejected_stops(self) -> None:
        for task in self._rejected_stops:
            task.cancel()

    async def _send_stop(self, session_id: str, reason: str) -> None:
        if self._stop_sender is None:
            return
        try:
            async with asyncio.timeout(STOP_SEND_TIMEOUT):
                await self._stop_sender(session_id, reason)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — cleanup is independent of notification.
            _LOGGER.warning("Unable to send MIC_CAPTURE_STOP for session %s", session_id)

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
