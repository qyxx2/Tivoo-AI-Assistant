"""GCP 7.0 voice bridge and bounded, one-use PCM delivery for local turns."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from time import monotonic
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiohttp import ClientError, WSMsgType, web
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import get_url

from .diagnostics import TYPE_AUDIO_STOP

INPUT_RATE = 16000
MAX_PCM_BYTES = 512 * 1024
GET_TIMEOUT = 10
IO_TIMEOUT = 10
EVENT_TIMEOUT = 45
TURN_TIMEOUT = 120
RETAIN_SECONDS = 5
TAIL_FRAME_SECONDS = 0.02
TERMINAL_CAPABILITY = "response.terminal-status"
_LOGGER = logging.getLogger(__name__)


class QwenPcmStream:
    """Byte-bounded queue; EOF/cancel never need a free data slot."""

    def __init__(
        self,
        stream_id: str,
        sample_rate: int,
        *,
        max_bytes: int = MAX_PCM_BYTES,
        changed: asyncio.Event | None = None,
        session_id: str | None = None,
        generation: str | None = None,
    ) -> None:
        if type(sample_rate) is not int or sample_rate not in (24000, 32000):
            raise ValueError("Unsupported Qwen PCM sample rate")
        self.stream_id = stream_id
        self.sample_rate = sample_rate
        self.max_bytes = max_bytes
        self.buffered_bytes = 0
        self._chunks = deque()
        self._ready = asyncio.Event()
        self.requested = asyncio.Event()
        self.http_finished = asyncio.Event()
        self.disconnected = False
        self.finished = False
        self.aborted = False
        self.changed = changed or asyncio.Event()
        self.handler_task: asyncio.Task | None = None
        self.session_id = session_id
        self.generation = generation
        self.response_ids: set[str] = set()

    @property
    def mime_type(self) -> str:
        return f"audio/x-tivoo-pcm-s16le-{self.sample_rate}-mono"

    def push(self, pcm: bytes) -> None:
        if self.finished or self.aborted:
            raise RuntimeError("Qwen PCM delivery is closed")
        if len(pcm) % 2:
            raise ValueError("PCM must be sample aligned")
        if self.buffered_bytes + len(pcm) > self.max_bytes:
            raise RuntimeError("Qwen PCM consumer fell behind byte limit")
        if pcm:
            self._chunks.append(pcm)
            self.buffered_bytes += len(pcm)
            self._ready.set()

    def finish(self) -> None:
        self.finished = True
        self._ready.set()

    def abort(self) -> None:
        self.aborted = True
        self._chunks.clear()
        self.buffered_bytes = 0
        self._ready.set()
        self.changed.set()

    def claim(self) -> None:
        if self.requested.is_set():
            raise RuntimeError("PCM resource already consumed")
        self.requested.set()

    async def chunks(self) -> AsyncIterator[bytes]:
        while not self.aborted:
            if self._chunks:
                chunk = self._chunks.popleft()
                self.buffered_bytes -= len(chunk)
                yield chunk
            elif self.finished:
                return
            else:
                self._ready.clear()
                await asyncio.wait_for(self._ready.wait(), IO_TIMEOUT)


class TivooQwenPcmView(HomeAssistantView):
    """The unguessable stream id is a transient single-use capability."""

    url = "/api/tivoo/qwen/audio/{stream_id}"
    name = "api:tivoo:qwen_audio"
    requires_auth = False

    def __init__(self, streams: dict[str, QwenPcmStream]) -> None:
        self._streams = streams

    async def get(self, request: web.Request, stream_id: str) -> web.StreamResponse:
        stream = self._streams.get(stream_id)
        if stream is None:
            return web.Response(status=404)
        if stream.requested.is_set():
            return web.Response(status=409)
        stream.claim()
        stream.handler_task = asyncio.current_task()
        response = web.StreamResponse(
            headers={
                "Content-Type": stream.mime_type,
                "Cache-Control": "no-store",
            }
        )
        try:
            async with asyncio.timeout(IO_TIMEOUT):
                await response.prepare(request)
            async for chunk in stream.chunks():
                async with asyncio.timeout(IO_TIMEOUT):
                    await response.write(chunk)
            if stream.aborted:
                raise ConnectionError("PCM producer aborted")
            async with asyncio.timeout(IO_TIMEOUT):
                await response.write_eof()
        except BaseException:
            stream.disconnected = True
            stream.abort()
            raise
        finally:
            stream.http_finished.set()
            stream.changed.set()
            self._streams.pop(stream_id, None)
        return response


@dataclass(frozen=True)
class QwenResult:
    transcript: str
    turn_id: str
    response_id: str
    followup_eligible: bool = True


class QwenTurnOwner:
    """One MIC/generation's delivery owner, using the existing TTS interface."""

    def __init__(
        self, bridge, session_id, generation, current, prompt_player, parent_session_id
    ):
        self.bridge = bridge
        self.session_id = session_id
        self.generation = generation
        self.current = current
        self.prompt_player = prompt_player
        self.parent_session_id = parent_session_id
        self.playback_id = None
        self.stream = None
        self.send_failed = False
        self.changed = asyncio.Event()
        self.input_drained = False
        self.playback_completed = False
        self.playback_failed = False
        self.stopped = False
        self.success = False
        # Satellite decides retention after the validated final result.
        self.keep_socket = False
        self.on_connection_lost: Callable[[], None] | None = None
        self.turn_id = None
        self.responses = {}
        self.completed_responses = set()
        self.tools = {}
        self.final_has_tools = False
        self.final_response = None
        self.transcripts = {}
        self.dispatched = False
        self._stop_sent = False
        self._close_task = None
        self.started_at = monotonic()
        self.timings: dict[str, int] = {}
        self.input_bytes = 0
        self.output_bytes = 0

    def mark(self, event: str) -> None:
        self.timings.setdefault(event, round((monotonic() - self.started_at) * 1000))

    def stop_dispatch(self):
        self.stopped = True
        self.keep_socket = False
        if self.stream:
            self.stream.abort()
        self.changed.set()

    async def async_stop_playback(self):
        self.stop_dispatch()
        if self.playback_id and not self.playback_completed and not self._stop_sent:
            self._stop_sent = True
            async with asyncio.timeout(5):
                await self.bridge.adapter.async_send_message(
                    TYPE_AUDIO_STOP,
                    json.dumps(
                        {
                            "request_id": str(uuid.uuid4()),
                            "expected_audio_id": self.playback_id,
                            "session_id": self.session_id,
                            "reason": "wake_word",
                        }
                    ).encode(),
                )

    async def async_close(self):
        if self._close_task is None:
            self._close_task = asyncio.create_task(self.bridge._close_owner(self))
        await asyncio.shield(self._close_task)


