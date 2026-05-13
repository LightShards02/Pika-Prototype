"""Shared dependencies: store singletons and config loading."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Request

from api.events import PhaseRunEventBus
from api.phase_registry import PhaseRegistry, get_phase_registry
from api.phase_runs import PhaseRunRegistry
from api.workspace_lock import WorkspaceLockManager
from api.workspaces import WorkspaceStore
from core.config_loader import load_and_validate_config
from core.pika_paths import get_config_schema_path


_PIKA_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _PIKA_BACKEND_ROOT.parent


def repo_root() -> Path:
    """Return the repo root (parent of backend/)."""
    return _REPO_ROOT


def api_state_dir() -> Path:
    override = os.environ.get("PIKA_API_STATE_DIR")
    if override:
        return Path(override).resolve()
    return (_REPO_ROOT / "out" / "api_state").resolve()


def workspace_registry_path() -> Path:
    return api_state_dir() / "workspaces.json"


def load_workspace_config(workspace_path: Path) -> dict[str, Any] | None:
    """Resolve and load the workspace's config.yaml; return None if not present."""
    from core.pika_config import get_pika_config

    try:
        candidates = get_pika_config().get("config_candidates") or []
    except Exception:
        candidates = []
    for c in candidates:
        if not isinstance(c, str):
            continue
        candidate = (workspace_path / c).resolve()
        if candidate.is_file():
            schema_path = get_config_schema_path()
            return load_and_validate_config(candidate, schema_path=schema_path)
    return None


def get_workspace_store(request: Request) -> WorkspaceStore:
    return request.app.state.workspace_store


def get_phase_run_registry(request: Request) -> PhaseRunRegistry:
    return request.app.state.phase_run_registry


def get_phase_registry_dep(request: Request) -> PhaseRegistry:
    return request.app.state.phase_registry


def get_event_bus(request: Request) -> PhaseRunEventBus:
    return request.app.state.event_bus


def get_workspace_lock_manager(request: Request) -> WorkspaceLockManager:
    return request.app.state.workspace_lock_manager
