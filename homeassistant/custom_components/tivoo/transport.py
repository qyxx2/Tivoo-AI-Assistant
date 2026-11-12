"""ESP32 TCP transport and P5 diagnostic protocol handling."""

import asyncio
import json
import logging

from homeassistant.exceptions import HomeAssistantError

from .commands import TivooCommand
from .diagnostics import (
    TYPE_DIAGNOSTIC_LOG,
    TYPE_ERROR,
    TYPE_HELLO,
    TYPE_HELLO_ACK,
    DiagnosticFrameStream,
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
}
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

        state = "stopped" if self.host else "unavailable"
        self.states = {"control": state, "diagnostic": state}

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
                    self.states[channel] = "connected"
                    while await reader.read(4096):
                        pass
                else:
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
        """Negotiate TVIO v1 then consume device logs until this socket closes."""
        frames = DiagnosticFrameStream()
        handshaken = False

        while data := await reader.read(4096):
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
                            json.dumps(acknowledgement, separators=(",", ":")).encode(
                                "utf-8"
                            ),
                            0,
                        )
                    )
                    await writer.drain()
                    if not acknowledgement["accepted"]:
                        return

                    handshaken = True
                    _LOGGER.info(
                        "ESP32 diagnostic channel ready: %s firmware=%s reset=%s",
                        payload["device_id"],
                        payload["firmware_version"],
                        payload["reset_reason"],
                    )
                    continue

                try:
                    if message.message_type == TYPE_DIAGNOSTIC_LOG:
                        self._log_diagnostic(self._decode_json(message.payload))
                    elif message.message_type == TYPE_ERROR:
                        self._log_error(self._decode_json(message.payload))
                    # Unknown and not-applicable message types are ignored in P5.
                except (ValueError, TypeError) as err:
                    _LOGGER.warning(
                        "Ignoring invalid ESP32 diagnostic message: %s", err
                    )

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
            or payload.get("capabilities") != ["spp_control", "remote_diagnostics"]
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

    def _log_diagnostic(self, payload: dict) -> None:
        level = payload.get("level")
        if level not in _LOG_LEVELS:
            raise ValueError("invalid diagnostic log level")
        module, message, uptime_ms = self._validate_log_fields(payload)
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
        correlation_id = payload.get("correlation_id")
        if correlation_id is not None and not isinstance(correlation_id, str):
            raise ValueError("invalid ERROR correlation_id")

        suffix = f" [module={module} uptime_ms={uptime_ms}"
        if correlation_id:
            suffix += f" correlation_id={correlation_id}"
        suffix += "]"
        _LOGGER.error("ESP32 %s: %s%s", error_code, message, suffix)
