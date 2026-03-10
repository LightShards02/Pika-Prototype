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


def _validate_unified_plan(
    plan: dict[str, Any],
    all_spec_ids: set[str],
    module_catalog: ModuleCatalog,
) -> dict[str, Any]:
    """Validate the unified planner output: spec coverage and DAG acyclicity.

    Checks:
    1. Every spec_id in the workset appears in at least one planned_anchor.
    2. spec_dependencies form a DAG (no cycles).
    3. All spec_ids referenced in spec_dependencies exist in the workset.
    4. Every module in module_catalog has a corresponding module_plan.
    """
    reasons: list[str] = []
    checks: list[str] = []

    module_plans = plan.get("module_plans", [])
    spec_deps = plan.get("spec_dependencies", [])

    # Check 1: spec coverage
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
        reasons.append(f"Specs not covered by any planned_anchor: {', '.join(uncovered)}")
    else:
        checks.append("all_specs_covered")

    # Check 2: DAG acyclicity via DFS
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
        reasons.append(f"Spec dependency cycle detected: {' -> '.join(cycle)}")
    else:
        checks.append("spec_dependencies_acyclic")

    # Check 3: all referenced spec_ids exist in workset
    unknown_refs = sorted(all_referenced - all_spec_ids)
    if unknown_refs:
        reasons.append(f"spec_dependencies reference unknown spec_ids: {', '.join(unknown_refs)}")
    else:
        checks.append("spec_dependency_refs_valid")

    # Check 4: module coverage
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
        reasons.append(f"Modules in catalog but missing from plan: {', '.join(missing_modules)}")
    else:
        checks.append("all_modules_planned")

    return {
        "status": ImplementStatus.PASSED if not reasons else ImplementStatus.FAILED,
        "checks": checks,
        "reasons": reasons,
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
