"""Handler for `agent format` — SADS Formatter (Phase 0.b).

Deterministic normalization pipeline (no LLM). Optional agent enrichment phase
(``commands.format.enrichment.enabled: true``) fills ``module_role`` via the
``design_doc_enricher`` agent after the deterministic step completes.

Note: ``evidence_type`` and ``acceptance_criteria`` are no longer written by the
format stage. They are produced by the ``spec_testability_enricher`` agent during
the ``refine`` stage.
"""

from __future__ import annotations

import shutil
from core.time_utils import format_timestamp_local_minutes_filename
from pathlib import Path
from typing import Any

from core.contracts import get_design_spec_required_columns
from core.context import RuntimeContext
from core.format_sads import (
    load_sads_csv_or_xlsx,
    normalize_raw_sads,
    rows_to_csv,
)
from core.lifecycle import (
    get_agent_provider,
    get_run_logger,
    invoke_agent_with_schema_retry,
    log_lifecycle_event,
    resolve_format_output_path,
    resolve_format_source_path,
    resolve_output_path,
    resolve_output_schema_path,
    resolve_project_context_content,
    resolve_project_state_path,
)
from core.pika_config import get_pika_config, get_prompt_name
from handlers.implement.config import _get_impl_cfg


def validate_design_enrich_module_roles(
    output: dict[str, Any],
    allowed_module_roles: set[str],
) -> None:
    """Reject design_doc_enricher output when any ``modules[].module_role`` is not allowed.

    Roles are compared after ``strip().lower()``, matching ``implement`` workset normalization
    and ``commands.implement.allowed_module_roles``.

    Args:
        output: Parsed agent JSON with a ``modules`` array of objects.
        allowed_module_roles: Lowercase role tokens from implement config.

    Raises:
        ValueError: If a module entry has an empty or disallowed ``module_role``.
    """
    if not allowed_module_roles:
        raise ValueError(
            "design enricher module_role gate: allowed_module_roles is empty (check implement config)"
        )
    modules = output.get("modules")
    if not isinstance(modules, list):
        return
    for idx, entry in enumerate(modules):
        if not isinstance(entry, dict):
            continue
        tag = str(entry.get("module_tag", "")).strip()
        role = str(entry.get("module_role", "")).strip().lower()
        if not role:
            raise ValueError(
                f"design enricher modules[{idx}] (module_tag={tag!r}) has empty module_role"
            )
        if role not in allowed_module_roles:
            raise ValueError(
                f"design enricher module_role {role!r} for module_tag {tag!r} is not in "
                f"commands.implement.allowed_module_roles {sorted(allowed_module_roles)!r}"
            )


def run_format(config: dict[str, Any], ctx: RuntimeContext) -> dict[str, Any]:
    """Execute format command lifecycle.

    Lifecycle: load Raw SADS -> deterministic preprocess (normalize) -> translate.
    No agent invocation; no schema validation; no manual resolution.

    Transform steps:
    1. Keyword replacement (sensitive dictionary)
    2. Appending missing contract columns
    3. Adding deterministic spec_ids via registry
    4. Produce normalized Draft Formatted SADS + logs
    """
    project_root = Path(ctx.project_root)

    # 3. Load required inputs
    log_lifecycle_event("lifecycle_load_inputs", command="format", run_id=ctx.run_id)
    source_path = resolve_format_source_path(
        config, project_root, ctx.input_overrides
    )
    if not source_path.exists():
        return {
            "command": "format",
            "status": "skipped",
            "reason": "source file does not exist",
        }

    inputs = {"source_path": source_path}

    # 4. Deterministic preprocessing (normalize to contract-compliant CSV)
    log_lifecycle_event("lifecycle_preprocess", command="format", run_id=ctx.run_id)
    normalized_content, format_log = normalize_raw_sads(
        source_path,
        config,
        project_root,
        dry_run=ctx.dry_run,
    )

    # Validate format output has all required Design Spec columns (including title)
    output_columns = format_log.get("output_columns") or []
    header_lower = {str(h).strip().lower(): h for h in output_columns if h}
    required = get_design_spec_required_columns()
    missing = [c for c in required if c.lower() not in header_lower]
    if missing:
        raise ValueError(
            f"Format output missing required columns: {', '.join(missing)}. "
            f"Source must provide or derive title, requirement, etc. "
            f"Contract: docs/csv_contracts.md"
        )

    # Emit format-specific log event
    _log_format_result(ctx, format_log)

    # 5. No agent for format
    # 6. No schema validation
    # 7. No manual resolution
    # 8. Translate: write Draft Formatted SADS to output (with backup if copy_before_write)
    log_lifecycle_event("lifecycle_translate", command="format", run_id=ctx.run_id)
    _translate_format(config, ctx, normalized_content, inputs)

    # 9. Optional agent enrichment: fill module_role + acceptance_criteria
    if not ctx.dry_run and _enrichment_enabled(config):
        out_file = resolve_format_output_path(config, project_root)
        if out_file is not None and out_file.exists():
            log_lifecycle_event("lifecycle_invoke_agent", command="format", run_id=ctx.run_id)
            _run_format_enrichment(config, ctx, out_file)

    return {"command": "format", "status": "completed", "dry_run": ctx.dry_run}


