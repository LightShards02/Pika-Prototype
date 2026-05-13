"""Redirect stderr into the phase-run event bus for the duration of a context."""

from __future__ import annotations

import contextlib
import re
import sys
import threading
from datetime import datetime
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from api.events import PhaseRunEventBus


_PIKA_LINE = re.compile(r"^\[PIKA\]\s+(?P<step>[^:]+):\s+(?P<status>[^—\-]+?)\s*[—\-]\s*(?P<detail>.*)$")


class _BusWriter:
    """Thread-safe file-like writer that funnels stderr lines into the bus."""

    def __init__(self, phase_run_id: str, bus: "PhaseRunEventBus", passthrough: "object | None" = None) -> None:
        self._phase_run_id = phase_run_id
        self._bus = bus
        self._passthrough = passthrough
        self._lock = threading.Lock()
        self._buffer = ""

    def write(self, data: str) -> int:
        if not isinstance(data, str):
            data = str(data)
        with self._lock:
            self._buffer += data
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                self._emit(line)
            if self._passthrough is not None:
                try:
                    self._passthrough.write(data)
                except Exception:
                    pass
        return len(data)

    def flush(self) -> None:
        with self._lock:
            if self._buffer:
                self._emit(self._buffer)
                self._buffer = ""
            if self._passthrough is not None:
                try:
                    self._passthrough.flush()
                except Exception:
                    pass

    def _emit(self, line: str) -> None:
        if not line:
            return
        ts = datetime.now().isoformat(timespec="seconds")
        match = _PIKA_LINE.match(line)
        if match:
            payload = {
                "step": match.group("step").strip(),
                "status": match.group("status").strip(),
                "detail": match.group("detail").strip(),
                "ts": ts,
            }
        else:
            payload = {"raw": line, "ts": ts}
        self._bus.publish(
            self._phase_run_id,
            {"event": "progress", "data": payload},
        )

    def isatty(self) -> bool:
        return False


@contextlib.contextmanager
def install_stderr_capture(
    phase_run_id: str,
    bus: "PhaseRunEventBus",
    *,
    passthrough: bool = True,
) -> Iterator[None]:
    """Replace `sys.stderr` with a bus-publishing writer for the context's lifetime."""
    original = sys.stderr
    writer = _BusWriter(phase_run_id, bus, passthrough=original if passthrough else None)
    sys.stderr = writer
    try:
        yield
    finally:
        writer.flush()
        sys.stderr = original


__all__ = ["install_stderr_capture"]
