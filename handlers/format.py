"""Handler for `agent format` — SADS Formatter (Phase 0.b; deterministic only; no LLM)."""

from __future__ import annotations

import shutil
from core.time_utils import format_timestamp_local_minutes_filename
from pathlib import Path
from typing import Any

from core.context import RuntimeContext
from core.format_sads import normalize_raw_sads
from core.lifecycle import (
    get_run_logger,
    log_lifecycle_event,
    resolve_input_path,
    resolve_output_path,
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
    raw_path = resolve_input_path(
        config, project_root, "raw_sads_path", overrides=ctx.input_overrides
    )
    design_path = resolve_input_path(
        config, project_root, "design_spec_path", overrides=ctx.input_overrides
    )
    # Format can use raw_sads_path or design_spec_path as source
    source_path = raw_path if (raw_path and raw_path.exists()) else design_path
    if source_path is None or not source_path.exists():
        return {
            "command": "format",
            "status": "skipped",
            "reason": "raw_sads_path/design_spec_path not configured or missing",
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

    # Emit format-specific log event
    _log_format_result(ctx, format_log)

    # 5. No agent for format
    # 6. No schema validation
    # 7. No manual resolution
    # 8. Translate: write Draft Formatted SADS to output (with backup if copy_before_write)
    log_lifecycle_event("lifecycle_translate", command="format", run_id=ctx.run_id)
    _translate_format(config, ctx, normalized_content, inputs)

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


def _output_filename_from_source(source_path: Path) -> str:
    """Derive output CSV filename from source: formatted_{original_stem}.csv."""
    stem = source_path.stem
    return f"formatted_{stem}.csv"


def _translate_format(
    config: dict[str, Any],
    ctx: RuntimeContext,
    normalized_content: str,
    inputs: dict[str, Any],
) -> None:
    """Write Draft Formatted SADS to normalized_dir as formatted_{original_name}.csv.

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

    out_dir = resolve_output_path(config, project_root, "normalized_dir")
    if not out_dir:
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    out_filename = _output_filename_from_source(source_path)
    out_file = out_dir / out_filename

    # Backup existing output if copy_before_write; backups go to backups_dir/format/
    copy_before_write = True
    cmd_format = config.get("commands", {}).get("format")
    if isinstance(cmd_format, dict):
        copy_before_write = cmd_format.get("copy_before_write", True)

    if copy_before_write and out_file.exists():
        backups_base = resolve_output_path(config, project_root, "backups_dir")
        if backups_base:
            backups_dir = backups_base / "format"
            backups_dir.mkdir(parents=True, exist_ok=True)
            ts = format_timestamp_local_minutes_filename()
            backup_name = f"{out_filename.removesuffix('.csv')}_{ts}_{ctx.run_id[:8]}.csv"
            backup_path = backups_dir / backup_name
            shutil.copy2(out_file, backup_path)

    out_file.write_text(normalized_content, encoding="utf-8")
