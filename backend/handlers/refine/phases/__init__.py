"""Refine phase modules and shared phase-artifact writers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.resolution import generate_resolution_template


def _write_json(path: Path, payload: Any) -> None:
    """Write JSON deterministically with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_phase_resolution_block(
    items: list[dict[str, Any]],
    manual_dir: Path,
    stage: str,
    phase_run_dir: Path,
    phase_run_id: str,
    source: str,
    *,
    appendix_recommendations: list[dict[str, Any]] | None = None,
) -> None:
    """Phase-shape replacement for handlers.refine.impl._write_resolution_block.

    Writes manual_dir/<stage>.json + manual_dir/resolutions.yaml. Does NOT
    write run_meta.json — that is the M2b REST router's responsibility.
    """
    payload: dict[str, Any] = {
        "stage": stage,
        "format_version": 2,
        "items": items,
    }
    if appendix_recommendations:
        payload["appendix_recommendations"] = appendix_recommendations
    _write_json(manual_dir / f"{stage}.json", payload)
    generate_resolution_template(
        run_dir=phase_run_dir,
        stage=stage,
        items=items,
        command="refine",
        run_id=phase_run_id,
        source=source,
    )


__all__ = ["write_phase_resolution_block"]
