"""Handler for `agent map` — SADS Mapper (Phase 2)."""

from __future__ import annotations

import json
import re
import shutil
import sys
from core.time_utils import (
    format_timestamp_local_minutes,
    format_timestamp_local_minutes_filename,
    normalize_timestamp_for_display,
)
from pathlib import Path
from typing import Any

from core.context import RuntimeContext
from core.contracts import get_design_spec_column_definitions
from core.format_sads import (
    append_missing_columns,
    build_agent_view_csv_content,
    get_design_spec_add_if_missing,
    load_sads_csv_or_xlsx,
    rows_to_csv,
)
from core.codebase_snapshot import build_codebase_snapshot
from core.lifecycle import (
    append_manual_resolution_items_to_file,
    get_agent_provider,
    get_run_logger,
    has_blocking_manual_resolution,
    invoke_agent_with_schema_retry,
    log_lifecycle_event,
    resolve_codebase_dir_path,
    resolve_input_path,
    resolve_intermediate_map_dir,
    resolve_output_path,
    resolve_output_schema_path,
    resolve_extra_prompt_content,
    resolve_project_context_content,
)

_SPEC_ID_PATTERN = re.compile(r"^[A-Za-z][0-9]+$")
_ENTITY_ID_RANGE = re.compile(r"^([A-Za-z])([0-9]+)-([A-Za-z])([0-9]+)$")


def _report_map_step(step: str, status: str, reason: str) -> None:
    """Print a merge/validation step to stderr with status and reason."""
    print(f"[PIKA] {step}: {status} — {reason}", file=sys.stderr)


def _entity_id_to_spec_ids(entity_id: str) -> set[str]:
    """Expand entity_id to a set of spec_ids. Handles single (A109) and range (A109-A342)."""
    if not isinstance(entity_id, str) or not entity_id.strip():
        return set()
    eid = entity_id.strip()
    m = _ENTITY_ID_RANGE.fullmatch(eid)
    if m:
        p1, n1, p2, n2 = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
        if p1 != p2 or n1 > n2:
            return {eid}  # Invalid range; treat as single
        return {f"{p1}{i}" for i in range(n1, n2 + 1)}
    if _SPEC_ID_PATTERN.fullmatch(eid):
        return {eid}
    return {eid}  # Unknown format; treat as single spec_id


def _normalize_code_refs(code_refs: Any) -> list[dict[str, Any]]:
    """Normalize code_refs to include consistency_score and problems. Backfill defaults for legacy data."""
    if not isinstance(code_refs, list):
        return []
    result: list[dict[str, Any]] = []
    for ref in code_refs:
        if not isinstance(ref, dict):
            continue
        # Accept legacy "notes" as "problems" for backward compatibility
        problems = ref.get("problems", ref.get("notes", ""))
        normalized = {
            "path": ref.get("path", ""),
            "symbol_name": ref.get("symbol_name", ""),
            "symbol_type": ref.get("symbol_type", "other"),
            "confidence": ref.get("confidence", 0.0),
            "consistency_score": ref.get("consistency_score", 0.0),
            "problems": problems,
        }
        # Clamp scores to [0, 1]
        conf = normalized["confidence"]
        cons = normalized["consistency_score"]
        normalized["confidence"] = max(0.0, min(1.0, conf if isinstance(conf, (int, float)) else 0.0))
        normalized["consistency_score"] = max(0.0, min(1.0, cons if isinstance(cons, (int, float)) else 0.0))
        result.append(normalized)
    return result


def _get_map_config(config: dict[str, Any], ctx: RuntimeContext) -> dict[str, Any]:
    """Return map command config with CLI overrides applied."""
    commands = config.get("commands") or {}
    map_cfg = commands.get("map") if isinstance(commands, dict) else {}
    if not isinstance(map_cfg, dict):
        map_cfg = {}
    overrides = ctx.input_overrides or {}
    skip_mapped = map_cfg.get("skip_mapped", True)
    if overrides.get("force_remap", "").lower() in ("true", "1", "yes"):
        skip_mapped = False
    max_acceptance_chars = map_cfg.get("max_acceptance_chars", 0)
    if "max_acceptance_chars" in overrides:
        try:
            max_acceptance_chars = int(overrides["max_acceptance_chars"])
        except (ValueError, TypeError):
            pass
    return {"skip_mapped": skip_mapped, "max_acceptance_chars": max_acceptance_chars}


