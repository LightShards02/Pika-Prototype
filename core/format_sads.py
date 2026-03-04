"""Deterministic SADS formatting: Raw SADS → Draft Formatted SADS.

Transforms Raw SADS into contract-compliant Draft Formatted SADS via:
1. Keyword replacement (sensitive dictionary)
2. Appending missing contract columns
3. Adding deterministic spec_ids via persisted registry
4. Producing normalized CSV + format logs

No agent invocation; purely deterministic.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
from pathlib import Path
from typing import Any

# Optional XLSX support
try:
    import openpyxl  # type: ignore
except ImportError:
    openpyxl = None  # type: ignore

# Unicode to LaTeX conversion (preserves math formulas, special chars as ASCII-safe escapes)
from pylatexenc.latexencode import UnicodeToLatexEncoder

_LATEX_ENCODER = UnicodeToLatexEncoder(
    non_ascii_only=True,
    unknown_char_policy="replace",
)


# Default for map_status when adding column
MAP_STATUS_DEFAULT = "unmapped"


def get_design_spec_add_if_missing(config: dict[str, Any]) -> list[str]:
    """Return design spec add_if_missing columns from config. Required.

    Config is the single source of truth. csv_contracts.design_spec.add_if_missing
    must be present and a non-empty list.

    Args:
        config: Full PIKA config.

    Returns:
        List of column names to add if missing, in contract order.

    Raises:
        ValueError: If add_if_missing is missing, empty, or not a list.
    """
    csv_contracts = config.get("csv_contracts") or {}
    design_spec = csv_contracts.get("design_spec") if isinstance(csv_contracts, dict) else {}
    if not isinstance(design_spec, dict):
        raise ValueError(
            "csv_contracts.design_spec.add_if_missing is required. "
            "Add it to your project config under csv_contracts.design_spec."
        )
    add_cols = design_spec.get("add_if_missing")
    if not isinstance(add_cols, list) or len(add_cols) == 0:
        raise ValueError(
            "csv_contracts.design_spec.add_if_missing is required and must be a non-empty list. "
            "Define the contract columns in your project config."
        )
    return [str(c) for c in add_cols]


# Max empty columns to keep between existing and new contract columns
MAX_EMPTY_COLUMNS_BEFORE_NEW = 2

# Spec ID format: one letter + digits (e.g. A1001)
SPEC_ID_LETTER = "A"
SPEC_ID_PATTERN = re.compile(r"^[A-Za-z][0-9]+$")

# SADS ID format in Sample-Spec: D{number}.{subnumber} (e.g. D627.01)
SADS_ID_PATTERN = re.compile(r"^D\d+\.\d+$")


def _unicode_to_latex(s: str) -> str:
    """Convert non-ASCII Unicode to LaTeX escapes for ASCII-safe CSV storage.

    Only converts non-ASCII characters; ASCII strings (including existing LaTeX
    like \\sum) are returned unchanged.

    Args:
        s: Cell value string, possibly containing Unicode (e.g. ∑, μm).

    Returns:
        LaTeX-escaped string safe for UTF-8/ASCII storage.
    """
    if not s or s.isascii():
        return s
    return _LATEX_ENCODER.unicode_to_latex(s)


def load_sads_csv_or_xlsx(source_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Load Raw SADS from CSV or XLSX into (headers, rows).

    Args:
        source_path: Path to CSV or XLSX file.

    Returns:
        Tuple of (column names in order, list of row dicts keyed by column name).

    Raises:
        ValueError: If file extension unsupported or XLSX used without openpyxl.
        OSError: If file cannot be read.
    """
    suffix = source_path.suffix.lower()
    if suffix == ".csv":
        return _load_csv(source_path)
    if suffix == ".xlsx":
        return _load_xlsx(source_path)
    raise ValueError(
        f"Unsupported file extension: {suffix}. Use .csv or .xlsx."
    )


