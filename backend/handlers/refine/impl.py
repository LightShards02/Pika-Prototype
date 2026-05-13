"""Orchestrator for `pika refine` — spec quality review and improvement workflow."""

from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
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


_SEVERITY_ORDER = ("safety_or_clinical", "data_integrity", "functional_defect", "cosmetic")


def _format_severity_breakdown(items: list[dict[str, Any]]) -> str:
    """Return a comma-separated severity breakdown like '1 safety_or_clinical, 3 functional_defect'.

    Zero-count classes are skipped. Items missing consequence_class are tallied as 'unknown'.
    """
    counts = Counter(
        (item.get("consequence_class") or "unknown") for item in items
    )
    parts: list[str] = []
    for cls in _SEVERITY_ORDER:
        if counts.get(cls, 0) > 0:
            parts.append(f"{counts[cls]} {cls}")
    if counts.get("unknown", 0) > 0:
        parts.append(f"{counts['unknown']} unknown")
    return ", ".join(parts) if parts else "unspecified"


# Canonical resolution options. Injected by the v3->v2 translator so the agent
# no longer has to emit this constant on every item; resolve.py and resolution.py
# still see the same options[] shape they have always consumed.
_CANONICAL_RESOLUTION_OPTIONS: list[dict[str, str]] = [
    {
        "option_id": "accept_suggestion",
        "label": "Accept suggested rewrite",
        "effect": "Replace the requirement with the suggested improvement text.",
    },
    {
        "option_id": "let_agent_edit",
        "label": "Let agent edit",
        "effect": "Have the agent produce a custom rewrite before applying changes.",
    },
    {
        "option_id": "skip",
        "label": "Skip",
        "effect": "Leave this requirement unchanged.",
    },
]


