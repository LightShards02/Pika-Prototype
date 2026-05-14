"""Phase: map.match — SADS Mapper as a single REST phase with one coalesced gate."""

from __future__ import annotations

import concurrent.futures
import json
import shutil
import threading
from dataclasses import replace as _dc_replace
from pathlib import Path
from typing import Any

from core.context import RuntimeContext
from core.format_sads import (
    append_missing_columns,
    build_agent_view_csv_content,
    get_design_spec_add_if_missing,
    load_sads_csv_or_xlsx,
)
from core.lifecycle import (
    has_blocking_manual_resolution,
    invoke_agent_with_schema_retry,
    log_lifecycle_event,
    resolve_output_schema_path,
    resolve_phase_run_dir,
)
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
from core.resolution import (
    RESOLUTION_SOURCE_VALIDATION,
    build_resolved_decisions_context,
    generate_resolution_template,
    load_resolution_file,
    validate_resolutions,
)

from handlers.map import (
    _get_map_config,
    _get_prompt_name,
    build_template_vars,
    filter_rows_for_mapping,
    group_by_subunit,
    load_outputs_from_directory,
    merge_subunit_results,
    sanitize_subunit_for_filename,
    translate_map,
    validate_code_ref_paths,
    validate_map_output_contract,
    validate_spec_id_unique,
    validate_subunit_column,
)


MAP_MATCH = PhaseContract(
    name="map.match",
    command="map",
    inputs=(
        PhaseInput(
            name="design_spec_path",
            kind="workspace_relative_path",
            required=True,
            description="Path to Formatted SADS (CSV/XLSX) relative to workspace root or absolute.",
        ),
        PhaseInput(
            name="codebase_dir",
            kind="workspace_relative_path",
            required=True,
            description="Path to the codebase root.",
        ),
        PhaseInput(
            name="project_context_path",
            kind="workspace_relative_path",
            required=False,
            description="Path to project context markdown (e.g., PROJECT_CONTEXT.md).",
        ),
        PhaseInput(
            name="extra_prompt_path",
            kind="workspace_relative_path",
            required=False,
            description="Path to extra-prompt markdown to inject into the mapper agent prompt.",
        ),
        PhaseInput(
            name="force_remap",
            kind="bool",
            required=False,
            description="Re-map all specs even if already mapped in a prior run.",
        ),
        PhaseInput(
            name="max_acceptance_chars",
            kind="int",
            required=False,
            description="Truncate acceptance_criteria to N chars (0 = unlimited). Overrides config.",
        ),
        PhaseInput(
            name="prior_match_run_id",
            kind="phase_run_ref",
            required=False,
            description=(
                "Phase-run ID of a prior map.match run whose per-subunit outputs should be "
                "loaded instead of invoking the agent (cache-replay; equivalent to CLI "
                "--apply-existing-outputs)."
            ),
            ref_phase="map.match",
        ),
    ),
    outputs=(
        PhaseOutput(name="map_output", path="map_output.json", schema_ref="map_output"),
        PhaseOutput(name="subunit_outputs", path="subunits/*.json"),
    ),
    recommended_prerequisites=("refine.quality-audit",),
    can_block=True,
    destructive=False,
    async_execution=True,
    description=(
        "Produce traceability mappings from spec_id to code symbols via per-subunit "
        "LLM agent calls, merged into a single map output. Blocks when any subunit "
        "emits manual-resolution items."
    ),
)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _ctx_with_resolved_decisions(ctx: RuntimeContext, resolved: str) -> RuntimeContext:
    return _dc_replace(ctx, resolved_decisions=resolved)