def _validate_subunit_column(headers: list[str], rows: list[dict[str, str]]) -> None:
    """Validate that all rows have a non-empty subunit value. Raise ValueError if not."""
    subunit_col = _find_column(headers, ["subunit"])
    if not subunit_col:
        raise ValueError(
            "subunit column is required for map command. Add it to your design spec "
            "(csv_contracts.design_spec.add_if_missing includes subunit)."
        )
    for i, row in enumerate(rows):
        val = (row.get(subunit_col) or "").strip()
        if not val:
            raise ValueError(
                f"Row {i + 1} has empty subunit. All rows must have a non-empty subunit "
                "value for the map command. Populate the subunit column before running map."
            )


def _validate_spec_id_unique(headers: list[str], rows: list[dict[str, str]]) -> None:
    """Validate that spec_id values are unique across rows. Raise ValueError if duplicates exist."""
    spec_id_col = _find_column(headers, ["spec_id", "Spec_ID", "spec_ID"])
    if not spec_id_col:
        return  # No spec_id column; nothing to validate
    seen: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        sid = (row.get(spec_id_col, "") or "").strip()
        if sid:
            if sid not in seen:
                seen[sid] = []
            seen[sid].append(i + 1)
    duplicates = {sid: indices for sid, indices in seen.items() if len(indices) > 1}
    if duplicates:
        first = next(iter(duplicates))
        indices = duplicates[first]
        raise ValueError(
            f"Duplicate spec_id '{first}' in design spec (rows {indices}). "
            "Each spec_id must be unique."
        )


def _filter_rows_for_mapping(
    headers: list[str],
    rows: list[dict[str, str]],
    *,
    skip_mapped: bool,
) -> list[dict[str, str]]:
    """Filter rows to those needing mapping.

    Returns:
        Rows with status != 'mapped' when skip_mapped is True, or all rows otherwise.
    """
    status_col = _find_column(headers, ["index_status"])
    if not status_col:
        return rows
    filtered: list[dict[str, str]] = []
    for row in rows:
        status = (row.get(status_col) or "").strip().lower()
        if skip_mapped and status == "mapped":
            continue
        filtered.append(row)
    return filtered


