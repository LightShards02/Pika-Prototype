"""Workspace document store: per-workspace text files under ``<ws>/documents/<category>/``.

Documents are user-managed text artifacts (notes, references, scratch CSV/JSON).
The store enforces an extension allowlist and a per-document size cap; path
resolution rejects anything that escapes the workspace's ``documents/`` root.

Pure module — no FastAPI imports. Mirrors the shape of ``memory_store``.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import TypedDict


ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {".md", ".txt", ".csv", ".json", ".yaml", ".yml"}
)
MAX_BYTES: int = 1024 * 1024

_CATEGORY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


class DocumentEntry(TypedDict):
    name: str
    size: int
    mtime: float


def documents_root(workspace_root: Path) -> Path:
    """Return ``<workspace>/documents``."""
    return workspace_root / "documents"


def category_dir(workspace_root: Path, category: str) -> Path:
    """Return ``<workspace>/documents/<category>`` (no validation)."""
    return documents_root(workspace_root) / category


def is_valid_category(category: str) -> bool:
    """True if ``category`` is a single safe path segment."""
    return bool(_CATEGORY_RE.fullmatch(category))


def is_valid_name(name: str) -> bool:
    """True if ``name`` matches the safe-segment regex and has an allowed extension."""
    if not _NAME_RE.fullmatch(name):
        return False
    if name.startswith(".") or name.endswith("."):
        return False
    suffix = Path(name).suffix.lower()
    return suffix in ALLOWED_EXTENSIONS


def resolve_document_path(
    workspace_root: Path, category: str, name: str
) -> Path:
    """Return the resolved path inside the workspace's documents root.

    Raises ``ValueError`` if the category or name is invalid, or if the
    resolved path escapes ``<workspace>/documents/``.
    """
    if not is_valid_category(category):
        raise ValueError(f"invalid category: {category!r}")
    if not is_valid_name(name):
        raise ValueError(f"invalid document name: {name!r}")
    root = documents_root(workspace_root).resolve()
    candidate = (root / category / name).resolve()
    if candidate != root and not candidate.is_relative_to(root):
        raise ValueError(
            f"document path {category}/{name} resolves outside {root}"
        )
    return candidate


def content_type_for(name: str) -> str:
    """Return the HTTP content-type for a document name's suffix."""
    suffix = Path(name).suffix.lower()
    if suffix == ".json":
        return "application/json"
    return "text/plain; charset=utf-8"


def _resolve_category_dir(workspace_root: Path, category: str) -> Path:
    """Resolve ``<ws>/documents/<category>`` with traversal containment.

    Raises ``ValueError`` for an invalid category, or if the resolved path
    escapes the documents root (e.g. via a symlinked category directory).
    """
    if not is_valid_category(category):
        raise ValueError(f"invalid category: {category!r}")
    root = documents_root(workspace_root).resolve()
    target = (root / category).resolve()
    if target != root and not target.is_relative_to(root):
        raise ValueError(
            f"category {category!r} resolves outside {root}"
        )
    return target


def list_documents(workspace_root: Path, category: str) -> list[DocumentEntry]:
    """Return entries in ``<ws>/documents/<category>/`` sorted by name.

    Returns ``[]`` when the category directory does not exist.
    Raises ``ValueError`` for an invalid category or a containment escape
    (e.g. category is a symlink to an external directory). Files with
    disallowed extensions are skipped (the directory may have been touched
    by hand).
    """
    target = _resolve_category_dir(workspace_root, category)
    if not target.is_dir():
        return []
    entries: list[DocumentEntry] = []
    for child in target.iterdir():
        if not child.is_file():
            continue
        if child.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        try:
            stat = child.stat()
        except OSError:
            continue
        entries.append(
            DocumentEntry(name=child.name, size=stat.st_size, mtime=stat.st_mtime)
        )
    entries.sort(key=lambda e: e["name"])
    return entries


def read_document(workspace_root: Path, category: str, name: str) -> bytes:
    """Return raw document bytes. Raises ``FileNotFoundError`` / ``IsADirectoryError``."""
    path = resolve_document_path(workspace_root, category, name)
    if path.is_dir():
        raise IsADirectoryError(f"{category}/{name} is a directory")
    if not path.is_file():
        raise FileNotFoundError(f"document {category}/{name} not found")
    return path.read_bytes()


def write_document(
    workspace_root: Path, category: str, name: str, data: bytes
) -> None:
    """Atomically write ``data`` to the resolved path (unique temp + rename).

    Uses :func:`tempfile.mkstemp` so the temp filename is unique even for
    concurrent writes to the same target — the atomic-write primitive does
    not rely on the caller holding a lock.

    Creates the parent ``documents/<category>/`` directory lazily. Raises
    ``ValueError`` on invalid inputs (delegated through
    :func:`resolve_document_path`).
    """
    path = resolve_document_path(workspace_root, category, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def delete_document(workspace_root: Path, category: str, name: str) -> None:
    """Delete the document. Raises ``FileNotFoundError`` if missing."""
    path = resolve_document_path(workspace_root, category, name)
    if not path.is_file():
        raise FileNotFoundError(f"document {category}/{name} not found")
    path.unlink()


__all__ = [
    "ALLOWED_EXTENSIONS",
    "MAX_BYTES",
    "DocumentEntry",
    "documents_root",
    "category_dir",
    "is_valid_category",
    "is_valid_name",
    "resolve_document_path",
    "content_type_for",
    "list_documents",
    "read_document",
    "write_document",
    "delete_document",
]