def _ctx_with_overrides(ctx: RuntimeContext, extra: dict[str, str]) -> RuntimeContext:
    """Return a copy of ctx with extra input_overrides merged in."""
    merged = dict(ctx.input_overrides or {})
    merged.update(extra)
    return _dc_replace(ctx, input_overrides=merged)


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _build_overrides_from_inputs(inputs: dict[str, Any]) -> dict[str, str]:
    """Map REST inputs onto the input_overrides shape that handlers.map already understands."""
    overrides: dict[str, str] = {}
    for key in ("design_spec_path", "codebase_dir", "project_context_path", "extra_prompt_path"):
        if key in inputs and inputs[key] is not None:
            overrides[key] = str(inputs[key])
    if "force_remap" in inputs and inputs["force_remap"] is not None:
        overrides["force_remap"] = _coerce_str(inputs["force_remap"])
    if "max_acceptance_chars" in inputs and inputs["max_acceptance_chars"] is not None:
        overrides["max_acceptance_chars"] = _coerce_str(inputs["max_acceptance_chars"])
    return overrides


def _cache_replay(
    config: dict[str, Any],
    ctx: RuntimeContext,
    project_root: Path,
    prior_run_id: str,
    phase_run_dir: Path,
    inputs: dict[str, Any],
) -> PhaseResult:
    """Reuse a prior map.match run's outputs.

    Fast path: if the prior run has `map_output.json`, copy it (+ subunits) and
    return `PhaseCompleted` immediately. Slow path: if only `subunits/*.json`
    exist, load them and run the full post-merge pipeline (merge → validate →
    coalesced gate → translate) without invoking the agent.
    """
    try:
        prior_dir = resolve_phase_run_dir(config, project_root, "map.match", prior_run_id)
    except ValueError:
        return PhaseFailed(
            error_code="prior_phase_artifact_missing",
            message=f"prior_match_run_id {prior_run_id!r} is invalid",
        )
    prior_map_output = prior_dir / "map_output.json"
    prior_subunits = prior_dir / "subunits"

    has_map_output = prior_dir.exists() and prior_map_output.exists()
    has_subunits = (
        prior_dir.exists()
        and prior_subunits.exists()
        and prior_subunits.is_dir()
        and any(prior_subunits.glob("*.json"))
    )
    if not (has_map_output or has_subunits):
        return PhaseFailed(
            error_code="prior_phase_artifact_missing",
            message=(
                f"map_output.json (or populated subunits/) not found in prior map.match run "
                f"{prior_run_id!r} (expected at {prior_map_output} or {prior_subunits})"
            ),
        )

    phase_run_dir.mkdir(parents=True, exist_ok=True)

    if has_subunits:
        dest_subunits = phase_run_dir / "subunits"
        dest_subunits.mkdir(parents=True, exist_ok=True)
        for src in prior_subunits.glob("*.json"):
            shutil.copy2(src, dest_subunits / src.name)

    if has_map_output:
        dest = phase_run_dir / "map_output.json"
        dest.write_text(prior_map_output.read_text(encoding="utf-8"), encoding="utf-8")
        artifacts_index: dict[str, str] = {"map_output": "map_output.json"}
        if has_subunits:
            artifacts_index["subunit_outputs"] = "subunits/*.json"
        return PhaseCompleted(
            artifacts_index=artifacts_index,
            summary={"cache_replay": True, "source_phase_run_id": prior_run_id},
        )

    # Subunits-only replay: load them, run the post-merge pipeline.
    raw_design = inputs.get("design_spec_path")
    raw_codebase = inputs.get("codebase_dir")
    if raw_design is None or raw_codebase is None:
        return PhaseFailed(
            error_code="inputs_invalid",
            message="design_spec_path and codebase_dir are required for subunits-only replay",
        )
    design_path = Path(raw_design)
    codebase_dir = Path(raw_codebase)
    if not design_path.exists():
        return PhaseFailed(
            error_code="input_missing",
            message=f"design_spec_path does not exist: {design_path}",
        )
    if not codebase_dir.exists():
        return PhaseFailed(
            error_code="input_missing",
            message=f"codebase_dir does not exist: {codebase_dir}",
        )

    try:
        batch_outputs = load_outputs_from_directory(prior_subunits)
    except ValueError as exc:
        return PhaseFailed(error_code="prior_phase_artifact_missing", message=str(exc))
    if not batch_outputs:
        return PhaseFailed(
            error_code="prior_phase_artifact_missing",
            message=f"no valid subunit JSONs in {prior_subunits}",
        )

    ctx = _ctx_with_overrides(ctx, _build_overrides_from_inputs(inputs))
    map_cfg = _get_map_config(config, ctx)
    return _finalize_match_outputs(
        batch_outputs=batch_outputs,
        phase_run_dir=phase_run_dir,
        ctx=ctx,
        config=config,
        map_cfg=map_cfg,
        codebase_dir=codebase_dir,
        design_path=design_path,
        extra_summary={"cache_replay": True, "source_phase_run_id": prior_run_id},
    )


