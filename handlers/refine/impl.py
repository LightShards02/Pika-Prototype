"""Orchestrator for `pika refine` — spec quality review and improvement workflow."""

from __future__ import annotations

import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from core.context import RuntimeContext
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
    """Raise ValueError if any required column is absent (case-insensitive match).

    Args:
        headers: CSV header list.
        required: Logical column names that must be present.
    """
    lower_headers = {h.strip().lower() for h in headers if h}
    missing = [col for col in required if col.lower() not in lower_headers]
    if missing:
        raise ValueError(f"SADS CSV missing required columns: {', '.join(missing)}")


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


def run_refine(config: dict[str, Any], ctx: RuntimeContext) -> dict[str, Any]:
    """Execute refine command lifecycle.

    Lifecycle:
    1. Load & validate SADS CSV
    2. Decomposition check (NLP) — optional blocking gate
    3. Ambiguity Detector + Testability Auditor agents (parallel)
    4. Merge all manual_resolution_items
    5. 0 items → copy CSV to output, completed
       N items → write stage file, needs_resolution

    Returns:
        {"command": "refine", "status": "completed|needs_resolution|skipped|failed", ...}
    """
    project_root = Path(ctx.project_root)
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
    headers, rows = load_sads_csv_or_xlsx(design_path)

    # 4. validate required columns
    try:
        _validate_required_columns(headers, _REQUIRED_COLUMNS)
    except ValueError as exc:
        return {"command": "refine", "status": "failed", "reason": str(exc)}

    _report_refine_step("Load", "ok", f"{len(rows)} specs from {design_path.name}")

    # 5. setup run dir
    run_dir = resolve_agent_runs_dir_for_command(config, project_root, "refine", ctx.run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    manual_dir = run_dir / "manual_resolution"

    # write initial run_meta
    _write_json(run_dir / "run_meta.json", {
        "command": "refine",
        "run_id": ctx.run_id,
        "completed_stages": [],
        "resolution_status": "running",
        "input_design_spec_path": str(design_path),
    })

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
                    "status": "needs_resolution",
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

    # 7. resolve schemas and context
    try:
        context_text = resolve_project_context_content(
            config, project_root, ctx, project_root
        )
    except Exception as exc:
        return {"command": "refine", "status": "failed", "reason": f"project_context: {exc}"}

    ambiguity_schema = _resolve_refine_schema(
        config, project_root, "spec_ambiguity_detector_output"
    )
    testability_schema = _resolve_refine_schema(
        config, project_root, "spec_testability_auditor_output"
    )

    design_csv = rows_to_csv(headers, rows)
    manual_resolution_file = str(manual_dir)
    run_summary_file = str(run_dir / "summary.json")

    common_vars: dict[str, Any] = {
        "project_context": context_text,
        "design_spec_csv": design_csv,
        "manual_resolution_file": manual_resolution_file,
        "run_summary_file": run_summary_file,
        "control_vocab_section": "",
    }
    ambiguity_vars = {**common_vars, "output_schema_file": str(ambiguity_schema)}
    testability_vars = {**common_vars, "output_schema_file": str(testability_schema)}

    # 8. run agents in parallel
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

    # 9. collect and write agent outputs
    ambiguity_items: list[dict[str, Any]] = (
        ambiguity_output.get("manual_resolution_items", [])
        if isinstance(ambiguity_output, dict)
        else []
    )
    testability_items: list[dict[str, Any]] = (
        testability_output.get("manual_resolution_items", [])
        if isinstance(testability_output, dict)
        else []
    )
    _write_json(run_dir / "ambiguity_output.json", ambiguity_output or {})
    _write_json(run_dir / "testability_output.json", testability_output or {})

    all_items = _merge_all_items([], ambiguity_items, testability_items)

    # 10. gate or complete
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
        _write_json(run_dir / "run_meta.json", {
            "command": "refine",
            "run_id": ctx.run_id,
            "completed_stages": completed_stages,
            "resolution_status": "not_needed",
            "input_design_spec_path": str(design_path),
            "output_design_spec_path": str(output_path),
        })
        log_lifecycle_event("lifecycle_completed", command="refine", run_id=ctx.run_id)
        return {
            "command": "refine",
            "status": "completed",
            "run_id": ctx.run_id,
            "specs_improved": 0,
            "output_path": str(output_path),
            "dry_run": ctx.dry_run,
        }

    # N items → block
    _report_refine_step(
        "Refine",
        "needs_resolution",
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
        "status": "needs_resolution",
        "blocking_items": len(all_items),
        "ambiguity_items": len(ambiguity_items),
        "testability_items": len(testability_items),
        "input_design_spec_path": str(design_path),
    })
    log_lifecycle_event("lifecycle_manual_resolution", command="refine", run_id=ctx.run_id)
    return {
        "command": "refine",
        "status": "needs_resolution",
        "run_id": ctx.run_id,
        "blocking_items": len(all_items),
        "blocking_stage": "agent_review",
    }
