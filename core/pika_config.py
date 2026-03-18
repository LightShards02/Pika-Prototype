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
    _require(isinstance(cfg.get("api"), dict), "api", missing)
    _require(isinstance(cfg.get("local"), dict), "local", missing)
    _require(isinstance(cfg.get("default_outputs"), dict), "default_outputs", missing)
    _require(isinstance(cfg.get("default_workspace"), dict), "default_workspace", missing)
    _require(isinstance(cfg.get("implement"), dict), "implement", missing)
    _require(isinstance(cfg.get("codebase_transmission"), dict), "codebase_transmission", missing)
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

    if isinstance(cfg.get("api"), dict):
        api = cfg["api"]
        _require_non_empty_string(api.get("url"), "api.url", missing)
        _require_non_empty_string(api.get("model"), "api.model", missing)
        _require_non_empty_string(api.get("api_key_env"), "api.api_key_env", missing)
        _require(isinstance(api.get("request_timeout_sec"), (int, float)), "api.request_timeout_sec", missing)
        _require(isinstance(api.get("map"), dict), "api.map", missing)
        _require(isinstance(api.get("default"), dict), "api.default", missing)
        if isinstance(api.get("map"), dict):
            for key in ("max_tokens", "temperature", "top_p"):
                _require(key in api["map"], f"api.map.{key}", missing)
        if isinstance(api.get("default"), dict):
            for key in ("max_tokens", "temperature", "top_p"):
                _require(key in api["default"], f"api.default.{key}", missing)

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

    if isinstance(cfg.get("stub"), dict):
        _require_non_empty_string(cfg["stub"].get("plan_proposed_sads"), "stub.plan_proposed_sads", missing)

    if isinstance(cfg.get("codebase_transmission"), dict):
        codebase = cfg["codebase_transmission"]
        for key in (
            "max_summary_chars",
            "max_raw_files",
            "max_raw_chars_per_file",
            "depth_limit",
        ):
            _require(isinstance(codebase.get(key), int), f"codebase_transmission.{key}", missing)
        _require(isinstance(codebase.get("include_extensions"), list), "codebase_transmission.include_extensions", missing)
        _require(isinstance(codebase.get("exclude_patterns"), list), "codebase_transmission.exclude_patterns", missing)

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


def reset_pika_config_cache() -> None:
    """Reset cache (for tests)."""
    global _pika_config
    _pika_config = None
