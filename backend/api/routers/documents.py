"""Workspace document endpoints (CRUD over ``<ws>/documents/<category>/<name>``)."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response, status

from api.deps import get_workspace_lock_manager, get_workspace_store
from api.errors import http_error
from api.routers.workspaces import _require_workspace_root
from api.workspace_lock import WorkspaceLockManager
from api.workspaces import WorkspaceStore
from core import document_store

router = APIRouter(prefix="/v1/workspaces", tags=["documents"])

_log = logging.getLogger(__name__)


def _require_valid_category(category: str) -> None:
    if not document_store.is_valid_category(category):
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "document_invalid_category",
            f"category {category!r} is not a single safe path segment",
            details={"category": category},
        )


def _require_valid_name(name: str) -> None:
    if not document_store.is_valid_name(name):
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "document_invalid_name",
            (
                f"document name {name!r} must match [A-Za-z0-9_.-]{{1,128}} and end "
                "in an allowed extension (.md, .txt, .csv, .json, .yaml, .yml)"
            ),
            details={"name": name},
        )


def _resolve_or_400(workspace_root: Path, category: str, name: str) -> Path:
    # Defense in depth: regex validators above already block path-segment
    # shapes; this catches escapes via symlinks or filesystem normalization.
    try:
        return document_store.resolve_document_path(workspace_root, category, name)
    except ValueError as exc:
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "document_path_outside_workspace",
            str(exc),
            details={"category": category, "name": name},
        ) from exc


@router.get("/{workspace_id}/documents/{category}")
def list_documents(
    workspace_id: str,
    category: str,
    store: WorkspaceStore = Depends(get_workspace_store),
) -> list[dict]:
    workspace_root = _require_workspace_root(workspace_id, store)
    _require_valid_category(category)
    try:
        return document_store.list_documents(workspace_root, category)
    except ValueError as exc:
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "document_path_outside_workspace",
            str(exc),
            details={"category": category},
        ) from exc


@router.get("/{workspace_id}/documents/{category}/{name}")
def get_document(
    workspace_id: str,
    category: str,
    name: str,
    store: WorkspaceStore = Depends(get_workspace_store),
) -> Response:
    workspace_root = _require_workspace_root(workspace_id, store)
    _require_valid_category(category)
    _require_valid_name(name)
    _resolve_or_400(workspace_root, category, name)
    try:
        data = document_store.read_document(workspace_root, category, name)
    except IsADirectoryError as exc:
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "document_path_not_file",
            f"{category}/{name} resolves to a directory",
        ) from exc
    except FileNotFoundError as exc:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "document_not_found",
            f"document {category}/{name} not found",
        ) from exc
    except OSError as exc:
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "document_read_failed",
            str(exc),
        ) from exc
    return Response(content=data, media_type=document_store.content_type_for(name))


@router.put("/{workspace_id}/documents/{category}/{name}")
async def put_document(
    workspace_id: str,
    category: str,
    name: str,
    request: Request,
    store: WorkspaceStore = Depends(get_workspace_store),
    lock_manager: WorkspaceLockManager = Depends(get_workspace_lock_manager),
) -> Response:
    workspace_root = _require_workspace_root(workspace_id, store)
    _require_valid_category(category)
    _require_valid_name(name)

    raw = await request.body()
    if len(raw) > document_store.MAX_BYTES:
        raise http_error(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "document_too_large",
            f"document body exceeds {document_store.MAX_BYTES} bytes",
            details={
                "limit_bytes": document_store.MAX_BYTES,
                "size_bytes": len(raw),
            },
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "document_body_not_utf8",
            "document body must be UTF-8 text",
        ) from exc

    _resolve_or_400(workspace_root, category, name)

    async with lock_manager.get(workspace_id):
        try:
            document_store.write_document(
                workspace_root, category, name, text.encode("utf-8")
            )
        except OSError as exc:
            raise http_error(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "document_write_failed",
                str(exc),
            ) from exc
    return Response(
        content=text.encode("utf-8"),
        media_type=document_store.content_type_for(name),
    )


@router.delete("/{workspace_id}/documents/{category}/{name}")
async def delete_document(
    workspace_id: str,
    category: str,
    name: str,
    store: WorkspaceStore = Depends(get_workspace_store),
    lock_manager: WorkspaceLockManager = Depends(get_workspace_lock_manager),
) -> Response:
    workspace_root = _require_workspace_root(workspace_id, store)
    _require_valid_category(category)
    _require_valid_name(name)
    _resolve_or_400(workspace_root, category, name)

    async with lock_manager.get(workspace_id):
        try:
            document_store.delete_document(workspace_root, category, name)
        except FileNotFoundError as exc:
            raise http_error(
                status.HTTP_404_NOT_FOUND,
                "document_not_found",
                str(exc),
            ) from exc
        except OSError as exc:
            raise http_error(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "document_delete_failed",
                str(exc),
            ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
