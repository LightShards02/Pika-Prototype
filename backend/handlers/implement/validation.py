"""Unified plan and batch plan validation for implement workflow."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from core.constants import BatchKind, ImplementStatus
from core.implement_types import BatchBrief, BatchPlan, ModuleCatalog

from handlers.implement.helpers import _find_col

# Field-like word extraction from free text (camelCase, snake_case, kebab-case).
_WORD_TOKEN_PATTERN = re.compile(r"\b([A-Za-z][A-Za-z0-9_-]*)\b")
_WORD_SPLIT_PATTERN = re.compile(r"[_-]+")
_CAMEL_PART_PATTERN = re.compile(r"[A-Z]+(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+|[0-9]+")
_SAFE_TOKEN_PATTERN = re.compile(r"[^a-z0-9_]+")


_AMBIGUITY_TIE_MARGIN = 0.03


def _validate_unified_plan(
    plan: dict[str, Any],
    all_spec_ids: set[str],
    module_catalog: ModuleCatalog,
) -> dict[str, Any]:
    """Validate the unified planner output with differentiated failure handling.

    Checks (retryable — planner omission, share planner retry counter):
    1. Every spec_id in the workset appears in at least one planned_anchor.
    3. All spec_ids referenced in spec_dependencies exist in the workset.
    4. Every module in module_catalog has a corresponding module_plan.

    Checks (blocking — requires human judgment):
    2. spec_dependencies form a DAG (no cycles).
    """
    retryable_reasons: list[str] = []
    blocking_reasons: list[str] = []
    checks: list[str] = []
    cycle_path: list[str] | None = None

    module_plans = plan.get("module_plans", [])
    spec_deps = plan.get("spec_dependencies", [])

    # Check 1 (retryable): spec coverage
    covered_specs: set[str] = set()
    for mp in module_plans:
        if not isinstance(mp, dict):
            continue
        for anchor in mp.get("planned_anchors", []):
            if not isinstance(anchor, dict):
                continue
            for sid in anchor.get("spec_ids", []):
                covered_specs.add(str(sid).strip())

    uncovered = sorted(all_spec_ids - covered_specs)
    if uncovered:
        retryable_reasons.append(f"Specs not covered by any planned_anchor: {', '.join(uncovered)}")
    else:
        checks.append("all_specs_covered")

    # Check 2 (blocking): DAG acyclicity via DFS
    dep_graph: dict[str, set[str]] = {}
    all_referenced: set[str] = set()
    for dep in spec_deps:
        if not isinstance(dep, dict):
            continue
        consumer = str(dep.get("consumer_spec_id", "")).strip()
        providers = dep.get("provider_spec_ids", [])
        if not consumer or not isinstance(providers, list):
            continue
        dep_graph.setdefault(consumer, set())
        all_referenced.add(consumer)
        for p in providers:
            pid = str(p).strip()
            if pid:
                dep_graph[consumer].add(pid)
                dep_graph.setdefault(pid, set())
                all_referenced.add(pid)

    cycle = _find_cycle(dep_graph)
    if cycle:
        cycle_path = cycle
        blocking_reasons.append(f"Spec dependency cycle detected: {' -> '.join(cycle)}")
    else:
        checks.append("spec_dependencies_acyclic")

    # Check 3 (retryable): all referenced spec_ids exist in workset
    unknown_refs = sorted(all_referenced - all_spec_ids)
    if unknown_refs:
        retryable_reasons.append(f"spec_dependencies reference unknown spec_ids: {', '.join(unknown_refs)}")
    else:
        checks.append("spec_dependency_refs_valid")

    # Check 4 (retryable): module coverage
    catalog_tags = {
        str(m.get("module_tag", "")).strip()
        for m in module_catalog.get("modules", [])
        if isinstance(m, dict) and str(m.get("module_tag", "")).strip()
    }
    plan_tags = {
        str(mp.get("module_tag", "")).strip()
        for mp in module_plans
        if isinstance(mp, dict) and str(mp.get("module_tag", "")).strip()
    }
    missing_modules = sorted(catalog_tags - plan_tags)
    if missing_modules:
        retryable_reasons.append(f"Modules in catalog but missing from plan: {', '.join(missing_modules)}")
    else:
        checks.append("all_modules_planned")

    all_reasons = retryable_reasons + blocking_reasons
    return {
        "status": ImplementStatus.PASSED if not all_reasons else ImplementStatus.FAILED,
        "checks": checks,
        "reasons": all_reasons,
        "retryable_reasons": retryable_reasons,
        "blocking_reasons": blocking_reasons,
        "cycle_path": cycle_path,
    }


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    """Return a cycle path if the graph contains one, else None.

    Uses iterative DFS with WHITE/GRAY/BLACK coloring.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {node: WHITE for node in graph}
    parent: dict[str, str | None] = {}

    for start in sorted(graph):
        if color[start] != WHITE:
            continue
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            node, processed = stack.pop()
            if processed:
                color[node] = BLACK
                continue
            if color[node] == GRAY:
                color[node] = BLACK
                continue
            color[node] = GRAY
            stack.append((node, True))
            for neighbor in sorted(graph.get(node, set())):
                if color.get(neighbor, WHITE) == GRAY:
                    path = [neighbor, node]
                    current = node
                    while current != neighbor:
                        current = parent.get(current, "")
                        if not current:
                            break
                        path.append(current)
                    path.reverse()
                    return path
                if color.get(neighbor, WHITE) == WHITE:
                    parent[neighbor] = node
                    stack.append((neighbor, False))
    return None


