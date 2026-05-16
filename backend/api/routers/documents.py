"""Workspace document endpoints: id-addressed CRUD with per-category manifest."""

from __future__ import annotations

from pathlib import Path

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from api.deps import get_workspace_lock_manager, get_workspace_store
from api.errors import http_error
from api.routers.workspaces import _require_workspace_root
from api.workspace_lock import WorkspaceLockManager
from api.workspaces import WorkspaceStore
from core import document_store
from core.document_store import DocumentNotFoundError, ManifestEntry

router = APIRouter(prefix="/v1/workspaces", tags=["documents"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class RenameRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=128)


class DocumentEntryResponse(BaseModel):
    file_id: str
    display_name: str
    extension: str
    size: int
    content_type: str
    sha256: str
    created_at: str
    updated_at: str


def _entry_to_response(entry: ManifestEntry) -> DocumentEntryResponse:
    return DocumentEntryResponse(**entry)


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def _require_valid_category(category: str) -> None:
    if not document_store.is_valid_category(category):
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "document_invalid_category",
            f"category {category!r} is not a single safe path segment",
            details={"category": category},
        )


def _require_valid_display_name(display_name: str) -> None:
    if not document_store.is_valid_display_name(display_name):
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "document_invalid_display_name",
            (
                "display_name must match [A-Za-z0-9_.-]{1,128}, not start/end "
                "with '.', and end in an allowed extension "
                "(.md, .txt, .csv, .json, .yaml, .yml)"
            ),
            details={"display_name": display_name},
        )


def _require_valid_file_id(file_id: str) -> None:
    if not document_store.is_valid_file_id(file_id):
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "document_invalid_file_id",
            "file_id must be a UUID4 string",
            details={"file_id": file_id},
        )


def _resolve_or_400(workspace_root: Path, category: str) -> None:
    try:
        document_store.resolve_category_dir(workspace_root, category)
    except ValueError as exc:
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "document_path_outside_workspace",
            str(exc),
            details={"category": category},
        ) from exc


async def _read_upload(file: UploadFile) -> bytes:
    """Read the multipart file body, enforcing the size cap."""
    # Drain in chunks so an oversized upload doesn't fully buffer before we reject it.
    chunks: list[bytes] = []
    total = 0
    limit = document_store.MAX_BYTES
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise http_error(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "document_too_large",
                f"document body exceeds {limit} bytes",
                details={"limit_bytes": limit, "size_bytes": total},
            )
        chunks.append(chunk)
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/{workspace_id}/documents/{category}",
    response_model=list[DocumentEntryResponse],
)
def list_documents(
    workspace_id: str,
    category: str,
    store: WorkspaceStore = Depends(get_workspace_store),
) -> list[DocumentEntryResponse]:
    workspace_root = _require_workspace_root(workspace_id, store)
    _require_valid_category(category)
    try:
        entries = document_store.list_documents(workspace_root, category)
    except ValueError as exc:
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "document_path_outside_workspace",
            str(exc),
            details={"category": category},
        ) from exc
    return [_entry_to_response(e) for e in entries]


@router.get("/{workspace_id}/documents/{category}/{file_id}")
def get_document_content(
    workspace_id: str,
    category: str,
    file_id: str,
    store: WorkspaceStore = Depends(get_workspace_store),
) -> Response:
    workspace_root = _require_workspace_root(workspace_id, store)
    _require_valid_category(category)
    _require_valid_file_id(file_id)
    _resolve_or_400(workspace_root, category)
    try:
        entry, data = document_store.read_document(
            workspace_root, category, file_id
        )
    except DocumentNotFoundError as exc:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "document_not_found",
            f"document {file_id} not found in category {category!r}",
        ) from exc
    except FileNotFoundError as exc:
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "document_blob_missing",
            str(exc),
        ) from exc
    except ValueError as exc:
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "document_manifest_corrupt",
            str(exc),
        ) from exc
    headers = {
        "X-Document-Id": entry["file_id"],
        "X-Document-Display-Name": entry["display_name"],
        "X-Document-Sha256": entry["sha256"],
    }
    return Response(
        content=data, media_type=entry["content_type"], headers=headers
    )


@router.get(
    "/{workspace_id}/documents/{category}/{file_id}/meta",
    response_model=DocumentEntryResponse,
)
def get_document_meta(
    workspace_id: str,
    category: str,
    file_id: str,
    store: WorkspaceStore = Depends(get_workspace_store),
) -> DocumentEntryResponse:
    workspace_root = _require_workspace_root(workspace_id, store)
    _require_valid_category(category)
    _require_valid_file_id(file_id)
    _resolve_or_400(workspace_root, category)
    try:
        entry = document_store.get_entry(workspace_root, category, file_id)
    except DocumentNotFoundError as exc:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "document_not_found",
            f"document {file_id} not found in category {category!r}",
        ) from exc
    except ValueError as exc:
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "document_manifest_invalid",
            str(exc),
        ) from exc
    return _entry_to_response(entry)