def _load_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Load CSV file. Preserves column order and normalizes values to str.

    Tries UTF-8 first; on decode error falls back to cp1252 (common for
    Windows/Excel exports). Converts non-ASCII Unicode to LaTeX escapes for
    ASCII-safe internal representation.
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
    headers = reader.fieldnames or []
    rows: list[dict[str, str]] = []
    for row in reader:
        normalized: dict[str, str] = {}
        for k in headers:
            v = row.get(k, "")
            raw = "" if v is None else str(v).strip()
            normalized[k] = _unicode_to_latex(raw)
        rows.append(normalized)
    return list(headers), rows


def _load_xlsx(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Load first sheet of XLSX file. Requires openpyxl.

    Converts non-ASCII Unicode (e.g. math symbols ∑, μm) to LaTeX escapes
    for ASCII-safe internal representation.
    """
    if openpyxl is None:
        raise ValueError(
            "XLSX support requires openpyxl. Install with: pip install openpyxl"
        )
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = wb.active
    if sheet is None:
        wb.close()
        return [], []

    rows_iter = sheet.iter_rows(values_only=True)
    first = next(rows_iter, None)
    if first is None:
        wb.close()
        return [], []

    headers = [str(c) if c is not None else "" for c in first]
    rows: list[dict[str, str]] = []
    for row in rows_iter:
        if row is None:
            continue
        normalized: dict[str, str] = {}
        for i, k in enumerate(headers):
            v = row[i] if i < len(row) else None
            raw = "" if v is None else str(v).strip()
            normalized[k] = _unicode_to_latex(raw)
        rows.append(normalized)
    wb.close()
    return headers, rows


def _find_column(headers: list[str], candidates: list[str]) -> str | None:
    """Find first column name that matches any candidate (case-insensitive)."""
    header_set = {h.strip(): h for h in headers if h}
    for c in candidates:
        for k, v in header_set.items():
            if k.lower() == c.lower():
                return v
    return None


def flatten_sads_rows(
    headers: list[str],
    rows: list[dict[str, str]],
    *,
    sads_id_pattern: re.Pattern[str] = SADS_ID_PATTERN,
) -> tuple[list[str], list[dict[str, str]]]:
    """Forward-fill SRS ID/SRS and filter to SADS rows only.

    For hierarchical SRS/SADS sources (e.g. Sample-Spec), rows with empty
    SRS ID inherit from the previous row. Only rows with a valid SADS ID
    (pattern D\\d+\\.\\d+) are output.

    Args:
        headers: Column names. Expected: SRS ID, SRS, SADS ID, SADS (or aliases).
        rows: Row dicts keyed by column name.
        sads_id_pattern: Regex to match valid SADS IDs. Default D\\d+\\.\\d+.

    Returns:
        Tuple of (headers, flattened rows). All original columns preserved.
    """
    srs_id_col = _find_column(headers, ["SRS ID", "srs_id", "SRS_ID"])
    srs_col = _find_column(headers, ["SRS", "srs"])
    sads_id_col = _find_column(headers, ["SADS ID", "sads_id", "SADS_ID"])
    sads_col = _find_column(headers, ["SADS", "sads"])

    current_srs_id = ""
    current_srs = ""
    result: list[dict[str, str]] = []

    for row in rows:
        if srs_id_col and row.get(srs_id_col, "").strip():
            current_srs_id = row.get(srs_id_col, "").strip()
        if srs_col and row.get(srs_col, "").strip():
            current_srs = row.get(srs_col, "").strip()

        sads_id_val = row.get(sads_id_col or "", "").strip()
        if not sads_id_val or not sads_id_pattern.match(sads_id_val):
            continue

        r = dict(row)
        if srs_id_col and not r.get(srs_id_col, "").strip():
            r[srs_id_col] = current_srs_id
        if srs_col and not r.get(srs_col, "").strip():
            r[srs_col] = current_srs
        result.append(r)

    return headers, result


def derive_contract_columns(
    headers: list[str],
    rows: list[dict[str, str]],
) -> tuple[list[str], list[dict[str, str]]]:
    """Derive title and requirement from SADS ID/SADS when missing.

    When source has SADS ID and SADS but no title/requirement, add
    contract columns derived from them. Preserves original columns.

    Args:
        headers: Column names.
        rows: Row dicts.

    Returns:
        Tuple of (headers with possibly new columns, rows with values filled).
    """
    sads_id_col = _find_column(headers, ["SADS ID", "sads_id", "SADS_ID"])
    sads_col = _find_column(headers, ["SADS", "sads"])
    title_col = _find_column(headers, ["title", "Title"])
    req_col = _find_column(headers, ["requirement", "Requirement"])

    new_headers = list(headers)
    to_add: list[str] = []
    if not title_col and sads_id_col:
        to_add.append("title")
    if not req_col and sads_col:
        to_add.append("requirement")

    for c in to_add:
        if c not in new_headers:
            new_headers.append(c)

    new_rows: list[dict[str, str]] = []
    for row in rows:
        r = dict(row)
        if "title" in to_add and sads_id_col:
            r["title"] = row.get(sads_id_col, "")
        if "requirement" in to_add and sads_col:
            r["requirement"] = row.get(sads_col, "")
        new_rows.append(r)

    return new_headers, new_rows


# Type for per-mapping keyword replacement: (keyword->replacement dict, case_sensitive)
_KeywordMapping = tuple[dict[str, str], bool]


def _normalize_sensitive_keywords(config_value: dict[str, Any]) -> list[_KeywordMapping]:
    """Convert sensitive_keywords config to list of (keyword->replacement, case_sensitive).

    Each mapping must be an object: replacement -> {keywords: [...], case_sensitive?: bool}
    The keywords field is required; case_sensitive is optional (default False).

    Returns:
        List of (keyword->replacement dict, case_sensitive) for apply_keyword_replacement.
    """
    result: list[_KeywordMapping] = []
    for replacement_key, v in config_value.items():
        if not isinstance(v, dict) or "keywords" not in v:
            continue
        replacement = str(replacement_key)
        kw_list = v.get("keywords")
        if not isinstance(kw_list, list):
            continue
        keywords_dict: dict[str, str] = {}
        for kw in kw_list:
            if isinstance(kw, str) and kw.strip():
                keywords_dict[kw.strip()] = replacement
        if keywords_dict:
            case_sensitive = bool(v.get("case_sensitive", False))
            result.append((keywords_dict, case_sensitive))
    return result


def apply_keyword_replacement(
    headers: list[str],
    rows: list[dict[str, str]],
    mappings: list[_KeywordMapping],
) -> list[dict[str, str]]:
    """Replace sensitive keywords in text cells. Whole-word match.

    Args:
        headers: Column names.
        rows: Row dicts.
        mappings: List of (keyword->replacement dict, case_sensitive) per mapping.

    Returns:
        New list of row dicts with replacements applied (rows are copied).
    """
    if not mappings:
        return [dict(r) for r in rows]

    # Build patterns per mapping group (each can have different case_sensitive)
    all_patterns: list[tuple[re.Pattern[str], str]] = []
    for keywords_dict, cs in mappings:
        flags = 0 if cs else re.IGNORECASE
        for kw, repl in keywords_dict.items():
            if not kw:
                continue
            escaped = re.escape(kw)
            all_patterns.append((re.compile(rf"\b{escaped}\b", flags), repl))

    result: list[dict[str, str]] = []
    for row in rows:
        new_row: dict[str, str] = {}
        for col in headers:
            val = row.get(col, "")
            if isinstance(val, str):
                for pat, repl in all_patterns:
                    val = pat.sub(repl, val)
            new_row[col] = val
        result.append(new_row)
    return result


def collapse_empty_columns_before_new(
    headers: list[str],
    *,
    max_empty: int = MAX_EMPTY_COLUMNS_BEFORE_NEW,
) -> list[str]:
    """Collapse consecutive empty columns to at most max_empty.

    Reduces the gap between existing source columns and new contract columns
    (e.g. title, requirement, spec_id) to at most max_empty empty columns.
    Preserves column order; only trims excess empty columns.

    Args:
        headers: Current column names (may include empty strings from XLSX).
        max_empty: Maximum empty columns to keep. Default 2.

    Returns:
        New headers list with empty runs collapsed to at most max_empty.
    """
    if not headers:
        return headers
    result: list[str] = []
    i = 0
    while i < len(headers):
        h = headers[i]
        if h.strip():
            result.append(h)
            i += 1
            continue
        # Run of empty columns
        j = i
        while j < len(headers) and not headers[j].strip():
            j += 1
        empty_count = j - i
        kept = min(empty_count, max_empty)
        for _ in range(kept):
            result.append("")
        i = j
    return result


def append_missing_columns(
    headers: list[str],
    rows: list[dict[str, str]],
    add_if_missing: list[str],
    *,
    map_status_default: str = MAP_STATUS_DEFAULT,
) -> tuple[list[str], list[dict[str, str]]]:
    """Append contract columns that are missing. Preserve original column order.

    Args:
        headers: Current column names.
        rows: Row dicts.
        add_if_missing: Contract columns to add if absent (in order).
        map_status_default: Default value for map_status column.

    Returns:
        Tuple of (new headers, new rows). Original columns unchanged; new columns appended.
    """
    existing = set(headers)
    new_headers = list(headers)
    to_add: list[str] = []
    for col in add_if_missing:
        if col not in existing:
            to_add.append(col)
            existing.add(col)
    new_headers.extend(to_add)

    defaults: dict[str, str] = {}
    for col in to_add:
        if col == "map_status":
            defaults[col] = map_status_default
        else:
            defaults[col] = ""

    new_rows: list[dict[str, str]] = []
    for row in rows:
        r = dict(row)
        for col in to_add:
            r[col] = defaults[col]
        new_rows.append(r)
    return new_headers, new_rows


def _spec_fingerprint(row: dict[str, str], headers: list[str]) -> str:
    """Canonical fingerprint for spec ID assignment per csv_contracts."""
    parts: list[str] = []
    for key in ("title", "requirement", "acceptance_criteria"):
        if key in headers:
            parts.append(row.get(key, ""))
        else:
            parts.append("")
    return "|".join(parts)


def _sads_spec_fingerprint(row: dict[str, str], headers: list[str]) -> str:
    """Fingerprint for SADS format: srs_id|sads_id|requirement."""
    srs_id_col = _find_column(headers, ["SRS ID", "srs_id", "SRS_ID"])
    sads_id_col = _find_column(headers, ["SADS ID", "sads_id", "SADS_ID"])
    req_col = _find_column(headers, ["requirement", "Requirement"])
    sads_col = _find_column(headers, ["SADS", "sads"])
    srs_id = row.get(srs_id_col or "", "") if srs_id_col else ""
    sads_id = row.get(sads_id_col or "", "") if sads_id_col else ""
    req = row.get(req_col or "", "") if req_col else (row.get(sads_col or "", "") if sads_col else "")
    return f"{srs_id}|{sads_id}|{req}"


def _is_sads_format(headers: list[str], rows: list[dict[str, str]]) -> bool:
    """True if source has SADS ID column and at least one matching row."""
    sads_id_col = _find_column(headers, ["SADS ID", "sads_id", "SADS_ID"])
    if not sads_id_col:
        return False
    for row in rows:
        if SADS_ID_PATTERN.match(row.get(sads_id_col, "").strip()):
            return True
    return False


def _parse_spec_id(s: str) -> int | None:
    """Extract numeric suffix from spec_id (e.g. A1001 -> 1001)."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if not SPEC_ID_PATTERN.match(s):
        return None
    digits = re.sub(r"^[A-Za-z]+", "", s)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _next_spec_id(registry: dict[str, Any]) -> str:
    """Allocate next spec_id numeric suffix. Registry has 'spec_next' and 'spec_max'."""
    next_val = registry.get("spec_next", 1)
    max_val = registry.get("spec_max", 0)
    if next_val <= max_val:
        next_val = max_val + 1
    registry["spec_next"] = next_val + 1
    registry["spec_max"] = max(next_val, max_val)
    return f"{SPEC_ID_LETTER}{next_val}"


def assign_deterministic_ids(
    headers: list[str],
    rows: list[dict[str, str]],
    registry_path: Path,
    project_root: Path,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Assign spec_ids using fingerprint-based registry. Preserve existing valid IDs.

    Args:
        headers: Column names (must include spec_id after append_missing_columns).
        rows: Row dicts.
        registry_path: Path to id_registry.json (relative to project_root if not absolute).
        project_root: Project root for resolving relative registry path.

    Returns:
        Tuple of (rows with spec_id filled, updated registry dict).
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

    fingerprints: dict[str, str] = registry.get("spec_fingerprints", {})
    if not isinstance(fingerprints, dict):
        fingerprints = {}
    spec_next = registry.get("spec_next", 1)
    spec_max = registry.get("spec_max", 0)
    for fid, sid in fingerprints.items():
        n = _parse_spec_id(sid)
        if n is not None and n > spec_max:
            spec_max = n
    registry["spec_next"] = spec_next
    registry["spec_max"] = spec_max
    registry["spec_fingerprints"] = fingerprints

    spec_id_col = "spec_id"
    new_rows: list[dict[str, str]] = []
    for row in rows:
        r = dict(row)
        existing = r.get(spec_id_col, "").strip()
        if existing and SPEC_ID_PATTERN.match(existing):
            r[spec_id_col] = existing
            fp = _spec_fingerprint(r, headers)
            fp_hash = hashlib.sha256(fp.encode("utf-8")).hexdigest()
            fingerprints[fp_hash] = existing
            n = _parse_spec_id(existing)
            if n is not None and n > spec_max:
                spec_max = n
            registry["spec_max"] = spec_max
        else:
            fp = _spec_fingerprint(r, headers)
            fp_hash = hashlib.sha256(fp.encode("utf-8")).hexdigest()
            if fp_hash in fingerprints:
                r[spec_id_col] = fingerprints[fp_hash]
            else:
                sid = _next_spec_id(registry)
                fingerprints[fp_hash] = sid
                r[spec_id_col] = sid
        new_rows.append(r)

    registry["spec_fingerprints"] = fingerprints
    return new_rows, registry


def assign_sads_deterministic_ids(
    headers: list[str],
    rows: list[dict[str, str]],
    registry_path: Path,
    project_root: Path,
) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any]]:
    """Assign spec_ids to SADS rows using srs_id|sads_id|requirement fingerprint.

    Always assigns new spec_ids (does not preserve existing). Builds ID mapping
    for by_sads_id and by_srs_id.

    Args:
        headers: Column names (must include SRS ID, SADS ID, requirement/SADS).
        rows: Row dicts (SADS rows only, after flatten).
        registry_path: Path to id_registry.json.
        project_root: Project root for resolving relative paths.

    Returns:
        Tuple of (rows with spec_id filled, updated registry, id_mapping dict).
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

    fingerprints: dict[str, str] = registry.get("spec_fingerprints", {})
    if not isinstance(fingerprints, dict):
        fingerprints = {}
    spec_max = registry.get("spec_max", 0)
    for _fid, sid in fingerprints.items():
        n = _parse_spec_id(sid)
        if n is not None and n > spec_max:
            spec_max = n
    registry["spec_max"] = spec_max

    srs_id_col = _find_column(headers, ["SRS ID", "srs_id", "SRS_ID"])
    sads_id_col = _find_column(headers, ["SADS ID", "sads_id", "SADS_ID"])
    spec_id_col = "spec_id"

    by_sads_id: dict[str, dict[str, str]] = {}
    by_srs_id: dict[str, list[str]] = {}

    new_rows: list[dict[str, str]] = []
    for row in rows:
        r = dict(row)
        fp = _sads_spec_fingerprint(r, headers)
        fp_hash = hashlib.sha256(fp.encode("utf-8")).hexdigest()

        if fp_hash in fingerprints:
            sid = fingerprints[fp_hash]
        else:
            sid = _next_spec_id(registry)
            fingerprints[fp_hash] = sid
        r[spec_id_col] = sid

        sads_id = r.get(sads_id_col or "", "").strip()
        srs_id = r.get(srs_id_col or "", "").strip()
        by_sads_id[sads_id] = {"spec_id": sid, "srs_id": srs_id}
        by_srs_id.setdefault(srs_id, []).append(sid)

        new_rows.append(r)

    registry["spec_fingerprints"] = fingerprints
    id_mapping: dict[str, Any] = {"by_sads_id": by_sads_id, "by_srs_id": by_srs_id}
    return new_rows, registry, id_mapping


def write_id_mapping(
    id_mapping: dict[str, Any],
    mapping_path: Path,
    project_root: Path,
    *,
    dry_run: bool = False,
) -> None:
    """Persist SADS ID mapping to JSON file.

    Args:
        id_mapping: Dict with by_sads_id and by_srs_id.
        mapping_path: Path to mapping file (relative to project_root if not absolute).
        project_root: Project root for resolving relative path.
        dry_run: If True, do not write to disk.
    """
    if dry_run:
        return
    resolved = mapping_path if mapping_path.is_absolute() else (project_root / mapping_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(id_mapping, indent=2), encoding="utf-8")


def normalize_newlines_in_cells(
    headers: list[str],
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Replace newlines in cell values with space so each row is a single CSV line.

    Prevents embedded newlines (e.g. from XLSX) from producing extra blank lines
    in the output CSV.
    """
    result: list[dict[str, str]] = []
    for row in rows:
        new_row: dict[str, str] = {}
        for col in headers:
            val = row.get(col, "")
            if isinstance(val, str) and ("\n" in val or "\r" in val):
                val = " ".join(val.split())
            new_row[col] = val
        result.append(new_row)
    return result