def _write_phase_resolution_block(
    items: list[dict[str, Any]],
    manual_dir: Path,
    phase_run_dir: Path,
    phase_run_id: str,
) -> None:
    manual_dir.mkdir(parents=True, exist_ok=True)
    _write_json(manual_dir / "map.json", {"stage": "map", "items": items})
    generate_resolution_template(
        run_dir=phase_run_dir,
        stage="map",
        items=items,
        command="map",
        run_id=phase_run_id,
        source=RESOLUTION_SOURCE_VALIDATION,
    )


def _build_template_vars(
    config: dict[str, Any],
    project_root: Path,
    ctx: RuntimeContext,
    phase_run_dir: Path,
    design_path: Path,
    agent_view_content: str,
) -> dict[str, Any]:
    """Build template_vars using handlers.map.build_template_vars, then redirect outputs."""
    template_vars = build_template_vars(
        config,
        project_root,
        ctx,
        {"design_spec_path": design_path, "agent_view_content": agent_view_content},
    )
    template_vars["manual_resolution_file"] = str(phase_run_dir / "manual_resolution")
    template_vars["run_summary_file"] = str(phase_run_dir / "summary.json")
    if ctx.resolved_decisions:
        template_vars["resolved_decisions"] = ctx.resolved_decisions
    return template_vars


def _invoke_subunit(
    config: dict[str, Any],
    ctx: RuntimeContext,
    project_root: Path,
    phase_run_dir: Path,
    design_path: Path,
    headers: list[str],
    subunit_name: str,
    sub_rows: list[dict[str, str]],
    max_acceptance_chars: int,
    max_specs_per_subunit: int,
    subunits_dir: Path,
) -> tuple[dict[str, Any] | None, str | None]:
    """Invoke the mapper agent for one subunit. Returns (output, error_message)."""
    if not sub_rows:
        return None, None
    row_count = len(sub_rows)

    if max_specs_per_subunit and max_specs_per_subunit > 0 and row_count > max_specs_per_subunit:
        batches = [
            sub_rows[i : i + max_specs_per_subunit]
            for i in range(0, row_count, max_specs_per_subunit)
        ]
    else:
        batches = [sub_rows]

    log_lifecycle_event(
        "lifecycle_invoke_agent",
        command="map",
        run_id=ctx.run_id,
        extra={"subunit": subunit_name, "row_count": row_count, "batches": len(batches)},
    )

    sub_batch_outputs: list[dict[str, Any]] = []
    sanitized = sanitize_subunit_for_filename(subunit_name)
    schema_path = resolve_output_schema_path(config, project_root, "map_output", command="map")

    for batch_idx, batch_rows in enumerate(batches):
        csv_content = build_agent_view_csv_content(
            headers, batch_rows, max_acceptance_chars=max_acceptance_chars,
        )
        if not csv_content:
            continue
        template_vars = _build_template_vars(
            config, project_root, ctx, phase_run_dir, design_path, csv_content,
        )
        try:
            out = invoke_agent_with_schema_retry(
                prompt_name=_get_prompt_name(config),
                template_vars=template_vars,
                schema_path=schema_path,
                config=config,
                ctx=ctx,
            )
            sub_batch_outputs.append(out)
        except Exception as exc:  # noqa: BLE001
            return None, f"subunit {subunit_name!r} batch {batch_idx}: {exc}"

    if not sub_batch_outputs:
        return None, None

    if len(sub_batch_outputs) == 1:
        subunit_out = sub_batch_outputs[0]
    else:
        try:
            subunit_out = merge_subunit_results(sub_batch_outputs)
        except ValueError as exc:
            return None, f"sub-batch merge for {subunit_name!r}: {exc}"

    subunits_dir.mkdir(parents=True, exist_ok=True)
    (subunits_dir / f"{sanitized}.json").write_text(
        json.dumps(subunit_out, indent=2), encoding="utf-8",
    )
    return subunit_out, None


