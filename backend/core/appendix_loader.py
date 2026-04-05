"""Appendix document loading, ID assignment, and formatting.

Appendix documents are user-provided supplementary materials (data dictionaries,
API schemas, glossaries) that travel alongside the design spec CSV. Two formats
are supported:
  - Plain text (markdown): one file = one AppendixEntry.
  - Structured CSV: one row = one AppendixEntry (requires ``title`` and ``content``
    columns; optional ``module_tag`` column).

ID assignment follows the same fingerprint-based registry pattern used by
``assign_deterministic_ids`` in ``format_sads.py``, but under a separate
``appendix_fingerprints`` namespace in ``id_registry.json``.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.errors import PikaError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APX_ID_PREFIX = "APX"
APX_ID_PATTERN = re.compile(r"^APX[0-9]+$")


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

class AppendixSizeLimitError(PikaError):
    """Total appendix content exceeds max_appendix_chars."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class AppendixEntry:
    """A single appendix document or CSV row."""

    appendix_id: str = ""
    module_tag: str | None = None
    title: str = ""
    content: str = ""
    source_path: str = ""
    format: str = "text"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_appendix_files(
    config: dict[str, Any],
    project_root: Path,
    *,
    command: str,
) -> list[AppendixEntry]:
    """Load appendix entries from config for a given command (refine/implement).

    Reads ``commands.<command>.inputs.appendices`` from *config*. Each item
    is either a plain-text file (one entry) or a CSV file (one entry per row).

    Args:
        config: Merged workspace config dict.
        project_root: Project root directory.
        command: ``"refine"`` or ``"implement"``.

    Returns:
        List of AppendixEntry (without IDs assigned yet).
    """
    cmd_cfg = config.get("commands", {}).get(command, {})
    appendices_cfg: list[dict[str, Any]] = cmd_cfg.get("inputs", {}).get("appendices", [])
    if not appendices_cfg:
        return []

    entries: list[AppendixEntry] = []
    for item in appendices_cfg:
        path_str = item.get("path", "")
        if not path_str:
            continue
        resolved = project_root / path_str
        if not resolved.exists():
            continue

        fmt = item.get("format", "text").lower()
        config_module_tag = item.get("module_tag") or None
        config_title = item.get("title", "")

        if fmt == "csv":
            entries.extend(
                _load_csv_appendix(
                    resolved,
                    config_module_tag=config_module_tag,
                )
            )
        else:
            content = resolved.read_text(encoding="utf-8")
            title = config_title or resolved.stem
            entries.append(
                AppendixEntry(
                    module_tag=config_module_tag,
                    title=title,
                    content=content,
                    source_path=str(resolved),
                    format="text",
                )
            )

    return entries


