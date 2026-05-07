"""Implement command configuration parsing and normalization."""

from __future__ import annotations

from typing import Any

from core.constants import ContractKind
from core.errors import ConfigParseError
from core.lifecycle import get_agent_provider
from core.pika_config import get_pika_config


_DEFAULT_ROLES = ("frontend", "api", "domain", "infra", "shared", "cli", "worker")
_DEFAULT_BUDGETS = {
    "max_specs_per_batch": 15,
    "max_files": 10,
    "max_lines_changed": 600,
    "max_parallel_batches": 3,
}
_DEFAULT_TYPE_PLACEMENT = "shared/types"
_DEFAULT_MIN_CONFIDENCE_THRESHOLD = 0.70
_DEFAULT_LEAF_DEPENDENCY_POLICY_MODE = "auto_drop"
_DEFAULT_TRACK_EXTERNAL_DEPENDENCIES = True
_DEFAULT_MIN_AUTO_BIND_SCORE = 0.70
_DEFAULT_TIE_MARGIN = 0.08
_DEFAULT_FIELD_MATCH_SCORE_THRESHOLD = 0.80
_DEFAULT_SEMANTIC_VALIDATION_RETRIES = 2
_DEFAULT_IMPLEMENT_STEP_ENABLED = True
_CONTRACT_KINDS = tuple(ContractKind)
_DEFAULT_DISALLOWED_LINK_KINDS_BY_REQUIRED_ROLE: dict[str, set[str]] = {
    "frontend": {
        ContractKind.SERVICE_INTERFACE,
        ContractKind.EVENT_TOPIC,
        ContractKind.DB_TABLE,
        ContractKind.FILE_FORMAT,
        ContractKind.EXTERNAL_API,
        ContractKind.TEST_SUITE,
    },
    "domain": {ContractKind.EXTERNAL_API},
}
_DEFAULT_CONTRACT_KIND_DEFINITIONS: dict[str, str] = {
    ContractKind.API_ENDPOINT: "Internal project API boundary between project modules.",
    ContractKind.SERVICE_INTERFACE: "Internal callable service boundary inside the project.",
    ContractKind.EVENT_TOPIC: "Asynchronous event stream/topic boundary.",
    ContractKind.DB_TABLE: "Persistent storage table contract boundary.",
    ContractKind.FILE_FORMAT: "Shared serialized file/document schema boundary.",
    ContractKind.EXTERNAL_API: "Out-of-project third-party/system HTTP API boundary only.",
    ContractKind.TEST_SUITE: "Test harness or test provider capability boundary.",
}

_DETERMINISTIC_IMPLEMENT_STEPS_IN_ORDER: tuple[str, ...] = (
    "workset_schema_validation",
    "module_catalog_validation",
    "planner_path_contract_prep",
    "planner_semantic_validation",
    "planner_manual_resolution_gate",
    "spec_issue_escalation",
    "unified_plan_validation",
    "contract_field_consistency_validation",
    "required_field_coverage_validation",
    "batch_plan_construction",
    "batch_plan_dependency_validation",
    "batch_brief_build",
    "batch_brief_scope_validation",
    "dependency_context_edge_validation",
    "batch_runtime_path_contract_prep",
    "implement_semantic_validation",
    "implement_output_structure_validation",
    "patch_constraints_validation",
    "verification_command_resolution",
    "patch_normalization",
    "patch_apply_gate",
    "contract_schema_conformance_check",
    "verification_execution",
)


def _step_cfg(impl: dict[str, Any], step_name: str) -> dict[str, Any]:
    """Return step config object for `implement.<step_name>`, else empty object."""
    raw = impl.get(step_name)
    return raw if isinstance(raw, dict) else {}


def _agent_cfg(impl: dict[str, Any], agent_name: str) -> dict[str, Any]:
    """Return agent config object for `implement.<agent_name>`, else empty object."""
    raw = impl.get(agent_name)
    return raw if isinstance(raw, dict) else {}


