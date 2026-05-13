"""Phase-run registry: in-memory + disk reflection of run_meta.json files."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Iterable


class PhaseRunRegistry:
    """Stores phase-run records, hydrated from on-disk run_meta.json on startup."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, dict[str, Any]] = {}

    def reflect_from_disk(self, agent_runs_roots: Iterable[Path]) -> int:
        """Scan each <agent_runs_root>/<phase>/<run_id>/run_meta.json and load it."""
        loaded = 0
        with self._lock:
            for root in agent_runs_roots:
                if not root.is_dir():
                    continue
                for phase_dir in root.iterdir():
                    if not phase_dir.is_dir():
                        continue
                    for run_dir in phase_dir.iterdir():
                        if not run_dir.is_dir():
                            continue
                        meta_path = run_dir / "run_meta.json"
                        if not meta_path.is_file():
                            continue
                        try:
                            meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError):
                            continue
                        if not isinstance(meta, dict):
                            continue
                        rid = meta.get("phase_run_id")
                        if isinstance(rid, str) and rid:
                            self._records[rid] = meta
                            loaded += 1
        return loaded

    def put(self, record: dict[str, Any]) -> None:
        rid = record.get("phase_run_id")
        if not isinstance(rid, str) or not rid:
            raise ValueError("phase_run_id missing from record")
        with self._lock:
            self._records[rid] = dict(record)

    def get(self, phase_run_id: str) -> dict[str, Any] | None:
        return self._records.get(phase_run_id)

    def list(self) -> list[dict[str, Any]]:
        return list(self._records.values())
