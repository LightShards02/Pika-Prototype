"""Phase: format.normalize — wraps handlers.format.run_format."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from api.phase_registry import (
    PhaseCompleted,
    PhaseContract,
    PhaseFailed,
    PhaseInput,
    PhaseOutput,
    PhaseResult,
    get_phase_registry,
)
from core.context import RuntimeContext
from core.lifecycle import resolve_format_output_path
from handlers.format import run_format


FORMAT_NORMALIZE = PhaseContract(
    name="format.normalize",
    command="format",
    inputs=(
        PhaseInput(
            name="design_spec_path",
            kind="workspace_relative_path",
            required=True,
            description="Path to Raw SADS (CSV/XLSX) relative to the workspace root.",
        ),
    ),
    outputs=(
        PhaseOutput(name="normalized", path="normalized.csv"),
    ),
    can_block=False,
    destructive=True,
    description="SADS Formatter (Phase 0.b): normalize Raw SADS into Draft Formatted SADS.",
)


def run(
    config: dict[str, Any],
    ctx: RuntimeContext,
    phase_run_dir: Path,
    inputs: dict[str, Any],
) -> PhaseResult:
    design_spec_path = inputs["design_spec_path"]
    phase_run_dir.mkdir(parents=True, exist_ok=True)

    result = run_format(config, ctx)
    status = result.get("status")
    if status == "skipped":
        return PhaseFailed(
            error_code="input_missing",
            message=str(result.get("reason") or "format input missing"),
        )
    if status != "completed":
        return PhaseFailed(
            error_code="format_failed",
            message=f"run_format returned unexpected status: {status!r}",
        )

    project_root = Path(ctx.project_root)
    workspace_output = resolve_format_output_path(config, project_root)
    artifact_path = phase_run_dir / "normalized.csv"

    if workspace_output is None:
        return PhaseFailed(
            error_code="artifact_missing",
            message="format runner completed but workspace output path could not be resolved.",
        )
    if not workspace_output.exists():
        return PhaseFailed(
            error_code="artifact_missing",
            message=f"format runner completed but expected output not found at {workspace_output}",
        )

    shutil.copy2(workspace_output, artifact_path)

    summary: dict[str, Any] = {
        "source_path": str(design_spec_path),
        "dry_run": bool(ctx.dry_run),
        "workspace_output_path": str(workspace_output),
    }
    return PhaseCompleted(
        artifacts_index={"normalized": "normalized.csv"},
        summary=summary,
    )


def register() -> None:
    registry = get_phase_registry()
    if registry.contract(FORMAT_NORMALIZE.name) is None:
        registry.register(FORMAT_NORMALIZE, run)