def _log_format_result(ctx: RuntimeContext, format_log: dict[str, Any]) -> None:
    """Emit format-specific structured log to run logger."""
    logger = get_run_logger()
    level = logger.getEffectiveLevel()
    payload: dict[str, Any] = {
        "event": "format_result",
        "command": "format",
        "run_id": ctx.run_id,
        "source_path": format_log.get("source_path"),
        "input_rows": format_log.get("input_rows"),
        "output_rows": format_log.get("output_rows"),
        "keyword_replacements": format_log.get("keyword_replacements"),
        "columns_appended": format_log.get("columns_appended"),
        "ids_assigned": format_log.get("ids_assigned"),
        "ids_preserved": format_log.get("ids_preserved"),
    }
    logger.log(level, "format_result", extra=payload)


def _translate_format(
    config: dict[str, Any],
    ctx: RuntimeContext,
    normalized_content: str,
    inputs: dict[str, Any],
) -> None:
    """Write Draft Formatted SADS to commands.format.outputs.design_spec_path.

    After writing, copy to project.state.design_spec_path.
    Backup before overwrite if copy_before_write. Backups go to backups_dir/format/.
    """
    if ctx.dry_run:
        return

    project_root = Path(ctx.project_root)
    source_path = inputs.get("source_path")
    if not isinstance(source_path, Path):
        source_path = Path(str(source_path)) if source_path else None
    if source_path is None:
        return

    out_file = resolve_format_output_path(config, project_root)
    if out_file is None:
        raise ValueError(
            "commands.format.outputs.design_spec_path is required. "
            "Add it to your project config under commands.format.outputs."
        )
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # Backup existing output if copy_before_write; backups go to backups_dir/format/
    copy_before_write = True
    cmd_format = config.get("commands", {}).get("format")
    if isinstance(cmd_format, dict):
        copy_before_write = cmd_format.get("copy_before_write", True)

    if copy_before_write and out_file.exists():
        backups_base = resolve_output_path(
            config, project_root, "backups_dir", command="format"
        )
        if backups_base:
            backups_dir = backups_base / "format"
            backups_dir.mkdir(parents=True, exist_ok=True)
            ts = format_timestamp_local_minutes_filename()
            stem = out_file.stem
            backup_name = f"{stem}_{ts}_{ctx.run_id[:8]}.csv"
            backup_path = backups_dir / backup_name
            shutil.copy2(out_file, backup_path)

    out_file.write_text(normalized_content, encoding="utf-8")

    # Final step: copy to project.state.design_spec_path
    state_design_path = resolve_project_state_path(
        config, project_root, "design_spec_path"
    )
    if state_design_path is not None and state_design_path != out_file:
        state_design_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out_file, state_design_path)


def _enrichment_enabled(config: dict[str, Any]) -> bool:
    """Return True when commands.format.enrichment.enabled is set to True."""
    cmd_format = (config.get("commands") or {}).get("format")
    if not isinstance(cmd_format, dict):
        return False
    enrichment = cmd_format.get("enrichment")
    if not isinstance(enrichment, dict):
        return False
    return bool(enrichment.get("enabled", False))


def _enrichment_skip_filled(config: dict[str, Any]) -> bool:
    """Return True (default) when already-populated rows should be skipped."""
    cmd_format = (config.get("commands") or {}).get("format")
    if not isinstance(cmd_format, dict):
        return True
    enrichment = cmd_format.get("enrichment")
    if not isinstance(enrichment, dict):
        return True
    return bool(enrichment.get("skip_filled", True))