def _evidence_by_kind(item: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index a v3 quality_item's concern_evidence[] entries by their kind.

    Returns an empty dict when concern_evidence is absent or malformed. When the
    schema's uniqueness constraint is violated (duplicate kinds in one item), the
    last entry wins — the translator stays defensive rather than raising.
    """
    result: dict[str, dict[str, Any]] = {}
    entries = item.get("concern_evidence")
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                kind = entry.get("kind")
                if isinstance(kind, str) and kind:
                    result[kind] = entry
    return result


def _synthesize_untestable_reason(item: dict[str, Any], concern_kinds: list[str]) -> str:
    """Synthesize a v1-shaped untestable_reason for desktop-app rendering.

    Used only by the v3->v2 legacy translation. Prefers the concern_evidence
    entry for kind="untestable_outcome" when present; otherwise builds a short
    string from the dominant concern_kind plus worst_case so the gate panel has
    something to display.
    """
    evidence_map = _evidence_by_kind(item)
    untestable_entry = evidence_map.get("untestable_outcome")
    if isinstance(untestable_entry, dict):
        evidence_text = untestable_entry.get("evidence")
        if isinstance(evidence_text, str) and evidence_text.strip():
            return evidence_text.strip()
    label_map = {
        "untestable_outcome": "Requirement is clear but not testable as written",
        "unresolvable_reference": "Reference cannot be resolved from appendix or sibling specs",
        "implementation_leak": "Constrains implementation; not externally observable",
        "legitimate_constraint": "Implementation constraint with external mandate; verify out-of-band",
        "vague_language": "Requirement uses vague language",
    }
    primary = next((k for k in concern_kinds if k in label_map), "untestable_outcome")
    base = label_map.get(primary, "Quality concern flagged")
    worst = item.get("worst_case")
    if isinstance(worst, str) and worst.strip():
        return f"{base}. Worst case: {worst.strip()}"
    return base


def _translate_v3_item_to_v2_legacy(item: dict[str, Any]) -> dict[str, Any]:
    """Translate a v3 quality_item into a v1-shaped flat item that the desktop-app
    gate panel renders unchanged (under format_version=2 detection).

    The desktop app falls through to its v1 path when neither is_compound=true
    nor a non-empty concerns[] is present. v1 detection uses the presence of
    vague_phrases vs untestable_reason to decide ambiguity vs testability rendering.

    Strategy: pick a primary concern_kind. If 'vague_language' is among them,
    render as v1 ambiguity (vague_phrases populated, untestable_reason omitted).
    Otherwise render as v1 testability (untestable_reason populated, vague_phrases omitted).

    Schema-stripped fields are injected here:
      * `field` is always "requirement" — the schema dropped the const property.
      * `options` is always the canonical 3-tuple — the schema dropped the array.
      * `vague_phrases` / `untestable_reason` / `suggested_test_type` /
        `verification_method` are reconstructed from `concern_evidence[]` by kind.

    The full v3 item is preserved separately in auditor_output.json; this translation
    is lossy on purpose to keep the gate UI stable until the desktop app gains v3 support.
    """
    concern_kinds = list(item.get("concern_kinds") or [])
    evidence_map = _evidence_by_kind(item)
    out: dict[str, Any] = {
        "item_id": item.get("item_id", ""),
        "title": item.get("title", ""),
        "spec_id": item.get("spec_id", ""),
        "field": "requirement",
        "suggested_improvement": item.get("suggested_improvement", ""),
        "options": [dict(opt) for opt in _CANONICAL_RESOLUTION_OPTIONS],
    }
    if "vague_language" in concern_kinds:
        vague_entry = evidence_map.get("vague_language")
        evidence_text = (
            vague_entry.get("evidence") if isinstance(vague_entry, dict) else None
        )
        if isinstance(evidence_text, str) and evidence_text.strip():
            out["vague_phrases"] = [evidence_text.strip()]
        else:
            out["vague_phrases"] = [item.get("title") or "vague language"]
    else:
        out["untestable_reason"] = _synthesize_untestable_reason(item, concern_kinds)
        untestable_entry = evidence_map.get("untestable_outcome")
        if isinstance(untestable_entry, dict):
            test_type = untestable_entry.get("test_type_if_fixed")
            if isinstance(test_type, str) and test_type.strip():
                out["suggested_test_type"] = test_type.strip()

    # Pass v3-only metadata through as extra fields. The desktop-app's transform
    # reads named fields and ignores unknowns; the CLI resolution-template generator
    # can surface these in resolutions.yaml so operators see severity/grounding info.
    if isinstance(item.get("concern_kinds"), list):
        out["concern_kinds"] = list(item["concern_kinds"])
    if isinstance(item.get("consequence_class"), str):
        out["consequence_class"] = item["consequence_class"]
    if isinstance(item.get("worst_case"), str):
        out["worst_case"] = item["worst_case"]
    legitimate_entry = evidence_map.get("legitimate_constraint")
    if isinstance(legitimate_entry, dict):
        vm = legitimate_entry.get("verification_method")
        if isinstance(vm, str) and vm.strip():
            out["verification_method"] = vm.strip()
    return out


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
    *,
    appendix_recommendations: list[dict[str, Any]] | None = None,
) -> None:
    """Write manual resolution block: stage JSON + resolutions.yaml + run_meta update.

    appendix_recommendations: optional v3 dictionary-gap entries from the unified
    auditor. When present, embedded as a top-level field in the stage JSON for the
    desktop-app to surface once it gains v3 support. Older clients read items[] only
    and ignore unknown top-level fields.
    """
    payload: dict[str, Any] = {
        "stage": stage,
        "format_version": 2,
        "items": items,
    }
    if appendix_recommendations:
        payload["appendix_recommendations"] = appendix_recommendations
    _write_json(manual_dir / f"{stage}.json", payload)
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
    """Run the unified spec_quality_auditor in N parallel replicas, then gate or complete.

    Instance 0 runs in full mode (produces enrichments[] + manual_resolution_items[]
    + appendix_recommendations[]). Replicas 1..N-1 run in triage mode (manual_resolution_items[]
    only) for consensus filtering. Shared by the normal refine path and the
    decomposition-resume path.
    """
    cfg = _get_refine_cfg(config)
    manual_dir = run_dir / "manual_resolution"

    try:
        context_text = resolve_project_context_content(config, project_root, ctx, project_root)
    except Exception as exc:
        return {"command": "refine", "status": "failed", "reason": f"project_context: {exc}"}

    auditor_full_schema = _resolve_refine_schema(
        config, project_root, "spec_quality_auditor_output",
    )
    auditor_triage_schema = _resolve_refine_schema(
        config, project_root, "spec_quality_auditor_triage_output",
    )

    # Build minimal CSV (strip unused columns to save tokens; auditor only needs
    # spec_id + module_tag + subunit + requirement to make every Stage 1 decision).
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
        "design_spec_csv": minimal_design_csv,
    }
    auditor_full_vars = {
        **common_base,
        "enrich_mode": "full",
        "output_schema_file": str(auditor_full_schema),
    }
    auditor_triage_vars = {
        **common_base,
        "enrich_mode": "triage",
        "output_schema_file": str(auditor_triage_schema),
    }

    agent_replicas = cfg["agent_replicas"]
    consensus_min_votes = cfg["consensus_min_votes"]
    auditor_prompt = cfg["quality_auditor_prompt_name"]

    _report_refine_step(
        "Agents", "running",
        f"quality auditor x{agent_replicas} (1 full + {agent_replicas - 1} triage)",
    )

    def _make_caller(template_vars: dict[str, Any], schema_path: Path, idx: int, mode: str):
        def _call() -> dict[str, Any]:
            _report_refine_step(f"Agents.replica.{idx}", "running", f"mode={mode}")
            return invoke_agent_with_schema_retry(
                prompt_name=auditor_prompt,
                template_vars=template_vars,
                schema_path=schema_path,
                config=config,
                ctx=ctx,
            )
        return _call

    auditor_outputs: list[dict[str, Any] | None] = [None] * agent_replicas
    agent_errors: list[str] = []

    with ThreadPoolExecutor(max_workers=agent_replicas) as executor:
        futures = {}
        for i in range(agent_replicas):
            if i == 0:
                tvars, sch, mode = auditor_full_vars, auditor_full_schema, "full"
            else:
                tvars, sch, mode = auditor_triage_vars, auditor_triage_schema, "triage"
            futures[executor.submit(_make_caller(tvars, sch, i, mode))] = i

        for future, idx in futures.items():
            try:
                result = future.result()
                auditor_outputs[idx] = result
                n_items = len((result or {}).get("manual_resolution_items", []) or [])
                _report_refine_step(f"Agents.replica.{idx}", "ok", f"{n_items} items")
            except Exception as exc:
                agent_errors.append(f"auditor[{idx}]: {exc}")
                _report_refine_step(f"Agents.replica.{idx}", "failed", str(exc))

    if agent_errors:
        detail = "; ".join(agent_errors)
        _report_refine_step("Agents", "failed", detail)
        return {"command": "refine", "status": "failed", "reason": detail, "run_id": ctx.run_id}

    completed_stages.append("agents")
    log_lifecycle_event("lifecycle_agent_invoked", command="refine", run_id=ctx.run_id)

    # Per-instance outputs (preserved for debugging + resume).
    for i in range(agent_replicas):
        _write_json(run_dir / f"auditor_output_{i}.json", auditor_outputs[i] or {})

    # Consensus filtering across replicas (single rule family now).
    all_instance_items: list[list[dict[str, Any]]] = [
        (out.get("manual_resolution_items", []) if isinstance(out, dict) else [])
        for out in auditor_outputs
    ]
    consensus_items = _filter_by_consensus(all_instance_items, consensus_min_votes)

    # Appendix recommendations from instance 0 only (full mode emits, replicas don't).
    instance0_out = auditor_outputs[0] if auditor_outputs else None
    appendix_recommendations: list[dict[str, Any]] = []
    if isinstance(instance0_out, dict):
        for entry in (instance0_out.get("appendix_recommendations") or []):
            if isinstance(entry, dict):
                appendix_recommendations.append(entry)

    # Persist consolidated v3 output.
    _write_json(run_dir / "auditor_output.json", {
        "manual_resolution_items": consensus_items,
        "appendix_recommendations": appendix_recommendations,
    })
    _write_json(run_dir / "consensus_meta.json", {
        "agent_replicas": agent_replicas,
        "consensus_min_votes": consensus_min_votes,
        "items_pre_consensus": sum(len(items) for items in all_instance_items),
        "items_post_consensus": len(consensus_items),
        "appendix_recommendations": len(appendix_recommendations),
    })

    # Collect enrichments from instance 0 (full mode only).
    # Guard: skip any spec_id that also appears in the consensus MR items.
    flagged_spec_ids: set[str] = {
        str(item.get("spec_id", "")).strip()
        for item in consensus_items
        if item.get("spec_id")
    }
    enrichments: list[dict[str, Any]] = []
    if isinstance(instance0_out, dict):
        for entry in (instance0_out.get("enrichments") or []):
            if not isinstance(entry, dict):
                continue
            sid = str(entry.get("spec_id", "")).strip()
            if sid and sid not in flagged_spec_ids:
                enrichments.append(entry)

    # Apply enrichments (acceptance_criteria only) to the working rows.
    # evidence_type is now per-criterion and lives in the per-spec test_plan
    # side-file; it no longer occupies a SADS CSV column.
    if enrichments and not ctx.dry_run:
        _header_map = {h.strip().lower(): h for h in headers if h}
        ac_col = _header_map.get("acceptance_criteria", "acceptance_criteria")
        sid_col = _header_map.get("spec_id", "spec_id")
        if ac_col not in headers:
            headers = list(headers) + [ac_col]
        for entry in enrichments:
            sid = str(entry.get("spec_id", "")).strip()
            ac_val = str(entry.get("acceptance_criteria", "")).strip()
            if not ac_val:
                continue
            for row in rows:
                if str(row.get(sid_col, "")).strip() == sid:
                    row[ac_col] = ac_val
                    break

    _write_json(run_dir / "enrichments.json", {"enrichments": enrichments})

    # Persist per-spec test_plan side-files. Structured nested data lives outside
    # the CSV; downstream consumers (implement, reviewer) load these by spec_id.
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

    if not consensus_items:
        _report_refine_step("Refine", "ok", "no issues found — writing enriched output")
        output_path = _resolve_output_csv_path(config, project_root)
        if not ctx.dry_run:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rows_to_csv(headers, rows), encoding="utf-8")
        _write_json(run_dir / "summary.json", {
            "status": "completed",
            "specs_enriched": len(enrichments),
            "appendix_recommendations": appendix_recommendations,
            "output_path": str(output_path),
        })
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
            "appendix_recommendations": len(appendix_recommendations),
            "output_path": str(output_path),
            "dry_run": ctx.dry_run,
        }

    severity = _format_severity_breakdown(consensus_items)
    rec_suffix = (
        f"; {len(appendix_recommendations)} appendix gap(s)"
        if appendix_recommendations else ""
    )
    _report_refine_step(
        "Refine",
        "blocked",
        f"{len(consensus_items)} items require review (severity: {severity}){rec_suffix}",
    )
    v2_items = [_translate_v3_item_to_v2_legacy(item) for item in consensus_items]
    _write_resolution_block(
        v2_items,
        manual_dir,
        "agent_review",
        run_dir,
        ctx.run_id,
        completed_stages,
        RESOLUTION_SOURCE_AGENT,
        appendix_recommendations=appendix_recommendations,
    )
    _write_json(run_dir / "summary.json", {
        "status": "blocked",
        "blocking_items": len(consensus_items),
        "severity_breakdown": severity,
        "appendix_recommendations": appendix_recommendations,
        "specs_enriched": len(enrichments),
        "input_design_spec_path": str(design_path),
    })
    log_lifecycle_event("lifecycle_manual_resolution", command="refine", run_id=ctx.run_id)
    return {
        "command": "refine",
        "status": "blocked",
        "run_id": ctx.run_id,
        "blocking_items": len(consensus_items),
        "appendix_recommendations": len(appendix_recommendations),
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
            # Agents completed — load cached outputs, skip to gate
            _report_refine_step(
                "Resume", "ok",
                f"agents already completed — loading cached outputs (failed at {failed_at_stage})",
            )
            auditor_path = run_dir / "auditor_output.json"
            legacy_paths = [
                run_dir / "ambiguity_output.json",
                run_dir / "testability_output.json",
            ]
            if not auditor_path.exists() and any(p.exists() for p in legacy_paths):
                raise ResumeError(
                    "Cached agent outputs were produced by the legacy two-agent refine "
                    "pipeline (ambiguity_output.json / testability_output.json). "
                    "The schema is no longer compatible. Start a fresh run instead."
                )
            if not auditor_path.exists():
                raise ResumeError(
                    "Cached agent output file not found for resume (auditor_output.json)."
                )
            auditor_output = json.loads(auditor_path.read_text(encoding="utf-8"))

            consensus_items: list[dict[str, Any]] = (
                auditor_output.get("manual_resolution_items", [])
                if isinstance(auditor_output, dict) else []
            )
            appendix_recommendations: list[dict[str, Any]] = (
                auditor_output.get("appendix_recommendations", [])
                if isinstance(auditor_output, dict) else []
            )
            stages_list = list(completed_stages)
            manual_dir = run_dir / "manual_resolution"

            _write_json(run_meta_path, run_meta)

            if not consensus_items:
                _report_refine_step("Refine", "ok", "no issues found — copying input to output")
                output_path = _resolve_output_csv_path(config, project_root)
                if not ctx.dry_run:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(design_path, output_path)
                _write_json(run_dir / "summary.json", {
                    "status": "completed",
                    "specs_improved": 0,
                    "appendix_recommendations": appendix_recommendations,
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
                    "appendix_recommendations": len(appendix_recommendations),
                    "output_path": str(output_path),
                    "dry_run": ctx.dry_run,
                }

            severity = _format_severity_breakdown(consensus_items)
            rec_suffix = (
                f"; {len(appendix_recommendations)} appendix gap(s)"
                if appendix_recommendations else ""
            )
            _report_refine_step(
                "Refine", "blocked",
                f"{len(consensus_items)} items require review (severity: {severity}){rec_suffix}",
            )
            v2_items = [_translate_v3_item_to_v2_legacy(item) for item in consensus_items]
            _write_resolution_block(
                v2_items, manual_dir, "agent_review",
                run_dir, resume_run_id, stages_list,
                RESOLUTION_SOURCE_AGENT,
                appendix_recommendations=appendix_recommendations,
            )
            _write_json(run_dir / "summary.json", {
                "status": "blocked",
                "blocking_items": len(consensus_items),
                "severity_breakdown": severity,
                "appendix_recommendations": appendix_recommendations,
                "input_design_spec_path": str(design_path),
            })
            log_lifecycle_event("lifecycle_manual_resolution", command="refine", run_id=ctx.run_id)
            return {
                "command": "refine",
                "status": "blocked",
                "run_id": resume_run_id,
                "blocking_items": len(consensus_items),
                "appendix_recommendations": len(appendix_recommendations),
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