# Agent-view columns: input-only subset for map prompts (no SRS/SADS lineage, no output columns)
# Output columns (mapped_code_symbols, mapped_confidence, etc.) are produced by the agent, not consumed.
AGENT_VIEW_COLUMNS = [
    "spec_id",
    "subunit",
    "title",
    "requirement",
    "acceptance_criteria",
    "implementation_status",
]


def truncate_cell(value: str, max_chars: int) -> str:
    """Truncate cell value to max_chars. Append [truncated] when cut.

    Args:
        value: Cell value to truncate.
        max_chars: Max character count (0 = no limit).

    Returns:
        Truncated string, or original if max_chars <= 0 or value is short enough.
    """
    if max_chars <= 0 or not isinstance(value, str):
        return value if isinstance(value, str) else ""
    val = str(value)
    if len(val) <= max_chars:
        return val
    return val[: max_chars - len("[truncated]")] + "[truncated]"


def build_agent_view_csv_content(
    headers: list[str],
    rows: list[dict[str, str]],
    *,
    columns: list[str] | None = None,
    max_acceptance_chars: int = 0,
    extra_columns: list[str] | None = None,
) -> str:
    """Build agent-view CSV content from headers and rows.

    Extracts only the specified columns (default AGENT_VIEW_COLUMNS).
    Optionally truncates acceptance_criteria when max_acceptance_chars > 0.
    extra_columns are appended after the base columns if present in headers.

    Args:
        headers: Column names.
        rows: Row dicts.
        columns: Columns to include (default AGENT_VIEW_COLUMNS).
        max_acceptance_chars: Truncate acceptance_criteria to this many chars (0 = no limit).
        extra_columns: Additional columns to include after the base columns.

    Returns:
        CSV content string.
    """
    cols = list(columns or AGENT_VIEW_COLUMNS)
    if extra_columns:
        for ec in extra_columns:
            if ec not in cols:
                cols.append(ec)
    header_lower = {h.strip().lower(): h for h in headers if h}
    agent_headers: list[str] = []
    for col in cols:
        key = col.strip().lower()
        if key in header_lower:
            agent_headers.append(header_lower[key])
    if not agent_headers:
        return ""
    ac_col = header_lower.get("acceptance_criteria")
    out_rows: list[dict[str, str]] = []
    for row in rows:
        out_row: dict[str, str] = {}
        for h in agent_headers:
            val = row.get(h, "")
            if ac_col and h == ac_col and max_acceptance_chars > 0:
                val = truncate_cell(val, max_acceptance_chars)
            out_row[h] = val if isinstance(val, str) else str(val)
        out_rows.append(out_row)
    return rows_to_csv(agent_headers, out_rows)