@router.post(
    "/{workspace_id}/documents/{category}",
    response_model=DocumentEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    workspace_id: str,
    category: str,
    file: UploadFile = File(...),
    display_name: str | None = Form(default=None),
    store: WorkspaceStore = Depends(get_workspace_store),
    lock_manager: WorkspaceLockManager = Depends(get_workspace_lock_manager),
) -> DocumentEntryResponse:
    workspace_root = _require_workspace_root(workspace_id, store)
    _require_valid_category(category)
    _resolve_or_400(workspace_root, category)
    chosen = display_name or file.filename or ""
    _require_valid_display_name(chosen)
    data = await _read_upload(file)
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "document_body_not_utf8",
            "document body must be UTF-8 text",
        ) from exc
    async with lock_manager.get(workspace_id):
        try:
            entry = document_store.add_document(
                workspace_root, category, chosen, data
            )
        except ValueError as exc:
            raise http_error(
                status.HTTP_400_BAD_REQUEST,
                "document_invalid_input",
                str(exc),
            ) from exc
        except OSError as exc:
            raise http_error(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "document_write_failed",
                str(exc),
            ) from exc
    return _entry_to_response(entry)


@router.put(
    "/{workspace_id}/documents/{category}/{file_id}",
    response_model=DocumentEntryResponse,
)
async def replace_document(
    workspace_id: str,
    category: str,
    file_id: str,
    file: UploadFile = File(...),
    display_name: str | None = Form(default=None),
    store: WorkspaceStore = Depends(get_workspace_store),
    lock_manager: WorkspaceLockManager = Depends(get_workspace_lock_manager),
) -> DocumentEntryResponse:
    workspace_root = _require_workspace_root(workspace_id, store)
    _require_valid_category(category)
    _require_valid_file_id(file_id)
    _resolve_or_400(workspace_root, category)
    if display_name is not None:
        _require_valid_display_name(display_name)
    data = await _read_upload(file)
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "document_body_not_utf8",
            "document body must be UTF-8 text",
        ) from exc
    async with lock_manager.get(workspace_id):
        try:
            entry = document_store.replace_document_content(
                workspace_root,
                category,
                file_id,
                data,
                display_name=display_name,
            )
        except DocumentNotFoundError as exc:
            raise http_error(
                status.HTTP_404_NOT_FOUND,
                "document_not_found",
                f"document {file_id} not found in category {category!r}",
            ) from exc
        except ValueError as exc:
            raise http_error(
                status.HTTP_400_BAD_REQUEST,
                "document_invalid_input",
                str(exc),
            ) from exc
        except OSError as exc:
            raise http_error(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "document_write_failed",
                str(exc),
            ) from exc
    return _entry_to_response(entry)


@router.patch(
    "/{workspace_id}/documents/{category}/{file_id}",
    response_model=DocumentEntryResponse,
)
async def rename_document(
    workspace_id: str,
    category: str,
    file_id: str,
    payload: RenameRequest = Body(...),
    store: WorkspaceStore = Depends(get_workspace_store),
    lock_manager: WorkspaceLockManager = Depends(get_workspace_lock_manager),
) -> DocumentEntryResponse:
    workspace_root = _require_workspace_root(workspace_id, store)
    _require_valid_category(category)
    _require_valid_file_id(file_id)
    _resolve_or_400(workspace_root, category)
    _require_valid_display_name(payload.display_name)
    async with lock_manager.get(workspace_id):
        try:
            entry = document_store.rename_document(
                workspace_root, category, file_id, payload.display_name
            )
        except DocumentNotFoundError as exc:
            raise http_error(
                status.HTTP_404_NOT_FOUND,
                "document_not_found",
                f"document {file_id} not found in category {category!r}",
            ) from exc
        except ValueError as exc:
            raise http_error(
                status.HTTP_400_BAD_REQUEST,
                "document_invalid_input",
                str(exc),
            ) from exc
        except OSError as exc:
            raise http_error(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "document_write_failed",
                str(exc),
            ) from exc
    return _entry_to_response(entry)


@router.delete(
    "/{workspace_id}/documents/{category}/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    workspace_id: str,
    category: str,
    file_id: str,
    store: WorkspaceStore = Depends(get_workspace_store),
    lock_manager: WorkspaceLockManager = Depends(get_workspace_lock_manager),
) -> Response:
    workspace_root = _require_workspace_root(workspace_id, store)
    _require_valid_category(category)
    _require_valid_file_id(file_id)
    _resolve_or_400(workspace_root, category)
    async with lock_manager.get(workspace_id):
        try:
            document_store.delete_document(workspace_root, category, file_id)
        except DocumentNotFoundError as exc:
            raise http_error(
                status.HTTP_404_NOT_FOUND,
                "document_not_found",
                f"document {file_id} not found in category {category!r}",
            ) from exc
        except OSError as exc:
            raise http_error(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "document_delete_failed",
                str(exc),
            ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
