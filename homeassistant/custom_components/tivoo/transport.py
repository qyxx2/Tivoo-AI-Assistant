"""ESP32 TCP transport and TVIO diagnostic protocol handling."""

import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from homeassistant.exceptions import HomeAssistantError

from .audio_session import AudioSessionManager
from .commands import TivooCommand
from .diagnostics import (
    ESP32_TO_HA_MESSAGE_TYPES,
    HA_TO_ESP32_MESSAGE_TYPES,
    SUPPORTED_MESSAGE_TYPES,
    TYPE_AUDIO_INTERRUPTED,
    TYPE_DEVICE_EVENT,
    TYPE_DEVICE_STATUS,
    TYPE_DIAGNOSTIC_LOG,
    TYPE_ERROR,
    TYPE_GET_STATUS,
    TYPE_HELLO,
    TYPE_HELLO_ACK,
    TYPE_MIC_PCM,
    TYPE_MIC_SESSION_END,
    TYPE_MIC_SESSION_START,
    TYPE_PING,
    TYPE_PONG,
    DiagnosticFrameStream,
    DiagnosticMessage,
    encode_message,
)
from .protocol import encode_command

_LOGGER = logging.getLogger("custom_components.tivoo")

CONTROL_PORT = 7777
DIAGNOSTIC_PORT = 7778

_ERROR_CODES = {
    "wifi_init_failed",
    "wifi_connect_failed",
    "tcp_listen_failed",
    "spp_init_failed",
    "spp_connect_failed",
    "spp_disconnect_failed",
    "spp_not_connected",
    "spp_tx_queue_full",
    "spp_write_failed",
    "tcp_control_malformed",
    "tivoo_frame_malformed",
    "protocol_invalid_header",
    "protocol_invalid_payload",
    "protocol_unsupported_message",
    "reverse_queue_full",
    "audio_busy",
    "audio_http_failed",
    "audio_http_status",
    "audio_content_type_mismatch",
    "operation_cancelled",
}
_DEVICE_EVENTS = {
    "wifi_connected",
    "wifi_disconnected",
    "spp_connecting",
    "spp_connected",
    "spp_disconnected",
}
_MAC_PATTERN = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_BEARER_PATTERN = re.compile(r"\bBearer\s+[^\s,;]+", re.IGNORECASE)
_SECRET_PATTERN = re.compile(
    r"\b(token|access_token|authorization|password|passwd|wifi_password|ssid|pcm|pcm_data|pcm_bytes)\s*([=:])\s*[^\s,;]+",
    re.IGNORECASE,
)
_LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


