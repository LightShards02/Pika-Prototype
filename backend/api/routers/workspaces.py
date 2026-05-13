"""Workspace endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from api.deps import get_workspace_store
from api.errors import http_error
from api.schemas.workspaces import WorkspaceCreateRequest, WorkspaceResponse
from api.workspaces import WorkspaceStore

router = APIRouter(prefix="/v1/workspaces", tags=["workspaces"])


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