def _group_by_subunit(
    headers: list[str],
    rows: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    """Group rows by subunit value. Returns dict mapping subunit name to its rows."""
    subunit_col = _find_column(headers, ["subunit"])
    if not subunit_col:
        return {"": rows}  # fallback: single group
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        key = (row.get(subunit_col) or "").strip() or ""
        if key not in groups:
            groups[key] = []
        groups[key].append(row)
    return groups


def _merge_subunit_results(batch_outputs: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge per-subunit agent outputs into a single output. Check for duplicate spec_ids."""
    merged_mappings: dict[str, Any] = {}
    manual_items: list[Any] = []
    run_summary = None
    created_at = ""
    for out in batch_outputs:
        mappings = out.get("mappings") or {}
        if isinstance(mappings, list):
            for item in mappings:
                if isinstance(item, dict):
                    sid = item.get("spec_id")
                    if sid and sid in merged_mappings:
                        raise ValueError(
                            f"Duplicate spec_id '{sid}' across subunits. "
                            "Each spec_id must appear in exactly one subunit."
                        )
                    if sid:
                        merged_mappings[sid] = item
        else:
            for sid, m in mappings.items():
                if sid in merged_mappings:
                    raise ValueError(
                        f"Duplicate spec_id '{sid}' across subunits. "
                        "Each spec_id must appear in exactly one subunit."
                    )
                merged_mappings[sid] = m
        manual_items.extend(out.get("manual_resolution_items") or [])
        if out.get("run_summary"):
            run_summary = out["run_summary"]
        if out.get("created_at"):
            created_at = out["created_at"]
    return {
        "manual_resolution_items": manual_items,
        "run_summary": run_summary or {},
        "created_at": created_at,
        "mappings": merged_mappings,
    }


def _sanitize_subunit_for_filename(name: str) -> str:
    """Sanitize subunit name for use in filenames. Replaces unsafe chars with underscore."""
    return re.sub(r"[^\w\-.]", "_", name) or "subunit"


def _load_outputs_from_directory(path: Path) -> list[dict[str, Any]]:
    """Load all map output JSON files from a directory. Returns list ordered by filename.

    Each file must have 'mappings' (and expected map output keys). Raises ValueError
    if directory is missing, empty, or any file is invalid.
    """
    if not path.exists():
        raise ValueError(f"Directory does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"Path is not a directory: {path}")
    files = sorted(path.glob("*.json"))
    if not files:
        raise ValueError(f"No *.json files in directory: {path}")
    outputs: list[dict[str, Any]] = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise ValueError(f"Invalid or unreadable JSON in {f}: {e}") from e
        if not isinstance(data, dict):
            raise ValueError(f"Expected object in {f}, got {type(data).__name__}")
        if "mappings" not in data:
            raise ValueError(f"Missing 'mappings' in {f}")
        outputs.append(data)
    return outputs


def run_map(config: dict[str, Any], ctx: RuntimeContext) -> dict[str, Any]:
    """Execute map command lifecycle.

    Lifecycle: load Formatted SADS -> validate subunit -> filter -> group by subunit ->
    invoke agent per subunit -> merge -> validate -> manual resolution -> translate.
    """
    project_root = Path(ctx.project_root)

    # 3. Load required inputs
    log_lifecycle_event("lifecycle_load_inputs", command="map", run_id=ctx.run_id)
    design_path = resolve_input_path(
        config, project_root, "design_spec_path", overrides=ctx.input_overrides
    )
    if design_path is None or not design_path.exists():
        return {"command": "map", "status": "skipped", "reason": "design_spec_path not configured or missing"}

    headers, rows = load_sads_csv_or_xlsx(design_path)
    add_if_missing = get_design_spec_add_if_missing(config)
    headers, rows = append_missing_columns(headers, rows, add_if_missing)
    _validate_subunit_column(headers, rows)
    _validate_spec_id_unique(headers, rows)

    # Apply-existing-outputs: load from directory, merge, validate, translate (no agent)
    apply_existing = (ctx.input_overrides or {}).get("apply_existing_outputs", "").strip()
    if apply_existing:
        resolved_path = Path(apply_existing)
        if not resolved_path.is_absolute():
            resolved_path = (project_root / apply_existing).resolve()
        if not resolved_path.exists() or not resolved_path.is_dir():
            _report_map_step(
                "Load outputs",
                "failed",
                "apply_existing_outputs path is not an existing directory",
            )
            return {
                "command": "map",
                "status": "failed",
                "reason": "apply_existing_outputs path is not an existing directory",
            }
        try:
            batch_outputs = _load_outputs_from_directory(resolved_path)
        except ValueError as e:
            _report_map_step("Load outputs", "failed", str(e))
            return {"command": "map", "status": "failed", "reason": str(e)}
        if not batch_outputs:
            _report_map_step("Load outputs", "failed", "no valid map output JSON files in directory")
            return {
                "command": "map",
                "status": "failed",
                "reason": "no valid map output JSON files in directory",
            }
        _report_map_step(
            "Load outputs",
            "ok",
            f"loaded {len(batch_outputs)} subunit output(s) from {resolved_path}",
        )
        output = _merge_subunit_results(batch_outputs)
        n_mappings = len(output.get("mappings") or {})
        _report_map_step(
            "Merge",
            "ok",
            f"merged {n_mappings} mapping(s) from {len(batch_outputs)} subunit(s)",
        )
        try:
            _validate_map_output_contract(output)
        except ValueError as e:
            _report_map_step("Validate", "failed", str(e))
            return {"command": "map", "status": "failed", "reason": str(e)}
        _report_map_step("Validate", "ok", "output contract passed")
        if has_blocking_manual_resolution(output):
            n_blocking = len(output.get("manual_resolution_items", []))
            _report_map_step(
                "Manual resolution",
                "blocked",
                f"{n_blocking} blocking item(s) require human resolution before translate",
            )
            log_lifecycle_event("lifecycle_manual_resolution", command="map", run_id=ctx.run_id)
            manual_path = resolve_output_path(config, project_root, "manual_resolution_file")
            if manual_path:
                append_manual_resolution_items_to_file(
                    output["manual_resolution_items"],
                    manual_path,
                )
            return {
                "command": "map",
                "status": "blocked",
                "blocking_items": n_blocking,
            }
        _report_map_step("Translate", "ok", "writing mappings to design spec CSV")
        log_lifecycle_event("lifecycle_translate", command="map", run_id=ctx.run_id)
        inputs = {"design_spec_path": design_path}
        _translate_map(config, ctx, output, inputs)
        _report_map_step("Translate", "completed", f"updated {n_mappings} row(s) in design spec")
        return {"command": "map", "status": "completed", "dry_run": ctx.dry_run}

    map_cfg = _get_map_config(config, ctx)
    skip_mapped = map_cfg["skip_mapped"]
    max_acceptance_chars = map_cfg["max_acceptance_chars"]

    filtered_rows = _filter_rows_for_mapping(headers, rows, skip_mapped=skip_mapped)
    if not filtered_rows:
        return {"command": "map", "status": "completed", "reason": "no specs to map (all already mapped)"}

    subunit_groups = _group_by_subunit(headers, filtered_rows)
    subunit_order = sorted(subunit_groups.keys())

    batch_outputs: list[dict[str, Any]] = []
    partial_failures: list[dict[str, str]] = []
    logger = get_run_logger()

    for subunit_name in subunit_order:
        sub_rows = subunit_groups[subunit_name]
        if not sub_rows:
            continue
        row_count = len(sub_rows)
        log_lifecycle_event(
            "lifecycle_invoke_agent",
            command="map",
            run_id=ctx.run_id,
            extra={"subunit": subunit_name, "row_count": row_count},
        )
        print(
            f"[PIKA] Mapping subunit '{subunit_name}' ({row_count} specs)...",
            file=sys.stderr,
        )
        csv_content = build_agent_view_csv_content(
            headers,
            sub_rows,
            max_acceptance_chars=max_acceptance_chars,
        )
        if not csv_content:
            continue
        inputs = {
            "design_spec_path": design_path,
            "agent_view_content": csv_content,
        }
        template_vars = _build_template_vars(config, project_root, ctx, inputs)
        schema_path = resolve_output_schema_path(config, project_root, "map_output")
        invocation_ts = format_timestamp_local_minutes()
        try:
            out = invoke_agent_with_schema_retry(
                prompt_name=_get_prompt_name(config),
                template_vars=template_vars,
                schema_path=schema_path,
                config=config,
                ctx=ctx,
                invocation_timestamp=invocation_ts,
            )
            # Persist per-subunit output for resume/apply-existing-outputs
            intermediate_dir = resolve_intermediate_map_dir(config, project_root)
            run_subdir = intermediate_dir / ctx.run_id
            run_subdir.mkdir(parents=True, exist_ok=True)
            sanitized = _sanitize_subunit_for_filename(subunit_name)
            out_path = run_subdir / f"map_{sanitized}.json"
            out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
            batch_outputs.append(out)
        except Exception as exc:
            logger.exception("Subunit %s failed: %s", subunit_name, exc)
            partial_failures.append({"subunit": subunit_name, "error": str(exc)})
            log_lifecycle_event(
                "lifecycle_subunit_failed",
                command="map",
                run_id=ctx.run_id,
                extra={"subunit": subunit_name, "error": str(exc)},
            )

    if not batch_outputs:
        _report_map_step("Merge", "failed", "all subunits failed; no outputs to merge")
        return {
            "command": "map",
            "status": "failed",
            "reason": "all subunits failed",
            "partial_failures": partial_failures,
        }

    output = _merge_subunit_results(batch_outputs)
    n_mappings = len(output.get("mappings") or {})
    _report_map_step(
        "Merge",
        "ok",
        f"merged {n_mappings} mapping(s) from {len(batch_outputs)} subunit(s)",
    )
    try:
        _validate_map_output_contract(output)
    except ValueError as e:
        _report_map_step("Validate", "failed", str(e))
        return {"command": "map", "status": "failed", "reason": str(e)}
    _report_map_step("Validate", "ok", "output contract passed")

    # 7. Manual-resolution: append items to file and return blocked
    if has_blocking_manual_resolution(output):
        n_blocking = len(output.get("manual_resolution_items", []))
        _report_map_step(
            "Manual resolution",
            "blocked",
            f"{n_blocking} blocking item(s) require human resolution before translate",
        )
        log_lifecycle_event("lifecycle_manual_resolution", command="map", run_id=ctx.run_id)
        manual_path = resolve_output_path(config, project_root, "manual_resolution_file")
        if manual_path:
            append_manual_resolution_items_to_file(
                output["manual_resolution_items"],
                manual_path,
            )
        return {
            "command": "map",
            "status": "blocked",
            "blocking_items": n_blocking,
        }

    # 8. Translate: update mapping columns in Formatted SADS
    _report_map_step("Translate", "ok", "writing mappings to design spec CSV")
    log_lifecycle_event("lifecycle_translate", command="map", run_id=ctx.run_id)
    inputs = {"design_spec_path": design_path}
    _translate_map(config, ctx, output, inputs)
    _report_map_step("Translate", "completed", f"updated {n_mappings} row(s) in design spec")

    result: dict[str, Any] = {"command": "map", "status": "completed", "dry_run": ctx.dry_run}
    if partial_failures:
        result["partial_failures"] = partial_failures
    return result


def _build_template_vars(
    config: dict[str, Any],
    project_root: Path,
    ctx: RuntimeContext,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """Build template variables for map_spec_to_code prompt."""
    manual_path = resolve_output_path(config, project_root, "manual_resolution_file")
    run_summary_path = resolve_output_path(config, project_root, "run_summary_file")
    schema_path = resolve_output_schema_path(config, project_root, "map_output")
    schema_file = str(schema_path) if schema_path and schema_path.exists() else ""

    # Resolve codebase_dir: CLI/config or default to project_root
    codebase_dir_path = resolve_codebase_dir_path(config, project_root, ctx)
    codebase_dir = str(codebase_dir_path)

    # Resolve project_context: CLI path or codebase_dir/project_context_filename
    project_context_content = resolve_project_context_content(
        config, project_root, ctx, codebase_dir_path
    )

    # Resolve extra_prompt: CLI path or project_root/inputs.extra_prompt_filename (optional)
    extra_prompt_content = resolve_extra_prompt_content(config, project_root, ctx)
    extra_prompt_section = (
        f"\n\nExtra Instructions:\n{extra_prompt_content}\n"
        if extra_prompt_content.strip()
        else ""
    )

    # Build codebase snapshot for API providers (local/stub have filesystem access)
    provider = get_agent_provider(config)
    codebase_content = ""
    if provider not in ("local", "stub"):
        codebase_content = build_codebase_snapshot(codebase_dir_path, config, command="map")

    return {
        "output_schema_file": schema_file,
        "project_context": project_context_content,
        "extra_prompt_section": extra_prompt_section,
        "design_spec_rows_csv": inputs.get("agent_view_content", inputs.get("design_spec_content", "")),
        "design_spec_column_definitions": get_design_spec_column_definitions(),
        "codebase_dir": codebase_dir,
        "codebase_content": codebase_content,
        "manual_resolution_file": str(manual_path) if manual_path else "",
        "run_summary_file": str(run_summary_path) if run_summary_path else "",
    }


def _get_prompt_name(config: dict[str, Any]) -> str:
    """Return prompt name for map from config."""
    commands = config.get("commands", {})
    map_cfg = commands.get("map") if isinstance(commands, dict) else {}
    if isinstance(map_cfg, dict):
        return map_cfg.get("prompt_name", "map_spec_to_code")
    return "map_spec_to_code"


def _find_column(headers: list[str], candidates: list[str]) -> str | None:
    """Find first column that matches any candidate (case-insensitive)."""
    header_map = {h.strip().lower(): h for h in headers if h}
    for c in candidates:
        key = c.strip().lower()
        if key in header_map:
            return header_map[key]
    return None


def _translate_map(
    config: dict[str, Any],
    ctx: RuntimeContext,
    output: dict[str, Any],
    inputs: dict[str, Any],
) -> None:
    """Translate map output into Formatted SADS mapping column updates. Dry-run aware.

    Updates only mapping-related columns per csv_contracts:
    - mapped_code_symbols: comma-delimited symbol_name from code_refs
    - mapped_confidence: comma-delimited confidence (0-1) per symbol, same order
    - mapped_consistency_score: comma-delimited consistency_score (0-1) per symbol, same order
    - mapped_problems: semicolon-delimited problems per symbol, same order
    - index_status: mapping.status (mapped|partial|unmapped|blocked)
    - assumptions: mapping.assumptions (nullable)
    - last_indexed_at: YYYY-MM-DDTHH:MM:SS UTC+X (agent created_at when provided, else invocation time)

    Preserves all original columns. Backs up design spec before overwrite.
    """
    if ctx.dry_run:
        return

    project_root = Path(ctx.project_root)
    design_path = inputs.get("design_spec_path")
    if not isinstance(design_path, Path):
        design_path = Path(str(design_path)) if design_path else None
    if design_path is None or not design_path.exists():
        return

    mappings: dict[str, Any] = output.get("mappings") or {}
    if not mappings:
        return

    # Timestamp for last_indexed_at (YYYY-MM-DDTHH:MM:SS UTC+X)
    created_at = output.get("created_at", "")
    if isinstance(created_at, str) and created_at.strip():
        last_indexed_at = normalize_timestamp_for_display(created_at)
    else:
        last_indexed_at = format_timestamp_local_minutes()

    # Load design spec
    headers, rows = load_sads_csv_or_xlsx(design_path)

    # Ensure mapping columns exist (append if missing; config is single source of truth)
    add_if_missing_full = get_design_spec_add_if_missing(config)
    add_if_missing = [c for c in add_if_missing_full if c != "spec_id"]
    headers, rows = append_missing_columns(headers, rows, add_if_missing)

    # Resolve column names (support alternate casing)
    spec_id_col = _find_column(headers, ["spec_id", "Spec_ID", "spec_ID"])
    mapped_col = _find_column(headers, ["mapped_code_symbols"])
    confidence_col = _find_column(headers, ["mapped_confidence"])
    consistency_col = _find_column(headers, ["mapped_consistency_score"])
    problems_col = _find_column(headers, ["mapped_problems"])
    status_col = _find_column(headers, ["index_status"])
    assumptions_col = _find_column(headers, ["assumptions", "index_notes"])  # index_notes for backward compat
    timestamp_col = _find_column(headers, ["last_indexed_at"])

    if not spec_id_col:
        return  # No spec_id column; cannot match rows

    # Build spec_id -> row index for fast lookup
    spec_id_to_idx: dict[str, int] = {}
    for i, row in enumerate(rows):
        sid = (row.get(spec_id_col, "") or "").strip()
        if sid:
            spec_id_to_idx[sid] = i

    # Apply mapping updates
    for spec_id, mapping in mappings.items():
        if spec_id not in spec_id_to_idx:
            continue
        idx = spec_id_to_idx[spec_id]
        row = rows[idx]

        # mapped_code_symbols, mapped_confidence, mapped_consistency_score, mapped_problems
        code_refs = mapping.get("code_refs") or []
        symbols: list[str] = []
        confidences: list[str] = []
        consistencies: list[str] = []
        problems_list: list[str] = []
        for ref in code_refs:
            if not isinstance(ref, dict):
                continue
            sym = str(ref.get("symbol_name", "")).strip()
            if not sym:
                continue
            symbols.append(sym)
            conf = ref.get("confidence")
            conf_str = f"{conf:.2f}" if isinstance(conf, (int, float)) else ""
            confidences.append(conf_str)
            cons = ref.get("consistency_score")
            cons_str = f"{cons:.2f}" if isinstance(cons, (int, float)) else ""
            consistencies.append(cons_str)
            prob = ref.get("problems", ref.get("notes", "")) or ""
            problems_list.append(str(prob).strip())
        if mapped_col:
            row[mapped_col] = ",".join(symbols)
        if confidence_col:
            row[confidence_col] = ",".join(confidences)
        if consistency_col:
            row[consistency_col] = ",".join(consistencies)
        if problems_col:
            row[problems_col] = ";".join(problems_list)

        # index_status
        status = mapping.get("status", "unmapped")
        if isinstance(status, str) and status.strip():
            if status_col:
                row[status_col] = status.strip()

        # assumptions (nullable)
        assumptions = mapping.get("assumptions", mapping.get("notes"))  # backward compat
        if assumptions_col:
            row[assumptions_col] = "" if assumptions is None else str(assumptions).strip()

        # last_indexed_at
        if timestamp_col:
            row[timestamp_col] = last_indexed_at

    # Backup before overwrite (per csv_contracts). backups_dir is required for map.
    backups_base = resolve_output_path(config, project_root, "backups_dir")
    if backups_base is None:
        raise ValueError(
            "backups_dir is required for map command. "
            "Configure outputs.backups_dir in your project config."
        )
    backups_dir = backups_base / "map"
    backups_dir.mkdir(parents=True, exist_ok=True)
    ts = format_timestamp_local_minutes_filename()
    stem = design_path.stem
    suffix = design_path.suffix or ".csv"
    backup_name = f"{stem}_{ts}_{ctx.run_id[:8]}{suffix}"
    backup_path = backups_dir / backup_name
    shutil.copy2(design_path, backup_path)

    # Write updated CSV
    csv_content = rows_to_csv(headers, rows)
    design_path.write_text(csv_content, encoding="utf-8")


def _validate_map_output_contract(output: dict[str, Any]) -> None:
    """Enforce map-specific invariants. Normalizes code_refs to include consistency_score
    and problems (per-ref reasons for inconfidence/inconsistency; empty when both high).
    Schema may provide mappings as either:
    - list of objects with explicit spec_id (Codex response_format-safe), or
    - dict keyed by spec_id (legacy/internal shape).
    This function normalizes to dict keyed by spec_id.
    """
    mappings_raw = output.get("mappings")
    if mappings_raw is None:
        return

    mappings: dict[str, Any] = {}
    if isinstance(mappings_raw, dict):
        for spec_id, item in mappings_raw.items():
            if not isinstance(item, dict):
                raise ValueError("Output contract failed: each mappings item must be an object")
            mappings[spec_id] = {
                "status": item.get("status"),
                "code_refs": _normalize_code_refs(item.get("code_refs")),
                "assumptions": item.get("assumptions", item.get("notes")),  # backward compat
            }
    elif isinstance(mappings_raw, list):
        for item in mappings_raw:
            if not isinstance(item, dict):
                raise ValueError("Output contract failed: each mappings item must be an object")
            spec_id = item.get("spec_id")
            if not isinstance(spec_id, str) or not spec_id.strip():
                raise ValueError(
                    "Output contract failed: each mappings list item must include non-empty 'spec_id'"
                )
            sid = spec_id.strip()
            if sid in mappings:
                raise ValueError(f"Output contract failed: duplicate spec_id in mappings list: {sid}")
            mappings[sid] = {
                "status": item.get("status"),
                "code_refs": _normalize_code_refs(item.get("code_refs")),
                "assumptions": item.get("assumptions", item.get("notes")),  # backward compat
            }
    else:
        raise ValueError(
            "Output contract failed: 'mappings' must be an object with spec_id keys "
            "or a list of mapping items with 'spec_id'"
        )
    output["mappings"] = mappings

    manual_items = output.get("manual_resolution_items")
    if isinstance(manual_items, list) and manual_items and mappings:
        blocked_spec_ids: set[str] = set()
        for item in manual_items:
            if isinstance(item, dict):
                blocked_spec_ids.update(
                    _entity_id_to_spec_ids(item.get("entity_id", ""))
                )
        overlapping = blocked_spec_ids & set(mappings.keys())
        if overlapping:
            preview = ", ".join(sorted(overlapping)[:5])
            raise ValueError(
                "Output contract failed: when manual_resolution_items references "
                "a spec_id, that spec_id must not appear in mappings. "
                f"Overlapping: {preview}"
            )

    invalid_keys = [
        key for key in mappings.keys()
        if not isinstance(key, str) or not _SPEC_ID_PATTERN.fullmatch(key)
    ]
    if invalid_keys:
        keys_preview = ", ".join(sorted(str(key) for key in invalid_keys[:5]))
        raise ValueError(
            "Output contract failed: mappings keys must match ^[A-Za-z][0-9]+$. "
            f"Invalid keys: {keys_preview}"
        )