def _run_format_enrichment(
    config: dict[str, Any],
    ctx: RuntimeContext,
    out_file: Path,
) -> None:
    """Invoke design_doc_enricher agent and apply module_role only.

    Loads the written CSV, identifies rows needing module_role enrichment, invokes
    the agent, then applies module_role and re-writes the CSV file.

    Note: evidence_type and acceptance_criteria are no longer written here.
    They are produced by the spec_testability_enricher agent during the refine stage.

    Args:
        config: Full workspace config.
        ctx: Runtime context (provider, run_id, project_root, etc.).
        out_file: Path to the Draft Formatted SADS CSV already written to disk.
    """
    project_root = Path(ctx.project_root)
    headers, rows = load_sads_csv_or_xlsx(out_file)
    if not rows:
        return

    skip_filled = _enrichment_skip_filled(config)

    # Identify rows that need module_role enrichment
    header_lower = {h.strip().lower(): h for h in headers if h}
    module_role_col = header_lower.get("module_role", "module_role")
    spec_id_col = header_lower.get("spec_id", "spec_id")
    module_tag_col = header_lower.get("module_tag", "module_tag")
    req_col = header_lower.get("requirement", "requirement")

    if skip_filled:
        rows_to_enrich = [
            r for r in rows
            if not r.get(module_role_col, "").strip()
        ]
    else:
        rows_to_enrich = list(rows)

    if not rows_to_enrich:
        return

    # Build minimal CSV payload for the agent (spec_id, module_tag, requirement)
    enrich_headers = [
        h for h in [spec_id_col, module_tag_col, req_col]
        if h in headers or h in header_lower.values()
    ]
    specs_csv = rows_to_csv(enrich_headers, rows_to_enrich)

    # Resolve prompt and schema
    provider = get_agent_provider(config)
    prompt_name = get_prompt_name("format", "enricher", provider=provider)
    pika_cfg = get_pika_config()
    schema_key = "enrich_output"
    schema_path = resolve_output_schema_path(pika_cfg, project_root, schema_key)

    # Optional project context (best-effort; enricher does not require a codebase dir)
    _pc_filename = (
        ((config.get("commands") or {}).get("format") or {})
        .get("inputs", {})
        .get("project_context_filename", "PROJECT_CONTEXT.md")
    )
    _pc_path = project_root / _pc_filename
    project_context = _pc_path.read_text(encoding="utf-8") if _pc_path.exists() else ""

    impl_cfg = _get_impl_cfg(config)
    allowed_role_set: set[str] = set(impl_cfg.get("allowed_module_roles") or [])
    allowed_roles = sorted(allowed_role_set)
    allowed_module_roles = ", ".join(allowed_roles)

    template_vars: dict[str, Any] = {
        "output_schema_file": str(schema_path) if schema_path else "",
        "specs_csv": specs_csv,
        "allowed_module_roles": allowed_module_roles,
    }
    if project_context:
        template_vars["project_context"] = project_context

    def _post_validate_enrich(out: dict[str, Any]) -> None:
        validate_design_enrich_module_roles(out, allowed_role_set)

    agent_output = invoke_agent_with_schema_retry(
        prompt_name,
        template_vars,
        schema_path=schema_path,
        config=config,
        ctx=ctx,
        post_schema_validate=_post_validate_enrich,
    )

    # Apply module_role enrichment deterministically
    module_role_by_tag: dict[str, str] = {
        m["module_tag"]: m["module_role"]
        for m in (agent_output.get("modules") or [])
        if isinstance(m, dict) and m.get("module_tag") and m.get("module_role")
    }

    # Ensure module_role column exists in headers
    new_headers = list(headers)
    if module_role_col not in new_headers:
        new_headers.append(module_role_col)

    enriched_count = 0
    new_rows: list[dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        mtag = r.get(module_tag_col, "").strip()
        changed = False

        if not skip_filled or not r.get(module_role_col, "").strip():
            role = module_role_by_tag.get(mtag, "")
            if role:
                r[module_role_col] = role
                changed = True

        if changed:
            enriched_count += 1
        new_rows.append(r)

    enriched_csv = rows_to_csv(new_headers, new_rows)
    out_file.write_text(enriched_csv, encoding="utf-8")

    # Sync enriched CSV to project.state.design_spec_path
    state_design_path = resolve_project_state_path(config, project_root, "design_spec_path")
    if state_design_path is not None and state_design_path != out_file:
        state_design_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out_file, state_design_path)

    # Log enrichment result
    logger = get_run_logger()
    logger.log(
        logger.getEffectiveLevel(),
        "format_enrichment_result",
        extra={
            "event": "format_enrichment_result",
            "command": "format",
            "run_id": ctx.run_id,
            "rows_enriched": enriched_count,
            "modules_filled": len(module_role_by_tag),
        },
    )
