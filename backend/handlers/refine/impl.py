"""Orchestrator for `pika refine` — spec quality review and improvement workflow."""

from __future__ import annotations

import json
import shutil
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from core.appendix_loader import format_appendix_for_agent, load_appendix_files
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


# acceptance_criteria is produced by refine (testability enricher), not required on input.
_REQUIRED_COLUMNS = ["spec_id", "module_tag", "module_role", "requirement"]


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
    """Merge ambiguity + testability items by spec_id into compound items.

    When both agents flag the same spec_id, they are grouped into a single
    compound item with multiple concerns and item-level resolution options.
    Decomposition items are prepended unchanged (separate blocking stage).

    Returns:
        Merged item list: decomp items first, then spec-grouped agent items
        sorted by spec_id.
    """
    by_spec: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in ambiguity_items:
        by_spec[item.get("spec_id", "")].append({**item, "_agent_type": "ambiguity"})
    for item in testability_items:
        by_spec[item.get("spec_id", "")].append({**item, "_agent_type": "testability"})

    merged: list[dict[str, Any]] = []
    for spec_id in sorted(by_spec):
        if not spec_id:
            continue
        group = by_spec[spec_id]
        concerns: list[dict[str, Any]] = []
        for original in group:
            concern: dict[str, Any] = {
                "item_id": original["item_id"],
                "agent_type": original.pop("_agent_type"),
                "title": original.get("title", ""),
                "field": original.get("field", ""),
                "suggested_improvement": original.get("suggested_improvement", ""),
            }
            if concern["agent_type"] == "ambiguity":
                concern["vague_phrases"] = original.get("vague_phrases")
            else:
                concern["untestable_reason"] = original.get("untestable_reason")
                concern["suggested_test_type"] = original.get("suggested_test_type")
            concerns.append(concern)

        is_compound = len(concerns) > 1
        if is_compound:
            options = [
                {
                    "option_id": "accept_ambiguity",
                    "label": "Accept ambiguity fix",
                    "effect": "Apply ambiguity suggestion to requirement field",
                },
                {
                    "option_id": "accept_testability",
                    "label": "Accept testability fix",
                    "effect": "Apply testability suggestion to requirement field",
                },
                {
                    "option_id": "accept_both_improvements",
                    "label": "Accept both improvements",
                    "effect": "Invoke merger agent to produce a single merged requirement rewrite (with preview)",
                },
                {
                    "option_id": "let_agent_edit",
                    "label": "Let agent edit",
                    "effect": "Agent rewrites the requirement addressing all concerns",
                },
                {
                    "option_id": "skip",
                    "label": "Skip",
                    "effect": "Leave spec unchanged",
                },
            ]
            merged.append({
                "item_id": f"merged_{spec_id}",
                "spec_id": spec_id,
                "is_compound": True,
                "title": f"Multiple issues: {spec_id}",
                "concerns": concerns,
                "options": options,
            })
        else:
            single = concerns[0]
            merged.append({
                "item_id": single["item_id"],
                "spec_id": spec_id,
                "is_compound": False,
                "title": single["title"],
                "concerns": concerns,
                "options": group[0].get("options", []),
            })

    return list(decomp_items) + merged


def _filter_by_consensus(
    all_instance_items: list[list[dict[str, Any]]],
    min_votes: int,
) -> list[dict[str, Any]]:
    """Filter agent resolution items by cross-instance consensus.

    For each spec_id, count how many distinct instances flagged it. Keep only
    spec_ids where the count >= min_votes. Return one representative item per
    surviving spec_id, taken from the first instance that flagged it.

    Args:
        all_instance_items: List of N item-lists, one per agent instance.
        min_votes: Minimum number of instances that must flag the same spec_id.

    Returns:
        Consensus-filtered items sorted by spec_id.
    """
    spec_id_counts: Counter[str] = Counter()
    for items in all_instance_items:
        seen_in_instance: set[str] = set()
        for item in items:
            sid = item.get("spec_id", "")
            if sid and sid not in seen_in_instance:
                spec_id_counts[sid] += 1
                seen_in_instance.add(sid)

    passing_spec_ids = {sid for sid, count in spec_id_counts.items() if count >= min_votes}

    representatives: dict[str, dict[str, Any]] = {}
    for items in all_instance_items:
        for item in items:
            sid = item.get("spec_id", "")
            if sid in passing_spec_ids and sid not in representatives:
                representatives[sid] = item

    return [representatives[sid] for sid in sorted(representatives)]


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


