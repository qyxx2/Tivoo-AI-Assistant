"""Run the real P7A Wyoming handler with deterministic test models."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import threading
from types import SimpleNamespace

import numpy as np
from sherpa_wyoming.config import ServiceConfig
from sherpa_wyoming.models import ModelBundle
from sherpa_wyoming.providers.tts import TTSStreamSession
from sherpa_wyoming.run import WyomingEventHandler, run_server
from wyoming.server import AsyncEventHandler

_TRACE_PATH = ""
_TRACE_LOCK = threading.Lock()
_ACTIVE_HANDLERS = []
_TTS_CALLBACK_RELEASE = threading.Event()
_TTS_CALLBACK_WAITING = threading.Event()
_HOLD_TTS_CALLBACK = 0
_TTS_SAMPLE_COUNT = 512
_TTS_GENERATE_COUNT = 0


def trace(event: str, **fields) -> None:
    record = {"event": event, **fields}
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with _TRACE_LOCK, open(_TRACE_PATH, "a", encoding="utf-8") as trace_file:
        trace_file.write(line + "\n")
    print(f"P6_5_TRACE {line}", flush=True)


class FakeWakeStream:
    def __init__(self) -> None:
        self.ready = False


class FakeWake:
    def create_stream(self):
        return FakeWakeStream()

    def is_ready(self, stream) -> bool:
        return stream.ready

    def decode_stream(self, stream) -> None:
        stream.ready = False

    def get_result(self, _stream) -> str:
        return "tivoo"


class FakeSttStream:
    def __init__(self) -> None:
        self.result = SimpleNamespace(text="测试正常完成")

    def accept_waveform(self, _rate: int, _samples: np.ndarray) -> None:
        return None


class FakeRecognizer:
    def create_stream(self):
        return FakeSttStream()

    def decode_stream(self, _stream) -> None:
        return None


class FakeTts:
    def generate(self, text: str, *, sid: int, speed: float, callback=None):
        global _TTS_GENERATE_COUNT
        _TTS_GENERATE_COUNT += 1
        trace("tts_generate", text=text, sid=sid, speed=speed)
        samples = np.linspace(-0.25, 0.25, _TTS_SAMPLE_COUNT, dtype=np.float32)
        if _TTS_GENERATE_COUNT == _HOLD_TTS_CALLBACK:
            _TTS_CALLBACK_WAITING.set()
            trace("tts_callback_waiting")
            _TTS_CALLBACK_RELEASE.wait()
            trace("tts_callback_released")
        callback_result = None
        if callback is not None:
            callback_result = callback(samples, 1.0)
        trace("tts_callback", text=text, callback_result=callback_result)
        return SimpleNamespace(samples=samples, sample_rate=22_050)


def _install_task_tracing() -> None:
    original_cleanup = TTSStreamSession._cleanup

    async def tracked_cleanup(self) -> None:
        try:
            await original_cleanup(self)
        finally:
            trace(
                "tts_session_cleanup",
                input_task_done=(
                    self._input_task.done() if self._input_task is not None else None
                ),
                worker_task_done=(
                    self._worker_task.done() if self._worker_task is not None else None
                ),
                input_stopped=self._input_stopped,
                failed=self._failure is not None,
                text_chars=self.text_char_count,
            )

    TTSStreamSession._cleanup = tracked_cleanup

    original_disconnect = WyomingEventHandler.disconnect

    async def tracked_disconnect(self) -> None:
        task = self._tts_task
        if task is not None:
            trace("tts_tcp_eof")
        await original_disconnect(self)
        if task is not None:
            trace("tts_request_finished", cancelled=task.cancelled())

    WyomingEventHandler.disconnect = tracked_disconnect

    original_collect = WyomingEventHandler._collect_stream_task

    async def tracked_collect(self) -> None:
        task = self._tts_task
        session = self._tts_session
        try:
            await original_collect(self)
        finally:
            trace(
                "tts_collect_complete",
                task_done=task.done() if task is not None else None,
                task_cancelled=task.cancelled() if task is not None else None,
                input_task_done=(
                    session._input_task.done()
                    if session is not None and session._input_task is not None
                    else None
                ),
                worker_task_done=(
                    session._worker_task.done()
                    if session is not None and session._worker_task is not None
                    else None
                ),
            )

    WyomingEventHandler._collect_stream_task = tracked_collect

    original_reset = WyomingEventHandler._reset_request

    def tracked_reset(self) -> None:
        previous_provider = self._provider
        original_reset(self)
        if previous_provider is not None:
            self._p6_5_last_provider = previous_provider
            trace(
                "request_reset",
                previous_provider=previous_provider,
                provider_after_reset=self._provider,
                tts_task_pending=self._tts_task is not None,
            )

    WyomingEventHandler._reset_request = tracked_reset

    original_run = AsyncEventHandler.run

    async def tracked_run(self) -> None:
        self._p6_5_handler_task = asyncio.current_task()
        _ACTIVE_HANDLERS.append(self)
        try:
            await original_run(self)
        finally:
            trace(
                "handler_finished",
                last_provider=getattr(self, "_p6_5_last_provider", None),
                tts_task_pending=self._tts_task is not None,
            )
            if self in _ACTIVE_HANDLERS:
                _ACTIVE_HANDLERS.remove(self)

    WyomingEventHandler.run = tracked_run


def _task_state(task) -> str | None:
    if task is None:
        return None
    if task.cancelled():
        return "cancelled"
    if task.done():
        return "done"
    return "pending"


async def _handle_control(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    try:
        command = json.loads(await reader.readline())
        action = command.get("action")
        if action == "release_tts":
            _TTS_CALLBACK_RELEASE.set()
            result = {"released": True}
        elif action == "status":
            handlers = []
            for handler in _ACTIVE_HANDLERS:
                session = handler._tts_session
                handlers.append(
                    {
                        "provider": handler._provider,
                        "handler_task": _task_state(
                            getattr(handler, "_p6_5_handler_task", None)
                        ),
                        "tts_request_task": _task_state(handler._tts_task),
                        "input_task": _task_state(
                            session._input_task if session else None
                        ),
                        "worker_task": _task_state(
                            session._worker_task if session else None
                        ),
                        "session_cancelled": session._cancelled.is_set()
                        if session
                        else None,
                    }
                )
            result = {
                "callback_waiting": _TTS_CALLBACK_WAITING.is_set()
                and not _TTS_CALLBACK_RELEASE.is_set(),
                "handlers": handlers,
            }
        else:
            result = {"error": "unknown action"}
        writer.write(json.dumps(result).encode() + b"\n")
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def _run(
    host: str,
    port: int,
    control_port: int | None,
    hold_tts_callback: int,
    sample_count: int,
) -> None:
    global _HOLD_TTS_CALLBACK, _TTS_SAMPLE_COUNT
    _HOLD_TTS_CALLBACK = hold_tts_callback
    _TTS_SAMPLE_COUNT = sample_count
    _TTS_CALLBACK_RELEASE.clear()
    _TTS_CALLBACK_WAITING.clear()
    _install_task_tracing()
    control_server = (
        await asyncio.start_server(_handle_control, host, control_port)
        if control_port is not None
        else None
    )
    config = ServiceConfig(
        wake_word_phrase="tivoo",
        host=host,
        port=port,
    )
    models = ModelBundle(
        keyword_spotter=FakeWake(),
        stt_recognizer=FakeRecognizer(),
        tts_engine=FakeTts(),
    )
    try:
        await run_server(
            config,
            keyword_generator=lambda *_args: None,
            model_loader=lambda _config: models,
        )
    finally:
        if control_server is not None:
            control_server.close()
            await control_server.wait_closed()


def main() -> None:
    global _TRACE_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--trace", required=True)
    parser.add_argument("--control-port", type=int)
    parser.add_argument("--hold-first-tts-callback", action="store_true")
    parser.add_argument("--hold-tts-callback", type=int, default=0)
    parser.add_argument("--tts-sample-count", type=int, default=512)
    args = parser.parse_args()
    _TRACE_PATH = args.trace
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    asyncio.run(
        _run(
            args.host,
            args.port,
            args.control_port,
            1 if args.hold_first_tts_callback else args.hold_tts_callback,
            args.tts_sample_count,
        )
    )


if __name__ == "__main__":
    main()