def _validate_batch_plan_dependencies(
    batch_plan: BatchPlan,
    spec_dependencies: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate dependency wiring between batches using spec-level dependencies.

    Checks:
    1. All dependency batch IDs exist.
    2. Spec IDs are unique across batches.
    3. For each cross-batch spec dependency, the consumer batch can reach the provider batch.
    """
    checks: list[str] = []
    reasons: list[str] = []
    batches = [b for b in batch_plan.get("batches", []) if isinstance(b, dict)]
    by_id = {
        str(batch.get("batch_id", "")): batch
        for batch in batches
        if str(batch.get("batch_id", "")).strip()
    }

    # Check 1: dependency IDs exist
    missing_dep_refs: list[str] = []
    for batch in batches:
        batch_id = str(batch.get("batch_id", "")).strip()
        for dep in [str(d) for d in batch.get("depends_on_batches", [])]:
            if dep not in by_id:
                missing_dep_refs.append(f"{batch_id}->{dep}")
    if missing_dep_refs:
        reasons.append(
            "Batch plan references unknown dependency batch IDs: "
            + ", ".join(sorted(missing_dep_refs))
        )
    else:
        checks.append("dependency_ids_exist")

    # Check 2: spec_ids unique across batches
    assigned_specs: list[str] = []
    spec_to_batch: dict[str, str] = {}
    for batch in batches:
        batch_id = str(batch.get("batch_id", ""))
        for sid in batch.get("spec_ids", []):
            s = str(sid).strip()
            if s:
                assigned_specs.append(s)
                spec_to_batch[s] = batch_id

    counts = Counter(assigned_specs)
    duplicates = sorted(sid for sid, c in counts.items() if c > 1)
    if duplicates:
        reasons.append("Spec IDs assigned to multiple batches: " + ", ".join(duplicates))
    else:
        checks.append("spec_ids_unique_across_batches")

    # Check 3: provider dependency paths exist
    reachable_cache: dict[str, set[str]] = {}

    def reachable(batch_id: str) -> set[str]:
        if batch_id in reachable_cache:
            return reachable_cache[batch_id]
        seen: set[str] = set()
        stack = [batch_id]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            current_batch = by_id.get(current, {})
            for dep in [str(d) for d in current_batch.get("depends_on_batches", [])]:
                if dep and dep not in seen:
                    stack.append(dep)
        reachable_cache[batch_id] = seen
        return seen

    missing_paths: list[str] = []
    for dep_entry in spec_dependencies:
        if not isinstance(dep_entry, dict):
            continue
        consumer = str(dep_entry.get("consumer_spec_id", "")).strip()
        providers = dep_entry.get("provider_spec_ids", [])
        if not consumer or not isinstance(providers, list):
            continue
        consumer_batch = spec_to_batch.get(consumer)
        if not consumer_batch:
            continue
        for provider_spec in providers:
            pid = str(provider_spec).strip()
            provider_batch = spec_to_batch.get(pid)
            if not provider_batch or provider_batch == consumer_batch:
                continue
            if provider_batch not in reachable(consumer_batch):
                missing_paths.append(
                    f"{consumer_batch}({consumer}) missing path to "
                    f"{provider_batch}({pid})"
                )

    if missing_paths:
        reasons.append(
            "Missing provider dependency paths: "
            + "; ".join(sorted(set(missing_paths)))
        )
    else:
        checks.append("provider_dependency_paths_ok")

    return {
        "status": ImplementStatus.PASSED if not reasons else ImplementStatus.FAILED,
        "checks": checks,
        "reasons": reasons,
    }


def _validate_brief_scoping(briefs: list[BatchBrief]) -> dict[str, Any]:
    """Validate that each brief's anchors and contracts are scoped to its batch spec_ids.

    Catches scope leaks where planned_anchors[].spec_ids or
    shared_contracts[].consumed_by_specs reference specs outside the batch.
    """
    checks: list[str] = []
    reasons: list[str] = []
    total_anchor_leaks = 0
    total_contract_leaks = 0
    total_nullable_missing = 0

    for brief in briefs:
        if not isinstance(brief, dict):
            continue
        batch_id = str(brief.get("batch_id", ""))
        batch_specs = {
            str(r.get("spec_id", "")).strip()
            for r in brief.get("spec_rows", [])
            if isinstance(r, dict) and str(r.get("spec_id", "")).strip()
        }
        if not batch_specs:
            continue

        for anchor in brief.get("planned_anchors", []):
            if not isinstance(anchor, dict):
                continue
            anchor_specs = {str(s).strip() for s in anchor.get("spec_ids", []) if str(s).strip()}
            leaked = anchor_specs - batch_specs
            if leaked:
                total_anchor_leaks += len(leaked)

        for contract in brief.get("shared_contracts", []):
            if not isinstance(contract, dict):
                continue
            consumed = {str(s).strip() for s in contract.get("consumed_by_specs", []) if str(s).strip()}
            leaked = consumed - batch_specs
            if leaked:
                total_contract_leaks += len(leaked)
            for field in contract.get("fields") or []:
                if not isinstance(field, dict):
                    continue
                name = str(field.get("name", "")).strip()
                if name and not isinstance(field.get("nullable"), bool):
                    total_nullable_missing += 1

    if total_anchor_leaks:
        reasons.append(
            f"planned_anchors contain {total_anchor_leaks} spec_id refs outside their batch scope"
        )
    else:
        checks.append("anchor_spec_ids_batch_scoped")

    if total_contract_leaks:
        reasons.append(
            f"shared_contracts contain {total_contract_leaks} consumed_by_specs refs outside their batch scope"
        )
    else:
        checks.append("contract_consumed_by_specs_batch_scoped")

    if total_nullable_missing:
        reasons.append(
            f"batch briefs contain {total_nullable_missing} contract field(s) missing nullable boolean"
        )
    else:
        checks.append("contract_fields_have_nullable")

    return {
        "status": ImplementStatus.PASSED if not reasons else ImplementStatus.FAILED,
        "checks": checks,
        "reasons": reasons,
    }


def _extract_words(text: str) -> set[str]:
    """Extract candidate words from free text for fuzzy field-name comparison."""
    if not text or not isinstance(text, str):
        return set()
    return {str(t).strip() for t in _WORD_TOKEN_PATTERN.findall(text) if str(t).strip()}


def _split_word_parts(word: str) -> list[str]:
    """Split word into comparable parts: camelCase + dash/underscore delimiters."""
    if not word:
        return []
    parts: list[str] = []
    for chunk in _WORD_SPLIT_PATTERN.split(str(word).strip()):
        if not chunk:
            continue
        camel_parts = _CAMEL_PART_PATTERN.findall(chunk)
        if camel_parts:
            parts.extend(p.lower() for p in camel_parts if p)
        else:
            parts.append(chunk.lower())
    return parts


def _normalize_word_for_distance(word: str) -> str:
    """Normalize a word by splitting, sorting parts alphabetically, then joining."""
    parts = _split_word_parts(word)
    if not parts:
        return ""
    return "".join(sorted(parts))


def _damerau_levenshtein_distance(a: str, b: str) -> int:
    """Return Damerau-Levenshtein distance (adjacent transpositions allowed)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    len_a = len(a)
    len_b = len(b)
    d = [[0] * (len_b + 1) for _ in range(len_a + 1)]
    for i in range(len_a + 1):
        d[i][0] = i
    for j in range(len_b + 1):
        d[0][j] = j

    for i in range(1, len_a + 1):
        for j in range(1, len_b + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(
                d[i - 1][j] + 1,      # deletion
                d[i][j - 1] + 1,      # insertion
                d[i - 1][j - 1] + cost,  # substitution
            )
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + cost)  # transposition
    return d[len_a][len_b]


def _match_sort_key(row: dict[str, Any]) -> tuple[float, int, str, str]:
    """Deterministic ordering key for match candidates/results."""
    return (
        -float(row.get("score", -1.0)),
        int(row.get("distance", 9999)),
        str(row.get("source_word", "")),
        str(row.get("target_word", "")),
    )


def _build_high_match_row(
    source_word: str,
    target_word: str,
    *,
    score_threshold: float,
) -> dict[str, Any] | None:
    """Build a high-match row for a source/target pair when score passes threshold."""
    source = str(source_word).strip().lower()
    target = str(target_word).strip().lower()
    if not source or not target or source == target:
        return None
    norm_source = _normalize_word_for_distance(source)
    norm_target = _normalize_word_for_distance(target)
    if not norm_source or not norm_target:
        return None
    distance = _damerau_levenshtein_distance(norm_source, norm_target)
    max_len = max(len(norm_source), len(norm_target), 1)
    score = 1.0 - (float(distance) / float(max_len))
    if score < score_threshold:
        return None
    return {
        "source_word": source,
        "target_word": target,
        "distance": distance,
        "score": score,
    }


def _global_high_matches_one_to_one(
    source_words: set[str],
    target_words: set[str],
    *,
    score_threshold: float,
    reserved_source_words: set[str] | None = None,
    reserved_target_words: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return globally pruned high matches with one-to-one source/target assignment.

    Matching is deterministic and greedy by strongest pair rank across all
    candidates. A source and target can each appear at most once. Reserved
    words are excluded from matching (used to protect exact token matches).
    """
    reserved_sources = {
        str(v).strip().lower()
        for v in (reserved_source_words or set())
        if str(v).strip()
    }
    reserved_targets = {
        str(v).strip().lower()
        for v in (reserved_target_words or set())
        if str(v).strip()
    }
    sources = [
        str(s).strip().lower()
        for s in sorted(source_words)
        if str(s).strip() and str(s).strip().lower() not in reserved_sources
    ]
    targets = [
        str(t).strip().lower()
        for t in sorted(target_words)
        if str(t).strip() and str(t).strip().lower() not in reserved_targets
    ]

    candidates: list[dict[str, Any]] = []
    for source in sources:
        for target in targets:
            row = _build_high_match_row(source, target, score_threshold=score_threshold)
            if row is not None:
                candidates.append(row)

    selected: list[dict[str, Any]] = []
    used_sources: set[str] = set()
    used_targets: set[str] = set()
    for row in sorted(candidates, key=_match_sort_key):
        source = str(row.get("source_word", "")).strip().lower()
        target = str(row.get("target_word", "")).strip().lower()
        if not source or not target:
            continue
        if source in used_sources or target in used_targets:
            continue
        selected.append(row)
        used_sources.add(source)
        used_targets.add(target)

    return sorted(selected, key=_match_sort_key)


def _format_high_match_pairs(rows: list[dict[str, Any]]) -> str:
    """Format high-match rows for deterministic question text."""
    if not rows:
        return "[]"
    ordered = sorted(rows, key=_match_sort_key)
    parts = [
        f"{r['source_word']} ~ {r['target_word']} (score={float(r['score']):.3f})"
        for r in ordered
    ]
    return "[" + "; ".join(parts) + "]"


def _safe_item_token(value: str) -> str:
    """Return item-id-safe token segment."""
    cleaned = _SAFE_TOKEN_PATTERN.sub("_", str(value).strip().lower()).strip("_")
    return cleaned or "word"


def _validate_contract_field_consistency(
    shared_contracts: list[dict[str, Any]],
    spec_rows: list[dict[str, Any]],
    headers: list[str],
    *,
    resolutions: list[dict[str, Any]] | None = None,
    match_score_threshold: float = 0.80,
) -> dict[str, Any]:
    """Validate that shared_contract field names match spec text for all consumed specs.

    Checks two mismatch directions using configurable normalized score threshold:
    1. Consumer near-miss: spec words with high Damerau-Levenshtein match to
       contract fields, but not exact same word.
    2. Provider deviation: contract fields missing from defining spec exact words,
       but with high-score matches to spec words.

    High-match candidate selection uses global one-to-one pruning:
    - each source token can match at most one target token;
    - each target token can match at most one source token;
    - exact source/target token matches are reserved and excluded from fuzzy
      candidate selection, preventing overshadow false positives.

    Provider spec is identified as the spec in consumed_by_specs whose module_tag equals
    the contract's owning_module.

    Resolution entries are ignored for mismatch computation. Users must edit
    specs and re-run; this validator always recomputes current mismatches from
    spec text and shared contracts.
    """
    _ = resolutions
    match_score_threshold = max(0.0, min(1.0, float(match_score_threshold)))
    req_col = _find_col(headers, "requirement")
    ac_col = _find_col(headers, "acceptance_criteria")
    spec_id_col = _find_col(headers, "spec_id")
    module_col = _find_col(headers, "module_tag")
    if not spec_id_col or not module_col:
        return {
            "status": ImplementStatus.PASSED,
            "manual_resolution_items": [],
            "reasons": [],
            "shared_contracts": [dict(c) for c in shared_contracts if isinstance(c, dict)],
        }

    contracts = [dict(c) for c in shared_contracts]
    spec_by_id: dict[str, dict[str, Any]] = {}
    for row in spec_rows:
        if not isinstance(row, dict):
            continue
        sid = str(row.get(spec_id_col, "")).strip()
        if not sid:
            continue
        req = str(row.get(req_col or "requirement", "") or "")
        ac = str(row.get(ac_col or "acceptance_criteria", "") or "")
        mod = str(row.get(module_col, "")).strip()
        spec_by_id[sid] = {"module_tag": mod, "text": f"{req} {ac}"}

    items: list[dict[str, Any]] = []
    reasons: list[str] = []

    # Structural metadata pre-pass: check nullable presence and duplicate field names.
    for contract in contracts:
        if not isinstance(contract, dict):
            continue
        contract_id = str(contract.get("contract_id", "")).strip()
        if not contract_id:
            continue
        fields_list = contract.get("fields") or []
        if not isinstance(fields_list, list):
            continue
        seen_names: dict[str, int] = {}
        for idx, field in enumerate(fields_list):
            if not isinstance(field, dict):
                continue
            name = str(field.get("name", "")).strip()
            type_name = str(field.get("type_name", "")).strip()
            if not name or not type_name:
                continue
            if name in seen_names:
                item_id = f"duplicate_field_{contract_id}_{name}"
                items.append({
                    "item_id": item_id,
                    "title": f"Duplicate field name in contract {contract_id}: {name!r}",
                    "question": (
                        f"Contract {contract_id} declares field {name!r} more than once "
                        f"(first at index {seen_names[name]}, again at index {idx}). "
                        "Remove the duplicate field declaration."
                    ),
                    "resolution_mode": "edit_contract",
                    "options": [],
                    "required": True,
                    "blocking_reason": f"Duplicate field name {name!r} in contract {contract_id}.",
                })
                reasons.append(f"Contract {contract_id} has duplicate field name {name!r}")
            else:
                seen_names[name] = idx
            nullable = field.get("nullable")
            if not isinstance(nullable, bool):
                item_id = f"missing_nullable_{contract_id}_{name}"
                items.append({
                    "item_id": item_id,
                    "title": f"Missing nullable on {contract_id}.{name}",
                    "question": (
                        f"Field {name!r} in contract {contract_id} is missing the required `nullable` "
                        "boolean. Add `nullable: true` or `nullable: false` to the field declaration."
                    ),
                    "resolution_mode": "edit_contract",
                    "options": [],
                    "required": True,
                    "blocking_reason": f"Field {name!r} in contract {contract_id} has no nullable boolean.",
                })
                reasons.append(f"Contract {contract_id} field {name!r} missing nullable boolean")

    for contract in contracts:
        if not isinstance(contract, dict):
            continue
        contract_id = str(contract.get("contract_id", "")).strip()
        if not contract_id:
            continue
        owning_module = str(contract.get("owning_module", "")).strip()
        consumed = [
            str(s).strip()
            for s in contract.get("consumed_by_specs", [])
            if str(s).strip()
        ]
        fields_list = contract.get("fields") or []
        contract_fields = {
            str(f.get("name", "")).strip().lower()
            for f in fields_list
            if isinstance(f, dict) and str(f.get("name", "")).strip()
        }
        if not contract_fields:
            continue

        provider_spec_id: str | None = None
        for sid in consumed:
            spec_info = spec_by_id.get(sid)
            if spec_info and spec_info.get("module_tag") == owning_module:
                provider_spec_id = sid
                break

        for spec_id in consumed:
            spec_info = spec_by_id.get(spec_id)
            if not spec_info:
                continue
            text = spec_info.get("text", "")
            spec_words = {w.lower() for w in _extract_words(text)}

            is_provider = spec_id == provider_spec_id

            exact_matches = spec_words & contract_fields

            # Consumer check: emit globally pruned high-score fuzzy matches only.
            consumer_matches = _global_high_matches_one_to_one(
                spec_words,
                contract_fields,
                score_threshold=match_score_threshold,
                reserved_source_words=exact_matches,
                reserved_target_words=exact_matches,
            )

            for match in sorted(
                consumer_matches,
                key=_match_sort_key,
            ):
                token = str(match.get("source_word", "")).strip()
                target = str(match.get("target_word", "")).strip()
                distance = int(match.get("distance", 0))
                score = float(match.get("score", 0.0))
                item_id = (
                    f"field_mismatch_{contract_id}_{spec_id}_{_safe_item_token(token)}"
                )
                pairs_text = _format_high_match_pairs([match])
                items.append({
                    "item_id": item_id,
                    "title": f"Contract field mismatch: {contract_id} vs spec {spec_id}",
                    "question": (
                        f"Spec {spec_id} has high-match word pair(s) {pairs_text} against contract "
                        f"{contract_id} (score_threshold={match_score_threshold:.3f}). "
                        "If this is a real field mismatch, edit the spec to align field names."
                    ),
                    "resolution_mode": "edit_spec",
                    "options": [],
                    "required": True,
                    "blocking_reason": (
                        f"Word '{token}' in spec {spec_id} is highly matched to contract field "
                        f"'{target}' (score={score:.3f}, distance={distance})."
                    ),
                })
                reasons.append(
                    f"Spec {spec_id} word '{token}' highly matches contract field '{target}' "
                    f"(score={score:.3f}, distance={distance}, score_threshold={match_score_threshold:.3f})"
                )

            # Tie-detection: for each non-exact field, find all candidates and
            # check for near-equal scores (ambiguity that needs human clarification).
            for field_name in contract_fields:
                if field_name in exact_matches:
                    continue
                candidates: list[dict[str, Any]] = []
                for source_word in spec_words:
                    row = _build_high_match_row(
                        source_word,
                        field_name,
                        score_threshold=match_score_threshold,
                    )
                    if row is not None:
                        candidates.append(row)
                candidates_sorted = sorted(candidates, key=_match_sort_key)
                if len(candidates_sorted) < 2:
                    continue
                top = candidates_sorted[0]
                second = candidates_sorted[1]
                score_delta = abs(
                    float(top.get("score", 0.0)) - float(second.get("score", 0.0))
                )
                if score_delta > _AMBIGUITY_TIE_MARGIN:
                    continue
                tie_item_id = (
                    f"match_ambiguity_{contract_id}_{spec_id}_{_safe_item_token(field_name)}"
                )
                items.append({
                    "item_id": tie_item_id,
                    "title": f"Ambiguous contract field match: {contract_id} / {spec_id}",
                    "question": (
                        f"Spec {spec_id} has near-equal word matches for contract field "
                        f"'{field_name}': {_format_high_match_pairs([top, second])}. "
                        "Edit the spec text to use one unambiguous field name."
                    ),
                    "resolution_mode": "edit_spec",
                    "options": [],
                    "required": True,
                    "blocking_reason": (
                        f"Near-equal candidate words for {field_name} in spec {spec_id} "
                        f"(delta={score_delta:.3f})"
                    ),
                })
                reasons.append(
                    f"Spec {spec_id} has ambiguous high-match candidates for "
                    f"{contract_id}.{field_name}"
                )

            # Provider check: evaluate missing contract fields by high-distance matches.
            if is_provider and provider_spec_id:
                missing_in_spec = sorted(contract_fields - spec_words)
                provider_matches = _global_high_matches_one_to_one(
                    set(missing_in_spec),
                    spec_words,
                    score_threshold=match_score_threshold,
                    reserved_target_words=exact_matches,
                )

                if provider_matches:
                    item_id = f"provider_deviation_{contract_id}_{provider_spec_id}"
                    pairs_text = _format_high_match_pairs(provider_matches)
                    matched_missing = sorted(
                        {str(p.get("source_word", "")).strip() for p in provider_matches if str(p.get("source_word", "")).strip()}
                    )
                    items.append({
                        "item_id": item_id,
                        "title": f"Planner deviation: contract {contract_id} vs defining spec {provider_spec_id}",
                        "question": (
                            f"Contract {contract_id} has highly matched missing field pair(s) {pairs_text} "
                            f"against defining spec {provider_spec_id} "
                            f"(score_threshold={match_score_threshold:.3f}). "
                            f"Matched missing contract fields: {matched_missing}. "
                            "If this is a real deviation, edit the spec to align fields."
                        ),
                        "resolution_mode": "edit_spec",
                        "options": [],
                        "required": True,
                        "blocking_reason": (
                            f"Contract {contract_id} deviates from defining spec {provider_spec_id}."
                        ),
                    })
                    reasons.append(
                        f"Contract {contract_id} has highly matched missing fields "
                        f"{matched_missing} vs provider spec {provider_spec_id} "
                        f"(score_threshold={match_score_threshold:.3f})"
                    )

    return {
        "status": ImplementStatus.PASSED if not items else ImplementStatus.FAILED,
        "manual_resolution_items": items,
        "reasons": reasons,
        "shared_contracts": contracts,
    }



def _spec_words_and_parts(text: str) -> tuple[set[str], set[str], set[str]]:
    """Return exact words, normalized words, and split parts from spec text."""
    raw_words = _extract_words(text)
    words = {w.lower() for w in raw_words}
    normalized_words = {_normalize_word_for_distance(w) for w in raw_words}
    normalized_words.discard("")
    parts: set[str] = set()
    for word in raw_words:
        parts.update(_split_word_parts(word))
    return words, normalized_words, parts


def _field_is_covered_in_spec(field_name: str, spec_text: str) -> bool:
    """Return True if contract field is explicitly or alias-covered in spec text."""
    field = str(field_name).strip().lower()
    if not field:
        return True
    words, normalized_words, parts = _spec_words_and_parts(spec_text)
    if field in words:
        return True
    field_norm = _normalize_word_for_distance(field)
    if field_norm and field_norm in normalized_words:
        return True
    field_parts = [p for p in _split_word_parts(field) if p]
    if field_parts and all(part in parts for part in field_parts):
        return True
    return False


def _spec_text_lookup(
    spec_rows: list[dict[str, Any]],
    headers: list[str],
) -> dict[str, dict[str, Any]]:
    """Return spec_id -> normalized text/context metadata."""
    req_col = _find_col(headers, "requirement")
    ac_col = _find_col(headers, "acceptance_criteria")
    spec_col = _find_col(headers, "spec_id")
    module_col = _find_col(headers, "module_tag")
    if not spec_col:
        return {}

    by_spec: dict[str, dict[str, Any]] = {}
    for row in spec_rows:
        if not isinstance(row, dict):
            continue
        spec_id = str(row.get(spec_col, "")).strip()
        if not spec_id:
            continue
        requirement = str(row.get(req_col or "requirement", "") or "")
        acceptance = str(row.get(ac_col or "acceptance_criteria", "") or "")
        text = f"{requirement} {acceptance}".strip()
        by_spec[spec_id] = {
            "module_tag": str(row.get(module_col or "module_tag", "")).strip(),
            "text": text,
        }
    return by_spec


def _validate_required_field_coverage(
    shared_contracts: list[dict[str, Any]],
    spec_rows: list[dict[str, Any]],
    headers: list[str],
) -> dict[str, Any]:
    """Validate contract field coverage using provider-first, low-noise rules.

    Deterministic policy:
    1) Prefer provider specs (consumed specs in owning_module) as source-of-truth.
    2) If provider text explicitly declares canonical contract/DTO + field naming intent,
       treat provider coverage as satisfied even when every field token is not listed.
    3) If no provider spec exists, emit a manual_resolution_item (always manual_block).
    """
    spec_by_id = _spec_text_lookup(spec_rows, headers)
    reasons: list[str] = []
    checks: list[str] = []
    missing_records: list[dict[str, Any]] = []
    manual_resolution_items: list[dict[str, Any]] = []

    for contract in shared_contracts:
        if not isinstance(contract, dict):
            continue
        contract_id = str(contract.get("contract_id", "")).strip()
        if not contract_id:
            continue
        fields = contract.get("fields", [])
        if not isinstance(fields, list) or not fields:
            continue
        field_names = [
            str(field.get("name", "")).strip()
            for field in fields
            if isinstance(field, dict) and str(field.get("name", "")).strip()
        ]
        if not field_names:
            continue

        consumed_specs = [
            str(spec_id).strip()
            for spec_id in contract.get("consumed_by_specs", [])
            if str(spec_id).strip()
        ]
        owning_module = str(contract.get("owning_module", "")).strip()
        provider_spec_ids = [
            spec_id
            for spec_id in consumed_specs
            if str(spec_by_id.get(spec_id, {}).get("module_tag", "")).strip() == owning_module
        ]
        if not provider_spec_ids:
            manual_resolution_items.append({
                "item_id": f"no_provider_spec_{contract_id}",
                "title": f"No provider spec for contract {contract_id}",
                "question": (
                    f"Contract {contract_id} (owning_module={owning_module!r}) has no provider spec "
                    f"in consumed_by_specs {consumed_specs}. Add a spec owned by "
                    f"{owning_module!r} to consumed_by_specs."
                ),
                "options": [],
                "required": True,
                "blocking_reason": f"No provider spec found for contract {contract_id}.",
            })
            checks.append(f"{contract_id}:manual_block_no_provider_spec")
            continue

        provider_texts = [
            str(spec_by_id.get(spec_id, {}).get("text", ""))
            for spec_id in provider_spec_ids
            if spec_id in spec_by_id
        ]
        canonical_declaration_present = any(
            ("dto" in text.lower() or "contract" in text.lower())
            and "field" in text.lower()
            for text in provider_texts
        )
        if canonical_declaration_present:
            checks.append(f"{contract_id}:provider_declares_canonical_contract")
            continue

        covered_fields: set[str] = set()
        for text in provider_texts:
            for field_name in field_names:
                if _field_is_covered_in_spec(field_name, text):
                    covered_fields.add(field_name)
        missing_fields_sorted = sorted(set(field_names) - covered_fields)
        if not missing_fields_sorted:
            checks.append(f"{contract_id}:provider_fields_covered")
            continue

        missing_records.append(
            {
                "contract_id": contract_id,
                "provider_spec_ids": provider_spec_ids,
                "missing_fields": missing_fields_sorted,
            }
        )
        reasons.append(
            f"Provider spec(s) {provider_spec_ids} do not explicitly/alias-cover required contract "
            f"fields {missing_fields_sorted} for {contract_id}"
        )
        manual_resolution_items.append({
            "item_id": f"uncovered_fields_{contract_id}",
            "title": f"Uncovered fields in contract {contract_id}",
            "question": (
                f"Provider spec(s) {provider_spec_ids} do not cover required fields "
                f"{missing_fields_sorted} for contract {contract_id}. "
                "Edit provider spec text to reference these fields."
            ),
            "options": [],
            "required": True,
            "blocking_reason": (
                f"Required fields {missing_fields_sorted} not covered "
                f"in provider spec(s) {provider_spec_ids}."
            ),
        })

    if not reasons and not manual_resolution_items:
        checks.append("required_contract_fields_covered")
    return {
        "status": (
            ImplementStatus.PASSED
            if not reasons and not manual_resolution_items
            else ImplementStatus.FAILED
        ),
        "checks": checks,
        "reasons": reasons,
        "missing_records": missing_records,
        "manual_resolution_items": manual_resolution_items,
    }



_SPEC_ISSUE_BLOCKING_REASONS: dict[str, str] = {
    "contradiction": "Mutually exclusive behaviors in specs {affected}",
    "overlap": "Overlapping responsibilities in specs {affected}",
    "dependency_gap": "Dependency gap in specs {affected}",
    "ambiguity": "Ambiguous requirement in specs {affected}",
    "orphan_reference": "Orphan reference in specs {affected}",
}


def _escalate_spec_issues(
    spec_issues: list[dict[str, Any]],
    selected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert all spec_issues to blocking manual_resolution_items.

    All 5 issue kinds (contradiction, overlap, dependency_gap, ambiguity,
    orphan_reference) are escalated regardless of cross-module scope.
    For dependency_gap, module detail is included in the blocking_reason.
    """
    spec_id_to_module: dict[str, str] = {}
    for row in selected:
        spec_id = str(row.get("spec_id", "")).strip()
        module_tag = str(row.get("module_tag", "")).strip()
        if spec_id and module_tag:
            spec_id_to_module[spec_id] = module_tag

    items: list[dict[str, Any]] = []
    for issue in spec_issues:
        kind = str(issue.get("kind", "")).strip()
        if not kind:
            continue
        affected_ids: list[str] = [
            str(s).strip() for s in issue.get("affected_spec_ids", []) if s
        ]
        affected_str = ", ".join(affected_ids) if affected_ids else "unknown"
        description = str(issue.get("description", "")).strip()
        resolution_hint = str(issue.get("resolution_hint", "")).strip()

        blocking_reason = _SPEC_ISSUE_BLOCKING_REASONS.get(
            kind, f"{kind} in specs {{affected}}"
        ).format(affected=affected_str)

        if kind == "dependency_gap":
            modules = sorted({
                spec_id_to_module[sid]
                for sid in affected_ids
                if sid in spec_id_to_module
            })
            if len(modules) >= 2:
                blocking_reason = (
                    f"Dependency gap spanning modules {modules} in specs {affected_str}"
                )

        item: dict[str, Any] = {
            "item_id": issue.get("issue_id", ""),
            "title": description[:120],
            "question": description,
            "options": [],
            "required": True,
            "blocking_reason": blocking_reason,
            "evidence_refs": affected_ids,
            "resolution_mode": "edit_spec",
        }
        if resolution_hint:
            item["spec_amendment_hints"] = resolution_hint
        items.append(item)
    return items


