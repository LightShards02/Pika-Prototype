"""Per-workspace asyncio lock manager."""

from __future__ import annotations

import asyncio
import threading


class WorkspaceLockManager:
    """Lazily-created asyncio.Lock per workspace_id."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._lock = threading.Lock()

    def get(self, workspace_id: str) -> asyncio.Lock:
        with self._lock:
            lock = self._locks.get(workspace_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[workspace_id] = lock
            return lock


__all__ = ["WorkspaceLockManager"]
