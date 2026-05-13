"""Phase: refine.decomposition-check — NLP structural analysis with optional manual gate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.context import RuntimeContext
from core.phase_registry import PhaseRegistry
from core.phase_types import (
    PhaseBlocked,
    PhaseCompleted,
    PhaseContract,
    PhaseFailed,
    PhaseInput,
    PhaseOutput,
    PhaseResult,
)
from core.format_sads import load_sads_csv_or_xlsx, rows_to_csv
from core.resolution import (
    RESOLUTION_SOURCE_VALIDATION,
    load_resolution_file,
    validate_resolutions,
)

from handlers.refine.config import _get_refine_cfg
from handlers.refine.decomposition import _build_decomposition_items, run_decomposition_check
from handlers.refine.impl import (
    _REQUIRED_COLUMNS,
    _validate_required_columns,
)
from handlers.refine.phases import _write_json, write_phase_resolution_block
from handlers.resolve import apply_structural_edits


DECOMPOSITION_CHECK = PhaseContract(
    name="refine.decomposition-check",
    command="refine",
    inputs=(
        PhaseInput(
            name="design_spec_path",
            kind="workspace_relative_path",
            required=True,
            description="Path to SADS CSV/XLSX relative to the workspace root (or absolute).",
        ),
    ),
    outputs=(
        PhaseOutput(name="decomposition_flags", path="decomposition_flags.json"),
        PhaseOutput(name="restructured_csv", path="restructured.csv"),
    ),
    recommended_prerequisites=(),
    can_block=True,
    destructive=False,
    description=(
        "Detect structural issues in specs (split/merge candidates) via NLP "
        "sentence-embedding analysis. Blocks on items requiring user clarification."
    ),
)


def _apply_decomposition_resolutions(
    design_path: Path,
    resolutions: dict[str, Any],
    restructured_path: Path,
) -> dict[str, Any]:
    """Apply resolved decomposition items deterministically and write restructured.csv."""
    headers, rows = load_sads_csv_or_xlsx(design_path)
    items = resolutions.get("items") or []
    summary = {"items_total": len(items), "skipped": 0, "applied": 0, "no_op": 0}
    for item in items:
        if not isinstance(item, dict):
            continue
        chosen = str(item.get("chosen_option_id", "")).strip()
        if chosen == "skip":
            summary["skipped"] += 1
            continue
        if chosen == "let_agent_edit":
            editor_output = item.get("editor_output")
            if isinstance(editor_output, dict) and editor_output.get("edit_type") == "structural":
                edits = editor_output.get("edits") or []
                rows = apply_structural_edits(rows, headers, edits)
                summary["applied"] += len(edits)
            else:
                summary["no_op"] += 1
            continue
        summary["no_op"] += 1
    restructured_path.parent.mkdir(parents=True, exist_ok=True)
    restructured_path.write_text(rows_to_csv(headers, rows), encoding="utf-8")
    return summary


def run(
    config: dict[str, Any],
    ctx: RuntimeContext,
    phase_run_dir: Path,
    inputs: dict[str, Any],
) -> PhaseResult:
    phase_run_id = phase_run_dir.name or ctx.run_id

    design_spec_path = inputs.get("design_spec_path")
    if design_spec_path is None:
        return PhaseFailed(error_code="inputs_invalid", message="design_spec_path is required")
    design_path = Path(design_spec_path)
    if not design_path.exists():
        phase_run_dir.mkdir(parents=True, exist_ok=True)
        return PhaseFailed(
            error_code="input_missing",
            message=f"design_spec_path does not exist: {design_path}",
        )

    phase_run_dir.mkdir(parents=True, exist_ok=True)
    flags_path = phase_run_dir / "decomposition_flags.json"
    restructured_path = phase_run_dir / "restructured.csv"
    manual_dir = phase_run_dir / "manual_resolution"

    resolutions = load_resolution_file(phase_run_dir)
    if resolutions is not None:
        is_valid, _errors = validate_resolutions(resolutions)
        if not is_valid:
            flags_existing: dict[str, Any] = {}
            if flags_path.exists():
                try:
                    flags_existing = json.loads(flags_path.read_text(encoding="utf-8"))
                except Exception:
                    flags_existing = {}
            items_remaining = _build_decomposition_items(flags_existing)
            return PhaseBlocked(
                manual_dir=manual_dir,
                item_count=len(items_remaining),
                blocking_reason=f"decomposition: {len(items_remaining)} structural issues",
            )
        applied_summary = _apply_decomposition_resolutions(
            design_path, resolutions, restructured_path,
        )
        artifacts_index = {"restructured_csv": "restructured.csv"}
        if flags_path.exists():
            artifacts_index["decomposition_flags"] = "decomposition_flags.json"
        return PhaseCompleted(
            artifacts_index=artifacts_index,
            summary={"resume": True, **applied_summary},
        )

    cfg = _get_refine_cfg(config)

    if not cfg["decomposition_enabled"]:
        prior_artifacts = (
            flags_path.exists()
            or restructured_path.exists()
            or manual_dir.exists()
        )
        if prior_artifacts:
            return PhaseFailed(
                error_code="invalid_state",
                message=(
                    "decomposition is disabled in config but phase_run_dir has prior "
                    "artifacts — cannot apply a fresh-run skip to a non-fresh dir."
                ),
            )
        return PhaseCompleted(
            artifacts_index={},
            summary={"skipped": True, "reason": "decomposition_disabled"},
        )

    headers, rows = load_sads_csv_or_xlsx(design_path)
    _validate_required_columns(headers, _REQUIRED_COLUMNS)

    flags = run_decomposition_check(
        rows,
        similarity_threshold=cfg["similarity_threshold"],
        variance_threshold=cfg["variance_threshold"],
    )
    _write_json(flags_path, flags)

    n_split = len(flags.get("split_candidates", []) or [])
    n_merge = len(flags.get("merge_candidates", []) or [])
    skipped = bool(flags.get("skipped", False))

    if cfg["decomposition_blocking"] and not skipped:
        items = _build_decomposition_items(flags)
        if items:
            write_phase_resolution_block(
                items,
                manual_dir,
                "decomposition",
                phase_run_dir,
                phase_run_id,
                RESOLUTION_SOURCE_VALIDATION,
            )
            return PhaseBlocked(
                manual_dir=manual_dir,
                item_count=len(items),
                blocking_reason=f"decomposition: {len(items)} structural issues",
            )

    return PhaseCompleted(
        artifacts_index={"decomposition_flags": "decomposition_flags.json"},
        summary={
            "split_candidates": n_split,
            "merge_candidates": n_merge,
            "skipped": skipped,
        },
    )


def register(registry: PhaseRegistry) -> None:
    if registry.contract(DECOMPOSITION_CHECK.name) is None:
        registry.register(DECOMPOSITION_CHECK, run)