def _resolve_step_enabled(step_config: dict[str, Any], default: bool = True) -> bool:
    """Resolve step enabled flag with deterministic default."""
    raw = step_config.get("enabled")
    return raw if isinstance(raw, bool) else bool(default)


def _parse_min_confidence_threshold(value: Any) -> float:
    """Parse min_confidence_threshold. 0 = disabled."""
    if value is None:
        return _DEFAULT_MIN_CONFIDENCE_THRESHOLD
    try:
        v = float(value)
        return max(0.0, min(1.0, v))
    except (TypeError, ValueError):
        return _DEFAULT_MIN_CONFIDENCE_THRESHOLD


def _resolve_min_confidence_threshold(impl: dict[str, Any]) -> float:
    """Resolve min_confidence_threshold: project config > pika config > default 0.7."""
    raw = impl.get("min_confidence_threshold")
    if raw is None:
        raw = get_pika_config().get("commands", {}).get("implement", {}).get("min_confidence_threshold")
    if raw is None:
        raw = _DEFAULT_MIN_CONFIDENCE_THRESHOLD
    return _parse_min_confidence_threshold(raw)


def _normalize_disallowed_link_policy(value: Any) -> dict[str, set[str]]:
    """Return normalized role->disallowed-kind policy with compatibility defaults."""
    if value is None:
        return {
            role: set(kinds)
            for role, kinds in _DEFAULT_DISALLOWED_LINK_KINDS_BY_REQUIRED_ROLE.items()
        }
    if not isinstance(value, dict):
        raise ConfigParseError("implement.disallowed_link_kinds_by_required_role must be an object")
    normalized: dict[str, set[str]] = {}
    known_roles = set(_DEFAULT_ROLES)
    known_kinds = set(_CONTRACT_KINDS)
    for raw_role, raw_kinds in value.items():
        role = str(raw_role).strip().lower()
        if role not in known_roles:
            raise ConfigParseError(
                "implement.disallowed_link_kinds_by_required_role contains unknown role: "
                f"{raw_role}"
            )
        if not isinstance(raw_kinds, list):
            raise ConfigParseError(
                "implement.disallowed_link_kinds_by_required_role entries must be arrays of contract kind strings"
            )
        kinds: set[str] = set()
        for raw_kind in raw_kinds:
            kind = str(raw_kind).strip()
            if kind not in known_kinds:
                raise ConfigParseError(
                    "implement.disallowed_link_kinds_by_required_role contains unknown contract kind "
                    f"'{raw_kind}' for role '{role}'"
                )
            kinds.add(kind)
        if kinds:
            normalized[role] = kinds
    return normalized


def _serialize_disallowed_link_policy(policy: dict[str, set[str]]) -> dict[str, list[str]]:
    """Serialize normalized policy to deterministic JSON-compatible mapping."""
    return {role: sorted(kinds) for role, kinds in sorted(policy.items())}


def _normalize_leaf_dependency_roles(value: Any) -> set[str]:
    """Normalize configured leaf dependency roles to a validated role set."""
    if value is None:
        return set()
    if not isinstance(value, list):
        raise ConfigParseError("implement.leaf_dependency_roles must be an array of role strings")
    normalized: set[str] = set()
    known_roles = set(_DEFAULT_ROLES)
    for raw_role in value:
        role = str(raw_role).strip().lower()
        if not role:
            continue
        if role not in known_roles:
            raise ConfigParseError(f"implement.leaf_dependency_roles contains unknown role: {raw_role}")
        normalized.add(role)
    return normalized


