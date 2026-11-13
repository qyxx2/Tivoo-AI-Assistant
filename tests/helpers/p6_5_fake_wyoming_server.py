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
        trace("tts_generate", text=text, sid=sid, speed=speed)
        samples = np.linspace(-0.25, 0.25, 512, dtype=np.float32)
        callback_result = None
        if callback is not None:
            callback_result = callback(samples, 1.0)
        trace("tts_callback", callback_result=callback_result)
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
        try:
            await original_run(self)
        finally:
            trace(
                "handler_finished",
                last_provider=getattr(self, "_p6_5_last_provider", None),
                tts_task_pending=self._tts_task is not None,
            )

    WyomingEventHandler.run = tracked_run


async def _run(host: str, port: int) -> None:
    _install_task_tracing()
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
    await run_server(
        config,
        keyword_generator=lambda *_args: None,
        model_loader=lambda _config: models,
    )


def main() -> None:
    global _TRACE_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--trace", required=True)
    args = parser.parse_args()
    _TRACE_PATH = args.trace
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    asyncio.run(_run(args.host, args.port))


if __name__ == "__main__":
    main()
