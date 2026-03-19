"""Orchestrator for `pika refine` — spec quality review and improvement workflow."""

from __future__ import annotations

import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from core.context import RuntimeContext
from core.errors import PikaError, ResumeError, WorksetValidationError
from core.format_sads import load_sads_csv_or_xlsx, rows_to_csv
from core.lifecycle import (
    invoke_agent_with_schema_retry,
    log_lifecycle_event,
    resolve_agent_runs_dir_for_command,
    resolve_input_path,
    resolve_output_path,
    resolve_output_schema_path,
    resolve_project_context_content,
)
from core.resolution import (
    RESOLUTION_SOURCE_AGENT,
    RESOLUTION_SOURCE_VALIDATION,
    generate_resolution_template,
)

from handlers.refine.config import _get_refine_cfg
from handlers.refine.decomposition import _build_decomposition_items, run_decomposition_check


_REQUIRED_COLUMNS = ["spec_id", "module_tag", "module_role", "requirement", "acceptance_criteria"]


def _report_refine_step(step: str, status: str, detail: str) -> None:
    """Print a refine step to stderr with status and detail."""
    print(f"[PIKA] {step}: {status} — {detail}", file=sys.stderr)


def _write_json(path: Path, payload: Any) -> None:
    """Write JSON to disk with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _find_col(headers: list[str], name: str) -> str | None:
    """Return first matching header by case-insensitive name."""
    mapping = {h.strip().lower(): h for h in headers if h}
    return mapping.get(name.lower())


def _validate_required_columns(headers: list[str], required: list[str]) -> None:
    """Raise WorksetValidationError if any required column is absent (case-insensitive match).

    Args:
        headers: CSV header list.
        required: Logical column names that must be present.
    """
    lower_headers = {h.strip().lower() for h in headers if h}
    missing = [col for col in required if col.lower() not in lower_headers]
    if missing:
        raise WorksetValidationError(f"SADS CSV missing required columns: {', '.join(missing)}")


def _merge_all_items(
    decomp_items: list[dict[str, Any]],
    ambiguity_items: list[dict[str, Any]],
    testability_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Combine manual_resolution_items from all three sources in order."""
    return list(decomp_items) + list(ambiguity_items) + list(testability_items)


def _resolve_refine_schema(config: dict[str, Any], project_root: Path, schema_key: str) -> Path:
    """Resolve schema path from config, falling back to pika root schemas directory."""
    path = resolve_output_schema_path(config, project_root, schema_key, command="refine")
    if path is not None:
        return path
    return project_root / "schemas" / "agent_outputs" / f"{schema_key}.schema.json"


def _resolve_output_csv_path(config: dict[str, Any], project_root: Path) -> Path:
    """Resolve output CSV path from config with default fallback."""
    path = resolve_output_path(config, project_root, "design_spec_path", command="refine")
    if path is not None:
        return path
    return project_root / "out" / "state" / "REFINED-SPEC.csv"


def _write_resolution_block(
    items: list[dict[str, Any]],
    manual_dir: Path,
    stage: str,
    run_dir: Path,
    run_id: str,
    completed_stages: list[str],
    source: str,
) -> None:
    """Write manual resolution block: stage JSON + resolutions.yaml + run_meta update."""
    _write_json(manual_dir / f"{stage}.json", {"stage": stage, "items": items})
    generate_resolution_template(
        run_dir=run_dir,
        stage=stage,
        items=items,
        command="refine",
        run_id=run_id,
        source=source,
    )
    run_meta_path = run_dir / "run_meta.json"
    run_meta: dict[str, Any] = {}
    if run_meta_path.exists():
        try:
            run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    run_meta["blocked_at_stage"] = stage
    run_meta["completed_stages"] = completed_stages
    run_meta["resolution_status"] = "pending"
    _write_json(run_meta_path, run_meta)


