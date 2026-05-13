"""Phase: refine.quality-audit — spec quality auditor N replicas + consensus + enrichment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.appendix_loader import format_appendix_for_agent, load_appendix_files
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
from core.format_sads import load_sads_csv_or_xlsx
from core.lifecycle import resolve_phase_run_dir

from handlers.refine.config import _get_refine_cfg
from handlers.refine.impl import (
    _REQUIRED_COLUMNS,
    _run_refine_agents,
    _validate_required_columns,
)


QUALITY_AUDIT = PhaseContract(
    name="refine.quality-audit",
    command="refine",
    inputs=(
        PhaseInput(
            name="design_spec_path",
            kind="workspace_relative_path",
            required=False,
            description="Path to SADS CSV. Required if decomposition_check_run_id is omitted.",
        ),
        PhaseInput(
            name="decomposition_check_run_id",
            kind="phase_run_ref",
            required=False,
            description=(
                "Phase-run ID of a completed refine.decomposition-check whose "
                "restructured.csv should be used as input."
            ),
            ref_phase="refine.decomposition-check",
        ),
    ),
    outputs=(
        PhaseOutput(name="auditor_output", path="auditor_output.json"),
        PhaseOutput(name="auditor_raw_replicas", path="auditor_output_*.json"),
        PhaseOutput(name="enrichments", path="enrichments.json"),
        PhaseOutput(name="summary", path="summary.json"),
        PhaseOutput(name="enriched_csv", path="enriched.csv"),
        PhaseOutput(
            name="test_plans",
            path="out/state/test_plans/*.json",
            scope="workspace",
        ),
    ),
    recommended_prerequisites=("refine.decomposition-check",),
    can_block=True,
    destructive=False,
    description=(
        "Run spec_quality_auditor agent in N parallel replicas (1 full + N-1 triage), "
        "consensus-filter manual-resolution items, apply enrichments, and gate."
    ),
)


def _resolve_design_path(
    config: dict[str, Any],
    project_root: Path,
    inputs: dict[str, Any],
) -> tuple[Path | None, PhaseFailed | None]:
    """Resolve the design CSV path from inputs."""
    prior_run_id = inputs.get("decomposition_check_run_id")
    if prior_run_id:
        prior_dir = resolve_phase_run_dir(
            config, project_root, "refine.decomposition-check", str(prior_run_id),
        )
        artifact = prior_dir / "restructured.csv"
        if not artifact.exists():
            return None, PhaseFailed(
                error_code="prior_phase_artifact_missing",
                message=(
                    f"restructured.csv not found in prior decomposition-check run "
                    f"{prior_run_id!s} (expected at {artifact})"
                ),
            )
        return artifact, None

    raw = inputs.get("design_spec_path")
    if not raw:
        return None, PhaseFailed(
            error_code="inputs_invalid",
            message="Either design_spec_path or decomposition_check_run_id must be provided",
        )
    path = Path(raw)
    if not path.exists():
        return None, PhaseFailed(
            error_code="input_missing",
            message=f"design_spec_path does not exist: {path}",
        )
    return path, None


def _post_resolve_completed(phase_run_dir: Path) -> PhaseResult:
    """Build a PhaseCompleted from a phase-run dir that has already been resolved."""
    summary_path = phase_run_dir / "summary.json"
    artifacts_index: dict[str, str] = {}
    if (phase_run_dir / "auditor_output.json").exists():
        artifacts_index["auditor_output"] = "auditor_output.json"
    if summary_path.exists():
        artifacts_index["summary"] = "summary.json"
    summary: dict[str, Any] = {"resume": True}
    run_meta_path = phase_run_dir / "run_meta.json"
    if run_meta_path.exists():
        try:
            run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
            output_path = run_meta.get("output_design_spec_path")
            if isinstance(output_path, str) and output_path:
                summary["output_design_spec_path"] = output_path
        except Exception:
            pass
    return PhaseCompleted(artifacts_index=artifacts_index, summary=summary)


def _normalize_enriched_csv(
    output_path_raw: Any,
    phase_run_dir: Path,
    artifacts_index: dict[str, str],
    summary: dict[str, Any],
) -> None:
    """Ensure enriched_csv lands in phase_run_dir and is always indexed.

    If the workspace-configured output path is already under phase_run_dir,
    index it directly. Otherwise copy it to phase_run_dir/enriched.csv so the
    artifact contract is satisfied, and surface the original workspace path in
    summary as supplemental metadata.
    """
    if not isinstance(output_path_raw, str) or not output_path_raw:
        return
    output_path = Path(output_path_raw)
    if not output_path.exists():
        return
    try:
        rel = output_path.resolve().relative_to(phase_run_dir.resolve())
        artifacts_index["enriched_csv"] = rel.as_posix()
    except ValueError:
        import shutil
        artifact = phase_run_dir / "enriched.csv"
        shutil.copy2(output_path, artifact)
        artifacts_index["enriched_csv"] = "enriched.csv"
        summary["workspace_output_path"] = str(output_path)


def run(
    config: dict[str, Any],
    ctx: RuntimeContext,
    phase_run_dir: Path,
    inputs: dict[str, Any],
) -> PhaseResult:
    project_root = Path(ctx.project_root)
    phase_run_dir.mkdir(parents=True, exist_ok=True)

    resolutions_path = phase_run_dir / "manual_resolution" / "resolutions.yaml"
    if resolutions_path.exists():
        from core.resolution import load_resolution_file, validate_resolutions

        resolutions = load_resolution_file(phase_run_dir)
        if resolutions is not None:
            is_valid, _ = validate_resolutions(resolutions)
            if is_valid:
                return _post_resolve_completed(phase_run_dir)
            item_count = len([i for i in (resolutions.get("items") or []) if isinstance(i, dict)])
            return PhaseBlocked(
                manual_dir=phase_run_dir / "manual_resolution",
                item_count=item_count,
                blocking_reason=f"agent_review: {item_count} unresolved items",
            )

    design_path, failure = _resolve_design_path(config, project_root, inputs)
    if failure is not None:
        return failure
    assert design_path is not None

    headers, rows = load_sads_csv_or_xlsx(design_path)
    _validate_required_columns(headers, _REQUIRED_COLUMNS)

    cfg = _get_refine_cfg(config)
    appendix_entries = load_appendix_files(config, project_root, command="refine")
    appendix_text = format_appendix_for_agent(
        appendix_entries, max_chars=cfg["max_appendix_chars"],
    )

    result = _run_refine_agents(
        config=config,
        ctx=ctx,
        project_root=project_root,
        run_dir=phase_run_dir,
        design_path=design_path,
        headers=headers,
        rows=rows,
        completed_stages=[],
        appendix_text=appendix_text,
    )

    status = result.get("status")
    if status == "completed":
        artifacts_index: dict[str, str] = {}
        if (phase_run_dir / "auditor_output.json").exists():
            artifacts_index["auditor_output"] = "auditor_output.json"
        if (phase_run_dir / "summary.json").exists():
            artifacts_index["summary"] = "summary.json"
        if (phase_run_dir / "enrichments.json").exists():
            artifacts_index["enrichments"] = "enrichments.json"
        summary: dict[str, Any] = {
            "specs_enriched": result.get("specs_enriched", 0),
            "appendix_recommendations": result.get("appendix_recommendations", 0),
        }
        _normalize_enriched_csv(
            result.get("output_path"), phase_run_dir, artifacts_index, summary,
        )
        if "enriched_csv" not in artifacts_index:
            return PhaseFailed(
                error_code="artifact_missing",
                message=(
                    "_run_refine_agents reported completed but no enriched CSV was "
                    f"materialized (output_path={result.get('output_path')!r})."
                ),
            )
        return PhaseCompleted(artifacts_index=artifacts_index, summary=summary)

    if status == "blocked":
        severity = result.get("severity_breakdown", "")
        blocking = int(result.get("blocking_items", 0) or 0)
        return PhaseBlocked(
            manual_dir=phase_run_dir / "manual_resolution",
            item_count=blocking,
            blocking_reason=f"agent_review: {blocking} items, severity {severity}",
        )

    return PhaseFailed(
        error_code="agents_failed",
        message=str(result.get("reason", "unknown")),
    )


def register(registry: PhaseRegistry) -> None:
    if registry.contract(QUALITY_AUDIT.name) is None:
        registry.register(QUALITY_AUDIT, run)
