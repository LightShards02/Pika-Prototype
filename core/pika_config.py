"""Load PIKA-level configuration (project-independent).

No schema validation. Provides defaults for hardcoded values.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# PIKA root: parent of core/
_PIKA_ROOT = Path(__file__).resolve().parent.parent
_PIKA_CONFIG_PATH = _PIKA_ROOT / "config" / "pika.yaml"

# In-memory cache
_pika_config: dict[str, Any] | None = None


def _load_raw() -> dict[str, Any]:
    """Load pika.yaml. Returns empty dict if missing or on error."""
    try:
        import yaml
    except ImportError:
        return {}
    if not _PIKA_CONFIG_PATH.exists() or not _PIKA_CONFIG_PATH.is_file():
        return {}
    try:
        loaded = yaml.safe_load(_PIKA_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if loaded is None or not isinstance(loaded, dict):
        return {}
    return loaded


def load_pika_config() -> dict[str, Any]:
    """Load and cache PIKA config. Returns merged config with built-in defaults."""
    global _pika_config
    if _pika_config is not None:
        return _pika_config

    defaults: dict[str, Any] = {
        "paths": {
            "config_schema": "config/config.schema.json",
            "csv_contracts": "docs/csv_contracts.md",
            "project_context_contracts": "docs/project_context_contracts.md",
            "prompts_file": "prompts/PROMPT.yaml",
            "schemas_dir": "schemas/agent_outputs",
        },
        "schema_map": {
            "plan_output": "plan_output.schema.json",
            "map_output": "index_output.schema.json",
            "implement_output": "implement_output.schema.json",
            "resolve_plan_map_output": "issue_map_output.schema.json",
            "resolve_plan_output": "issue_resolve_output.schema.json",
            "handshake_output": "handshake_output.schema.json",
        },
        "config_candidates": ["config.yaml", "config/config.yaml", "config/config.example.yaml"],
        "api": {
            "url": "https://integrate.api.nvidia.com/v1/chat/completions",
            "model": "moonshotai/kimi-k2.5",
            "api_key_env": "NVIDIA_API_KEY",
            "request_timeout_sec": 600,
            "map": {"max_tokens": 32768, "temperature": 0.1, "top_p": 0.95},
            "default": {"max_tokens": 16384, "temperature": 0.7, "top_p": 1.0},
        },
        "local": {
            "command": "codex",
            "ps1_path_windows": str(Path.home() / "AppData" / "Roaming" / "npm" / "codex.ps1"),
            "heartbeat_interval_sec": 30,
            "exec_timeout_sec": 600,
        },
        "default_outputs": {
            "log_dir": "out/logs",
            "state_dir": "out/state",
            "sads_id_mapping": "out/state/sads_id_mapping.json",
            "id_registry": "out/state/id_registry.json",
            "intermediate_map_dir": "out/intermediate/map",
            "agent_input_codebase_content_dir": "out/agent_input/codebase_content",
        },
        "stub": {"plan_proposed_sads": "out/agent_artifacts/stub/plan_proposed_sads.csv"},
        "codebase_transmission": {
            "max_summary_chars": 200_000,
            "max_raw_files": 10,
            "max_raw_chars_per_file": 5_000,
            "include_extensions": [".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rs", ".c", ".cpp", ".h", ".hpp"],
            "exclude_patterns": [
                "**/__pycache__/**",
                "**/.git/**",
                "**/node_modules/**",
                "**/venv/**",
                "**/dist/**",
                "**/build/**",
                "**/*.min.js",
            ],
            "depth_limit": 15,
        },
    }

    def _merge(base: dict, override: dict) -> dict:
        out = dict(base)
        for k, v in override.items():
            if k in out and isinstance(out[k], dict) and isinstance(v, dict):
                out[k] = _merge(out[k], v)
            else:
                out[k] = v
        return out

    loaded = _load_raw()
    _pika_config = _merge(defaults, loaded)
    return _pika_config


def get_pika_config() -> dict[str, Any]:
    """Return loaded PIKA config (cached)."""
    return load_pika_config()


def reset_pika_config_cache() -> None:
    """Reset cache (for tests)."""
    global _pika_config
    _pika_config = None
