"""Contract definitions parsed from docs (single source of truth).

CSV column rules are read from docs/csv_contracts.md.
PROJECT_CONTEXT section rules are read from docs/project_context_contracts.md.
These docs are PIKA-internal (project-independent) and live under PIKA root.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.pika_paths import get_csv_contracts_path, get_project_context_contracts_path

# Path names for error messages (docs live under PIKA root)
_CONTRACTS_DOC_NAME = "docs/csv_contracts.md"
_PROJECT_CONTEXT_CONTRACTS_DOC_NAME = "docs/project_context_contracts.md"

# Section headings in docs/csv_contracts.md
_DESIGN_SPEC_SECTION = "Design Spec (SADS) Table Contract"
_ISSUE_TRACKING_SECTION = "Implementation Issue Tracking Table Contract"

# Section heading in docs/project_context_contracts.md
_PROJECT_CONTEXT_REQUIRED_SECTIONS = "Required Sections"




def _extract_markdown_section(lines: list[str], heading: str) -> list[str]:
    """Extract lines between a ## heading and the next ## heading."""
    start: int | None = None
    heading_pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$")
    for idx, line in enumerate(lines):
        if heading_pattern.match(line.strip()):
            start = idx + 1
            break
    if start is None:
        return []
    end = len(lines)
    for idx in range(start, len(lines)):
        if lines[idx].strip().startswith("## "):
            end = idx
            break
    return lines[start:end]


def _parse_table_rows_with_required(
    section_lines: list[str],
    *,
    name_col: int = 0,
    required_col: int = 1,
) -> tuple[tuple[str, ...], ...]:
    """Parse markdown table, return (column_names, required_names).

    Table format: | Column | Required | ... |
    Returns (all_column_names, required_column_names) where required_column_names
    are those with Required=Yes.
    """
    all_columns: list[str] = []
    required_columns: list[str] = []

    for line in section_lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.split("|")[1:-1]]
        if not cells:
            continue
        # Skip header and separator rows
        if cells[0].lower() == "column" or set(cells[0]) == {"-"}:
            continue
        col_name = cells[name_col] if name_col < len(cells) else ""
        req_val = cells[required_col] if required_col < len(cells) else ""
        if col_name:
            all_columns.append(col_name)
            if req_val and req_val.lower() == "yes":
                required_columns.append(col_name)

    return (tuple(all_columns), tuple(required_columns))


def _load_contracts_doc() -> list[str]:
    """Load CSV contracts doc from PIKA root. Raises if not found."""
    path = get_csv_contracts_path()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(
            f"Contract document not found: {path}. "
            "Ensure docs/csv_contracts.md exists under PIKA root."
        )
    return path.read_text(encoding="utf-8").splitlines()


def _load_project_context_contracts_doc() -> list[str]:
    """Load PROJECT_CONTEXT contracts doc from PIKA root. Raises if not found."""
    path = get_project_context_contracts_path()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(
            f"Contract document not found: {path}. "
            "Ensure docs/project_context_contracts.md exists under PIKA root."
        )
    return path.read_text(encoding="utf-8").splitlines()


def get_design_spec_required_columns() -> tuple[str, ...]:
    """Return required columns for Design Spec from docs/csv_contracts.md (PIKA root)."""
    lines = _load_contracts_doc()
    section = _extract_markdown_section(lines, _DESIGN_SPEC_SECTION)
    _, required = _parse_table_rows_with_required(section)
    if not required:
        raise ValueError(
            f"No required columns found in {_DESIGN_SPEC_SECTION}. "
            f"Check {_CONTRACTS_DOC_NAME} table format."
        )
    return required


def get_issue_tracking_required_columns() -> tuple[str, ...]:
    """Return required columns for Issue Tracking from docs/csv_contracts.md (PIKA root)."""
    lines = _load_contracts_doc()
    section = _extract_markdown_section(lines, _ISSUE_TRACKING_SECTION)
    _, required = _parse_table_rows_with_required(section)
    if not required:
        raise ValueError(
            f"No required columns found in {_ISSUE_TRACKING_SECTION}. "
            f"Check {_CONTRACTS_DOC_NAME} table format."
        )
    return required


def get_design_spec_column_definitions() -> str:
    """Return Design Spec column definitions as text for agent prompts.

    Parses the Design Spec (SADS) table from docs/csv_contracts.md and returns
    a formatted string with column name, required/optional, and meaning.
    Used by map and implement commands to inject column semantics into prompts.

    Returns:
        Formatted string suitable for design_spec_column_definitions template var.
    """
    lines = _load_contracts_doc()
    section = _extract_markdown_section(lines, _DESIGN_SPEC_SECTION)
    # Table format: | Column | Required | Added if Missing | Meaning |
    parts: list[str] = []
    for line in section:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.split("|")[1:-1]]
        if len(cells) < 4:
            continue
        col_name = cells[0]
        if col_name.lower() == "column" or set(col_name) == {"-"}:
            continue
        required = cells[1]
        added = cells[2]
        meaning = cells[3]
        req_str = "required" if required.lower() == "yes" else "optional"
        parts.append(f"- {col_name} ({req_str}): {meaning}")
    return "\n".join(parts) if parts else ""


def get_project_context_required_sections() -> tuple[str, ...]:
    """Return required section names for PROJECT_CONTEXT.md from docs/project_context_contracts.md.

    Section names are matched case-insensitively against headings.
    Returns e.g. ('purpose', 'overview', 'workflow').
    Contract doc is read from PIKA root.
    """
    lines = _load_project_context_contracts_doc()
    section = _extract_markdown_section(lines, _PROJECT_CONTEXT_REQUIRED_SECTIONS)
    # Table: | Section | Required | Meaning |
    _, required = _parse_table_rows_with_required(
        section,
        name_col=0,
        required_col=1,
    )
    if not required:
        raise ValueError(
            f"No required sections found in {_PROJECT_CONTEXT_REQUIRED_SECTIONS}. "
            f"Check {_PROJECT_CONTEXT_CONTRACTS_DOC_NAME} table format."
        )
    return tuple(s.lower() for s in required)
