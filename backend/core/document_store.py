"""Workspace document store: id-addressed text blobs with a per-category manifest.

Files live at ``<ws>/documents/<category>/blobs/<file_id><extension>`` (the
on-disk extension is preserved so extension-sniffing handlers see the right
type; the file_id is still the canonical opaque identifier). A sibling
``manifest.json`` is the source of truth for display names, extensions,
content-types, sizes, sha256s, and timestamps.

File IDs are server-minted UUID4 strings. Display names need not be unique
within a category; the file_id disambiguates.

Pure module — no FastAPI imports. Concurrency: write operations are atomic
at the manifest level (temp + rename) and at the blob level (unique
mkstemp + rename). The caller is responsible for the outer per-workspace
lock that serializes writers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict


ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {".md", ".txt", ".csv", ".json", ".yaml", ".yml"}
)
MAX_BYTES: int = 1024 * 1024
MANIFEST_VERSION: int = 1

_CATEGORY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_DISPLAY_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_FILE_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class ManifestEntry(TypedDict):
    file_id: str
    display_name: str
    extension: str
    size: int
    content_type: str
    sha256: str
    created_at: str
    updated_at: str


class DocumentNotFoundError(KeyError):
    """Raised when a file_id is absent from the manifest."""


def documents_root(workspace_root: Path) -> Path:
    return workspace_root / "documents"


def category_dir(workspace_root: Path, category: str) -> Path:
    return documents_root(workspace_root) / category


def _manifest_path(workspace_root: Path, category: str) -> Path:
    return category_dir(workspace_root, category) / "manifest.json"


def _blob_dir(workspace_root: Path, category: str) -> Path:
    return category_dir(workspace_root, category) / "blobs"


def _blob_path(workspace_root: Path, category: str, file_id: str, extension: str) -> Path:
    """Return the blob path. Extension is included so downstream tools that
    sniff by suffix (handlers, OS file pickers) see the right type."""
    return _blob_dir(workspace_root, category) / f"{file_id}{extension}"


def is_valid_category(category: str) -> bool:
    return bool(_CATEGORY_RE.fullmatch(category))


def is_valid_display_name(name: str) -> bool:
    if not _DISPLAY_NAME_RE.fullmatch(name):
        return False
    if name.startswith(".") or name.endswith("."):
        return False
    return Path(name).suffix.lower() in ALLOWED_EXTENSIONS


def is_valid_file_id(file_id: str) -> bool:
    return bool(_FILE_ID_RE.fullmatch(file_id))


def content_type_for(display_name: str) -> str:
    """Return the HTTP content-type for a display name's suffix."""
    suffix = Path(display_name).suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix == ".md":
        return "text/markdown; charset=utf-8"
    if suffix == ".csv":
        return "text/csv; charset=utf-8"
    if suffix in (".yaml", ".yml"):
        return "application/yaml"
    return "text/plain; charset=utf-8"


def resolve_category_dir(workspace_root: Path, category: str) -> Path:
    """Resolve ``<ws>/documents/<category>`` with traversal containment.

    Raises ``ValueError`` for an invalid category or a containment escape.
    """
    if not is_valid_category(category):
        raise ValueError(f"invalid category: {category!r}")
    root = documents_root(workspace_root).resolve()
    target = (root / category).resolve()
    if target != root and not target.is_relative_to(root):
        raise ValueError(f"category {category!r} resolves outside {root}")
    return target


# Backwards-compat alias for module-internal callers; the public name is
# ``resolve_category_dir``.
_resolve_category_dir = resolve_category_dir


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _empty_manifest() -> dict:
    return {"version": MANIFEST_VERSION, "documents": {}}


def _load_manifest(workspace_root: Path, category: str) -> dict:
    """Read the per-category manifest. Returns an empty manifest if missing.

    Raises ``ValueError`` on a corrupt manifest or a version mismatch.
    """
    path = _manifest_path(workspace_root, category)
    if not path.is_file():
        return _empty_manifest()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"manifest at {path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(f"manifest at {path} is not an object")
    version = data.get("version")
    if version != MANIFEST_VERSION:
        raise ValueError(
            f"manifest at {path} has unsupported version {version!r}; "
            f"expected {MANIFEST_VERSION}"
        )
    documents = data.get("documents")
    if not isinstance(documents, dict):
        raise ValueError(f"manifest at {path} has malformed 'documents' field")
    return data