def _run_match_fresh(
    config: dict[str, Any],
    ctx: RuntimeContext,
    phase_run_dir: Path,
    inputs: dict[str, Any],
) -> PhaseResult:
    """Load SADS → invoke per-subunit agents → coalesced gate → translate or block."""
    project_root = Path(ctx.project_root)

    raw_design = inputs.get("design_spec_path")
    if raw_design is None:
        return PhaseFailed(error_code="inputs_invalid", message="design_spec_path is required")
    design_path = Path(raw_design)
    if not design_path.exists():
        return PhaseFailed(
            error_code="input_missing",
            message=f"design_spec_path does not exist: {design_path}",
        )

    raw_codebase = inputs.get("codebase_dir")
    if raw_codebase is None:
        return PhaseFailed(error_code="inputs_invalid", message="codebase_dir is required")
    codebase_dir = Path(raw_codebase)
    if not codebase_dir.exists():
        return PhaseFailed(
            error_code="input_missing",
            message=f"codebase_dir does not exist: {codebase_dir}",
        )

    headers, rows = load_sads_csv_or_xlsx(design_path)
    add_if_missing = get_design_spec_add_if_missing(config)
    headers, rows = append_missing_columns(headers, rows, add_if_missing)
    try:
        validate_subunit_column(headers, rows)
        validate_spec_id_unique(headers, rows)
    except ValueError as exc:
        return PhaseFailed(error_code="inputs_invalid", message=str(exc))

    map_cfg = _get_map_config(config, ctx)
    filtered = filter_rows_for_mapping(
        headers, rows,
        skip_mapped=map_cfg["skip_mapped"],
        min_remapping_confidence_threshold=map_cfg["min_remapping_confidence_threshold"],
    )

    phase_run_dir.mkdir(parents=True, exist_ok=True)
    subunits_dir = phase_run_dir / "subunits"

    if not filtered:
        empty: dict[str, Any] = {
            "manual_resolution_items": [],
            "run_summary": {},
            "created_at": "",
            "mappings": {},
        }
        _write_json(phase_run_dir / "map_output.json", empty)
        return PhaseCompleted(
            artifacts_index={"map_output": "map_output.json"},
            summary={"mappings": 0, "subunits": 0, "no_op": True},
        )

    subunit_groups = group_by_subunit(headers, filtered)
    subunit_filter = map_cfg["subunit_filter"]
    subunit_order = sorted(subunit_groups.keys())
    if subunit_filter:
        subunit_order = [s for s in subunit_order if s in subunit_filter]
        if not subunit_order:
            return PhaseCompleted(
                artifacts_index={},
                summary={"mappings": 0, "subunits": 0, "filtered_out": True},
            )

    results_with_order: list[tuple[int, dict[str, Any]]] = []
    partial_failures: list[str] = []
    lock = threading.Lock()

    def _task(idx_name: tuple[int, str]) -> None:
        idx, subunit_name = idx_name
        out, err = _invoke_subunit(
            config, ctx, project_root, phase_run_dir, design_path, headers,
            subunit_name, subunit_groups[subunit_name],
            map_cfg["max_acceptance_chars"], map_cfg["max_specs_per_subunit"],
            subunits_dir,
        )
        if err:
            with lock:
                partial_failures.append(err)
            return
        if out is None:
            return
        with lock:
            results_with_order.append((idx, out))

    with concurrent.futures.ThreadPoolExecutor() as executor:
        list(executor.map(_task, enumerate(subunit_order)))

    if partial_failures:
        return PhaseFailed(
            error_code="map_agent_failed",
            message="; ".join(partial_failures),
        )

    results_with_order.sort(key=lambda x: x[0])
    batch_outputs: list[dict[str, Any]] = [out for _, out in results_with_order]

    return _finalize_match_outputs(
        batch_outputs=batch_outputs,
        phase_run_dir=phase_run_dir,
        ctx=ctx,
        config=config,
        map_cfg=map_cfg,
        codebase_dir=codebase_dir,
        design_path=design_path,
        extra_summary={},
    )


