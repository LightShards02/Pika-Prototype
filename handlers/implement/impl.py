"""Orchestrator for `agent implement` with unified planning and execution workflow."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.constants import ImplementStatus
from core.resolution import RESOLUTION_SOURCE_VALIDATION
from core.context import RuntimeContext
from core.format_sads import load_sads_csv_or_xlsx, rows_to_csv
from core.lifecycle import (
    cleanup_local_agent_temp_workspace,
    create_local_agent_shared_workspace,
    get_agent_provider,
    load_prompt_registry,
    log_lifecycle_event,
    resolve_agent_runs_dir_for_command,
    resolve_codebase_dir_path,
    resolve_input_path,
    resolve_project_context_content,
    sync_local_agent_workspace,
)

from handlers.implement.batching import (
    _build_batches,
    _build_briefs,
)
from handlers.implement.catalog import (
    _build_module_catalog,
    _minimal_specs,
    _select_workset,
)
from handlers.implement.config import (
    _get_impl_cfg,
)
from handlers.implement.execution import _execute_batch
from handlers.implement.helpers import (
    _find_col,
    _manual_block,
    _report_implement_phase,
    _sha256,
    _write_json,
)
from handlers.implement.semantic_guard import (
    build_directory_tree_snapshot,
    build_planner_path_contract,
    invoke_with_semantic_retry,
    validate_unified_plan_semantics,
)
from handlers.implement.spec_update import _update_design_and_test_spec
from handlers.implement.validation import (
    _validate_batch_plan_dependencies,
    _validate_brief_scoping,
    _validate_contract_field_consistency,
    _validate_unified_plan,
)


def _normalize_module_dir_name(module_tag: str) -> str:
    """Return a safe module directory name derived from module_tag."""
    name = str(module_tag or "").strip()
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise ValueError(f"Invalid module_tag for directory creation: {module_tag!r}")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise ValueError(f"Invalid module_tag for directory creation: {module_tag!r}")
    return name


def _ensure_batch_module_dirs(codebase_dir: Path, brief: dict[str, Any]) -> list[str]:
    """Ensure module root directories for a batch exist under codebase_dir."""
    codebase_root = codebase_dir.resolve()
    module_tags = sorted(
        {
            _normalize_module_dir_name(str(row.get("module_tag", "")).strip())
            for row in brief.get("spec_rows", [])
            if isinstance(row, dict) and str(row.get("module_tag", "")).strip()
        }
    )
    created: list[str] = []
    for module_tag in module_tags:
        target = (codebase_root / module_tag).resolve()
        try:
            target.relative_to(codebase_root)
        except ValueError as exc:
            raise ValueError(f"Resolved module dir escapes codebase_dir: {target}") from exc
        if target.exists():
            if not target.is_dir():
                raise ValueError(f"Module dir path exists as a file: {target}")
            continue
        target.mkdir(parents=True, exist_ok=True)
        created.append(f"{module_tag}/")
    return created


def run_implement(config: dict[str, Any], ctx: RuntimeContext) -> dict[str, Any]:
    """Run implement workflow: deterministic prep, unified planning, batching, execution, translation."""
    root = Path(ctx.project_root)
    impl = _get_impl_cfg(config)
    log_lifecycle_event("lifecycle_load_inputs", command="implement", run_id=ctx.run_id)

    design_path = resolve_input_path(
        config,
        root,
        "design_spec_path",
        overrides=ctx.input_overrides,
        command="implement",
    )
    if design_path is None or not design_path.exists():
        return {
            "command": "implement",
            "status": ImplementStatus.SKIPPED,
            "reason": "design_spec_path not configured or missing",
        }

    headers, rows = load_sads_csv_or_xlsx(design_path)
    selected = _select_workset(headers, rows)
    log_lifecycle_event(
        "lifecycle_workset_selected",
        command="implement",
        run_id=ctx.run_id,
        extra={"row_count": len(selected)},
    )
    _report_implement_phase("Load", "ok", f"{len(selected)} specs from design spec")
    paths = _init_run_workspace(config, root, ctx)
    _report_implement_phase("Workspace", "ok", f"run {ctx.run_id}")

    run_meta_path = paths["run"] / "run_meta.json"
    existing_run_meta: dict[str, Any] = {}
    if run_meta_path.exists():
        try:
            existing_run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
        except Exception:
            existing_run_meta = {}
    resume_blocked = bool(getattr(ctx, "resume_run_id", None))
    completed_stages_set: set[str] = set()
    if resume_blocked:
        completed_stages_set = {
            str(s).strip()
            for s in existing_run_meta.get("completed_stages", [])
            if str(s).strip()
        }

    run_meta_payload = dict(existing_run_meta)
    run_meta_payload.update(
        {
            "command": "implement",
            "run_id": ctx.run_id,
            "dry_run": ctx.dry_run,
            "budgets": impl["budgets"],
            "type_placement_path": impl["type_placement_path"],
            "config_hash": _sha256(
                json.dumps(config, sort_keys=True, default=str).encode("utf-8")
            ),
        }
    )
    if not resume_blocked:
        run_meta_payload.pop("blocked_at_stage", None)
        run_meta_payload.pop("resolution_status", None)
        run_meta_payload.pop("failed_at_stage", None)
    _write_json(
        run_meta_path,
        run_meta_payload,
    )
    _write_json(
        paths["run"] / "workset.json",
        {
            "selected": [
                {
                    "spec_id": row["spec_id"],
                    "module_tag": row["module_tag"],
                    "module_role": row["module_role"],
                }
                for row in selected
            ]
        },
    )
    if not selected:
        _write_json(
            paths["run"] / "summary.json",
            {"status": ImplementStatus.COMPLETED, "reason": "no specs to implement"},
        )
        return {"command": "implement", "status": ImplementStatus.COMPLETED, "dry_run": ctx.dry_run}

    codebase_dir = resolve_codebase_dir_path(config, root, ctx)
    module_catalog = _build_module_catalog(selected, impl["allowed_module_roles"], codebase_dir)
    _write_json(paths["run"] / "module_catalog.json", module_catalog)
    log_lifecycle_event(
        "lifecycle_module_catalog_built",
        command="implement",
        run_id=ctx.run_id,
        extra={"module_count": len(module_catalog["modules"])},
    )
    module_tags = ", ".join(m["module_tag"] for m in module_catalog["modules"])
    _report_implement_phase("Catalog", "ok", f"{len(module_catalog['modules'])} modules ({module_tags})")

    schemas = _resolve_prompt_schemas(config, impl)
    context_text = _project_context(config, root, ctx)
    provider = get_agent_provider(config)
    shared_local_workspace: Path | None = None
    if provider == "local":
        shared_local_workspace = create_local_agent_shared_workspace(
            config,
            root,
            command="implement",
            run_id=ctx.run_id,
        )
        log_lifecycle_event(
            "lifecycle_local_shared_workspace_created",
            command="implement",
            run_id=ctx.run_id,
            extra={"workspace_dir": str(shared_local_workspace)},
        )

    def _cleanup_shared_local_workspace() -> None:
        nonlocal shared_local_workspace
        if shared_local_workspace is None:
            return
        workspace_path = shared_local_workspace
        cleanup_local_agent_temp_workspace(workspace_path)
        log_lifecycle_event(
            "lifecycle_local_shared_workspace_cleaned",
            command="implement",
            run_id=ctx.run_id,
            extra={"workspace_dir": str(workspace_path)},
        )
        shared_local_workspace = None

    # --- Unified Planner (single agent call) ---
    if "unified_planner" in completed_stages_set and (paths["run"] / "unified_plan.json").exists():
        _report_implement_phase("Planner", "skipped", "resume: using cached output")
        planner_output = json.loads((paths["run"] / "unified_plan.json").read_text(encoding="utf-8"))
    else:
        _report_implement_phase("Planner", "running", "unified planner")
        minimal = _minimal_specs(selected)
        design_csv = rows_to_csv(
            ["spec_id", "title", "requirement", "acceptance_criteria", "module_tag", "module_role"],
            minimal,
        )
        planner_codebase_view = (
            shared_local_workspace.resolve()
            if shared_local_workspace is not None
            else codebase_dir.resolve()
        )
        planner_path_contract = build_planner_path_contract(
            module_catalog,
            impl["type_placement_path"],
            impl["forbidden_paths"],
        )
        template_vars: dict[str, Any] = {
            "output_schema_file": str(schemas["unified_planner"]),
            "project_context": context_text,
            "design_spec_csv": design_csv,
            "module_catalog_json": json.dumps(module_catalog, indent=2),
            "type_placement_path": impl["type_placement_path"],
            "manual_resolution_file": str(paths["manual"]),
            "run_summary_file": str(paths["run"] / "summary.json"),
            "allowed_paths_json": json.dumps(planner_path_contract, indent=2),
            "directory_tree_snapshot": build_directory_tree_snapshot(planner_codebase_view),
            "forbidden_path_patterns_json": json.dumps(
                planner_path_contract.get("forbidden_path_prefixes", []),
                indent=2,
            ),
            "semantic_retry_context": "",
        }
        template_vars["resolved_decisions"] = ctx.resolved_decisions or ""
        if shared_local_workspace is not None:
            sync_local_agent_workspace(codebase_dir, shared_local_workspace)
            log_lifecycle_event(
                "lifecycle_local_shared_workspace_resynced",
                command="implement",
                run_id=ctx.run_id,
                extra={
                    "source_dir": str(codebase_dir),
                    "workspace_dir": str(shared_local_workspace),
                    "phase": "unified_planner",
                },
            )
            template_vars["directory_tree_snapshot"] = build_directory_tree_snapshot(
                shared_local_workspace.resolve()
            )
        try:
            planner_output = invoke_with_semantic_retry(
                prompt_name=impl["unified_planner_prompt_name"],
                template_vars=template_vars,
                schema_path=schemas["unified_planner"],
                config=config,
                ctx=ctx,
                semantic_validator=lambda output: validate_unified_plan_semantics(
                    output,
                    planner_path_contract,
                ),
                semantic_validation_retries=impl["semantic_validation_retries"],
                validation_label="implement_unified_planner",
                local_workspace_override=shared_local_workspace,
            )
        except Exception as exc:
            _report_implement_phase("Planner", "failed", str(exc))
            _update_run_meta_state(
                run_meta_path,
                completed_stages=["load", "catalog"],
                failed_at_stage="unified_planner",
            )
            _write_json(
                paths["run"] / "summary.json",
                {
                    "status": ImplementStatus.FAILED,
                    "reason": "planner_invoke_failed",
                    "details": str(exc),
                },
            )
            _cleanup_shared_local_workspace()
            return {
                "command": "implement",
                "status": ImplementStatus.FAILED,
                "reason": "planner_invoke_failed",
            }
    _write_json(paths["run"] / "unified_plan.json", planner_output)
    log_lifecycle_event(
        "lifecycle_invoke_agent",
        command="implement",
        run_id=ctx.run_id,
        extra={"phase": "unified_planner"},
    )

    if _manual_block(
        planner_output,
        paths["manual"],
        "unified_planner",
        run_dir=paths["run"],
        command="implement",
        run_id=ctx.run_id,
        completed_stages=["load", "catalog"],
    ):
        n = len(planner_output.get("manual_resolution_items", []))
        _report_implement_phase("Planner", "blocked", f"{n} manual resolution items")
        _cleanup_shared_local_workspace()
        return {
            "command": "implement",
            "status": ImplementStatus.BLOCKED,
            "blocking_items": n,
        }

    module_plans = planner_output.get("module_plans", [])
    spec_dependencies = planner_output.get("spec_dependencies", [])
    shared_contracts = planner_output.get("shared_contracts", [])

    n_anchors = sum(len(mp.get("planned_anchors", [])) for mp in module_plans)
    _report_implement_phase(
        "Planner", "ok",
        f"{len(module_plans)} modules, {n_anchors} anchors, "
        f"{len(spec_dependencies)} cross-deps, {len(shared_contracts)} contracts",
    )

    # Write per-module plans for debugging
    for mp in module_plans:
        tag = mp.get("module_tag", "UNKNOWN")
        _write_json(paths["module_plans"] / f"{tag}.json", mp)

    # --- Validate unified plan ---
    all_spec_ids = {row["spec_id"] for row in selected}
    plan_validation = _validate_unified_plan(
        planner_output, all_spec_ids, module_catalog,
    )
    _write_json(paths["run"] / "plan_validation.json", plan_validation)

    if plan_validation["status"] != ImplementStatus.PASSED:
        reasons = plan_validation.get("reasons", [])
        _report_implement_phase("Plan validation", "failed", "; ".join(reasons[:3]))
        _write_json(
            paths["run"] / "summary.json",
            {"status": ImplementStatus.FAILED, "reason": "plan_validation_failed", "details": reasons},
        )
        _cleanup_shared_local_workspace()
        return {
            "command": "implement",
            "status": ImplementStatus.FAILED,
            "reason": "plan_validation_failed",
        }
    _report_implement_phase("Plan validation", "ok", "DAG valid, all specs covered")

    # --- Contract field consistency check ---
    resolution_items: list[dict[str, Any]] = []
    if resume_blocked:
        from core.resolution import load_resolution_file
        res_data = load_resolution_file(paths["run"])
        if res_data:
            resolution_items = res_data.get("items") or []
    contract_validation = _validate_contract_field_consistency(
        shared_contracts, selected, headers,
        resolutions=resolution_items if resolution_items else None,
        match_score_threshold=impl["field_match_score_threshold"],
    )
    patched_contracts = contract_validation.get("shared_contracts")
    if isinstance(patched_contracts, list):
        shared_contracts = patched_contracts
    _write_json(paths["run"] / "contract_field_validation.json", contract_validation)
    if contract_validation["status"] != ImplementStatus.PASSED:
        items = contract_validation.get("manual_resolution_items", [])
        _manual_block(
            None,
            paths["manual"],
            "contract_field_consistency",
            run_dir=paths["run"],
            command="implement",
            run_id=ctx.run_id,
            completed_stages=[
                "load",
                "catalog",
                "unified_planner",
                "plan_validation",
            ],
            source=RESOLUTION_SOURCE_VALIDATION,
            items=items,
            spec_rows=selected,
            headers=headers,
            shared_contracts=shared_contracts,
        )
        _report_implement_phase(
            "Contract field check", "blocked",
            f"{len(items)} field mismatch(es) require manual resolution",
        )
        _cleanup_shared_local_workspace()
        return {
            "command": "implement",
            "status": ImplementStatus.BLOCKED,
            "blocking_items": len(items),
        }
    _report_implement_phase("Contract field check", "ok", "all contract fields consistent")

    # --- Build batches from spec dependency graph ---
    anchor_plans_by_module = {
        mp["module_tag"]: mp
        for mp in module_plans
        if isinstance(mp, dict) and mp.get("module_tag")
    }
    batch_plan = _build_batches(
        selected,
        spec_dependencies,
        impl["budgets"],
        anchor_plans=anchor_plans_by_module,
        module_plans=module_plans,
    )
    _write_json(paths["run"] / "batch_plan.json", batch_plan)
    batch_plan_validation = _validate_batch_plan_dependencies(
        batch_plan, spec_dependencies,
    )
    _write_json(paths["run"] / "batch_plan_validation.json", batch_plan_validation)
    log_lifecycle_event(
        "lifecycle_batch_plan_validated",
        command="implement",
        run_id=ctx.run_id,
        extra={
            "batch_count": len(batch_plan.get("batches", [])),
            "validation_status": batch_plan_validation.get("status"),
        },
    )
    if batch_plan_validation["status"] != ImplementStatus.PASSED:
        _update_run_meta_state(
            run_meta_path,
            completed_stages=[
                "load",
                "catalog",
                "unified_planner",
                "plan_validation",
                "contract_field_consistency",
            ],
            failed_at_stage="batch_plan",
        )
        _report_implement_phase("Batch plan", "failed", "dependency cycle or validation error")
        _write_json(
            paths["run"] / "summary.json",
            {"status": ImplementStatus.FAILED, "reason": "batch_plan_validation_failed"},
        )
        _cleanup_shared_local_workspace()
        return {
            "command": "implement",
            "status": ImplementStatus.FAILED,
            "reason": "batch_plan_validation_failed",
        }
    n_batches = len(batch_plan.get("batches", []))
    _report_implement_phase("Batch plan", "ok", f"{n_batches} batches")

    # --- Build briefs ---
    briefs = _build_briefs(
        selected,
        anchor_plans_by_module,
        spec_dependencies,
        shared_contracts,
        batch_plan,
        impl,
    )
    for brief in briefs:
        _write_json(paths["briefs"] / f"{brief['batch_id']}.json", brief)
    log_lifecycle_event(
        "lifecycle_batch_briefs_built",
        command="implement",
        run_id=ctx.run_id,
        extra={"brief_count": len(briefs)},
    )
    _report_implement_phase("Briefs", "ok", f"{len(briefs)} batch briefs")

    # --- Validate brief scoping ---
    brief_validation = _validate_brief_scoping(briefs)
    _write_json(paths["run"] / "brief_validation.json", brief_validation)
    if brief_validation["status"] != ImplementStatus.PASSED:
        _update_run_meta_state(
            run_meta_path,
            completed_stages=[
                "load",
                "catalog",
                "unified_planner",
                "plan_validation",
                "contract_field_consistency",
                "batch_plan",
                "briefs",
            ],
            failed_at_stage="brief_validation",
        )
        reasons = brief_validation.get("reasons", [])
        _report_implement_phase("Brief validation", "failed", "; ".join(reasons))
        _write_json(
            paths["run"] / "summary.json",
            {"status": ImplementStatus.FAILED, "reason": "brief_validation_failed", "details": reasons},
        )
        _cleanup_shared_local_workspace()
        return {
            "command": "implement",
            "status": ImplementStatus.FAILED,
            "reason": "brief_validation_failed",
        }
    _report_implement_phase("Brief validation", "ok", "all briefs batch-scoped")

    # --- Execute batches ---
    if ctx.dry_run:
        _update_run_meta_state(
            run_meta_path,
            completed_stages=[
                "load",
                "catalog",
                "unified_planner",
                "plan_validation",
                "contract_field_consistency",
                "batch_plan",
                "briefs",
                "brief_validation",
            ],
            failed_at_stage=None,
        )
        _report_implement_phase("Execute", "skipped", "dry-run")
        _write_json(paths["run"] / "summary.json", {"status": ImplementStatus.COMPLETED, "dry_run": True})
        _cleanup_shared_local_workspace()
        return {"command": "implement", "status": ImplementStatus.COMPLETED, "dry_run": True}

    base_stages = [
        "load",
        "catalog",
        "unified_planner",
        "plan_validation",
        "contract_field_consistency",
        "batch_plan",
        "briefs",
        "brief_validation",
    ]
    spec_outputs: dict[str, dict[str, Any]] = {}
    for idx, brief in enumerate(briefs, start=1):
        batch_id = brief["batch_id"]
        execute_stage = f"execute_{batch_id}"
        completed_stages = base_stages + [
            f"execute_{b['batch_id']}" for b in briefs[: idx - 1]
        ]
        if resume_blocked and execute_stage in completed_stages_set:
            cached_path = paths["agent_outputs"] / f"implement_{batch_id}.json"
            if cached_path.exists():
                try:
                    cached_output = json.loads(cached_path.read_text(encoding="utf-8"))
                except Exception:
                    cached_output = None
                if cached_output and not cached_output.get("manual_resolution_items"):
                    from handlers.implement.execution import _collect_spec_output
                    try:
                        parsed = _collect_spec_output(cached_output)
                        spec_outputs.update(parsed)
                        _report_implement_phase("Execute", "skipped", f"{batch_id} (resume: cached)")
                        log_lifecycle_event(
                            "lifecycle_batch_executed",
                            command="implement",
                            run_id=ctx.run_id,
                            extra={"batch_id": batch_id, "spec_count": len(parsed), "resumed": True},
                        )
                        continue
                    except Exception:
                        pass
        _report_implement_phase("Execute", "running", f"{batch_id} ({idx}/{len(briefs)})")
        try:
            created_dirs = _ensure_batch_module_dirs(codebase_dir, brief)
            log_lifecycle_event(
                "lifecycle_batch_module_dirs_created",
                command="implement",
                run_id=ctx.run_id,
                extra={
                    "batch_id": batch_id,
                    "created_count": len(created_dirs),
                    "created_dirs": json.dumps(created_dirs),
                },
            )
            if shared_local_workspace is not None:
                sync_local_agent_workspace(codebase_dir, shared_local_workspace)
                log_lifecycle_event(
                    "lifecycle_local_shared_workspace_resynced",
                    command="implement",
                    run_id=ctx.run_id,
                    extra={
                        "source_dir": str(codebase_dir),
                        "workspace_dir": str(shared_local_workspace),
                        "phase": "batch_pre_execute_dir_sync",
                        "batch_id": batch_id,
                    },
                )
            result = _execute_batch(
                config,
                ctx,
                impl,
                schemas["implementer"],
                root,
                context_text,
                paths,
                headers,
                brief,
                completed_stages=completed_stages,
                local_workspace_override=shared_local_workspace,
            )
        except Exception as exc:
            _update_run_meta_state(
                run_meta_path,
                completed_stages=completed_stages,
                failed_at_stage=execute_stage,
            )
            _report_implement_phase("Execute", "failed", f"{execute_stage}: {exc}")
            _write_json(
                paths["run"] / "summary.json",
                {
                    "status": ImplementStatus.FAILED,
                    "reason": f"execute_exception_{batch_id}",
                    "details": str(exc),
                },
            )
            _cleanup_shared_local_workspace()
            return {
                "command": "implement",
                "status": ImplementStatus.FAILED,
                "reason": f"execute_exception_{batch_id}",
            }
        if result["status"] != ImplementStatus.COMPLETED:
            reason = result.get("reason", "batch_failed")
            if result.get("status") == ImplementStatus.BLOCKED:
                _report_implement_phase("Execute", "blocked", f"{brief['batch_id']} manual resolution")
            else:
                _update_run_meta_state(
                    run_meta_path,
                    completed_stages=completed_stages,
                    failed_at_stage=execute_stage,
                )
                _report_implement_phase("Execute", "failed", reason)
            _write_json(
                paths["run"] / "summary.json",
                {
                    "status": result["status"],
                    "reason": reason,
                },
            )
            _cleanup_shared_local_workspace()
            return {
                "command": "implement",
                "status": result["status"],
                "reason": reason,
            }
        spec_outputs.update(result.get("spec_outputs", {}))
        log_lifecycle_event(
            "lifecycle_batch_executed",
            command="implement",
            run_id=ctx.run_id,
            extra={"batch_id": brief["batch_id"], "spec_count": len(brief.get("spec_rows", []))},
        )

    _report_implement_phase("Execute", "ok", f"{len(briefs)} batches completed")

    try:
        _update_design_and_test_spec(config, ctx, impl, design_path, spec_outputs)
    except Exception as exc:
        _update_run_meta_state(
            run_meta_path,
            completed_stages=base_stages + [f"execute_{b['batch_id']}" for b in briefs],
            failed_at_stage="translate",
        )
        _report_implement_phase("Translate", "failed", str(exc))
        _write_json(
            paths["run"] / "summary.json",
            {
                "status": ImplementStatus.FAILED,
                "reason": "translate_failed",
                "details": str(exc),
            },
        )
        _cleanup_shared_local_workspace()
        return {
            "command": "implement",
            "status": ImplementStatus.FAILED,
            "reason": "translate_failed",
        }
    log_lifecycle_event(
        "lifecycle_translate",
        command="implement",
        run_id=ctx.run_id,
        extra={"spec_output_count": len(spec_outputs)},
    )
    _report_implement_phase("Translate", "ok", "design spec + test spec updated")
    _update_run_meta_state(
        run_meta_path,
        completed_stages=base_stages + [f"execute_{b['batch_id']}" for b in briefs] + ["translate"],
        failed_at_stage=None,
    )
    _write_json(
        paths["run"] / "summary.json",
        {"status": ImplementStatus.COMPLETED, "batches_completed": len(briefs), "batches_failed": 0},
    )
    _cleanup_shared_local_workspace()
    return {"command": "implement", "status": ImplementStatus.COMPLETED, "dry_run": False}


def _resolve_prompt_schemas(config: dict[str, Any], impl: dict[str, Any]) -> dict[str, Path]:
    """Resolve schema paths for unified planner and implementer prompts."""
    registry = load_prompt_registry(config)
    return {
        "unified_planner": registry.get_schema_path(impl["unified_planner_prompt_name"]),
        "implementer": registry.get_schema_path(impl["prompt_name"]),
    }


def _project_context(config: dict[str, Any], root: Path, ctx: RuntimeContext) -> str:
    """Resolve project context content using shared lifecycle resolver."""
    codebase = resolve_codebase_dir_path(config, root, ctx)
    return resolve_project_context_content(config, root, ctx, codebase)


def _init_run_workspace(config: dict[str, Any], root: Path, ctx: RuntimeContext) -> dict[str, Path]:
    """Create run workspace directories and return keyed paths.

    Uses out/agent_runs/implement/{run_id}/ for run workspace.
    """
    run = resolve_agent_runs_dir_for_command(config, root, "implement", ctx.run_id)
    paths = {
        "run": run,
        "module_plans": run / "module_plans",
        "manual": run / "manual_resolution",
        "briefs": run / "batch_briefs",
        "agent_outputs": run / "agent_outputs",
        "patches": run / "patches",
        "verification": run / "verification",
        "trace": run / "trace",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _update_run_meta_state(
    run_meta_path: Path,
    *,
    completed_stages: list[str] | None,
    failed_at_stage: str | None,
) -> None:
    """Update run_meta stage progress and clear stale block metadata."""
    run_meta: dict[str, Any] = {}
    if run_meta_path.exists():
        try:
            run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
        except Exception:
            run_meta = {}
    if completed_stages is not None:
        run_meta["completed_stages"] = list(completed_stages)
    if failed_at_stage:
        run_meta["failed_at_stage"] = failed_at_stage
    else:
        run_meta.pop("failed_at_stage", None)
    run_meta.pop("blocked_at_stage", None)
    run_meta.pop("resolution_status", None)
    _write_json(run_meta_path, run_meta)
