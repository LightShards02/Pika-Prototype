"""Per-process pub/sub for phase-run progress events (SSE backing store)."""

from __future__ import annotations

import asyncio
import threading
from typing import Any


_MAX_QUEUE_SIZE = 1000


class _Channel:
    __slots__ = ("queue", "loop", "lock", "dropped", "closed")

    def __init__(self, queue: asyncio.Queue[dict[str, Any]], loop: asyncio.AbstractEventLoop) -> None:
        self.queue = queue
        self.loop = loop
        self.lock = threading.Lock()
        self.dropped = 0
        self.closed = False


class PhaseRunEventBus:
    """Per-process pub/sub for phase-run progress events.

    The owning event loop is captured on `create()` (called from the request
    handler) so background threads (e.g. ThreadPoolExecutor inside
    `_run_refine_agents`) can publish via `call_soon_threadsafe`.
    """

    def __init__(self) -> None:
        self._channels: dict[str, _Channel] = {}
        self._lock = threading.Lock()

    def create(self, phase_run_id: str) -> asyncio.Queue[dict[str, Any]]:
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
        with self._lock:
            self._channels[phase_run_id] = _Channel(queue, loop)
        return queue

    def has(self, phase_run_id: str) -> bool:
        return phase_run_id in self._channels

    def subscribe(self, phase_run_id: str) -> asyncio.Queue[dict[str, Any]] | None:
        chan = self._channels.get(phase_run_id)
        return chan.queue if chan is not None else None

    def publish(self, phase_run_id: str, event: dict[str, Any]) -> None:
        chan = self._channels.get(phase_run_id)
        if chan is None or chan.closed:
            return
        with chan.lock:
            def _put() -> None:
                try:
                    chan.queue.put_nowait(event)
                except asyncio.QueueFull:
                    try:
                        chan.queue.get_nowait()
                        chan.dropped += 1
                        chan.queue.put_nowait({
                            "event": "progress",
                            "data": {"dropped": chan.dropped},
                        })
                        chan.queue.put_nowait(event)
                    except Exception:
                        pass
            try:
                chan.loop.call_soon_threadsafe(_put)
            except RuntimeError:
                pass

    def close(self, phase_run_id: str) -> None:
        with self._lock:
            chan = self._channels.pop(phase_run_id, None)
        if chan is not None:
            chan.closed = True
            try:
                chan.loop.call_soon_threadsafe(chan.queue.put_nowait, {"event": "_close", "data": {}})
            except RuntimeError:
                pass


__all__ = ["PhaseRunEventBus"]
