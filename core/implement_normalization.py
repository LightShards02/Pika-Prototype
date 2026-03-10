"""Deterministic normalization and matching helpers for implement planning/linking."""

from __future__ import annotations

import copy
import re
from typing import Any

_HTTP_METHOD_PREFIX_RE = re.compile(r"^(get|post|put|patch|delete)_api_", re.IGNORECASE)
_INTERNAL_API_ROUTE_RE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE)\s+/api/", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_CAMEL_ACRONYM_BOUNDARY_RE = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_CAMEL_WORD_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_DEPENDENCY_INTENT_RE = re.compile(
    r"^dep[._](?P<target>[A-Za-z0-9]+)[._](?P<name>.+)$",
    re.IGNORECASE,
)
_GENERIC_TOKENS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "this",
    "that",
    "intent",
    "required",
    "provided",
    "interface",
    "service",
    "module",
    "workflow",
    "handler",
    "endpoint",
    "dep",
    "req",
    "ui",
    "api",
    "core",
    "data",
    "obs",
    "shared",
    "provider",
    "request",
    "response",
    "boundary",
}
_TOKEN_ALIASES = {
    "metrics": "metric",
    "calories": "calorie",
    "macros": "macro",
}
_SCORE_RESCALE_DENOMINATOR = 0.45


