"""Per-spec acceptance criteria + evidence_type loader.

Single source of truth for downstream consumers (implement evaluator, review)
that need the spec_id -> {acceptance_criteria, evidence_type} mapping without
re-parsing the SADS CSV themselves.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from core.format_sads import load_sads_csv_or_xlsx

_SPEC_ID_COL = "spec_id"
_AC_COL = "acceptance_criteria"
_EVIDENCE_COL = "evidence_type"


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