def _normalize_leaf_dependency_policy(value: Any) -> dict[str, Any]:
    """Normalize leaf dependency policy with strict defaults."""
    if value is None:
        return {
            "mode": _DEFAULT_LEAF_DEPENDENCY_POLICY_MODE,
            "track_external_dependencies": _DEFAULT_TRACK_EXTERNAL_DEPENDENCIES,
        }
    if not isinstance(value, dict):
        raise ConfigParseError("implement.leaf_dependency_policy must be an object")
    mode = str(value.get("mode", _DEFAULT_LEAF_DEPENDENCY_POLICY_MODE)).strip().lower()
    if mode != "auto_drop":
        raise ConfigParseError("implement.leaf_dependency_policy.mode must be 'auto_drop'")
    track = value.get("track_external_dependencies", _DEFAULT_TRACK_EXTERNAL_DEPENDENCIES)
    if not isinstance(track, bool):
        raise ConfigParseError(
            "implement.leaf_dependency_policy.track_external_dependencies must be boolean"
        )
    return {"mode": mode, "track_external_dependencies": track}


def _normalize_contract_kind_definitions(value: Any) -> dict[str, str]:
    """Normalize contract kind definitions and fill defaults for missing keys."""
    definitions = dict(_DEFAULT_CONTRACT_KIND_DEFINITIONS)
    if value is None:
        return definitions
    if not isinstance(value, dict):
        raise ConfigParseError("implement.contract_kind_definitions must be an object")
    known_kinds = set(_CONTRACT_KINDS)
    for raw_kind, raw_info in value.items():
        kind = str(raw_kind).strip()
        if kind not in known_kinds:
            raise ConfigParseError(
                f"implement.contract_kind_definitions contains unknown kind: {raw_kind}"
            )
        if not isinstance(raw_info, dict):
            raise ConfigParseError(
                f"implement.contract_kind_definitions.{kind} must be an object with a definition field"
            )
        definition = str(raw_info.get("definition", "")).strip()
        if not definition:
            raise ConfigParseError(
                f"implement.contract_kind_definitions.{kind}.definition must be non-empty"
            )
        definitions[kind] = definition
    return definitions


def _normalize_type_shape_match(value: Any) -> dict[str, float]:
    """Normalize type-shape matching thresholds with bounded defaults."""
    if value is None:
        return {
            "min_auto_bind_score": _DEFAULT_MIN_AUTO_BIND_SCORE,
            "tie_margin": _DEFAULT_TIE_MARGIN,
        }
    if not isinstance(value, dict):
        raise ConfigParseError("implement.type_shape_match must be an object")
    min_score = value.get("min_auto_bind_score", _DEFAULT_MIN_AUTO_BIND_SCORE)
    tie_margin = value.get("tie_margin", _DEFAULT_TIE_MARGIN)
    try:
        min_score_f = float(min_score)
        tie_margin_f = float(tie_margin)
    except (TypeError, ValueError) as exc:
        raise ConfigParseError(
            "implement.type_shape_match values must be numeric"
        ) from exc
    min_score_f = max(0.0, min(1.0, min_score_f))
    tie_margin_f = max(0.0, min(1.0, tie_margin_f))
    return {"min_auto_bind_score": min_score_f, "tie_margin": tie_margin_f}


def _parse_field_match_score_threshold(value: Any) -> float:
    """Parse normalized score threshold for validation word matching (0..1)."""
    if value is None:
        return _DEFAULT_FIELD_MATCH_SCORE_THRESHOLD
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return _DEFAULT_FIELD_MATCH_SCORE_THRESHOLD
    return max(0.0, min(1.0, parsed))


def _parse_semantic_validation_retries(value: Any) -> int:
    """Parse semantic validation retries (non-negative integer)."""
    if value is None:
        return _DEFAULT_SEMANTIC_VALIDATION_RETRIES
    try:
        retries = int(value)
    except (TypeError, ValueError):
        return _DEFAULT_SEMANTIC_VALIDATION_RETRIES
    return max(0, retries)


def _render_contract_kind_definitions_for_prompt(
    definitions: dict[str, str],
) -> dict[str, dict[str, str]]:
    """Render contract kind definitions into prompt-oriented JSON shape."""
    return {
        kind: {"definition": str(definitions.get(kind, "")).strip()}
        for kind in _CONTRACT_KINDS
    }


