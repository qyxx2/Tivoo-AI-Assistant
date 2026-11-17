"""Run-scoped TTS ownership for HA Core 2026.11.0's ResultStream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing
from time import monotonic
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.components.wyoming.tts import WyomingTtsProvider
    from wyoming.client import AsyncTcpClient

from homeassistant.components import tts
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

_WYOMING_CLOSE_TIMEOUT = 15
_CONVERSION_CLOSE_TIMEOUT = 5


class _OwnedCache(tts.TTSCache):
    """Keep the native Proxy cache contract with request-local queue cleanup."""

    def __init__(self, stream: tts.ResultStream, audio: AsyncGenerator[bytes]) -> None:
        super().__init__(stream.token, stream.extension, audio)
        self.closed = False
        self._load_started = asyncio.Event()

    async def async_load_data(self) -> bytes:
        """Publish producer readiness before the first source await."""
        self._load_started.set()
        return await super().async_load_data()

    def stop_delivery(self) -> None:
        self.closed = True
        self._load_started.set()
        if self._consumers is not None:
            for queue in self._consumers:
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)

    async def async_stream_data(self) -> AsyncGenerator[bytes]:
        if self.closed:
            return
        if (
            self._result_data is None
            and self._partial_data is None
            and self._loading_error is None
        ):
            await self._load_started.wait()
            if self.closed:
                return
        if self._result_data is not None:
            yield self._result_data
            return
        queue = None
        consumers = self._consumers
        if consumers is not None:
            queue = asyncio.Queue()
            consumers.append(queue)

        try:
            for chunk in list(self._partial_data or ()):
                if self.closed:
                    return
                yield chunk
            if queue is not None:
                while not self.closed and (chunk := await queue.get()) is not None:
                    if self.closed:
                        return
                    yield chunk
            if self._loading_error is not None:
                raise self._loading_error
            self.last_used = monotonic()
        finally:
            if queue is not None:
                consumers.remove(queue)


class PipelineTtsOwner:
    """Claim one ResultStream before Assist starts feeding its text."""

    @classmethod
    def for_stream(cls, stream: tts.ResultStream) -> PipelineTtsOwner | None:
        """Claim the streaming Wyoming path used by Tivoo."""
        if stream.engine is None or not stream.supports_streaming_input:
            return None
        provider = tts.get_engine_instance(stream.hass, stream.engine)
        if (
            not isinstance(provider, tts.TextToSpeechEntity)
            or provider.platform is None
            or provider.platform.platform_name != "wyoming"
        ):
            return None
        from homeassistant.components.wyoming.tts import WyomingTtsProvider

        if isinstance(provider, WyomingTtsProvider):
            return cls(stream, provider)
        return None

    def __init__(self, stream: tts.ResultStream, provider: WyomingTtsProvider) -> None:
        if HA_VERSION != "2026.11.0":
            raise HomeAssistantError("Tivoo TTS ownership requires HA Core 2026.11.0")
        self.stream = stream
        self._provider = provider
        self.cache: _OwnedCache | None = None
        self.producer: asyncio.Task | None = None
        self._close_task: asyncio.Task | None = None
        self._closed = False
        self._client: AsyncTcpClient | None = None
        self._writer: asyncio.Task | None = None
        self._read_finished = asyncio.Event()
        self._peer_eof = False

        # The pipeline already holds this object. Limit the adapter to its token.
        stream.async_set_message_stream = self._start
        stream.async_set_message = self._start_message
        stream.async_stream_result = self._stream_result

    @callback
    def _start_message(self, message: str) -> None:
        async def one_message() -> AsyncGenerator[str]:
            yield message

        self._start(one_message())

    @callback
    def _start(self, message: AsyncGenerator[str]) -> None:
        stream = self.stream
        if self._closed or stream._result_cache.done():
            return
        stream._async_mark_used()
        self.cache = _OwnedCache(stream, self._generate(message))
        self.producer = stream.hass.async_create_background_task(
            self._produce(self.cache), "Tivoo TTS producer"
        )
        stream._result_cache.set_result(self.cache)

    async def _stream_result(self) -> AsyncGenerator[bytes]:
        if self.stream._override_media_path is not None:
            async with aclosing(
                tts.ResultStream.async_stream_result(self.stream)
            ) as source:
                async for chunk in source:
                    yield chunk
            return
        cache = await asyncio.shield(self.stream._result_cache)
        if cache is not None:
            async with aclosing(cache.async_stream_data()) as source:
                async for chunk in source:
                    yield chunk

    async def _produce(self, cache: _OwnedCache) -> None:
        async with aclosing(cache._data_gen):
            try:
                await cache.async_load_data()
            except Exception:  # noqa: BLE001 - TTSCache stores provider errors for GET.
                return

    async def _generate(self, message: AsyncGenerator[str]) -> AsyncGenerator[bytes]:
        stream = self.stream
        async with aclosing(message), aclosing(self._wyoming_audio(message)) as wav:
            options = stream.options
            if stream.extension == "wav" and not any(
                options.get(key) is not None
                for key in (
                    tts.ATTR_PREFERRED_SAMPLE_RATE,
                    tts.ATTR_PREFERRED_SAMPLE_CHANNELS,
                    tts.ATTR_PREFERRED_SAMPLE_BYTES,
                )
            ):
                async for chunk in wav:
                    if not self._closed:
                        yield chunk
                return
            async with aclosing(
                tts._async_convert_audio(
                    stream.hass,
                    "wav",
                    wav,
                    to_extension=stream.extension,
                    to_sample_rate=options.get(tts.ATTR_PREFERRED_SAMPLE_RATE),
                    to_sample_channels=options.get(tts.ATTR_PREFERRED_SAMPLE_CHANNELS),
                    to_sample_bytes=options.get(tts.ATTR_PREFERRED_SAMPLE_BYTES),
                    to_bitrate=options.get(tts.ATTR_PREFERRED_BITRATE),
                )
            ) as conversion:
                async for chunk in conversion:
                    if not self._closed:
                        yield chunk

    async def _wyoming_audio(
        self, message: AsyncGenerator[str]
    ) -> AsyncGenerator[bytes]:
        from homeassistant.components.wyoming import tts as wyoming_tts

        provider = self._provider
        options = self.stream.options
        voice = None
        if (name := options.get(tts.ATTR_VOICE)) is not None:
            voice = wyoming_tts.SynthesizeVoice(
                name=name, speaker=options.get(wyoming_tts.ATTR_SPEAKER)
            )

        client = wyoming_tts.AsyncTcpClient(
            provider.service.host, provider.service.port
        )
        self._client = client
        try:
            if self._closed:
                return
            await client.connect()
            if self._closed:
                return
            self._writer = provider.config_entry.async_create_background_task(
                self.stream.hass,
                provider._write_tts_message(message, client, voice),
                "Tivoo Wyoming TTS writer",
            )
            async with aclosing(provider._read_tts_audio(client)) as audio:
                async for chunk in audio:
                    if not self._closed:
                        yield chunk
            if self._closed:
                # The provider can stop reading on SynthesizeStopped. Keep the
                # half-close handshake owned by this same reader until TCP EOF.
                while await client.read_event() is not None:
                    pass
            # The read loop can also stop on a malformed event or a socket
            # error. A drained reader at EOF confirms the peer closed.
            reader = client._reader
            self._peer_eof = reader is not None and reader.at_eof()
        finally:
            self._read_finished.set()
            try:
                await self._close_wyoming(client)
            finally:
                self._client = None

    async def _close_wyoming(self, client: AsyncTcpClient) -> None:
        if self._writer is not None:
            self._writer.cancel()
            await asyncio.gather(self._writer, return_exceptions=True)
        await client.disconnect()

    async def _finish_wyoming(self, client: AsyncTcpClient) -> None:
        # Cancel text before sending FIN. Keep the read half open until P7A
        # joins its request and closes its socket. The reader drains any
        # buffered events without forwarding them to FFmpeg or Proxy.
        assert self._writer is not None
        self._writer.cancel()
        await asyncio.gather(self._writer, return_exceptions=True)
        transport = client._writer
        try:
            async with asyncio.timeout(_WYOMING_CLOSE_TIMEOUT):
                if not self._read_finished.is_set() and transport is not None:
                    transport.write_eof()
                await self._read_finished.wait()
        except (TimeoutError, OSError) as err:
            await client.disconnect()
            raise HomeAssistantError(
                "Wyoming TTS cancellation was not confirmed"
            ) from err
        if not self._peer_eof:
            raise HomeAssistantError("Wyoming TTS cancellation was not confirmed")

    async def async_cancel(self) -> None:
        """Stop delivery and join this run's producer and its input owners."""
        if self._close_task is None:
            self._closed = True
            self.stream.delete()
            if not self.stream._result_cache.done():
                self.stream._result_cache.set_result(None)
            if self.cache is not None:
                self.cache.stop_delivery()
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)

    async def _close(self) -> None:
        if self.producer is None:
            return
        if self._client is not None and self._writer is not None:
            # Closing TCP drives EOF through HA's FFmpeg input writer. Let the
            # conversion drain stdout, close stdin, and wait for the process.
            try:
                await self._finish_wyoming(self._client)
            finally:
                await self._join_producer()
        else:
            self.producer.cancel()
            await self._join_producer()

    async def _join_producer(self) -> None:
        assert self.producer is not None
        try:
            async with asyncio.timeout(_CONVERSION_CLOSE_TIMEOUT):
                await asyncio.shield(self.producer)
        except asyncio.CancelledError:
            if not self.producer.cancelled():
                raise
        except TimeoutError as err:
            if not self.producer.cancelling():
                self.producer.cancel()
            await asyncio.gather(self.producer, return_exceptions=True)
            raise HomeAssistantError("HA TTS producer did not exit") from err