class QwenRealtimeBridge:
    """ConfigEntry owns the socket; Satellite owns turn admission and policy."""

    def __init__(
        self, hass, adapter, streams, entry_id, *, gateway_url=None, gateway_token=None
    ):
        self.hass, self.adapter, self.streams = hass, adapter, streams
        self.entry_id = entry_id
        self.gateway_url = gateway_url or os.environ.get(
            "TIVOO_QWEN_GATEWAY_URL", "ws://127.0.0.1:3101/api/realtime"
        )
        self.gateway_token = (
            gateway_token
            if gateway_token is not None
            else os.environ.get("TIVOO_QWEN_GATEWAY_TOKEN", "")
        )
        self._ws = None
        self._owner = None
        self._retained_parent = None
        self._retained_task = None
        self._retired_turns = set()

    def create_turn(
        self,
        session_id,
        generation,
        *,
        current,
        prompt_player=None,
        parent_session_id=None,
    ):
        return QwenTurnOwner(
            self, session_id, generation, current, prompt_player, parent_session_id
        )

    @staticmethod
    def _event_id():
        return f"evt_tivoo_{uuid.uuid4().hex}"

    async def _send(self, event):
        async with asyncio.timeout(IO_TIMEOUT):
            await self._ws.send_json({"event_id": self._event_id(), **event})

    async def _receive(self):
        message = await self._ws.receive()
        if message.type != WSMsgType.TEXT:
            raise ConnectionError("Qwen Gateway WebSocket closed or invalid frame")
        try:
            event = json.loads(message.data)
        except (TypeError, ValueError) as err:
            raise ValueError("Qwen Gateway sent invalid JSON") from err
        if not isinstance(event, dict):
            raise TypeError("Qwen event must be an object")
        if not isinstance(event.get("type"), str):
            raise TypeError("Invalid Qwen event type")
        if event["type"] == "error":
            # Do not include upstream message, credentials or URLs in logs.
            raise RuntimeError("Qwen Gateway rejected the current operation")
        if event["type"] == "session.ping":
            if not isinstance(event.get("event_id"), str):
                raise ValueError("Uncorrelated Gateway ping")
            await self._send(
                {"type": "session.pong", "request_event_id": event["event_id"]}
            )
        return event

    async def _connect(self, owner):
        if self._retained_task:
            task, self._retained_task = self._retained_task, None
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self._ws is not None:
            if (
                owner.parent_session_id
                and owner.parent_session_id == self._retained_parent
            ):
                self._retained_parent = None
                owner.mark("voice_ready")
                return
            await self._close_socket()
        if owner.parent_session_id:
            raise RuntimeError("Authorized follow-up socket is no longer available")
        parsed = urlsplit(self.gateway_url)
        if (
            parsed.scheme not in ("ws", "wss")
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError("Invalid Qwen Gateway URL")
        # Each independent wake starts a fresh Gateway history partition.
        # Authorized follow-ups return above and keep the original socket.
        conversation_id = owner.session_id
        query = [(k, v) for k, v in parse_qsl(parsed.query) if k != "sessionId"]
        url = urlunsplit(
            parsed._replace(query=urlencode([*query, ("sessionId", conversation_id)]))
        )
        try:
            async with asyncio.timeout(20):
                self._ws = await async_get_clientsession(self.hass).ws_connect(
                    url,
                    headers={"Authorization": f"Bearer {self.gateway_token}"}
                    if self.gateway_token
                    else {},
                    heartbeat=25,
                    autoping=True,
                    max_msg_size=1024 * 1024,
                )
        except (ClientError, OSError, TimeoutError):
            raise ConnectionError("Unable to connect to Qwen Gateway") from None
        hello_id = self._event_id()
        await self._send(
            {
                "type": "session.hello",
                "event_id": hello_id,
                "protocol": {"min": "7.0.0", "max": "7.0.0"},
                "client": {
                    "type": "embedded",
                    "version": "tivoo-p6.8",
                    "instance_id": f"tivoo-{self.entry_id}",
                },
                "capabilities": [
                    "input.audio",
                    "session.heartbeat",
                    TERMINAL_CAPABILITY,
                ],
                "locale": "zh-CN",
                "time_zone": "Asia/Shanghai",
                "connection": {
                    "voice_enabled": True,
                    "input_enabled": True,
                    "output_enabled": True,
                    "text_only": False,
                },
            }
        )
        session_ready = False
        async with asyncio.timeout(20):
            while True:
                event = await self._receive()
                if event["type"] == "session.ready":
                    if (
                        event.get("request_event_id") != hello_id
                        or event.get("session_id") != conversation_id
                        or event.get("protocol_version") != "7.0.0"
                        or not {
                            "input.audio",
                            "session.heartbeat",
                            TERMINAL_CAPABILITY,
                        }.issubset(event.get("capabilities", []))
                    ):
                        raise RuntimeError(
                            "Qwen Gateway handshake capability or identity mismatch"
                        )
                    session_ready = True
                elif event["type"] == "voice.ready":
                    if (
                        not session_ready
                        or type(event.get("inputSampleRate")) is not int
                        or event["inputSampleRate"] != INPUT_RATE
                    ):
                        raise RuntimeError(
                            "Qwen voice-ready ordering or input rate mismatch"
                        )
                    owner.mark("voice_ready")
                    return
                elif (
                    event["type"] == "voice.ownership"
                    and event.get("state") != "active"
                ):
                    raise RuntimeError("Qwen voice owner is unavailable")

    async def _input(self, owner, audio):
        count = 0
        async for chunk in audio:
            if owner.stopped or not owner.current():
                raise RuntimeError("Qwen MIC generation was superseded")
            if not isinstance(chunk, bytes) or len(chunk) % 2:
                raise ValueError("Qwen input must be PCM16 bytes")
            for offset in range(0, len(chunk), 640):
                count += 1
                owner.input_bytes += len(chunk[offset : offset + 640])
                await self._send(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(
                            chunk[offset : offset + 640]
                        ).decode(),
                    }
                )
        if not count:
            raise RuntimeError("Qwen MIC stream was empty")
        owner.input_drained = True
        owner.mark("input_eof")
        owner.changed.set()
        for _ in range(50):
            if owner.stopped or not owner.current():
                raise RuntimeError("Qwen MIC generation was superseded")
            await self._send(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(bytes(640)).decode(),
                }
            )
            await asyncio.sleep(TAIL_FRAME_SECONDS)

    async def _open_output(self, owner):
        stream = owner.stream
        if owner.dispatched or stream is None or not owner.input_drained:
            return
        owner.dispatched = True
        owner.playback_id = stream.stream_id
        if owner.prompt_player:
            await owner.prompt_player.async_yield_to_tts(owner.playback_id)
        if owner.stopped or not owner.current():
            raise RuntimeError("Qwen output generation was superseded")
        base = get_url(
            self.hass,
            allow_internal=True,
            allow_external=False,
            allow_cloud=False,
            allow_ip=True,
        )
        if urlsplit(base).scheme not in ("http", "https"):
            raise ValueError("No usable HA internal URL")
        await self.adapter.async_send_tts_play(
            owner.playback_id,
            f"{base.rstrip('/')}/api/tivoo/qwen/audio/{stream.stream_id}",
            stream.mime_type,
            session_id=owner.session_id,
        )
        owner.mark("tts_play")

    def _handle(self, owner, event, on_event):
        kind = event["type"]
        if kind == "playback.clear":
            initial_clear = (
                event.get("reason") == "user_interruption"
                and owner.turn_id is None
                and not owner.responses
                and owner.stream is None
                and owner.playback_id is None
                and not owner.dispatched
                and owner.final_response is None
            )
            if initial_clear:
                on_event(event)
                return
            owner.keep_socket = False
            raise RuntimeError("Qwen response delivery was revoked")
        if kind in {"input.suspend", "voice.deactivated", "response.interrupted"}:
            owner.keep_socket = False
            raise RuntimeError("Qwen response delivery was revoked")
        tid = event.get("turnId")
        rid = event.get("responseId")
        if tid in self._retired_turns:
            return
        if kind in {
            "turn.started",
            "response.started",
            "audio.delta",
            "audio.done",
            "transcript.final",
            "transcript.delta",
            "tool.call",
        }:
            if not tid and rid:
                tid = owner.responses.get(rid)
            if not isinstance(tid, str) or not tid:
                raise RuntimeError("Qwen event lacks turn correlation")
            if owner.turn_id is None:
                owner.turn_id = tid
            elif owner.turn_id != tid:
                raise RuntimeError("Multiple Gateway turns for one MIC session")
        if kind in {"response.started", "audio.delta", "audio.done", "tool.call"} or (
            kind.startswith("transcript.") and event.get("role") == "assistant"
        ):
            if not isinstance(rid, str) or not rid:
                raise RuntimeError("Qwen event lacks response identity")
            owner.responses[rid] = tid
        if kind == "audio.delta":
            rate = event.get("sampleRate")
            if type(rate) is not int or rate not in (24000, 32000):
                raise RuntimeError("Unsupported Qwen output rate")
            if owner.final_response:
                raise RuntimeError("Audio arrived after final response terminal")
            if owner.stream is None:
                owner.stream = QwenPcmStream(
                    str(uuid.uuid4()),
                    rate,
                    changed=owner.changed,
                    session_id=owner.session_id,
                    generation=owner.generation,
                )
                owner.mark("first_output")
                self.streams[owner.stream.stream_id] = owner.stream
            owner.stream.response_ids.add(rid)
            if owner.stream.sample_rate != rate:
                raise RuntimeError("Qwen PCM sample rate changed within stream")
            try:
                raw = base64.b64decode(event.get("audio", ""), validate=True)
            except (ValueError, TypeError, binascii.Error):
                raise ValueError("Invalid Qwen PCM base64") from None
            if not raw:
                raise ValueError("Qwen returned empty PCM")
            owner.stream.push(raw)
            owner.output_bytes += len(raw)
        elif kind == "audio.done":
            if event.get("responseStatus") != "completed":
                raise RuntimeError("Qwen response did not complete normally")
            if (
                type(event.get("hasFunctionCall")) is not bool
                or type(event.get("awaitsToolFollowUp")) is not bool
            ):
                raise RuntimeError("Missing Qwen response terminal metadata")
            owner.completed_responses.add(rid)
            if not event["awaitsToolFollowUp"]:
                owner.final_response = rid
                owner.final_has_tools = event["hasFunctionCall"]
                if owner.final_has_tools:
                    owner.keep_socket = False
                    if any(
                        tool_rid == rid and status == "failed"
                        for tool_rid, status in owner.tools.values()
                    ):
                        raise RuntimeError("Qwen terminal tool execution failed")
                if owner.stream is None:
                    raise RuntimeError("Qwen completed without PCM")
                owner.stream.finish()
        elif kind == "tool.call":
            call_id, status = event.get("callId"), event.get("status")
            if (
                not isinstance(call_id, str)
                or not call_id
                or status not in {"received", "running", "completed", "failed"}
            ):
                raise ValueError("Invalid Qwen tool lifecycle")
            owner.tools[call_id] = (rid, status)
            if status == "failed":
                # Ordinary MCP errors are function outputs. Let Gateway send
                # them back to the model and produce its final spoken reply.
                # A terminal tool-only acceptance has no such follow-up.
                result = event.get("result")
                _LOGGER.warning(
                    "Qwen tool failed: %s (%s)",
                    event.get("name", "unknown"),
                    result[:512] if isinstance(result, str) else "unknown",
                )
                if owner.final_has_tools and owner.final_response == rid:
                    on_event(event)
                    raise RuntimeError("Qwen terminal tool execution failed")
        elif kind in {"transcript.final", "transcript.delta"}:
            if event.get("role") not in ("assistant", "user") or not isinstance(
                event.get("content"), str
            ):
                raise ValueError("Invalid Qwen transcript")
            if kind == "transcript.final" and event["role"] == "assistant":
                owner.transcripts[rid] = event["content"]
        on_event(event)

    def on_playback(self, playback_id, state):
        owner = self._owner
        if owner is None or owner.playback_id != playback_id or owner.stopped:
            return
        if state == "completed":
            owner.playback_completed = True
            owner.mark("playback_completed")
        elif state == "playing":
            owner.mark("playback_playing")
        elif state in {"failed", "stopped", "interrupted"}:
            owner.playback_failed = True
        owner.changed.set()

    async def async_run(
        self,
        owner: QwenTurnOwner,
        audio: AsyncIterator[bytes],
        on_event: Callable[[dict], None],
        *,
        on_result: Callable[[QwenResult], None] | None = None,
    ) -> QwenResult:
        sender = receiver = waiter = get_waiter = None
        if self._owner is not None:
            raise RuntimeError("Previous Qwen owner has not been retired")
        self._owner = owner
        try:
            async with asyncio.timeout(TURN_TIMEOUT):
                await self._connect(owner)
                sender = asyncio.create_task(self._input(owner, audio))
                receiver = asyncio.create_task(self._receive())
                while True:
                    if owner.stopped or not owner.current():
                        raise RuntimeError("Qwen turn lost its generation")
                    if owner.playback_failed or (
                        owner.stream and owner.stream.disconnected
                    ):
                        raise RuntimeError("Qwen PCM consumer disconnected or failed")
                    await self._open_output(owner)
                    if owner.dispatched and get_waiter is None:
                        get_waiter = asyncio.create_task(self._wait_get(owner.stream))
                    if (
                        owner.final_response
                        and owner.transcripts.get(owner.final_response, "").strip()
                        and owner.input_drained
                        and sender.done()
                        and owner.playback_completed
                        and owner.stream.http_finished.is_set()
                        and set(owner.responses).issubset(owner.completed_responses)
                        and all(
                            status in {"completed", "failed"} for _, status in owner.tools.values()
                        )
                        and (
                            not owner.final_has_tools
                            or any(
                                rid == owner.final_response
                                for rid, _ in owner.tools.values()
                            )
                        )
                    ):
                        sender.result()
                        owner.success = True
                        result = QwenResult(
                            owner.transcripts[owner.final_response],
                            owner.turn_id,
                            owner.final_response,
                            not owner.final_has_tools,
                        )
                        if on_result is not None:
                            on_result(result)
                        return result
                    owner.changed.clear()
                    waiter = asyncio.create_task(owner.changed.wait())
                    tasks = {receiver, waiter}
                    if not sender.done():
                        tasks.add(sender)
                    else:
                        sender.result()
                    if get_waiter is not None:
                        if get_waiter.done():
                            get_waiter.result()
                        else:
                            tasks.add(get_waiter)
                    done, _ = await asyncio.wait(
                        tasks,
                        timeout=EVENT_TIMEOUT,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    waiter.cancel()
                    await asyncio.gather(waiter, return_exceptions=True)
                    waiter = None
                    if not done:
                        raise TimeoutError(
                            "Qwen response or physical playback timed out"
                        )
                    if sender in done:
                        sender.result()
                    if get_waiter in done:
                        get_waiter.result()
                    if receiver in done:
                        self._handle(owner, receiver.result(), on_event)
                        receiver = asyncio.create_task(self._receive())
        except BaseException:
            owner.send_failed = True
            owner.keep_socket = False
            raise
        finally:
            for task in (sender, receiver, waiter, get_waiter):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(
                    task
                    for task in (sender, receiver, waiter, get_waiter)
                    if task is not None
                ),
                return_exceptions=True,
            )
            await owner.async_close()

    @staticmethod
    async def _wait_get(stream):
        await asyncio.wait_for(stream.requested.wait(), GET_TIMEOUT)

    async def _close_owner(self, owner):
        try:
            if not owner.success:
                try:
                    await owner.async_stop_playback()
                finally:
                    if self._owner is owner and self._ws:
                        try:
                            await self._send({"type": "response.cancel"})
                        except (ClientError, OSError, RuntimeError, TimeoutError):
                            _LOGGER.debug(
                                "Qwen cancel unavailable during socket cleanup"
                            )
        finally:
            try:
                if self._owner is owner:
                    if (
                        owner.success
                        and owner.keep_socket
                        and not owner.final_has_tools
                        and owner.current()
                    ):
                        self._retained_parent = owner.session_id
                        if owner.turn_id:
                            self._retired_turns.add(owner.turn_id)
                        self._retained_task = asyncio.create_task(self._retain(owner))
                    else:
                        await self._close_socket()
            finally:
                if owner.stream:
                    owner.stream.abort()
                    self.streams.pop(owner.stream.stream_id, None)
                    handler = owner.stream.handler_task
                    if not owner.success and handler is not None and not handler.done():
                        handler.cancel()
                        async with asyncio.timeout(5):
                            await asyncio.gather(handler, return_exceptions=True)
                if owner.prompt_player and owner.playback_id:
                    owner.prompt_player.release_tts(owner.playback_id)
                if self._owner is owner:
                    self._owner = None
                _LOGGER.info(
                    "qwen_bridge_metrics generation=%s success=%s input_bytes=%d output_bytes=%d timing_ms=%s",
                    owner.generation,
                    owner.success,
                    owner.input_bytes,
                    owner.output_bytes,
                    json.dumps(owner.timings, separators=(",", ":")),
                )

    async def _retain(self, owner):
        try:
            async with asyncio.timeout(RETAIN_SECONDS):
                while True:
                    event = await self._receive()
                    if event["type"] in {
                        "playback.clear",
                        "input.suspend",
                        "voice.deactivated",
                    }:
                        break
        except asyncio.CancelledError:
            return
        except (
            ClientError,
            OSError,
            RuntimeError,
            ValueError,
            TypeError,
            TimeoutError,
        ):
            _LOGGER.debug("Qwen retained connection ended")
        await self._close_socket()
        if owner.on_connection_lost is not None:
            owner.on_connection_lost()

    async def async_release_parent(self, session_id):
        """Revoke only this retired MIC's retained connection, joining its reader."""
        if self._retained_parent != session_id:
            return
        if self._retained_task:
            self._retained_task.cancel()
            await asyncio.gather(self._retained_task, return_exceptions=True)
            self._retained_task = None
        await self._close_socket()

    async def _close_socket(self):
        ws, self._ws = self._ws, None
        self._retained_parent = None
        self._retired_turns.clear()
        if ws is not None:
            async with asyncio.timeout(5):
                await ws.close()

    async def async_close(self):
        if self._retained_task:
            self._retained_task.cancel()
            await asyncio.gather(self._retained_task, return_exceptions=True)
            self._retained_task = None
        if self._owner:
            self._owner.stop_dispatch()
            await self._owner.async_close()
        await self._close_socket()
