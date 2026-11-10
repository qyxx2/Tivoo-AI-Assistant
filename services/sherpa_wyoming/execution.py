from __future__ import annotations

import asyncio
import functools
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any


class ExecutionQueueFull(RuntimeError):
    """Raised when a model has no free or pending execution slot."""


class BoundedExecutor:
    """A small per-model worker pool with a fixed running + pending limit."""

    def __init__(
        self,
        *,
        max_workers: int,
        max_pending: int,
        name: str = "model",
    ) -> None:
        if max_workers < 1 or max_pending < 0:
            raise ValueError(
                "max_workers must be positive and max_pending non-negative"
            )
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=name,
        )
        self._slots = threading.BoundedSemaphore(max_workers + max_pending)

    async def run(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if not self._slots.acquire(blocking=False):
            raise ExecutionQueueFull("model execution queue is full")

        loop = asyncio.get_running_loop()
        try:
            worker_future: Future[Any] = self._pool.submit(
                functools.partial(function, *args, **kwargs)
            )
        except BaseException:
            self._slots.release()
            raise

        future = asyncio.wrap_future(worker_future, loop=loop)
        try:
            result = await asyncio.shield(future)
        except asyncio.CancelledError:
            # Pending work can be removed from ThreadPoolExecutor's queue. A
            # running call cannot be stopped, so it retains its slot until exit.
            if worker_future.cancel():
                self._slots.release()
            else:
                worker_future.add_done_callback(lambda _future: self._slots.release())
                future.add_done_callback(_consume_future_exception)
            raise
        except BaseException:
            self._slots.release()
            raise

        self._slots.release()
        return result

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def _consume_future_exception(future: asyncio.Future[Any]) -> None:
    if not future.cancelled():
        future.exception()