def _save_manifest(workspace_root: Path, category: str, manifest: dict) -> None:
    """Atomically write the manifest (temp + rename)."""
    target = _resolve_category_dir(workspace_root, category)
    target.mkdir(parents=True, exist_ok=True)
    path = _manifest_path(workspace_root, category)
    payload = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix="manifest.", suffix=".tmp", dir=str(target))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_blob(
    workspace_root: Path,
    category: str,
    file_id: str,
    extension: str,
    data: bytes,
) -> None:
    blob_dir = _blob_dir(workspace_root, category)
    blob_dir.mkdir(parents=True, exist_ok=True)
    target = _blob_path(workspace_root, category, file_id, extension)
    fd, tmp_name = tempfile.mkstemp(prefix=file_id + ".", suffix=".tmp", dir=str(blob_dir))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_path, target)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _entry_from_doc(file_id: str, doc: dict) -> ManifestEntry:
    """Project a manifest document record into the public ManifestEntry shape."""
    return ManifestEntry(
        file_id=file_id,
        display_name=str(doc["display_name"]),
        extension=str(doc["extension"]),
        size=int(doc["size"]),
        content_type=str(doc["content_type"]),
        sha256=str(doc["sha256"]),
        created_at=str(doc["created_at"]),
        updated_at=str(doc["updated_at"]),
    )


def list_documents(workspace_root: Path, category: str) -> list[ManifestEntry]:
    """Return all manifest entries for a category, sorted by display_name then file_id.

    Returns ``[]`` if the category has no manifest yet. Raises ``ValueError``
    on traversal escape or manifest corruption.
    """
    _resolve_category_dir(workspace_root, category)
    manifest = _load_manifest(workspace_root, category)
    docs: dict[str, dict] = manifest["documents"]
    entries = [_entry_from_doc(fid, doc) for fid, doc in docs.items()]
    entries.sort(key=lambda e: (e["display_name"], e["file_id"]))
    return entries


def get_entry(
    workspace_root: Path, category: str, file_id: str
) -> ManifestEntry:
    """Return the manifest entry for ``file_id``. Raises ``DocumentNotFoundError``."""
    if not is_valid_file_id(file_id):
        raise ValueError(f"invalid file_id: {file_id!r}")
    _resolve_category_dir(workspace_root, category)
    manifest = _load_manifest(workspace_root, category)
    doc = manifest["documents"].get(file_id)
    if doc is None:
        raise DocumentNotFoundError(file_id)
    return _entry_from_doc(file_id, doc)


def read_document(
    workspace_root: Path, category: str, file_id: str
) -> tuple[ManifestEntry, bytes]:
    """Return ``(entry, bytes)`` for a document. Raises ``DocumentNotFoundError`` if absent.

    The blob file is also checked — if the manifest entry exists but the blob
    is missing on disk, ``FileNotFoundError`` is raised.
    """
    entry = get_entry(workspace_root, category, file_id)
    blob = _blob_path(workspace_root, category, file_id, entry["extension"])
    if not blob.is_file():
        raise FileNotFoundError(
            f"blob for file_id {file_id} in category {category!r} is missing"
        )
    return entry, blob.read_bytes()


def resolve_document_blob_path(
    workspace_root: Path, category: str, file_id: str
) -> Path:
    """Return the absolute blob path for a document. Raises ``DocumentNotFoundError``.

    Used by the phase-run input resolver to translate a document_ref into a
    path the handler can read. The returned path includes the document's
    extension so extension-sniffing handlers see the correct type.
    """
    entry = get_entry(workspace_root, category, file_id)
    blob = _blob_path(workspace_root, category, file_id, entry["extension"])
    if not blob.is_file():
        raise FileNotFoundError(
            f"blob for file_id {file_id} in category {category!r} is missing"
        )
    return blob


def add_document(
    workspace_root: Path,
    category: str,
    display_name: str,
    data: bytes,
) -> ManifestEntry:
    """Create a new document. Returns the manifest entry with a fresh ``file_id``."""
    if not is_valid_category(category):
        raise ValueError(f"invalid category: {category!r}")
    if not is_valid_display_name(display_name):
        raise ValueError(f"invalid display_name: {display_name!r}")
    if len(data) > MAX_BYTES:
        raise ValueError(
            f"document body exceeds {MAX_BYTES} bytes (got {len(data)})"
        )
    _resolve_category_dir(workspace_root, category)
    file_id = str(uuid.uuid4())
    now = _now_iso()
    extension = Path(display_name).suffix.lower()
    sha256 = hashlib.sha256(data).hexdigest()
    content_type = content_type_for(display_name)
    _write_blob(workspace_root, category, file_id, extension, data)
    manifest = _load_manifest(workspace_root, category)
    manifest["documents"][file_id] = {
        "display_name": display_name,
        "extension": extension,
        "size": len(data),
        "content_type": content_type,
        "sha256": sha256,
        "created_at": now,
        "updated_at": now,
    }
    _save_manifest(workspace_root, category, manifest)
    return _entry_from_doc(file_id, manifest["documents"][file_id])