def _load_csv_appendix(
    path: Path,
    *,
    config_module_tag: str | None,
) -> list[AppendixEntry]:
    """Parse a CSV file into one AppendixEntry per row.

    Required CSV columns: ``title``, ``content``.
    Optional CSV column: ``module_tag``.
    Row-level ``module_tag`` overrides config-level.

    Args:
        path: Path to CSV file.
        config_module_tag: Default module_tag from config.

    Returns:
        List of AppendixEntry.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="cp1252")

    reader = csv.DictReader(
        text.splitlines(),
        delimiter=",",
        quotechar='"',
        skipinitialspace=True,
    )
    headers = [
        h.strip().lower()
        for h in (reader.fieldnames or [])
        if isinstance(h, str) and h.strip()
    ]
    if "title" not in headers or "content" not in headers:
        return []

    entries: list[AppendixEntry] = []
    for row in reader:
        norm = _normalize_csv_row(row, headers)
        title = norm.get("title", "")
        content = norm.get("content", "")
        if not title and not content:
            continue
        row_module = norm.get("module_tag") or None
        module_tag = row_module if row_module else config_module_tag
        entries.append(
            AppendixEntry(
                module_tag=module_tag,
                title=title,
                content=content,
                source_path=str(path),
                format="csv_row",
            )
        )

    return entries


def _normalize_csv_row(
    row: dict[str | None, Any],
    headers: list[str],
) -> dict[str, str]:
    """Normalize a CSV DictReader row and merge overflow cells safely.

    ``csv.DictReader`` stores surplus cells under the ``None`` key when a data
    row has more comma-separated values than the header declares. This happens
    when the last field contains an unquoted comma. For appendix CSVs, preserve
    that content by appending the overflow cells to the final declared header
    instead of crashing during key normalization.
    """
    normalized: dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            continue
        key_text = str(key).strip().lower()
        if not key_text:
            continue
        normalized[key_text] = (value or "").strip()

    overflow = row.get(None)
    if isinstance(overflow, list) and headers:
        extras = [str(value).strip() for value in overflow if value is not None and str(value).strip()]
        if extras:
            last_header = headers[-1]
            existing = normalized.get(last_header, "")
            normalized[last_header] = ", ".join(([existing] if existing else []) + extras)

    return normalized


# ---------------------------------------------------------------------------
# ID assignment
# ---------------------------------------------------------------------------

def _appendix_fingerprint(entry: AppendixEntry) -> str:
    """Canonical fingerprint for appendix ID stability."""
    return f"{entry.source_path}|{entry.title}|{entry.content[:500]}"


def _parse_apx_num(s: str) -> int | None:
    """Extract numeric suffix from APX ID (e.g. APX003 -> 3)."""
    if not s or not APX_ID_PATTERN.match(s.strip()):
        return None
    digits = s.strip()[len(APX_ID_PREFIX):]
    try:
        return int(digits)
    except ValueError:
        return None


def assign_appendix_ids(
    entries: list[AppendixEntry],
    registry_path: Path,
    project_root: Path,
) -> list[AppendixEntry]:
    """Assign stable APX-prefixed IDs to appendix entries via fingerprint registry.

    Uses the same registry file as spec IDs (``id_registry.json``) but under
    a separate ``appendix_fingerprints`` key.

    Args:
        entries: List of AppendixEntry (mutated in place with appendix_id).
        registry_path: Path to id_registry.json (relative to project_root if not absolute).
        project_root: Project root directory.

    Returns:
        The same list with ``appendix_id`` fields populated.
    """
    resolved = registry_path if registry_path.is_absolute() else (project_root / registry_path)
    registry: dict[str, Any] = {}
    if resolved.exists():
        try:
            registry = json.loads(resolved.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    if not isinstance(registry, dict):
        registry = {}

    fingerprints: dict[str, str] = registry.get("appendix_fingerprints", {})
    if not isinstance(fingerprints, dict):
        fingerprints = {}
    apx_next: int = registry.get("apx_next", 1)
    apx_max: int = registry.get("apx_max", 0)

    for fp_hash, apx_id in fingerprints.items():
        n = _parse_apx_num(apx_id)
        if n is not None and n > apx_max:
            apx_max = n

    for entry in entries:
        fp = _appendix_fingerprint(entry)
        fp_hash = hashlib.sha256(fp.encode("utf-8")).hexdigest()
        if fp_hash in fingerprints:
            entry.appendix_id = fingerprints[fp_hash]
        else:
            if apx_next <= apx_max:
                apx_next = apx_max + 1
            apx_id = f"{APX_ID_PREFIX}{apx_next:03d}"
            fingerprints[fp_hash] = apx_id
            entry.appendix_id = apx_id
            apx_max = max(apx_next, apx_max)
            apx_next += 1

    registry["appendix_fingerprints"] = fingerprints
    registry["apx_next"] = apx_next
    registry["apx_max"] = apx_max

    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(registry, indent=2), encoding="utf-8")

    return entries


# ---------------------------------------------------------------------------
# Formatting for prompt injection
# ---------------------------------------------------------------------------

def format_appendix_for_agent(
    entries: list[AppendixEntry],
    *,
    max_chars: int = 0,
) -> str:
    """Format appendix entries as a readable text block for prompt injection.

    Args:
        entries: List of AppendixEntry with IDs assigned.
        max_chars: Maximum total characters allowed. 0 = no limit.

    Returns:
        Formatted text block.

    Raises:
        AppendixSizeLimitError: If total content exceeds *max_chars*.
    """
    if not entries:
        return ""

    parts: list[str] = []
    for e in entries:
        scope = f"module={e.module_tag}" if e.module_tag else "general"
        header = f"[{e.appendix_id}] {e.title} ({scope})"
        parts.append(f"{header}\n{e.content}")

    text = "\n\n---\n\n".join(parts)

    if max_chars > 0 and len(text) > max_chars:
        raise AppendixSizeLimitError(
            f"Total appendix content ({len(text)} chars) exceeds "
            f"max_appendix_chars ({max_chars}). Reduce appendix content "
            f"or increase the limit."
        )

    return text


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def appendix_entries_to_lookup(
    entries: list[AppendixEntry],
) -> dict[str, AppendixEntry]:
    """Build a dict keyed by appendix_id for O(1) lookup.

    Args:
        entries: List of AppendixEntry with IDs assigned.

    Returns:
        Dict mapping appendix_id -> AppendixEntry.
    """
    return {e.appendix_id: e for e in entries if e.appendix_id}


def appendix_content_hash(entries: list[AppendixEntry]) -> str:
    """Compute a deterministic hash over all appendix content for resume checks.

    Args:
        entries: List of AppendixEntry.

    Returns:
        Hex digest string.
    """
    h = hashlib.sha256()
    for e in sorted(entries, key=lambda x: x.appendix_id):
        h.update(f"{e.appendix_id}|{e.source_path}|{e.content}".encode("utf-8"))
    return h.hexdigest()
