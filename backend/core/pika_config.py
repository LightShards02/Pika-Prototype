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


def _validate_local_model_profile(
    profile: Any,
    path: str,
    missing: list[str],
    *,
    require_name: bool,
) -> None:
    """Validate one nested ``local.model`` profile object."""
    if not isinstance(profile, dict):
        missing.append(path)
        return

    name = profile.get("name")
    if require_name:
        _require_non_empty_string(name, f"{path}.name", missing)
    elif name is not None:
        _require_non_empty_string(name, f"{path}.name", missing)

    reasoning_effort = profile.get("reasoning_effort")
    if reasoning_effort is not None:
        _require(
            isinstance(reasoning_effort, str)
            and reasoning_effort in ("low", "medium", "high", "xhigh"),
            f"{path}.reasoning_effort",
            missing,
        )

    model_verbosity = profile.get("model_verbosity")
    if model_verbosity is not None:
        _require_non_empty_string(model_verbosity, f"{path}.model_verbosity", missing)

    if "web_search" in profile:
        _require(isinstance(profile.get("web_search"), bool), f"{path}.web_search", missing)

    # base_url is optional; when present, it must be a non-empty string
    if "base_url" in profile:
        base_url = profile.get("base_url")
        if base_url is not None:
            _require_non_empty_string(base_url, f"{path}.base_url", missing)

    for field_name, minimum, maximum in (("temperature", 0, 2), ("top_p", 0, 1)):
        value = profile.get(field_name)
        if value is None and field_name in profile:
            continue
        if value is not None:
            _require(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and minimum <= float(value) <= maximum,
                f"{path}.{field_name}",
                missing,
            )


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
    _require(isinstance(cfg.get("commands"), dict), "commands", missing)
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
        _require(isinstance(local.get("heartbeat_interval_sec"), (int, float)), "local.heartbeat_interval_sec", missing)
        _require(isinstance(local.get("exec_timeout_sec"), (int, float)), "local.exec_timeout_sec", missing)
        _require_non_empty_string(local.get("temp_workspace_prefix"), "local.temp_workspace_prefix", missing)
        _require(isinstance(local.get("temp_workspace_ttl_sec"), (int, float)), "local.temp_workspace_ttl_sec", missing)
        model = local.get("model")
        if model is None:
            missing.append("local.model")
        elif isinstance(model, dict):
            default_profile = model.get("default")
            _validate_local_model_profile(
                default_profile,
                "local.model.default",
                missing,
                require_name=True,
            )
            for key, value in model.items():
                if key == "default":
                    continue
                if not isinstance(key, str) or not key.strip():
                    missing.append("local.model.<agent_name>")
                    continue
                _validate_local_model_profile(
                    value,
                    f"local.model.{key}",
                    missing,
                    require_name=False,
                )
        else:
            missing.append("local.model (must be object with default profile)")

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

    if isinstance(cfg.get("commands"), dict):
        cmds = cfg["commands"]
        # plan
        plan_cmd = cmds.get("plan") if isinstance(cmds.get("plan"), dict) else {}
        _require_non_empty_string(plan_cmd.get("prompt_names"), "commands.plan.prompt_names", missing)
        # format
        fmt_cmd = cmds.get("format") if isinstance(cmds.get("format"), dict) else {}
        fmt_pn = fmt_cmd.get("prompt_names")
        _require(isinstance(fmt_pn, dict), "commands.format.prompt_names", missing)
        if isinstance(fmt_pn, dict):
            _require_non_empty_string(fmt_pn.get("enricher"), "commands.format.prompt_names.enricher", missing)
        # review
        review_cmd = cmds.get("review") if isinstance(cmds.get("review"), dict) else {}
        _require_non_empty_string(review_cmd.get("prompt_names"), "commands.review.prompt_names", missing)
        # map
        map_cmd = cmds.get("map") if isinstance(cmds.get("map"), dict) else {}
        map_pn = map_cmd.get("prompt_names")
        _require(isinstance(map_pn, dict), "commands.map.prompt_names", missing)
        if isinstance(map_pn, dict):
            _require_non_empty_string(map_pn.get("default"), "commands.map.prompt_names.default", missing)
            _require_non_empty_string(map_pn.get("local"), "commands.map.prompt_names.local", missing)
        # implement
        impl_cmd = cmds.get("implement") if isinstance(cmds.get("implement"), dict) else {}
        _require(isinstance(impl_cmd, dict) and impl_cmd, "commands.implement", missing)
        if isinstance(impl_cmd, dict):
            _require(
                isinstance(impl_cmd.get("min_confidence_threshold"), (int, float)),
                "commands.implement.min_confidence_threshold",
                missing,
            )
            impl_pn = impl_cmd.get("prompt_names")
            _require(isinstance(impl_pn, dict), "commands.implement.prompt_names", missing)
            if isinstance(impl_pn, dict):
                _require(isinstance(impl_pn.get("implementer"), dict), "commands.implement.prompt_names.implementer", missing)
                if isinstance(impl_pn.get("implementer"), dict):
                    _require_non_empty_string(impl_pn["implementer"].get("default"), "commands.implement.prompt_names.implementer.default", missing)
                    _require_non_empty_string(impl_pn["implementer"].get("local"), "commands.implement.prompt_names.implementer.local", missing)
                _require_non_empty_string(impl_pn.get("unified_planner"), "commands.implement.prompt_names.unified_planner", missing)
        # resolve_plan
        rp_cmd = cmds.get("resolve_plan") if isinstance(cmds.get("resolve_plan"), dict) else {}
        rp_pn = rp_cmd.get("prompt_names")
        _require(isinstance(rp_pn, dict), "commands.resolve_plan.prompt_names", missing)
        if isinstance(rp_pn, dict):
            _require_non_empty_string(rp_pn.get("map"), "commands.resolve_plan.prompt_names.map", missing)
            _require_non_empty_string(rp_pn.get("resolve"), "commands.resolve_plan.prompt_names.resolve", missing)
        # refine
        refine_cmd = cmds.get("refine") if isinstance(cmds.get("refine"), dict) else {}
        refine_pn = refine_cmd.get("prompt_names")
        _require(isinstance(refine_pn, dict), "commands.refine.prompt_names", missing)
        if isinstance(refine_pn, dict):
            for sub in ("quality_auditor", "spec_editor"):
                _require_non_empty_string(refine_pn.get(sub), f"commands.refine.prompt_names.{sub}", missing)

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
    pn = get_pika_config()["commands"][command]["prompt_names"]
    node = pn

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
