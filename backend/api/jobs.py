"""Phase-run identifier generation and on-disk directory helpers."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from core.lifecycle import resolve_phase_run_dir


_id_lock = threading.Lock()
_last_second: str | None = None
_counter: int = 0


def generate_phase_run_id(now: datetime | None = None) -> str:
    """Return phase run id of the form YYYYMMDD-HHMMSS-XXXX (hex).

    Strictly increasing within a single process: same-second calls bump a
    counter; a new second resets the counter to 0.
    """
    global _last_second, _counter
    dt = (now or datetime.now()).astimezone()
    base = dt.strftime("%Y%m%d-%H%M%S")
    with _id_lock:
        if base == _last_second:
            _counter += 1
        else:
            _last_second = base
            _counter = 0
        if _counter > 0xFFFF:
            raise RuntimeError("phase_run_id counter exhausted within one second")
        suffix = f"{_counter:04x}"
    return f"{base}-{suffix}"


def phase_run_dir_for(
    config: dict[str, Any],
    project_root: Path,
    phase_name: str,
    phase_run_id: str,
) -> Path:
    return resolve_phase_run_dir(config, project_root, phase_name, phase_run_id)
