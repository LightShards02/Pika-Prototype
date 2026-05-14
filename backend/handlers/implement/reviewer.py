"""Two-tier reviewer for the implement command (Phase 4).

Architecture:

1. **Per-spec axis reviewer (LLM).** ``run_reviewer_for_batch`` fans one
   reviewer call out per spec_id in the batch via a thread pool, bounded
   by ``reviewer.max_parallel_per_spec``. Each call is wall-clock-bounded
   by ``reviewer.per_spec_max_total_seconds``; exhaustion fails the
   entire batch (no partial-result synthesis).

2. **Synthesis pass (deterministic Python).** Given all per-spec results,
   ``synthesize_reviewer_output`` aggregates axis findings, applies the
   Phase-4 demotion rule (axis 3/4 → minor_findings when axis 1 passes
   for the same spec), decides ``response_kind`` via an explicit decision
   tree, and builds an ``amendment_packet`` with deterministic
   ``amendment_id`` strings of the form ``f"{spec_id}::{criterion_id}::{axis}"``.

Public functions (the synthesis helpers are exported so Phase 5's loop
state machine and tests can call them without invoking the LLM tier).
"""

from __future__ import annotations

import json
from concurrent.futures import (
    FIRST_COMPLETED,
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
    wait as futures_wait,
)
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from core.constants import EscalationKind
from core.context import RuntimeContext
from core.lifecycle import invoke_agent_with_schema_retry, log_lifecycle_event

REVIEWER_PER_SPEC_PROMPT_NAME = "reviewer_per_spec"

AXIS_NAMES: tuple[str, ...] = ("code", "test_plan", "test_code", "test_evidence")
_STATUS_RANK = {"pass": 0, "insufficient_evidence": 1, "fail": 2}
_DEMOTABLE_AXES: frozenset[str] = frozenset({"test_code", "test_evidence"})


@dataclass
class PerSpecResult:
    """Container for one per-spec reviewer LLM call's output."""

    spec_id: str
    axis_findings: list[dict[str, Any]] = field(default_factory=list)
    minor_findings: list[dict[str, Any]] = field(default_factory=list)
    block_recommendation: dict[str, Any] | None = None


def amendment_id_for(spec_id: str, criterion_id: str, axis: str) -> str:
    """Compute the deterministic amendment_id used for stagnation detection.

    Pure string composition — no hashing, no normalization. Only stable
    fields participate so two iterations flagging the same atomic defect
    produce identical IDs regardless of how the LLM phrased it.
    """
    return f"{spec_id}::{criterion_id}::{axis}"


def amendment_ids_in_packet(packet: Mapping[str, Any] | None) -> set[str]:
    """Return the set of amendment_id strings present in an amendment_packet."""
    if not isinstance(packet, Mapping):
        return set()
    out: set[str] = set()
    for entry in packet.get("amendments") or []:
        if not isinstance(entry, Mapping):
            continue
        aid = str(entry.get("amendment_id", "")).strip()
        if aid:
            out.add(aid)
    return out


def is_stagnant(
    current_packet: Mapping[str, Any] | None,
    prior_amendment_ids: set[str] | None,
) -> bool:
    """Return True when iteration N's packet shows zero progress vs N-1.

    Stagnation rule (P5): every amendment_id from iteration N-1 also
    appears in iteration N. New amendments may be added; the rule fires
    purely on the persistence of *all* prior amendments. Identity is the
    deterministic ``f"{spec_id}::{criterion_id}::{axis}"`` form, so LLM
    prose drift on required_change does not affect detection.
    """
    if not prior_amendment_ids:
        return False
    current_ids = amendment_ids_in_packet(current_packet)
    return prior_amendment_ids.issubset(current_ids)


