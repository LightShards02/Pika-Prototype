"""Handler for `agent implement` with contract-driven planning and execution workflow."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from core.codebase_snapshot import build_codebase_snapshot
from core.context import RuntimeContext
from core.contracts import get_design_spec_column_definitions
from core.format_sads import load_sads_csv_or_xlsx, rows_to_csv
from core.lifecycle import (
    get_agent_provider,
    invoke_agent_with_schema_retry,
    load_prompt_registry,
    log_lifecycle_event,
    resolve_agent_artifacts_dir_for_command,
    resolve_agent_runs_dir_for_command,
    resolve_codebase_dir_path,
    resolve_input_path,
    resolve_output_path,
    resolve_project_context_content,
)
from core.time_utils import format_timestamp_local_minutes_filename

_DEFAULT_ROLES = ("frontend", "api", "domain", "infra", "shared", "cli", "worker")
_DEFAULT_BUDGETS = {
    "max_specs_per_batch": 15,
    "max_files": 10,
    "max_lines_changed": 600,
    "max_context_tokens": 12000,
}
_DEFAULT_MIN_CONFIDENCE_THRESHOLD = 0.7  # Project config > pika config > this default
_DEFAULT_TYPE_PLACEMENT = "workspace/shared-contracts/"
_DEFAULT_LINKER_MAX_ATTEMPTS = 2
_CONTRACT_KINDS = (
    "api_endpoint",
    "service_interface",
    "event_topic",
    "db_table",
    "file_format",
    "external_api",
    "test_suite",
)
_DEFAULT_DISALLOWED_LINK_KINDS_BY_REQUIRED_ROLE: dict[str, set[str]] = {
    "frontend": {
        "service_interface",
        "event_topic",
        "db_table",
        "file_format",
        "external_api",
        "test_suite",
    },
    "domain": {"external_api"},
}
_TEST_SPEC_HEADERS = [
    "test_id",
    "test_name",
    "test_description",
    "framework",
    "test_file",
    "test_case",
]


def run_implement(config: dict[str, Any], ctx: RuntimeContext) -> dict[str, Any]:
    """Run implement workflow: deterministic prep, planning, batching, execution, translation."""
    root = Path(ctx.project_root)
    impl = _get_impl_cfg(config)
    log_lifecycle_event("lifecycle_load_inputs", command="implement", run_id=ctx.run_id)

    design_path = resolve_input_path(
        config,
        root,
        "design_spec_path",
        overrides=ctx.input_overrides,
        command="implement",
    )
    if design_path is None or not design_path.exists():
        return {
            "command": "implement",
            "status": "skipped",
            "reason": "design_spec_path not configured or missing",
        }

    headers, rows = load_sads_csv_or_xlsx(design_path)
    selected = _select_workset(headers, rows)
    paths = _init_run_workspace(config, root, ctx)

    _write_json(
        paths["run"] / "run_meta.json",
        {
            "command": "implement",
            "run_id": ctx.run_id,
            "dry_run": ctx.dry_run,
            "budgets": impl["budgets"],
            "type_placement_path": impl["type_placement_path"],
            "linker_max_attempts": impl["linker_max_attempts"],
            "disallowed_link_kinds_by_required_role": _serialize_disallowed_link_policy(
                impl["disallowed_link_kinds_by_required_role"]
            ),
            "config_hash": _sha256(
                json.dumps(config, sort_keys=True, default=str).encode("utf-8")
            ),
        },
    )
    _write_json(
        paths["run"] / "workset.json",
        {
            "selected": [
                {
                    "spec_id": row["spec_id"],
                    "module_tag": row["module_tag"],
                    "module_role": row["module_role"],
                }
                for row in selected
            ]
        },
    )
    if not selected:
        _write_json(
            paths["run"] / "summary.json",
            {"status": "completed", "reason": "no specs to implement"},
        )
        return {"command": "implement", "status": "completed", "dry_run": ctx.dry_run}

    module_catalog = _build_module_catalog(selected, impl["allowed_module_roles"])
    _write_json(paths["run"] / "module_catalog.json", module_catalog)

    schemas = _resolve_prompt_schemas(config, impl)
    context_text = _project_context(config, root, ctx)
    anchor_plans: dict[str, dict[str, Any]] = {}
    for module in module_catalog["modules"]:
        module_tag = module["module_tag"]
        packet = {
            "module": module,
            "spec_rows": _minimal_specs(
                [row for row in selected if row["module_tag"] == module_tag]
            ),
        }
        planner_output = invoke_agent_with_schema_retry(
            prompt_name=impl["anchor_planner_prompt_name"],
            template_vars={
                "output_schema_file": str(schemas["planner"]),
                "project_context": context_text,
                "module_packet_json": json.dumps(packet, indent=2),
                "manual_resolution_file": str(paths["manual"]),
                "run_summary_file": str(paths["run"] / "summary.json"),
            },
            schema_path=schemas["planner"],
            config=config,
            ctx=ctx,
        )
        if _manual_block(planner_output, paths["manual"], f"planner_{module_tag}"):
            return {
                "command": "implement",
                "status": "blocked",
                "blocking_items": len(planner_output.get("manual_resolution_items", [])),
            }
        anchor_plans[module_tag] = planner_output
        _write_json(paths["anchor_plans"] / f"{module_tag}.json", planner_output)

    linker_output: dict[str, Any] | None = None
    link_validation: dict[str, Any] | None = None
    linker_retry_context: dict[str, Any] | None = None
    for linker_attempt in range(1, impl["linker_max_attempts"] + 1):
        linker_output = invoke_agent_with_schema_retry(
            prompt_name=impl["anchor_linker_prompt_name"],
            template_vars={
                "output_schema_file": str(schemas["linker"]),
                "project_context": context_text,
                "module_catalog_json": json.dumps(module_catalog, indent=2),
                "anchor_plans_json": json.dumps(list(anchor_plans.values()), indent=2),
                "type_placement_path": impl["type_placement_path"],
                "disallowed_link_kinds_by_required_role_json": json.dumps(
                    _serialize_disallowed_link_policy(
                        impl["disallowed_link_kinds_by_required_role"]
                    ),
                    indent=2,
                ),
                "manual_resolution_file": str(paths["manual"]),
                "run_summary_file": str(paths["run"] / "summary.json"),
                "linker_retry_context_json": (
                    json.dumps(linker_retry_context, indent=2)
                    if linker_retry_context
                    else "null"
                ),
            },
            schema_path=schemas["linker"],
            config=config,
            ctx=ctx,
        )
        _write_json(paths["agent_outputs"] / f"anchor_linker_attempt_{linker_attempt}.json", linker_output)
        _write_json(paths["agent_outputs"] / "anchor_linker.json", linker_output)
        if _manual_block(linker_output, paths["manual"], "linker"):
            return {
                "command": "implement",
                "status": "blocked",
                "blocking_items": len(linker_output.get("manual_resolution_items", [])),
            }
        _write_json(paths["run"] / "link_plan.json", linker_output)

        link_validation = _validate_link_plan(
            anchor_plans,
            module_catalog,
            linker_output,
            impl["type_placement_path"],
            impl["disallowed_link_kinds_by_required_role"],
        )
        _write_json(paths["run"] / "link_plan_validation.json", link_validation)
        _write_json(
            paths["trace"] / f"link_plan_validation_attempt_{linker_attempt}.json",
            link_validation,
        )
        if link_validation["status"] == "passed":
            break

        missing = link_validation.get("unbound_required_refs", [])
        violations = link_validation.get("violations", [])
        can_retry = (
            linker_attempt < impl["linker_max_attempts"]
            and (
                (isinstance(missing, list) and bool(missing))
                or (isinstance(violations, list) and bool(violations))
            )
        )
        if can_retry:
            linker_retry_context = _build_linker_retry_context(
                linker_attempt,
                impl["linker_max_attempts"],
                missing,
                violations if isinstance(violations, list) else [],
            )
            _write_json(
                paths["trace"] / f"linker_retry_context_attempt_{linker_attempt + 1}.json",
                linker_retry_context,
            )
            continue
        _write_json(
            paths["run"] / "summary.json",
            {"status": "failed", "reason": "link_plan_validation_failed"},
        )
        return {
            "command": "implement",
            "status": "failed",
            "reason": "link_plan_validation_failed",
        }

    if linker_output is None or link_validation is None or link_validation["status"] != "passed":
        _write_json(
            paths["run"] / "summary.json",
            {"status": "failed", "reason": "link_plan_validation_failed"},
        )
        return {
            "command": "implement",
            "status": "failed",
            "reason": "link_plan_validation_failed",
        }

    batch_plan = _build_batches(selected, linker_output, impl["budgets"])
    _write_json(paths["run"] / "batch_plan.json", batch_plan)
    batch_plan_validation = _validate_batch_plan_dependencies(batch_plan, linker_output)
    _write_json(paths["run"] / "batch_plan_validation.json", batch_plan_validation)
    if batch_plan_validation["status"] != "passed":
        _write_json(
            paths["run"] / "summary.json",
            {"status": "failed", "reason": "batch_plan_validation_failed"},
        )
        return {
            "command": "implement",
            "status": "failed",
            "reason": "batch_plan_validation_failed",
        }
    briefs = _build_briefs(selected, anchor_plans, linker_output, batch_plan, impl)
    for brief in briefs:
        _write_json(paths["briefs"] / f"{brief['batch_id']}.json", brief)

    low_conf_items = _collect_low_confidence_items(
        briefs, anchor_plans, impl["min_confidence_threshold"]
    )
    if low_conf_items:
        _write_json(
            paths["manual"] / "batch_briefs_confidence.json",
            {"stage": "batch_briefs_confidence", "items": low_conf_items},
        )
        _write_json(
            paths["run"] / "summary.json",
            {"status": "blocked", "reason": "low_confidence_items", "blocking_items": len(low_conf_items)},
        )
        return {
            "command": "implement",
            "status": "blocked",
            "reason": "low_confidence_items",
            "blocking_items": len(low_conf_items),
        }

    if ctx.dry_run:
        _write_json(paths["run"] / "summary.json", {"status": "completed", "dry_run": True})
        return {"command": "implement", "status": "completed", "dry_run": True}

    spec_outputs: dict[str, dict[str, Any]] = {}
    for brief in briefs:
        result = _execute_batch(
            config,
            ctx,
            impl,
            schemas["implementer"],
            root,
            context_text,
            paths,
            headers,
            brief,
        )
        if result["status"] != "completed":
            _write_json(
                paths["run"] / "summary.json",
                {
                    "status": result["status"],
                    "reason": result.get("reason", "batch_failed"),
                },
            )
            return {
                "command": "implement",
                "status": result["status"],
                "reason": result.get("reason", "batch_failed"),
            }
        spec_outputs.update(result.get("spec_outputs", {}))

    _update_design_and_test_spec(config, ctx, impl, design_path, spec_outputs)
    _write_json(
        paths["run"] / "summary.json",
        {"status": "completed", "batches_completed": len(briefs), "batches_failed": 0},
    )
    return {"command": "implement", "status": "completed", "dry_run": False}


def _write_json(path: Path, payload: Any) -> None:
    """Write JSON to disk with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _sha256(payload: bytes) -> str:
    """Compute SHA-256 hex digest."""
    return hashlib.sha256(payload).hexdigest()