def _run_refine_agents(
    config: dict[str, Any],
    ctx: RuntimeContext,
    project_root: Path,
    run_dir: Path,
    design_path: Path,
    headers: list[str],
    rows: list[dict[str, Any]],
    completed_stages: list[str],
) -> dict[str, Any]:
    """Run ambiguity+testability agents in parallel, then gate or complete.

    Shared by the normal refine path and the decomposition-resume path.
    """
    cfg = _get_refine_cfg(config)
    manual_dir = run_dir / "manual_resolution"

    try:
        context_text = resolve_project_context_content(config, project_root, ctx, project_root)
    except Exception as exc:
        return {"command": "refine", "status": "failed", "reason": f"project_context: {exc}"}

    ambiguity_schema = _resolve_refine_schema(config, project_root, "spec_ambiguity_detector_output")
    testability_schema = _resolve_refine_schema(config, project_root, "spec_testability_auditor_output")

    design_csv = rows_to_csv(headers, rows)
    common_vars: dict[str, Any] = {
        "project_context": context_text,
        "design_spec_csv": design_csv,
        "manual_resolution_file": str(manual_dir),
        "run_summary_file": str(run_dir / "summary.json"),
        "control_vocab_section": "",
    }
    ambiguity_vars = {**common_vars, "output_schema_file": str(ambiguity_schema)}
    testability_vars = {**common_vars, "output_schema_file": str(testability_schema)}

    _report_refine_step("Agents", "running", "ambiguity detector + testability auditor")

    def _call_ambiguity() -> dict[str, Any]:
        return invoke_agent_with_schema_retry(
            prompt_name=cfg["ambiguity_detector_prompt_name"],
            template_vars=ambiguity_vars,
            schema_path=ambiguity_schema,
            config=config,
            ctx=ctx,
        )

    def _call_testability() -> dict[str, Any]:
        return invoke_agent_with_schema_retry(
            prompt_name=cfg["testability_auditor_prompt_name"],
            template_vars=testability_vars,
            schema_path=testability_schema,
            config=config,
            ctx=ctx,
        )

    ambiguity_output: dict[str, Any] | None = None
    testability_output: dict[str, Any] | None = None
    agent_errors: list[str] = []

    with ThreadPoolExecutor(max_workers=2) as executor:
        fut_ambiguity = executor.submit(_call_ambiguity)
        fut_testability = executor.submit(_call_testability)
        try:
            ambiguity_output = fut_ambiguity.result()
        except Exception as exc:
            agent_errors.append(f"ambiguity_detector: {exc}")
        try:
            testability_output = fut_testability.result()
        except Exception as exc:
            agent_errors.append(f"testability_auditor: {exc}")

    if agent_errors:
        detail = "; ".join(agent_errors)
        _report_refine_step("Agents", "failed", detail)
        return {"command": "refine", "status": "failed", "reason": detail, "run_id": ctx.run_id}

    completed_stages.append("agents")
    log_lifecycle_event("lifecycle_agent_invoked", command="refine", run_id=ctx.run_id)

    ambiguity_items: list[dict[str, Any]] = (
        ambiguity_output.get("manual_resolution_items", []) if isinstance(ambiguity_output, dict) else []
    )
    testability_items: list[dict[str, Any]] = (
        testability_output.get("manual_resolution_items", []) if isinstance(testability_output, dict) else []
    )
    _write_json(run_dir / "ambiguity_output.json", ambiguity_output or {})
    _write_json(run_dir / "testability_output.json", testability_output or {})

    all_items = _merge_all_items([], ambiguity_items, testability_items)

    if not all_items:
        _report_refine_step("Refine", "ok", "no issues found — copying input to output")
        output_path = _resolve_output_csv_path(config, project_root)
        if not ctx.dry_run:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(design_path, output_path)
        _write_json(run_dir / "summary.json", {
            "status": "completed",
            "specs_improved": 0,
            "output_path": str(output_path),
        })
        # Merge into existing run_meta (preserves command, run_id, input_design_spec_path)
        run_meta_path = run_dir / "run_meta.json"
        existing_meta: dict[str, Any] = {}
        if run_meta_path.exists():
            try:
                existing_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        existing_meta.update({
            "completed_stages": completed_stages,
            "resolution_status": "not_needed",
            "output_design_spec_path": str(output_path),
        })
        existing_meta.pop("blocked_at_stage", None)
        _write_json(run_meta_path, existing_meta)
        log_lifecycle_event("lifecycle_completed", command="refine", run_id=ctx.run_id)
        return {
            "command": "refine",
            "status": "completed",
            "run_id": ctx.run_id,
            "specs_improved": 0,
            "output_path": str(output_path),
            "dry_run": ctx.dry_run,
        }

    _report_refine_step(
        "Refine",
        "blocked",
        f"{len(all_items)} items require review (ambiguity: {len(ambiguity_items)}, testability: {len(testability_items)})",
    )
    _write_resolution_block(
        all_items,
        manual_dir,
        "agent_review",
        run_dir,
        ctx.run_id,
        completed_stages,
        RESOLUTION_SOURCE_AGENT,
    )
    _write_json(run_dir / "summary.json", {
        "status": "blocked",
        "blocking_items": len(all_items),
        "ambiguity_items": len(ambiguity_items),
        "testability_items": len(testability_items),
        "input_design_spec_path": str(design_path),
    })
    log_lifecycle_event("lifecycle_manual_resolution", command="refine", run_id=ctx.run_id)
    return {
        "command": "refine",
        "status": "blocked",
        "run_id": ctx.run_id,
        "blocking_items": len(all_items),
        "blocking_stage": "agent_review",
    }