def _validate_dependency_context_edges(
    briefs: list[BatchBrief],
    spec_dependencies: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate brief dependency-context edges against planner spec_dependencies."""
    expected_edges: set[tuple[str, str]] = set()
    for dep in spec_dependencies:
        if not isinstance(dep, dict):
            continue
        consumer = str(dep.get("consumer_spec_id", "")).strip()
        providers = dep.get("provider_spec_ids", [])
        if not consumer or not isinstance(providers, list):
            continue
        for provider_raw in providers:
            provider = str(provider_raw).strip()
            if provider:
                expected_edges.add((consumer, provider))

    observed_edges: set[tuple[str, str]] = set()
    reasons: list[str] = []
    checks: list[str] = []

    for brief in briefs:
        if not isinstance(brief, dict):
            continue
        batch_id = str(brief.get("batch_id", "")).strip()
        for dep in brief.get("spec_dependency_context", []):
            if not isinstance(dep, dict):
                continue
            consumer = str(dep.get("consumer_spec_id", "")).strip()
            providers = dep.get("provider_spec_ids", [])
            if not consumer or not isinstance(providers, list):
                continue
            for provider_raw in providers:
                provider = str(provider_raw).strip()
                if not provider:
                    continue
                edge = (consumer, provider)
                observed_edges.add(edge)
                if edge not in expected_edges:
                    reasons.append(
                        f"Batch {batch_id} contains unknown dependency-context edge {consumer}->{provider}"
                    )

    missing_edges = sorted(expected_edges - observed_edges)
    if missing_edges:
        reasons.append(
            "Missing dependency-context edges: "
            + ", ".join(f"{consumer}->{provider}" for consumer, provider in missing_edges)
        )

    if not reasons:
        checks.append("dependency_context_edges_match_planner")
    return {
        "status": ImplementStatus.PASSED if not reasons else ImplementStatus.FAILED,
        "checks": checks,
        "reasons": reasons,
        "missing_edges": [
            {"consumer_spec_id": consumer, "provider_spec_id": provider}
            for consumer, provider in missing_edges
        ],
    }
