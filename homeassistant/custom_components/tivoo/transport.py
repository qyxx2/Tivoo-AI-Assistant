"""ESP32 TCP connection lifecycle; application protocols are added later."""

import asyncio

from homeassistant.exceptions import HomeAssistantError

from .commands import TivooCommand

CONTROL_PORT = 7777
DIAGNOSTIC_PORT = 7778


class Esp32ConnectionAdapter:
    """Maintain independent TCP connections to the ESP32 listeners."""

    def __init__(self, host: str | None, retry_interval: float = 1.0) -> None:
        self.host = host
        self.retry_interval = retry_interval
        self.states = {
            "control": "unavailable",
            "diagnostic": "unavailable",
        }
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._writers: dict[str, asyncio.StreamWriter] = {}
        self._stopping = False

    async def async_start(self) -> None:
        """Start the independent connection loops when a host is configured."""
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
        """Reject commands until the raw control bridge is implemented."""
        raise HomeAssistantError(
            "Tivoo command forwarding is unavailable in P5b1; "
            f"{command.name} was not sent"
        )

    async def _connection_loop(self, channel: str, port: int) -> None:
        """Connect and wait for peer closure; keep this channel independent."""
        assert self.host is not None
        while not self._stopping:
            self.states[channel] = "connecting"
            writer: asyncio.StreamWriter | None = None
            try:
                async with asyncio.timeout(5):
                    reader, writer = await asyncio.open_connection(self.host, port)
                self._writers[channel] = writer
                self.states[channel] = "connected"
                # P5b1 owns connection state only. Later batches add each
                # channel's protocol reader; no payload is interpreted here.
                while await reader.read(4096):
                    pass
            except (OSError, TimeoutError):
                self.states[channel] = "disconnected"
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
