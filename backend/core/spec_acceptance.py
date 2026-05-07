"""Per-spec acceptance criteria + evidence_type + test_plan loader.

Single source of truth for downstream consumers (implement evaluator, review)
that need the spec_id -> {acceptance_criteria, evidence_type} mapping or the
spec_id -> {criteria, test_plan} structured side-files without re-parsing
artifacts themselves.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from core.format_sads import load_sads_csv_or_xlsx

_SPEC_ID_COL = "spec_id"
_AC_COL = "acceptance_criteria"
_EVIDENCE_COL = "evidence_type"
_TEST_PLANS_REL_PATH = ("out", "state", "test_plans")


def load_spec_acceptance_criteria(
    design_spec_csv_path: Path,
) -> dict[str, dict[str, str]]:
    """Return per-spec acceptance criteria and evidence_type from a SADS CSV/XLSX.

    Args:
        design_spec_csv_path: Path to a SADS-shaped CSV or XLSX file.

    Returns:
        Mapping of spec_id -> {"acceptance_criteria": str, "evidence_type": str}.
        Skips rows with empty spec_id or empty acceptance_criteria.
        Returns an empty dict if the file is missing, the spec_id column is
        absent, or the acceptance_criteria column is absent.
        evidence_type defaults to "" (empty) if the column is missing or the
        cell is empty.
    """
    if not design_spec_csv_path.exists():
        return {}
    headers, rows = load_sads_csv_or_xlsx(design_spec_csv_path)
    if _SPEC_ID_COL not in headers or _AC_COL not in headers:
        return {}
    has_evidence = _EVIDENCE_COL in headers
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        spec_id = str(row.get(_SPEC_ID_COL, "")).strip()
        ac = str(row.get(_AC_COL, "")).strip()
        if not spec_id or not ac:
            continue
        evidence = str(row.get(_EVIDENCE_COL, "")).strip() if has_evidence else ""
        out[spec_id] = {
            "acceptance_criteria": ac,
            "evidence_type": evidence,
        }
    return out


def filter_to_spec_ids(
    acceptance_map: Mapping[str, dict[str, str]],
    spec_ids: set[str] | list[str],
) -> dict[str, dict[str, str]]:
    """Restrict an acceptance map to a subset of spec_ids.

    Convenience for downstream callers that only need entries for the specs
    selected for the current run/batch.
    """
    wanted = set(spec_ids)
    return {sid: payload for sid, payload in acceptance_map.items() if sid in wanted}


def load_spec_test_plans(
    project_root: Path,
    spec_ids: set[str] | list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return per-spec structured criteria + test_plan side-files.

    Reads ``<project_root>/out/state/test_plans/<spec_id>.json`` files written
    by refine's testability enricher (P2). Each file's payload shape is
    ``{spec_id, criteria?, test_plan?}``.

    Args:
        project_root: Workspace root (the same path used as ``--project-root``).
        spec_ids: Optional filter. When provided, only returns entries whose
            spec_id is in the set. When None, returns everything in the
            test_plans directory.

    Returns:
        Mapping of spec_id -> the file's payload dict (containing optional
        ``criteria`` array and optional ``test_plan`` object). Returns an
        empty dict when the test_plans directory does not exist.
        Files that fail to parse as JSON are silently skipped — refine is the
        single writer, so corruption indicates external tampering and the
        downstream consumer (implement) should treat it as missing.
    """
    test_plans_dir = project_root.joinpath(*_TEST_PLANS_REL_PATH)
    if not test_plans_dir.exists():
        return {}
    wanted: set[str] | None = None if spec_ids is None else set(spec_ids)
    out: dict[str, dict[str, Any]] = {}
    for entry in test_plans_dir.iterdir():
        if not entry.is_file() or entry.suffix.lower() != ".json":
            continue
        sid = entry.stem.strip()
        if not sid:
            continue
        if wanted is not None and sid not in wanted:
            continue
        try:
            payload = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        out[sid] = payload
    return out
