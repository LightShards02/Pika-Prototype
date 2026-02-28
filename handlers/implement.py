"""Handler for `agent implement` — Implementer (Phase 1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.context import RuntimeContext
from core.codebase_snapshot import build_codebase_snapshot
from core.format_sads import write_agent_view_csv
from core.lifecycle import (
    append_manual_resolution_items_to_file,
    get_agent_provider,
    has_blocking_manual_resolution,
    invoke_agent_with_schema_retry,
    log_lifecycle_event,
    resolve_codebase_dir_path,
    resolve_input_path,
    resolve_output_path,
    resolve_output_schema_path,
    resolve_project_context_content,
)


def run_implement(config: dict[str, Any], ctx: RuntimeContext) -> dict[str, Any]:
    """Execute implement command lifecycle.

    Lifecycle: load Formatted SADS -> invoke agent (stub) -> validate ->
    manual resolution -> translate (apply diffs to code, update tracker).
    """
    project_root = Path(ctx.project_root)

    # 3. Load required inputs
    log_lifecycle_event("lifecycle_load_inputs", command="implement", run_id=ctx.run_id)
    design_path = resolve_input_path(
        config, project_root, "design_spec_path", overrides=ctx.input_overrides
    )
    if design_path is None or not design_path.exists():
        return {"command": "implement", "status": "skipped", "reason": "design_spec_path not configured or missing"}

    # Write agent-view CSV (slim spec for prompts); overwritten each run
    design_spec_content = design_path.read_text(encoding="utf-8")
    agent_view_path = resolve_output_path(config, project_root, "agent_view_csv")
    agent_view_content = design_spec_content
    if agent_view_path:
        agent_view_content = write_agent_view_csv(
            design_path,
            agent_view_path,
            dry_run=ctx.dry_run,
        )
        if not agent_view_content:
            agent_view_content = design_spec_content

    inputs = {
        "design_spec_content": design_spec_content,
        "design_spec_path": design_path,
        "agent_view_content": agent_view_content,
    }

    # 4. No deterministic preprocessing
    # 5. Invoke agent (stub) with schema validation and retry
    template_vars = _build_template_vars(config, project_root, ctx, inputs)
    schema_path = resolve_output_schema_path(config, project_root, "implement_output")
    output = invoke_agent_with_schema_retry(
        prompt_name=_get_prompt_name(config),
        template_vars=template_vars,
        schema_path=schema_path,
        config=config,
        ctx=ctx,
    )

    # 7. Manual-resolution: append items to file and return blocked
    if has_blocking_manual_resolution(output):
        log_lifecycle_event("lifecycle_manual_resolution", command="implement", run_id=ctx.run_id)
        manual_path = resolve_output_path(config, project_root, "manual_resolution_file")
        if manual_path:
            append_manual_resolution_items_to_file(
                output["manual_resolution_items"],
                manual_path,
            )
        return {
            "command": "implement",
            "status": "blocked",
            "blocking_items": len(output.get("manual_resolution_items", [])),
        }

    # 8. Translate: apply diffs to code, update implementation-status columns
    log_lifecycle_event("lifecycle_translate", command="implement", run_id=ctx.run_id)
    _translate_implement(config, ctx, output, inputs)

    return {"command": "implement", "status": "completed", "dry_run": ctx.dry_run}


def _build_template_vars(
    config: dict[str, Any],
    project_root: Path,
    ctx: RuntimeContext,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """Build template variables for implement_from_specs prompt."""
    manual_path = resolve_output_path(config, project_root, "manual_resolution_file")
    run_summary_path = resolve_output_path(config, project_root, "run_summary_file")
    schema_path = resolve_output_schema_path(config, project_root, "implement_output")
    schema_file = str(schema_path) if schema_path and schema_path.exists() else ""
    artifacts_dir = resolve_output_path(config, project_root, "agent_artifacts_dir")
    artifacts_path = (artifacts_dir / ctx.run_id) if (artifacts_dir and ctx.run_id) else artifacts_dir

    # Resolve codebase_dir: CLI/config or default to project_root
    codebase_dir_path = resolve_codebase_dir_path(config, project_root, ctx)

    # Resolve project_context: CLI path or codebase_dir/project_context_filename
    project_context_content = resolve_project_context_content(
        config, project_root, ctx, codebase_dir_path
    )

    # Build codebase snapshot for API providers (includes raw files for implement)
    provider = get_agent_provider(config)
    codebase_content = ""
    if provider not in ("local", "stub"):
        codebase_content = build_codebase_snapshot(codebase_dir_path, config, command="implement")

    return {
        "output_schema_file": schema_file,
        "project_context": project_context_content,
        "selected_specs_csv": inputs.get("agent_view_content", inputs.get("design_spec_content", "")),
        "design_spec_column_definitions": "",
        "indexed_mappings_csv": "",
        "codebase_dir": str(codebase_dir_path),
        "codebase_content": codebase_content,
        "manual_resolution_file": str(manual_path) if manual_path else "",
        "run_summary_file": str(run_summary_path) if run_summary_path else "",
        "agent_artifacts_dir": str(artifacts_path) if artifacts_path else "",
    }


def _get_prompt_name(config: dict[str, Any]) -> str:
    """Return prompt name for implement from config."""
    commands = config.get("commands", {})
    impl_cfg = commands.get("implement") if isinstance(commands, dict) else {}
    if isinstance(impl_cfg, dict):
        return impl_cfg.get("prompt_name", "implement_from_specs")
    return "implement_from_specs"


def _translate_implement(
    config: dict[str, Any],
    ctx: RuntimeContext,
    output: dict[str, Any],
    inputs: dict[str, Any],
) -> None:
    """Translate implement output: apply diffs to code, update tracker. Dry-run aware.

    Each diff has path (target file), action, diff_path (file containing unified diff),
    and spec_ids. Read diff content from diff_path, then apply to target.
    """
    if ctx.dry_run:
        return
    project_root = Path(ctx.project_root)
    for d in output.get("diffs", []):
        diff_path = Path(d.get("diff_path", ""))
        if not diff_path.is_absolute():
            diff_path = (project_root / diff_path).resolve()
        # Stub: real impl would read diff_path.read_text() and apply patch to d["path"]
        _ = config, inputs, diff_path, d