def _collect_type_shape_hints(
    normalized_intent_catalog: dict[str, Any],
    unbound_required_refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collect top-ranked deterministic matching hints for unbound required intents."""
    rankings = normalized_intent_catalog.get("required_to_provided_rankings", [])
    if not isinstance(rankings, list):
        return []
    ranking_map: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in rankings:
        if not isinstance(entry, dict):
            continue
        required_ref = entry.get("required_ref", {})
        if not isinstance(required_ref, dict):
            continue
        key = (
            str(required_ref.get("module_tag", "")).strip(),
            str(required_ref.get("intent_local_id", "")).strip(),
        )
        if all(key):
            ranking_map[key] = entry

    hints: list[dict[str, Any]] = []
    for ref in unbound_required_refs:
        if not isinstance(ref, dict):
            continue
        key = (
            str(ref.get("module_tag", "")).strip(),
            str(ref.get("intent_local_id", "")).strip(),
        )
        entry = ranking_map.get(key)
        if entry is None:
            continue
        candidates = entry.get("candidates", [])
        if not isinstance(candidates, list):
            candidates = []
        top_candidates = candidates[:2]
        hints.append(
            {
                "required_ref": {
                    "module_tag": key[0],
                    "intent_local_id": key[1],
                },
                "auto_bind_candidate": entry.get("auto_bind_candidate"),
                "top_candidates": top_candidates,
            }
        )
    hints.sort(
        key=lambda item: (
            str(item.get("required_ref", {}).get("module_tag", "")),
            str(item.get("required_ref", {}).get("intent_local_id", "")),
        )
    )
    return hints


def _get_impl_cfg(config: dict[str, Any]) -> dict[str, Any]:
    """Return implement config with defaults and normalized values."""
    commands = config.get("commands") if isinstance(config, dict) else {}
    impl = commands.get("implement") if isinstance(commands, dict) else {}
    if not isinstance(impl, dict):
        impl = {}
    planner_agent_cfg = _agent_cfg(impl, "unified_planner")
    implementer_agent_cfg = _agent_cfg(impl, "implementer")
    raw_budgets = impl.get("budgets") if isinstance(impl.get("budgets"), dict) else {}
    budgets = dict(_DEFAULT_BUDGETS)
    for key, default in _DEFAULT_BUDGETS.items():
        value = raw_budgets.get(key, default)
        if isinstance(value, int) and value > 0:
            budgets[key] = value
    pika_min_max_files = get_pika_config().get("commands", {}).get("implement", {}).get("min_max_files", 5)
    if budgets["max_files"] < pika_min_max_files:
        raise ConfigParseError(
            f"budgets.max_files ({budgets['max_files']}) is below the minimum "
            f"allowed value ({pika_min_max_files}) from pika.yaml commands.implement.min_max_files"
        )
    roles = impl.get("allowed_module_roles", list(_DEFAULT_ROLES))
    if not isinstance(roles, list) or not roles:
        roles = list(_DEFAULT_ROLES)
    forbidden = impl.get("forbidden_paths", ["docs/", "specs/"])
    if not isinstance(forbidden, list):
        forbidden = ["docs/", "specs/"]
    verify_cmds = impl.get("verification_commands", [])
    if not isinstance(verify_cmds, list):
        verify_cmds = []
    disallowed_policy = _normalize_disallowed_link_policy(
        planner_agent_cfg.get(
            "disallowed_link_kinds_by_required_role",
            impl.get("disallowed_link_kinds_by_required_role"),
        )
    )
    leaf_dependency_roles = _normalize_leaf_dependency_roles(
        planner_agent_cfg.get("leaf_dependency_roles", impl.get("leaf_dependency_roles"))
    )
    leaf_dependency_policy = _normalize_leaf_dependency_policy(
        planner_agent_cfg.get("leaf_dependency_policy", impl.get("leaf_dependency_policy"))
    )
    contract_kind_definitions = _normalize_contract_kind_definitions(
        planner_agent_cfg.get("contract_kind_definitions", impl.get("contract_kind_definitions"))
    )
    type_shape_match = _normalize_type_shape_match(
        planner_agent_cfg.get("type_shape_match", impl.get("type_shape_match"))
    )
    min_confidence_source = dict(impl)
    planner_min_confidence_threshold = planner_agent_cfg.get(
        "min_confidence_threshold",
        impl.get("min_confidence_threshold"),
    )
    if planner_min_confidence_threshold is not None:
        min_confidence_source["min_confidence_threshold"] = planner_min_confidence_threshold

    step_configs = {
        step_name: _step_cfg(impl, step_name)
        for step_name in _DETERMINISTIC_IMPLEMENT_STEPS_IN_ORDER
    }
    steps: dict[str, dict[str, Any]] = {
        step_name: {
            "enabled": _resolve_step_enabled(
                step_configs[step_name],
                _DEFAULT_IMPLEMENT_STEP_ENABLED,
            )
        }
        for step_name in _DETERMINISTIC_IMPLEMENT_STEPS_IN_ORDER
    }

    contract_field_cfg = step_configs["contract_field_consistency_validation"]
    field_match_score_threshold = _parse_field_match_score_threshold(
        contract_field_cfg.get("field_match_score_threshold")
    )
    steps["contract_field_consistency_validation"][
        "field_match_score_threshold"
    ] = field_match_score_threshold

    planner_semantic_cfg = step_configs["planner_semantic_validation"]
    implement_semantic_cfg = step_configs["implement_semantic_validation"]
    planner_semantic_validation_retries = _parse_semantic_validation_retries(
        planner_semantic_cfg.get("semantic_validation_retries")
    )
    implement_semantic_validation_retries = _parse_semantic_validation_retries(
        implement_semantic_cfg.get("semantic_validation_retries")
    )
    steps["planner_semantic_validation"][
        "semantic_validation_retries"
    ] = planner_semantic_validation_retries
    steps["implement_semantic_validation"][
        "semantic_validation_retries"
    ] = implement_semantic_validation_retries

    appendix_cfg = impl.get("appendix") or {}
    if not isinstance(appendix_cfg, dict):
        appendix_cfg = {}
    max_appendix_chars_raw = appendix_cfg.get("max_appendix_chars", 0)
    try:
        max_appendix_chars = max(0, int(max_appendix_chars_raw))
    except (TypeError, ValueError):
        max_appendix_chars = 0

    author_tests_raw = implementer_agent_cfg.get("author_tests", False)
    author_tests = bool(author_tests_raw) if isinstance(author_tests_raw, bool) else False
    _DEFAULT_TEST_AUTHORING_KINDS = ("unit_test", "integration_test")
    test_authoring_kinds_raw = implementer_agent_cfg.get(
        "test_authoring_required_for_evidence_kinds", list(_DEFAULT_TEST_AUTHORING_KINDS)
    )
    if not isinstance(test_authoring_kinds_raw, list):
        test_authoring_kinds_raw = list(_DEFAULT_TEST_AUTHORING_KINDS)
    test_authoring_required_for_evidence_kinds = sorted(
        {
            str(k).strip()
            for k in test_authoring_kinds_raw
            if str(k).strip()
            in {
                "static_check",
                "unit_test",
                "integration_test",
                "runtime_log",
                "manual_review",
            }
        }
    ) or list(_DEFAULT_TEST_AUTHORING_KINDS)

    # P4: reviewer config
    reviewer_agent_cfg = _agent_cfg(impl, "reviewer")

    def _bool(value: Any, default: bool) -> bool:
        return value if isinstance(value, bool) else default

    def _pos_int(value: Any, default: int, *, min_value: int = 1) -> int:
        if isinstance(value, bool):
            return default
        if isinstance(value, int) and value >= min_value:
            return value
        return default

    reviewer_enabled = _bool(reviewer_agent_cfg.get("enabled"), False)
    reviewer_max_iterations = _pos_int(reviewer_agent_cfg.get("max_iterations"), 2)
    reviewer_max_parallel_per_spec = _pos_int(
        reviewer_agent_cfg.get("max_parallel_per_spec"), 4
    )
    reviewer_per_spec_max_total_seconds = _pos_int(
        reviewer_agent_cfg.get("per_spec_max_total_seconds"), 180
    )
    reviewer_escalate_on_axes_insufficient_evidence = _bool(
        reviewer_agent_cfg.get("escalate_on_axes_insufficient_evidence"), True
    )
    reviewer_demote_verification_to_evidence = _bool(
        reviewer_agent_cfg.get("demote_verification_to_evidence"), True
    )

    # P4: verification.timeout_seconds (per-command timeout for verification commands)
    verification_cfg_raw = impl.get("verification")
    verification_cfg = (
        verification_cfg_raw if isinstance(verification_cfg_raw, dict) else {}
    )
    verification_timeout_seconds = _pos_int(
        verification_cfg.get("timeout_seconds"), 300
    )

    from core.pika_config import get_prompt_name
    provider = get_agent_provider(config)

    # Phase 5: amendment-only implementer prompt; falls back to full-mode prompt
    # when pika.yaml hasn't registered the amend variant (e.g., older pika.yaml).
    try:
        amend_prompt_name = get_prompt_name(
            "implement", "implementer_amend", provider=provider
        )
    except Exception:
        amend_prompt_name = get_prompt_name(
            "implement", "implementer", provider=provider
        )
    return {
        "prompt_name": get_prompt_name("implement", "implementer", provider=provider),
        "amend_prompt_name": amend_prompt_name,
        "unified_planner_prompt_name": get_prompt_name("implement", "unified_planner"),
        "type_placement_path": str(
            impl.get("type_placement_path", _DEFAULT_TYPE_PLACEMENT)
        ),
        "allowed_module_roles": {str(r).strip().lower() for r in roles if str(r).strip()},
        "budgets": budgets,
        "forbidden_paths": [str(p).replace("\\", "/") for p in forbidden if str(p).strip()],
        "verification_commands": [str(c) for c in verify_cmds if str(c).strip()],
        "test_spec_path": str(impl.get("test_spec_path", "out/state/test_spec.csv")),
        "min_confidence_threshold": _resolve_min_confidence_threshold(min_confidence_source),
        "disallowed_link_kinds_by_required_role": disallowed_policy,
        "leaf_dependency_roles": leaf_dependency_roles,
        "leaf_dependency_policy": leaf_dependency_policy,
        "contract_kind_definitions": contract_kind_definitions,
        "type_shape_match": type_shape_match,
        # Backward-compatible flat aliases; nested step values are canonical.
        "field_match_score_threshold": field_match_score_threshold,
        "semantic_validation_retries": planner_semantic_validation_retries,
        "steps": steps,
        "max_appendix_chars": max_appendix_chars,
        "author_tests": author_tests,
        "test_authoring_required_for_evidence_kinds": test_authoring_required_for_evidence_kinds,
        "reviewer": {
            "enabled": reviewer_enabled,
            "max_iterations": reviewer_max_iterations,
            "max_parallel_per_spec": reviewer_max_parallel_per_spec,
            "per_spec_max_total_seconds": reviewer_per_spec_max_total_seconds,
            "escalate_on_axes_insufficient_evidence":
                reviewer_escalate_on_axes_insufficient_evidence,
            "demote_verification_to_evidence":
                reviewer_demote_verification_to_evidence,
        },
        "verification_timeout_seconds": verification_timeout_seconds,
    }
