"""Shared helper utilities for implement handler submodules."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from core.constants import EscalationKind
from core.resolution import (
    RESOLUTION_SOURCE_AGENT,
    RESOLUTION_SOURCE_VALIDATION,
    generate_resolution_template,
)


def _report_implement_phase(phase: str, status: str, detail: str) -> None:
    """Print a phase step to stderr with status and detail."""
    print(f"[PIKA] {phase}: {status} — {detail}", file=sys.stderr)


def _write_json(path: Path, payload: Any) -> None:
    """Write JSON to disk with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _sha256(payload: bytes) -> str:
    """Compute SHA-256 hex digest."""
    return hashlib.sha256(payload).hexdigest()


def _find_col(headers: list[str], name: str) -> str | None:
    """Return first matching header by case-insensitive name."""
    mapping = {h.strip().lower(): h for h in headers if h}
    return mapping.get(name.lower())


def _manual_block(
    output: dict[str, Any] | None,
    manual_dir: Path,
    stage: str,
    *,
    run_dir: Path,
    command: str,
    run_id: str,
    completed_stages: list[str],
    source: str = RESOLUTION_SOURCE_AGENT,
    spec_rows: list[dict[str, Any]] | None = None,
    headers: list[str] | None = None,
    shared_contracts: list[dict[str, Any]] | None = None,
    items: list[dict[str, Any]] | None = None,
) -> bool:
    """Persist manual resolution payload and return True when output is blocking.

    When blocking: writes stage JSON, generates resolutions.yaml template,
    and updates run_meta.json with blocked_at_stage and completed_stages.

    Items can come from output['manual_resolution_items'] or be passed directly
    via the items parameter (e.g. for validation-originated blocks).
    """
    if items is None and output is not None:
        items = output.get("manual_resolution_items")
    if not isinstance(items, list) or not items:
        return False

    _write_json(manual_dir / f"{stage}.json", {"stage": stage, "items": items})
    generate_resolution_template(
        run_dir=run_dir,
        stage=stage,
        items=items,
        command=command,
        run_id=run_id,
        source=source,
        spec_rows=spec_rows,
        headers=headers,
        shared_contracts=shared_contracts,
    )

    kinds_set: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_kind = item.get("kind")
        if isinstance(raw_kind, str) and raw_kind.strip():
            kinds_set.add(raw_kind.strip())
        else:
            kinds_set.add(EscalationKind.GENERIC.value)
    escalation_kinds = sorted(kinds_set)

    run_meta_path = run_dir / "run_meta.json"
    run_meta: dict[str, Any] = {}
    if run_meta_path.exists():
        try:
            run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    run_meta["blocked_at_stage"] = stage
    run_meta["completed_stages"] = completed_stages
    run_meta["resolution_status"] = "pending"
    run_meta["escalation_kinds"] = escalation_kinds
    _write_json(run_meta_path, run_meta)

    return True
