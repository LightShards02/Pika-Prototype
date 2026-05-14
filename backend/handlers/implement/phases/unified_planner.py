"""Phase: implement.unified-planner — single coalesced planner gate over a workspace."""

from __future__ import annotations

import json
from dataclasses import replace as _dc_replace
from pathlib import Path
from typing import Any

from core.appendix_loader import (
    appendix_entries_to_lookup,
    assign_appendix_ids,
    format_appendix_for_agent,
    load_appendix_files,
)
from core.context import RuntimeContext
from core.format_sads import load_sads_csv_or_xlsx, rows_to_csv
from core.lifecycle import (
    load_prompt_registry,
    resolve_phase_run_dir,
    resolve_project_context_content,
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

from handlers.implement.catalog import _build_module_catalog, _select_workset
from handlers.implement.config import _get_impl_cfg
from handlers.implement.planner import (
    _escalate_spec_issues,
    _minimal_specs,
    build_directory_tree_snapshot,
    build_planner_path_contract,
    invoke_with_semantic_retry,
    validate_unified_plan_semantics,
)


UNIFIED_PLANNER = PhaseContract(
    name="implement.unified-planner",
    command="implement",
    inputs=(
        PhaseInput(
            name="design_spec_path",
            kind="workspace_relative_path",
            required=True,
            description="Path to design spec CSV (Formatted SADS) relative to workspace root, or absolute.",
        ),
        PhaseInput(
            name="codebase_dir",
            kind="workspace_relative_path",
            required=True,
            description="Path to the codebase root used for path-contract construction + directory tree snapshot.",
        ),
        PhaseInput(
            name="project_context_path",
            kind="workspace_relative_path",
            required=False,
            description="Path to project context markdown (e.g., PROJECT_CONTEXT.md).",
        ),
        PhaseInput(
            name="prior_planner_run_id",
            kind="phase_run_ref",
            required=False,
            description="Phase-run ID of a previously completed implement.unified-planner run whose unified_plan.json should be used as the result (cache-replay).",
            ref_phase="implement.unified-planner",
        ),
    ),
    outputs=(
        PhaseOutput(name="unified_plan", path="unified_plan.json", schema_ref="unified_planner_output"),
        PhaseOutput(name="spec_issues", path="spec_issues.json"),
    ),
    recommended_prerequisites=("refine.quality-audit",),
    can_block=True,
    destructive=False,
    async_execution=True,
    description=(
        "Run the unified planner agent over the design spec + module catalog + codebase. "
        "Produces module_plans, spec_dependencies, shared_contracts, and spec_issues. "
        "Blocks on planner manual-resolution items OR escalated spec issues (coalesced)."
    ),
)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _step_enabled(impl: dict[str, Any], step_name: str) -> bool:
    steps = impl.get("steps", {}) if isinstance(impl.get("steps", {}), dict) else {}
    step_cfg = steps.get(step_name, {}) if isinstance(steps.get(step_name, {}), dict) else {}
    enabled = step_cfg.get("enabled")
    return enabled if isinstance(enabled, bool) else True


def _step_value(impl: dict[str, Any], step_name: str, field_name: str, default: Any) -> Any:
    steps = impl.get("steps", {}) if isinstance(impl.get("steps", {}), dict) else {}
    step_cfg = steps.get(step_name, {}) if isinstance(steps.get(step_name, {}), dict) else {}
    value = step_cfg.get(field_name, default)
    return default if value is None else value


def _cache_replay(
    config: dict[str, Any],
    project_root: Path,
    prior_run_id: str,
    phase_run_dir: Path,
) -> PhaseResult:
    """Reuse a previously completed planner run's unified_plan.json as result."""
    try:
        prior_dir = resolve_phase_run_dir(
            config, project_root, "implement.unified-planner", prior_run_id,
        )
    except ValueError:
        return PhaseFailed(
            error_code="prior_phase_artifact_missing",
            message=f"prior_planner_run_id {prior_run_id!r} is invalid",
        )
    prior_plan = prior_dir / "unified_plan.json"
    if not prior_dir.exists() or not prior_plan.exists():
        return PhaseFailed(
            error_code="prior_phase_artifact_missing",
            message=(
                f"unified_plan.json not found in prior implement.unified-planner run "
                f"{prior_run_id!r} (expected at {prior_plan})"
            ),
        )

    phase_run_dir.mkdir(parents=True, exist_ok=True)
    plan_dest = phase_run_dir / "unified_plan.json"
    plan_dest.write_text(prior_plan.read_text(encoding="utf-8"), encoding="utf-8")

    artifacts_index: dict[str, str] = {"unified_plan": "unified_plan.json"}
    prior_issues = prior_dir / "spec_issues.json"
    if prior_issues.exists():
        issues_dest = phase_run_dir / "spec_issues.json"
        issues_dest.write_text(prior_issues.read_text(encoding="utf-8"), encoding="utf-8")
        artifacts_index["spec_issues"] = "spec_issues.json"

    return PhaseCompleted(
        artifacts_index=artifacts_index,
        summary={"cache_replay": True, "source_phase_run_id": prior_run_id},
    )


def _coalesced_items(planner_output: dict[str, Any], selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge planner manual_resolution_items with escalated spec_issues, preserving each item's kind."""
    planner_items_raw = planner_output.get("manual_resolution_items") or []
    planner_items = [item for item in planner_items_raw if isinstance(item, dict)]
    spec_issues = planner_output.get("spec_issues") or []
    spec_issue_items = _escalate_spec_issues(
        spec_issues if isinstance(spec_issues, list) else [],
        selected,
    )
    return list(planner_items) + list(spec_issue_items)


def _write_phase_resolution_block(
    items: list[dict[str, Any]],
    manual_dir: Path,
    stage: str,
    phase_run_dir: Path,
    phase_run_id: str,
) -> None:
    """Write {stage}.json + resolutions.yaml under manual_dir for a coalesced planner gate."""
    manual_dir.mkdir(parents=True, exist_ok=True)
    _write_json(manual_dir / f"{stage}.json", {"stage": stage, "items": items})
    generate_resolution_template(
        run_dir=phase_run_dir,
        stage=stage,
        items=items,
        command="implement",
        run_id=phase_run_id,
        source=RESOLUTION_SOURCE_VALIDATION,
    )


def _ctx_with_resolved_decisions(ctx: RuntimeContext, resolved: str) -> RuntimeContext:
    """Return a copy of ctx with resolved_decisions populated."""
    return _dc_replace(ctx, resolved_decisions=resolved)


def _build_planner_template_vars(
    impl: dict[str, Any],
    config: dict[str, Any],
    ctx: RuntimeContext,
    project_root: Path,
    phase_run_dir: Path,
    design_path: Path,
    codebase_dir: Path,
    project_context_path: Path | None,
    selected: list[dict[str, Any]],
    module_catalog: dict[str, Any],
    planner_path_contract: dict[str, Any],
) -> tuple[dict[str, Any], Path]:
    """Build the template_vars dict + schema path for invoke_with_semantic_retry."""
    registry = load_prompt_registry(config)
    schema_path = registry.get_schema_path(impl["unified_planner_prompt_name"])

    if project_context_path is not None and project_context_path.exists():
        context_text = project_context_path.read_text(encoding="utf-8")
    else:
        context_text = resolve_project_context_content(config, project_root, ctx, codebase_dir)

    appendix_entries = load_appendix_files(config, project_root, command="implement")
    registry_path = Path(
        config.get("id_generation", {}).get("id_registry", "out/state/id_registry.json")
    )
    if appendix_entries:
        appendix_entries = assign_appendix_ids(appendix_entries, registry_path, project_root)
    appendix_text = format_appendix_for_agent(
        appendix_entries, max_chars=impl.get("max_appendix_chars", 0),
    )

    minimal = _minimal_specs(selected)
    design_csv = rows_to_csv(
        ["spec_id", "title", "requirement", "acceptance_criteria", "module_tag", "module_role"],
        minimal,
    )

    from core import memory_store as _memory_store
    manual_dir = phase_run_dir / "manual_resolution"
    template_vars: dict[str, Any] = {
        "output_schema_file": str(schema_path),
        "project_context": context_text,
        "design_spec_csv": design_csv,
        "module_catalog_json": json.dumps(module_catalog, indent=2),
        "type_placement_path": impl["type_placement_path"],
        "manual_resolution_file": str(manual_dir),
        "run_summary_file": str(phase_run_dir / "summary.json"),
        "allowed_paths_json": json.dumps(planner_path_contract, indent=2),
        "directory_tree_snapshot": build_directory_tree_snapshot(codebase_dir.resolve()),
        "forbidden_path_patterns_json": json.dumps(
            planner_path_contract.get("forbidden_path_prefixes", []),
            indent=2,
        ),
        "semantic_retry_context": "",
        "appendix_content": appendix_text,
        "resolved_decisions": ctx.resolved_decisions or "",
        "memory": _memory_store.memory_template_value(ctx),
    }
    return template_vars, schema_path


def _run_planner_fresh(
    config: dict[str, Any],
    ctx: RuntimeContext,
    phase_run_dir: Path,
    inputs: dict[str, Any],
) -> PhaseResult:
    """Resolve inputs, invoke the planner agent, persist outputs, coalesce gates."""
    project_root = Path(ctx.project_root)
    impl = _get_impl_cfg(config)

    raw_design = inputs.get("design_spec_path")
    if raw_design is None:
        return PhaseFailed(
            error_code="inputs_invalid",
            message="design_spec_path is required",
        )
    design_path = Path(raw_design)
    if not design_path.exists():
        return PhaseFailed(
            error_code="input_missing",
            message=f"design_spec_path does not exist: {design_path}",
        )

    raw_codebase = inputs.get("codebase_dir")
    if raw_codebase is None:
        return PhaseFailed(
            error_code="inputs_invalid",
            message="codebase_dir is required",
        )
    codebase_dir = Path(raw_codebase)
    if not codebase_dir.exists():
        return PhaseFailed(
            error_code="input_missing",
            message=f"codebase_dir does not exist: {codebase_dir}",
        )

    project_context_path: Path | None = None
    raw_ctx_path = inputs.get("project_context_path")
    if raw_ctx_path is not None:
        project_context_path = Path(raw_ctx_path)

    headers, rows = load_sads_csv_or_xlsx(design_path)
    try:
        selected = _select_workset(headers, rows)
    except ValueError as exc:
        return PhaseFailed(error_code="workset_invalid", message=str(exc))

    if not selected:
        phase_run_dir.mkdir(parents=True, exist_ok=True)
        _write_json(phase_run_dir / "unified_plan.json", {"module_plans": [], "spec_dependencies": [], "shared_contracts": [], "spec_issues": []})
        _write_json(phase_run_dir / "spec_issues.json", {"spec_issues": []})
        return PhaseCompleted(
            artifacts_index={"unified_plan": "unified_plan.json", "spec_issues": "spec_issues.json"},
            summary={"module_plans": 0, "spec_dependencies": 0, "shared_contracts": 0, "spec_issues": 0, "selected": 0},
        )

    try:
        module_catalog = _build_module_catalog(selected, impl["allowed_module_roles"], codebase_dir)
    except ValueError as exc:
        return PhaseFailed(error_code="module_catalog_invalid", message=str(exc))

    planner_path_contract = (
        build_planner_path_contract(
            module_catalog,
            impl["type_placement_path"],
            impl["forbidden_paths"],
        )
        if _step_enabled(impl, "planner_path_contract_prep")
        else {
            "module_root_prefixes_by_tag": {},
            "shared_contract_prefix": "",
            "forbidden_path_prefixes": [],
        }
    )

    phase_run_dir.mkdir(parents=True, exist_ok=True)
    template_vars, schema_path = _build_planner_template_vars(
        impl,
        config,
        ctx,
        project_root,
        phase_run_dir,
        design_path,
        codebase_dir,
        project_context_path,
        selected,
        module_catalog,
        planner_path_contract,
    )

    try:
        planner_output = invoke_with_semantic_retry(
            prompt_name=impl["unified_planner_prompt_name"],
            template_vars=template_vars,
            schema_path=schema_path,
            config=config,
            ctx=ctx,
            semantic_validator=(
                (lambda output: validate_unified_plan_semantics(output, planner_path_contract))
                if _step_enabled(impl, "planner_semantic_validation")
                else (lambda _output: [])
            ),
            semantic_validation_retries=int(
                _step_value(
                    impl,
                    "planner_semantic_validation",
                    "semantic_validation_retries",
                    impl.get("semantic_validation_retries", 2),
                )
            ),
            validation_label="implement_unified_planner",
        )
    except Exception as exc:  # noqa: BLE001
        return PhaseFailed(error_code="planner_failed", message=str(exc))

    spec_issues = planner_output.get("spec_issues") or []
    _write_json(phase_run_dir / "spec_issues.json", {"spec_issues": spec_issues})

    merged_items = _coalesced_items(planner_output, selected)
    if merged_items:
        n_planner = len([
            i for i in (planner_output.get("manual_resolution_items") or []) if isinstance(i, dict)
        ])
        n_spec = len(merged_items) - n_planner
        manual_dir = phase_run_dir / "manual_resolution"
        phase_run_id = phase_run_dir.name or ctx.run_id
        _write_phase_resolution_block(
            merged_items, manual_dir, "unified_planner", phase_run_dir, phase_run_id,
        )
        return PhaseBlocked(
            manual_dir=manual_dir,
            item_count=len(merged_items),
            blocking_reason=(
                f"unified_planner: {len(merged_items)} items "
                f"(planner={n_planner}, spec_issues={n_spec})"
            ),
        )

    _write_json(phase_run_dir / "unified_plan.json", planner_output)
    module_plans = planner_output.get("module_plans") or []
    spec_dependencies = planner_output.get("spec_dependencies") or []
    shared_contracts = planner_output.get("shared_contracts") or []
    return PhaseCompleted(
        artifacts_index={
            "unified_plan": "unified_plan.json",
            "spec_issues": "spec_issues.json",
        },
        summary={
            "module_plans": len(module_plans),
            "spec_dependencies": len(spec_dependencies),
            "shared_contracts": len(shared_contracts),
            "spec_issues": len(spec_issues),
        },
    )


def run(
    config: dict[str, Any],
    ctx: RuntimeContext,
    phase_run_dir: Path,
    inputs: dict[str, Any],
) -> PhaseResult:
    project_root = Path(ctx.project_root)

    prior_run_id = inputs.get("prior_planner_run_id")
    if isinstance(prior_run_id, str) and prior_run_id.strip():
        return _cache_replay(config, project_root, prior_run_id.strip(), phase_run_dir)

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
                    blocking_reason=f"unified_planner: {item_count} unresolved items",
                )
            resolved_text = build_resolved_decisions_context(resolutions)
            ctx = _ctx_with_resolved_decisions(ctx, resolved_text)

    return _run_planner_fresh(config, ctx, phase_run_dir, inputs)


def register(registry: PhaseRegistry) -> None:
    if registry.contract(UNIFIED_PLANNER.name) is None:
        registry.register(UNIFIED_PLANNER, run)
