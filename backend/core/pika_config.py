"""Load PIKA-level configuration (project-independent)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

# PIKA root: parent of core/
_PIKA_ROOT = Path(__file__).resolve().parent.parent
_PIKA_CONFIG_PATH = _PIKA_ROOT / "config" / "pika.yaml"

# In-memory cache
_pika_config: dict[str, Any] | None = None


def _load_raw() -> dict[str, Any]:
    """Load and parse `config/pika.yaml`.

    Raises for missing file, parse errors, or invalid YAML structure.
    """
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - import-time dependency guard
        raise RuntimeError(
            "PyYAML is required to load PIKA configuration. Install with `pip install pyyaml`."
        ) from exc

    if not _PIKA_CONFIG_PATH.exists() or not _PIKA_CONFIG_PATH.is_file():
        raise FileNotFoundError(
            "Required PIKA config not found. Expected: "
            f"{_PIKA_CONFIG_PATH}. Run from the PIKA repository root."
        )

    try:
        loaded = yaml.safe_load(_PIKA_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(
            f"Unable to parse PIKA config {_PIKA_CONFIG_PATH}: {exc}"
        ) from exc
    if loaded is None or not isinstance(loaded, dict):
        raise ValueError(f"Invalid PIKA config {_PIKA_CONFIG_PATH}: top-level must be a mapping.")
    return loaded


def _require(condition: bool, name: str, missing: list[str]) -> None:
    if not condition:
        missing.append(name)


def _require_non_empty_string(value: Any, path: str, missing: list[str]) -> None:
    _require(isinstance(value, str) and bool(value.strip()), path, missing)


def _validate_required_config(cfg: dict[str, Any]) -> None:
    """Validate that all required PIKA config sections and fields are present."""
    missing: list[str] = []

    _require_non_empty_string(cfg.get("version"), "version", missing)
    _require(isinstance(cfg.get("paths"), dict), "paths", missing)
    _require(isinstance(cfg.get("schema_map"), dict), "schema_map", missing)
    _require(isinstance(cfg.get("config_candidates"), list), "config_candidates", missing)
    _require(isinstance(cfg.get("local"), dict), "local", missing)
    _require(isinstance(cfg.get("default_outputs"), dict), "default_outputs", missing)
    _require(isinstance(cfg.get("default_workspace"), dict), "default_workspace", missing)
    _require(isinstance(cfg.get("implement"), dict), "implement", missing)
    _require(isinstance(cfg.get("stub"), dict), "stub", missing)

    if isinstance(cfg.get("paths"), dict):
        paths = cfg["paths"]
        for key in (
            "config_schema",
            "csv_contracts",
            "project_context_contracts",
            "prompts_file",
            "schemas_dir",
        ):
            _require_non_empty_string(paths.get(key), f"paths.{key}", missing)

    if isinstance(cfg.get("schema_map"), dict):
        schema_map = cfg["schema_map"]
        for key in (
            "plan_output",
            "map_output",
            "implement_output",
            "resolve_plan_map_output",
            "resolve_plan_output",
            "handshake_output",
        ):
            _require_non_empty_string(schema_map.get(key), f"schema_map.{key}", missing)

    if isinstance(cfg.get("local"), dict):
        local = cfg["local"]
        _require_non_empty_string(local.get("command"), "local.command", missing)
        _require(isinstance(local.get("heartbeat_interval_sec"), (int, float)), "local.heartbeat_interval_sec", missing)
        _require(isinstance(local.get("exec_timeout_sec"), (int, float)), "local.exec_timeout_sec", missing)
        _require_non_empty_string(local.get("temp_workspace_prefix"), "local.temp_workspace_prefix", missing)
        _require(isinstance(local.get("temp_workspace_ttl_sec"), (int, float)), "local.temp_workspace_ttl_sec", missing)
        model = local.get("model")
        if model is None:
            missing.append("local.model")
        elif isinstance(model, str):
            _require_non_empty_string(model, "local.model", missing)
        elif isinstance(model, dict):
            _require_non_empty_string(model.get("default"), "local.model.default", missing)
        else:
            missing.append("local.model (must be string or object with default)")

    if isinstance(cfg.get("default_outputs"), dict):
        default_outputs = cfg["default_outputs"]
        for key in (
            "log_dir",
            "state_dir",
            "sads_id_mapping",
            "id_registry",
            "intermediate_map_dir",
            "agent_input_codebase_content_dir",
        ):
            _require_non_empty_string(default_outputs.get(key), f"default_outputs.{key}", missing)

    if isinstance(cfg.get("default_workspace"), dict):
        workspace = cfg["default_workspace"]
        _require(isinstance(workspace.get("project"), dict), "default_workspace.project", missing)
        _require(isinstance(workspace.get("inputs"), dict), "default_workspace.inputs", missing)
        if isinstance(workspace.get("project"), dict):
            state = workspace["project"].get("state")
            _require(isinstance(state, dict), "default_workspace.project.state", missing)
            if isinstance(state, dict):
                for key in (
                    "design_spec_path",
                    "id_registry_path",
                    "sads_id_mapping_path",
                ):
                    _require_non_empty_string(state.get(key), f"default_workspace.project.state.{key}", missing)
        if isinstance(workspace.get("inputs"), dict):
            _require_non_empty_string(
                workspace["inputs"].get("project_context_filename"),
                "default_workspace.inputs.project_context_filename",
                missing,
            )
            extensions = workspace["inputs"].get("allowed_extensions")
            _require(isinstance(extensions, list) and len(extensions) > 0, "default_workspace.inputs.allowed_extensions", missing)

    if isinstance(cfg.get("implement"), dict):
        _require(
            isinstance(cfg["implement"].get("min_confidence_threshold"), (int, float)),
            "implement.min_confidence_threshold",
            missing,
        )

    _require(isinstance(cfg.get("id_generation"), dict), "id_generation", missing)
    if isinstance(cfg.get("id_generation"), dict):
        id_gen = cfg["id_generation"]
        _require(isinstance(id_gen.get("spec"), dict), "id_generation.spec", missing)
        _require(isinstance(id_gen.get("issue"), dict), "id_generation.issue", missing)
        _require_non_empty_string(id_gen.get("collision_scope"), "id_generation.collision_scope", missing)
        if isinstance(id_gen.get("spec"), dict):
            _require_non_empty_string(id_gen["spec"].get("pattern"), "id_generation.spec.pattern", missing)
        if isinstance(id_gen.get("issue"), dict):
            _require_non_empty_string(id_gen["issue"].get("pattern"), "id_generation.issue.pattern", missing)

    _require(isinstance(cfg.get("csv_contracts"), dict), "csv_contracts", missing)
    if isinstance(cfg.get("csv_contracts"), dict):
        csv_c = cfg["csv_contracts"]
        for contract_name in ("design_spec", "issue_tracking"):
            _require(isinstance(csv_c.get(contract_name), dict), f"csv_contracts.{contract_name}", missing)
            contract = csv_c.get(contract_name)
            if isinstance(contract, dict):
                cols = contract.get("add_if_missing")
                _require(
                    isinstance(cols, list) and len(cols) > 0,
                    f"csv_contracts.{contract_name}.add_if_missing",
                    missing,
                )

    _require(isinstance(cfg.get("prompt_names"), dict), "prompt_names", missing)
    if isinstance(cfg.get("prompt_names"), dict):
        pn = cfg["prompt_names"]
        _require_non_empty_string(pn.get("plan"), "prompt_names.plan", missing)
        _require_non_empty_string(pn.get("review"), "prompt_names.review", missing)
        _require(isinstance(pn.get("map"), dict), "prompt_names.map", missing)
        if isinstance(pn.get("map"), dict):
            _require_non_empty_string(pn["map"].get("default"), "prompt_names.map.default", missing)
            _require_non_empty_string(pn["map"].get("local"), "prompt_names.map.local", missing)
        _require(isinstance(pn.get("implement"), dict), "prompt_names.implement", missing)
        if isinstance(pn.get("implement"), dict):
            impl_pn = pn["implement"]
            _require(isinstance(impl_pn.get("implementer"), dict), "prompt_names.implement.implementer", missing)
            if isinstance(impl_pn.get("implementer"), dict):
                _require_non_empty_string(impl_pn["implementer"].get("default"), "prompt_names.implement.implementer.default", missing)
                _require_non_empty_string(impl_pn["implementer"].get("local"), "prompt_names.implement.implementer.local", missing)
            _require_non_empty_string(impl_pn.get("unified_planner"), "prompt_names.implement.unified_planner", missing)
        _require(isinstance(pn.get("resolve_plan"), dict), "prompt_names.resolve_plan", missing)
        if isinstance(pn.get("resolve_plan"), dict):
            _require_non_empty_string(pn["resolve_plan"].get("map"), "prompt_names.resolve_plan.map", missing)
            _require_non_empty_string(pn["resolve_plan"].get("resolve"), "prompt_names.resolve_plan.resolve", missing)
        _require(isinstance(pn.get("refine"), dict), "prompt_names.refine", missing)
        if isinstance(pn.get("refine"), dict):
            for sub in ("ambiguity_detector", "testability_auditor", "spec_editor"):
                _require_non_empty_string(pn["refine"].get(sub), f"prompt_names.refine.{sub}", missing)

    if isinstance(cfg.get("stub"), dict):
        _require_non_empty_string(cfg["stub"].get("plan_proposed_sads"), "stub.plan_proposed_sads", missing)

    if missing:
        raise ValueError(
            "PIKA config is missing required fields: " + ", ".join(sorted(set(missing)))
        )


def load_pika_config() -> dict[str, Any]:
    """Load and cache required PIKA config."""
    global _pika_config
    if _pika_config is not None:
        return _pika_config

    loaded = _load_raw()
    _validate_required_config(loaded)
    _pika_config = loaded
    return _pika_config


def get_pika_config() -> dict[str, Any]:
    """Return loaded PIKA config (cached)."""
    return load_pika_config()


def get_prompt_name(command: str, sub_key: str | None = None, *, provider: str = "stub") -> str:
    """Return prompt name for *command* from pika.yaml prompt_names.

    For commands with provider-specific variants (map, implement.implementer),
    selects the ``local`` variant when *provider* is ``"local"``, otherwise
    the ``default`` variant.

    Args:
        command: Top-level command name (plan, review, map, implement, resolve_plan, refine).
        sub_key: Optional sub-key for commands with multiple prompts
                 (e.g. ``"implementer"``, ``"unified_planner"``, ``"map"``,
                 ``"ambiguity_detector"``).
        provider: Agent provider string (``"stub"`` or ``"local"``).

    Returns:
        Prompt name string.

    Raises:
        KeyError: If the requested prompt_names path does not exist.
    """
    pn = get_pika_config()["prompt_names"]
    node = pn[command]

    if sub_key is not None:
        node = node[sub_key]

    if isinstance(node, str):
        return node

    # dict with default / local variants
    if provider == "local" and "local" in node:
        return node["local"]
    return node["default"]


def reset_pika_config_cache() -> None:
    """Reset cache (for tests)."""
    global _pika_config
    _pika_config = None
