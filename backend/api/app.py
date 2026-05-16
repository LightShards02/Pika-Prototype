"""FastAPI app factory for PIKA's phase REST API."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.deps import api_state_dir, load_workspace_config, repo_root, workspace_registry_path
from api.errors import error_body
from api.events import PhaseRunEventBus
from api.phase_registry import get_phase_registry
from api.phase_runs import PhaseRunRegistry
from api.routers import documents as documents_router
from api.routers import phase_runs as phase_runs_router
from api.routers import phases as phases_router
from api.routers import workspaces as workspaces_router
from api.workspace_lock import WorkspaceLockManager
from api.workspaces import WorkspaceStore
from core.lifecycle import resolve_agent_runs_root


def register_phases() -> None:
    """Import and register all known phases (side effects on import)."""
    from api.phases import (
        format_normalize,
        implement_unified_planner,
        map_match,
        refine_decomposition_check,
        refine_quality_audit,
    )

    format_normalize.register()
    refine_decomposition_check.register()
    refine_quality_audit.register()
    implement_unified_planner.register()
    map_match.register()


def _agent_runs_roots_for_known_workspaces(store: WorkspaceStore) -> list[Path]:
    """Return phase-run base dirs for all registered workspaces.

    Loads each workspace's config and resolves the agent-runs root via the
    lifecycle helper (which honors any workspace-level config override and
    falls back to ``<workspace>/out/agent_runs``). On config-load failure,
    falls back to the default path directly. Deduped; only existing
    directories are returned.
    """
    roots: set[Path] = set()
    for record in store.list():
        workspace_path = Path(record.path)
        root: Path
        try:
            config = load_workspace_config(workspace_path)
        except Exception:
            config = None
        if config is not None:
            try:
                root = resolve_agent_runs_root(config, workspace_path)
            except Exception:
                root = (workspace_path / "out" / "agent_runs").resolve()
        else:
            root = (workspace_path / "out" / "agent_runs").resolve()
        roots.add(root)
    return [r for r in roots if r.is_dir()]


def create_app() -> FastAPI:
    app = FastAPI(title="PIKA REST API", version="0.1.0")

    api_state_dir().mkdir(parents=True, exist_ok=True)
    workspace_store = WorkspaceStore(workspace_registry_path())
    phase_run_registry = PhaseRunRegistry()

    register_phases()

    phase_run_registry.reflect_from_disk(
        _agent_runs_roots_for_known_workspaces(workspace_store)
    )

    app.state.repo_root = repo_root()
    app.state.workspace_store = workspace_store
    app.state.phase_run_registry = phase_run_registry
    app.state.phase_registry = get_phase_registry()
    app.state.event_bus = PhaseRunEventBus()
    app.state.workspace_lock_manager = WorkspaceLockManager()

    app.include_router(workspaces_router.router)
    app.include_router(documents_router.router)
    app.include_router(phases_router.router)
    app.include_router(phase_runs_router.router)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": error_body(
                    "request_invalid",
                    "request body failed validation",
                    {"errors": exc.errors()},
                )["error"]
            },
        )

    return app