def replace_document_content(
    workspace_root: Path,
    category: str,
    file_id: str,
    data: bytes,
    *,
    display_name: str | None = None,
) -> ManifestEntry:
    """Replace the content (and optionally the display_name) of an existing document.

    The new display_name (if given) must have the SAME extension as the
    existing entry — extension changes are not allowed via PUT to avoid
    silently converting a document's type. Use DELETE + POST for that.

    Raises ``DocumentNotFoundError`` if file_id is not in the manifest,
    ``ValueError`` on validation failure.
    """
    if not is_valid_file_id(file_id):
        raise ValueError(f"invalid file_id: {file_id!r}")
    if len(data) > MAX_BYTES:
        raise ValueError(
            f"document body exceeds {MAX_BYTES} bytes (got {len(data)})"
        )
    _resolve_category_dir(workspace_root, category)
    manifest = _load_manifest(workspace_root, category)
    doc = manifest["documents"].get(file_id)
    if doc is None:
        raise DocumentNotFoundError(file_id)
    if display_name is not None:
        if not is_valid_display_name(display_name):
            raise ValueError(f"invalid display_name: {display_name!r}")
        if Path(display_name).suffix.lower() != doc["extension"]:
            raise ValueError(
                f"display_name extension must match existing extension "
                f"{doc['extension']!r}; got {Path(display_name).suffix.lower()!r}"
            )
        doc["display_name"] = display_name
        doc["content_type"] = content_type_for(display_name)
    _write_blob(workspace_root, category, file_id, doc["extension"], data)
    doc["size"] = len(data)
    doc["sha256"] = hashlib.sha256(data).hexdigest()
    doc["updated_at"] = _now_iso()
    _save_manifest(workspace_root, category, manifest)
    return _entry_from_doc(file_id, doc)


def rename_document(
    workspace_root: Path,
    category: str,
    file_id: str,
    display_name: str,
) -> ManifestEntry:
    """Update the display_name of an existing document. Extension must match."""
    if not is_valid_file_id(file_id):
        raise ValueError(f"invalid file_id: {file_id!r}")
    if not is_valid_display_name(display_name):
        raise ValueError(f"invalid display_name: {display_name!r}")
    _resolve_category_dir(workspace_root, category)
    manifest = _load_manifest(workspace_root, category)
    doc = manifest["documents"].get(file_id)
    if doc is None:
        raise DocumentNotFoundError(file_id)
    if Path(display_name).suffix.lower() != doc["extension"]:
        raise ValueError(
            f"display_name extension must match existing extension "
            f"{doc['extension']!r}; got {Path(display_name).suffix.lower()!r}"
        )
    doc["display_name"] = display_name
    doc["content_type"] = content_type_for(display_name)
    doc["updated_at"] = _now_iso()
    _save_manifest(workspace_root, category, manifest)
    return _entry_from_doc(file_id, doc)


def delete_document(
    workspace_root: Path, category: str, file_id: str
) -> ManifestEntry:
    """Remove a document. Returns the removed entry. Raises ``DocumentNotFoundError``."""
    if not is_valid_file_id(file_id):
        raise ValueError(f"invalid file_id: {file_id!r}")
    _resolve_category_dir(workspace_root, category)
    manifest = _load_manifest(workspace_root, category)
    doc = manifest["documents"].get(file_id)
    if doc is None:
        raise DocumentNotFoundError(file_id)
    entry = _entry_from_doc(file_id, doc)
    # Remove manifest entry first so a partial blob-delete failure can't
    # leave an unreferenced manifest record around.
    extension = doc["extension"]
    del manifest["documents"][file_id]
    _save_manifest(workspace_root, category, manifest)
    blob = _blob_path(workspace_root, category, file_id, extension)
    try:
        blob.unlink()
    except FileNotFoundError:
        pass
    return entry


__all__ = [
    "ALLOWED_EXTENSIONS",
    "MAX_BYTES",
    "MANIFEST_VERSION",
    "ManifestEntry",
    "DocumentNotFoundError",
    "documents_root",
    "category_dir",
    "resolve_category_dir",
    "is_valid_category",
    "is_valid_display_name",
    "is_valid_file_id",
    "content_type_for",
    "list_documents",
    "get_entry",
    "read_document",
    "resolve_document_blob_path",
    "add_document",
    "replace_document_content",
    "rename_document",
    "delete_document",
]
