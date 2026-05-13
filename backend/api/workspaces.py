"""Workspace registry: content-hashed IDs persisted to disk."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkspaceRecord:
    id: str
    path: str
    exists: bool
    config_resolved: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "exists": self.exists,
            "config_resolved": self.config_resolved,
        }


def compute_workspace_id(abspath: str) -> str:
    """Workspace ID is sha256(abspath)[:12] of the absolute resolved path."""
    digest = hashlib.sha256(abspath.encode("utf-8")).hexdigest()
    return digest[:12]


def _config_resolves(path: Path) -> bool:
    """Return True when one of pika.yaml config_candidates exists under path."""
    try:
        from core.pika_config import get_pika_config
    except Exception:
        return False
    try:
        candidates = get_pika_config().get("config_candidates") or []
    except Exception:
        candidates = []
    for c in candidates:
        if isinstance(c, str) and (path / c).is_file():
            return True
    return False


class WorkspaceStore:
    """Idempotent on-disk store of registered workspaces."""

    def __init__(self, registry_path: Path) -> None:
        self._path = registry_path
        self._lock = threading.Lock()
        self._records: dict[str, WorkspaceRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        entries = data.get("workspaces")
        if not isinstance(entries, list):
            return
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            wid = entry.get("id")
            path = entry.get("path")
            if not isinstance(wid, str) or not isinstance(path, str):
                continue
            self._records[wid] = WorkspaceRecord(
                id=wid,
                path=path,
                exists=bool(entry.get("exists", False)),
                config_resolved=bool(entry.get("config_resolved", False)),
            )

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "workspaces": [r.to_dict() for r in self._records.values()],
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def register(self, raw_path: str) -> WorkspaceRecord:
        """Register a workspace. Idempotent.

        Accepts absolute or relative paths; relative is resolved against the
        server's current working directory, matching CLI ``--project-root``
        semantics. The hashed ID is always taken from the resolved absolute
        form so the same directory is the same workspace regardless of how
        the client referenced it.
        """
        if not raw_path or not raw_path.strip():
            raise ValueError("workspace path must be non-empty")
        p = Path(raw_path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"workspace path does not exist: {p}")
        if not p.is_dir():
            raise NotADirectoryError(f"workspace path is not a directory: {p}")
        abspath = str(p)
        wid = compute_workspace_id(abspath)
        with self._lock:
            existing = self._records.get(wid)
            config_resolved = _config_resolves(p)
            record = WorkspaceRecord(
                id=wid,
                path=abspath,
                exists=True,
                config_resolved=config_resolved,
            )
            if existing != record:
                self._records[wid] = record
                self._persist()
            return record

    def get(self, workspace_id: str) -> WorkspaceRecord | None:
        return self._records.get(workspace_id)

    def list(self) -> list[WorkspaceRecord]:
        return list(self._records.values())
