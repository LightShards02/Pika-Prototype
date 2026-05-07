"""Code evaluator sub-agent for the implement command — DEPRECATED (P6).

Superseded by ``handlers/implement/reviewer.py`` and the reviewer-loop
orchestrator wired through ``_maybe_run_reviewer`` in
``handlers/implement/impl.py``. The legacy evaluator path remains callable
behind ``implement.evaluator.enabled`` for one release so existing
workspaces can opt back in if the reviewer loop misbehaves; new
deployments should set ``implement.reviewer.enabled = true`` instead.
Scheduled for removal in the next release.

Wraps the ``code_evaluator`` prompt: builds template variables from a finished
batch's spec_outputs + harness results, invokes the agent through the standard
schema-retry loop, and translates the evaluator's failed_specs into manual
resolution items the lifecycle can persist.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from core.constants import EscalationKind
from core.context import RuntimeContext
from core.lifecycle import (
    invoke_agent_with_schema_retry,
    log_lifecycle_event,
    resolve_agent_artifacts_dir_for_command,
)
from handlers.implement.semantic_guard import build_directory_tree_snapshot

CODE_EVALUATOR_PROMPT_NAME = "code_evaluator"
DEFAULT_FAIL_ACTION = "warn"
DEFAULT_RERUN_THRESHOLD = "blocker"
DEFAULT_MAX_EVAL_CYCLES = 1
_SEVERITY_RANK = {"minor": 1, "major": 2, "blocker": 3}


def build_applied_diffs_summary(
    spec_outputs: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build a compact per-spec summary of applied diffs for the evaluator prompt.

    Each entry: ``{spec_id, touched_files, diff_ids, summary}``.
    ``touched_files`` is the deduplicated union across the spec's diffs.
    """
    summary: list[dict[str, Any]] = []
    for spec_id, payload in spec_outputs.items():
        diffs = payload.get("diffs") or []
        diff_ids: list[str] = []
        touched: set[str] = set()
        for diff in diffs:
            if not isinstance(diff, Mapping):
                continue
            did = str(diff.get("diff_id") or "").strip()
            if did:
                diff_ids.append(did)
            for path in diff.get("touched_files") or []:
                if isinstance(path, str) and path.strip():
                    touched.add(path.strip())
        summary.append(
            {
                "spec_id": spec_id,
                "diff_ids": diff_ids,
                "touched_files": sorted(touched),
                "summary": str(payload.get("summary") or "").strip(),
            }
        )
    summary.sort(key=lambda x: x["spec_id"])
    return summary


def _coerce_severity(value: Any) -> str:
    if isinstance(value, str) and value in _SEVERITY_RANK:
        return value
    return "blocker"


def collect_failed_spec_ids_above_threshold(
    failed_specs: Sequence[Mapping[str, Any]],
    threshold: str,
) -> set[str]:
    """Return spec_ids whose severity meets or exceeds ``threshold``."""
    min_rank = _SEVERITY_RANK.get(threshold, _SEVERITY_RANK[DEFAULT_RERUN_THRESHOLD])
    out: set[str] = set()
    for entry in failed_specs:
        if not isinstance(entry, Mapping):
            continue
        spec_id = str(entry.get("spec_id") or "").strip()
        if not spec_id:
            continue
        rank = _SEVERITY_RANK.get(_coerce_severity(entry.get("severity")), 0)
        if rank >= min_rank:
            out.add(spec_id)
    return out