def _resolve_test_plans_dir(project_root: Path) -> Path:
    """Resolve workspace-wide test_plans directory.

    Per-spec test_plan side-files (one JSON per spec_id) live here. Path is
    fixed at out/state/test_plans/ for v1; downstream consumers (implement)
    look here without config indirection.
    """
    return project_root / "out" / "state" / "test_plans"


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
    _write_json(manual_dir / f"{stage}.json", {
        "stage": stage,
        "format_version": 2,
        "items": items,
    })
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
    *,
    appendix_text: str = "",
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
    # Full schema for instance 0; triage schema for replicas (no AC writing in replicas)
    testability_full_schema = _resolve_refine_schema(config, project_root, "spec_testability_enricher_output")
    testability_triage_schema = _resolve_refine_schema(config, project_root, "spec_testability_triage_output")

    # Build minimal CSV for testability enricher (strip unused columns to save tokens)
    _minimal_cols = ["spec_id", "module_tag", "subunit", "requirement"]
    _header_lower = {h.strip().lower(): h for h in headers if h}
    minimal_headers = [_header_lower[c] for c in _minimal_cols if c in _header_lower]
    minimal_design_csv = rows_to_csv(minimal_headers, rows)

    common_base: dict[str, Any] = {
        "project_context": context_text,
        "manual_resolution_file": str(manual_dir),
        "run_summary_file": str(run_dir / "summary.json"),
        "control_vocab_section": "",
        "appendix_content": appendix_text,
    }
    # Ambiguity detector only reads spec_id + requirement (cross-spec ref resolution);
    # minimal CSV saves ~70% tokens with no information loss.
    ambiguity_vars = {
        **common_base,
        "design_spec_csv": minimal_design_csv,
        "output_schema_file": str(ambiguity_schema),
    }
    # Instance 0: full mode — writes enrichments[] + MR items
    testability_full_vars = {
        **common_base,
        "design_spec_csv": minimal_design_csv,
        "enrich_mode": "full",
        "output_schema_file": str(testability_full_schema),
    }
    # Replicas 1..N-1: triage mode — writes MR items only (no AC, saves output tokens)
    testability_triage_vars = {
        **common_base,
        "design_spec_csv": minimal_design_csv,
        "enrich_mode": "triage",
        "output_schema_file": str(testability_triage_schema),
    }

    agent_replicas = cfg["agent_replicas"]
    consensus_min_votes = cfg["consensus_min_votes"]

    _report_refine_step(
        "Agents", "running",
        f"ambiguity detector x{agent_replicas} + testability enricher x{agent_replicas} "
        f"(1 full + {agent_replicas - 1} triage)",
    )

    def _make_caller(prompt_name: str, template_vars: dict[str, Any],
                     schema_path: Path, label: str, index: int):
        def _call() -> tuple[str, int, dict[str, Any]]:
            result = invoke_agent_with_schema_retry(
                prompt_name=prompt_name,
                template_vars=template_vars,
                schema_path=schema_path,
                config=config,
                ctx=ctx,
            )
            return (label, index, result)
        return _call

    ambiguity_outputs: list[dict[str, Any] | None] = [None] * agent_replicas
    testability_outputs: list[dict[str, Any] | None] = [None] * agent_replicas
    agent_errors: list[str] = []

    with ThreadPoolExecutor(max_workers=agent_replicas * 2) as executor:
        futures = {}
        for i in range(agent_replicas):
            fut_a = executor.submit(_make_caller(
                cfg["ambiguity_detector_prompt_name"], ambiguity_vars,
                ambiguity_schema, "ambiguity", i,
            ))
            futures[fut_a] = ("ambiguity", i)
            # Instance 0 uses full schema; replicas use triage schema
            if i == 0:
                t_vars = testability_full_vars
                t_schema = testability_full_schema
            else:
                t_vars = testability_triage_vars
                t_schema = testability_triage_schema
            fut_t = executor.submit(_make_caller(
                cfg["testability_enricher_prompt_name"], t_vars,
                t_schema, "testability", i,
            ))
            futures[fut_t] = ("testability", i)

        for future in futures:
            agent_type, idx = futures[future]
            try:
                _, _, result = future.result()
                if agent_type == "ambiguity":
                    ambiguity_outputs[idx] = result
                else:
                    testability_outputs[idx] = result
            except Exception as exc:
                agent_errors.append(f"{agent_type}[{idx}]: {exc}")

    if agent_errors:
        detail = "; ".join(agent_errors)
        _report_refine_step("Agents", "failed", detail)
        return {"command": "refine", "status": "failed", "reason": detail, "run_id": ctx.run_id}

    completed_stages.append("agents")
    log_lifecycle_event("lifecycle_agent_invoked", command="refine", run_id=ctx.run_id)

    # Write per-instance outputs
    for i in range(agent_replicas):
        _write_json(run_dir / f"ambiguity_output_{i}.json", ambiguity_outputs[i] or {})
        _write_json(run_dir / f"testability_output_{i}.json", testability_outputs[i] or {})

    # Extract items from all instances and apply consensus filtering
    all_ambiguity_instance_items: list[list[dict[str, Any]]] = [
        (out.get("manual_resolution_items", []) if isinstance(out, dict) else [])
        for out in ambiguity_outputs
    ]
    all_testability_instance_items: list[list[dict[str, Any]]] = [
        (out.get("manual_resolution_items", []) if isinstance(out, dict) else [])
        for out in testability_outputs
    ]

    ambiguity_items = _filter_by_consensus(all_ambiguity_instance_items, consensus_min_votes)
    testability_items = _filter_by_consensus(all_testability_instance_items, consensus_min_votes)

    # Write consensus-filtered outputs
    _write_json(run_dir / "ambiguity_output.json", {"manual_resolution_items": ambiguity_items})
    _write_json(run_dir / "testability_output.json", {"manual_resolution_items": testability_items})
    _write_json(run_dir / "consensus_meta.json", {
        "agent_replicas": agent_replicas,
        "consensus_min_votes": consensus_min_votes,
        "ambiguity_pre_consensus": sum(len(items) for items in all_ambiguity_instance_items),
        "ambiguity_post_consensus": len(ambiguity_items),
        "testability_pre_consensus": sum(len(items) for items in all_testability_instance_items),
        "testability_post_consensus": len(testability_items),
    })

    # Collect enrichments from instance 0 (full mode only).
    # Guard: skip any spec_id that also appears in the consensus MR items (MR takes priority).
    flagged_spec_ids: set[str] = {
        str(item.get("spec_id", "")).strip()
        for item in testability_items
        if item.get("spec_id")
    }
    instance0_out = testability_outputs[0] if testability_outputs else None
    enrichments: list[dict[str, Any]] = []
    if isinstance(instance0_out, dict):
        for entry in (instance0_out.get("enrichments") or []):
            if not isinstance(entry, dict):
                continue
            sid = str(entry.get("spec_id", "")).strip()
            if sid and sid not in flagged_spec_ids:
                enrichments.append(entry)

    # Apply enrichments (AC + evidence_type) to the working rows.
    # Ensure both columns exist in headers before writing.
    if enrichments and not ctx.dry_run:
        _header_map = {h.strip().lower(): h for h in headers if h}
        ac_col = _header_map.get("acceptance_criteria", "acceptance_criteria")
        et_col = _header_map.get("evidence_type", "evidence_type")
        sid_col = _header_map.get("spec_id", "spec_id")
        if ac_col not in headers:
            headers = list(headers) + [ac_col]
        if et_col not in headers:
            headers = list(headers) + [et_col]
        for entry in enrichments:
            sid = str(entry.get("spec_id", "")).strip()
            ac_val = str(entry.get("acceptance_criteria", "")).strip()
            et_val = str(entry.get("evidence_type", "")).strip()
            for row in rows:
                if str(row.get(sid_col, "")).strip() == sid:
                    if ac_val:
                        row[ac_col] = ac_val
                    if et_val:
                        row[et_col] = et_val
                    break

    _write_json(run_dir / "enrichments.json", {"enrichments": enrichments})

    # Persist per-spec test_plan side-files (P2).
    # Structured nested data lives outside the CSV; downstream consumers
    # (implement command, reviewer) load these by spec_id from a fixed path.
    if enrichments and not ctx.dry_run:
        test_plans_dir = _resolve_test_plans_dir(project_root)
        test_plans_dir.mkdir(parents=True, exist_ok=True)
        for entry in enrichments:
            sid = str(entry.get("spec_id", "")).strip()
            if not sid:
                continue
            test_plan = entry.get("test_plan")
            criteria = entry.get("criteria")
            if not isinstance(test_plan, dict) and not isinstance(criteria, list):
                continue
            payload: dict[str, Any] = {"spec_id": sid}
            if isinstance(criteria, list):
                payload["criteria"] = criteria
            if isinstance(test_plan, dict):
                payload["test_plan"] = test_plan
            _write_json(test_plans_dir / f"{sid}.json", payload)

    all_items = _merge_all_items([], ambiguity_items, testability_items)

    if not all_items:
        _report_refine_step("Refine", "ok", "no issues found — writing enriched output")
        output_path = _resolve_output_csv_path(config, project_root)
        if not ctx.dry_run:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rows_to_csv(headers, rows), encoding="utf-8")
        _write_json(run_dir / "summary.json", {
            "status": "completed",
            "specs_enriched": len(enrichments),
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
            "specs_enriched": len(enrichments),
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
        "specs_enriched": len(enrichments),
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

        appendix_entries = load_appendix_files(config, project_root, command="refine")
        cfg = _get_refine_cfg(config)
        appendix_text = format_appendix_for_agent(
            appendix_entries, max_chars=cfg["max_appendix_chars"],
        )
        return _run_refine_agents(
            config=config,
            ctx=ctx,
            project_root=project_root,
            run_dir=run_dir,
            design_path=design_path,
            headers=headers,
            rows=rows,
            completed_stages=stages_list,
            appendix_text=appendix_text,
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

        appendix_entries = load_appendix_files(config, project_root, command="refine")
        resume_cfg = _get_refine_cfg(config)
        appendix_text = format_appendix_for_agent(
            appendix_entries, max_chars=resume_cfg["max_appendix_chars"],
        )
        return _run_refine_agents(
            config=config,
            ctx=ctx,
            project_root=project_root,
            run_dir=run_dir,
            design_path=design_path,
            headers=headers,
            rows=rows,
            completed_stages=stages_list,
            appendix_text=appendix_text,
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

    # Early exit: --load-validate-only
    if getattr(ctx, "phase_only", None) == "load_validate_only":
        return {
            "command": "refine",
            "status": "load_validate_only",
            "spec_count": len(rows),
            "design_spec_path": str(design_path),
        }

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
    _phase_only = getattr(ctx, "phase_only", None)
    if _phase_only == "agents_only":
        _write_json(
            run_dir / "decomposition_flags.json",
            {"skipped": True, "reason": "skipped by --agents-only flag"},
        )
        _report_refine_step("Decomposition", "skipped", "skipped by --agents-only flag")

    elif cfg["decomposition_enabled"] or _phase_only == "decomposition_only":
        _report_refine_step("Decomposition", "running", "analyzing topic coherence")
        decomp_flags = run_decomposition_check(
            rows,
            similarity_threshold=cfg["similarity_threshold"],
            variance_threshold=cfg["variance_threshold"],
        )
        _write_json(run_dir / "decomposition_flags.json", decomp_flags)
        completed_stages.append("decomposition")

        # --decomposition-only: return immediately; skip blocking gate
        if _phase_only == "decomposition_only":
            n_split = len(decomp_flags.get("split_candidates", []))
            n_merge = len(decomp_flags.get("merge_candidates", []))
            _report_refine_step(
                "Decomposition",
                "ok",
                f"{n_split} split, {n_merge} merge candidates (decomposition-only mode)",
            )
            return {
                "command": "refine",
                "status": "decomposition_only",
                "run_id": ctx.run_id,
                "split_candidates": n_split,
                "merge_candidates": n_merge,
                "skipped": decomp_flags.get("skipped", False),
            }

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

    # 7. load appendices
    appendix_entries = load_appendix_files(config, project_root, command="refine")
    appendix_text = format_appendix_for_agent(
        appendix_entries, max_chars=cfg["max_appendix_chars"],
    )

    # 8-11. run agents, gate or complete
    return _run_refine_agents(
        config=config,
        ctx=ctx,
        project_root=project_root,
        run_dir=run_dir,
        design_path=design_path,
        headers=headers,
        rows=rows,
        completed_stages=completed_stages,
        appendix_text=appendix_text,
    )
