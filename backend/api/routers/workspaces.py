"""Workspace endpoints."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response, status

from api.deps import get_workspace_lock_manager, get_workspace_store
from api.errors import http_error
from api.schemas.workspaces import WorkspaceCreateRequest, WorkspaceResponse
from api.workspace_lock import WorkspaceLockManager
from api.workspaces import WorkspaceStore
from core import memory_store

router = APIRouter(prefix="/v1/workspaces", tags=["workspaces"])

_log = logging.getLogger(__name__)


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_200_OK)
def create_workspace(
    payload: WorkspaceCreateRequest,
    store: WorkspaceStore = Depends(get_workspace_store),
) -> WorkspaceResponse:
    try:
        record = store.register(payload.path)
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