def eval_failures_to_resolution_items(
    failed_specs: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Translate evaluator failed_specs into manual_resolution_items entries."""
    items: list[dict[str, Any]] = []
    for idx, entry in enumerate(failed_specs, start=1):
        if not isinstance(entry, Mapping):
            continue
        spec_id = str(entry.get("spec_id") or "").strip()
        if not spec_id:
            continue
        reason = str(entry.get("reason") or "").strip() or "Code evaluator flagged this spec without a reason."
        severity = _coerce_severity(entry.get("severity"))
        suggested = str(entry.get("suggested_fix") or "").strip()
        question = (
            f"Code evaluator flagged spec {spec_id} as {severity}. "
            "How should the implementation proceed?"
        )
        options = [
            {
                "option_id": "accept_as_is",
                "label": "Accept current implementation",
                "effect": "Proceed without changes; mark spec implemented despite evaluator concern.",
            },
            {
                "option_id": "rework",
                "label": "Re-run implement for this spec",
                "effect": "Re-execute the affected batch with evaluator feedback as semantic_retry_context.",
            },
        ]
        evidence_refs: list[str] = []
        if suggested:
            evidence_refs.append(f"suggested_fix: {suggested}")
        items.append(
            {
                "item_id": f"code_eval_{idx:02d}_{spec_id}",
                "title": f"Code evaluator: {spec_id} ({severity})",
                "question": question,
                "options": options,
                "recommended_option_id": "rework" if severity == "blocker" else "accept_as_is",
                "required": True,
                "blocking_reason": reason,
                "evidence_refs": evidence_refs,
                "kind": EscalationKind.CODE_EVAL_FAILURE.value,
            }
        )
    return items


def build_evaluator_feedback(
    eval_output: Mapping[str, Any],
    rerun_spec_ids: set[str],
) -> str:
    """Render evaluator feedback for the next batch's semantic_retry_context."""
    rationale = str(eval_output.get("overall_rationale") or "").strip()
    lines: list[str] = []
    if rationale:
        lines.append(f"Code evaluator rationale: {rationale}")
    failed = eval_output.get("failed_specs") or []
    targeted: list[str] = []
    for entry in failed:
        if not isinstance(entry, Mapping):
            continue
        sid = str(entry.get("spec_id") or "").strip()
        if sid not in rerun_spec_ids:
            continue
        sev = _coerce_severity(entry.get("severity"))
        reason = str(entry.get("reason") or "").strip()
        suggested = str(entry.get("suggested_fix") or "").strip()
        chunk = f"- {sid} [{sev}]: {reason}"
        if suggested:
            chunk += f" Suggested: {suggested}"
        targeted.append(chunk)
    if targeted:
        lines.append("Targeted re-run guidance:")
        lines.extend(targeted)
    return "\n".join(lines).strip()


def run_code_evaluator(
    *,
    config: dict[str, Any],
    ctx: RuntimeContext,
    schema_path: Path,
    project_root: Path,
    paths: Mapping[str, Path],
    selected_specs_csv: str,
    spec_outputs: Mapping[str, Mapping[str, Any]],
    harness_results: Sequence[Mapping[str, Any]],
    module_catalog_json: str = "",
    appendix_content: str = "",
) -> dict[str, Any]:
    """Single evaluator invocation. Returns the validated evaluator output dict."""
    artifacts_root = resolve_agent_artifacts_dir_for_command(
        config, project_root, "implement", ctx.run_id
    )
    artifacts_dir = artifacts_root / "code_evaluator"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    applied_diffs_summary = build_applied_diffs_summary(spec_outputs)

    template_vars: dict[str, Any] = {
        "output_schema_file": str(schema_path),
        "project_context": appendix_content if appendix_content else "",
        "selected_specs_csv": selected_specs_csv,
        "applied_diffs_summary_json": json.dumps(applied_diffs_summary, indent=2),
        "directory_tree_snapshot": build_directory_tree_snapshot(project_root),
        "harness_results_json": json.dumps(list(harness_results), indent=2),
        "module_catalog_json": module_catalog_json or "",
        "manual_resolution_file": str(paths["manual"]),
        "run_summary_file": str(paths["run"] / "summary.json"),
        "agent_artifacts_dir": str(artifacts_dir),
        "control_vocab_section": "",
    }

    log_lifecycle_event(
        "lifecycle_code_evaluator_invoking",
        command="implement",
        run_id=ctx.run_id,
        extra={
            "spec_count": len(applied_diffs_summary),
            "harness_count": len(list(harness_results)),
        },
    )
    output = invoke_agent_with_schema_retry(
        prompt_name=CODE_EVALUATOR_PROMPT_NAME,
        template_vars=template_vars,
        schema_path=schema_path,
        config=config,
        ctx=ctx,
    )
    log_lifecycle_event(
        "lifecycle_code_evaluator_done",
        command="implement",
        run_id=ctx.run_id,
        extra={
            "passed": bool(output.get("passed")),
            "failed_spec_count": len(output.get("failed_specs") or []),
        },
    )
    return output


def evaluator_config(impl: Mapping[str, Any]) -> dict[str, Any]:
    """Return the resolved evaluator config block with defaults filled in."""
    raw = impl.get("evaluator")
    if not isinstance(raw, Mapping):
        raw = {}
    return {
        "enabled": bool(raw.get("enabled", False)),
        "max_eval_cycles": int(raw.get("max_eval_cycles", DEFAULT_MAX_EVAL_CYCLES)),
        "fail_action": str(raw.get("fail_action", DEFAULT_FAIL_ACTION)),
        "rerun_severity_threshold": str(
            raw.get("rerun_severity_threshold", DEFAULT_RERUN_THRESHOLD)
        ),
        "harnesses": list(raw.get("harnesses") or [
            "syntax_check",
            "import_smoke",
            "unresolved_symbol",
            "forbidden_path_violation",
            "anchor_preservation",
            "diff_size_sanity",
        ]),
        "diff_size_sanity_max_lines": int(raw.get("diff_size_sanity_max_lines", 2000)),
    }