def normalize_anchor_plan_kinds(
    anchor_plans: dict[str, dict[str, Any]],
    module_catalog: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Normalize intent kinds to reduce false-positive policy violations.

    Rule implemented:
    - For `frontend` modules only, rewrite required intent kind `external_api`
      to `api_endpoint` when the intent clearly targets an internal API route.
    """
    normalized = copy.deepcopy(anchor_plans)
    events: list[dict[str, Any]] = []
    roles = _module_roles(module_catalog)
    has_api_module = any(role == "api" for role in roles.values())
    if not has_api_module:
        return normalized, events

    for module_tag, plan in normalized.items():
        if roles.get(module_tag) != "frontend":
            continue
        required_intents = plan.get("required_intents", [])
        if not isinstance(required_intents, list):
            continue
        for intent in required_intents:
            if not isinstance(intent, dict):
                continue
            current_kind = str(intent.get("kind", "")).strip()
            if current_kind != "external_api":
                continue
            if not _is_internal_api_intent(intent):
                continue
            intent["kind"] = "api_endpoint"
            events.append(
                {
                    "event_type": "kind_rewrite",
                    "module_tag": module_tag,
                    "intent_local_id": str(intent.get("intent_local_id", "")),
                    "from_kind": "external_api",
                    "to_kind": "api_endpoint",
                    "reason": "frontend_internal_api_route",
                }
            )
    return normalized, events


def enforce_leaf_dependency_policy(
    anchor_plans: dict[str, dict[str, Any]],
    module_catalog: dict[str, Any],
    leaf_dependency_roles: set[str],
    track_external_dependencies: bool,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Apply leaf dependency policy by auto-dropping required intents for leaf roles.

    For modules with roles in `leaf_dependency_roles`:
    - move required intents into `declared_external_dependencies` (when enabled),
    - clear required intents to avoid false unbound-link obligations.
    """
    normalized = copy.deepcopy(anchor_plans)
    events: list[dict[str, Any]] = []
    roles = _module_roles(module_catalog)
    if not leaf_dependency_roles:
        return normalized, events

    for module_tag, plan in normalized.items():
        role = roles.get(module_tag)
        if role not in leaf_dependency_roles:
            continue
        required_intents = plan.get("required_intents", [])
        if not isinstance(required_intents, list) or not required_intents:
            continue

        moved: list[dict[str, Any]] = []
        for idx, intent in enumerate(
            sorted(
                (i for i in required_intents if isinstance(i, dict)),
                key=lambda item: str(item.get("intent_local_id", "")),
            ),
            start=1,
        ):
            moved.append(_to_declared_external_dependency(module_tag, idx, intent))

        if track_external_dependencies:
            existing = plan.get("declared_external_dependencies", [])
            if not isinstance(existing, list):
                existing = []
            plan["declared_external_dependencies"] = existing + moved

        plan["required_intents"] = []
        events.append(
            {
                "event_type": "leaf_required_intents_auto_dropped",
                "module_tag": module_tag,
                "module_role": role,
                "dropped_count": len(moved),
                "tracked_external_dependencies": bool(track_external_dependencies),
            }
        )
    return normalized, events


def build_intent_fingerprint(intent: dict[str, Any]) -> dict[str, Any]:
    """Build deterministic fingerprint fields for an intent."""
    capability_tokens = _tokenize(
        f"{intent.get('capability_name', '')} {intent.get('description', '')}"
    )
    inputs = intent.get("inputs", [])
    outputs = intent.get("outputs", [])
    errors = intent.get("error_modes", [])
    return {
        "capability_tokens": sorted(capability_tokens),
        "input_tokens": sorted(_io_tokens(inputs)),
        "output_tokens": sorted(_io_tokens(outputs)),
        "error_tokens": sorted(_tokenize(" ".join(str(v) for v in errors if isinstance(v, str)))),
        "input_count": len(inputs) if isinstance(inputs, list) else 0,
        "output_count": len(outputs) if isinstance(outputs, list) else 0,
    }


def score_intent_candidates(
    required_intent: dict[str, Any],
    provided_intent: dict[str, Any],
    *,
    required_module_tag: str = "",
    provided_module_tag: str = "",
) -> dict[str, Any]:
    """Score required->provided compatibility for deterministic hinting."""
    req_fp = build_intent_fingerprint(required_intent)
    prov_fp = build_intent_fingerprint(provided_intent)

    capability_similarity = _jaccard(
        set(req_fp["capability_tokens"]), set(prov_fp["capability_tokens"])
    )
    input_similarity = _jaccard(set(req_fp["input_tokens"]), set(prov_fp["input_tokens"]))
    output_similarity = _jaccard(set(req_fp["output_tokens"]), set(prov_fp["output_tokens"]))
    count_similarity = _count_similarity(
        req_fp["input_count"],
        prov_fp["input_count"],
        req_fp["output_count"],
        prov_fp["output_count"],
    )
    io_similarity = (0.35 * input_similarity) + (0.45 * output_similarity) + (0.20 * count_similarity)
    error_similarity = _jaccard(set(req_fp["error_tokens"]), set(prov_fp["error_tokens"]))
    intent_local_similarity = _jaccard(
        _tokenize(str(required_intent.get("intent_local_id", ""))),
        _tokenize(str(provided_intent.get("intent_local_id", ""))),
    )
    module_affinity_similarity = _module_affinity_similarity(
        required_intent,
        required_module_tag,
        provided_module_tag,
    )
    module_affinity_penalty = _module_affinity_penalty(
        required_intent,
        required_module_tag,
        provided_module_tag,
    )
    spec_overlap_similarity = _jaccard(
        _spec_id_set(required_intent.get("spec_ids", [])),
        _spec_id_set(provided_intent.get("spec_ids", [])),
    )

    raw_score = (
        (0.22 * capability_similarity)
        + (0.22 * io_similarity)
        + (0.10 * error_similarity)
        + (0.28 * intent_local_similarity)
        + (0.18 * module_affinity_similarity)
    )
    pre_rescale_score = max(0.0, min(1.0, raw_score - module_affinity_penalty))
    score = _rescale_score(pre_rescale_score)

    req_input_types = _io_type_names(required_intent.get("inputs", []))
    prov_input_types = _io_type_names(provided_intent.get("inputs", []))
    req_output_types = _io_type_names(required_intent.get("outputs", []))
    prov_output_types = _io_type_names(provided_intent.get("outputs", []))
    adapter_needed = (req_input_types != prov_input_types) or (req_output_types != prov_output_types)
    return {
        "score": round(score, 4),
        "score_breakdown": {
            "capability_similarity": round(capability_similarity, 4),
            "io_similarity": round(io_similarity, 4),
            "error_mode_similarity": round(error_similarity, 4),
            "intent_local_id_similarity": round(intent_local_similarity, 4),
            "module_affinity_similarity": round(module_affinity_similarity, 4),
            "module_affinity_penalty": round(module_affinity_penalty, 4),
            "raw_score": round(raw_score, 4),
            "pre_rescale_score": round(pre_rescale_score, 4),
            "spec_overlap_similarity": round(spec_overlap_similarity, 4),
        },
        "adapter_needed": adapter_needed,
    }


def build_adapter_template(
    required_ref: dict[str, str],
    provided_ref: dict[str, str],
    required_intent: dict[str, Any],
    provided_intent: dict[str, Any],
) -> dict[str, Any]:
    """Build deterministic adapter plan scaffold for shape mismatch bridging."""
    req_inputs = _io_names(required_intent.get("inputs", []))
    prov_inputs = _io_names(provided_intent.get("inputs", []))
    req_outputs = _io_names(required_intent.get("outputs", []))
    prov_outputs = _io_names(provided_intent.get("outputs", []))
    return {
        "kind": "shape_adapter",
        "required_ref": {
            "module_tag": str(required_ref.get("module_tag", "")),
            "intent_local_id": str(required_ref.get("intent_local_id", "")),
        },
        "provided_ref": {
            "module_tag": str(provided_ref.get("module_tag", "")),
            "intent_local_id": str(provided_ref.get("intent_local_id", "")),
        },
        "input_field_mappings": _pair_fields(req_inputs, prov_inputs),
        "output_field_mappings": _pair_fields(req_outputs, prov_outputs),
        "notes": [
            "Map required input/output shapes to provider shapes using deterministic field transforms.",
            "Preserve provider error modes and map them to required intent error modes explicitly.",
        ],
    }


def build_normalized_intent_catalog(
    anchor_plans: dict[str, dict[str, Any]],
    module_catalog: dict[str, Any],
    min_auto_bind_score: float,
    tie_margin: float,
) -> dict[str, Any]:
    """Build deterministic required->provided candidate rankings and auto-bind hints."""
    providers = _collect_providers(anchor_plans)
    rankings: list[dict[str, Any]] = []

    for module_tag, plan in sorted(anchor_plans.items()):
        required_intents = plan.get("required_intents", [])
        if not isinstance(required_intents, list):
            continue
        for req_intent in required_intents:
            if not isinstance(req_intent, dict):
                continue
            req_ref = {
                "module_tag": module_tag,
                "intent_local_id": str(req_intent.get("intent_local_id", "")).strip(),
            }
            req_kind = str(req_intent.get("kind", "")).strip()
            if not req_ref["intent_local_id"]:
                continue
            candidates = []
            for provider in providers:
                prov_intent = provider["intent"]
                prov_kind = str(prov_intent.get("kind", "")).strip()
                if req_kind and prov_kind and req_kind != prov_kind:
                    continue
                score_info = score_intent_candidates(
                    req_intent,
                    prov_intent,
                    required_module_tag=module_tag,
                    provided_module_tag=str(provider["provided_ref"].get("module_tag", "")),
                )
                candidate = {
                    "provided_ref": provider["provided_ref"],
                    "score": score_info["score"],
                    "score_breakdown": score_info["score_breakdown"],
                    "adapter_needed": score_info["adapter_needed"],
                }
                if score_info["adapter_needed"]:
                    candidate["adapter_plan"] = build_adapter_template(
                        req_ref,
                        provider["provided_ref"],
                        req_intent,
                        prov_intent,
                    )
                candidates.append(candidate)

            candidates.sort(
                key=lambda item: (
                    -float(item.get("score", 0.0)),
                    str(item["provided_ref"].get("module_tag", "")),
                    str(item["provided_ref"].get("intent_local_id", "")),
                )
            )
            top_score = float(candidates[0]["score"]) if candidates else 0.0
            second_score = float(candidates[1]["score"]) if len(candidates) > 1 else 0.0
            auto_bind_candidate = None
            if candidates and top_score >= min_auto_bind_score and (top_score - second_score) >= tie_margin:
                auto_bind_candidate = candidates[0]

            rankings.append(
                {
                    "required_ref": req_ref,
                    "required_kind": req_kind,
                    "candidates": candidates,
                    "auto_bind_candidate": auto_bind_candidate,
                }
            )

    return {
        "metadata": {
            "min_auto_bind_score": round(min_auto_bind_score, 4),
            "tie_margin": round(tie_margin, 4),
            "module_count": len(module_catalog.get("modules", []))
            if isinstance(module_catalog.get("modules", []), list)
            else 0,
            "ranking_count": len(rankings),
        },
        "required_to_provided_rankings": rankings,
    }


def normalize_for_linking(
    anchor_plans: dict[str, dict[str, Any]],
    module_catalog: dict[str, Any],
    *,
    leaf_dependency_roles: set[str],
    track_external_dependencies: bool,
    min_auto_bind_score: float,
    tie_margin: float,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Run all deterministic pre-link normalization stages and return artifacts."""
    after_kind, kind_events = normalize_anchor_plan_kinds(anchor_plans, module_catalog)
    after_leaf, leaf_events = enforce_leaf_dependency_policy(
        after_kind,
        module_catalog,
        leaf_dependency_roles=leaf_dependency_roles,
        track_external_dependencies=track_external_dependencies,
    )
    catalog = build_normalized_intent_catalog(
        after_leaf,
        module_catalog,
        min_auto_bind_score=min_auto_bind_score,
        tie_margin=tie_margin,
    )
    report = {
        "events": kind_events + leaf_events,
        "counts": {
            "kind_rewrites": sum(1 for item in kind_events if item.get("event_type") == "kind_rewrite"),
            "leaf_auto_drop_events": sum(
                1 for item in leaf_events if item.get("event_type") == "leaf_required_intents_auto_dropped"
            ),
        },
    }
    return after_leaf, report, catalog


def _module_roles(module_catalog: dict[str, Any]) -> dict[str, str]:
    """Return module_tag -> module_role mapping from module catalog."""
    roles: dict[str, str] = {}
    modules = module_catalog.get("modules", [])
    if not isinstance(modules, list):
        return roles
    for module in modules:
        if not isinstance(module, dict):
            continue
        module_tag = str(module.get("module_tag", "")).strip()
        module_role = str(module.get("module_role", "")).strip().lower()
        if module_tag:
            roles[module_tag] = module_role
    return roles


def _is_internal_api_intent(intent: dict[str, Any]) -> bool:
    """Return True when an intent looks like an internal project API call."""
    capability_name = str(intent.get("capability_name", "")).strip()
    if _HTTP_METHOD_PREFIX_RE.search(capability_name):
        return True
    for item in intent.get("inputs", []) or []:
        if not isinstance(item, dict):
            continue
        if _INTERNAL_API_ROUTE_RE.search(str(item.get("type_name", "")).strip()):
            return True
    for item in intent.get("outputs", []) or []:
        if not isinstance(item, dict):
            continue
        if _INTERNAL_API_ROUTE_RE.search(str(item.get("type_name", "")).strip()):
            return True
    return False


def _to_declared_external_dependency(
    module_tag: str,
    index: int,
    intent: dict[str, Any],
) -> dict[str, Any]:
    """Convert required intent into non-linking declared external dependency shape."""
    local_id = str(intent.get("intent_local_id", "")).strip() or f"required_intent_{index:03d}"
    return {
        "dependency_id": f"{module_tag}_dep_{index:03d}",
        "source_intent_local_id": local_id,
        "kind": str(intent.get("kind", "")).strip(),
        "capability_name": str(intent.get("capability_name", "")).strip(),
        "description": str(intent.get("description", "")).strip(),
        "spec_ids": sorted(_spec_id_set(intent.get("spec_ids", []))),
        "confidence": float(intent.get("confidence", 0.0))
        if isinstance(intent.get("confidence"), (int, float))
        else 0.0,
    }


def _collect_providers(anchor_plans: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect provided intents with refs from all modules."""
    providers: list[dict[str, Any]] = []
    for module_tag, plan in sorted(anchor_plans.items()):
        intents = plan.get("provided_intents", [])
        if not isinstance(intents, list):
            continue
        for intent in intents:
            if not isinstance(intent, dict):
                continue
            local_id = str(intent.get("intent_local_id", "")).strip()
            if not local_id:
                continue
            providers.append(
                {
                    "provided_ref": {
                        "module_tag": module_tag,
                        "intent_local_id": local_id,
                    },
                    "intent": intent,
                }
            )
    return providers


def _tokenize(text: str) -> set[str]:
    """Tokenize text into lower-cased alphanumeric tokens."""
    if not text:
        return set()
    expanded = _CAMEL_ACRONYM_BOUNDARY_RE.sub(" ", text)
    expanded = _CAMEL_WORD_BOUNDARY_RE.sub(" ", expanded)
    tokens: set[str] = set()
    for token in _TOKEN_RE.findall(expanded):
        normalized = token.lower()
        normalized = _TOKEN_ALIASES.get(normalized, normalized)
        if len(normalized) <= 1:
            continue
        if normalized in _GENERIC_TOKENS:
            continue
        tokens.add(normalized)
    return tokens


def _io_tokens(items: Any) -> set[str]:
    """Return IO token set from intent input/output item arrays."""
    if not isinstance(items, list):
        return set()
    tokens: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        tokens.update(_tokenize(str(item.get("name", ""))))
        tokens.update(_tokenize(str(item.get("type_name", ""))))
        constraints = item.get("constraints", [])
        if isinstance(constraints, list):
            for constraint in constraints:
                if isinstance(constraint, str):
                    tokens.update(_tokenize(constraint))
    return tokens


def _spec_id_set(values: Any) -> set[str]:
    """Return normalized spec-id set from arbitrary value."""
    if not isinstance(values, list):
        return set()
    return {str(value).strip() for value in values if str(value).strip()}


def _jaccard(left: set[str], right: set[str]) -> float:
    """Return Jaccard similarity over two token sets."""
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _count_similarity(
    req_input_count: int,
    prov_input_count: int,
    req_output_count: int,
    prov_output_count: int,
) -> float:
    """Return similarity score for IO arity."""
    input_delta = min(abs(req_input_count - prov_input_count), 3)
    output_delta = min(abs(req_output_count - prov_output_count), 3)
    input_score = 1.0 - (input_delta / 3.0)
    output_score = 1.0 - (output_delta / 3.0)
    return (input_score + output_score) / 2.0


def _io_type_names(items: Any) -> list[str]:
    """Return normalized ordered list of IO type_name values."""
    if not isinstance(items, list):
        return []
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("type_name", "")).strip().lower()
        if name:
            names.append(name)
    return names


def _io_names(items: Any) -> list[str]:
    """Return normalized ordered list of IO field names."""
    if not isinstance(items, list):
        return []
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if name:
            names.append(name)
    return names


def _pair_fields(required_fields: list[str], provided_fields: list[str]) -> list[dict[str, str]]:
    """Create deterministic field-pair scaffold by exact-name match then positional fallback."""
    pairs: list[dict[str, str]] = []
    remaining_prov = list(provided_fields)
    for req in required_fields:
        match = next((item for item in remaining_prov if item.lower() == req.lower()), None)
        if match is None and remaining_prov:
            match = remaining_prov[0]
        if match is None:
            pairs.append({"required_field": req, "provided_field": "", "transform": "manual_map"})
            continue
        remaining_prov.remove(match)
        transform = "identity" if match.lower() == req.lower() else "rename_or_transform"
        pairs.append({"required_field": req, "provided_field": match, "transform": transform})
    return pairs


def _extract_dependency_target(intent_local_id: str) -> str:
    """Return dependency target module token from `dep.<target>.*` style IDs."""
    match = _DEPENDENCY_INTENT_RE.match(intent_local_id.strip())
    if match is None:
        return ""
    return match.group("target").strip().lower()


def _module_affinity_similarity(
    required_intent: dict[str, Any],
    required_module_tag: str,
    provided_module_tag: str,
) -> float:
    """Return module-affinity similarity signal from required-intent routing hints."""
    required_id = str(required_intent.get("intent_local_id", "")).strip()
    required_kind = str(required_intent.get("kind", "")).strip().lower()
    provider_module = provided_module_tag.strip().lower()
    target = _extract_dependency_target(required_id)
    if target:
        return 1.0 if provider_module == target else 0.0
    if required_kind == "api_endpoint":
        return 1.0 if provider_module == "api" else 0.0
    return 0.0


def _module_affinity_penalty(
    required_intent: dict[str, Any],
    required_module_tag: str,
    provided_module_tag: str,
) -> float:
    """Return penalty for provider-module choices that conflict with dependency intent target."""
    required_id = str(required_intent.get("intent_local_id", "")).strip()
    target = _extract_dependency_target(required_id)
    if not target:
        return 0.0
    provider_module = provided_module_tag.strip().lower()
    required_module = required_module_tag.strip().lower()
    penalty = 0.0
    if provider_module and provider_module != target:
        penalty += 0.12
    if required_module and target != required_module and provider_module == required_module:
        penalty += 0.10
    return penalty


def _rescale_score(value: float) -> float:
    """Rescale pre-score into confidence range expected by linker thresholding."""
    if value <= 0.0:
        return 0.0
    return min(1.0, value / _SCORE_RESCALE_DENOMINATOR)
