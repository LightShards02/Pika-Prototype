"""Workspace endpoints."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response, status

from api.deps import (
    get_phase_run_registry,
    get_workspace_lock_manager,
    get_workspace_store,
)
from api.errors import http_error
from api.phase_runs import PhaseRunRegistry
from api.schemas.common import PhaseRunState
from api.schemas.phases import PhaseRunResponse
from api.schemas.workspaces import WorkspaceCreateRequest, WorkspaceResponse
from api.workspace_lock import WorkspaceLockManager
from api.workspaces import (
    AbsoluteWorkspacePathError,
    PathEscapesBaseError,
    WorkspaceStore,
)
from core import memory_store

router = APIRouter(prefix="/v1/workspaces", tags=["workspaces"])

_log = logging.getLogger(__name__)


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_200_OK)
def create_workspace(
    payload: WorkspaceCreateRequest,
    store: WorkspaceStore = Depends(get_workspace_store),
) -> WorkspaceResponse:
    try:
        record = store.register(payload.path, seed_config=payload.create)
    except AbsoluteWorkspacePathError as exc:
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "workspace_path_must_be_relative",
            str(exc),
            details={"path": payload.path},
        ) from exc
    except PathEscapesBaseError as exc:
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "workspace_path_escapes_base",
            str(exc),
            details={"path": payload.path},
        ) from exc
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "workspace_invalid",
            str(exc),
            details={"path": payload.path},
        ) from exc
    try:
        memory_store.bootstrap(Path(record.path))
    except OSError as exc:
        _log.warning("memory bootstrap failed for %s: %s", record.path, exc)
    return WorkspaceResponse(**record.to_dict())


@router.get("", response_model=list[WorkspaceResponse])
def list_workspaces(
    store: WorkspaceStore = Depends(get_workspace_store),
) -> list[WorkspaceResponse]:
    records = sorted(store.list(), key=lambda r: r.path)
    return [WorkspaceResponse(**r.to_dict()) for r in records]


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(
    workspace_id: str,
    store: WorkspaceStore = Depends(get_workspace_store),
) -> WorkspaceResponse:
    record = store.get(workspace_id)
    if record is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "workspace_not_found",
            f"workspace {workspace_id!r} not found",
        )
    return WorkspaceResponse(**record.to_dict())


def _require_workspace_root(
    workspace_id: str, store: WorkspaceStore
) -> Path:
    record = store.get(workspace_id)
    if record is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "workspace_not_found",
            f"workspace {workspace_id!r} not found",
        )
    return Path(record.path)


def _require_valid_file(name: str) -> None:
    if not memory_store.is_valid_file(name):
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "unknown_memory_file",
            f"memory file {name!r} is not one of memory|lessons|tasks|gaps",
        )


@router.get("/{workspace_id}/memory")
def get_memory_bundle(
    workspace_id: str,
    store: WorkspaceStore = Depends(get_workspace_store),
) -> dict[str, str]:
    workspace_root = _require_workspace_root(workspace_id, store)
    return memory_store.read_all(workspace_root)


@router.get("/{workspace_id}/memory/{file}")
def get_memory_file(
    workspace_id: str,
    file: str,
    store: WorkspaceStore = Depends(get_workspace_store),
) -> Response:
    _require_valid_file(file)
    workspace_root = _require_workspace_root(workspace_id, store)
    content = memory_store.read_file(workspace_root, file)
    return Response(content=content, media_type="text/plain; charset=utf-8")


@router.put("/{workspace_id}/memory/{file}")
async def put_memory_file(
    workspace_id: str,
    file: str,
    request: Request,
    store: WorkspaceStore = Depends(get_workspace_store),
    lock_manager: WorkspaceLockManager = Depends(get_workspace_lock_manager),
) -> Response:
    _require_valid_file(file)
    workspace_root = _require_workspace_root(workspace_id, store)
    raw = await request.body()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "memory_body_not_utf8",
            "memory file body must be UTF-8 text",
        ) from exc
    async with lock_manager.get(workspace_id):
        try:
            memory_store.write_file(workspace_root, file, text)
        except OSError as exc:
            raise http_error(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "memory_write_failed",
                str(exc),
            ) from exc
    return Response(content=text, media_type="text/plain; charset=utf-8")


def _resolve_state_path(workspace_root: Path, raw: str) -> Path:
    """Return the resolved path under ``<workspace>/out/state/``, or raise on traversal."""
    state_root = (workspace_root / "out" / "state").resolve()
    candidate = (state_root / raw).resolve()
    if candidate != state_root and not candidate.is_relative_to(state_root):
        raise ValueError(f"path {raw!r} resolves outside {state_root}")
    return candidate


@router.get("/{workspace_id}/state/{path:path}")
def get_state_file(
    workspace_id: str,
    path: str,
    store: WorkspaceStore = Depends(get_workspace_store),
) -> Response:
    workspace_root = _require_workspace_root(workspace_id, store)
    try:
        resolved = _resolve_state_path(workspace_root, path)
    except ValueError as exc:
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "state_path_outside_workspace",
            str(exc),
        ) from exc
    if resolved.is_dir():
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "state_path_not_file",
            f"state path {path!r} resolves to a directory; only file reads are supported",
        )
    if not resolved.is_file():
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "state_path_not_found",
            f"state path {path!r} not found under workspace",
        )
    try:
        data = resolved.read_bytes()
    except OSError as exc:
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "state_read_failed",
            str(exc),
        ) from exc
    suffix = resolved.suffix.lower()
    if suffix == ".json":
        media_type = "application/json"
    elif suffix in (".yaml", ".yml", ".md", ".txt", ".csv"):
        media_type = "text/plain; charset=utf-8"
    else:
        media_type = "application/octet-stream"
    return Response(content=data, media_type=media_type)


_PHASE_RUN_LIMIT_MIN = 1
_PHASE_RUN_LIMIT_MAX = 500
_PHASE_RUN_LIMIT_DEFAULT = 100

# started_at format produced by core.time_utils.format_timestamp_local_minutes
# combined with the phase-run id counter, e.g. "20260514-153000-0042".
_STARTED_AT_RE = re.compile(r"\d{8}-\d{6}-[0-9a-fA-F]{4}")


def _phase_run_events_url(phase_run_id: str) -> str:
    return f"/v1/phase-runs/{phase_run_id}/events"


def _phase_run_response_from_meta(meta: dict[str, Any]) -> PhaseRunResponse:
    """Project a registry record into a PhaseRunResponse, matching GET /v1/phase-runs/{id}."""
    return PhaseRunResponse(
        phase_run_id=meta["phase_run_id"],
        phase=meta["phase"],
        workspace_id=meta["workspace_id"],
        chain_id=meta.get("chain_id"),
        status=PhaseRunState(meta["status"]),
        started_at=meta["started_at"],
        ended_at=meta.get("ended_at"),
        blocked_at=meta.get("blocked_at"),
        inputs=meta.get("inputs") or {},
        artifacts_index=meta.get("artifacts_index") or {},
        summary=meta.get("summary") or {},
        error=meta.get("error"),
        events_url=_phase_run_events_url(meta["phase_run_id"]),
    )


@router.get("/{workspace_id}/phase-runs", response_model=list[PhaseRunResponse])
def list_workspace_phase_runs(
    workspace_id: str,
    phase: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    chain_id: str | None = Query(default=None),
    limit: int = Query(default=_PHASE_RUN_LIMIT_DEFAULT),
    store: WorkspaceStore = Depends(get_workspace_store),
    run_registry: PhaseRunRegistry = Depends(get_phase_run_registry),
) -> list[PhaseRunResponse]:
    if store.get(workspace_id) is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "workspace_not_found",
            f"workspace {workspace_id!r} not found",
        )
    if limit < _PHASE_RUN_LIMIT_MIN or limit > _PHASE_RUN_LIMIT_MAX:
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "invalid_limit",
            f"limit must be between {_PHASE_RUN_LIMIT_MIN} and {_PHASE_RUN_LIMIT_MAX}",
            details={"limit": limit, "min": _PHASE_RUN_LIMIT_MIN, "max": _PHASE_RUN_LIMIT_MAX},
        )

    matches: list[dict[str, Any]] = []
    for record in run_registry.list():
        if record.get("workspace_id") != workspace_id:
            continue
        if phase is not None and record.get("phase") != phase:
            continue
        if status_filter is not None and record.get("status") != status_filter:
            continue
        if chain_id is not None and record.get("chain_id") != chain_id:
            continue
        matches.append(record)

    valid_runs: list[dict[str, Any]] = []
    invalid_runs: list[dict[str, Any]] = []
    for r in matches:
        s = r.get("started_at")
        if isinstance(s, str) and _STARTED_AT_RE.fullmatch(s):
            valid_runs.append(r)
        else:
            invalid_runs.append(r)
    valid_runs.sort(key=lambda r: r["started_at"], reverse=True)
    ordered = valid_runs + invalid_runs
    return [_phase_run_response_from_meta(r) for r in ordered[:limit]]