def _finalize_match_outputs(
    *,
    batch_outputs: list[dict[str, Any]],
    phase_run_dir: Path,
    ctx: RuntimeContext,
    config: dict[str, Any],
    map_cfg: dict[str, Any],
    codebase_dir: Path,
    design_path: Path,
    extra_summary: dict[str, Any],
) -> PhaseResult:
    """Post-agent processing: coalesced gate, merge, validate, translate.

    Shared by fresh-run and subunits-only cache replay so behavior is identical.
    """
    blocked_items: list[dict[str, Any]] = []
    for out in batch_outputs:
        if has_blocking_manual_resolution(out):
            for item in out.get("manual_resolution_items") or []:
                if isinstance(item, dict):
                    blocked_items.append(item)

    if blocked_items:
        manual_dir = phase_run_dir / "manual_resolution"
        phase_run_id = phase_run_dir.name or ctx.run_id
        _write_phase_resolution_block(blocked_items, manual_dir, phase_run_dir, phase_run_id)
        return PhaseBlocked(
            manual_dir=manual_dir,
            item_count=len(blocked_items),
            blocking_reason=f"map: {len(blocked_items)} manual-resolution item(s) across subunits",
        )

    try:
        merged = merge_subunit_results(batch_outputs)
    except ValueError as exc:
        return PhaseFailed(error_code="map_merge_failed", message=str(exc))

    try:
        validate_map_output_contract(
            merged,
            min_remapping_confidence_threshold=map_cfg["min_remapping_confidence_threshold"],
        )
    except ValueError as exc:
        return PhaseFailed(error_code="map_contract_invalid", message=str(exc))

    try:
        validate_code_ref_paths(merged, codebase_dir)
    except ValueError as exc:
        return PhaseFailed(error_code="map_code_ref_invalid", message=str(exc))

    _write_json(phase_run_dir / "map_output.json", merged)
    try:
        translate_map(config, ctx, merged, {"design_spec_path": design_path})
    except Exception as exc:  # noqa: BLE001
        return PhaseFailed(error_code="map_translate_failed", message=str(exc))

    summary: dict[str, Any] = {
        "mappings": len(merged.get("mappings") or {}),
        "subunits": len(batch_outputs),
    }
    summary.update(extra_summary)
    return PhaseCompleted(
        artifacts_index={
            "map_output": "map_output.json",
            "subunit_outputs": "subunits/*.json",
        },
        summary=summary,
    )


def run(
    config: dict[str, Any],
    ctx: RuntimeContext,
    phase_run_dir: Path,
    inputs: dict[str, Any],
) -> PhaseResult:
    project_root = Path(ctx.project_root)

    prior_run_id = inputs.get("prior_match_run_id")
    if isinstance(prior_run_id, str) and prior_run_id.strip():
        return _cache_replay(config, ctx, project_root, prior_run_id.strip(), phase_run_dir, inputs)

    ctx = _ctx_with_overrides(ctx, _build_overrides_from_inputs(inputs))

    resolutions_path = phase_run_dir / "manual_resolution" / "resolutions.yaml"
    if resolutions_path.exists():
        resolutions = load_resolution_file(phase_run_dir)
        if resolutions is not None:
            is_valid, _errors = validate_resolutions(resolutions)
            if not is_valid:
                item_count = len([
                    i for i in (resolutions.get("items") or []) if isinstance(i, dict)
                ])
                return PhaseBlocked(
                    manual_dir=phase_run_dir / "manual_resolution",
                    item_count=item_count,
                    blocking_reason=f"map: {item_count} unresolved items",
                )
            resolved_text = build_resolved_decisions_context(resolutions)
            ctx = _ctx_with_resolved_decisions(ctx, resolved_text)

    return _run_match_fresh(config, ctx, phase_run_dir, inputs)


def register(registry: PhaseRegistry) -> None:
    if registry.contract(MAP_MATCH.name) is None:
        registry.register(MAP_MATCH, run)
