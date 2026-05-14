"""Handler for `agent review` — Design Reviewer (Design gate support)."""

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
    resolve_manual_resolution_path_for_command,
    resolve_output_schema_path,
)


def run_review(config: dict[str, Any], ctx: RuntimeContext) -> dict[str, Any]:
    """Execute review command lifecycle.

    Lifecycle: load SRS + Draft Formatted SADS -> invoke agent (stub) ->
    validate -> manual resolution -> translate (Design Issue Tracker updates).
    """
    project_root = Path(ctx.project_root)

    # 3. Load required inputs
    log_lifecycle_event("lifecycle_load_inputs", command="review", run_id=ctx.run_id)
    srs_path = resolve_input_path(
        config,
        project_root,
        "srs_path",
        overrides=ctx.input_overrides,
        command="review",
    )
    design_path = resolve_input_path(
        config,
        project_root,
        "design_spec_path",
        overrides=ctx.input_overrides,
        command="review",
    )
    if design_path is None or not design_path.exists():
        return {"command": "review", "status": "skipped", "reason": "design_spec_path not configured or missing"}
    srs_content = srs_path.read_text(encoding="utf-8") if srs_path and srs_path.exists() else ""
    inputs = {
        "srs_content": srs_content,
        "draft_sads_content": design_path.read_text(encoding="utf-8"),
        "design_spec_path": design_path,
    }

    # 4. No deterministic preprocessing
    # 5. Invoke agent (stub) with schema validation and retry
    schema_path = resolve_output_schema_path(
        config, project_root, "review_output", command="review"
    )
    from core import memory_store as _memory_store
    output = invoke_agent_with_schema_retry(
        prompt_name=_get_prompt_name(config),
        template_vars={
            "srs_content": inputs["srs_content"],
            "draft_sads_content": inputs["draft_sads_content"],
            "memory": _memory_store.memory_template_value(ctx),
        },
        schema_path=schema_path,
        config=config,
        ctx=ctx,
    )

    # 7. Manual-resolution: append items to file and return blocked
    if has_blocking_manual_resolution(output):
        log_lifecycle_event("lifecycle_manual_resolution", command="review", run_id=ctx.run_id)
        manual_path = resolve_manual_resolution_path_for_command(config, project_root, "review")
        append_manual_resolution_items_to_file(
            output["manual_resolution_items"],
            manual_path,
        )
        return {
            "command": "review",
            "status": "blocked",
            "blocking_items": len(output.get("manual_resolution_items", [])),
        }

    # 8. Translate: update Design Issue Tracker
    log_lifecycle_event("lifecycle_translate", command="review", run_id=ctx.run_id)
    _translate_review(config, ctx, output, inputs)

    return {"command": "review", "status": "completed", "dry_run": ctx.dry_run}


def _get_prompt_name(config: dict[str, Any]) -> str:
    """Return prompt name for review from pika.yaml."""
    from core.pika_config import get_prompt_name
    return get_prompt_name("review")


def _translate_review(
    config: dict[str, Any],
    ctx: RuntimeContext,
    output: dict[str, Any],
    inputs: dict[str, Any],
) -> None:
    """Translate review output into Design Issue Tracker updates. Dry-run aware."""
    if ctx.dry_run:
        return
    # Stub: real impl would update Design Issue Tracker per contract
    _ = config, ctx, output, inputs
