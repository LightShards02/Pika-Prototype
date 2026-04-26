"""Orchestrator for `agent implement` with unified planning and execution workflow."""

from __future__ import annotations

import json
import re
import tempfile
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor
from concurrent.futures import wait as futures_wait
from pathlib import Path
from typing import Any

from core.appendix_loader import (
    AppendixEntry,
    appendix_content_hash,
    appendix_entries_to_lookup,
    assign_appendix_ids,
    format_appendix_for_agent,
    load_appendix_files,
)
from core.constants import ImplementStatus
from core.errors import (
    AgentInvocationError,
    BatchValidationError,
    PikaError,
    PlanValidationError,
    ResumeError,
)
from core.resolution import RESOLUTION_SOURCE_VALIDATION, load_resolution_file
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
from handlers.implement.evaluator import (
    build_evaluator_feedback,
    collect_failed_spec_ids_above_threshold,
    eval_failures_to_resolution_items,
    evaluator_config,
    run_code_evaluator,
)
from handlers.implement.evidence_harnesses import collect_harness_results
from handlers.implement.execution import _collect_spec_output, _execute_batch
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
    _escalate_spec_issues,
    _validate_dependency_context_edges,
    _validate_required_field_coverage,
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
            raise PikaError(f"Resolved module dir escapes codebase_dir: {target}") from exc
        if target.exists():
            if not target.is_dir():
                raise PikaError(f"Module dir path exists as a file: {target}")
            continue
        target.mkdir(parents=True, exist_ok=True)
        created.append(f"{module_tag}/")
    return created


def _has_completed_agent_stage(stages: list[str]) -> bool:
    """Return True if any agent stage completed (planner or batch execution)."""
    if "unified_planner" in stages:
        return True
    return any(s.startswith("execute_") for s in stages)


def _step_enabled(impl: dict[str, Any], step_name: str) -> bool:
    """Return whether a deterministic implement step is enabled."""
    steps = impl.get("steps", {}) if isinstance(impl.get("steps", {}), dict) else {}
    step_cfg = steps.get(step_name, {}) if isinstance(steps.get(step_name, {}), dict) else {}
    enabled = step_cfg.get("enabled")
    return enabled if isinstance(enabled, bool) else True


def _step_value(impl: dict[str, Any], step_name: str, field_name: str, default: Any) -> Any:
    """Return step-scoped field value with fallback."""
    steps = impl.get("steps", {}) if isinstance(impl.get("steps", {}), dict) else {}
    step_cfg = steps.get(step_name, {}) if isinstance(steps.get(step_name, {}), dict) else {}
    value = step_cfg.get(field_name, default)
    return default if value is None else value