class Esp32ConnectionAdapter:
    """Maintain independent control and diagnostic connections to ESP32."""

    def __init__(
        self,
        host: str | None,
        bluetooth_mac: str | None = None,
        retry_interval: float = 1.0,
        *,
        clock: Callable[[], float] | None = None,
        heartbeat_sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.host = host
        self.retry_interval = retry_interval
        self._bluetooth_mac = None
        if host:
            if not isinstance(bluetooth_mac, str):
                raise ValueError(
                    "Tivoo Bluetooth MAC is required when ESP32 host is set"
                )
            mac = bluetooth_mac.replace(":", "").replace("-", "")
            if len(mac) != 12:
                raise ValueError("Tivoo Bluetooth MAC must contain six octets")
            try:
                self._bluetooth_mac = bytes.fromhex(mac)
            except ValueError as err:
                raise ValueError("Tivoo Bluetooth MAC must be hexadecimal") from err
        self._control_write_lock = asyncio.Lock()
        self.states = {
            "control": "unavailable",
            "diagnostic": "unavailable",
        }
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._writers: dict[str, asyncio.StreamWriter] = {}
        self._diagnostic_tx_sequence = 0
        self._diagnostic_handshaken = False
        self._diagnostic_last_pong_at = 0.0
        self._device_status_request_id: str | None = None
        self._clock = clock if clock is not None else time.monotonic
        self._heartbeat_sleep = (
            heartbeat_sleep if heartbeat_sleep is not None else asyncio.sleep
        )
        self.device_status: dict | None = None
        self.last_device_event: dict | None = None
        self._diagnostic_write_lock = asyncio.Lock()
        self._message_handlers: dict[
            int, Callable[[DiagnosticMessage], Awaitable[None]]
        ] = {}
        self._spp_reverse_handler: Callable[[bytes], Awaitable[None]] | None = None
        self.spp_hint = "unavailable"
        self._stopping = False

    async def async_start(self) -> None:
        """Start independent connection loops when a host is configured."""
        if not self.host or self._tasks:
            return

        self._stopping = False
        for channel, port in (
            ("control", CONTROL_PORT),
            ("diagnostic", DIAGNOSTIC_PORT),
        ):
            self._tasks[channel] = asyncio.create_task(
                self._connection_loop(channel, port),
                name=f"tivoo_esp32_{channel}",
            )

    async def async_stop(self) -> None:
        """Close both sockets and stop their reconnect loops."""
        self._stopping = True
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

        for writer in self._writers.values():
            writer.close()
        if self._writers:
            await asyncio.gather(
                *(writer.wait_closed() for writer in self._writers.values()),
                return_exceptions=True,
            )
        self._writers.clear()
        self._diagnostic_handshaken = False
        self._diagnostic_tx_sequence = 0

        state = "stopped" if self.host else "unavailable"
        self.states = {"control": state, "diagnostic": state}
        self.spp_hint = state

    async def async_execute(self, command: TivooCommand) -> None:
        """Send encoded Tivoo command frames through the active 7777 session."""
        try:
            packets = encode_command(command)
        except (KeyError, TypeError, ValueError) as err:
            raise HomeAssistantError(
                f"Invalid Tivoo command {command.name}: {err}"
            ) from err

        async with self._control_write_lock:
            writer = self._writers.get("control")
            if (
                self.states["control"] != "connected"
                or writer is None
                or writer.is_closing()
            ):
                raise HomeAssistantError(
                    f"ESP32 control channel is not connected; {command.name} was not sent"
                )
            try:
                writer.write(b"".join(packets))
                await writer.drain()
            except (OSError, ConnectionError) as err:
                raise HomeAssistantError(
                    f"ESP32 control channel failed while sending {command.name}"
                ) from err

    def register_spp_reverse_handler(
        self, handler: Callable[[bytes], Awaitable[None]]
    ) -> None:
        """Register an async consumer for opaque bytes returned by Tivoo SPP."""
        if not callable(handler):
            raise TypeError("handler must be callable")
        self._spp_reverse_handler = handler

    async def _handle_control_data(self, data: bytes) -> None:
        """Handle a single-byte upstream hint or forward opaque SPP bytes."""
        if data == b"\x69":
            self.spp_hint = "connecting"
            return
        if data == b"\x96":
            self.spp_hint = "disconnected"
            return

        if self._spp_reverse_handler is not None:
            try:
                await self._spp_reverse_handler(data)
            except Exception:  # noqa: BLE001 — isolate the registered consumer.
                _LOGGER.warning("Tivoo SPP reverse consumer failed")

    def register_audio_session_manager(self, manager: AudioSessionManager) -> None:
        """Connect P6 MIC and interruption messages to one session manager."""

        async def handle_session_start(message: DiagnosticMessage) -> None:
            await manager.async_start_session(self._decode_json(message.payload))

        async def handle_pcm(message: DiagnosticMessage) -> None:
            session_id = manager.active_session_id
            if session_id is not None:
                # MIC_PCM is an opaque binary payload; session association comes
                # from the single active session and TCP message ordering.
                await manager.async_push_pcm(session_id, message.payload)

        async def handle_session_end(message: DiagnosticMessage) -> None:
            payload = self._decode_json(message.payload)
            session_id = payload.get("session_id")
            reason = payload.get("reason")
            if not isinstance(session_id, str) or not session_id:
                raise ValueError("MIC_SESSION_END requires session_id")
            if not isinstance(reason, str) or not reason:
                raise ValueError("MIC_SESSION_END requires reason")
            await manager.async_end_session(session_id, reason)

        async def handle_audio_interrupted(message: DiagnosticMessage) -> None:
            await manager.async_handle_audio_interrupted(
                self._decode_json(message.payload)
            )

        self.register_message_handler(TYPE_MIC_SESSION_START, handle_session_start)
        self.register_message_handler(TYPE_MIC_PCM, handle_pcm)
        self.register_message_handler(TYPE_MIC_SESSION_END, handle_session_end)
        self.register_message_handler(TYPE_AUDIO_INTERRUPTED, handle_audio_interrupted)

    def register_message_handler(
        self,
        message_type: int,
        handler: Callable[[DiagnosticMessage], Awaitable[None]],
    ) -> None:
        """Register an async consumer for one supported TVIO message type."""
        if message_type not in ESP32_TO_HA_MESSAGE_TYPES:
            raise ValueError("message_type is not an ESP32-to-HA TVIO message")
        if not callable(handler):
            raise TypeError("handler must be callable")
        self._message_handlers[message_type] = handler

    async def async_send_message(self, message_type: int, payload: bytes) -> None:
        """Send one TVIO message after the diagnostic HELLO handshake."""
        if message_type not in HA_TO_ESP32_MESSAGE_TYPES:
            raise ValueError("message_type is not an HA-to-ESP32 TVIO message")
        if not self._diagnostic_handshaken:
            raise HomeAssistantError("ESP32 diagnostic handshake is not accepted")
        async with self._diagnostic_write_lock:
            writer = self._writers.get("diagnostic")
            if not self._diagnostic_handshaken or writer is None or writer.is_closing():
                raise HomeAssistantError("ESP32 diagnostic handshake is not accepted")
            frame = encode_message(message_type, payload, self._diagnostic_tx_sequence)
            try:
                writer.write(frame)
                await writer.drain()
            except (OSError, ConnectionError) as err:
                raise HomeAssistantError(
                    "ESP32 diagnostic channel failed while sending a message"
                ) from err
            self._diagnostic_tx_sequence = (
                self._diagnostic_tx_sequence + 1
            ) & 0xFFFFFFFF

    async def _connection_loop(self, channel: str, port: int) -> None:
        """Connect/reconnect one channel without coupling the other channel."""
        assert self.host is not None
        while not self._stopping:
            self.states[channel] = "connecting"
            writer: asyncio.StreamWriter | None = None
            try:
                async with asyncio.timeout(5):
                    reader, writer = await asyncio.open_connection(self.host, port)
                self._writers[channel] = writer
                if channel == "control":
                    if self._bluetooth_mac is None:
                        raise ValueError("Tivoo Bluetooth MAC is not configured")
                    writer.write(b"\x69" + self._bluetooth_mac)
                    await writer.drain()
                    self.spp_hint = "unknown"
                    self.states[channel] = "connected"
                    while data := await reader.read(4096):
                        await self._handle_control_data(data)
                else:
                    self._diagnostic_tx_sequence = 0
                    self._diagnostic_handshaken = False
                    self.states[channel] = "connected"
                    await self._diagnostic_session(reader, writer)
            except (OSError, TimeoutError) as err:
                _LOGGER.debug("ESP32 %s channel disconnected: %s", channel, err)
            except (ValueError, TypeError) as err:
                _LOGGER.warning("ESP32 %s protocol error: %s", channel, err)
            except asyncio.CancelledError:
                raise
            finally:
                if writer is not None:
                    self._writers.pop(channel, None)
                    if channel == "diagnostic":
                        self._diagnostic_handshaken = False
                        self._diagnostic_tx_sequence = 0
                        self._device_status_request_id = None
                        self.device_status = None
                        self.last_device_event = None
                    else:
                        self.spp_hint = "unavailable"
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except OSError:
                        pass

            if not self._stopping:
                self.states[channel] = "disconnected"
                await asyncio.sleep(self.retry_interval)

    async def _diagnostic_session(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Negotiate TVIO v1, request status once, and maintain 7778 liveness."""
        frames = DiagnosticFrameStream()
        handshaken = False
        heartbeat_task: asyncio.Task[None] | None = None
        read_task = asyncio.create_task(reader.read(4096))
        self._diagnostic_tx_sequence = 0
        self._diagnostic_handshaken = False
        self._device_status_request_id = None
        self.device_status = None

        try:
            while True:
                waiters = {read_task}
                if heartbeat_task is not None:
                    waiters.add(heartbeat_task)
                done, _ = await asyncio.wait(
                    waiters, return_when=asyncio.FIRST_COMPLETED
                )
                if heartbeat_task is not None and heartbeat_task in done:
                    await heartbeat_task
                    raise TimeoutError("ESP32 diagnostic heartbeat stopped")
                if read_task not in done:
                    continue

                data = read_task.result()
                if not data:
                    return
                read_task = asyncio.create_task(reader.read(4096))

                for message in frames.feed(data):
                    if not handshaken:
                        if message.message_type != TYPE_HELLO:
                            raise ValueError("first diagnostic message must be HELLO")
                        payload = self._decode_json(message.payload)
                        self._validate_hello(payload)

                        if payload["protocol_version"] != 1:
                            acknowledgement = {
                                "accepted": False,
                                "reason": "unsupported_protocol_version",
                            }
                        else:
                            acknowledgement = {"accepted": True}

                        writer.write(
                            encode_message(
                                TYPE_HELLO_ACK,
                                json.dumps(
                                    acknowledgement, separators=(",", ":")
                                ).encode("utf-8"),
                                self._diagnostic_tx_sequence,
                            )
                        )
                        await writer.drain()
                        self._diagnostic_tx_sequence = (
                            self._diagnostic_tx_sequence + 1
                        ) & 0xFFFFFFFF
                        if not acknowledgement["accepted"]:
                            return

                        handshaken = True
                        self._diagnostic_handshaken = True
                        self._diagnostic_last_pong_at = self._clock()
                        _LOGGER.info(
                            "ESP32 diagnostic channel ready: %s firmware=%s reset=%s",
                            payload["device_id"],
                            payload["firmware_version"],
                            payload["reset_reason"],
                        )
                        self._device_status_request_id = str(uuid.uuid4())
                        self.last_device_event = None
                        try:
                            await self.async_send_message(
                                TYPE_GET_STATUS,
                                json.dumps(
                                    {"request_id": self._device_status_request_id},
                                    separators=(",", ":"),
                                ).encode("utf-8"),
                            )
                        except HomeAssistantError as err:
                            raise ConnectionError(
                                "ESP32 diagnostic channel failed during status request"
                            ) from err
                        heartbeat_task = asyncio.create_task(
                            self._diagnostic_heartbeat(),
                            name="tivoo_esp32_diagnostic_heartbeat",
                        )
                        continue

                    try:
                        if message.message_type == TYPE_PONG:
                            if message.payload:
                                raise ValueError("PONG payload must be empty")
                            self._diagnostic_last_pong_at = self._clock()
                            continue
                        if message.message_type == TYPE_DEVICE_STATUS:
                            payload = self._validate_device_status(
                                self._decode_json(message.payload)
                            )
                            self.device_status = payload
                        elif message.message_type == TYPE_DEVICE_EVENT:
                            payload = self._validate_device_event(
                                self._decode_json(message.payload)
                            )
                            self._apply_device_event(payload)
                            self.last_device_event = payload
                        elif message.message_type == TYPE_DIAGNOSTIC_LOG:
                            self._log_diagnostic(self._decode_json(message.payload))
                        elif message.message_type == TYPE_ERROR:
                            self._log_error(self._decode_json(message.payload))
                        elif message.message_type not in SUPPORTED_MESSAGE_TYPES:
                            _LOGGER.warning(
                                "protocol_unsupported_message: unsupported TVIO "
                                "message type 0x%02x",
                                message.message_type,
                            )
                        if handler := self._message_handlers.get(message.message_type):
                            await handler(message)
                        # Supported messages without a registered handler are ignored.
                    except (ValueError, TypeError) as err:
                        _LOGGER.warning(
                            "Ignoring invalid ESP32 diagnostic message: %s", err
                        )
        finally:
            for task in (read_task, heartbeat_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (read_task, heartbeat_task) if task is not None),
                return_exceptions=True,
            )

    async def _diagnostic_heartbeat(self) -> None:
        """Send PING on a fixed cadence and fail only this 7778 session."""
        next_ping_at = self._clock() + 15.0
        while True:
            pong_deadline = self._diagnostic_last_pong_at + 45.0
            wake_at = min(next_ping_at, pong_deadline)
            await self._heartbeat_sleep(max(0.0, wake_at - self._clock()))
            now = self._clock()
            if now >= self._diagnostic_last_pong_at + 45.0:
                raise TimeoutError("ESP32 diagnostic PONG timeout")
            if now >= next_ping_at:
                try:
                    await self.async_send_message(TYPE_PING, b"")
                except HomeAssistantError as err:
                    raise ConnectionError(
                        "ESP32 diagnostic channel failed during heartbeat"
                    ) from err
                next_ping_at += 15.0
                while next_ping_at <= now:
                    next_ping_at += 15.0

    def _validate_device_status(self, payload: dict) -> dict:
        request_id = payload.get("request_id")
        firmware_version = payload.get("firmware_version")
        uptime_ms = payload.get("uptime_ms")
        if (
            not isinstance(request_id, str)
            or not request_id
            or request_id != self._device_status_request_id
            or payload.get("device_id") != "tivoo-esp32"
            or not isinstance(firmware_version, str)
            or not firmware_version
            or isinstance(uptime_ms, bool)
            or not isinstance(uptime_ms, int)
            or uptime_ms < 0
        ):
            raise ValueError("invalid DEVICE_STATUS identity fields")

        wifi = payload.get("wifi")
        tcp = payload.get("tcp")
        spp = payload.get("spp")
        audio = payload.get("audio_resource")
        if not isinstance(wifi, dict) or wifi.get("state") not in {
            "connected",
            "disconnected",
        }:
            raise ValueError("invalid DEVICE_STATUS wifi state")
        if not isinstance(tcp, dict) or any(
            tcp.get(port) not in {"connected", "disconnected"}
            for port in ("7777", "7778")
        ):
            raise ValueError("invalid DEVICE_STATUS tcp state")
        if not isinstance(spp, dict) or spp.get("state") not in {
            "disconnected",
            "connecting",
            "connected",
        }:
            raise ValueError("invalid DEVICE_STATUS spp state")
        if not isinstance(audio, dict) or audio.get("state") not in {
            "idle",
            "fetching",
        }:
            raise ValueError("invalid DEVICE_STATUS audio_resource state")

        clean_wifi = {"state": wifi["state"]}
        ip = wifi.get("ip")
        if isinstance(ip, str) and ip:
            clean_wifi["ip"] = ip
        rssi = wifi.get("rssi_dbm")
        if isinstance(rssi, int) and not isinstance(rssi, bool):
            clean_wifi["rssi_dbm"] = rssi

        clean_spp = {"state": spp["state"]}
        mac = spp.get("mac")
        if isinstance(mac, str) and _MAC_PATTERN.fullmatch(mac):
            clean_spp["mac"] = mac.upper()

        playback_id = audio.get("playback_id")
        if audio["state"] == "fetching":
            if (
                not isinstance(playback_id, str)
                or not playback_id
                or len(playback_id) > 64
            ):
                raise ValueError("fetching DEVICE_STATUS requires playback_id")
        elif playback_id is not None:
            raise ValueError("idle DEVICE_STATUS playback_id must be null")

        return {
            "request_id": request_id,
            "device_id": "tivoo-esp32",
            "firmware_version": firmware_version,
            "uptime_ms": uptime_ms,
            "wifi": clean_wifi,
            "tcp": {"7777": tcp["7777"], "7778": tcp["7778"]},
            "spp": clean_spp,
            "audio_resource": {"state": audio["state"], "playback_id": playback_id},
        }

    @staticmethod
    def _validate_device_event(payload: dict) -> dict:
        event = payload.get("event")
        uptime_ms = payload.get("uptime_ms")
        data = payload.get("data")
        if (
            event not in _DEVICE_EVENTS
            or isinstance(uptime_ms, bool)
            or not isinstance(uptime_ms, int)
            or uptime_ms < 0
            or not isinstance(data, dict)
        ):
            raise ValueError("invalid DEVICE_EVENT fields")
        clean_data = {}
        mac = data.get("mac")
        if isinstance(mac, str) and _MAC_PATTERN.fullmatch(mac):
            clean_data["mac"] = mac.upper()
        return {"event": event, "uptime_ms": uptime_ms, "data": clean_data}

    def _apply_device_event(self, event: dict) -> None:
        if self.device_status is None:
            return
        name = event["event"]
        if name.startswith("wifi_"):
            wifi = dict(self.device_status["wifi"])
            wifi["state"] = "connected" if name == "wifi_connected" else "disconnected"
            if name == "wifi_disconnected":
                wifi.pop("ip", None)
                wifi.pop("rssi_dbm", None)
            self.device_status["wifi"] = wifi
        elif name.startswith("spp_"):
            spp = dict(self.device_status["spp"])
            spp["state"] = name.removeprefix("spp_")
            if name == "spp_disconnected":
                spp.pop("mac", None)
            elif "mac" in event["data"]:
                spp["mac"] = event["data"]["mac"]
            self.device_status["spp"] = spp

    @staticmethod
    def _decode_json(payload: bytes) -> dict:
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise ValueError(f"invalid JSON payload: {err}") from err
        if not isinstance(value, dict):
            raise TypeError("JSON payload must be an object")
        return value

    @staticmethod
    def _validate_hello(payload: dict) -> None:
        if (
            payload.get("device_id") != "tivoo-esp32"
            or not isinstance(payload.get("firmware_version"), str)
            or not payload["firmware_version"]
            or payload.get("capabilities")
            != [
                "spp_control",
                "spp_reverse",
                "remote_diagnostics",
                "device_status",
                "device_events",
                "audio_resource_http",
                "audio_control",
            ]
            or not isinstance(payload.get("reset_reason"), str)
            or not payload["reset_reason"]
            or isinstance(payload.get("protocol_version"), bool)
            or not isinstance(payload.get("protocol_version"), int)
        ):
            raise ValueError("invalid HELLO payload")

    @staticmethod
    def _validate_log_fields(payload: dict) -> tuple[str, str, int]:
        module = payload.get("module")
        message = payload.get("message")
        uptime_ms = payload.get("uptime_ms")
        if (
            not isinstance(module, str)
            or not module
            or not isinstance(message, str)
            or len(message.encode("utf-8")) > 384
            or isinstance(uptime_ms, bool)
            or not isinstance(uptime_ms, int)
            or uptime_ms < 0
        ):
            raise ValueError("invalid diagnostic log fields")
        return module, message, uptime_ms

    @staticmethod
    def _redact_sensitive_text(message: str) -> str:
        """Remove transient URLs, credentials, bearer values and PCM fields."""
        message = _URL_PATTERN.sub("[redacted-url]", message)
        message = _BEARER_PATTERN.sub("Bearer [redacted]", message)
        return _SECRET_PATTERN.sub(r"\1\2[redacted]", message)

    def _log_diagnostic(self, payload: dict) -> None:
        level = payload.get("level")
        if level not in _LOG_LEVELS:
            raise ValueError("invalid diagnostic log level")
        module, message, uptime_ms = self._validate_log_fields(payload)
        message = self._redact_sensitive_text(message)
        correlation_id = payload.get("correlation_id")
        if correlation_id is not None and not isinstance(correlation_id, str):
            raise ValueError("invalid diagnostic correlation_id")
        dropped_count = payload.get("dropped_count")
        if dropped_count is not None and (
            isinstance(dropped_count, bool)
            or not isinstance(dropped_count, int)
            or dropped_count < 0
        ):
            raise ValueError("invalid diagnostic dropped_count")

        suffix = f" [module={module} uptime_ms={uptime_ms}"
        if correlation_id:
            suffix += f" correlation_id={correlation_id}"
        if dropped_count is not None:
            suffix += f" dropped_count={dropped_count}"
        suffix += "]"
        _LOGGER.log(_LOG_LEVELS[level], "ESP32 %s%s", message, suffix)

    def _log_error(self, payload: dict) -> None:
        error_code = payload.get("error_code")
        if error_code not in _ERROR_CODES:
            raise ValueError("invalid ESP32 error_code")
        module, message, uptime_ms = self._validate_log_fields(payload)
        message = self._redact_sensitive_text(message)
        correlation_id = payload.get("correlation_id")
        if correlation_id is not None and not isinstance(correlation_id, str):
            raise ValueError("invalid ERROR correlation_id")

        suffix = f" [module={module} uptime_ms={uptime_ms}"
        if correlation_id:
            suffix += f" correlation_id={correlation_id}"
        suffix += "]"
        _LOGGER.error("ESP32 %s: %s%s", error_code, message, suffix)