def write_agent_view_csv(
    design_path: Path,
    output_path: Path,
    *,
    dry_run: bool = False,
) -> str:
    """Create agent-view CSV from design spec. Overwrites output_path.

    Extracts only agent-relevant columns (spec_id, title, requirement, mapping
    columns, etc.), dropping source lineage (SRS ID, SADS ID, UNIT, SADS, KEY).
    Used by map and implement commands to reduce prompt size.

    Args:
        design_path: Path to Formatted SADS (CSV or XLSX).
        output_path: Path to write agent-view CSV. Overwritten on each run.
        dry_run: If True, do not write to disk.

    Returns:
        CSV content string that would be (or was) written.
    """
    headers, rows = load_sads_csv_or_xlsx(design_path)
    header_lower = {h.strip().lower(): h for h in headers if h}
    agent_headers: list[str] = []
    for col in AGENT_VIEW_COLUMNS:
        key = col.strip().lower()
        if key in header_lower:
            agent_headers.append(header_lower[key])
    if not agent_headers:
        return ""
    content = rows_to_csv(agent_headers, rows)
    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
    return content


def rows_to_csv(headers: list[str], rows: list[dict[str, str]]) -> str:
    """Serialize headers and rows to CSV string.

    Converts non-ASCII Unicode in cell values to LaTeX escapes for ASCII-safe
    output. Uses lineterminator='\\n' so that when written via write_text() on
    Windows, Python's text-mode newline translation converts \\n to \\r\\n
    correctly. The default csv lineterminator '\\r\\n' would be double-translated
    on Windows, producing \\r\\r\\n and blank lines between rows.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=headers,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        out_row = {
            h: _unicode_to_latex(row.get(h, ""))
            for h in headers
        }
        writer.writerow(out_row)
    return buf.getvalue()


def normalize_raw_sads(
    source_path: Path,
    config: dict[str, Any],
    project_root: Path,
    *,
    dry_run: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Full deterministic normalization: load, flatten (if SADS format), replace
    keywords, append columns, assign IDs, persist ID mapping.

    Pipeline:
    1. Load Raw SADS (CSV/XLSX)
    2. If SADS format (SADS ID column + matching rows): flatten (forward-fill
       SRS ID/SRS, filter to SADS rows), derive title/requirement
    3. Keyword replacement (before fingerprinting)
    4. Append missing contract columns
    5. Assign deterministic spec_ids (SADS fingerprint or standard)
    6. Persist registry and ID mapping (if SADS format)

    Args:
        source_path: Path to Raw SADS (CSV or XLSX).
        config: Full PIKA config.
        project_root: Project root path.
        dry_run: If True, do not persist ID registry or mapping to disk.

    Returns:
        Tuple of (CSV content of Draft Formatted SADS, format log dict).
    """
    log: dict[str, Any] = {
        "source_path": str(source_path),
        "keyword_replacements": 0,
        "columns_appended": [],
        "ids_assigned": 0,
        "ids_preserved": 0,
        "sads_format": False,
    }

    headers, rows = load_sads_csv_or_xlsx(source_path)
    log["input_rows"] = len(rows)
    log["input_columns"] = list(headers)

    # 1. Flatten and derive if SADS format (Sample-Spec structure)
    sads_format = _is_sads_format(headers, rows)
    log["sads_format"] = sads_format
    if sads_format:
        headers, rows = flatten_sads_rows(headers, rows)
        headers, rows = derive_contract_columns(headers, rows)
        log["rows_after_flatten"] = len(rows)

    # 2. Keyword replacement (before fingerprinting)
    mappings: list[_KeywordMapping] = []
    cmd_format = config.get("commands", {}).get("format")
    if isinstance(cmd_format, dict):
        kw = cmd_format.get("sensitive_keywords")
        if isinstance(kw, dict):
            mappings = _normalize_sensitive_keywords(kw)
    rows = apply_keyword_replacement(headers, rows, mappings)
    log["keyword_replacements"] = sum(len(kd) for kd, _ in mappings)

    # 3. Collapse empty columns between existing and new to at most 2
    headers = collapse_empty_columns_before_new(headers)

    # 4. Append missing columns (config is single source of truth)
    add_if_missing = get_design_spec_add_if_missing(config)
    existing_before = set(headers)
    headers, rows = append_missing_columns(headers, rows, add_if_missing)
    log["columns_appended"] = [c for c in add_if_missing if c not in existing_before]

    # 5. Deterministic IDs
    from core.pika_config import get_pika_config

    default_outputs = get_pika_config().get("default_outputs", {})
    registry_path_str = default_outputs.get("id_registry", "out/state/id_registry.json")
    id_gen = config.get("id_generation", {})
    if isinstance(id_gen, dict):
        rp = id_gen.get("registry_path")
        if isinstance(rp, str) and rp.strip():
            registry_path_str = rp.strip()
    registry_path = Path(registry_path_str)

    if sads_format:
        rows_before = 0
        rows, registry, id_mapping = assign_sads_deterministic_ids(
            headers, rows, registry_path, project_root
        )
        log["ids_assigned"] = len(rows)
        log["ids_preserved"] = 0

        # 6. Persist registry and ID mapping: write to out/state first, then copy to project.state
        if not dry_run:
            from core.lifecycle import resolve_project_state_path

            # Write registry to out/state (id_generation.registry_path)
            resolved_registry = registry_path if registry_path.is_absolute() else (project_root / registry_path)
            resolved_registry.parent.mkdir(parents=True, exist_ok=True)
            resolved_registry.write_text(json.dumps(registry, indent=2), encoding="utf-8")
            state_registry = resolve_project_state_path(config, project_root, "id_registry_path")
            if state_registry is not None and state_registry != resolved_registry:
                state_registry.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(resolved_registry, state_registry)

            # Write mapping to out/state first
            mapping_out_state = default_outputs.get(
                "sads_id_mapping", "out/state/sads_id_mapping.json"
            )
            mapping_out_path = Path(mapping_out_state) if isinstance(mapping_out_state, str) else Path("out/state/sads_id_mapping.json")
            write_id_mapping(id_mapping, mapping_out_path, project_root, dry_run=dry_run)
            # Copy to project.state.sads_id_mapping_path
            state_mapping = resolve_project_state_path(config, project_root, "sads_id_mapping_path")
            if state_mapping is not None:
                resolved_mapping = mapping_out_path if mapping_out_path.is_absolute() else (project_root / mapping_out_path)
                if state_mapping != resolved_mapping and resolved_mapping.exists():
                    state_mapping.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(resolved_mapping, state_mapping)
    else:
        rows_before = sum(
            1
            for r in rows
            if r.get("spec_id", "").strip() and SPEC_ID_PATTERN.match(r.get("spec_id", "").strip())
        )
        rows, registry = assign_deterministic_ids(headers, rows, registry_path, project_root)
        ids_assigned = sum(1 for r in rows if r.get("spec_id", "").strip())
        log["ids_assigned"] = ids_assigned - rows_before
        log["ids_preserved"] = rows_before

        if not dry_run:
            from core.lifecycle import resolve_project_state_path

            resolved_registry = registry_path if registry_path.is_absolute() else (project_root / registry_path)
            resolved_registry.parent.mkdir(parents=True, exist_ok=True)
            resolved_registry.write_text(json.dumps(registry, indent=2), encoding="utf-8")
            state_registry = resolve_project_state_path(config, project_root, "id_registry_path")
            if state_registry is not None and state_registry != resolved_registry:
                state_registry.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(resolved_registry, state_registry)

    # Normalize newlines in cells so each row is a single CSV line
    rows = normalize_newlines_in_cells(headers, rows)

    csv_content = rows_to_csv(headers, rows)
    log["output_rows"] = len(rows)
    log["output_columns"] = list(headers)
    return csv_content, log