def _resume_refine(
    config: dict[str, Any],
    ctx: RuntimeContext,
    project_root: Path,
    resume_run_id: str,
) -> dict[str, Any]:
    """Resume a previously blocked or failed refine run.

    Three cases:
    - agent_review blocked: pika resolve already applied all changes via
      _apply_refine_resolutions. Return completed immediately.
    - decomposition blocked: pika resolve applied structural edits and wrote a
      restructured CSV. Load that CSV and run the ambiguity+testability agents.
    - failed with agent cache: reload cached agent outputs and skip to
      merge/gate, or re-run agents if only decomposition completed.
    """
    run_dir = resolve_agent_runs_dir_for_command(config, project_root, "refine", resume_run_id)
    if not run_dir.exists():
        raise ResumeError(f"run_id not found: {resume_run_id}")

    run_meta_path = run_dir / "run_meta.json"
    try:
        run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ResumeError(f"run_meta.json unreadable: {exc}") from exc

    blocked_stage = str(run_meta.get("blocked_at_stage", "")).strip()
    failed_at_stage = str(run_meta.get("failed_at_stage", "")).strip()
    completed_stages = set(run_meta.get("completed_stages", []))

    # --- Case 1: blocked at agent_review (resolved) ---
    if blocked_stage == "agent_review":
        output_path = run_meta.get("output_design_spec_path", "")
        _report_refine_step("Resume", "ok", "agent_review resolutions already applied by resolve")
        return {
            "command": "refine",
            "status": "completed",
            "run_id": resume_run_id,
            "output_path": output_path,
        }

    # --- Case 2: blocked at decomposition (resolved) ---
    if blocked_stage == "decomposition":
        restructured_path_str = run_meta.get("output_design_spec_path", "")
        if not restructured_path_str or not Path(restructured_path_str).exists():
            raise ResumeError(
                "output_design_spec_path not found in run_meta.json. "
                "Ensure 'pika resolve' completed successfully before resuming."
            )

        design_path = Path(restructured_path_str)
        _report_refine_step(
            "Resume",
            "ok",
            f"decomposition resolved — running agents on {design_path.name}",
        )

        headers, rows = load_sads_csv_or_xlsx(design_path)
        _validate_required_columns(headers, _REQUIRED_COLUMNS)

        stages_list = list(run_meta.get("completed_stages", []))
        run_meta["input_design_spec_path"] = restructured_path_str
        run_meta["resolution_status"] = "running"
        run_meta.pop("blocked_at_stage", None)
        _write_json(run_meta_path, run_meta)

        return _run_refine_agents(
            config=config,
            ctx=ctx,
            project_root=project_root,
            run_dir=run_dir,
            design_path=design_path,
            headers=headers,
            rows=rows,
            completed_stages=stages_list,
        )

    # --- Case 3: failed with agent cache ---
    if failed_at_stage:
        if "agents" not in completed_stages and "decomposition" not in completed_stages:
            raise ResumeError("No agent work to recover. Start a fresh run instead.")

        # Resolve input spec path for re-running from cache
        design_path_str = str(run_meta.get("input_design_spec_path", "")).strip()
        if not design_path_str or not Path(design_path_str).exists():
            raise ResumeError(
                f"input_design_spec_path not found or missing: {design_path_str!r}"
            )
        design_path = Path(design_path_str)
        headers, rows = load_sads_csv_or_xlsx(design_path)
        _validate_required_columns(headers, _REQUIRED_COLUMNS)

        # Clear failed marker, keep completed_stages
        run_meta.pop("failed_at_stage", None)
        run_meta["resolution_status"] = "running"

        if "agents" in completed_stages:
            # Agents completed — load cached outputs, skip to merge/gate
            _report_refine_step(
                "Resume", "ok",
                f"agents already completed — loading cached outputs (failed at {failed_at_stage})",
            )
            ambiguity_path = run_dir / "ambiguity_output.json"
            testability_path = run_dir / "testability_output.json"
            if not ambiguity_path.exists() or not testability_path.exists():
                raise ResumeError(
                    "Cached agent output files not found for resume "
                    "(ambiguity_output.json / testability_output.json)."
                )
            ambiguity_output = json.loads(ambiguity_path.read_text(encoding="utf-8"))
            testability_output = json.loads(testability_path.read_text(encoding="utf-8"))

            ambiguity_items: list[dict[str, Any]] = (
                ambiguity_output.get("manual_resolution_items", [])
                if isinstance(ambiguity_output, dict) else []
            )
            testability_items: list[dict[str, Any]] = (
                testability_output.get("manual_resolution_items", [])
                if isinstance(testability_output, dict) else []
            )
            all_items = _merge_all_items([], ambiguity_items, testability_items)
            stages_list = list(completed_stages)
            manual_dir = run_dir / "manual_resolution"

            _write_json(run_meta_path, run_meta)

            if not all_items:
                _report_refine_step("Refine", "ok", "no issues found — copying input to output")
                output_path = _resolve_output_csv_path(config, project_root)
                if not ctx.dry_run:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(design_path, output_path)
                _write_json(run_dir / "summary.json", {
                    "status": "completed",
                    "specs_improved": 0,
                    "output_path": str(output_path),
                })
                existing_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
                existing_meta.update({
                    "completed_stages": stages_list,
                    "resolution_status": "not_needed",
                    "output_design_spec_path": str(output_path),
                })
                existing_meta.pop("blocked_at_stage", None)
                _write_json(run_meta_path, existing_meta)
                log_lifecycle_event("lifecycle_completed", command="refine", run_id=ctx.run_id)
                return {
                    "command": "refine",
                    "status": "completed",
                    "run_id": resume_run_id,
                    "specs_improved": 0,
                    "output_path": str(output_path),
                    "dry_run": ctx.dry_run,
                }

            _report_refine_step(
                "Refine", "blocked",
                f"{len(all_items)} items require review "
                f"(ambiguity: {len(ambiguity_items)}, testability: {len(testability_items)})",
            )
            _write_resolution_block(
                all_items, manual_dir, "agent_review",
                run_dir, resume_run_id, stages_list,
                RESOLUTION_SOURCE_AGENT,
            )
            _write_json(run_dir / "summary.json", {
                "status": "blocked",
                "blocking_items": len(all_items),
                "ambiguity_items": len(ambiguity_items),
                "testability_items": len(testability_items),
                "input_design_spec_path": str(design_path),
            })
            log_lifecycle_event("lifecycle_manual_resolution", command="refine", run_id=ctx.run_id)
            return {
                "command": "refine",
                "status": "blocked",
                "run_id": resume_run_id,
                "blocking_items": len(all_items),
                "blocking_stage": "agent_review",
            }

        # Only decomposition completed — re-run agents from where we left off
        _report_refine_step(
            "Resume", "ok",
            f"decomposition completed — re-running agents (failed at {failed_at_stage})",
        )
        stages_list = list(completed_stages)
        _write_json(run_meta_path, run_meta)

        return _run_refine_agents(
            config=config,
            ctx=ctx,
            project_root=project_root,
            run_dir=run_dir,
            design_path=design_path,
            headers=headers,
            rows=rows,
            completed_stages=stages_list,
        )

    raise ResumeError(
        f"Run is not resumable (blocked_at_stage={blocked_stage!r}, "
        f"failed_at_stage={failed_at_stage!r})."
    )


