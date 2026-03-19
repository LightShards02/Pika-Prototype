"""Handler for `agent map` — SADS Mapper (Phase 2)."""

from __future__ import annotations

import concurrent.futures
import json
import re
import shutil
import sys
import threading
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
    get_agent_provider,
    get_run_logger,
    has_blocking_manual_resolution,
    invoke_agent_with_schema_retry,
    log_lifecycle_event,
    persist_manual_resolution_block_for_run,
    resolve_codebase_dir_path,
    resolve_input_path,
    resolve_intermediate_map_dir,
    resolve_output_path,
    resolve_output_schema_path,
    resolve_extra_prompt_content,
    resolve_project_context_content,
    resolve_resolution_template_path_for_run,
    resolve_run_summary_path_for_command,
)

_SPEC_ID_PATTERN = re.compile(r"^[A-Za-z][0-9]+$")
_ENTITY_ID_RANGE = re.compile(r"^([A-Za-z])([0-9]+)-([A-Za-z])([0-9]+)$")

# Column name aliases for backward compatibility. Keys are logical names; values are candidate headers.
_COLUMN_ALIASES: dict[str, list[str]] = {
    "spec_id": ["spec_id", "Spec_ID", "spec_ID"],
    "subunit": ["subunit"],
    "map_status": ["map_status", "index_status"],
    "map_assumptions": ["map_assumptions", "assumptions", "index_notes"],
    "mapped_at": ["mapped_at", "last_indexed_at"],
}


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
    dropped = 0
    for ref in code_refs:
        if not isinstance(ref, dict):
            dropped += 1
            continue
        problems = ref.get("problems", "")
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
    if dropped:
        get_run_logger().warning(
            "code_refs: skipped %d non-dict item(s); agent may have returned malformed data",
            dropped,
        )
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
    max_specs_per_subunit = map_cfg.get("max_specs_per_subunit", 0)
    if "max_specs_per_subunit" in overrides:
        try:
            max_specs_per_subunit = int(overrides["max_specs_per_subunit"])
        except (ValueError, TypeError):
            pass
    subunit_filter_raw = overrides.get("subunit_filter", "")
    subunit_filter: set[str] = {s.strip() for s in subunit_filter_raw.split(",") if s.strip()} if subunit_filter_raw else set()
    min_remapping_confidence_threshold = map_cfg.get("min_remapping_confidence_threshold", 0.0)
    if "min_remapping_confidence_threshold" in overrides:
        try:
            min_remapping_confidence_threshold = float(overrides["min_remapping_confidence_threshold"])
        except (ValueError, TypeError):
            pass
    max_problem_threshold = map_cfg.get("max_problem_threshold", 1.0)
    if "max_problem_threshold" in overrides:
        try:
            max_problem_threshold = float(overrides["max_problem_threshold"])
        except (ValueError, TypeError):
            pass
    return {
        "skip_mapped": skip_mapped,
        "max_acceptance_chars": max_acceptance_chars,
        "max_specs_per_subunit": max_specs_per_subunit,
        "subunit_filter": subunit_filter,
        "min_remapping_confidence_threshold": min_remapping_confidence_threshold,
        "max_problem_threshold": max_problem_threshold,
    }


def validate_subunit_column(headers: list[str], rows: list[dict[str, str]]) -> None:
    """Validate that all rows have a non-empty subunit value. Raise ValueError if not."""
    subunit_col = _find_column(headers, _COLUMN_ALIASES["subunit"])
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


def validate_spec_id_unique(headers: list[str], rows: list[dict[str, str]]) -> None:
    """Validate that spec_id values are unique across rows. Raise ValueError if duplicates exist."""
    spec_id_col = _find_column(headers, _COLUMN_ALIASES["spec_id"])
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


def _parse_max_confidence(raw: str) -> float:
    """Parse comma-delimited confidence string; return max float (0.0 on empty/error)."""
    best = 0.0
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            val = float(part)
            if val > best:
                best = val
        except ValueError:
            pass
    return best