def out_of_scope_diff_ids(
    current_diff_plan: Sequence[Mapping[str, Any]],
    target_spec_ids: Sequence[str] | set[str],
    prior_diff_plan: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return diff entries that touch spec ownership outside ``target_spec_ids``.

    P5 partial-spec lock-in. A diff is in-scope when:
      * its ``owner_spec_id`` is in ``target_spec_ids``, OR
      * its ``owner_spec_id`` was already an owner in ``prior_diff_plan``
        (shared infrastructure that pre-existed this amendment iteration
        and is being modified again — the implementer is allowed to
        re-emit it under the same owner).

    Each returned entry is the full diff_plan_item dict, with an extra
    ``offending_owner_spec_id`` key copied for caller convenience.
    """
    targets = {str(s).strip() for s in target_spec_ids if str(s).strip()}
    prior_owners: set[str] = set()
    if prior_diff_plan:
        for entry in prior_diff_plan:
            if not isinstance(entry, Mapping):
                continue
            owner = str(entry.get("owner_spec_id", "")).strip()
            if owner:
                prior_owners.add(owner)
    offenders: list[dict[str, Any]] = []
    for entry in current_diff_plan:
        if not isinstance(entry, Mapping):
            continue
        owner = str(entry.get("owner_spec_id", "")).strip()
        if not owner:
            continue
        if owner in targets:
            continue
        if owner in prior_owners:
            # Pre-existing shared diff being modified — allow.
            continue
        offenders.append({**entry, "offending_owner_spec_id": owner})
    return offenders


def _axis_lookup(axis_findings: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index per-spec axis_findings by axis name."""
    out: dict[str, dict[str, Any]] = {}
    for entry in axis_findings:
        if not isinstance(entry, Mapping):
            continue
        axis = str(entry.get("axis", "")).strip()
        if axis in AXIS_NAMES:
            out[axis] = dict(entry)
    return out


def _worst_status(*statuses: str) -> str:
    return max(statuses, key=lambda s: _STATUS_RANK.get(s, -1))


def _aggregate_axis_findings(
    per_spec_results: Sequence[PerSpecResult],
) -> list[dict[str, Any]]:
    """Build batch-level axis_findings (one entry per axis, status = worst across specs)."""
    aggregate: list[dict[str, Any]] = []
    for axis in AXIS_NAMES:
        worst_status = "pass"
        worst_summary = "All specs pass on this axis."
        worst_spec: str | None = None
        for result in per_spec_results:
            entry = _axis_lookup(result.axis_findings).get(axis)
            if entry is None:
                continue
            status = str(entry.get("status", "")).strip() or "insufficient_evidence"
            ranked = _worst_status(worst_status, status)
            if ranked != worst_status or worst_spec is None:
                worst_status = ranked
                worst_summary = str(entry.get("summary", "")).strip() or worst_summary
                worst_spec = result.spec_id
        summary = (
            worst_summary
            if worst_status == "pass" or worst_spec is None
            else f"[{worst_spec}] {worst_summary}"
        )
        aggregate.append({"axis": axis, "status": worst_status, "summary": summary})
    return aggregate


def _build_per_spec_axis_matrix(
    per_spec_results: Sequence[PerSpecResult],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Return spec_id -> axis -> finding entry for the demotion rule."""
    return {r.spec_id: _axis_lookup(r.axis_findings) for r in per_spec_results}


def _apply_demotion_rule(
    matrix: Mapping[str, Mapping[str, dict[str, Any]]],
    minor_seed: Sequence[Mapping[str, Any]],
    *,
    spec_id_lookup: Mapping[str, str] | None = None,
) -> tuple[dict[str, set[str]], list[dict[str, Any]]]:
    """Apply Phase-4 axis 3/4 demotion when axis 1 passes for the same spec.

    Returns:
        (demoted_axes_by_spec, aggregated_minor_findings)

        demoted_axes_by_spec maps spec_id to the set of axis names whose
        finding for that spec was demoted (so amendment-builder skips them).
        aggregated_minor_findings is the merged minor_findings list for the
        final reviewer_output, including Phase-4 demoted entries.
    """
    demoted: dict[str, set[str]] = {}
    minor: list[dict[str, Any]] = []
    # Seed minor list with the per-spec minor_findings the LLM directly emitted.
    for entry in minor_seed:
        if isinstance(entry, Mapping):
            minor.append(dict(entry))

    for spec_id, axis_map in matrix.items():
        code_finding = axis_map.get("code") or {}
        if str(code_finding.get("status", "")).strip() != "pass":
            continue
        for axis in _DEMOTABLE_AXES:
            entry = axis_map.get(axis)
            if not isinstance(entry, Mapping):
                continue
            status = str(entry.get("status", "")).strip()
            if status not in {"fail", "insufficient_evidence"}:
                continue
            demoted.setdefault(spec_id, set()).add(axis)
            offenders = entry.get("offending_criterion_ids") or []
            if not offenders:
                # Emit a single demoted minor entry without criterion_id
                # when the LLM didn't pin specific criteria.
                minor.append({
                    "spec_id": spec_id,
                    "axis": axis,
                    "summary": str(entry.get("summary", "")).strip()
                    or f"Demoted {axis} finding for {spec_id}.",
                })
                continue
            base_summary = str(entry.get("summary", "")).strip()
            for cid in offenders:
                cid_str = str(cid).strip()
                if not cid_str:
                    continue
                minor.append({
                    "spec_id": spec_id,
                    "axis": axis,
                    "criterion_id": cid_str,
                    "summary": base_summary or f"Demoted {axis} finding for {spec_id}/{cid_str}.",
                })
    return demoted, minor


def _detect_block_recommendations(
    per_spec_results: Sequence[PerSpecResult],
) -> tuple[str | None, str, list[str]]:
    """Inspect per-spec block_recommendations for ambiguity / scope_conflict.

    Returns:
        (kind, reason, conflicting_spec_ids). kind is None when no spec
        emitted a block_recommendation. scope_conflict requires at least
        two specs that mention each other.
    """
    ambiguities: list[tuple[str, str]] = []
    scope_conflicts: dict[str, set[str]] = {}
    for r in per_spec_results:
        rec = r.block_recommendation
        if not isinstance(rec, Mapping):
            continue
        kind = str(rec.get("kind", "")).strip()
        reason = str(rec.get("reason", "")).strip() or "No reason provided."
        if kind == "ambiguity":
            ambiguities.append((r.spec_id, reason))
        elif kind == "scope_conflict":
            others = [
                str(s).strip()
                for s in (rec.get("conflicting_spec_ids") or [])
                if str(s).strip()
            ]
            scope_conflicts[r.spec_id] = set(others)

    if scope_conflicts:
        # Mutual reference: spec A points at B AND B points at A.
        for src, targets in scope_conflicts.items():
            for tgt in targets:
                if tgt in scope_conflicts and src in scope_conflicts[tgt]:
                    parties = sorted({src, tgt})
                    return (
                        "scope_conflict",
                        f"Specs {parties[0]} and {parties[1]} require "
                        f"mutually exclusive code/test changes.",
                        parties,
                    )
        # No mutual reference — surface as ambiguity instead.
        first_src = next(iter(scope_conflicts))
        return (
            "ambiguity",
            f"Spec {first_src} declared scope_conflict with "
            f"{sorted(scope_conflicts[first_src])} but no mutual reference exists.",
            [first_src],
        )

    if ambiguities:
        sid, reason = ambiguities[0]
        return ("ambiguity", f"[{sid}] {reason}", [sid])
    return (None, "", [])


def _build_amendment_packet(
    per_spec_results: Sequence[PerSpecResult],
    demoted: Mapping[str, set[str]],
    *,
    packet_id: str,
    criteria_text_lookup: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any] | None:
    """Build amendment_packet from non-demoted axis failures.

    Returns None when there are no actionable failures (caller should
    pick a different response_kind).
    """
    amendments: list[dict[str, Any]] = []
    target_specs: set[str] = set()
    for r in per_spec_results:
        for entry in r.axis_findings:
            if not isinstance(entry, Mapping):
                continue
            axis = str(entry.get("axis", "")).strip()
            status = str(entry.get("status", "")).strip()
            if axis not in AXIS_NAMES or status != "fail":
                continue
            if axis in demoted.get(r.spec_id, set()):
                continue
            offenders = [
                str(c).strip()
                for c in (entry.get("offending_criterion_ids") or [])
                if str(c).strip()
            ]
            if not offenders:
                continue
            defect_summary = (
                str(entry.get("summary", "")).strip()
                or f"{axis} review failed for {r.spec_id}."
            )
            for cid in offenders:
                criterion_text = ""
                if criteria_text_lookup is not None:
                    criterion_text = (
                        criteria_text_lookup.get(r.spec_id, {}).get(cid, "")
                    )
                required_change = _render_required_change(axis, cid, criterion_text)
                amendment = {
                    "amendment_id": amendment_id_for(r.spec_id, cid, axis),
                    "spec_id": r.spec_id,
                    "criterion_id": cid,
                    "axis": axis,
                    "defect_summary": defect_summary,
                    "required_change": required_change,
                }
                amendments.append(amendment)
                target_specs.add(r.spec_id)

    if not amendments:
        return None
    # De-duplicate by amendment_id (deterministic identity guarantees
    # multiple offending paths can't double-count the same atomic defect).
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for amendment in amendments:
        aid = amendment["amendment_id"]
        if aid in seen:
            continue
        seen.add(aid)
        unique.append(amendment)
    return {
        "packet_id": packet_id,
        "target_spec_ids": sorted(target_specs),
        "amendments": unique,
    }


def _render_required_change(axis: str, criterion_id: str, criterion_text: str) -> str:
    """Build a deterministic required_change string from axis + criterion text.

    Synthesis owns this rendering (not the LLM) so the string remains
    stable across iterations even when LLM prose drifts.
    """
    suffix = f": {criterion_text}" if criterion_text else "."
    if axis == "code":
        return f"Implement code that satisfies criterion {criterion_id}{suffix}"
    if axis == "test_plan":
        return f"Cover criterion {criterion_id} in the test plan{suffix}"
    if axis == "test_code":
        return (
            f"Author or extend test code so the test_plan entry for "
            f"criterion {criterion_id} executes{suffix}"
        )
    if axis == "test_evidence":
        return (
            f"Produce passing test evidence for criterion {criterion_id} "
            f"(verify the relevant test executes and passes){suffix}"
        )
    return f"Address criterion {criterion_id} on axis {axis}{suffix}"


def _build_criteria_assessment(
    per_spec_results: Sequence[PerSpecResult],
    *,
    criteria_text_lookup: Mapping[str, Mapping[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Build criteria_assessment[] for response_kind=approve.

    Iterates per-spec axis_findings and emits one entry per (spec_id,
    criterion_id) with satisfied=True (since all axes pass on approve).
    """
    out: list[dict[str, Any]] = []
    for r in per_spec_results:
        seen: set[str] = set()
        for entry in r.axis_findings:
            if not isinstance(entry, Mapping):
                continue
            for cid in entry.get("offending_criterion_ids") or []:
                cid_str = str(cid).strip()
                if not cid_str or cid_str in seen:
                    continue
                seen.add(cid_str)
        if criteria_text_lookup is not None:
            for cid in criteria_text_lookup.get(r.spec_id, {}):
                if cid in seen:
                    continue
                seen.add(cid)
                out.append({
                    "spec_id": r.spec_id,
                    "criterion_id": cid,
                    "satisfied": True,
                    "evidence_summary": (
                        f"All four review axes pass for {r.spec_id}/{cid}."
                    ),
                })
    return out


def synthesize_reviewer_output(
    per_spec_results: Sequence[PerSpecResult],
    *,
    iteration_index: int,
    batch_id: str,
    escalate_on_axes_insufficient_evidence: bool = True,
    criteria_text_lookup: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Run the deterministic synthesis pass over per-spec reviewer outputs.

    Returns a dict that validates against ``reviewer_output.schema.json``.

    Decision tree (post-demotion):
      1. Any per-spec block_recommendation → manual_block (kind=ambiguity
         or scope_conflict per the recommendation aggregation).
      2. All non-demoted axis findings pass → approve.
      3. Any non-demoted axis fail → amend.
      4. Any non-demoted axis insufficient_evidence with the escalate flag
         set → manual_block (kind=ambiguity).
    """
    if not per_spec_results:
        # Defensive: empty batch can't approve nothing meaningfully.
        # Caller should never invoke this with no specs, but produce a
        # well-formed manual_block payload rather than crashing.
        return {
            "response_kind": "manual_block",
            "axis_findings": [
                {"axis": axis, "status": "insufficient_evidence", "summary": "No specs reviewed."}
                for axis in AXIS_NAMES
            ],
            "manual_resolution_items": [
                {
                    "item_id": "reviewer_empty_batch",
                    "title": "Reviewer received no specs",
                    "question": "Investigate why the batch had no spec_rows.",
                    "options": [
                        {
                            "option_id": "investigate",
                            "label": "Investigate",
                            "effect": "Inspect upstream brief construction.",
                        }
                    ],
                    "blocking_reason": "No per-spec reviewer results to synthesize.",
                    "kind": EscalationKind.AMBIGUITY.value,
                }
            ],
        }

    matrix = _build_per_spec_axis_matrix(per_spec_results)
    minor_seed: list[dict[str, Any]] = []
    for r in per_spec_results:
        for entry in r.minor_findings:
            if isinstance(entry, Mapping):
                copied = dict(entry)
                copied.setdefault("spec_id", r.spec_id)
                minor_seed.append(copied)

    demoted, minor_findings = _apply_demotion_rule(matrix, minor_seed)
    axis_findings = _aggregate_axis_findings(per_spec_results)

    # Compute non-demoted axis statuses across all specs.
    has_fail = False
    has_insufficient = False
    for spec_id, axis_map in matrix.items():
        for axis, entry in axis_map.items():
            if axis in demoted.get(spec_id, set()):
                continue
            status = str(entry.get("status", "")).strip()
            if status == "fail":
                has_fail = True
            elif status == "insufficient_evidence":
                has_insufficient = True

    block_kind, block_reason, block_specs = _detect_block_recommendations(per_spec_results)

    base: dict[str, Any] = {"axis_findings": axis_findings}
    if minor_findings:
        base["minor_findings"] = minor_findings

    # Stage 6 decision tree.
    if block_kind is not None:
        base["response_kind"] = "manual_block"
        base["manual_resolution_items"] = [
            _build_review_block_item(block_kind, block_reason, block_specs)
        ]
        return base

    if has_fail:
        base["response_kind"] = "amend"
        packet = _build_amendment_packet(
            per_spec_results,
            demoted,
            packet_id=f"AMD_{batch_id}_iter{iteration_index}",
            criteria_text_lookup=criteria_text_lookup,
        )
        if packet is None:
            # All "fail" findings were demoted — fall through to approve.
            base["response_kind"] = "approve"
            base["criteria_assessment"] = _build_criteria_assessment(
                per_spec_results, criteria_text_lookup=criteria_text_lookup
            )
            return base
        base["amendment_packet"] = packet
        return base

    if has_insufficient and escalate_on_axes_insufficient_evidence:
        base["response_kind"] = "manual_block"
        base["manual_resolution_items"] = [
            _build_review_block_item(
                "ambiguity",
                "One or more review axes returned insufficient_evidence.",
                [r.spec_id for r in per_spec_results],
            )
        ]
        return base

    base["response_kind"] = "approve"
    assessment = _build_criteria_assessment(
        per_spec_results, criteria_text_lookup=criteria_text_lookup
    )
    if assessment:
        base["criteria_assessment"] = assessment
    else:
        # Schema requires criteria_assessment on approve; emit a single
        # spec-level entry per spec when no AC text is available.
        base["criteria_assessment"] = [
            {
                "spec_id": r.spec_id,
                "criterion_id": "AC1",
                "satisfied": True,
                "evidence_summary": (
                    f"All four review axes pass for {r.spec_id}; "
                    "no per-criterion AC text was available to enumerate."
                ),
            }
            for r in per_spec_results
        ]
    return base


def _build_review_block_item(
    kind: str,
    reason: str,
    spec_ids: Sequence[str],
) -> dict[str, Any]:
    """Construct a manual_resolution_item for a reviewer-emitted block."""
    suffix = f" (specs: {', '.join(sorted({s for s in spec_ids if s}))})"
    return {
        "item_id": f"reviewer_{kind}_{'_'.join(sorted({s for s in spec_ids if s})) or 'batch'}",
        "title": f"Reviewer {kind.replace('_', ' ')}{suffix}",
        "question": (
            f"The reviewer escalated this batch as {kind}. "
            "How should the run proceed?"
        ),
        "options": [
            {
                "option_id": "edit_specs",
                "label": "Edit affected specs and resume",
                "effect": "Modify the offending specs/AC and resume — pika resolve will reload.",
            },
            {
                "option_id": "skip_batch",
                "label": "Skip this batch and continue",
                "effect": "Mark this batch as not-implemented; downstream batches continue.",
            },
        ],
        "blocking_reason": reason,
        "kind": kind,
    }


def parse_per_spec_output(
    output: Mapping[str, Any] | None,
    *,
    expected_spec_id: str,
) -> PerSpecResult:
    """Coerce a raw LLM dict into a PerSpecResult.

    Trusts the schema validation upstream — this just unpacks the fields
    into the dataclass and falls back to safe defaults when the LLM
    omitted optional sections.
    """
    if not isinstance(output, Mapping):
        return PerSpecResult(spec_id=expected_spec_id)
    spec_id = str(output.get("spec_id", "")).strip() or expected_spec_id
    axis_findings_raw = output.get("axis_findings") or []
    axis_findings: list[dict[str, Any]] = [
        dict(entry) for entry in axis_findings_raw if isinstance(entry, Mapping)
    ]
    minor_raw = output.get("minor_findings") or []
    minor_findings: list[dict[str, Any]] = [
        dict(entry) for entry in minor_raw if isinstance(entry, Mapping)
    ]
    block_recommendation: dict[str, Any] | None = None
    if isinstance(output.get("block_recommendation"), Mapping):
        block_recommendation = dict(output["block_recommendation"])
    return PerSpecResult(
        spec_id=spec_id,
        axis_findings=axis_findings,
        minor_findings=minor_findings,
        block_recommendation=block_recommendation,
    )


def project_per_spec_review_inputs(
    *,
    spec_id: str,
    brief: Mapping[str, Any],
    harness_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Slice batch-level data down to one spec's view for the reviewer prompt.

    Returns a template_vars dict the reviewer_per_spec prompt expects.
    Batch-shared inputs (verification_evidence_json, directory_tree_snapshot)
    are added by the caller after this projection.
    """
    spec_rows = brief.get("spec_rows") or []
    spec_row: dict[str, Any] = {}
    for row in spec_rows:
        if isinstance(row, Mapping) and str(row.get("spec_id", "")).strip() == spec_id:
            spec_row = dict(row)
            break

    ac_for_batch = brief.get("acceptance_criteria_for_batch") or {}
    ac_for_spec = ac_for_batch.get(spec_id, {}) if isinstance(ac_for_batch, Mapping) else {}

    tp_for_batch = brief.get("test_plan_for_batch") or {}
    tp_for_spec = tp_for_batch.get(spec_id, {}) if isinstance(tp_for_batch, Mapping) else {}

    # Slice harness results to this spec_id (when the harness recorded one)
    # plus all spec-agnostic harness entries (forbidden_path_violation,
    # diff_size_sanity etc. typically attribute to a spec when known and
    # leave it None otherwise).
    spec_harness: list[dict[str, Any]] = []
    for entry in harness_results:
        if not isinstance(entry, Mapping):
            continue
        target_sid = entry.get("spec_id")
        if target_sid is None or str(target_sid).strip() == spec_id:
            spec_harness.append(dict(entry))

    return {
        "spec_id": spec_id,
        "spec_row_csv": json.dumps(spec_row, indent=2, sort_keys=True),
        "acceptance_criteria_for_spec_json": json.dumps(ac_for_spec, indent=2),
        "test_plan_for_spec_json": json.dumps(tp_for_spec, indent=2),
        "harness_results_for_spec_json": json.dumps(spec_harness, indent=2),
    }


def run_reviewer_for_batch(
    *,
    config: dict[str, Any],
    ctx: RuntimeContext,
    schema_path: Path,
    brief: Mapping[str, Any],
    harness_results: Sequence[Mapping[str, Any]],
    applied_diffs_summary: Mapping[str, Any] | str,
    authored_test_cases_by_spec: Mapping[str, Sequence[Mapping[str, Any]]],
    verification_evidence: Sequence[Mapping[str, Any]],
    directory_tree_snapshot: str,
    selected_specs_csv: str,
    iteration_index: int,
    prior_amendment_packets: Sequence[Mapping[str, Any]] | None = None,
    max_parallel_per_spec: int = 4,
    per_spec_max_total_seconds: int = 180,
) -> tuple[list[PerSpecResult] | None, str | None]:
    """Run per-spec reviewers in parallel.

    Returns:
        ``(results, None)`` on success — one PerSpecResult per spec_id in
        the brief.
        ``(None, failure_spec_id)`` on per-spec budget exhaustion — the
        caller fails the entire batch with reason
        ``"reviewer_per_spec_timeout"``.
    """
    spec_ids = sorted(
        {
            str(row.get("spec_id", "")).strip()
            for row in (brief.get("spec_rows") or [])
            if isinstance(row, Mapping) and str(row.get("spec_id", "")).strip()
        }
    )
    if not spec_ids:
        return ([], None)

    diffs_payload = (
        applied_diffs_summary
        if isinstance(applied_diffs_summary, str)
        else json.dumps(applied_diffs_summary, indent=2)
    )
    prior_packets = list(prior_amendment_packets or [])
    verification_payload = json.dumps(list(verification_evidence), indent=2)

    def _invoke(spec_id: str) -> PerSpecResult:
        per_spec_inputs = project_per_spec_review_inputs(
            spec_id=spec_id, brief=brief, harness_results=harness_results,
        )
        prior_for_spec = [
            packet
            for packet in prior_packets
            if isinstance(packet, Mapping)
            and any(
                isinstance(a, Mapping) and str(a.get("spec_id", "")).strip() == spec_id
                for a in (packet.get("amendments") or [])
            )
        ]
        authored_for_spec = list(authored_test_cases_by_spec.get(spec_id, []))
        from core import memory_store as _memory_store
        template_vars: dict[str, Any] = {
            "output_schema_file": str(schema_path),
            "applied_diffs_summary_for_spec_json": diffs_payload,
            "authored_test_cases_for_spec_json": json.dumps(authored_for_spec, indent=2),
            "verification_evidence_json": verification_payload,
            "directory_tree_snapshot": directory_tree_snapshot,
            "selected_specs_csv": selected_specs_csv,
            "iteration_index": str(iteration_index),
            "prior_amendment_packets_for_spec_json": json.dumps(prior_for_spec, indent=2),
            "memory": _memory_store.memory_template_value(ctx),
            **per_spec_inputs,
        }
        raw_output = invoke_agent_with_schema_retry(
            prompt_name=REVIEWER_PER_SPEC_PROMPT_NAME,
            template_vars=template_vars,
            schema_path=schema_path,
            config=config,
            ctx=ctx,
        )
        return parse_per_spec_output(raw_output, expected_spec_id=spec_id)

    results: list[PerSpecResult] = []
    timeout_spec: str | None = None
    with ThreadPoolExecutor(max_workers=max(1, max_parallel_per_spec)) as executor:
        futures = {executor.submit(_invoke, sid): sid for sid in spec_ids}
        pending = set(futures.keys())
        while pending and timeout_spec is None:
            done, pending = futures_wait(
                pending,
                timeout=per_spec_max_total_seconds,
                return_when=FIRST_COMPLETED,
            )
            if not done:
                # Wall-clock budget for the whole pool exceeded.
                still_running = [futures[f] for f in pending]
                timeout_spec = still_running[0] if still_running else "unknown"
                for f in pending:
                    f.cancel()
                break
            for f in done:
                sid = futures[f]
                try:
                    results.append(f.result(timeout=0))
                except FuturesTimeoutError:
                    timeout_spec = sid
                    for other in pending:
                        other.cancel()
                    pending = set()
                    break
                except Exception as exc:
                    log_lifecycle_event(
                        "lifecycle_reviewer_per_spec_failed",
                        command="implement",
                        run_id=ctx.run_id,
                        extra={"spec_id": sid, "error": str(exc)},
                    )
                    timeout_spec = sid
                    for other in pending:
                        other.cancel()
                    pending = set()
                    break

    if timeout_spec is not None:
        return (None, timeout_spec)
    return (results, None)
