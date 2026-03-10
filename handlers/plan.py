"""Handler for `agent plan` — Project Designer (Phase 0.a)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.context import RuntimeContext

# Design Spec (SADS) column definitions per docs/csv_contracts.md
DESIGN_SPEC_COLUMN_DEFINITIONS = """
spec_id: Required. Stable deterministic spec identifier (one letter + number, e.g. A1001).
title: Required. Human-readable requirement title.
requirement: Required. Core requirement statement. Embed unit logic, feature logic, edge cases, error handling, class/helper descriptions.
acceptance_criteria: Optional. Concrete acceptance criteria for verification.
implementation_status: Optional. User workflow status for the spec row.
"""
from core.lifecycle import (
    has_blocking_manual_resolution,
    invoke_agent_with_schema_retry,
    log_lifecycle_event,
    persist_manual_resolution_block_for_run,
    resolve_agent_artifacts_dir_for_command,
    resolve_agent_runs_dir_for_command,
    resolve_codebase_dir_path,
    resolve_input_path,
    resolve_output_schema_path,
    resolve_project_context_content,
    resolve_resolution_template_path_for_run,
    resolve_run_summary_path_for_command,
)


def run_plan(config: dict[str, Any], ctx: RuntimeContext) -> dict[str, Any]:
    """Execute plan command lifecycle.

    Lifecycle: load SRS -> invoke agent (stub) -> validate -> manual resolution -> translate.
    """
    project_root = Path(ctx.project_root)

    # 3. Load required inputs
    log_lifecycle_event("lifecycle_load_inputs", command="plan", run_id=ctx.run_id)
    srs_path = resolve_input_path(
        config, project_root, "srs_path",
        overrides=ctx.input_overrides, command="plan",
    )
    if srs_path is None or not srs_path.exists():
        return {"command": "plan", "status": "skipped", "reason": "srs_path not configured or missing"}

    inputs = {"srs_content": srs_path.read_text(encoding="utf-8")}

    # Build template vars for project_designer prompt
    template_vars = _build_template_vars(config, project_root, ctx, inputs)

    # 4. No deterministic preprocessing for plan
    # 5. Invoke agent (stub) with schema validation and retry
    schema_path = resolve_output_schema_path(
        config, project_root, "plan_output", command="plan"
    )
    output = invoke_agent_with_schema_retry(
        prompt_name=_get_prompt_name(config),
        template_vars=template_vars,
        schema_path=schema_path,
        config=config,
        ctx=ctx,
    )

    # 7. Manual-resolution: append items to file and return blocked
    if has_blocking_manual_resolution(output):
        log_lifecycle_event("lifecycle_manual_resolution", command="plan", run_id=ctx.run_id)
        persist_manual_resolution_block_for_run(
            config,
            project_root,
            "plan",
            ctx.run_id,
            "plan",
            output["manual_resolution_items"],
            source="agent",
            completed_stages=["load_inputs", "invoke_agent"],
        )
        return {
            "command": "plan",
            "status": "blocked",
            "blocking_items": len(output.get("manual_resolution_items", [])),
        }

    # 8. Translate output (stub: write planning artifacts)
    log_lifecycle_event("lifecycle_translate", command="plan", run_id=ctx.run_id)
    _ensure_stub_artifact(output, project_root)
    _translate_plan(config, ctx, output, inputs)

    return {"command": "plan", "status": "completed", "dry_run": ctx.dry_run}


def _build_template_vars(
    config: dict[str, Any],
    project_root: Path,
    ctx: RuntimeContext,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """Build template variables for project_designer prompt."""
    manual_path = resolve_resolution_template_path_for_run(
        config, project_root, "plan", ctx.run_id
    )
    run_summary_path = resolve_run_summary_path_for_command(config, project_root, "plan")
    schema_path = resolve_output_schema_path(
        config, project_root, "plan_output", command="plan"
    )
    schema_file = str(schema_path) if schema_path and schema_path.exists() else ""
    run_id = ctx.run_id or "run"
    artifacts_path = resolve_agent_artifacts_dir_for_command(
        config, project_root, "plan", run_id
    )

    # Resolve codebase_dir: CLI/config or default to project_root
    codebase_dir_path = resolve_codebase_dir_path(config, project_root, ctx)

    # Resolve project_context: CLI path or codebase_dir/project_context_filename
    project_context_content = resolve_project_context_content(
        config, project_root, ctx, codebase_dir_path
    )
    return {
        "output_schema_file": schema_file,
        "srs_content": inputs.get("srs_content", ""),
        "project_context": project_context_content,
        "design_spec_column_definitions": DESIGN_SPEC_COLUMN_DEFINITIONS.strip(),
        "manual_resolution_file": str(manual_path),
        "run_summary_file": str(run_summary_path),
        "agent_artifacts_dir": str(artifacts_path),
        "resolved_decisions": ctx.resolved_decisions or "",
    }


def _get_prompt_name(config: dict[str, Any]) -> str:
    """Return prompt name for plan from config."""
    commands = config.get("commands", {})
    plan_cfg = commands.get("plan") if isinstance(commands, dict) else {}
    if isinstance(plan_cfg, dict):
        return plan_cfg.get("prompt_name", "project_designer")
    return "project_designer"


def _ensure_stub_artifact(output: dict[str, Any], project_root: Path) -> None:
    """Ensure stub proposed_sads_outline_path exists for testing (stub creates path but not file)."""
    path_val = output.get("proposed_sads_outline_path")
    if not path_val:
        return
    src = Path(path_val)
    if not src.is_absolute():
        src = (project_root / src).resolve()
    if not src.exists():
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(
            "spec_id,title,requirement,acceptance_criteria,implementation_status\n"
            "A1,Stub spec,Stub requirement with embedded unit logic.,Stub acceptance criteria,\n",
            encoding="utf-8",
        )


def _translate_plan(
    config: dict[str, Any],
    ctx: RuntimeContext,
    output: dict[str, Any],
    inputs: dict[str, Any],
) -> None:
    """Translate plan output into planning artifacts. Dry-run aware.

    Copies proposed_sads_outline from agent-written path to agent_runs_dir.
    Writes milestones JSON to agent_runs_dir.
    """
    if ctx.dry_run:
        return
    project_root = Path(ctx.project_root)
    out_dir = resolve_agent_runs_dir_for_command(config, project_root, "plan")
    out_dir.mkdir(parents=True, exist_ok=True)
    _ = inputs
    if "milestones" in output:
        milestones_path = out_dir / "plan_milestones.json"
        milestones_path.write_text(
            json.dumps(output["milestones"], indent=2),
            encoding="utf-8",
        )
    if "proposed_sads_outline_path" in output:
        src_path = Path(output["proposed_sads_outline_path"])
        if not src_path.is_absolute():
            src_path = (project_root / src_path).resolve()
        if src_path.exists():
            sads_csv_path = out_dir / "plan_proposed_sads.csv"
            sads_csv_path.write_text(src_path.read_text(encoding="utf-8"), encoding="utf-8")