def _select_workset_relaxed(headers: list[str], rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Select workset without raising on missing required columns/values."""
    spec_col = _find_col(headers, "spec_id")
    tag_col = _find_col(headers, "module_tag")
    role_col = _find_col(headers, "module_role")
    status_col = _find_col(headers, "implementation_status")
    selected: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        status = (row.get(status_col, "") if status_col else "").strip().lower()
        if status == ImplementStatus.COMPLETED:
            continue
        spec_id = str(row.get(spec_col, "") if spec_col else row.get("spec_id", "")).strip()
        module_tag = str(row.get(tag_col, "") if tag_col else row.get("module_tag", "")).strip()
        module_role = str(row.get(role_col, "") if role_col else row.get("module_role", "")).strip().lower()
        if not spec_id or not module_tag or not module_role:
            continue
        normalized = dict(row)
        normalized["spec_id"] = spec_id
        normalized["module_tag"] = module_tag
        normalized["module_role"] = module_role
        selected.append(normalized)
    return selected


def _build_module_catalog_relaxed(
    rows: list[dict[str, str]],
    allowed_roles: set[str],
    codebase_dir: Path,
) -> dict[str, Any]:
    """Build module catalog by normalizing inconsistent/unknown roles deterministically."""
    fallback_role = sorted(allowed_roles)[0] if allowed_roles else "shared"
    role_by_module: dict[str, str] = {}
    normalized_rows: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        module_tag = str(row.get("module_tag", "")).strip()
        spec_id = str(row.get("spec_id", "")).strip()
        if not module_tag or not spec_id:
            continue
        raw_role = str(row.get("module_role", "")).strip().lower()
        chosen_role = role_by_module.get(module_tag)
        if chosen_role is None:
            chosen_role = raw_role if raw_role in allowed_roles else fallback_role
            role_by_module[module_tag] = chosen_role
        updated = dict(row)
        updated["module_role"] = chosen_role
        normalized_rows.append(updated)
    return _build_module_catalog(normalized_rows, allowed_roles, codebase_dir)


def _execute_briefs_concurrently(
    briefs: list[dict[str, Any]],
    max_parallel: int,
    *,
    config: dict[str, Any],
    ctx: RuntimeContext,
    impl: dict[str, Any],
    schemas: dict[str, Any],
    root: Path,
    context_text: str,
    paths: dict[str, Path],
    headers: list[str],
    base_stages: list[str],
    resume_mode: str,
    completed_stages_set: set[str],
    codebase_dir: Path,
    shared_local_workspace: Path | None,
    provider: str,
    appendix_content: str = "",
) -> dict[str, Any]:
    """Execute briefs with DAG-aware parallel dispatch (up to max_parallel concurrent LLM calls).

    Returns:
        On success: {"spec_outputs": dict[str, dict]}
        On failure: {"status": ImplementStatus, "reason": str, "batch_id": str}
    """
    bid_to_brief = {b["batch_id"]: b for b in briefs}
    deps: dict[str, set[str]] = {
        b["batch_id"]: set(b.get("depends_on_batches", []))
        for b in briefs
    }

    completed: set[str] = set()
    pending: set[str] = set(bid_to_brief)
    spec_outputs: dict[str, dict[str, Any]] = {}

    # Handle resume: mark cached batches as pre-completed before dispatching.
    for brief in briefs:
        bid = brief["batch_id"]
        execute_stage = f"execute_{bid}"
        if resume_mode != "none" and execute_stage in completed_stages_set:
            cached_path = paths["agent_outputs"] / f"implement_{bid}.json"
            if cached_path.exists():
                try:
                    cached_output = json.loads(cached_path.read_text(encoding="utf-8"))
                    if cached_output and not cached_output.get("manual_resolution_items"):
                        parsed = _collect_spec_output(cached_output)
                        spec_outputs.update(parsed)
                        completed.add(bid)
                        pending.discard(bid)
                        _report_implement_phase("Execute", "skipped", f"{bid} (resume: cached)")
                        log_lifecycle_event(
                            "lifecycle_batch_executed",
                            command="implement",
                            run_id=ctx.run_id,
                            extra={"batch_id": bid, "spec_count": len(parsed), "resumed": True},
                        )
                except Exception:
                    pass

    if not pending:
        return {"spec_outputs": spec_outputs}

    patch_lock = threading.Lock()
    failure: dict[str, Any] | None = None
    batch_workspaces: dict[str, Path | None] = {}

    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        in_flight: dict[Any, str] = {}  # future -> batch_id

        def _ready() -> list[str]:
            in_flight_bids = set(in_flight.values())
            return sorted([
                bid for bid in pending
                if bid not in in_flight_bids
                and all(d in completed for d in deps[bid])
            ])

        def _submit_ready() -> None:
            available = max_parallel - len(in_flight)
            for bid in _ready()[:available]:
                brief = bid_to_brief[bid]
                _ensure_batch_module_dirs(codebase_dir, brief)

                # Isolate workspace per batch for local provider.
                batch_ws: Path | None = None
                if provider == "local" and shared_local_workspace is not None:
                    ws_dir = tempfile.mkdtemp(
                        prefix=f"pika_batch_{bid}_",
                        dir=shared_local_workspace.parent,
                    )
                    batch_ws = Path(ws_dir)
                batch_workspaces[bid] = batch_ws

                _report_implement_phase("Execute", "running", f"{bid} (parallel)")
                future = executor.submit(
                    _execute_batch,
                    config,
                    ctx,
                    impl,
                    schemas["implementer"],
                    root,
                    context_text,
                    paths,
                    headers,
                    brief,
                    completed_stages=base_stages,
                    local_workspace_override=batch_ws,
                    patch_apply_lock=patch_lock,
                    appendix_content=appendix_content,
                )
                in_flight[future] = bid

        _submit_ready()
        while in_flight:
            done, _ = futures_wait(in_flight, return_when=FIRST_COMPLETED)
            for f in done:
                bid = in_flight.pop(f)
                batch_ws = batch_workspaces.pop(bid, None)
                if batch_ws is not None:
                    cleanup_local_agent_temp_workspace(batch_ws)

                if failure is not None:
                    # Already failed; drain remaining without starting new batches.
                    continue

                try:
                    result = f.result()
                except Exception as exc:
                    failure = {
                        "status": ImplementStatus.FAILED,
                        "reason": f"execute_exception_{bid}",
                        "batch_id": bid,
                        "details": str(exc),
                    }
                    continue

                if result["status"] == ImplementStatus.BLOCKED:
                    failure = {
                        "status": ImplementStatus.BLOCKED,
                        "reason": result.get("reason", "batch_blocked"),
                        "batch_id": bid,
                    }
                elif result["status"] != ImplementStatus.COMPLETED:
                    failure = {
                        "status": result["status"],
                        "reason": result.get("reason", "batch_failed"),
                        "batch_id": bid,
                    }
                else:
                    completed.add(bid)
                    pending.discard(bid)
                    spec_outputs.update(result.get("spec_outputs", {}))
                    log_lifecycle_event(
                        "lifecycle_batch_executed",
                        command="implement",
                        run_id=ctx.run_id,
                        extra={
                            "batch_id": bid,
                            "spec_count": len(bid_to_brief[bid].get("spec_rows", [])),
                        },
                    )

                if failure is None:
                    _submit_ready()

    # Clean up any workspaces that were not yet freed (e.g., after a failure drain).
    for ws in batch_workspaces.values():
        if ws is not None:
            cleanup_local_agent_temp_workspace(ws)

    if failure is not None:
        return failure
    return {"spec_outputs": spec_outputs}


def run_implement(config: dict[str, Any], ctx: RuntimeContext) -> dict[str, Any]:
    """Run implement workflow: deterministic prep, unified planning, batching, execution, translation."""
    try:
        return _run_implement_inner(config, ctx)
    except PikaError as exc:
        return {
            "command": "implement",
            "status": ImplementStatus.FAILED,
            "reason": str(exc),
        }


def _run_implement_inner(config: dict[str, Any], ctx: RuntimeContext) -> dict[str, Any]:
    """Core implement logic — may raise PikaError subclasses."""
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
    if _step_enabled(impl, "workset_schema_validation"):
        selected = _select_workset(headers, rows)
    else:
        selected = _select_workset_relaxed(headers, rows)
        _report_implement_phase(
            "Load",
            "warning",
            "workset_schema_validation disabled; invalid rows are skipped",
        )
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
    # Determine resume mode
    resume_run_id = getattr(ctx, "resume_run_id", None)
    resume_mode = "none"  # "none" | "after_resolve" | "after_failure"
    completed_stages_set: set[str] = set()
    if resume_run_id:
        completed_stages_set = {
            str(s).strip()
            for s in existing_run_meta.get("completed_stages", [])
            if str(s).strip()
        }
        if existing_run_meta.get("resolution_status") == "resolved":
            resume_mode = "after_resolve"
        elif (
            existing_run_meta.get("failed_at_stage")
            and _has_completed_agent_stage(list(completed_stages_set))
        ):
            resume_mode = "after_failure"
        else:
            raise ResumeError(
                "No agent work to recover. Start a fresh run instead."
            )

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
    if resume_mode == "none":
        run_meta_payload.pop("blocked_at_stage", None)
        run_meta_payload.pop("resolution_status", None)
        run_meta_payload.pop("failed_at_stage", None)
    elif resume_mode == "after_failure":
        run_meta_payload.pop("failed_at_stage", None)
        # Config hash warning for stale cache
        old_hash = existing_run_meta.get("config_hash", "")
        new_hash = _sha256(json.dumps(config, sort_keys=True, default=str).encode("utf-8"))
        if old_hash and old_hash != new_hash:
            _report_implement_phase(
                "Resume", "warning",
                "Config changed since agent ran. Cached agent output may be stale.",
            )
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
    if _step_enabled(impl, "module_catalog_validation"):
        module_catalog = _build_module_catalog(selected, impl["allowed_module_roles"], codebase_dir)
    else:
        module_catalog = _build_module_catalog_relaxed(
            selected,
            impl["allowed_module_roles"],
            codebase_dir,
        )
        _report_implement_phase(
            "Catalog",
            "warning",
            "module_catalog_validation disabled; invalid roles are normalized",
        )
    _write_json(paths["run"] / "module_catalog.json", module_catalog)
    log_lifecycle_event(
        "lifecycle_module_catalog_built",
        command="implement",
        run_id=ctx.run_id,
        extra={"module_count": len(module_catalog["modules"])},
    )
    module_tags = ", ".join(m["module_tag"] for m in module_catalog["modules"])
    _report_implement_phase("Catalog", "ok", f"{len(module_catalog['modules'])} modules ({module_tags})")

    # --- Load appendices ---
    appendix_entries = load_appendix_files(config, root, command="implement")
    registry_path = Path(
        config.get("id_generation", {}).get("id_registry", "out/state/id_registry.json")
    )
    if appendix_entries:
        appendix_entries = assign_appendix_ids(appendix_entries, registry_path, root)
    appendix_lookup = appendix_entries_to_lookup(appendix_entries)
    appendix_text = format_appendix_for_agent(
        appendix_entries, max_chars=impl.get("max_appendix_chars", 0),
    )
    # Store hash for resume compatibility
    apx_hash = appendix_content_hash(appendix_entries) if appendix_entries else ""
    if apx_hash:
        run_meta_payload["appendix_content_hash"] = apx_hash
        if resume_mode != "none":
            old_apx_hash = existing_run_meta.get("appendix_content_hash", "")
            if old_apx_hash and old_apx_hash != apx_hash:
                _report_implement_phase(
                    "Appendix", "warning",
                    "Appendix content changed since original run. Cached output may be stale.",
                )
        _write_json(run_meta_path, run_meta_payload)
    if appendix_entries:
        _report_implement_phase(
            "Appendix", "ok",
            f"{len(appendix_entries)} entries loaded ({len(appendix_lookup)} with IDs)",
        )

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
        if not _step_enabled(impl, "planner_path_contract_prep"):
            _report_implement_phase(
                "Planner path contract",
                "warning",
                "planner_path_contract_prep disabled",
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
            "appendix_content": appendix_text,
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
        if not _step_enabled(impl, "planner_semantic_validation"):
            _report_implement_phase(
                "Planner semantic validation",
                "warning",
                "planner_semantic_validation disabled",
            )
        try:
            planner_output = invoke_with_semantic_retry(
                prompt_name=impl["unified_planner_prompt_name"],
                template_vars=template_vars,
                schema_path=schemas["unified_planner"],
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
            raise AgentInvocationError(
                f"Unified planner agent failed: {exc}"
            ) from exc
    _write_json(paths["run"] / "unified_plan.json", planner_output)
    log_lifecycle_event(
        "lifecycle_invoke_agent",
        command="implement",
        run_id=ctx.run_id,
        extra={"phase": "unified_planner"},
    )

    if _step_enabled(impl, "planner_manual_resolution_gate"):
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
    else:
        _report_implement_phase(
            "Planner manual gate",
            "warning",
            "planner_manual_resolution_gate disabled",
        )

    module_plans = planner_output.get("module_plans", [])
    spec_dependencies = planner_output.get("spec_dependencies", [])
    shared_contracts = planner_output.get("shared_contracts", [])

    # --- Extract and surface spec consistency issues (Phase 0 warnings) ---
    spec_issues: list[dict[str, Any]] = planner_output.get("spec_issues", [])
    if spec_issues:
        for issue in spec_issues:
            issue_id = issue.get("issue_id", "?")
            kind = issue.get("kind", "?")
            affected = ", ".join(issue.get("affected_spec_ids", []))
            description = issue.get("description", "")
            _report_implement_phase(
                "Spec issue",
                "warning",
                f"[{issue_id}] {kind} — {affected}: {description}",
            )
    _write_json(paths["run"] / "spec_issues.json", {"spec_issues": spec_issues})
    if spec_issues:
        _report_implement_phase(
            "Spec consistency", "warning", f"{len(spec_issues)} issue(s) — see spec_issues.json",
        )

    # --- Phase 8: Gate spec consistency issues ---
    if _step_enabled(impl, "spec_issue_escalation"):
        spec_issue_items = _escalate_spec_issues(spec_issues, selected)
        if spec_issue_items:
            _manual_block(
                None,
                paths["manual"],
                "spec_issue_escalation",
                run_dir=paths["run"],
                command="implement",
                run_id=ctx.run_id,
                completed_stages=["load", "catalog", "unified_planner"],
                source=RESOLUTION_SOURCE_VALIDATION,
                items=spec_issue_items,
            )
            _report_implement_phase(
                "Spec issue escalation",
                "blocked",
                f"{len(spec_issue_items)} spec issue(s) require resolution",
            )
            _cleanup_shared_local_workspace()
            return {
                "command": "implement",
                "status": ImplementStatus.BLOCKED,
                "blocking_items": len(spec_issue_items),
            }
    else:
        _report_implement_phase(
            "Spec issue escalation", "warning", "spec_issue_escalation disabled",
        )

    n_anchors = sum(len(mp.get("planned_anchors", [])) for mp in module_plans)
    _report_implement_phase(
        "Planner", "ok",
        f"{len(module_plans)} modules, {n_anchors} anchors, "
        f"{len(spec_dependencies)} cross-deps, {len(shared_contracts)} contracts"
        + (f", {len(spec_issues)} spec issue(s)" if spec_issues else ""),
    )

    # Write per-module plans for debugging
    for mp in module_plans:
        tag = mp.get("module_tag", "UNKNOWN")
        _write_json(paths["module_plans"] / f"{tag}.json", mp)

    # --- Validate unified plan (retry/block split) ---
    if _step_enabled(impl, "unified_plan_validation"):
        all_spec_ids = {row["spec_id"] for row in selected}
        plan_validation = _validate_unified_plan(
            planner_output, all_spec_ids, module_catalog,
        )
        _write_json(paths["run"] / "plan_validation.json", plan_validation)

        # Blocking reasons (cycles) → produce manual_resolution_items
        if plan_validation.get("blocking_reasons"):
            cycle = plan_validation.get("cycle_path") or []
            cycle_label = " \u2192 ".join(cycle) if cycle else "detected"
            cycle_items = [{
                "item_id": "dependency_cycle",
                "title": f"Dependency cycle: {cycle_label}",
                "question": (
                    f"Spec dependencies form a cycle: {cycle_label}. "
                    "Break the cycle by removing or reversing a dependency."
                ),
                "options": [],
                "blocking_reason": "Cyclic spec dependencies cannot be batched",
            }]
            _manual_block(
                None,
                paths["manual"],
                "plan_validation_cycle",
                run_dir=paths["run"],
                command="implement",
                run_id=ctx.run_id,
                completed_stages=["load", "catalog", "unified_planner"],
                source=RESOLUTION_SOURCE_VALIDATION,
                items=cycle_items,
            )
            _report_implement_phase(
                "Plan validation", "blocked",
                "dependency cycle requires manual resolution",
            )
            _cleanup_shared_local_workspace()
            return {
                "command": "implement",
                "status": ImplementStatus.BLOCKED,
                "blocking_items": len(cycle_items),
            }

        # Retryable reasons (uncovered specs, invalid refs, missing modules)
        # These share the planner retry budget — fail so the caller can re-invoke.
        if plan_validation.get("retryable_reasons"):
            reasons = plan_validation["retryable_reasons"]
            _report_implement_phase("Plan validation", "failed", "; ".join(reasons[:3]))
            _write_json(
                paths["run"] / "summary.json",
                {
                    "status": ImplementStatus.FAILED,
                    "reason": "plan_validation_retryable",
                    "details": reasons,
                    "retryable": True,
                },
            )
            _cleanup_shared_local_workspace()
            raise PlanValidationError(
                f"Plan validation failed (retryable): {'; '.join(reasons[:3])}"
            )

        _report_implement_phase("Plan validation", "ok", "DAG valid, all specs covered")
    else:
        _report_implement_phase("Plan validation", "warning", "unified_plan_validation disabled")
        _write_json(
            paths["run"] / "plan_validation.json",
            {"status": "skipped", "reason": "unified_plan_validation disabled"},
        )

    # --- Contract field consistency check ---
    resolution_items: list[dict[str, Any]] = []
    if resume_mode != "none":
        res_data = load_resolution_file(paths["run"])
        if res_data:
            resolution_items = res_data.get("items") or []
    if _step_enabled(impl, "contract_field_consistency_validation"):
        contract_validation = _validate_contract_field_consistency(
            shared_contracts, selected, headers,
            resolutions=resolution_items if resolution_items else None,
            appendix_lookup=appendix_lookup if appendix_lookup else None,
            match_score_threshold=float(
                _step_value(
                    impl,
                    "contract_field_consistency_validation",
                    "field_match_score_threshold",
                    impl.get("field_match_score_threshold", 0.8),
                )
            ),
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
    else:
        _report_implement_phase(
            "Contract field check",
            "warning",
            "contract_field_consistency_validation disabled",
        )
        _write_json(
            paths["run"] / "contract_field_validation.json",
            {"status": "skipped", "reason": "contract_field_consistency_validation disabled"},
        )

    if _step_enabled(impl, "required_field_coverage_validation"):
        coverage_step = impl.get("steps", {}).get("required_field_coverage_validation", {})
        required_field_coverage_validation = _validate_required_field_coverage(
            shared_contracts,
            selected,
            headers,
            appendix_lookup=appendix_lookup if appendix_lookup else None,
        )
        _write_json(
            paths["run"] / "required_field_coverage_validation.json",
            required_field_coverage_validation,
        )
        if required_field_coverage_validation["status"] != ImplementStatus.PASSED:
            block_items = required_field_coverage_validation.get("manual_resolution_items", [])
            if block_items:
                _manual_block(
                    None,
                    paths["manual"],
                    "required_field_coverage_validation",
                    run_dir=paths["run"],
                    command="implement",
                    run_id=ctx.run_id,
                    completed_stages=[
                        "load",
                        "catalog",
                        "unified_planner",
                        "plan_validation",
                        "contract_field_consistency",
                    ],
                    source=RESOLUTION_SOURCE_VALIDATION,
                    items=block_items,
                    spec_rows=selected,
                    headers=headers,
                    shared_contracts=shared_contracts,
                )
                _report_implement_phase(
                    "Required field coverage check", "blocked",
                    f"{len(block_items)} coverage issue(s) require manual resolution",
                )
                _cleanup_shared_local_workspace()
                return {
                    "command": "implement",
                    "status": ImplementStatus.BLOCKED,
                    "blocking_items": len(block_items),
                }
        _report_implement_phase("Required field coverage check", "ok", "contract fields are covered")
    else:
        _write_json(
            paths["run"] / "required_field_coverage_validation.json",
            {"status": "skipped", "reason": "required_field_coverage_validation disabled"},
        )

    # --- Build batches from spec dependency graph ---
    anchor_plans_by_module = {
        mp["module_tag"]: mp
        for mp in module_plans
        if isinstance(mp, dict) and mp.get("module_tag")
    }
    if _step_enabled(impl, "batch_plan_construction"):
        batch_plan = _build_batches(
            selected,
            spec_dependencies,
            impl["budgets"],
            anchor_plans=anchor_plans_by_module,
            module_plans=module_plans,
        )
    else:
        _report_implement_phase(
            "Batch plan",
            "warning",
            "batch_plan_construction disabled; using single deterministic batch",
        )
        batch_plan = {
            "batches": [
                {
                    "batch_id": "B0",
                    "kind": "module_impl",
                    "spec_ids": [str(row.get("spec_id", "")).strip() for row in selected if str(row.get("spec_id", "")).strip()],
                    "module_tags": sorted(
                        {
                            str(row.get("module_tag", "")).strip()
                            for row in selected
                            if str(row.get("module_tag", "")).strip()
                        }
                    ),
                    "depends_on_batches": [],
                    "rationale": "batch_plan_construction disabled",
                    "budgets_applied": impl["budgets"],
                }
            ]
        }
    _write_json(paths["run"] / "batch_plan.json", batch_plan)
    if _step_enabled(impl, "batch_plan_dependency_validation"):
        batch_plan_validation = _validate_batch_plan_dependencies(
            batch_plan, spec_dependencies,
        )
    else:
        batch_plan_validation = {
            "status": ImplementStatus.PASSED,
            "checks": [],
            "reasons": ["batch_plan_dependency_validation disabled"],
        }
        _report_implement_phase(
            "Batch plan validation",
            "warning",
            "batch_plan_dependency_validation disabled",
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
        raise BatchValidationError("Batch plan dependency validation failed")
    n_batches = len(batch_plan.get("batches", []))
    _report_implement_phase("Batch plan", "ok", f"{n_batches} batches")

    # --- Build briefs ---
    if _step_enabled(impl, "batch_brief_build"):
        briefs = _build_briefs(
            selected,
            anchor_plans_by_module,
            spec_dependencies,
            shared_contracts,
            batch_plan,
            impl,
            appendix_entries=appendix_entries if appendix_entries else None,
        )
    else:
        _report_implement_phase(
            "Briefs",
            "warning",
            "batch_brief_build disabled; using minimal brief projection",
        )
        selected_by_spec = {
            str(row.get("spec_id", "")).strip(): row
            for row in selected
            if isinstance(row, dict) and str(row.get("spec_id", "")).strip()
        }
        briefs = []
        for batch in batch_plan.get("batches", []):
            if not isinstance(batch, dict):
                continue
            spec_ids = [
                str(spec_id).strip()
                for spec_id in batch.get("spec_ids", [])
                if str(spec_id).strip()
            ]
            brief = {
                "batch_id": str(batch.get("batch_id", "")).strip() or "B0",
                "spec_rows": [selected_by_spec[sid] for sid in spec_ids if sid in selected_by_spec],
                "planned_anchors": [],
                "shared_contracts": [],
                "spec_dependency_context": [],
                "constraints": {
                    "forbidden_paths": impl["forbidden_paths"],
                    "budgets_applied": impl["budgets"],
                    "verification_commands": impl["verification_commands"],
                    "traceability_rules": {"require_spec_ids_per_diff": True},
                },
            }
            briefs.append(brief)
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
    if _step_enabled(impl, "batch_brief_scope_validation"):
        brief_validation = _validate_brief_scoping(briefs)
    else:
        brief_validation = {
            "status": ImplementStatus.PASSED,
            "checks": [],
            "reasons": ["batch_brief_scope_validation disabled"],
        }
        _report_implement_phase(
            "Brief validation",
            "warning",
            "batch_brief_scope_validation disabled",
        )
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
        raise BatchValidationError(f"Brief scope validation failed: {'; '.join(reasons)}")
    _report_implement_phase("Brief validation", "ok", "all briefs batch-scoped")
    if _step_enabled(impl, "dependency_context_edge_validation"):
        dependency_context_edge_validation = _validate_dependency_context_edges(
            briefs,
            spec_dependencies,
        )
        _write_json(
            paths["run"] / "dependency_context_edge_validation.json",
            dependency_context_edge_validation,
        )
        if dependency_context_edge_validation["status"] != ImplementStatus.PASSED:
            reasons = dependency_context_edge_validation.get("reasons", [])
            _report_implement_phase("Dependency context edge check", "failed", "; ".join(reasons[:3]))
            _write_json(
                paths["run"] / "summary.json",
                {
                    "status": ImplementStatus.FAILED,
                    "reason": "dependency_context_edge_validation_failed",
                    "details": reasons,
                },
            )
            _cleanup_shared_local_workspace()
            raise BatchValidationError(
                f"Dependency context edge validation failed: {'; '.join(reasons[:3])}"
            )
        _report_implement_phase("Dependency context edge check", "ok", "dependency context matches planner")
    else:
        _write_json(
            paths["run"] / "dependency_context_edge_validation.json",
            {"status": "skipped", "reason": "dependency_context_edge_validation disabled"},
        )

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
    max_parallel_batches = int(impl.get("budgets", {}).get("max_parallel_batches", 1))
    if max_parallel_batches > 1:
        parallel_result = _execute_briefs_concurrently(
            briefs,
            max_parallel_batches,
            config=config,
            ctx=ctx,
            impl=impl,
            schemas=schemas,
            root=root,
            context_text=context_text,
            paths=paths,
            headers=headers,
            base_stages=base_stages,
            resume_mode=resume_mode,
            completed_stages_set=completed_stages_set,
            codebase_dir=codebase_dir,
            shared_local_workspace=shared_local_workspace,
            provider=provider,
            appendix_content=appendix_text,
        )
        if "status" in parallel_result:
            failure_status = parallel_result["status"]
            failure_reason = parallel_result.get("reason", "batch_failed")
            failure_details = str(parallel_result.get("details", "")).strip()
            _update_run_meta_state(
                run_meta_path,
                completed_stages=base_stages,
                failed_at_stage=f"execute_{parallel_result.get('batch_id', 'unknown')}",
            )
            _report_implement_phase("Execute", "failed", failure_reason)
            _write_json(
                paths["run"] / "summary.json",
                (
                    {
                        "status": failure_status,
                        "reason": failure_reason,
                        "details": failure_details,
                    }
                    if failure_details
                    else {"status": failure_status, "reason": failure_reason}
                ),
            )
            _cleanup_shared_local_workspace()
            return {
                "command": "implement",
                "status": failure_status,
                "reason": failure_reason,
                **({"details": failure_details} if failure_details else {}),
            }
        spec_outputs: dict[str, dict[str, Any]] = parallel_result["spec_outputs"]
        _report_implement_phase("Execute", "ok", f"{len(briefs)} batches completed (parallel)")
    else:
        spec_outputs: dict[str, dict[str, Any]] = {}
        for idx, brief in enumerate(briefs, start=1):
            batch_id = brief["batch_id"]
            execute_stage = f"execute_{batch_id}"
            completed_stages = base_stages + [
                f"execute_{b['batch_id']}" for b in briefs[: idx - 1]
            ]
            if resume_mode != "none" and execute_stage in completed_stages_set:
                cached_path = paths["agent_outputs"] / f"implement_{batch_id}.json"
                if cached_path.exists():
                    try:
                        cached_output = json.loads(cached_path.read_text(encoding="utf-8"))
                    except Exception:
                        cached_output = None
                    if cached_output and not cached_output.get("manual_resolution_items"):
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
                    appendix_content=appendix_text,
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
                raise PikaError(
                    f"Batch execution failed for {batch_id}: {exc}"
                ) from exc
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
                    (
                        {
                            "status": result["status"],
                            "reason": reason,
                            "details": str(result.get("details", "")),
                        }
                        if str(result.get("details", "")).strip()
                        else {
                            "status": result["status"],
                            "reason": reason,
                        }
                    ),
                )
                _cleanup_shared_local_workspace()
                return {
                    "command": "implement",
                    "status": result["status"],
                    "reason": reason,
                    **(
                        {"details": str(result.get("details", ""))}
                        if str(result.get("details", "")).strip()
                        else {}
                    ),
                }
            spec_outputs.update(result.get("spec_outputs", {}))
            log_lifecycle_event(
                "lifecycle_batch_executed",
                command="implement",
                run_id=ctx.run_id,
                extra={"batch_id": brief["batch_id"], "spec_count": len(brief.get("spec_rows", []))},
            )
        _report_implement_phase("Execute", "ok", f"{len(briefs)} batches completed")

    eval_stage_name = "evaluate_implementation"
    skip_eval_resumed = (
        resume_mode != "none" and eval_stage_name in completed_stages_set
    )
    if skip_eval_resumed:
        _report_implement_phase("Evaluate", "skipped", "resume: cached")
    else:
        eval_outcome = _maybe_run_code_evaluator(
            config=config,
            ctx=ctx,
            impl=impl,
            schemas=schemas,
            root=root,
            paths=paths,
            headers=headers,
            selected=selected,
            briefs=briefs,
            module_plans=module_plans,
            spec_outputs=spec_outputs,
            completed_stages_so_far=base_stages + [f"execute_{b['batch_id']}" for b in briefs],
            execute_batch_kwargs={
                "config": config,
                "ctx": ctx,
                "impl": impl,
                "schema_path": schemas["implementer"],
                "root": root,
                "context_text": context_text,
                "paths": paths,
                "design_headers": headers,
                "shared_local_workspace": shared_local_workspace,
                "appendix_text": appendix_text,
            },
            run_meta_path=run_meta_path,
        )
        if isinstance(eval_outcome, dict) and eval_outcome.get("status") is not None:
            _cleanup_shared_local_workspace()
            return eval_outcome

    eval_completed_stages = (
        [eval_stage_name]
        if (skip_eval_resumed or evaluator_config(impl)["enabled"])
        else []
    )

    try:
        _update_design_and_test_spec(config, ctx, impl, design_path, spec_outputs)
    except Exception as exc:
        _update_run_meta_state(
            run_meta_path,
            completed_stages=(
                base_stages
                + [f"execute_{b['batch_id']}" for b in briefs]
                + eval_completed_stages
            ),
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
        raise PikaError(f"Design/test spec update failed: {exc}") from exc
    log_lifecycle_event(
        "lifecycle_translate",
        command="implement",
        run_id=ctx.run_id,
        extra={"spec_output_count": len(spec_outputs)},
    )
    _report_implement_phase("Translate", "ok", "design spec + test spec updated")
    _update_run_meta_state(
        run_meta_path,
        completed_stages=(
            base_stages
            + [f"execute_{b['batch_id']}" for b in briefs]
            + eval_completed_stages
            + ["translate"]
        ),
        failed_at_stage=None,
    )
    _write_json(
        paths["run"] / "summary.json",
        {"status": ImplementStatus.COMPLETED, "batches_completed": len(briefs), "batches_failed": 0},
    )
    _cleanup_shared_local_workspace()
    return {"command": "implement", "status": ImplementStatus.COMPLETED, "dry_run": False}


def _build_spec_to_module_tag(module_plans: list[dict[str, Any]]) -> dict[str, str]:
    """Map spec_id -> owning module_tag using planned_anchors[].spec_ids."""
    out: dict[str, str] = {}
    for mp in module_plans or []:
        if not isinstance(mp, dict):
            continue
        tag = str(mp.get("module_tag") or "").strip()
        if not tag:
            continue
        for anchor in mp.get("planned_anchors", []) or []:
            if not isinstance(anchor, dict):
                continue
            for sid in anchor.get("spec_ids", []) or []:
                sid_s = str(sid).strip()
                if sid_s and sid_s not in out:
                    out[sid_s] = tag
    return out


def _build_anchor_plans_by_module(module_plans: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Same shape as the planner-time map; rebuilt at eval time for clarity."""
    return {
        str(mp.get("module_tag") or "").strip(): mp
        for mp in module_plans or []
        if isinstance(mp, dict) and str(mp.get("module_tag") or "").strip()
    }


def _maybe_run_code_evaluator(
    *,
    config: dict[str, Any],
    ctx: RuntimeContext,
    impl: dict[str, Any],
    schemas: dict[str, Path],
    root: Path,
    paths: dict[str, Path],
    headers: list[str],
    selected: list[dict[str, Any]],
    briefs: list[dict[str, Any]],
    module_plans: list[dict[str, Any]],
    spec_outputs: dict[str, dict[str, Any]],
    completed_stages_so_far: list[str],
    execute_batch_kwargs: dict[str, Any],
    run_meta_path: Path,
) -> dict[str, Any] | None:
    """Run code_evaluator stage when enabled. Returns terminal-status dict on block, else None.

    On warn-action failure or pass: returns None and lifecycle continues.
    On block-action failure: persists manual_resolution, updates run_meta, and
    returns ``{"command": "implement", "status": ImplementStatus.BLOCKED, ...}``.
    """
    if ctx.dry_run:
        return None
    eval_cfg = evaluator_config(impl)
    if not eval_cfg["enabled"]:
        return None
    schema_path = schemas.get("code_evaluator")
    if schema_path is None:
        _report_implement_phase("Evaluate", "warning", "code_evaluator schema unavailable; skipping")
        return None

    forbidden_paths = list(impl.get("forbidden_paths") or [])
    anchor_plans_by_module = _build_anchor_plans_by_module(module_plans)
    spec_to_module_tag = _build_spec_to_module_tag(module_plans)
    selected_specs_csv = rows_to_csv(headers, selected)

    max_cycles = max(0, int(eval_cfg["max_eval_cycles"]))
    threshold = eval_cfg["rerun_severity_threshold"]
    fail_action = eval_cfg["fail_action"]

    last_eval: dict[str, Any] = {}
    for cycle in range(max_cycles + 1):
        try:
            harness_results = collect_harness_results(
                enabled_harnesses=eval_cfg["harnesses"],
                project_root=root,
                spec_outputs=spec_outputs,
                forbidden_path_prefixes=forbidden_paths,
                anchor_plans_by_module=anchor_plans_by_module,
                spec_to_module_tag=spec_to_module_tag,
                diff_size_max_lines=int(eval_cfg["diff_size_sanity_max_lines"]),
            )
        except Exception as exc:
            harness_results = [
                {
                    "harness_id": "collect_harness_results",
                    "spec_id": None,
                    "passed": False,
                    "details": f"harness collection error: {exc}",
                    "duration_ms": 0,
                }
            ]
        _write_json(paths["agent_outputs"] / f"harness_results_cycle_{cycle}.json", harness_results)

        try:
            eval_out = run_code_evaluator(
                config=config,
                ctx=ctx,
                schema_path=schema_path,
                project_root=root,
                paths=paths,
                selected_specs_csv=selected_specs_csv,
                spec_outputs=spec_outputs,
                harness_results=harness_results,
                appendix_content=execute_batch_kwargs.get("appendix_text", "") or "",
            )
        except Exception as exc:
            _report_implement_phase("Evaluate", "warning", f"evaluator agent error: {exc}; continuing")
            return None
        last_eval = eval_out
        _write_json(paths["agent_outputs"] / f"code_eval_cycle_{cycle}.json", eval_out)

        if bool(eval_out.get("passed")):
            _report_implement_phase("Evaluate", "ok", f"cycle {cycle}: passed")
            return None

        failed_specs = eval_out.get("failed_specs") or []
        rerun_ids = collect_failed_spec_ids_above_threshold(failed_specs, threshold)
        if not rerun_ids or cycle == max_cycles:
            break

        affected_briefs = [
            b for b in briefs
            if any(sid in rerun_ids for sid in (b.get("spec_ids") or []))
        ]
        if not affected_briefs:
            break

        feedback = build_evaluator_feedback(eval_out, rerun_ids)
        _report_implement_phase(
            "Evaluate",
            "running",
            f"cycle {cycle}: re-running {len(affected_briefs)} batch(es)",
        )
        for brief in affected_briefs:
            try:
                rerun_result = _execute_batch(
                    execute_batch_kwargs["config"],
                    execute_batch_kwargs["ctx"],
                    execute_batch_kwargs["impl"],
                    execute_batch_kwargs["schema_path"],
                    execute_batch_kwargs["root"],
                    execute_batch_kwargs["context_text"],
                    execute_batch_kwargs["paths"],
                    execute_batch_kwargs["design_headers"],
                    brief,
                    completed_stages=completed_stages_so_far,
                    local_workspace_override=execute_batch_kwargs.get("shared_local_workspace"),
                    appendix_content=execute_batch_kwargs.get("appendix_text", "") or "",
                    semantic_retry_context_override=feedback,
                )
            except Exception as exc:
                _report_implement_phase("Evaluate", "warning", f"re-run failed for {brief['batch_id']}: {exc}")
                continue
            if rerun_result.get("status") != ImplementStatus.COMPLETED:
                _report_implement_phase(
                    "Evaluate",
                    "warning",
                    f"re-run not completed for {brief['batch_id']}: {rerun_result.get('reason', 'unknown')}",
                )
                continue
            spec_outputs.update(rerun_result.get("spec_outputs", {}))

    if bool(last_eval.get("passed")):
        return None

    failed_specs = last_eval.get("failed_specs") or []
    if fail_action == "block":
        items = eval_failures_to_resolution_items(failed_specs)
        if items:
            _manual_block(
                None,
                paths["manual"],
                "code_evaluation",
                run_dir=paths["run"],
                command="implement",
                run_id=ctx.run_id,
                completed_stages=completed_stages_so_far,
                items=items,
            )
            _update_run_meta_state(
                run_meta_path,
                completed_stages=completed_stages_so_far,
                failed_at_stage="evaluate_implementation",
            )
            _write_json(
                paths["run"] / "summary.json",
                {
                    "status": ImplementStatus.BLOCKED,
                    "reason": "code_evaluation_failed",
                    "blocking_items": len(items),
                },
            )
            _report_implement_phase("Evaluate", "blocked", f"{len(items)} items require resolution")
            return {
                "command": "implement",
                "status": ImplementStatus.BLOCKED,
                "reason": "code_evaluation_failed",
                "blocking_items": len(items),
            }
    _report_implement_phase(
        "Evaluate",
        "warning",
        f"failed_specs={len(failed_specs)}; fail_action={fail_action}; continuing",
    )
    return None


def _resolve_prompt_schemas(config: dict[str, Any], impl: dict[str, Any]) -> dict[str, Path]:
    """Resolve schema paths for unified planner, implementer, and code evaluator prompts."""
    registry = load_prompt_registry(config)
    schemas: dict[str, Path] = {
        "unified_planner": registry.get_schema_path(impl["unified_planner_prompt_name"]),
        "implementer": registry.get_schema_path(impl["prompt_name"]),
    }
    try:
        schemas["code_evaluator"] = registry.get_schema_path("code_evaluator")
    except Exception:
        pass
    return schemas


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
