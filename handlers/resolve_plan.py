"""Handler for `agent resolve_plan` — Resolution Organizer (Phase 2/4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.context import RuntimeContext
from core.lifecycle import (
    append_manual_resolution_items_to_file,
    has_blocking_manual_resolution,
    invoke_agent_with_schema_retry,
    log_lifecycle_event,
    resolve_input_path,
    resolve_output_path,
    resolve_output_schema_path,
)


def run_resolve_plan(config: dict[str, Any], ctx: RuntimeContext) -> dict[str, Any]:
    """Execute resolve_plan command lifecycle.

    Lifecycle: load Implementation Issue Tracker + Formatted SADS ->
    invoke agent (stub) -> validate -> manual resolution ->
    translate (update Issue Tracker planning columns, persist resolution packets).
    """
    project_root = Path(ctx.project_root)

    # 3. Load required inputs
    log_lifecycle_event("lifecycle_load_inputs", command="resolve_plan", run_id=ctx.run_id)
    issue_path = resolve_input_path(
        config, project_root, "issue_tracking_path", overrides=ctx.input_overrides
    )
    design_path = resolve_input_path(
        config, project_root, "design_spec_path", overrides=ctx.input_overrides
    )
    if issue_path is None or not issue_path.exists():
        return {"command": "resolve_plan", "status": "skipped", "reason": "issue_tracking_path not configured or missing"}

    inputs = {
        "issue_tracking_content": issue_path.read_text(encoding="utf-8"),
        "issue_tracking_path": issue_path,
        "design_spec_content": design_path.read_text(encoding="utf-8") if design_path and design_path.exists() else "",
    }

    # 4. No deterministic preprocessing
    # 5. Invoke agent (stub) with schema validation and retry
    schema_path = resolve_output_schema_path(config, project_root, "resolve_plan_map_output")
    output = invoke_agent_with_schema_retry(
        prompt_name=_get_map_prompt_name(config),
        template_vars={
            "issue_tracking_content": inputs["issue_tracking_content"],
            "design_spec_content": inputs["design_spec_content"],
        },
        schema_path=schema_path,
        config=config,
        ctx=ctx,
    )

    # 7. Manual-resolution: append items to file and return blocked
    if has_blocking_manual_resolution(output):
        log_lifecycle_event("lifecycle_manual_resolution", command="resolve_plan", run_id=ctx.run_id)
        manual_path = resolve_output_path(config, project_root, "manual_resolution_file")
        if manual_path:
            append_manual_resolution_items_to_file(
                output["manual_resolution_items"],
                manual_path,
            )
        return {
            "command": "resolve_plan",
            "status": "blocked",
            "blocking_items": len(output.get("manual_resolution_items", [])),
        }

    # 8. Translate: update Issue Tracker planning columns, persist resolution packets
    log_lifecycle_event("lifecycle_translate", command="resolve_plan", run_id=ctx.run_id)
    _translate_resolve_plan(config, ctx, output, inputs)

    return {"command": "resolve_plan", "status": "completed", "dry_run": ctx.dry_run}


def _get_map_prompt_name(config: dict[str, Any]) -> str:
    """Return map prompt name for resolve_plan from config."""
    commands = config.get("commands", {})
    rp_cfg = commands.get("resolve_plan") if isinstance(commands, dict) else {}
    if isinstance(rp_cfg, dict):
        return rp_cfg.get("map_prompt_name", "map_issues_to_specs")
    return "map_issues_to_specs"


def _translate_resolve_plan(
    config: dict[str, Any],
    ctx: RuntimeContext,
    output: dict[str, Any],
    inputs: dict[str, Any],
) -> None:
    """Translate resolve_plan output: update Issue Tracker, persist resolution packets. Dry-run aware."""
    if ctx.dry_run:
        return
    # Stub: real impl would update mapped_spec_ids, issue_notes, follow_up_uncertainties, etc.
    _ = config, ctx, output, inputs