def filter_rows_for_mapping(
    headers: list[str],
    rows: list[dict[str, str]],
    *,
    skip_mapped: bool,
    min_remapping_confidence_threshold: float = 0.0,
) -> list[dict[str, str]]:
    """Filter rows to those needing mapping.

    Returns:
        Rows with status != 'mapped' when skip_mapped is True, or all rows otherwise.
        When min_remapping_confidence_threshold > 0, mapped rows whose max confidence
        falls below the threshold are re-included for re-mapping.
    """
    status_col = _find_column(headers, _COLUMN_ALIASES["map_status"])
    if not status_col:
        return rows
    conf_col = _find_column(headers, ["mapped_confidence"]) if min_remapping_confidence_threshold > 0.0 else None
    filtered: list[dict[str, str]] = []
    for row in rows:
        status = (row.get(status_col) or "").strip().lower()
        if skip_mapped and status == "mapped":
            if conf_col and min_remapping_confidence_threshold > 0.0:
                raw_conf = (row.get(conf_col) or "").strip()
                if _parse_max_confidence(raw_conf) < min_remapping_confidence_threshold:
                    filtered.append(row)
            continue
        filtered.append(row)
    return filtered


def group_by_subunit(
    headers: list[str],
    rows: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    """Group rows by subunit value. Returns dict mapping subunit name to its rows."""
    subunit_col = _find_column(headers, _COLUMN_ALIASES["subunit"])
    if not subunit_col:
        return {"": rows}  # fallback: single group
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        key = (row.get(subunit_col) or "").strip() or ""
        if key not in groups:
            groups[key] = []
        groups[key].append(row)
    return groups


def _aggregate_run_summaries(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-subunit run_summaries into one. Status hierarchy: blocked > partial > success."""
    if not summaries:
        return {}
    statuses = [s.get("status", "") for s in summaries]
    if "blocked" in statuses:
        agg_status = "blocked"
    elif "partial" in statuses:
        agg_status = "partial"
    else:
        agg_status = "success"
    summary_texts = [s.get("summary", "") for s in summaries if s.get("summary")]
    agg_summary = "; ".join(summary_texts) if summary_texts else ""
    agg_blocking = sum(s.get("blocking_items", 0) for s in summaries)
    storage_file = summaries[-1].get("storage_file", "")
    return {
        "command": "agent map",
        "status": agg_status,
        "summary": agg_summary or "aggregated",
        "blocking_items": agg_blocking,
        "storage_file": storage_file,
    }


def merge_subunit_results(batch_outputs: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge per-subunit agent outputs into a single output. Check for duplicate spec_ids."""
    merged_mappings: dict[str, Any] = {}
    manual_items: list[Any] = []
    all_run_summaries: list[dict[str, Any]] = []
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
            all_run_summaries.append(out["run_summary"])
        if out.get("created_at"):
            created_at = out["created_at"]
    return {
        "manual_resolution_items": manual_items,
        "run_summary": _aggregate_run_summaries(all_run_summaries),
        "created_at": created_at,
        "mappings": merged_mappings,
    }


def sanitize_subunit_for_filename(name: str) -> str:
    """Sanitize subunit name for use in filenames. Replaces unsafe chars with underscore."""
    return re.sub(r"[^\w\-.]", "_", name) or "subunit"


def _post_process_map(
    batch_outputs: list[dict[str, Any]],
    config: dict[str, Any],
    ctx: RuntimeContext,
    design_path: Path,
    *,
    partial_failures: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Merge, validate, check manual resolution, and translate. Shared by apply_existing and agent paths.

    Per-subunit blocking: clean (non-blocked) subunit outputs are translated immediately.
    Blocked subunit outputs trigger persist_manual_resolution_block_for_run and return status=blocked.
    """
    partial_failures = partial_failures or []
    project_root = Path(ctx.project_root)
    map_cfg = _get_map_config(config, ctx)
    min_threshold = map_cfg["min_remapping_confidence_threshold"]

    # Split into clean and blocked before merging (per-subunit blocking).
    clean_outputs = [o for o in batch_outputs if not has_blocking_manual_resolution(o)]
    blocked_outputs = [o for o in batch_outputs if has_blocking_manual_resolution(o)]

    # Process clean outputs (translate if any).
    clean_applied = 0
    if clean_outputs:
        try:
            clean_merged = merge_subunit_results(clean_outputs)
        except ValueError as e:
            _report_map_step("Merge", "failed", str(e))
            return {"command": "map", "status": "failed", "reason": str(e)}

        clean_n = len(clean_merged.get("mappings") or {})
        _report_map_step(
            "Merge",
            "ok",
            f"merged {clean_n} mapping(s) from {len(clean_outputs)} clean subunit(s)",
        )
        try:
            validate_map_output_contract(clean_merged, min_remapping_confidence_threshold=min_threshold)
        except ValueError as e:
            _report_map_step("Validate", "failed", str(e))
            return {"command": "map", "status": "failed", "reason": str(e)}
        _report_map_step("Validate", "ok", "output contract passed")

        # Validate code_ref paths.
        codebase_dir_path = resolve_codebase_dir_path(config, project_root, ctx)
        invalid_paths = validate_code_ref_paths(clean_merged, codebase_dir_path)
        if invalid_paths:
            _report_map_step(
                "PathValidation",
                "warning",
                f"{len(invalid_paths)} code_ref path(s) not found under codebase_dir",
            )
            logger = get_run_logger()
            for inv in invalid_paths:
                logger.warning(
                    "Invalid code_ref path: spec=%s path=%s symbol=%s",
                    inv["spec_id"], inv["path"], inv["symbol_name"],
                )

        _report_map_step("Translate", "ok", "writing mappings to design spec CSV")
        log_lifecycle_event("lifecycle_translate", command="map", run_id=ctx.run_id)
        inputs = {"design_spec_path": design_path}
        translate_map(config, ctx, clean_merged, inputs)
        clean_applied = clean_n
        _report_map_step("Translate", "completed", f"updated {clean_n} row(s) in design spec")

        # Post-run stats.
        if not ctx.dry_run:
            stats = _compute_map_stats(clean_merged)
            print(
                f"[PIKA] Map complete: {stats['mapped']} mapped, {stats['partial']} partial, "
                f"{stats['unmapped']} unmapped, {stats['blocked']} blocked ({stats['total']} total)",
                file=sys.stderr,
            )
            agent_runs_base = resolve_output_path(config, project_root, "agent_runs_dir", command="map")
            if agent_runs_base:
                stats_dir = agent_runs_base / "map"
                stats_dir.mkdir(parents=True, exist_ok=True)
                stats_payload: dict[str, Any] = {
                    "run_id": ctx.run_id,
                    **stats,
                    "partial_failures": len(partial_failures),
                    "invalid_code_ref_paths": len(invalid_paths),
                }
                (stats_dir / f"{ctx.run_id}_stats.json").write_text(
                    json.dumps(stats_payload, indent=2), encoding="utf-8"
                )

    # Handle blocked outputs.
    if blocked_outputs:
        all_blocking_items: list[Any] = []
        for bo in blocked_outputs:
            all_blocking_items.extend(bo.get("manual_resolution_items") or [])
        n_blocking = len(all_blocking_items)
        _report_map_step(
            "Manual resolution",
            "blocked",
            f"{n_blocking} blocking item(s) require human resolution before translate",
        )
        log_lifecycle_event("lifecycle_manual_resolution", command="map", run_id=ctx.run_id)
        persist_manual_resolution_block_for_run(
            config,
            project_root,
            "map",
            ctx.run_id,
            "map",
            all_blocking_items,
            source="agent",
            completed_stages=["load_inputs", "invoke_agent", "merge", "validate"],
        )
        result: dict[str, Any] = {
            "command": "map",
            "status": "blocked",
            "blocking_items": n_blocking,
        }
        if clean_applied:
            result["clean_mappings_applied"] = clean_applied
        if partial_failures:
            result["partial_failures"] = partial_failures
        return result

    # All clean, no blocking.
    if not clean_outputs:
        return {"command": "map", "status": "failed", "reason": "no outputs to process"}

    status = "partial" if partial_failures else "completed"
    result = {"command": "map", "status": status, "dry_run": ctx.dry_run}
    if partial_failures:
        result["partial_failures"] = partial_failures
        print(
            f"[PIKA] Warning: {len(partial_failures)} subunit(s) failed; see partial_failures in result.",
            file=sys.stderr,
        )
    return result


def load_outputs_from_directory(path: Path) -> list[dict[str, Any]]:
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
        config,
        project_root,
        "design_spec_path",
        overrides=ctx.input_overrides,
        command="map",
    )
    if design_path is None or not design_path.exists():
        return {"command": "map", "status": "skipped", "reason": "design_spec_path not configured or missing"}

    headers, rows = load_sads_csv_or_xlsx(design_path)
    add_if_missing = get_design_spec_add_if_missing(config)
    headers, rows = append_missing_columns(headers, rows, add_if_missing)
    validate_subunit_column(headers, rows)
    validate_spec_id_unique(headers, rows)

    # Apply-existing-outputs: load from directory, merge, validate, translate (no agent)
    apply_existing = (ctx.input_overrides or {}).get("apply_existing_outputs", "").strip()
    if apply_existing:
        # Resolve "latest" sentinel to the most recently modified run subdir.
        if apply_existing.lower() == "latest":
            base_intermediate = resolve_intermediate_map_dir(config, project_root)
            subdirs = [p for p in base_intermediate.iterdir() if p.is_dir()] if base_intermediate.exists() else []
            if not subdirs:
                _report_map_step("Load outputs", "failed", "apply_existing_outputs=latest: no prior run directories found in intermediate_map_dir")
                return {
                    "command": "map",
                    "status": "failed",
                    "reason": "apply_existing_outputs=latest: no prior run directories found in intermediate_map_dir",
                }
            apply_existing = str(max(subdirs, key=lambda p: p.stat().st_mtime))
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
            batch_outputs = load_outputs_from_directory(resolved_path)
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
        return _post_process_map(batch_outputs, config, ctx, design_path)

    map_cfg = _get_map_config(config, ctx)
    skip_mapped = map_cfg["skip_mapped"]
    max_acceptance_chars = map_cfg["max_acceptance_chars"]
    max_specs_per_subunit = map_cfg["max_specs_per_subunit"]
    subunit_filter = map_cfg["subunit_filter"]
    min_threshold = map_cfg["min_remapping_confidence_threshold"]

    filtered_rows = filter_rows_for_mapping(
        headers, rows,
        skip_mapped=skip_mapped,
        min_remapping_confidence_threshold=min_threshold,
    )
    if not filtered_rows:
        return {"command": "map", "status": "completed", "reason": "no specs to map (all already mapped)"}

    subunit_groups = group_by_subunit(headers, filtered_rows)
    subunit_order = sorted(subunit_groups.keys())

    # Apply subunit filter if specified.
    if subunit_filter:
        subunit_order = [s for s in subunit_order if s in subunit_filter]
        if not subunit_order:
            return {"command": "map", "status": "skipped", "reason": "no subunits matched subunit_filter"}

    results_with_order: list[tuple[int, dict[str, Any]]] = []
    partial_failures: list[dict[str, str]] = []
    lock = threading.Lock()
    logger = get_run_logger()

    def _invoke_subunit(idx_name: tuple[int, str]) -> None:
        idx, subunit_name = idx_name
        sub_rows = subunit_groups[subunit_name]
        if not sub_rows:
            return
        row_count = len(sub_rows)

        # Split large subunits into consecutive sub-batches.
        if max_specs_per_subunit and max_specs_per_subunit > 0 and row_count > max_specs_per_subunit:
            batches = [sub_rows[i:i + max_specs_per_subunit] for i in range(0, row_count, max_specs_per_subunit)]
        else:
            batches = [sub_rows]

        log_lifecycle_event(
            "lifecycle_invoke_agent",
            command="map",
            run_id=ctx.run_id,
            extra={"subunit": subunit_name, "row_count": row_count, "batches": len(batches)},
        )
        print(
            f"[PIKA] Mapping subunit '{subunit_name}' ({row_count} specs, {len(batches)} batch(es))...",
            file=sys.stderr,
        )

        sub_batch_outputs: list[dict[str, Any]] = []
        intermediate_dir = resolve_intermediate_map_dir(config, project_root)
        run_subdir = intermediate_dir / ctx.run_id
        run_subdir.mkdir(parents=True, exist_ok=True)
        sanitized = sanitize_subunit_for_filename(subunit_name)

        for batch_idx, batch_rows in enumerate(batches):
            csv_content = build_agent_view_csv_content(
                headers,
                batch_rows,
                max_acceptance_chars=max_acceptance_chars,
            )
            if not csv_content:
                continue
            inputs = {
                "design_spec_path": design_path,
                "agent_view_content": csv_content,
            }
            template_vars = build_template_vars(config, project_root, ctx, inputs)
            schema_path = resolve_output_schema_path(
                config, project_root, "map_output", command="map"
            )
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
                # Persist per-batch output for resume/apply-existing-outputs.
                suffix = f"_{batch_idx}" if len(batches) > 1 else ""
                out_path = run_subdir / f"map_{sanitized}{suffix}.json"
                out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
                sub_batch_outputs.append(out)
            except Exception as exc:
                logger.exception("Subunit %s batch %d failed: %s", subunit_name, batch_idx, exc)
                with lock:
                    partial_failures.append({"subunit": subunit_name, "batch": batch_idx, "error": str(exc)})
                log_lifecycle_event(
                    "lifecycle_subunit_failed",
                    command="map",
                    run_id=ctx.run_id,
                    extra={"subunit": subunit_name, "batch": batch_idx, "error": str(exc)},
                )

        if not sub_batch_outputs:
            return

        # Merge sub-batches into a single subunit-level output.
        if len(sub_batch_outputs) == 1:
            subunit_out = sub_batch_outputs[0]
        else:
            try:
                subunit_out = merge_subunit_results(sub_batch_outputs)
            except ValueError as exc:
                logger.exception("Sub-batch merge for subunit %s failed: %s", subunit_name, exc)
                with lock:
                    partial_failures.append({"subunit": subunit_name, "error": f"sub-batch merge: {exc}"})
                return

        with lock:
            results_with_order.append((idx, subunit_out))

    with concurrent.futures.ThreadPoolExecutor() as executor:
        list(executor.map(_invoke_subunit, enumerate(subunit_order)))

    # Sort by original index for deterministic merge order regardless of thread scheduling.
    results_with_order.sort(key=lambda x: x[0])
    batch_outputs: list[dict[str, Any]] = [out for _, out in results_with_order]

    if not batch_outputs:
        _report_map_step("Merge", "failed", "all subunits failed; no outputs to merge")
        return {
            "command": "map",
            "status": "failed",
            "reason": "all subunits failed",
            "partial_failures": partial_failures,
        }

    return _post_process_map(
        batch_outputs, config, ctx, design_path, partial_failures=partial_failures
    )


def build_template_vars(
    config: dict[str, Any],
    project_root: Path,
    ctx: RuntimeContext,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """Build template variables for map_spec_to_code prompt."""
    manual_path = resolve_resolution_template_path_for_run(
        config, project_root, "map", ctx.run_id
    )
    run_summary_path = resolve_run_summary_path_for_command(config, project_root, "map")
    schema_path = resolve_output_schema_path(
        config, project_root, "map_output", command="map"
    )
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

    # Build codebase snapshot only for API-style providers.
    # Local provider explores the codebase directly via file tools (uses map_spec_to_code_local
    # prompt which has no codebase_content placeholder). Stub provider never needs content.
    provider = get_agent_provider(config)
    codebase_content = ""
    if provider not in ("stub", "local"):
        codebase_content = build_codebase_snapshot(codebase_dir_path, config, command="map")

    commands = config.get("commands") or {}
    map_cfg_raw = commands.get("map") if isinstance(commands, dict) else {}
    map_cfg_raw = map_cfg_raw if isinstance(map_cfg_raw, dict) else {}
    max_problem_threshold = map_cfg_raw.get("max_problem_threshold", 1.0)

    return {
        "output_schema_file": schema_file,
        "project_context": project_context_content,
        "extra_prompt_section": extra_prompt_section,
        "design_spec_rows_csv": inputs.get("agent_view_content", inputs.get("design_spec_content", "")),
        "design_spec_column_definitions": get_design_spec_column_definitions(),
        "codebase_dir": codebase_dir,
        "codebase_content": codebase_content,
        "manual_resolution_file": str(manual_path),
        "run_summary_file": str(run_summary_path),
        "resolved_decisions": ctx.resolved_decisions or "",
        "max_problem_threshold": str(max_problem_threshold),
    }


def _get_prompt_name(config: dict[str, Any]) -> str:
    """Return prompt name for map from config.

    Explicit config prompt_name always takes precedence. Otherwise defaults to
    map_spec_to_code_local for local provider and map_spec_to_code for all others.
    """
    commands = config.get("commands", {})
    map_cfg = commands.get("map") if isinstance(commands, dict) else {}
    if isinstance(map_cfg, dict) and map_cfg.get("prompt_name"):
        return map_cfg["prompt_name"]
    if get_agent_provider(config) == "local":
        return "map_spec_to_code_local"
    return "map_spec_to_code"


def _find_column(headers: list[str], candidates: list[str]) -> str | None:
    """Find first column that matches any candidate (case-insensitive)."""
    header_map = {h.strip().lower(): h for h in headers if h}
    for c in candidates:
        key = c.strip().lower()
        if key in header_map:
            return header_map[key]
    return None


def _apply_mapping_updates(
    rows: list[dict[str, str]],
    mappings: dict[str, Any],
    spec_id_col: str,
    column_map: dict[str, str | None],
    mapped_at_val: str,
    run_id_val: str = "",
) -> None:
    """Apply mapping updates to rows in place. Pure data transform; no file I/O."""
    spec_id_to_idx: dict[str, int] = {}
    for i, row in enumerate(rows):
        sid = (row.get(spec_id_col, "") or "").strip()
        if sid:
            spec_id_to_idx[sid] = i

    mapped_col = column_map.get("mapped")
    confidence_col = column_map.get("confidence")
    consistency_col = column_map.get("consistency")
    problems_col = column_map.get("problems")
    status_col = column_map.get("status")
    assumptions_col = column_map.get("assumptions")
    timestamp_col = column_map.get("timestamp")
    run_id_col = column_map.get("run_id")

    for spec_id, mapping in mappings.items():
        if spec_id not in spec_id_to_idx:
            continue
        idx = spec_id_to_idx[spec_id]
        row = rows[idx]

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
            path_val = str(ref.get("path", "")).strip()
            symbols.append(f"{path_val}::{sym}" if path_val else sym)
            conf = ref.get("confidence")
            conf_str = f"{conf:.2f}" if isinstance(conf, (int, float)) else ""
            confidences.append(conf_str)
            cons = ref.get("consistency_score")
            cons_str = f"{cons:.2f}" if isinstance(cons, (int, float)) else ""
            consistencies.append(cons_str)
            prob = ref.get("problems", "") or ""
            problems_list.append(str(prob).strip())
        if mapped_col:
            row[mapped_col] = ",".join(symbols)
        if confidence_col:
            row[confidence_col] = ",".join(confidences)
        if consistency_col:
            row[consistency_col] = ",".join(consistencies)
        if problems_col:
            row[problems_col] = ";".join(problems_list)

        status = mapping.get("status", "unmapped")
        if isinstance(status, str) and status.strip() and status_col:
            row[status_col] = status.strip()

        assumptions = mapping.get("assumptions")
        if assumptions_col:
            row[assumptions_col] = "" if assumptions is None else str(assumptions).strip()

        if timestamp_col:
            row[timestamp_col] = mapped_at_val

        if run_id_col and run_id_val:
            row[run_id_col] = run_id_val


def _backup_and_write(
    design_path: Path,
    headers: list[str],
    rows: list[dict[str, str]],
    config: dict[str, Any],
    ctx: RuntimeContext,
) -> None:
    """Backup design spec and write updated CSV. Raises ValueError if backups_dir not configured."""
    project_root = Path(ctx.project_root)
    backups_base = resolve_output_path(
        config, project_root, "backups_dir", command="map"
    )
    if backups_base is None:
        raise ValueError(
            "backups_dir is required for map command. "
            "Configure commands.map.outputs.backups_dir in your project config."
        )
    backups_dir = backups_base / "map"
    backups_dir.mkdir(parents=True, exist_ok=True)
    ts = format_timestamp_local_minutes_filename()
    stem = design_path.stem
    suffix = design_path.suffix or ".csv"
    backup_name = f"{stem}_{ts}_{ctx.run_id[:8]}{suffix}"
    backup_path = backups_dir / backup_name
    shutil.copy2(design_path, backup_path)

    csv_content = rows_to_csv(headers, rows)
    design_path.write_text(csv_content, encoding="utf-8")


def translate_map(
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
    - map_status: mapping.status (mapped|partial|unmapped|blocked)
    - map_assumptions: mapping.assumptions (nullable)
    - mapped_at: YYYY-MM-DDTHH:MM:SS UTC+X (agent created_at when provided, else invocation time)

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

    created_at = output.get("created_at", "")
    if isinstance(created_at, str) and created_at.strip():
        mapped_at_val = normalize_timestamp_for_display(created_at)
    else:
        mapped_at_val = format_timestamp_local_minutes()

    headers, rows = load_sads_csv_or_xlsx(design_path)
    add_if_missing_full = get_design_spec_add_if_missing(config)
    add_if_missing = [c for c in add_if_missing_full if c != "spec_id"]
    headers, rows = append_missing_columns(headers, rows, add_if_missing)

    spec_id_col = _find_column(headers, _COLUMN_ALIASES["spec_id"])
    if not spec_id_col:
        return

    column_map = {
        "mapped": _find_column(headers, ["mapped_code_symbols"]),
        "confidence": _find_column(headers, ["mapped_confidence"]),
        "consistency": _find_column(headers, ["mapped_consistency_score"]),
        "problems": _find_column(headers, ["mapped_problems"]),
        "status": _find_column(headers, _COLUMN_ALIASES["map_status"]),
        "assumptions": _find_column(headers, _COLUMN_ALIASES["map_assumptions"]),
        "timestamp": _find_column(headers, _COLUMN_ALIASES["mapped_at"]),
        "run_id": _find_column(headers, ["map_run_id"]),
    }

    _apply_mapping_updates(rows, mappings, spec_id_col, column_map, mapped_at_val, run_id_val=ctx.run_id[:8])
    _backup_and_write(design_path, headers, rows, config, ctx)


def validate_map_output_contract(
    output: dict[str, Any],
    *,
    min_remapping_confidence_threshold: float = 0.0,
) -> None:
    """Enforce map-specific invariants. Normalizes code_refs to include consistency_score
    and problems (per-ref reasons for inconfidence/inconsistency; empty when both high).
    Schema may provide mappings as either:
    - list of objects with explicit spec_id (Codex response_format-safe), or
    - dict keyed by spec_id (legacy/internal shape).
    This function normalizes to dict keyed by spec_id.

    When min_remapping_confidence_threshold > 0, demotes 'mapped' → 'partial' for any
    mapping whose max code_ref confidence falls below the threshold. Never promotes
    'partial' → 'mapped'.
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
                "assumptions": item.get("assumptions"),
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
                "assumptions": item.get("assumptions"),
            }
    else:
        raise ValueError(
            "Output contract failed: 'mappings' must be an object with spec_id keys "
            "or a list of mapping items with 'spec_id'"
        )
    output["mappings"] = mappings

    # One-directional status demotion: mapped → partial when max confidence below threshold.
    # Never promotes partial → mapped.
    if min_remapping_confidence_threshold > 0.0:
        for mapping in mappings.values():
            if mapping.get("status") == "mapped":
                refs = mapping.get("code_refs") or []
                max_conf = max(
                    (r.get("confidence", 0.0) for r in refs if isinstance(r, dict)),
                    default=0.0,
                )
                if max_conf < min_remapping_confidence_threshold:
                    mapping["status"] = "partial"

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


def validate_code_ref_paths(
    output: dict[str, Any],
    codebase_dir: Path,
) -> list[dict[str, str]]:
    """Check all code_refs[].path values against codebase_dir.

    Returns list of {spec_id, path, symbol_name} for paths that do not exist under
    codebase_dir. Never raises — caller decides how to handle warnings.
    """
    invalid: list[dict[str, str]] = []
    mappings = output.get("mappings") or {}
    for spec_id, mapping in mappings.items():
        for ref in (mapping.get("code_refs") or []):
            if not isinstance(ref, dict):
                continue
            path_str = ref.get("path", "").strip()
            if not path_str:
                continue
            if not (codebase_dir / path_str).exists():
                invalid.append({
                    "spec_id": str(spec_id),
                    "path": path_str,
                    "symbol_name": ref.get("symbol_name", ""),
                })
    return invalid


def _compute_map_stats(output: dict[str, Any]) -> dict[str, int]:
    """Count mapping statuses across all mappings in output.

    Returns dict with keys: mapped, partial, unmapped, blocked, total.
    """
    counts: dict[str, int] = {"mapped": 0, "partial": 0, "unmapped": 0, "blocked": 0}
    for mapping in (output.get("mappings") or {}).values():
        status = (mapping.get("status") or "").strip().lower()
        if status in counts:
            counts[status] += 1
    counts["total"] = sum(counts.values())
    return counts