def run_refine(config: dict[str, Any], ctx: RuntimeContext) -> dict[str, Any]:
    """Execute refine command lifecycle.

    Lifecycle:
    1. Load & validate SADS CSV
    2. Decomposition check (NLP) — optional blocking gate
    3. Ambiguity Detector + Testability Auditor agents (parallel)
    4. Merge all manual_resolution_items
    5. 0 items → copy CSV to output, completed
       N items → write stage file, blocked

    Returns:
        {"command": "refine", "status": "completed|blocked|skipped|failed", ...}
    """
    project_root = Path(ctx.project_root)

    try:
        return _run_refine_inner(config, ctx, project_root)
    except PikaError as exc:
        return {"command": "refine", "status": "failed", "reason": str(exc)}


def _run_refine_inner(
    config: dict[str, Any], ctx: RuntimeContext, project_root: Path,
) -> dict[str, Any]:
    """Core refine logic — may raise PikaError subclasses."""
    # Resume check
    resume_run_id = getattr(ctx, "resume_run_id", None)
    if resume_run_id:
        return _resume_refine(config, ctx, project_root, resume_run_id)

    cfg = _get_refine_cfg(config)

    # 1. enabled check
    if not cfg["enabled"]:
        return {"command": "refine", "status": "skipped", "reason": "disabled"}

    # 2. resolve input path
    design_path = resolve_input_path(
        config,
        project_root,
        "design_spec_path",
        overrides=ctx.input_overrides,
        command="refine",
    )
    if design_path is None or not design_path.exists():
        return {
            "command": "refine",
            "status": "skipped",
            "reason": "design_spec_path not configured or missing",
        }

    # 3. load CSV
    log_lifecycle_event("lifecycle_load_inputs", command="refine", run_id=ctx.run_id)
    try:
        headers, rows = load_sads_csv_or_xlsx(design_path)
    except Exception as exc:
        raise WorksetValidationError(
            f"Failed to load design spec from {design_path}: {exc}"
        ) from exc

    # 4. validate required columns
    _validate_required_columns(headers, _REQUIRED_COLUMNS)

    _report_refine_step("Load", "ok", f"{len(rows)} specs from {design_path.name}")

    # 5. setup run dir
    run_dir = resolve_agent_runs_dir_for_command(config, project_root, "refine", ctx.run_id)
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PikaError(f"Failed to create refine run directory {run_dir}: {exc}") from exc
    manual_dir = run_dir / "manual_resolution"

    # write initial run_meta
    try:
        _write_json(run_dir / "run_meta.json", {
            "command": "refine",
            "run_id": ctx.run_id,
            "completed_stages": [],
            "resolution_status": "running",
            "input_design_spec_path": str(design_path),
        })
    except OSError as exc:
        raise PikaError(f"Failed to write run_meta.json: {exc}") from exc

    completed_stages: list[str] = []

    # 6. decomposition check
    if cfg["decomposition_enabled"]:
        _report_refine_step("Decomposition", "running", "analyzing topic coherence")
        decomp_flags = run_decomposition_check(
            rows,
            similarity_threshold=cfg["similarity_threshold"],
            variance_threshold=cfg["variance_threshold"],
        )
        _write_json(run_dir / "decomposition_flags.json", decomp_flags)
        completed_stages.append("decomposition")

        if cfg["decomposition_blocking"] and not decomp_flags.get("skipped", False):
            decomp_items = _build_decomposition_items(decomp_flags)
            if decomp_items:
                _report_refine_step(
                    "Decomposition",
                    "blocked",
                    f"{len(decomp_items)} structural issues",
                )
                _write_resolution_block(
                    decomp_items,
                    manual_dir,
                    "decomposition",
                    run_dir,
                    ctx.run_id,
                    completed_stages,
                    RESOLUTION_SOURCE_VALIDATION,
                )
                return {
                    "command": "refine",
                    "status": "blocked",
                    "run_id": ctx.run_id,
                    "blocking_items": len(decomp_items),
                    "blocking_stage": "decomposition",
                }

        n_split = len(decomp_flags.get("split_candidates", []))
        n_merge = len(decomp_flags.get("merge_candidates", []))
        skipped_msg = " (skipped: library unavailable)" if decomp_flags.get("skipped") else ""
        _report_refine_step(
            "Decomposition",
            "ok",
            f"{n_split} split, {n_merge} merge candidates{skipped_msg}",
        )
    else:
        _write_json(
            run_dir / "decomposition_flags.json",
            {"skipped": True, "reason": "decomposition disabled in config"},
        )
        _report_refine_step("Decomposition", "skipped", "disabled in config")

    # 7-10. run agents, gate or complete
    return _run_refine_agents(
        config=config,
        ctx=ctx,
        project_root=project_root,
        run_dir=run_dir,
        design_path=design_path,
        headers=headers,
        rows=rows,
        completed_stages=completed_stages,
    )