def _find_col(headers: list[str], name: str) -> str | None:
    """Return first matching header by case-insensitive name."""
    mapping = {h.strip().lower(): h for h in headers if h}
    return mapping.get(name.lower())


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
        from core.pika_config import get_pika_config

        raw = get_pika_config().get("implement", {}).get("min_confidence_threshold")
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
        raise ValueError("implement.disallowed_link_kinds_by_required_role must be an object")
    normalized: dict[str, set[str]] = {}
    known_roles = set(_DEFAULT_ROLES)
    known_kinds = set(_CONTRACT_KINDS)
    for raw_role, raw_kinds in value.items():
        role = str(raw_role).strip().lower()
        if role not in known_roles:
            raise ValueError(
                "implement.disallowed_link_kinds_by_required_role contains unknown role: "
                f"{raw_role}"
            )
        if not isinstance(raw_kinds, list):
            raise ValueError(
                "implement.disallowed_link_kinds_by_required_role entries must be arrays of contract kind strings"
            )
        kinds: set[str] = set()
        for raw_kind in raw_kinds:
            kind = str(raw_kind).strip()
            if kind not in known_kinds:
                raise ValueError(
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


def _get_impl_cfg(config: dict[str, Any]) -> dict[str, Any]:
    """Return implement config with defaults and normalized values."""
    commands = config.get("commands") if isinstance(config, dict) else {}
    impl = commands.get("implement") if isinstance(commands, dict) else {}
    if not isinstance(impl, dict):
        impl = {}
    raw_budgets = impl.get("budgets") if isinstance(impl.get("budgets"), dict) else {}
    budgets = dict(_DEFAULT_BUDGETS)
    for key, default in _DEFAULT_BUDGETS.items():
        value = raw_budgets.get(key, default)
        if isinstance(value, int) and value > 0:
            budgets[key] = value
    roles = impl.get("allowed_module_roles", list(_DEFAULT_ROLES))
    if not isinstance(roles, list) or not roles:
        roles = list(_DEFAULT_ROLES)
    forbidden = impl.get("forbidden_paths", ["docs/", "specs/"])
    if not isinstance(forbidden, list):
        forbidden = ["docs/", "specs/"]
    verify_cmds = impl.get("verification_commands", [])
    if not isinstance(verify_cmds, list):
        verify_cmds = []
    linker_attempts = impl.get("linker_max_attempts", _DEFAULT_LINKER_MAX_ATTEMPTS)
    if not isinstance(linker_attempts, int) or linker_attempts < 1:
        linker_attempts = _DEFAULT_LINKER_MAX_ATTEMPTS
    disallowed_policy = _normalize_disallowed_link_policy(
        impl.get("disallowed_link_kinds_by_required_role")
    )
    return {
        "prompt_name": str(impl.get("prompt_name", "implement_from_specs")),
        "anchor_planner_prompt_name": str(
            impl.get("anchor_planner_prompt_name", "implement_anchor_planner")
        ),
        "anchor_linker_prompt_name": str(
            impl.get("anchor_linker_prompt_name", "implement_anchor_linker")
        ),
        "type_placement_path": str(
            impl.get("type_placement_path", _DEFAULT_TYPE_PLACEMENT)
        ),
        "allowed_module_roles": {str(r).strip().lower() for r in roles if str(r).strip()},
        "budgets": budgets,
        "forbidden_paths": [str(p).replace("\\", "/") for p in forbidden if str(p).strip()],
        "verification_commands": [str(c) for c in verify_cmds if str(c).strip()],
        "test_spec_path": str(impl.get("test_spec_path", "out/state/test_spec.csv")),
        "min_confidence_threshold": _resolve_min_confidence_threshold(impl),
        "linker_max_attempts": linker_attempts,
        "disallowed_link_kinds_by_required_role": disallowed_policy,
    }


def _resolve_prompt_schemas(config: dict[str, Any], impl: dict[str, Any]) -> dict[str, Path]:
    """Resolve schema paths for planner/linker/implementer prompts."""
    registry = load_prompt_registry(config)
    return {
        "planner": registry.get_schema_path(impl["anchor_planner_prompt_name"]),
        "linker": registry.get_schema_path(impl["anchor_linker_prompt_name"]),
        "implementer": registry.get_schema_path(impl["prompt_name"]),
    }


def _project_context(config: dict[str, Any], root: Path, ctx: RuntimeContext) -> str:
    """Resolve project context content using shared lifecycle resolver."""
    codebase = resolve_codebase_dir_path(config, root, ctx)
    return resolve_project_context_content(config, root, ctx, codebase)


def _init_run_workspace(config: dict[str, Any], root: Path, ctx: RuntimeContext) -> dict[str, Path]:
    """Create run workspace directories and return keyed paths.

    Uses out/agent_runs/implement/{run_id}/ for run workspace.
    """
    run = resolve_agent_runs_dir_for_command(config, root, "implement", ctx.run_id)
    paths = {
        "run": run,
        "anchor_plans": run / "anchor_plans",
        "manual": run / "manual_resolution",
        "briefs": run / "batch_briefs",
        "agent_outputs": run / "agent_outputs",
        "patches": run / "patches",
        "verification": run / "verification",
        "trace": run / "trace",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _select_workset(headers: list[str], rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Select rows with implementation_status != Completed and required fields present."""
    spec_col = _find_col(headers, "spec_id")
    tag_col = _find_col(headers, "module_tag")
    role_col = _find_col(headers, "module_role")
    status_col = _find_col(headers, "implementation_status")
    missing = [
        name
        for name, col in (("spec_id", spec_col), ("module_tag", tag_col), ("module_role", role_col))
        if col is None
    ]
    if missing:
        raise ValueError("Missing required columns for implement: " + ", ".join(missing))
    selected: list[dict[str, str]] = []
    for idx, row in enumerate(rows, start=1):
        status = (row.get(status_col, "") if status_col else "").strip().lower()
        if status == "completed":
            continue
        spec_id = (row.get(spec_col, "") or "").strip()
        tag = (row.get(tag_col, "") or "").strip()
        role = (row.get(role_col, "") or "").strip().lower()
        if not spec_id or not tag or not role:
            raise ValueError(
                f"Selected row {idx} is missing required spec_id/module_tag/module_role"
            )
        updated = dict(row)
        updated["spec_id"] = spec_id
        updated["module_tag"] = tag
        updated["module_role"] = role
        selected.append(updated)
    return selected


def _build_module_catalog(rows: list[dict[str, str]], allowed_roles: set[str]) -> dict[str, Any]:
    """Build module catalog by module_tag with strict role consistency."""
    grouped: dict[str, set[str]] = {}
    for row in rows:
        grouped.setdefault(row["module_tag"], set()).add(row["module_role"])
    modules: list[dict[str, Any]] = []
    for module_tag in sorted(grouped):
        roles = grouped[module_tag]
        if len(roles) != 1:
            raise ValueError(
                f"Inconsistent module_role for module_tag '{module_tag}': {sorted(roles)}"
            )
        role = next(iter(roles))
        if role not in allowed_roles:
            raise ValueError(f"Invalid module_role '{role}' for module_tag '{module_tag}'")
        modules.append(
            {
                "module_tag": module_tag,
                "module_role": role,
                "root_dirs": [f"{module_tag}/"],
                "languages": [],
            }
        )
    return {"modules": modules}


def _minimal_specs(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return narrow set of row fields for planner prompt packets."""
    keys = ["spec_id", "title", "requirement", "acceptance_criteria", "module_tag", "module_role"]
    return [{k: row.get(k, "") for k in keys} for row in rows]


def _collect_low_confidence_items(
    briefs: list[dict[str, Any]],
    anchor_plans: dict[str, dict[str, Any]],
    threshold: float,
) -> list[dict[str, Any]]:
    """Collect items with confidence below threshold as manual_resolution_items.

    Scans relevant_bindings in briefs and provided/required intents in anchor_plans.
    Returns empty list when threshold <= 0 (disabled).
    """
    if threshold <= 0:
        return []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_binding_item(batch_id: str, binding: dict[str, Any]) -> None:
        contract_id = str(binding.get("contract_id", "")).strip()
        req = binding.get("required_ref") if isinstance(binding.get("required_ref"), dict) else {}
        prov = binding.get("provided_ref") if isinstance(binding.get("provided_ref"), dict) else {}
        req_mod = str(req.get("module_tag", ""))
        req_intent = str(req.get("intent_local_id", ""))
        prov_mod = str(prov.get("module_tag", ""))
        prov_intent = str(prov.get("intent_local_id", ""))
        conf = float(binding.get("confidence", 0))
        item_id = f"low_conf_binding_{batch_id}_{contract_id}_{req_mod}_{prov_mod}"
        if item_id in seen:
            return
        seen.add(item_id)
        items.append({
            "item_id": item_id,
            "title": f"Low confidence binding ({conf:.2f} < {threshold:.2f})",
            "question": (
                f"Binding {req_mod}:{req_intent} -> {prov_mod}:{prov_intent} "
                f"(contract {contract_id}) has confidence {conf:.2f}. Proceed or block?"
            ),
            "options": [
                {"option_id": "proceed", "label": "Proceed with implementation", "effect": "Allow code generation"},
                {"option_id": "block", "label": "Block until plan is revised", "effect": "Require manual revision"},
            ],
            "required": True,
            "blocking_reason": f"Confidence {conf:.2f} below threshold {threshold:.2f}",
            "evidence_refs": [f"batch_id:{batch_id}", f"contract_id:{contract_id}"],
        })

    def add_intent_item(module_tag: str, intent: dict[str, Any]) -> None:
        local_id = str(intent.get("intent_local_id", "")).strip()
        conf = float(intent.get("confidence", 0))
        item_id = f"low_conf_intent_{module_tag}_{local_id}"
        if item_id in seen:
            return
        seen.add(item_id)
        items.append({
            "item_id": item_id,
            "title": f"Low confidence intent ({conf:.2f} < {threshold:.2f})",
            "question": (
                f"Intent {module_tag}:{local_id} has confidence {conf:.2f}. Proceed or block?"
            ),
            "options": [
                {"option_id": "proceed", "label": "Proceed with implementation", "effect": "Allow code generation"},
                {"option_id": "block", "label": "Block until plan is revised", "effect": "Require manual revision"},
            ],
            "required": True,
            "blocking_reason": f"Confidence {conf:.2f} below threshold {threshold:.2f}",
            "evidence_refs": [f"module_tag:{module_tag}", f"intent_local_id:{local_id}"],
        })

    for brief in briefs:
        batch_id = str(brief.get("batch_id", ""))
        for binding in brief.get("relevant_bindings", []):
            if not isinstance(binding, dict):
                continue
            conf = binding.get("confidence")
            if isinstance(conf, (int, float)) and float(conf) < threshold:
                add_binding_item(batch_id, binding)

    for module_tag, plan in anchor_plans.items():
        if not isinstance(plan, dict):
            continue
        for intent in plan.get("provided_intents", []) or []:
            if isinstance(intent, dict) and isinstance(intent.get("confidence"), (int, float)):
                if float(intent.get("confidence", 0)) < threshold:
                    add_intent_item(module_tag, intent)
        for intent in plan.get("required_intents", []) or []:
            if isinstance(intent, dict) and isinstance(intent.get("confidence"), (int, float)):
                if float(intent.get("confidence", 0)) < threshold:
                    add_intent_item(module_tag, intent)

    return items


def _manual_block(output: dict[str, Any], manual_dir: Path, stage: str) -> bool:
    """Persist manual resolution payload and return True when output is blocking."""
    items = output.get("manual_resolution_items")
    if isinstance(items, list) and items:
        _write_json(manual_dir / f"{stage}.json", {"stage": stage, "items": items})
        return True
    return False


def _build_linker_retry_context(
    linker_attempt: int,
    linker_max_attempts: int,
    unbound_required_refs: list[dict[str, Any]],
    validation_violations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build deterministic retry payload for linker validation-repair attempts."""
    refs: list[dict[str, str]] = []
    for ref in unbound_required_refs:
        if not isinstance(ref, dict):
            continue
        module_tag = str(ref.get("module_tag", "")).strip()
        intent_local_id = str(ref.get("intent_local_id", "")).strip()
        if module_tag and intent_local_id:
            refs.append({"module_tag": module_tag, "intent_local_id": intent_local_id})
    refs.sort(key=lambda item: (item["module_tag"], item["intent_local_id"]))
    normalized_violations: list[dict[str, Any]] = []
    for violation in validation_violations:
        if not isinstance(violation, dict):
            continue
        normalized_violations.append(violation)
    return {
        "retry_reason": "link_plan_validation_failed",
        "next_attempt": linker_attempt + 1,
        "max_attempts": linker_max_attempts,
        "unbound_required_intents": refs,
        "validation_violations": normalized_violations,
        "instructions": (
            "For each unbound required intent or validation violation, either emit a valid binding "
            "that satisfies policy constraints or emit one manual_resolution_item explaining why no valid link exists."
        ),
    }


def _validate_link_plan(
    anchor_plans: dict[str, dict[str, Any]],
    module_catalog: dict[str, Any],
    link_plan: dict[str, Any],
    type_placement: str,
    disallowed_link_kinds_by_required_role: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """Run deterministic checks for required bindings, role rules, and type placement."""
    required = set()
    for module_tag, plan in anchor_plans.items():
        for intent in plan.get("required_intents", []):
            if isinstance(intent, dict):
                local = str(intent.get("intent_local_id", "")).strip()
                if local:
                    required.add((module_tag, local))
    bound = set()
    for binding in link_plan.get("bindings", []):
        if isinstance(binding, dict) and isinstance(binding.get("required_ref"), dict):
            ref = binding["required_ref"]
            module = str(ref.get("module_tag", "")).strip()
            local = str(ref.get("intent_local_id", "")).strip()
            if module and local:
                bound.add((module, local))
    checks: list[str] = []
    reasons: list[str] = []
    violations: list[dict[str, Any]] = []
    unbound_required_refs = [
        {"module_tag": module_tag, "intent_local_id": local}
        for module_tag, local in sorted(required - bound)
    ]
    if unbound_required_refs:
        reasons.append("Unbound required intents exist")
        for ref in unbound_required_refs:
            violations.append(
                {
                    "code": "unbound_required_intent",
                    "required_ref": ref,
                    "message": (
                        f"Required intent {ref['module_tag']}:{ref['intent_local_id']} is not bound in link_plan.bindings."
                    ),
                }
            )
    else:
        checks.append("all_required_bound")

    roles = {
        str(m.get("module_tag")): str(m.get("module_role"))
        for m in module_catalog.get("modules", [])
        if isinstance(m, dict)
    }
    contracts = {
        str(c.get("contract_id")): c
        for c in link_plan.get("contracts", [])
        if isinstance(c, dict)
    }
    policy = (
        disallowed_link_kinds_by_required_role
        if isinstance(disallowed_link_kinds_by_required_role, dict)
        else _DEFAULT_DISALLOWED_LINK_KINDS_BY_REQUIRED_ROLE
    )
    for binding in link_plan.get("bindings", []):
        if not isinstance(binding, dict):
            continue
        req = binding.get("required_ref") if isinstance(binding.get("required_ref"), dict) else {}
        prov = binding.get("provided_ref") if isinstance(binding.get("provided_ref"), dict) else {}
        module = str(req.get("module_tag", ""))
        role = roles.get(module, "")
        kind = str(contracts.get(str(binding.get("contract_id", "")), {}).get("kind", ""))
        disallowed_kinds = policy.get(role, set()) if isinstance(role, str) else set()
        if kind and kind in disallowed_kinds:
            if role == "domain" and kind == "external_api":
                reason = f"domain module {module} requires external_api directly"
            else:
                reason = f"{role} module {module} requires disallowed kind {kind}"
            reasons.append(reason)
            violations.append(
                {
                    "code": "disallowed_kind_for_required_role",
                    "required_ref": {
                        "module_tag": str(req.get("module_tag", "")),
                        "intent_local_id": str(req.get("intent_local_id", "")),
                    },
                    "provided_ref": {
                        "module_tag": str(prov.get("module_tag", "")),
                        "intent_local_id": str(prov.get("intent_local_id", "")),
                    },
                    "contract_id": str(binding.get("contract_id", "")),
                    "required_module_role": role,
                    "actual_kind": kind,
                    "disallowed_kinds_for_role": sorted(disallowed_kinds),
                    "message": reason,
                }
            )
    if not any("requires" in reason for reason in reasons):
        checks.append("role_rules_ok")

    prefix = type_placement.strip("/").lower()
    bad_location = False
    for binding in link_plan.get("bindings", []):
        if not isinstance(binding, dict):
            continue
        req = binding.get("required_ref") if isinstance(binding.get("required_ref"), dict) else {}
        prov = binding.get("provided_ref") if isinstance(binding.get("provided_ref"), dict) else {}
        if str(req.get("module_tag", "")) == str(prov.get("module_tag", "")):
            continue
        contract = contracts.get(str(binding.get("contract_id", "")), {})
        locations = contract.get("type_locations") if isinstance(contract.get("type_locations"), dict) else {}
        for loc in locations.values():
            if not str(loc).replace("\\", "/").strip("/").lower().startswith(prefix):
                bad_location = True
                violations.append(
                    {
                        "code": "cross_module_type_location_outside_placement_path",
                        "required_ref": {
                            "module_tag": str(req.get("module_tag", "")),
                            "intent_local_id": str(req.get("intent_local_id", "")),
                        },
                        "provided_ref": {
                            "module_tag": str(prov.get("module_tag", "")),
                            "intent_local_id": str(prov.get("intent_local_id", "")),
                        },
                        "contract_id": str(binding.get("contract_id", "")),
                        "actual_type_location": str(loc),
                        "required_prefix": prefix,
                        "message": "Cross-module type_locations outside configured placement path",
                    }
                )
    if bad_location:
        reasons.append("Cross-module type_locations outside configured placement path")
    else:
        checks.append("type_locations_ok")

    return {
        "status": "passed" if not reasons else "failed",
        "checks": checks,
        "reasons": reasons,
        "unbound_required_refs": unbound_required_refs,
        "violations": violations,
    }


def _build_batches(rows: list[dict[str, str]], link_plan: dict[str, Any], budgets: dict[str, int]) -> dict[str, Any]:
    """Build deterministic, graph-aware batch plan from bindings and budgets."""
    modules = _module_specs_from_rows(rows)
    graph = _build_consumer_provider_graph(modules, link_plan)
    sccs = _strongly_connected_components(graph)
    scc_order = _topologically_order_sccs(graph, sccs)
    module_to_scc = {module: idx for idx, comp in enumerate(sccs) for module in comp}

    max_specs = max(1, int(budgets.get("max_specs_per_batch", 1)))
    has_integration = isinstance(link_plan.get("integration_actions"), list) and bool(
        link_plan.get("integration_actions")
    )
    batches: list[dict[str, Any]] = []
    counter = 0
    if has_integration:
        batches.append(
            {
                "batch_id": "B0",
                "kind": "integration",
                "spec_ids": [],
                "module_tags": ["SHARED"],
                "depends_on_batches": [],
                "rationale": "integration actions",
                "budgets_applied": budgets,
            }
        )
        counter = 1

    module_to_batches: dict[str, list[str]] = {}
    for scc_idx in scc_order:
        members = sorted(sccs[scc_idx])
        cyclic = len(members) > 1 or (
            len(members) == 1 and members[0] in graph.get(members[0], set())
        )

        if cyclic:
            combined_specs: list[str] = []
            for member in members:
                combined_specs.extend(modules.get(member, []))
            chunks = _chunk_specs(sorted(set(combined_specs)), max_specs)
            if not chunks:
                continue
            prev_batch = ""
            external_deps: set[str] = set()
            for consumer in members:
                for provider in sorted(graph.get(consumer, set())):
                    provider_scc = module_to_scc.get(provider)
                    if provider_scc is None or provider_scc == scc_idx:
                        continue
                    external_deps.update(module_to_batches.get(provider, []))

            for chunk in chunks:
                bid = f"B{counter}"
                counter += 1
                deps: set[str] = set(external_deps)
                if has_integration:
                    deps.add("B0")
                if prev_batch:
                    deps.add(prev_batch)
                batches.append(
                    {
                        "batch_id": bid,
                        "kind": "module_impl",
                        "spec_ids": chunk,
                        "module_tags": members,
                        "depends_on_batches": sorted(deps),
                        "rationale": f"scc-cohort {','.join(members)}",
                        "budgets_applied": budgets,
                    }
                )
                for member in members:
                    module_to_batches.setdefault(member, []).append(bid)
                prev_batch = bid
            continue

        module = members[0]
        specs = modules.get(module, [])
        prev_batch = ""
        for chunk in _chunk_specs(specs, max_specs):
            bid = f"B{counter}"
            counter += 1
            deps: set[str] = set()
            if has_integration:
                deps.add("B0")
            for provider in sorted(graph.get(module, set())):
                deps.update(module_to_batches.get(provider, []))
            if prev_batch:
                deps.add(prev_batch)
            batches.append(
                {
                    "batch_id": bid,
                    "kind": "module_impl",
                    "spec_ids": chunk,
                    "module_tags": [module],
                    "depends_on_batches": sorted(deps),
                    "rationale": f"provider-first {module}",
                    "budgets_applied": budgets,
                }
            )
            module_to_batches.setdefault(module, []).append(bid)
            prev_batch = bid

    return {"batches": batches}


def _module_specs_from_rows(rows: list[dict[str, str]]) -> dict[str, list[str]]:
    """Build deterministic module -> spec_id mapping from selected rows."""
    modules: dict[str, list[str]] = {}
    for row in rows:
        module = str(row.get("module_tag", "")).strip()
        spec_id = str(row.get("spec_id", "")).strip()
        if not module or not spec_id:
            continue
        modules.setdefault(module, []).append(spec_id)
    for module in list(modules):
        modules[module] = sorted(set(modules[module]))
    return modules


def _build_consumer_provider_graph(
    modules: dict[str, list[str]], link_plan: dict[str, Any]
) -> dict[str, set[str]]:
    """Return consumer->providers graph from cross-module bindings."""
    graph: dict[str, set[str]] = {module: set() for module in modules}
    for binding in link_plan.get("bindings", []):
        if not isinstance(binding, dict):
            continue
        req = binding.get("required_ref") if isinstance(binding.get("required_ref"), dict) else {}
        prov = binding.get("provided_ref") if isinstance(binding.get("provided_ref"), dict) else {}
        consumer = str(req.get("module_tag", "")).strip()
        provider = str(prov.get("module_tag", "")).strip()
        if not consumer or not provider:
            continue
        graph.setdefault(consumer, set())
        graph.setdefault(provider, set())
        if consumer != provider:
            graph[consumer].add(provider)
    return graph


def _strongly_connected_components(graph: dict[str, set[str]]) -> list[list[str]]:
    """Compute SCCs using deterministic Tarjan traversal."""
    index = 0
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def strong_connect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for neighbor in sorted(graph.get(node, set())):
            if neighbor not in indices:
                strong_connect(neighbor)
                lowlink[node] = min(lowlink[node], lowlink[neighbor])
            elif neighbor in on_stack:
                lowlink[node] = min(lowlink[node], indices[neighbor])

        if lowlink[node] != indices[node]:
            return
        component: list[str] = []
        while stack:
            popped = stack.pop()
            on_stack.discard(popped)
            component.append(popped)
            if popped == node:
                break
        components.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            strong_connect(node)
    return components


def _topologically_order_sccs(graph: dict[str, set[str]], sccs: list[list[str]]) -> list[int]:
    """Topologically sort SCCs by provider->consumer edges with deterministic tie-breaks."""
    module_to_scc = {module: idx for idx, component in enumerate(sccs) for module in component}
    edges: dict[int, set[int]] = {idx: set() for idx in range(len(sccs))}
    indegree: dict[int, int] = {idx: 0 for idx in range(len(sccs))}

    for consumer, providers in graph.items():
        consumer_idx = module_to_scc.get(consumer)
        if consumer_idx is None:
            continue
        for provider in providers:
            provider_idx = module_to_scc.get(provider)
            if provider_idx is None or provider_idx == consumer_idx:
                continue
            if consumer_idx not in edges[provider_idx]:
                edges[provider_idx].add(consumer_idx)
                indegree[consumer_idx] += 1

    order: list[int] = []
    queue = [idx for idx, deg in indegree.items() if deg == 0]
    queue.sort(key=lambda idx: ",".join(sccs[idx]))
    while queue:
        current = queue.pop(0)
        order.append(current)
        for nxt in sorted(edges[current], key=lambda idx: ",".join(sccs[idx])):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
                queue.sort(key=lambda idx: ",".join(sccs[idx]))

    if len(order) == len(sccs):
        return order
    # Fallback keeps deterministic output even under malformed graph construction.
    return sorted(range(len(sccs)), key=lambda idx: ",".join(sccs[idx]))


def _chunk_specs(spec_ids: list[str], chunk_size: int) -> list[list[str]]:
    """Split sorted spec IDs into fixed-size chunks."""
    if chunk_size <= 0:
        return [spec_ids] if spec_ids else []
    return [spec_ids[i:i + chunk_size] for i in range(0, len(spec_ids), chunk_size)]


def _validate_batch_plan_dependencies(batch_plan: dict[str, Any], link_plan: dict[str, Any]) -> dict[str, Any]:
    """Validate dependency wiring between consumer and provider batches."""
    checks: list[str] = []
    reasons: list[str] = []
    batches = [b for b in batch_plan.get("batches", []) if isinstance(b, dict)]
    by_id = {str(batch.get("batch_id", "")): batch for batch in batches if str(batch.get("batch_id", "")).strip()}

    missing_dep_refs: list[str] = []
    for batch in batches:
        batch_id = str(batch.get("batch_id", "")).strip()
        for dep in [str(d) for d in batch.get("depends_on_batches", [])]:
            if dep not in by_id:
                missing_dep_refs.append(f"{batch_id}->{dep}")
    if missing_dep_refs:
        reasons.append("Batch plan references unknown dependency batch IDs: " + ", ".join(sorted(missing_dep_refs)))
    else:
        checks.append("dependency_ids_exist")

    module_batches: dict[str, list[str]] = {}
    assigned_specs: list[str] = []
    for batch in batches:
        if str(batch.get("kind", "module_impl")) == "integration":
            continue
        batch_id = str(batch.get("batch_id", ""))
        for module in [str(m) for m in batch.get("module_tags", [])]:
            module_batches.setdefault(module, []).append(batch_id)
        assigned_specs.extend([str(s) for s in batch.get("spec_ids", []) if str(s).strip()])

    duplicates = sorted({spec_id for spec_id in assigned_specs if assigned_specs.count(spec_id) > 1})
    if duplicates:
        reasons.append("Spec IDs assigned to multiple batches: " + ", ".join(duplicates))
    else:
        checks.append("spec_ids_unique_across_batches")

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

    missing_provider_paths: list[str] = []
    for binding in link_plan.get("bindings", []):
        if not isinstance(binding, dict):
            continue
        req = binding.get("required_ref") if isinstance(binding.get("required_ref"), dict) else {}
        prov = binding.get("provided_ref") if isinstance(binding.get("provided_ref"), dict) else {}
        consumer = str(req.get("module_tag", "")).strip()
        provider = str(prov.get("module_tag", "")).strip()
        contract_id = str(binding.get("contract_id", "")).strip()
        if not consumer or not provider or consumer == provider:
            continue
        consumer_batch_ids = module_batches.get(consumer, [])
        provider_batch_ids = set(module_batches.get(provider, []))
        if not consumer_batch_ids or not provider_batch_ids:
            missing_provider_paths.append(
                f"{consumer}->{provider} ({contract_id}): missing consumer/provider batches"
            )
            continue
        for consumer_batch_id in consumer_batch_ids:
            if reachable(consumer_batch_id).isdisjoint(provider_batch_ids):
                missing_provider_paths.append(
                    f"{consumer_batch_id} missing provider path {provider} ({contract_id})"
                )
    if missing_provider_paths:
        reasons.append("Missing provider dependency paths: " + "; ".join(sorted(set(missing_provider_paths))))
    else:
        checks.append("provider_dependency_paths_ok")

    return {"status": "passed" if not reasons else "failed", "checks": checks, "reasons": reasons}


def _build_briefs(
    rows: list[dict[str, str]],
    anchor_plans: dict[str, dict[str, Any]],
    link_plan: dict[str, Any],
    batch_plan: dict[str, Any],
    impl: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build batch briefs from selected rows and planning/linking artifacts."""
    by_spec = {row["spec_id"]: row for row in rows}
    contracts = link_plan.get("contracts", []) if isinstance(link_plan.get("contracts"), list) else []
    bindings = link_plan.get("bindings", []) if isinstance(link_plan.get("bindings"), list) else []
    required_intent_specs: dict[tuple[str, str], set[str]] = {}
    provided_intent_specs: dict[tuple[str, str], set[str]] = {}
    for module_tag, plan in anchor_plans.items():
        if not isinstance(plan, dict):
            continue
        for intent in plan.get("required_intents", []):
            if not isinstance(intent, dict):
                continue
            key = (str(module_tag), str(intent.get("intent_local_id", "")).strip())
            if key[1]:
                required_intent_specs[key] = {
                    str(spec_id).strip()
                    for spec_id in intent.get("spec_ids", [])
                    if str(spec_id).strip()
                }
        for intent in plan.get("provided_intents", []):
            if not isinstance(intent, dict):
                continue
            key = (str(module_tag), str(intent.get("intent_local_id", "")).strip())
            if key[1]:
                provided_intent_specs[key] = {
                    str(spec_id).strip()
                    for spec_id in intent.get("spec_ids", [])
                    if str(spec_id).strip()
                }

    briefs: list[dict[str, Any]] = []
    for batch in batch_plan.get("batches", []):
        if not isinstance(batch, dict):
            continue
        kind = str(batch.get("kind", "module_impl"))
        modules = [str(m) for m in batch.get("module_tags", [])]
        spec_ids = [str(s) for s in batch.get("spec_ids", [])]
        spec_id_set = set(spec_ids)
        constraints = {
            "forbidden_paths": impl["forbidden_paths"],
            "budgets_applied": impl["budgets"],
            "verification_commands": impl["verification_commands"],
            "traceability_rules": {"require_spec_ids_per_diff": True},
        }
        if kind == "integration":
            briefs.append(
                {
                    "batch_id": batch["batch_id"],
                    "spec_rows": [],
                    "relevant_contracts": contracts,
                    "relevant_bindings": bindings,
                    "planned_anchors": [],
                    "integration_actions": link_plan.get("integration_actions", []),
                    "constraints": constraints,
                }
            )
            continue

        relevant_bindings = []
        contract_ids: set[str] = set()
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            req = binding.get("required_ref") if isinstance(binding.get("required_ref"), dict) else {}
            prov = binding.get("provided_ref") if isinstance(binding.get("provided_ref"), dict) else {}
            req_module = str(req.get("module_tag", "")).strip()
            req_intent = str(req.get("intent_local_id", "")).strip()
            prov_module = str(prov.get("module_tag", "")).strip()
            prov_intent = str(prov.get("intent_local_id", "")).strip()

            include = False
            if req_module in modules:
                req_specs = required_intent_specs.get((req_module, req_intent), set())
                include = not req_specs or not spec_id_set.isdisjoint(req_specs)
            if not include and prov_module in modules:
                prov_specs = provided_intent_specs.get((prov_module, prov_intent), set())
                include = not prov_specs or not spec_id_set.isdisjoint(prov_specs)
            if include:
                relevant_bindings.append(binding)
                contract_ids.add(str(binding.get("contract_id", "")))
        anchors = []
        for module in modules:
            anchors.extend(
                [
                    anchor
                    for anchor in anchor_plans.get(module, {}).get("planned_anchors", [])
                    if isinstance(anchor, dict)
                    and not spec_id_set.isdisjoint(
                        {
                            str(spec_id).strip()
                            for spec_id in anchor.get("spec_ids", [])
                            if str(spec_id).strip()
                        }
                    )
                ]
            )
        briefs.append(
            {
                "batch_id": batch["batch_id"],
                "spec_rows": [by_spec[s] for s in spec_ids if s in by_spec],
                "relevant_contracts": [
                    c
                    for c in contracts
                    if isinstance(c, dict) and str(c.get("contract_id", "")) in contract_ids
                ],
                "relevant_bindings": relevant_bindings,
                "planned_anchors": anchors,
                "constraints": constraints,
            }
        )
    return briefs


def _collect_spec_output(output: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate and normalize spec-keyed implement output entries."""
    if not isinstance(output.get("run_summary"), dict):
        raise ValueError("Implement output must include run_summary for non-manual responses")
    parsed: dict[str, dict[str, Any]] = {}
    for key, value in output.items():
        if key == "run_summary":
            continue
        if not re.fullmatch(r"^[A-Za-z][0-9]+$", str(key)):
            raise ValueError(f"Invalid implement output key: {key}")
        if not isinstance(value, dict):
            raise ValueError(f"Spec entry for {key} must be an object")
        if not isinstance(value.get("diffs"), list):
            raise ValueError(f"Spec entry for {key} must include diffs[]")
        parsed[str(key)] = value
    return parsed


def _collect_and_copy_patches(
    root: Path,
    paths: dict[str, Path],
    batch_id: str,
    parsed: dict[str, dict[str, Any]],
    constraints: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """Validate/copy patch files and enforce forbidden-path + budget constraints."""
    forbidden = (
        [str(p).replace("\\", "/").strip("/") for p in constraints.get("forbidden_paths", []) if str(p).strip()]
        if isinstance(constraints.get("forbidden_paths", []), list)
        else []
    )
    budgets = constraints.get("budgets_applied", {}) if isinstance(constraints.get("budgets_applied", {}), dict) else {}
    max_files = int(budgets.get("max_files", _DEFAULT_BUDGETS["max_files"]))
    max_lines = int(budgets.get("max_lines_changed", _DEFAULT_BUDGETS["max_lines_changed"]))
    copied: list[str] = []
    touched_all: list[str] = []
    for spec_id, payload in parsed.items():
        for diff in payload.get("diffs", []):
            if not isinstance(diff, dict):
                continue
            diff_id = str(diff.get("diff_id", "")).strip() or f"{spec_id}_diff"
            raw_path = str(diff.get("diff_path", "")).strip()
            source = (root / raw_path).resolve() if raw_path and not Path(raw_path).is_absolute() else Path(raw_path)
            if not source.exists():
                raise ValueError(f"Missing diff_path for {spec_id}:{diff_id}: {raw_path}")
            touched = [str(p).replace("\\", "/") for p in diff.get("touched_files", []) if str(p).strip()]
            if not touched:
                raise ValueError(f"Diff {diff_id} for {spec_id} missing touched_files")
            if len(set(touched)) > max_files:
                raise ValueError(f"Diff {diff_id} exceeds max_files budget")
            for path in touched:
                for prefix in forbidden:
                    if prefix and path.strip("/").lower().startswith(prefix.lower()):
                        raise ValueError(f"Diff {diff_id} touches forbidden path {path}")
            line_count = sum(
                1
                for line in source.read_text(encoding="utf-8", errors="replace").splitlines()
                if line.startswith("+") or line.startswith("-")
            )
            if line_count > max_lines:
                raise ValueError(f"Diff {diff_id} exceeds max_lines_changed budget")
            dest = paths["patches"] / f"{batch_id}_{diff_id}.diff"
            shutil.copy2(source, dest)
            copied.append(str(dest))
            touched_all.extend(touched)
    return copied, sorted(set(touched_all))


def _apply_and_verify(
    root: Path,
    batch_id: str,
    patch_files: list[str],
    verification_commands: Any,
    verification_dir: Path,
) -> dict[str, Any]:
    """Apply patch files and run verification commands in a detached git worktree."""
    if not patch_files:
        return {"success": True, "records": []}
    commands = (
        [str(c) for c in verification_commands if str(c).strip()]
        if isinstance(verification_commands, list)
        else []
    )
    worktree = verification_dir / f"worktree_{batch_id}"
    records: list[dict[str, Any]] = []

    def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=False,
        )

    added = run(["git", "-C", str(root), "worktree", "add", "--detach", str(worktree), "HEAD"])
    if added.returncode != 0:
        return {"success": False, "records": records}
    try:
        for patch in patch_files:
            checked = run(["git", "-C", str(worktree), "apply", "--check", patch])
            if checked.returncode != 0:
                return {"success": False, "records": records}
            applied = run(["git", "-C", str(worktree), "apply", patch])
            if applied.returncode != 0:
                return {"success": False, "records": records}
        for idx, command in enumerate(commands, start=1):
            proc = subprocess.run(
                command,
                cwd=str(worktree),
                capture_output=True,
                text=True,
                shell=True,
                check=False,
            )
            log = verification_dir / f"{batch_id}_verify_{idx}.log"
            log.write_text(
                f"$ {command}\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}\n",
                encoding="utf-8",
            )
            records.append({"command": command, "exit_code": proc.returncode, "log_ref": str(log)})
            if proc.returncode != 0:
                return {"success": False, "records": records}
        for patch in patch_files:
            main_apply = run(["git", "-C", str(root), "apply", patch])
            if main_apply.returncode != 0:
                return {"success": False, "records": records}
        return {"success": True, "records": records}
    finally:
        run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)])


def _hashes(root: Path, relative_paths: list[str]) -> list[dict[str, str]]:
    """Return SHA-256 hashes for files that currently exist under project root."""
    hashed: list[dict[str, str]] = []
    for rel in relative_paths:
        path = (root / rel).resolve()
        if path.exists() and path.is_file():
            hashed.append({"path": rel, "sha256": _sha256(path.read_bytes())})
    return hashed


def _execute_batch(
    config: dict[str, Any],
    ctx: RuntimeContext,
    impl: dict[str, Any],
    schema_path: Path,
    root: Path,
    context_text: str,
    paths: dict[str, Path],
    design_headers: list[str],
    brief: dict[str, Any],
) -> dict[str, Any]:
    """Execute implementer for one batch, apply/verify patches, and append trace records."""
    codebase = resolve_codebase_dir_path(config, root, ctx)
    codebase_content = (
        build_codebase_snapshot(codebase, config, command="implement")
        if get_agent_provider(config) == "api"
        else ""
    )
    spec_rows = brief.get("spec_rows", []) if isinstance(brief.get("spec_rows", []), list) else []
    csv_rows = [{h: (row.get(h, "") if isinstance(row, dict) else "") for h in design_headers} for row in spec_rows]
    specs_csv = rows_to_csv(design_headers, csv_rows)

    artifacts = resolve_agent_artifacts_dir_for_command(config, root, "implement", ctx.run_id)
    artifacts.mkdir(parents=True, exist_ok=True)

    output = invoke_agent_with_schema_retry(
        prompt_name=impl["prompt_name"],
        template_vars={
            "output_schema_file": str(schema_path),
            "project_context": context_text,
            "selected_specs_csv": specs_csv,
            "design_spec_column_definitions": get_design_spec_column_definitions(),
            "indexed_mappings_csv": specs_csv,
            "codebase_dir": str(codebase),
            "codebase_content": codebase_content,
            "manual_resolution_file": str(paths["manual"]),
            "run_summary_file": str(paths["run"] / "summary.json"),
            "agent_artifacts_dir": str(artifacts),
            "batch_brief_json": json.dumps(brief, indent=2),
        },
        schema_path=schema_path,
        config=config,
        ctx=ctx,
    )
    _write_json(paths["agent_outputs"] / f"implement_{brief['batch_id']}.json", output)
    if _manual_block(output, paths["manual"], f"implement_{brief['batch_id']}"):
        return {"status": "blocked", "blocking_items": len(output.get("manual_resolution_items", []))}

    parsed = _collect_spec_output(output)
    patch_paths, touched_files = _collect_and_copy_patches(
        root,
        paths,
        brief["batch_id"],
        parsed,
        brief.get("constraints", {}),
    )
    before = _hashes(root, touched_files)
    verify = _apply_and_verify(
        root,
        brief["batch_id"],
        patch_paths,
        brief.get("constraints", {}).get("verification_commands", []),
        paths["verification"],
    )
    if not verify["success"]:
        return {"status": "failed", "reason": f"verification_failed_{brief['batch_id']}"}

    after = _hashes(root, touched_files)
    trace = {
        "run_id": ctx.run_id,
        "batch_id": brief["batch_id"],
        "spec_ids": sorted(parsed.keys()),
        "diff_sha256": _sha256(
            "\n".join(Path(p).read_text(encoding="utf-8") for p in patch_paths).encode("utf-8")
        )
        if patch_paths
        else "",
        "before_hashes": before,
        "after_hashes": after,
        "verification": verify["records"],
        "artifacts": [{"kind": "patch", "ref": f"patches/{Path(p).name}"} for p in patch_paths],
    }
    with (paths["trace"] / "trace.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(trace, separators=(",", ":")) + "\n")
    return {"status": "completed", "spec_outputs": parsed}


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read rows from CSV file into dictionaries."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _write_csv_rows(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    """Write dictionary rows to CSV with explicit headers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})


def _next_test_id(rows: list[dict[str, str]]) -> int:
    """Return next numeric suffix for test_id values formatted as T{N}."""
    max_value = 0
    for row in rows:
        match = re.fullmatch(r"T(\d+)", str(row.get("test_id", "")).strip())
        if match:
            max_value = max(max_value, int(match.group(1)))
    return max_value + 1


def _backup_file(config: dict[str, Any], ctx: RuntimeContext, root: Path, source: Path, category: str) -> None:
    """Create timestamped backup copy when source file exists."""
    if not source.exists() or not source.is_file():
        return
        backups = resolve_output_path(
            config, root, "backups_dir", command="implement"
        ) or (root / "out" / "backups")
    destination = backups / category
    destination.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix or ".csv"
    name = f"{source.stem}_{format_timestamp_local_minutes_filename()}_{ctx.run_id[:8]}{suffix}"
    shutil.copy2(source, destination / name)


def _update_design_and_test_spec(
    config: dict[str, Any],
    ctx: RuntimeContext,
    impl: dict[str, Any],
    design_path: Path,
    spec_outputs: dict[str, dict[str, Any]],
) -> None:
    """Update design spec mapped columns and maintain deduplicated test_spec CSV."""
    if not spec_outputs:
        return
    root = Path(ctx.project_root)
    headers, rows = load_sads_csv_or_xlsx(design_path)
    spec_col = _find_col(headers, "spec_id")
    if spec_col is None:
        raise ValueError("Design spec missing spec_id; cannot apply implement mappings")
    if _find_col(headers, "mapped_code_symbols") is None:
        headers.append("mapped_code_symbols")
        for row in rows:
            row["mapped_code_symbols"] = ""
    if _find_col(headers, "mapped_test_cases") is None:
        headers.append("mapped_test_cases")
        for row in rows:
            row["mapped_test_cases"] = ""
    map_col = _find_col(headers, "mapped_code_symbols") or "mapped_code_symbols"
    test_col = _find_col(headers, "mapped_test_cases") or "mapped_test_cases"
    by_spec = {str(row.get(spec_col, "")).strip(): row for row in rows}

    test_path = (
        Path(impl["test_spec_path"])
        if Path(impl["test_spec_path"]).is_absolute()
        else (root / impl["test_spec_path"]).resolve()
    )
    test_rows = _read_csv_rows(test_path) if test_path.exists() else []
    tuple_to_id = {
        (str(row.get("framework", "")), str(row.get("test_file", "")), str(row.get("test_case", ""))): str(row.get("test_id", ""))
        for row in test_rows
        if str(row.get("test_id", "")).strip()
    }
    next_id = _next_test_id(test_rows)

    for spec_id, payload in spec_outputs.items():
        row = by_spec.get(spec_id)
        if row is None:
            continue
        symbols = [
            str(item.get("qualified_name", "")).strip()
            for item in payload.get("mapped_classes_functions", [])
            if isinstance(item, dict) and str(item.get("qualified_name", "")).strip()
        ]
        row[map_col] = ",".join(symbols)
        mapped_ids: list[str] = []
        for item in payload.get("mapped_test_cases", []):
            if not isinstance(item, dict):
                continue
            key = (
                str(item.get("framework", "")).strip(),
                str(item.get("test_file", "")).strip(),
                str(item.get("test_case", "")).strip(),
            )
            if not all(key):
                continue
            test_id = tuple_to_id.get(key)
            if not test_id:
                test_id = f"T{next_id}"
                next_id += 1
                tuple_to_id[key] = test_id
                test_rows.append(
                    {
                        "test_id": test_id,
                        "test_name": key[2],
                        "test_description": "",
                        "framework": key[0],
                        "test_file": key[1],
                        "test_case": key[2],
                    }
                )
            mapped_ids.append(test_id)
        row[test_col] = ",".join(mapped_ids)

    _backup_file(config, ctx, root, design_path, "implement")
    design_path.write_text(rows_to_csv(headers, rows), encoding="utf-8")
    _backup_file(config, ctx, root, test_path, "implement")
    _write_csv_rows(test_path, _TEST_SPEC_HEADERS, test_rows)
