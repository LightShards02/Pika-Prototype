"""PIKA-internal path resolution.

Distinguishes two roots:
1. **PIKA root** — parent of cli.py; contains PIKA source, schemas, contracts, prompts.
   All project-independent paths are relative to this.
2. **Workspace root** — the project PIKA is used to build; contains project config,
   runtime outputs, inputs. All project-variable paths are relative to this.

Sanity check: if a file/dir is project-independent, it lives under PIKA root;
if it may vary per project, it lives under workspace root.
"""

from __future__ import annotations

from pathlib import Path

# PIKA root: parent of core/ (the PIKA project directory, same as parent of cli.py)
# Always contains: config/, core/, handlers/, prompts/, schemas/, docs/, tests/
PIKA_ROOT = Path(__file__).resolve().parent.parent

def _pika_path(key: str) -> Path:
    """Return path from pika config paths section, else built-in default."""
    from core.pika_config import get_pika_config

    paths = get_pika_config().get("paths", {})
    defaults = {
        "config_schema": "config/config.schema.json",
        "csv_contracts": "docs/csv_contracts.md",
        "project_context_contracts": "docs/project_context_contracts.md",
        "prompts_file": "prompts/PROMPT.yaml",
        "schemas_dir": "schemas/agent_outputs",
    }
    rel = paths.get(key, defaults.get(key, ""))
    return (PIKA_ROOT / rel).resolve()


def get_config_schema_path() -> Path:
    """Return path to PIKA config schema (project-independent)."""
    return _pika_path("config_schema")


def get_csv_contracts_path() -> Path:
    """Return path to docs/csv_contracts.md (project-independent)."""
    return _pika_path("csv_contracts")


def get_project_context_contracts_path() -> Path:
    """Return path to docs/project_context_contracts.md (project-independent)."""
    return _pika_path("project_context_contracts")


def get_default_prompts_path() -> Path:
    """Return default path to prompts/PROMPT.yaml under PIKA root."""
    return _pika_path("prompts_file")


def get_default_schema_path(schema_name: str) -> Path | None:
    """Return default path to a schema file under PIKA root, or None if unknown."""
    from core.pika_config import get_pika_config

    cfg = get_pika_config()
    schema_map = cfg.get("schema_map", {})
    schemas_dir = cfg.get("paths", {}).get("schemas_dir", "schemas/agent_outputs")
    filename = schema_map.get(schema_name)
    if not filename:
        return None
    return (PIKA_ROOT / schemas_dir / filename).resolve()


def resolve_prompts_path(config_value: str, *, pika_root: Path = PIKA_ROOT) -> Path:
    """Resolve prompts.prompt_file from PIKA root only.

    Prompt templates are project-independent; only template variables vary per project.
    """
    candidate = Path(config_value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (pika_root / candidate).resolve()


def resolve_schema_path(
    config_value: str,
    schema_key: str,
    workspace_root: Path,
    *,
    pika_root: Path = PIKA_ROOT,
) -> Path:
    """Resolve schema path: try workspace first, fallback to PIKA root."""
    candidate = Path(config_value)
    if candidate.is_absolute():
        return candidate.resolve()
    workspace_path = (workspace_root / candidate).resolve()
    if workspace_path.exists() and workspace_path.is_file():
        return workspace_path
    default = get_default_schema_path(schema_key)
    if default is not None and default.exists():
        return default
    return workspace_path  # For clearer error messages


def resolve_path_from_pika_root(
    path_value: str | Path, *, pika_root: Path = PIKA_ROOT
) -> Path:
    """Resolve path from PIKA root only. For prompts' output_schema_file (project-independent)."""
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (pika_root / candidate).resolve()
